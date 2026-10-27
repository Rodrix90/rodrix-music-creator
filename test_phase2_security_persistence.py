"""
Test Suite Completa: Fase 2 - Seguridad y Persistencia Cloud (Ajustes Requeridos)
Rodrix Music Creator v3.0

Pruebas locales automatizadas con MOCKS (Costo $0 en créditos musicales).
Verifica:
1. Seguridad de credenciales y ausencia de secretos hardcodeados.
2. Sanitización estricta de logs y reportes diagnósticos.
3. Prioridad de GOOGLE_DRIVE_REFRESH_TOKEN sobre tokens locales.
4. Inmutabilidad de variables de entorno ante guardado local.
5. Escritura atómica de library.json y users.json.
6. Protección anti-vaciado de users.json.
7. Regla de seguridad: Usuario bloqueado jamás se reactiva por sincronización.
8. Fusión no destructiva de library.json preservando IDs y metadatos.
9. Exponential backoff ante errores transitorios de red.
10. Aborto inmediato ante errores permanentes de autenticación (401/403).
11. Deduplicación de archivos en Google Drive por metadatos y búsqueda.
12. Simulación de reinicio de contenedor Render con disco efímero vacío.
13. Exigencia estricta de SECRET_KEY en producción (detiene arranque si falta).
14. Diagnóstico admin /api/admin/gdrive-diagnostic sin exposición de secretos.
15. Deduplicación de subidas concurrentes en vuelo (Single-Flight).
16. Resolución de conflictos multi-instancia en users.json y library.json.
17. Reanudación real de subidas resumibles (protocolo 308) y rechazo de incompletas.
"""

import os
import sys
import json
import time
import asyncio
import tempfile
import unittest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock

# Establecer entorno de prueba antes de importar app
os.environ["UDIO_API_KEY"] = "sk-test-udio-dummy-key-not-real"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-testing-32chars"
os.environ["GOOGLE_CLIENT_SECRET"] = "dummy-google-client-secret"

import app


class TestPhase2SecurityAndPersistence(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Crear directorio temporal para aislar pruebas de disco
        self.test_dir = tempfile.TemporaryDirectory()
        self.orig_cwd = os.getcwd()
        os.chdir(self.test_dir.name)

        # Configurar rutas locales en el directorio temporal
        app.LIBRARY_FILE = os.path.join(self.test_dir.name, "library.json")
        app.USERS_FILE = os.path.join(self.test_dir.name, "users.json")
        app.DELETED_TRACKS_FILE = os.path.join(self.test_dir.name, "deleted_tracks.json")
        app.GDRIVE_TOKEN_FILE = os.path.join(self.test_dir.name, "gdrive_token.json")
        app.TRACKS_DIR = os.path.join(self.test_dir.name, "tracks_storage")
        os.makedirs(app.TRACKS_DIR, exist_ok=True)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.test_dir.cleanup()

    # =========================================================================
    # 1. SEGURIDAD Y SANITIZACIÓN DE SECRETOS
    # =========================================================================
    def test_01_no_hardcoded_secrets_in_code(self):
        """Verifica que app.py no contenga claves secretas hardcodeadas."""
        with open(os.path.join(self.orig_cwd, "app.py"), "r", encoding="utf-8") as f:
            code = f.read()

        self.assertNotIn("sk-udio-bfa1b3b1", code, "¡Detectada clave hardcodeada de Udio en app.py!")
        self.assertNotIn("fal_key_b94cb2c", code, "¡Detectada clave hardcodeada de Fal en app.py!")
        self.assertNotIn("rodrix_super_secret_music_key_2025", code, "¡Detectada secret key insegura en app.py!")

    def test_02_log_and_diagnostic_sanitization(self):
        """Verifica que sanitize_logs_text oculte claves de API, tokens y secretos."""
        dirty_log = (
            "Iniciando llamada con sk-1234567890abcdef1234567890 y Bearer ya29.a0ARrdaM-secret1234567890.\n"
            "Google Secret: GOCSPX-dummyclientsecret12345\n"
            "Params: client_secret=abcdef123456789 refresh_token=1//09abcdef12345678"
        )
        clean = app.sanitize_logs_text(dirty_log)

        self.assertNotIn("sk-1234567890abcdef1234567890", clean)
        self.assertIn("[PROTECTED_API_KEY]", clean)
        self.assertNotIn("ya29.a0ARrdaM-secret1234567890", clean)
        self.assertIn("Bearer [PROTECTED_TOKEN]", clean)
        self.assertNotIn("GOCSPX-dummyclientsecret12345", clean)
        self.assertNotIn("1//09abcdef12345678", clean)

    # =========================================================================
    # 2. OAUTH Y PRIORIDAD DE GOOGLE_DRIVE_REFRESH_TOKEN
    # =========================================================================
    def test_03_gdrive_refresh_token_env_priority(self):
        """Verifica que el refresh token de entorno tenga prioridad sobre el local obsoleto."""
        app.save_gdrive_tokens({"refresh_token": "stale_local_token_123", "access_token": "old_acc"})
        
        os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"] = "fresh_render_env_token_456"
        tokens = app.load_gdrive_tokens()
        self.assertEqual(tokens["refresh_token"], "fresh_render_env_token_456",
                         "El refresh token de entorno debe priorizarse sobre el local.")

        del os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"]

    def test_04_save_gdrive_tokens_does_not_mutate_env(self):
        """Verifica que save_gdrive_tokens no sobrescriba la variable de entorno."""
        os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"] = "render_immutable_token"
        app.save_gdrive_tokens({"access_token": "new_access_token", "expires_at": 9999999999})
        
        self.assertEqual(os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN"), "render_immutable_token")
        del os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"]

    # =========================================================================
    # 3. ESCRITURA ATÓMICA
    # =========================================================================
    def test_05_atomic_library_and_users_save(self):
        """Verifica que save_library_atomic y save_users_atomic escriban correctamente sin dejar temporales."""
        lib_data = [{"id": "track_1", "title": "Obra 1", "gdrive_id": "drv_1"}]
        app.save_library_atomic(lib_data)
        
        loaded = app.load_library()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "track_1")

        users_data = {"test@example.com": {"name": "Test User", "status": "active"}}
        app.save_users_atomic(users_data)
        
        loaded_users = app.load_users()
        self.assertIn("test@example.com", loaded_users)
        self.assertEqual(loaded_users["test@example.com"]["status"], "active")

        tmps = [f for f in os.listdir(self.test_dir.name) if ".tmp_" in f]
        self.assertEqual(len(tmps), 0, "No deben quedar archivos temporales huérfanos tras escritura atómica.")

    # =========================================================================
    # 4. PERSISTENCIA DE USERS.JSON Y CONTROL DE ACCESO
    # =========================================================================
    async def test_06_users_anti_wipe_protection(self):
        """Verifica que una versión local vacía jamás sobrescriba la versión de Google Drive."""
        cloud_users = {
            "rodryandy@gmail.com": {"name": "Rodrigo", "status": "active", "role": "admin"}
        }

        with patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl, \
             patch("app.gdrive_upload_or_update", new_callable=AsyncMock) as mock_ul:
            
            mock_dl.return_value = json.dumps(cloud_users).encode("utf-8")
            
            await app.gdrive_sync_users_to_cloud({})
            mock_ul.assert_not_called()

    async def test_07_blocked_user_never_reactivated_by_sync(self):
        """Verifica que un usuario bloqueado localmente jamás se reactive por una versión cloud desactualizada."""
        cloud_users = {
            "blocked@test.com": {"name": "Malo", "status": "active", "role": "user"}
        }
        local_users = {
            "blocked@test.com": {"name": "Malo", "status": "blocked", "role": "user"}
        }
        app.save_users_atomic(local_users)

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl:
            
            mock_tok.return_value = "dummy_token"
            mock_find.return_value = {"id": "users_file_id"}
            mock_dl.return_value = json.dumps(cloud_users).encode("utf-8")
            
            await app.gdrive_sync_users_from_cloud()
            
            res = app.load_users()
            self.assertEqual(res["blocked@test.com"]["status"], "blocked",
                             "¡Un usuario bloqueado jamás debe ser reactivado por una sincronización!")

    # =========================================================================
    # 5. PERSISTENCIA DE LIBRARY.JSON Y FUSIÓN INTELIGENTE
    # =========================================================================
    async def test_08_library_merge_preserves_gdrive_ids_and_metadata(self):
        """Verifica que la fusión de biblioteca preserve gdrive_id y combine pistas sin pérdida."""
        cloud_library = [
            {"id": "t1", "title": "Pista Antigua Nube", "gdrive_id": "drv_t1", "updated_at": 100},
            {"id": "t2", "title": "Pista Solo en Nube", "gdrive_id": "drv_t2", "updated_at": 100}
        ]
        local_library = [
            {"id": "t1", "title": "Pista Antigua Renombrada en Local", "gdrive_id": "drv_t1", "updated_at": 200},
            {"id": "t3", "title": "Pista Nueva Local Sin Subir", "updated_at": 200}
        ]
        app.save_library_atomic(local_library)

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl:
            
            mock_tok.return_value = "dummy_token"
            mock_find.return_value = {"id": "library_file_id"}
            mock_dl.return_value = json.dumps(cloud_library).encode("utf-8")
            
            await app.gdrive_sync_library_from_cloud()
            
            merged = app.load_library()
            ids = [t["id"] for t in merged]
            
            self.assertIn("t1", ids)
            self.assertIn("t2", ids)
            self.assertIn("t3", ids)
            
            t1_record = next(t for t in merged if t["id"] == "t1")
            self.assertEqual(t1_record["title"], "Pista Antigua Renombrada en Local")
            self.assertEqual(t1_record["gdrive_id"], "drv_t1")

    # =========================================================================
    # 6. TRANSFERENCIAS DE AUDIO CON RETRIES Y DEDUPLICACIÓN
    # =========================================================================
    async def test_09_exponential_backoff_on_transient_error(self):
        """Verifica que gdrive_upload_or_update reintente con backoff ante errores 500/503/429."""
        attempts = 0

        async def fake_request(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            mock_resp = MagicMock()
            if attempts < 3:
                mock_resp.status_code = 503
                mock_resp.text = "Service Unavailable (Transient)"
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"id": "uploaded_file_id_success"}
            return mock_resp

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("httpx.AsyncClient.post", side_effect=fake_request), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            mock_tok.return_value = "dummy_token"
            mock_find.return_value = None
            res = await app.gdrive_upload_or_update("test.mp3", b"dummy_content", "audio/mpeg")
            
            self.assertIsNotNone(res)
            self.assertEqual(res.get("file_id"), "uploaded_file_id_success")
            self.assertEqual(attempts, 3, "Debe haber reintentado hasta tener éxito en el intento 3.")

    async def test_10_immediate_abort_on_auth_permanent_error(self):
        """Verifica que gdrive_upload_or_update aborte inmediatamente ante error 401/403 sin bucle de reintentos."""
        attempts = 0

        async def fake_auth_error(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized: Invalid Credentials"
            return mock_resp

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("httpx.AsyncClient.post", side_effect=fake_auth_error), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            
            mock_tok.return_value = "dummy_token"
            mock_find.return_value = None
            res = await app.gdrive_upload_or_update("test.mp3", b"dummy_content", "audio/mpeg")
            
            self.assertIsNone(res)
            self.assertEqual(attempts, 1, "Ante error 401 permanente no debe reintentar.")

    async def test_11_audio_deduplication(self):
        """Verifica que no se dupliquen archivos si ya existen en Google Drive con el mismo nombre."""
        mock_patch_resp = MagicMock()
        mock_patch_resp.status_code = 200
        mock_patch_resp.json.return_value = {"id": "existing_drive_id", "webViewLink": "https://drive.google.com/test"}

        with patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("httpx.AsyncClient.post") as mock_post, \
             patch("httpx.AsyncClient.patch", return_value=mock_patch_resp) as mock_patch:
            
            mock_tok.return_value = "dummy_token"
            mock_find.return_value = {"id": "existing_drive_id", "webViewLink": "https://drive.google.com/test"}
            
            test_audio_path = os.path.join(app.TRACKS_DIR, "track_abc.mp3")
            with open(test_audio_path, "wb") as f:
                f.write(b"mp3_fake_audio_bytes" * 100)
            
            res = await app.gdrive_upload_track_audio("track_abc", test_audio_path, "Mi Obra")
            
            self.assertIsNotNone(res)
            self.assertEqual(res["file_id"], "existing_drive_id")
            mock_post.assert_not_called()
            mock_patch.assert_called_once()

    # =========================================================================
    # 7. SIMULACIÓN DE REINICIO DE CONTENEDOR (DISCO EFÍMERO RENDER)
    # =========================================================================
    async def test_12_simulated_render_container_reboot(self):
        """Simula el reinicio de Render con disco local efímero vacío."""
        cloud_users = {
            "rodryandy@gmail.com": {"name": "Rodrigo", "status": "active", "role": "admin"}
        }
        cloud_library = [
            {"id": "track_persisted_1", "title": "Coro Pentecostal Avivamiento", "gdrive_id": "g123"}
        ]

        if os.path.exists(app.USERS_FILE): os.remove(app.USERS_FILE)
        if os.path.exists(app.LIBRARY_FILE): os.remove(app.LIBRARY_FILE)
        if os.path.exists(app.GDRIVE_TOKEN_FILE): os.remove(app.GDRIVE_TOKEN_FILE)

        os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"] = "render_persistent_refresh_token"

        async def fake_dl(file_id, *args, **kwargs):
            if file_id == "users_cloud_id":
                return json.dumps(cloud_users).encode("utf-8")
            elif file_id == "library_cloud_id":
                return json.dumps(cloud_library).encode("utf-8")
            return None

        async def fake_find(filename, *args, **kwargs):
            if filename == "users.json":
                return {"id": "users_cloud_id"}
            elif filename == "library.json":
                return {"id": "library_cloud_id"}
            return None

        with patch("app.gdrive_find_file", side_effect=fake_find), \
             patch("app.gdrive_download_file_bytes", side_effect=fake_dl), \
             patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok:
            
            mock_tok.return_value = "mock_access_token_via_env"
            await app.startup_event()
            
            restored_users = app.load_users()
            restored_library = app.load_library()
            
            self.assertIn("rodryandy@gmail.com", restored_users)
            self.assertEqual(len(restored_library), 1)
            self.assertEqual(restored_library[0]["id"], "track_persisted_1")
            self.assertEqual(restored_library[0]["gdrive_id"], "g123")

        del os.environ["GOOGLE_DRIVE_REFRESH_TOKEN"]

    # =========================================================================
    # 8. AJUSTES OBLIGATORIOS (NUEVAS PRUEBAS 13-17)
    # =========================================================================
    def test_13_secret_key_required_in_production(self):
        """Ajuste 2: Verifica que el arranque se detenga de inmediato si falta SECRET_KEY en producción."""
        import subprocess
        env = dict(os.environ)
        env["RENDER"] = "true"
        env.pop("SECRET_KEY", None)
        
        cmd = [sys.executable, "-c", "import app"]
        proc = subprocess.run(cmd, env=env, cwd=self.orig_cwd, capture_output=True, text=True)
        
        self.assertEqual(proc.returncode, 1, "El servidor debe abortar con sys.exit(1) si falta SECRET_KEY en producción.")
        self.assertIn("ERROR FATAL", proc.stderr)
        self.assertIn("SECRET_KEY", proc.stderr)

    async def test_14_admin_gdrive_diagnostic_does_not_reveal_secrets(self):
        """Ajuste 1: Verifica que el diagnóstico admin reporte estado sin revelar refresh_token ni secretos."""
        app.save_gdrive_tokens({"refresh_token": "super_secret_refresh_token_999", "access_token": "secret_access_abc"})
        
        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok:
            mock_tok.return_value = "dummy_valid_token"
            resp = await app.api_admin_gdrive_diagnostic(current_user=app.ADMIN_EMAIL)
            body = resp.body.decode("utf-8")
            data = json.loads(body)

            self.assertEqual(data["status"], "success")
            self.assertTrue(data["is_configured"])
            self.assertTrue(data["auth_working"])
            self.assertIn("auth_message", data)
            
            # Verificación estricta de seguridad: NINGÚN secreto expuesto
            self.assertNotIn("super_secret_refresh_token_999", body)
            self.assertNotIn("secret_access_abc", body)
            self.assertNotIn("refresh_token", data)
            self.assertNotIn("access_token", data)

    async def test_15_in_flight_concurrent_upload_deduplication(self):
        """Ajuste 3: Verifica que dos subidas simultáneas del mismo archivo compartan ejecución (Single-Flight)."""
        call_count = 0
        async def mock_do_upload(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05) # Simular latencia de red
            return {"file_id": "single_flight_drive_id"}

        with patch("app._do_upload_or_update", side_effect=mock_do_upload):
            # Disparar 2 llamadas concurrentes al mismo archivo
            res1, res2 = await asyncio.gather(
                app.gdrive_upload_or_update("concurrent_file.mp3", b"dummy_content"),
                app.gdrive_upload_or_update("concurrent_file.mp3", b"dummy_content")
            )
            self.assertEqual(res1["file_id"], "single_flight_drive_id")
            self.assertEqual(res2["file_id"], "single_flight_drive_id")
            self.assertEqual(call_count, 1, "Solo se debió invocar 1 vez la subida física gracias al mutex en vuelo.")

    async def test_16_multi_instance_conflict_resolution(self):
        """Ajuste 4: Verifica resolución de conflictos multi-instancia en users.json y library.json."""
        # A) users.json: Nube tiene activo, pero administrador local bloqueó al usuario
        cloud_users = {"bad_actor@test.com": {"name": "Usuario", "status": "active", "last_login": "2026-10-27 10:00:00"}}
        local_users = {"bad_actor@test.com": {"name": "Usuario", "status": "blocked", "last_login": "2026-10-27 10:05:00"}}

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl, \
             patch("app.gdrive_upload_or_update", new_callable=AsyncMock) as mock_ul:
            
            mock_tok.return_value = "token"
            mock_find.return_value = {"id": "users_id"}
            mock_dl.return_value = json.dumps(cloud_users).encode("utf-8")
            mock_ul.return_value = {"file_id": "users_id"}
            
            await app.gdrive_sync_users_to_cloud(local_users)
            saved = app.load_users()
            self.assertEqual(saved["bad_actor@test.com"]["status"], "blocked",
                             "La fusión multi-instancia jamás debe desbloquear un usuario bloqueado.")

        # B) library.json: Otra instancia agregó track_cloud_B en nube, nosotros tenemos track_local_A
        cloud_lib = [{"id": "track_cloud_B", "title": "Pista Otra Instancia", "gdrive_id": "drv_B"}]
        local_lib = [{"id": "track_local_A", "title": "Pista Local", "gdrive_id": "drv_A"}]

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl, \
             patch("app.gdrive_upload_or_update", new_callable=AsyncMock) as mock_ul:
            
            mock_tok.return_value = "token"
            mock_find.return_value = {"id": "lib_id"}
            mock_dl.return_value = json.dumps(cloud_lib).encode("utf-8")
            mock_ul.return_value = {"file_id": "lib_id"}

            await app.gdrive_sync_library_to_cloud(local_lib)
            merged = app.load_library()
            ids = [t["id"] for t in merged]
            self.assertIn("track_local_A", ids, "No debe perder la pista local")
            self.assertIn("track_cloud_B", ids, "Debe integrar la pista de la otra instancia sin sobrescribirla")

    async def test_17_resumable_upload_resumption_and_incomplete_rejection(self):
        """Ajuste 5: Verifica reanudación tras 308 Resume Incomplete y rechazo estricto de subidas incompletas."""
        client = MagicMock()
        init_resp = MagicMock(status_code=200, headers={"Location": "https://upload.google.com/session_123"})
        status_resp = MagicMock(status_code=308, headers={"Range": "bytes=0-4"})
        final_resp = MagicMock(status_code=200, json=lambda: {"id": "resumed_success_id"})
        
        client.post = AsyncMock(return_value=init_resp)
        client.put = AsyncMock(side_effect=[httpx.TimeoutException("Corte de red"), status_resp, final_resp])
        
        dummy_content = b"0123456789" # 10 bytes
        with patch("asyncio.sleep", new_callable=AsyncMock):
            res = await app._perform_resumable_upload(client, "test_resumable.mp3", dummy_content, "audio/mpeg", "folder", {}, max_retries=3)
            self.assertIsNotNone(res)
            self.assertEqual(res.get("file_id"), "resumed_success_id")

        client_fail = MagicMock()
        client_fail.post = AsyncMock(return_value=MagicMock(status_code=500, text="Internal Server Error"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            res_fail = await app._perform_resumable_upload(client_fail, "test_fail.mp3", dummy_content, "audio/mpeg", "folder", {}, max_retries=2)
            self.assertIsNone(res_fail, "Subida fallida debe retornar None.")

    # =========================================================================
    # 9. VALIDACIÓN FINAL: PROCESOS INDEPENDIENTES, RECUPERACIÓN Y TOMBSTONES
    # =========================================================================
    async def test_18_deletions_and_renames_never_reverted_by_sync(self):
        """Verifica que eliminaciones y renombrados no sean revertidos por sincronizaciones posteriores."""
        initial_library = [
            {"id": "del_1", "title": "Pista a Eliminar", "gdrive_id": "drv_del_1", "updated_at": 100},
            {"id": "ren_2", "title": "Titulo Original", "gdrive_id": "drv_ren_2", "updated_at": 100}
        ]
        app.save_library_atomic(initial_library)
        
        # Eliminar 'del_1'
        del_resp = await app.api_delete_from_library("del_1", current_user=app.ADMIN_EMAIL)
        self.assertEqual(del_resp.status_code, 200)
        
        # Renombrar 'ren_2'
        fake_req = MagicMock()
        fake_req.json = AsyncMock(return_value={"title": "Nuevo Titulo Editado"})
        ren_resp = await app.api_rename_track("ren_2", fake_req, current_user=app.ADMIN_EMAIL)
        self.assertEqual(ren_resp.status_code, 200)
        
        # Simular que la nube todavía tiene la versión vieja
        cloud_old_library = [
            {"id": "del_1", "title": "Pista a Eliminar", "gdrive_id": "drv_del_1", "updated_at": 100},
            {"id": "ren_2", "title": "Titulo Original", "gdrive_id": "drv_ren_2", "updated_at": 100}
        ]
        
        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_find_file", new_callable=AsyncMock) as mock_find, \
             patch("app.gdrive_download_file_bytes", new_callable=AsyncMock) as mock_dl:
            
            mock_tok.return_value = "token"
            mock_find.return_value = {"id": "lib_cloud_id"}
            mock_dl.return_value = json.dumps(cloud_old_library).encode("utf-8")
            
            await app.gdrive_sync_library_from_cloud()
            
            final_lib = app.load_library()
            ids = [t["id"] for t in final_lib]
            
            self.assertNotIn("del_1", ids, "Pista eliminada no debe reaparecer tras sync.")
            ren_track = next(t for t in final_lib if t["id"] == "ren_2")
            self.assertEqual(ren_track["title"], "Nuevo Titulo Editado", "Pista renombrada no debe ser pisada por sync viejo.")

    def test_19_two_independent_os_processes_concurrency(self):
        """
        Verifica que dos procesos de SO independientes realizando escrituras simultáneas reales
        sobre el mismo almacenamiento compartido (SQLite BEGIN IMMEDIATE + JSON + Cloud CAS)
        no pierdan ninguna actualización (0 Lost Updates).
        """
        import subprocess
        import sqlite3

        worker_code = """
import sys
import os
import json
import time
import asyncio
from unittest.mock import patch

proc_id = sys.argv[1]
work_dir = sys.argv[2]
repo_dir = sys.argv[3]

sys.path.insert(0, repo_dir)
os.environ["UDIO_API_KEY"] = "sk-test-udio-dummy-key-not-real"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-testing-32chars"
os.environ["GOOGLE_CLIENT_SECRET"] = "dummy-google-client-secret"
os.environ["RODRIX_DB_PATH"] = os.path.join(work_dir, "rodrix_persistence.db")

import app

app.LIBRARY_FILE = os.path.join(work_dir, "library.json")
app.USERS_FILE = os.path.join(work_dir, "users.json")
app.DELETED_TRACKS_FILE = os.path.join(work_dir, "deleted_tracks.json")

# Simular almacenamiento remoto compartido de Google Drive con CAS real sobre archivo compartido
cloud_dir = os.path.join(work_dir, "shared_cloud_drive")
os.makedirs(cloud_dir, exist_ok=True)

async def shared_find(filename, *args, **kwargs):
    p = os.path.join(cloud_dir, os.path.basename(filename))
    if os.path.exists(p):
        return {"id": os.path.basename(filename)}
    return None

async def shared_dl(file_id, *args, **kwargs):
    p = os.path.join(cloud_dir, os.path.basename(file_id))
    for _ in range(5):
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return f.read()
            except Exception:
                await asyncio.sleep(0.01)
    return None

async def shared_ul(filename, content_bytes, *args, **kwargs):
    p = os.path.join(cloud_dir, os.path.basename(filename))
    tmp = f"{p}.tmp_{proc_id}_{time.time_ns()}"
    with open(tmp, "wb") as f:
        f.write(content_bytes)
    for _ in range(10):
        try:
            os.replace(tmp, p)
            break
        except Exception:
            await asyncio.sleep(0.01)
    return {"file_id": os.path.basename(filename)}

async def main():
    with patch("app.gdrive_get_access_token", return_value="dummy_token"), \\
         patch("app.gdrive_find_file", side_effect=shared_find), \\
         patch("app.gdrive_download_file_bytes", side_effect=shared_dl), \\
         patch("app.gdrive_upload_or_update", side_effect=shared_ul):

        # Cada proceso inserta 5 canciones y 5 usuarios de forma concurrente
        for i in range(5):
            tid = f"track_{proc_id}_{i}"
            app.add_track_to_library({
                "id": tid,
                "title": f"Cancion {proc_id} #{i}",
                "gdrive_id": f"drv_{tid}",
                "updated_at": time.time()
            })
            email = f"user_{proc_id}_{i}@test.com"
            app.save_users_atomic({
                email: {
                    "email": email,
                    "name": f"Usuario {proc_id} #{i}",
                    "status": "active",
                    "updated_at": f"2026-10-27 11:00:0{i}"
                }
            })
            await asyncio.sleep(0.005)

        await app.gdrive_sync_library_to_cloud()
        await app.gdrive_sync_users_to_cloud()

asyncio.run(main())
"""
        script_path = os.path.join(self.test_dir.name, "concurrent_worker.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(worker_code)

        p1 = subprocess.Popen(
            [sys.executable, script_path, "procA", self.test_dir.name, self.orig_cwd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        p2 = subprocess.Popen(
            [sys.executable, script_path, "procB", self.test_dir.name, self.orig_cwd],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        out1, err1 = p1.communicate(timeout=20)
        out2, err2 = p2.communicate(timeout=20)

        self.assertEqual(p1.returncode, 0, f"Proceso A falló: {err1}")
        self.assertEqual(p2.returncode, 0, f"Proceso B falló: {err2}")

        saved_lib = app.load_library()
        saved_users = app.load_users()

        lib_ids = {t["id"] for t in saved_lib}
        expected_tracks = {f"track_procA_{i}" for i in range(5)} | {f"track_procB_{i}" for i in range(5)}
        expected_users = {f"user_procA_{i}@test.com" for i in range(5)} | {f"user_procB_{i}@test.com" for i in range(5)}

        self.assertEqual(lib_ids, expected_tracks, "Ninguna canción de ninguno de los dos procesos debe perderse (10/10).")
        self.assertEqual(set(saved_users.keys()), expected_users, "Ningún usuario de ninguno de los dos procesos debe perderse (10/10).")

        # Verificar también el estado en la base de datos transaccional SQLite
        conn = sqlite3.connect(app._get_db_path())
        try:
            db_track_ids = {row[0] for row in conn.execute("SELECT id FROM tracks").fetchall()}
            db_user_emails = {row[0] for row in conn.execute("SELECT email FROM users").fetchall()}
            self.assertEqual(db_track_ids, expected_tracks)
            self.assertEqual(db_user_emails, expected_users)
        finally:
            conn.close()

    async def test_20_pending_uploads_recovery_worker(self):
        """Verifica que el recuperador de subidas pendientes procese pistas sin gdrive_id tras un reinicio."""
        unbacked_track = {
            "id": "pending_track_1",
            "title": "Himno de Avivamiento",
            "gdrive_id": None
        }
        app.save_library_atomic([unbacked_track])

        audio_file_path = os.path.join(app.TRACKS_DIR, "pending_track_1.mp3")
        with open(audio_file_path, "wb") as f:
            f.write(b"fake_mp3_audio_data_for_recovery" * 100)

        mock_upload_res = {
            "file_id": "gdrive_recovered_id_999",
            "webViewLink": "https://drive.google.com/recovered_view"
        }

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("app.gdrive_upload_track_audio", new_callable=AsyncMock) as mock_upload, \
             patch("app.gdrive_sync_library_to_cloud", new_callable=AsyncMock):

            mock_tok.return_value = "token"
            mock_upload.return_value = mock_upload_res

            await app.recover_pending_uploads()

            updated_lib = app.load_library()
            self.assertEqual(len(updated_lib), 1)
            self.assertEqual(updated_lib[0]["gdrive_id"], "gdrive_recovered_id_999")
            self.assertEqual(updated_lib[0]["gdrive_link"], "https://drive.google.com/recovered_view")
            self.assertEqual(updated_lib[0]["persistence_status"], "PERSISTED_GDRIVE")
            self.assertTrue(updated_lib[0]["is_permanently_saved"])

    async def test_21_track_not_marked_saved_when_only_ephemeral_or_external_url(self):
        """
        Verifica que una generación NO se considere definitivamente guardada (is_permanently_saved=False)
        mientras su MP3 dependa exclusivamente del disco efímero de Render o de una URL temporal externa.
        """
        import sqlite3

        ephemeral_only_track = {
            "id": "ephemeral_track_01",
            "title": "Alabanza Efímera Sin Drive",
            "audio_url": "/api/audio_file/ephemeral_track_01",
            "raw_audio_url": "https://cdn.temporal-provider.com/temp_01.mp3",
            "cloud_backup": "https://catbox.moe/temp_01.mp3",
            "gdrive_id": None
        }
        app.add_track_to_library(ephemeral_only_track)

        loaded = app.load_library()
        self.assertEqual(len(loaded), 1)
        t = loaded[0]
        self.assertFalse(t["is_permanently_saved"], "No debe marcarse como guardada permanentemente sin gdrive_id.")
        self.assertEqual(t["persistence_status"], "PENDING_BACKUP")

        # Verificar que exista una operación pendiente en la tabla pending_operations de SQLite
        conn = sqlite3.connect(app._get_db_path())
        try:
            row = conn.execute("SELECT status, op_type FROM pending_operations WHERE id = ?", ("ephemeral_track_01",)).fetchone()
            self.assertIsNotNone(row, "Debe registrarse la operación pendiente en la base transaccional.")
            self.assertEqual(row[0], "PENDING_BACKUP")
            self.assertEqual(row[1], "UPLOAD_AUDIO")
        finally:
            conn.close()

    async def test_22_process_terminates_before_upload_and_external_url_expired(self):
        """
        Simula el caso donde el proceso termina antes de completar la subida a Google Drive,
        el MP3 local del disco efímero desaparece y la URL externa ya no está disponible (HTTP 404).
        Verifica que la canción NO figure como respaldada y pase a estado AUDIO_LOST_UNRECOVERABLE.
        """
        import sqlite3

        interrupted_track = {
            "id": "crashed_track_404",
            "title": "Canción Interrumpida Antes de Subir",
            "audio_url": "/api/audio_file/crashed_track_404",
            "raw_audio_url": "https://expired-cdn.example.com/crashed_track_404.mp3",
            "cloud_backup": None,
            "gdrive_id": None
        }
        app.add_track_to_library(interrupted_track)

        # Asegurar que el archivo local en disco efímero NO existe (simulando reinicio de contenedor Render)
        local_mp3 = os.path.join(app.TRACKS_DIR, "crashed_track_404.mp3")
        if os.path.exists(local_mp3):
            os.remove(local_mp3)

        # Simular que la URL externa ya expiró y devuelve 404 Not Found
        mock_404_resp = MagicMock()
        mock_404_resp.status_code = 404
        mock_404_resp.content = b"Not Found"

        with patch("app.gdrive_get_access_token", new_callable=AsyncMock) as mock_tok, \
             patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_404_resp), \
             patch("app.gdrive_sync_library_to_cloud", new_callable=AsyncMock):

            mock_tok.return_value = "valid_token"
            await app.recover_pending_uploads(max_retries=3)

            lib = app.load_library()
            self.assertEqual(len(lib), 1)
            t = lib[0]

            self.assertIsNone(t.get("gdrive_id"))
            self.assertFalse(t["is_permanently_saved"], "Jamás debe considerarse guardada si falló la subida y expiró la URL.")
            self.assertEqual(t["persistence_status"], "AUDIO_LOST_UNRECOVERABLE")
            self.assertEqual(t["backup_retry_count"], 1)
            self.assertIn("404", t.get("last_backup_error", ""))

            # Verificar que la base de datos SQLite también refleje AUDIO_LOST_UNRECOVERABLE
            conn = sqlite3.connect(app._get_db_path())
            try:
                row = conn.execute("SELECT persistence_status FROM tracks WHERE id = ?", ("crashed_track_404",)).fetchone()
                self.assertEqual(row[0], "AUDIO_LOST_UNRECOVERABLE")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
