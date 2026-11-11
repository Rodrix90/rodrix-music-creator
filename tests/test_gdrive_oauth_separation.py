import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

os.environ.setdefault("UDIO_API_KEY", "test_key_redacted_0000")

import app

_REAL_HTTPX_ASYNC_CLIENT = httpx.AsyncClient


class _MockResponse:
    def __init__(self, status_code=200, json_data=None, text=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        if text is not None:
            self.text = text
        elif json_data is not None:
            self.text = json.dumps(json_data)
        else:
            self.text = ""
        self.content = content if content else self.text.encode("utf-8")

    def json(self):
        if self._json is not None:
            return self._json
        return json.loads(self.text or "{}")


class _RejectRealNetworkAsyncClient:
    """Garantiza cero llamadas reales de red salientes cuando un test no provee su propio mock."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def _fail(self, method, url, *args, **kwargs):
        raise AssertionError(f"Llamada de red real bloqueada en test: {method} {url}")

    async def get(self, url, *args, **kwargs):
        return await self._fail("GET", url)

    async def post(self, url, *args, **kwargs):
        return await self._fail("POST", url)

    async def put(self, url, *args, **kwargs):
        return await self._fail("PUT", url)

    async def patch(self, url, *args, **kwargs):
        return await self._fail("PATCH", url)


class TestGDriveOAuthSeparation(unittest.IsolatedAsyncioTestCase):
    """
    Pruebas integrales (0 créditos, 0 llamadas reales a UdioAPI/Google)
    para la separación estricta entre autenticación de usuario y tokens OAuth de Google Drive.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_attrs = {
            "GDRIVE_TOKEN_FILE": app.GDRIVE_TOKEN_FILE,
            "USERS_FILE": app.USERS_FILE,
            "LIBRARY_FILE": app.LIBRARY_FILE,
            "DELETED_TRACKS_FILE": app.DELETED_TRACKS_FILE,
            "GENERATION_TASKS_FILE": app.GENERATION_TASKS_FILE,
            "TRACKS_DIR": app.TRACKS_DIR,
            "library_lock": app.library_lock,
            "users_lock": app.users_lock,
            "deleted_tracks_lock": app.deleted_tracks_lock,
            "_in_flight_lock": app._in_flight_lock,
        }
        self.orig_env = {
            "RODRIX_DB_PATH": os.environ.get("RODRIX_DB_PATH"),
            "GOOGLE_DRIVE_REFRESH_TOKEN": os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN"),
            "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET"),
            "RODRIX_DISABLE_GDRIVE_NETWORK": os.environ.get("RODRIX_DISABLE_GDRIVE_NETWORK"),
        }

        self.token_file = os.path.join(self.tmpdir.name, "gdrive_token.json")
        self.users_file = os.path.join(self.tmpdir.name, "users.json")
        self.lib_file = os.path.join(self.tmpdir.name, "library.json")
        self.deleted_file = os.path.join(self.tmpdir.name, "deleted_tracks.json")
        self.tasks_file = os.path.join(self.tmpdir.name, "generation_tasks.json")
        self.tracks_dir = os.path.join(self.tmpdir.name, "tracks_storage")
        self.db_file = os.path.join(self.tmpdir.name, "rodrix_test.db")
        os.makedirs(self.tracks_dir, exist_ok=True)

        app.GDRIVE_TOKEN_FILE = self.token_file
        app.USERS_FILE = self.users_file
        app.LIBRARY_FILE = self.lib_file
        app.DELETED_TRACKS_FILE = self.deleted_file
        app.GENERATION_TASKS_FILE = self.tasks_file
        app.TRACKS_DIR = self.tracks_dir
        app.library_lock = asyncio.Lock()
        app.users_lock = asyncio.Lock()
        app.deleted_tracks_lock = asyncio.Lock()
        app._in_flight_lock = asyncio.Lock()
        os.environ["RODRIX_DB_PATH"] = self.db_file
        os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"] = "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"
        os.environ["GOOGLE_CLIENT_SECRET"] = "GOCSPX-TEST_CLIENT_SECRET_1234567890"
        os.environ.pop("RODRIX_DISABLE_GDRIVE_NETWORK", None)

        with app._transactional_db():
            pass

        app.LAST_GDRIVE_ERROR.update({"error": None, "timestamp": None})
        app.LAST_GDRIVE_TOKEN_INFO.update({
            "token_origin": None,
            "has_drive_scope": False,
            "drive_permissions_verified": False,
            "token_expires_at": None,
            "refresh_source": None,
            "scope": None,
            "verified_at": None,
        })
        app.app.dependency_overrides.clear()

        self._net_patch = patch.object(app.httpx, "AsyncClient", _RejectRealNetworkAsyncClient)
        self._net_patch.start()

    async def asyncTearDown(self):
        # Drenar cualquier tarea asyncio en segundo plano creada por save_users/callbacks antes de restaurar locks
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def tearDown(self):
        self._net_patch.stop()
        app.app.dependency_overrides.clear()
        for attr, val in self.orig_attrs.items():
            setattr(app, attr, val)
        for key, val in self.orig_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        app.LAST_GDRIVE_ERROR.update({"error": None, "timestamp": None})
        self.tmpdir.cleanup()

    def _write_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _read_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _make_fake_oauth_google(self, redirect_fn=None, token_return=None):
        fake = MagicMock()
        if redirect_fn is not None:
            fake.authorize_redirect = AsyncMock(side_effect=redirect_fn)
        else:
            fake.authorize_redirect = AsyncMock()
        if token_return is not None:
            fake.authorize_access_token = AsyncMock(return_value=token_return)
        else:
            fake.authorize_access_token = AsyncMock()
        return fake

    async def test_01_login_via_google_requests_only_identity_scope(self):
        captured = {}

        async def fake_authorize_redirect(request, redirect_uri, **kwargs):
            captured["redirect_uri"] = redirect_uri
            captured["kwargs"] = kwargs
            return app.RedirectResponse(url="https://accounts.google.com/o/oauth2/v2/auth")

        fake_google = self._make_fake_oauth_google(redirect_fn=fake_authorize_redirect)
        transport = httpx.ASGITransport(app=app.app)
        with patch.object(app.oauth, "google", fake_google, create=True):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                resp = await client.get("/api/login/google", follow_redirects=False)

        self.assertIn(resp.status_code, (302, 307))
        self.assertEqual(captured["kwargs"].get("scope"), "openid email profile")
        self.assertNotIn("drive", captured["kwargs"].get("scope", ""))

    async def test_02_admin_login_identity_token_never_overwrites_drive_token_or_refresh(self):
        drive_fp = app._refresh_token_fingerprint("1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")
        initial_tokens = {
            "refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY",
            "access_token": "ya29.DRIVE_ACCESS_TOKEN_VALID",
            "expires_at": time.time() + 3000,
            "token_origin": "drive_refresh",
            "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
            "refresh_fingerprint": drive_fp,
        }
        self._write_json(self.token_file, initial_tokens)
        self._write_json(self.users_file, {
            app.ADMIN_EMAIL: {
                "email": app.ADMIN_EMAIL,
                "name": "Rodrigo",
                "status": "active",
                "role": "admin",
                "drive_access": True,
                "permissions": {"drive_read": True, "drive_write": True},
                "created_at": "2026-01-01 00:00:00",
            }
        })

        fake_login_token = {
            "access_token": "ya29.LOGIN_IDENTITY_ONLY_NO_DRIVE",
            "refresh_token": "1//SHOULD_NEVER_OVERWRITE_DRIVE_RT",
            "expires_at": time.time() + 3600,
            "scope": "openid email profile",
            "userinfo": {
                "email": app.ADMIN_EMAIL,
                "name": "Rodrigo Admin",
                "picture": "https://example.com/pic.jpg",
            },
        }

        fake_google = self._make_fake_oauth_google(token_return=fake_login_token)
        sync_mock = AsyncMock(return_value=None)
        sync_users_mock = AsyncMock(return_value=None)
        transport = httpx.ASGITransport(app=app.app)
        with patch.object(app.oauth, "google", fake_google, create=True), \
             patch.object(app, "gdrive_sync_library_from_cloud", sync_mock), \
             patch.object(app, "gdrive_sync_users_to_cloud", sync_users_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                resp = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0)

        self.assertIn(resp.status_code, (302, 307))
        self.assertEqual(resp.headers.get("location"), "/")

        # gdrive_token.json debe permanecer idéntico y nunca recibir tokens de identidad
        stored_tokens = self._read_json(self.token_file)
        self.assertEqual(stored_tokens["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")
        self.assertEqual(stored_tokens["access_token"], "ya29.DRIVE_ACCESS_TOKEN_VALID")
        self.assertNotEqual(stored_tokens["access_token"], "ya29.LOGIN_IDENTITY_ONLY_NO_DRIVE")
        self.assertEqual(stored_tokens["token_origin"], "drive_refresh")

        # Sesión y datos de admin actualizados preservando permisos existentes
        users = self._read_json(self.users_file)
        self.assertEqual(users[app.ADMIN_EMAIL]["role"], "admin")
        self.assertEqual(users[app.ADMIN_EMAIL]["status"], "active")
        self.assertTrue(users[app.ADMIN_EMAIL]["drive_access"])
        self.assertEqual(users[app.ADMIN_EMAIL]["permissions"], {"drive_read": True, "drive_write": True})

        # Y si gdrive_get_access_token se invoca luego, devuelve el token de Drive real sin llamadas HTTP
        selected = await app.gdrive_get_access_token()
        self.assertEqual(selected, "ya29.DRIVE_ACCESS_TOKEN_VALID")

        # También si no existe gdrive_token.json previo (refresh solo en ENV), el login admin no crea token de identidad en disco
        os.remove(self.token_file)
        with patch.object(app.oauth, "google", fake_google, create=True), \
             patch.object(app, "gdrive_sync_library_from_cloud", sync_mock), \
             patch.object(app, "gdrive_sync_users_to_cloud", sync_users_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                resp2 = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0)
        self.assertIn(resp2.status_code, (302, 307))
        self.assertFalse(os.path.exists(self.token_file))

    async def test_03_legacy_and_incompatible_cached_tokens_invalidated_without_losing_refresh_token(self):
        subcases = [
            (
                "legacy_sin_origen_ni_scope",
                {
                    "refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY",
                    "access_token": "ya29.OLD_UNVERIFIED_TOKEN",
                    "expires_at": time.time() + 3500,
                },
            ),
            (
                "origen_login_y_scope_sin_drive",
                {
                    "refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY",
                    "access_token": "ya29.IDENTITY_POISONED",
                    "expires_at": time.time() + 3500,
                    "token_origin": "user_login",
                    "scope": "openid email profile",
                    "refresh_fingerprint": app._refresh_token_fingerprint("1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"),
                },
            ),
            (
                "fingerprint_de_otro_refresh_token",
                {
                    "refresh_token": "1//OTRO_RT_ANTERIOR",
                    "access_token": "ya29.STALE_OTHER_RT",
                    "expires_at": time.time() + 3500,
                    "token_origin": "drive_refresh",
                    "scope": "https://www.googleapis.com/auth/drive.file",
                    "refresh_fingerprint": app._refresh_token_fingerprint("1//OTRO_RT_ANTERIOR"),
                },
            ),
        ]

        for idx, (label, seed) in enumerate(subcases, start=1):
            with self.subTest(case=label):
                self._write_json(self.token_file, seed)
                issued_token = f"ya29.VERIFIED_DRIVE_TOKEN_{idx}"
                post_calls = []

                class FakeAsyncClient:
                    def __init__(self, *a, **kw):
                        pass

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False

                    async def post(self, url, data=None, **kw):
                        post_calls.append((url, data))
                        return _MockResponse(200, {
                            "access_token": issued_token,
                            "expires_in": 3600,
                            "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
                        })

                with patch.object(app.httpx, "AsyncClient", FakeAsyncClient):
                    tok = await app.gdrive_get_access_token()

                self.assertEqual(tok, issued_token)
                self.assertEqual(len(post_calls), 1)
                self.assertEqual(post_calls[0][1]["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")

                stored = self._read_json(self.token_file)
                self.assertEqual(stored["access_token"], issued_token)
                self.assertEqual(stored["token_origin"], "drive_refresh")
                self.assertTrue(app._has_drive_write_scope(stored["scope"]))
                self.assertEqual(
                    stored["refresh_fingerprint"],
                    app._refresh_token_fingerprint("1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"),
                )
                self.assertEqual(stored["refresh_token"], seed["refresh_token"])

    async def test_04_reuses_valid_drive_token_until_expiry_then_refreshes_and_selects_for_drive_ops(self):
        post_calls = []
        drive_headers = []
        refresh_counter = {"n": 0}

        class FakeAsyncClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, content=None, headers=None, **kw):
                if "oauth2.googleapis.com/token" in url:
                    refresh_counter["n"] += 1
                    post_calls.append(data)
                    return _MockResponse(200, {
                        "access_token": f"ya29.DRIVE_OK_{refresh_counter['n']}",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/drive.file openid",
                    })
                if "upload/drive/v3/files" in url:
                    drive_headers.append(headers.get("Authorization"))
                    return _MockResponse(200, {"id": "gdrive_file_123", "name": "test.json"})
                raise AssertionError(f"POST inesperado: {url}")

            async def get(self, url, params=None, headers=None, **kw):
                if "www.googleapis.com/drive/v3/files" in url:
                    drive_headers.append(headers.get("Authorization"))
                    return _MockResponse(200, {"files": []})
                raise AssertionError(f"GET inesperado: {url}")

        with patch.object(app.httpx, "AsyncClient", FakeAsyncClient):
            tok1 = await app.gdrive_get_access_token()
            tok2 = await app.gdrive_get_access_token()
            upload_res = await app._do_upload_or_update("probe.json", b'{"ok":true}', "application/json")

            self.assertEqual(tok1, "ya29.DRIVE_OK_1")
            self.assertEqual(tok2, "ya29.DRIVE_OK_1")
            self.assertEqual(refresh_counter["n"], 1)  # Reutilizado sin renovar innecesariamente
            self.assertIsNotNone(upload_res)
            self.assertEqual(drive_headers, ["Bearer ya29.DRIVE_OK_1", "Bearer ya29.DRIVE_OK_1"])

            # Simular expiración del access token (< 60s restantes)
            disk = self._read_json(self.token_file)
            disk["expires_at"] = time.time() + 15
            self._write_json(self.token_file, disk)

            tok3 = await app.gdrive_get_access_token()
            self.assertEqual(tok3, "ya29.DRIVE_OK_2")
            self.assertEqual(refresh_counter["n"], 2)

    async def test_05_tokeninfo_fallback_and_rejection_when_refresh_lacks_drive_scope(self):
        self._write_json(self.token_file, {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})

        class ClientWithTokenInfoConfirm:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, **kw):
                return _MockResponse(200, {"access_token": "ya29.CONFIRMED_VIA_INFO", "expires_in": 3600})

            async def get(self, url, params=None, **kw):
                return _MockResponse(200, {"scope": "openid email https://www.googleapis.com/auth/drive.file"})

        with patch.object(app.httpx, "AsyncClient", ClientWithTokenInfoConfirm):
            tok_ok = await app.gdrive_get_access_token()
        self.assertEqual(tok_ok, "ya29.CONFIRMED_VIA_INFO")
        self.assertTrue(app.LAST_GDRIVE_TOKEN_INFO["drive_permissions_verified"])

        # Caso B: /token devuelve scope sin permiso Drive -> rechazado, refresh_token intacto
        self._write_json(self.token_file, {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})

        class ClientNoDriveScope:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, **kw):
                return _MockResponse(200, {
                    "access_token": "ya29.ONLY_IDENTITY_TOKEN",
                    "expires_in": 3600,
                    "scope": "openid email profile",
                })

        with patch.object(app.httpx, "AsyncClient", ClientNoDriveScope):
            tok_bad = await app.gdrive_get_access_token()

        self.assertIsNone(tok_bad)
        self.assertFalse(app.LAST_GDRIVE_TOKEN_INFO["drive_permissions_verified"])
        self.assertIn("ACCESS_TOKEN_SCOPE_INSUFFICIENT", app.LAST_GDRIVE_ERROR["error"] or "")
        stored_after = self._read_json(self.token_file)
        self.assertNotIn("access_token", stored_after)
        self.assertEqual(stored_after["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")

    async def test_06_safe_401_and_403_handling_and_zero_secret_leakage(self):
        drive_fp = app._refresh_token_fingerprint("1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")
        self._write_json(self.token_file, {
            "refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY",
            "access_token": "ya29.CACHED_TO_INVALIDATE",
            "expires_at": time.time() + 3600,
            "token_origin": "drive_refresh",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "refresh_fingerprint": drive_fp,
        })

        # 6A: Drive API responde 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT -> invalida cache, conserva refresh_token
        class Drive403Client:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return _MockResponse(
                    403,
                    text='{"error":{"code":403,"message":"ACCESS_TOKEN_SCOPE_INSUFFICIENT","secret":"GOCSPX-DO_NOT_LEAK_ME_99999","token":"ya29.SECRET_LEAK_ATTEMPT"}}',
                )

        with patch.object(app.httpx, "AsyncClient", Drive403Client):
            res = await app.gdrive_find_file("library.json")

        self.assertIsNone(res)
        after_403 = self._read_json(self.token_file)
        self.assertNotIn("access_token", after_403)
        self.assertEqual(after_403["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")
        self.assertNotIn("GOCSPX-DO_NOT_LEAK_ME", app.LAST_GDRIVE_ERROR["error"])
        self.assertNotIn("ya29.SECRET_LEAK_ATTEMPT", app.LAST_GDRIVE_ERROR["error"])

        # 6B: OAuth /token responde 401 y luego 403 -> manejo seguro y sin secretos expuestos
        for status_code in (401, 403):
            self._write_json(self.token_file, {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})

            class OAuthErrorClient:
                def __init__(self, *a, **kw):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def post(self, url, **kw):
                    return _MockResponse(
                        status_code,
                        text=f'{{"error":"unauthorized_client","refresh_token":"1//SECRET_RT_LEAK_{status_code}","client_secret":"GOCSPX-SECRET_{status_code}"}}',
                    )

            with patch.object(app.httpx, "AsyncClient", OAuthErrorClient):
                tok = await app.gdrive_get_access_token()

            self.assertIsNone(tok)
            self.assertIn(f"HTTP {status_code}", app.LAST_GDRIVE_ERROR["error"])
            self.assertNotIn(f"1//SECRET_RT_LEAK_{status_code}", app.LAST_GDRIVE_ERROR["error"])
            self.assertNotIn(f"GOCSPX-SECRET_{status_code}", app.LAST_GDRIVE_ERROR["error"])
            stored = self._read_json(self.token_file)
            self.assertEqual(stored["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")

    async def test_07_admin_gdrive_callback_verifies_scope_and_rejects_non_drive_or_non_admin(self):
        self._write_json(self.token_file, {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})
        transport = httpx.ASGITransport(app=app.app)

        # 7A: Usuario normal rechazado (403)
        fake_non_admin = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.USER_ATTACK",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "userinfo": {"email": "otro@example.com"},
        })
        with patch.object(app.oauth, "google", fake_non_admin, create=True):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_non_admin = await client.get("/api/admin/gdrive/callback", follow_redirects=False)
        self.assertEqual(r_non_admin.status_code, 403)

        # 7B: Admin sin permiso Drive concedido rechazado (403), refresh_token intacto
        class TokenInfoNoDrive:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return _MockResponse(200, {"scope": "openid email profile"})

        fake_no_drive = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.ADMIN_DENIED_DRIVE_CHECKBOX",
            "scope": "openid email profile",
            "userinfo": {"email": app.ADMIN_EMAIL},
        })
        with patch.object(app.oauth, "google", fake_no_drive, create=True), \
             patch.object(app.httpx, "AsyncClient", TokenInfoNoDrive):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_no_scope = await client.get("/api/admin/gdrive/callback", follow_redirects=False)
        self.assertEqual(r_no_scope.status_code, 403)
        self.assertNotIn("access_token", self._read_json(self.token_file))

        # 7C: Admin con permiso Drive verificado se guarda con token_origin='admin_gdrive_link'
        sync_mock = AsyncMock(return_value=None)
        fake_ok_drive = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.ADMIN_VERIFIED_DRIVE",
            "expires_at": time.time() + 3600,
            "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
            "userinfo": {"email": app.ADMIN_EMAIL},
        })
        with patch.object(app.oauth, "google", fake_ok_drive, create=True), \
             patch.object(app, "gdrive_sync_library_from_cloud", sync_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_ok = await client.get("/api/admin/gdrive/callback", follow_redirects=False)
                await asyncio.sleep(0)

        self.assertIn(r_ok.status_code, (302, 307))
        self.assertEqual(r_ok.headers.get("location"), "/?gdrive_linked=success")
        stored_ok = self._read_json(self.token_file)
        self.assertEqual(stored_ok["token_origin"], "admin_gdrive_link")
        self.assertEqual(stored_ok["access_token"], "ya29.ADMIN_VERIFIED_DRIVE")
        self.assertTrue(app._has_drive_write_scope(stored_ok["scope"]))
        self.assertEqual(stored_ok["refresh_token"], "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY")

    async def test_08_health_and_admin_diagnostic_require_verified_permissions_without_secret_exposure(self):
        os.environ["RODRIX_DISABLE_GDRIVE_NETWORK"] = "1"
        app.app.dependency_overrides[app.get_current_user] = lambda: app.ADMIN_EMAIL
        transport = httpx.ASGITransport(app=app.app)

        # Con red deshabilitada y sin token verificado: oauth_working y drive_permissions_verified en False
        async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
            h_res = await client.get("/api/health")
            d_res = await client.get("/api/admin/gdrive-diagnostic")

        self.assertEqual(h_res.status_code, 200)
        self.assertEqual(d_res.status_code, 200)
        h_json = h_res.json()
        d_json = d_res.json()
        self.assertFalse(h_json["gdrive"]["oauth_working"])
        self.assertFalse(h_json["gdrive"]["drive_permissions_verified"])
        self.assertFalse(d_json["auth_working"])
        self.assertFalse(d_json["drive_permissions_verified"])

        # Incluso si gdrive_get_access_token devolviera una cadena sin metadatos verificados de Drive, NO se asume oauth_working=True
        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="ya29.UNVERIFIED_MOCK")):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                h_unv = await client.get("/api/health")
                d_unv = await client.get("/api/admin/gdrive-diagnostic")
        self.assertFalse(h_unv.json()["gdrive"]["oauth_working"])
        self.assertFalse(h_unv.json()["gdrive"]["drive_permissions_verified"])
        self.assertFalse(d_unv.json()["auth_working"])
        self.assertFalse(d_unv.json()["drive_permissions_verified"])

        # Con token verificado vía refresh real mockeado
        os.environ.pop("RODRIX_DISABLE_GDRIVE_NETWORK", None)

        class RefreshOkClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kw):
                return _MockResponse(200, {
                    "access_token": "ya29.DIAGNOSTIC_VERIFIED_TOKEN",
                    "expires_in": 3600,
                    "scope": "openid https://www.googleapis.com/auth/drive.file",
                })

        with patch.object(app.httpx, "AsyncClient", RefreshOkClient):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                h_ok = await client.get("/api/health")
                d_ok = await client.get("/api/admin/gdrive-diagnostic")
                s_ok = await client.get("/api/gdrive/status")

        hj = h_ok.json()
        dj = d_ok.json()
        sj = s_ok.json()
        self.assertTrue(hj["gdrive"]["oauth_working"])
        self.assertTrue(hj["gdrive"]["drive_permissions_verified"])
        self.assertTrue(hj["gdrive"]["has_drive_scope"])
        self.assertEqual(hj["gdrive"]["token_origin"], "drive_refresh")
        self.assertEqual(hj["gdrive"]["refresh_source"], "env:GOOGLE_DRIVE_REFRESH_TOKEN")

        self.assertTrue(dj["auth_working"])
        self.assertTrue(dj["drive_permissions_verified"])
        self.assertTrue(dj["has_drive_scope"])
        self.assertEqual(dj["token_origin"], "drive_refresh")

        self.assertTrue(sj["drive_permissions_verified"])
        self.assertTrue(sj["has_drive_scope"])

        # Ningún secreto o token debe aparecer en las respuestas
        dumped = json.dumps(hj) + json.dumps(dj) + json.dumps(sj)
        self.assertNotIn("ya29.DIAGNOSTIC_VERIFIED_TOKEN", dumped)
        self.assertNotIn("TEST_DRIVE_REFRESH_TOKEN_PRIMARY", dumped)
        self.assertNotIn("GOCSPX-", dumped)

    async def test_09_normal_users_and_existing_library_remain_intact(self):
        self._write_json(self.token_file, {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})
        existing_tracks = [
            {"id": "track-01", "title": "Cancion Uno", "gdrive_id": "gd_1", "is_permanently_saved": True, "persistence_status": "PERSISTED_GDRIVE"},
            {"id": "track-02", "title": "Cancion Dos", "gdrive_id": "gd_2", "is_permanently_saved": True, "persistence_status": "PERSISTED_GDRIVE"},
        ]
        self._write_json(self.lib_file, existing_tracks)
        self._write_json(self.users_file, {
            app.ADMIN_EMAIL: {"email": app.ADMIN_EMAIL, "role": "admin", "status": "active"},
            "autorizado@example.com": {
                "email": "autorizado@example.com",
                "name": "Usuario Autorizado",
                "status": "active",
                "role": "user",
                "drive_access": True,
                "permissions": {"drive_read": True, "drive_download": True, "drive_write": False, "drive_delete": False},
            },
            "bloqueado@example.com": {
                "email": "bloqueado@example.com",
                "status": "blocked",
                "role": "user",
            },
        })

        transport = httpx.ASGITransport(app=app.app)
        sync_users_mock = AsyncMock(return_value=None)

        # 9A: Usuario normal autorizado conserva sus permisos y no toca gdrive_token.json
        fake_user_google = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.NORMAL_USER_LOGIN",
            "scope": "openid email profile",
            "userinfo": {"email": "autorizado@example.com", "name": "Usuario Autorizado Nuevo"},
        })
        with patch.object(app.oauth, "google", fake_user_google, create=True), \
             patch.object(app, "gdrive_sync_users_to_cloud", sync_users_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_user = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0)

        self.assertIn(r_user.status_code, (302, 307))
        self.assertEqual(r_user.headers.get("location"), "/")
        users_after = self._read_json(self.users_file)
        self.assertTrue(users_after["autorizado@example.com"]["drive_access"])
        self.assertTrue(users_after["autorizado@example.com"]["permissions"]["drive_download"])
        self.assertEqual(self._read_json(self.token_file), {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})

        # 9B: Usuario bloqueado continúa siendo rechazado
        fake_blocked_google = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.BLOCKED_USER",
            "scope": "openid email profile",
            "userinfo": {"email": "bloqueado@example.com", "name": "Bloqueado"},
        })
        with patch.object(app.oauth, "google", fake_blocked_google, create=True), \
             patch.object(app, "gdrive_sync_users_to_cloud", sync_users_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_blocked = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0)

        self.assertIn(r_blocked.status_code, (302, 307))
        self.assertIn("Acceso%20Bloqueado", r_blocked.headers.get("location", ""))

        # 9C: Usuario nuevo ingresa con permisos drive_access=False sin tocar Drive tokens ni biblioteca
        fake_new_google = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.NEW_USER",
            "scope": "openid email profile",
            "userinfo": {"email": "nuevo@example.com", "name": "Nuevo"},
        })
        with patch.object(app.oauth, "google", fake_new_google, create=True), \
             patch.object(app, "gdrive_sync_users_to_cloud", sync_users_mock):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                r_new = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0)

        self.assertIn(r_new.status_code, (302, 307))
        users_final = self._read_json(self.users_file)
        self.assertEqual(users_final["nuevo@example.com"]["role"], "user")
        self.assertFalse(users_final["nuevo@example.com"]["drive_access"])
        self.assertEqual(len(self._read_json(self.lib_file)), 2)
        self.assertEqual(self._read_json(self.token_file), {"refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY"})

    async def test_10_admin_login_plus_cloud_sync_uses_drive_token_and_preserves_two_tracks(self):
        # Escenario end-to-end: cache heredado sin metadatos + login admin con token openid + sincronización real simulada
        self._write_json(self.token_file, {
            "refresh_token": "1//TEST_DRIVE_REFRESH_TOKEN_PRIMARY",
            "access_token": "ya29.LEGACY_IDENTITY_CACHE",
            "expires_at": time.time() + 3600,
        })
        two_tracks = [
            {"id": "track-a", "title": "Himno Original A", "gdrive_id": "gd_a", "is_permanently_saved": True, "persistence_status": "PERSISTED_GDRIVE"},
            {"id": "track-b", "title": "Himno Original B", "gdrive_id": "gd_b", "is_permanently_saved": True, "persistence_status": "PERSISTED_GDRIVE"},
        ]
        self._write_json(self.lib_file, two_tracks)

        used_auth_headers = []

        class DriveAndOAuthMockClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, **kw):
                if "oauth2.googleapis.com/token" in url:
                    return _MockResponse(200, {
                        "access_token": "ya29.REAL_DRIVE_TOKEN_AFTER_ADMIN_LOGIN",
                        "expires_in": 3600,
                        "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
                    })
                raise AssertionError(f"POST inesperado: {url}")

            async def patch(self, url, headers=None, **kw):
                used_auth_headers.append((url, (headers or {}).get("Authorization")))
                return _MockResponse(200, {"id": "cloud_users_id"})

            async def get(self, url, headers=None, **kw):
                used_auth_headers.append((url, (headers or {}).get("Authorization")))
                if "alt=media" in url:
                    return _MockResponse(200, json_data=two_tracks, content=json.dumps(two_tracks).encode("utf-8"))
                if "drive/v3/files" in url:
                    return _MockResponse(200, {"files": [{"id": "cloud_lib_id", "name": "library.json"}]})
                raise AssertionError(f"GET inesperado: {url}")

        fake_google = self._make_fake_oauth_google(token_return={
            "access_token": "ya29.IDENTITY_TOKEN_FROM_LOGIN",
            "expires_at": time.time() + 3600,
            "scope": "openid email profile",
            "userinfo": {"email": app.ADMIN_EMAIL, "name": "Rodrigo"},
        })
        transport = httpx.ASGITransport(app=app.app)
        with patch.object(app.oauth, "google", fake_google, create=True), \
             patch.object(app.httpx, "AsyncClient", DriveAndOAuthMockClient):
            async with _REAL_HTTPX_ASYNC_CLIENT(transport=transport, base_url="https://rodrix.example") as client:
                resp = await client.get("/api/auth/callback", follow_redirects=False)
                await asyncio.sleep(0.05)

        self.assertIn(resp.status_code, (302, 307))
        self.assertGreaterEqual(len(used_auth_headers), 1)
        for url, auth in used_auth_headers:
            self.assertEqual(auth, "Bearer ya29.REAL_DRIVE_TOKEN_AFTER_ADMIN_LOGIN")
            self.assertNotEqual(auth, "Bearer ya29.IDENTITY_TOKEN_FROM_LOGIN")

        lib_after = self._read_json(self.lib_file)
        self.assertEqual([t["id"] for t in sorted(lib_after, key=lambda x: x["id"])], ["track-a", "track-b"])


if __name__ == "__main__":
    unittest.main()
