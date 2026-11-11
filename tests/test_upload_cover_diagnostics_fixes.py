import asyncio
import json
import os
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Garantizar que ninguna llamada accidental salga a Google Drive real durante pruebas unitarias
os.environ["RODRIX_DISABLE_GDRIVE_NETWORK"] = "1"
os.environ.setdefault("UDIO_API_KEY", "test_key_redacted_0000")

import app
import music_engine_adapter


class TestUploadCoverDiagnosticsFixes(unittest.IsolatedAsyncioTestCase):
    """
    Suite integral (0 créditos, 0 POST reales a UdioAPI, 0 escrituras en Google Drive real)
    que valida todas las correcciones derivadas del incidente upcov80e27a62e0bf4dcab171525cb86ed5be.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.orig_tasks_file = app.GENERATION_TASKS_FILE
        self.orig_lib_file = app.LIBRARY_FILE
        self.orig_tracks_dir = app.TRACKS_DIR
        self.orig_db_env = os.environ.get("RODRIX_DB_PATH")

        self.tmp_db = os.path.join(self.tmpdir.name, "test_rodrix.db")
        self.tmp_tracks = os.path.join(self.tmpdir.name, "tracks_storage")
        os.makedirs(self.tmp_tracks, exist_ok=True)
        os.environ["RODRIX_DB_PATH"] = self.tmp_db
        app.GENERATION_TASKS_FILE = os.path.join(self.tmpdir.name, "generation_tasks.json")
        app.LIBRARY_FILE = os.path.join(self.tmpdir.name, "library.json")
        app.TRACKS_DIR = self.tmp_tracks
        with app._transactional_db():
            pass
        app.TASKS.clear()
        app.RECENT_OPERATIONS.clear()
        app._in_flight_recoveries.clear()
        app._recovery_tasks.clear()
        app.app.dependency_overrides.clear()
        app.LAST_GDRIVE_ERROR.update({"error": None, "timestamp": None})
        app.LAST_GDRIVE_TASKS_SYNC.update({"ok": None, "file_id": None, "error": None, "timestamp": None})
        app.LAST_GDRIVE_LIBRARY_SYNC.update({"ok": None, "file_id": None, "tracks_count": 0, "error": None, "timestamp": None})

    def tearDown(self):
        app.app.dependency_overrides.clear()
        for t in list(app._recovery_tasks.values()):
            if not t.done():
                t.cancel()
        app._recovery_tasks.clear()
        app._in_flight_recoveries.clear()
        app.TASKS.clear()
        app.RECENT_OPERATIONS.clear()
        app.GENERATION_TASKS_FILE = self.orig_tasks_file
        app.LIBRARY_FILE = self.orig_lib_file
        app.TRACKS_DIR = self.orig_tracks_dir
        if self.orig_db_env is None:
            os.environ.pop("RODRIX_DB_PATH", None)
        else:
            os.environ["RODRIX_DB_PATH"] = self.orig_db_env
        self.tmpdir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Respaldo de generation_tasks.json en Google Drive y manejo de errores
    # -------------------------------------------------------------------------
    async def test_01_gdrive_sync_tasks_uses_gdrive_upload_or_update_no_nameerror(self):
        """Verifica que gdrive_sync_generation_tasks_to_cloud usa gdrive_upload_or_update, actualiza sin duplicar y registra éxito/error."""
        task_id = "task-sync-001"
        app.TASKS[task_id] = {
            "id": task_id,
            "work_id": "upcov_sync_001",
            "owner_email": "pastor@rodrix.com",
            "status": "IN_PROGRESS",
            "title": "Prueba Sync Drive",
            "model": "chirp-v6",
            "resolved_payload": {"model": "chirp-v6", "style": "Christian worship, 84 BPM"},
            "logs": "[10:00:00] Work ID asignado: upcov_sync_001\n",
            "created_at": time.time(),
        }
        with patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value=None)):
            app.save_task_persistent(task_id, app.TASKS[task_id])

        # Simular actualización exitosa vía gdrive_upload_or_update (patch in-place simulado)
        mock_upload = AsyncMock(return_value={"id": "drv_tasks_id_999", "file_id": "drv_tasks_id_999"})
        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok_safe")), \
             patch.object(app, "gdrive_upload_or_update", mock_upload):
            res = await app.gdrive_sync_generation_tasks_to_cloud()
            self.assertIsNotNone(res)
            self.assertEqual(res.get("file_id"), "drv_tasks_id_999")
            mock_upload.assert_awaited_once()
            args, _ = mock_upload.call_args
            self.assertEqual(args[0], app.GENERATION_TASKS_FILE)
            self.assertEqual(args[2], "application/json")
            self.assertTrue(app.LAST_GDRIVE_TASKS_SYNC["ok"])
            self.assertEqual(app.LAST_GDRIVE_TASKS_SYNC["file_id"], "drv_tasks_id_999")

        # Simular fallo de Google Drive (ej. HTTP 403 / timeout -> devuelve None)
        app.LAST_GDRIVE_ERROR.update({"error": "Error 403: quotaExceeded", "timestamp": "2026-11-10T00:00:00Z"})
        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok_safe")), \
             patch.object(app, "gdrive_upload_or_update", AsyncMock(return_value=None)):
            res_fail = await app.gdrive_sync_generation_tasks_to_cloud()
            self.assertIsNone(res_fail)
            self.assertFalse(app.LAST_GDRIVE_TASKS_SYNC["ok"])
            self.assertIn("403", app.LAST_GDRIVE_TASKS_SYNC["error"])

    async def test_02_do_upload_or_update_updates_existing_without_duplicate(self):
        """Verifica que _do_upload_or_update hace PATCH sobre el file_id existente en vez de crear archivo duplicado."""
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        patch_resp.json.return_value = {"id": "existing_tasks_fid"}

        mock_client = AsyncMock()
        mock_client.patch.return_value = patch_resp

        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok_safe")), \
             patch.object(app, "gdrive_find_file", AsyncMock(return_value={"id": "existing_tasks_fid"})), \
             patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            res = await app.gdrive_upload_or_update("generation_tasks.json", b"{}", "application/json", "folder_id_1")
            self.assertEqual(res.get("file_id"), "existing_tasks_fid")
            self.assertEqual(mock_client.patch.call_count, 1)
            self.assertEqual(mock_client.post.call_count, 0, "No debe hacer POST duplicado si el archivo ya existe")

    async def test_03_task_persistence_restoration_and_user_isolation(self):
        """Verifica restauración tras reinicio simulado y aislamiento estricto de tareas por usuario."""
        task_a = "task-user-a-001"
        task_b = "task-user-b-002"
        remote_tasks = {
            task_a: {
                "id": task_a,
                "task_id": task_a,
                "work_id": "upcov_user_a_wid",
                "provider_work_id": "upcov_user_a_wid",
                "owner_email": "usuario_a@iglesia.com",
                "title": "Alabanza A",
                "status": "IN_PROGRESS",
                "model": "chirp-v5",  # Histórico legacy: NO debe mutarse automáticamente a chirp-v6
                "payload": {"model": "chirp-v5", "style": "worship, 84 BPM"},
                "created_at": time.time(),
                "updated_at": time.time(),
            },
            task_b: {
                "id": task_b,
                "task_id": task_b,
                "work_id": "upcov_user_b_wid",
                "provider_work_id": "upcov_user_b_wid",
                "owner_email": "usuario_b@iglesia.com",
                "title": "Himno B",
                "status": "PENDING_VERIFICATION",
                "model": "chirp-v6",
                "payload": {"model": "chirp-v6", "style": "hymn, 72 BPM"},
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        }
        cloud_bytes = json.dumps(remote_tasks).encode("utf-8")

        # Simular reinicio completo con disco virgen
        app.TASKS.clear()
        if os.path.exists(app.GENERATION_TASKS_FILE):
            os.remove(app.GENERATION_TASKS_FILE)

        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok")), \
             patch.object(app, "gdrive_find_file", AsyncMock(return_value={"id": "drv_tasks_id"})), \
             patch.object(app, "gdrive_download_file_bytes", AsyncMock(return_value=cloud_bytes)):
            await app.gdrive_sync_generation_tasks_from_cloud()
            app.recover_pending_generation_tasks()

        # Verificar Work ID y modelo histórico intactos
        self.assertEqual(app.TASKS[task_a]["work_id"], "upcov_user_a_wid")
        self.assertEqual(app.TASKS[task_a]["model"], "chirp-v5", "Modelo histórico/pendiente no debe cambiarse automáticamente")
        self.assertEqual(app.TASKS[task_a]["status"], "PENDING_VERIFICATION")
        self.assertEqual(app.TASKS[task_b]["model"], "chirp-v6")

        # Verificar aislamiento estricto por usuario
        is_own_a_on_a, _ = app.find_task_and_check_ownership(task_a, "usuario_a@iglesia.com")
        is_own_a_on_b, _ = app.find_task_and_check_ownership(task_b, "usuario_a@iglesia.com")
        is_own_adm_on_b, _ = app.find_task_and_check_ownership(task_b, app.ADMIN_EMAIL)
        self.assertTrue(is_own_a_on_a)
        self.assertFalse(is_own_a_on_b, "Usuario A no debe tener acceso a tareas de Usuario B")
        self.assertTrue(is_own_adm_on_b)

    # -------------------------------------------------------------------------
    # 2. Priorización de STYLE y preservación de voz femenina española en <=1000 chars
    # -------------------------------------------------------------------------
    async def test_04_prioritized_style_preserves_female_spanish_vocals_and_core_fields(self):
        """
        Reproduce exactamente el caso saturado de upcov80e (yamaha tf5 + ludwig classic 70s +
        fender jazz bass deluxe + 84 BPM + articulaciones + voz femenina) y verifica que:
        - style <= 1000 caracteres
        - Conserva género/instrumentos principales, 84 BPM, ritmo y 'female Spanish vocals'
        - No trunca silenciosamente las prioridades 1-5 aunque el equipamiento sea muy extenso.
        """
        captured_payloads = []

        async def fake_post(url, headers=None, json=None, **kwargs):
            captured_payloads.append(dict(json or {}))
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "workId": "upcov_mock_priority_check"}
            return m

        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {
            "code": 200,
            "data": {"type": "SUCCESS", "response_data": []}
        }

        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_client.get.return_value = status_mock

        task_id = "test-priority-style-004"
        app.TASKS[task_id] = {"id": task_id, "owner_email": "test@rodrix.com", "logs": "", "status": "IN_PROGRESS"}

        heavy_style = "Christian Worship, yamaha tf5, ludwig classic 70s, fender jazz bass deluxe, martin d-28"
        anti_synth = "synth bass, synthesizer bass, 808 bass, 808 sub, electronic bass, moog bass, midi bass, synthesized bassline, digital sub bass"

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/mock.mp3")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_ok"})):
            client_cls.return_value.__aenter__.return_value = mock_client

            # Usar bytes reales de test.wav para no fallar en validaciones locales (y bypass=False para testear rápido)
            src_wav = os.path.join(REPO_DIR, "test.wav")
            if os.path.exists(src_wav):
                with open(src_wav, "rb") as _f:
                    audio_bytes = _f.read()
            else:
                audio_bytes = b"RIFF" + b"\x00" * 2048

            await app.run_transform_task(
                task_id=task_id,
                style=heavy_style,
                lyrics="[Verse]\nAlabanza de prueba original",
                title="No puede V1",
                audio_content=audio_bytes,
                audio_filename="test_original.wav",
                ignore_audio=False,
                include_lyrics=True,
                bypass_copyright=False,
                exclude_styles=anti_synth,
                vocal_gender="female",
                weirdness=25,
                style_influence=87,
                audio_influence=25,
                model="chirp-v6",
                target_bpm=84,
                hihat_mode="8th",
                art_crash_toms=True,
                art_bass_pickup=True,
                lyrics_mode="custom",
                preserve_original_audio=True,
            )

        self.assertEqual(mock_client.post.call_count, 1, "Debe realizarse exactamente 1 POST simulado al mock")
        payload = captured_payloads[0]
        sent_style = payload["style"]
        self.assertLessEqual(len(sent_style), 1000, "style nunca debe exceder 1000 caracteres")
        self.assertIn("Christian Worship", sent_style)
        self.assertIn("84 BPM", sent_style)
        self.assertIn("live acoustic drum kit", sent_style)
        self.assertIn("authentic electric bass guitar", sent_style)
        self.assertIn("eighth-note hi-hat", sent_style)
        self.assertIn("female Spanish vocals", sent_style, "La voz femenina en español DEBE preservarse")
        self.assertNotIn("synth bass", sent_style.lower(), "No debe inferirse synth bass desde 'zero synth bass'")
        self.assertNotIn("orchestral strings", sent_style.lower(), "No deben inferirse orchestral strings desde 'nickel strings'")

        # Verificar orden estricto de prioridades: 1.Género -> 2.BPM -> 3.Instrumentación -> 4.Ritmo -> 5.Voz -> 6.Detalles secundarios
        idx_genre = sent_style.index("Christian Worship")
        idx_bpm = sent_style.index("84 BPM")
        idx_inst = sent_style.index("live acoustic drum kit")
        idx_rhythm = sent_style.index("eighth-note hi-hat")
        idx_vocal = sent_style.index("clear natural female Spanish vocals")
        idx_sec = sent_style.index("yamaha tf5")
        self.assertLess(idx_genre, idx_bpm)
        self.assertLess(idx_bpm, idx_inst)
        self.assertLess(idx_inst, idx_rhythm)
        self.assertLess(idx_rhythm, idx_vocal)
        self.assertLess(idx_vocal, idx_sec)

        self.assertEqual(payload["model"], "chirp-v6")
        self.assertEqual(payload["gender"], "female")
        self.assertTrue(payload["custom_mode"])
        self.assertFalse(payload["make_instrumental"])

        # Verificar diagnósticos seguros registrados
        task_logs = app.TASKS[task_id]["logs"]
        self.assertIn("Modelo: chirp-v6", task_logs)
        self.assertIn("Tags de exclusión enviados (tags):", task_logs)
        self.assertIn("audio_weight=0.25", task_logs)
        self.assertIn("style_weight=0.87", task_logs)
        self.assertIn("Respaldo de tarea en Google Drive confirmado", task_logs)

    # -------------------------------------------------------------------------
    # 3. Exclusiones negativas (tags): sin corte 80 chars, manuales preservadas, sin conflictos
    # -------------------------------------------------------------------------
    def test_05_exclusions_no_80_char_cap_dedup_and_no_conflicts(self):
        """Verifica que tags preserva >80 chars, conserva exclusiones manuales primero, elimina duplicados y evita conflictos."""
        manual_and_auto = "cumbia, reggaeton, synth bass, synthbass, 808 bass, 808 sub, electronic bass, moog bass, midi bass, synthesized bassline, digital sub bass, keyboard bass"
        formatted = app.format_provider_tags(manual_and_auto)
        self.assertGreater(len(formatted), 80, "No debe truncar arbitrariamente a 80 chars")
        self.assertIn("cumbia", formatted)
        self.assertIn("midi bass", formatted)
        self.assertIn("keyboard bass", formatted)
        # Duplicados compactos eliminados ('synthbass' colapsado con 'synth bass')
        tokens = [t.strip().lower() for t in formatted.split(",")]
        self.assertEqual(tokens.count("synth bass"), 1)
        self.assertNotIn("synthbass", tokens)

        # Conflicto 1: Usuario pide explícitamente Synth Bass -> antiSynth NO debe prohibir synth bass ni 808
        _, tags_synth_allowed, _ = app.resolve_negative_exclusions(
            exclude_styles="reggaeton",
            positive_style="Christian electronic pop, 120 BPM, synth bass, drums, female vocals",
        )
        self.assertIn("reggaeton", tags_synth_allowed)
        self.assertNotIn("synth bass", tags_synth_allowed.lower())
        self.assertNotIn("808 bass", tags_synth_allowed.lower())

        # Conflicto 2: Usuario pide guitarra distorsionada -> las exclusiones automáticas no deben prohibir distortion ni guitar
        _, tags_rock_guitar, _ = app.resolve_negative_exclusions(
            exclude_styles="cumbia",
            positive_style="Christian rock, electric guitar, overdrive distortion, electric bass, acoustic drums",
        )
        self.assertIn("cumbia", tags_rock_guitar)
        self.assertNotIn("distortion", tags_rock_guitar.lower())
        self.assertIn("moog bass", tags_rock_guitar.lower(), "Debe seguir excluyendo moog bass cuando el bajo es eléctrico real")

    # -------------------------------------------------------------------------
    # 4. Validación de modelos v6 + compatibilidad legacy + rechazo de inválidos
    # -------------------------------------------------------------------------
    def test_06_model_catalog_validation_and_credits(self):
        """Verifica soporte de chirp-v6, chirp-v6-mini, chirp-v6-wild, alias legacy y rechazo de modelos inválidos."""
        for m, expected_cr in [("chirp-v6", 12), ("chirp-v6-mini", 10), ("chirp-v6-wild", 12), ("chirp-v5", 12), ("chirp-v4-5", 10)]:
            self.assertEqual(app.validate_udio_model(m), m)
            self.assertEqual(app.get_udio_model_credits(m), expected_cr)

        self.assertEqual(app.validate_udio_model(""), "chirp-v6")
        with self.assertRaises(app.HTTPException) as ctx:
            app.validate_udio_model("modelo-inexistente-999")
        self.assertEqual(ctx.exception.status_code, 400)

    # -------------------------------------------------------------------------
    # 5. Reanudación de tarea recuperada ejecuta 0 POSTs + Passthrough audio autorizado
    # -------------------------------------------------------------------------
    async def test_07_resume_zero_posts_and_preserve_original_audio_route(self):
        """Verifica 0 POSTs al reanudar Work ID existente y verifica que preserve_original_audio omite bypass_audio_fingerprint."""
        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {
            "code": 200,
            "data": {"type": "SUCCESS", "response_data": [{"id": "t_ok", "audio_url": "https://mock/ok.mp3"}]}
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = status_mock

        engine = music_engine_adapter.UdioProEngine()
        logs = []
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            res = await engine.generate_and_poll(
                task_id="resume-task-07",
                payload={"model": "chirp-v6", "style": "worship", "tags": "cumbia", "style_weight": 0.6, "audio_weight": 0.6, "weirdness_constraint": 0.2},
                upload_url="https://n.uguu.se/mock.mp3",
                log_msg=logs.append,
                is_task_cancelled=lambda: False,
                api_key="mock_secret_never_logged",
                resume_work_id="upcov_existing_wid_07",
            )
            self.assertEqual(len(res), 1)
            self.assertEqual(mock_client.post.call_count, 0, "La reanudación jamás debe ejecutar POST")
            self.assertEqual(mock_client.get.call_count, 1)
            joined_logs = "\n".join(logs)
            self.assertNotIn("mock_secret_never_logged", joined_logs)
            self.assertIn("Estado final proveedor [upcov_existing_wid_07]: SUCCESS", joined_logs)

        # Verificar que preserve_original_audio=True NO llama a bypass_audio_fingerprint aunque bypass_copyright=True
        tid = "task-passthrough-07"
        app.TASKS[tid] = {"id": tid, "owner_email": "test@rodrix.com", "logs": "", "status": "IN_PROGRESS"}
        with patch.object(app, "bypass_audio_fingerprint", side_effect=AssertionError("NO debe ejecutar bypass_audio_fingerprint")) as mock_byp, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/clean.wav")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "cache_track_audio", AsyncMock(return_value="/api/audio_file/t_ok")), \
             patch.object(app, "upload_to_catbox_async", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_upload_track_audio", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_id"})), \
             patch("httpx.AsyncClient") as client_cls:
            post_ok = MagicMock()
            post_ok.status_code = 200
            post_ok.json.return_value = {"code": 200, "workId": "upcov_clean_pass"}
            mc = AsyncMock()
            mc.post.return_value = post_ok
            mc.get.return_value = status_mock
            client_cls.return_value.__aenter__.return_value = mc

            src_wav = os.path.join(REPO_DIR, "test.wav")
            if os.path.exists(src_wav):
                with open(src_wav, "rb") as _fw:
                    raw_wav = _fw.read()
            else:
                raw_wav = b"RIFF" + b"\x00" * 2048

            await app.run_transform_task(
                task_id=tid,
                style="Acoustic Worship",
                lyrics="[Verse]\nLetra original autorizada",
                title="Passthrough Test",
                audio_content=raw_wav,
                audio_filename="mi_voz.wav",
                ignore_audio=False,
                include_lyrics=True,
                bypass_copyright=True,  # incluso si estaba marcado, preserve_original_audio lo anula limpiamente
                exclude_styles="",
                vocal_gender="female",
                weirdness=20,
                style_influence=60,
                audio_influence=60,
                model="chirp-v6",
                preserve_original_audio=True,
            )
            self.assertEqual(mock_byp.call_count, 0)
            self.assertIn("Audio original autorizado: preservando tono, tempo y timbre originales", app.TASKS[tid]["logs"])

    # -------------------------------------------------------------------------
    # 6. Verificación de HTML / Frontend (modelos, exclusiones, micrófono intacto)
    # -------------------------------------------------------------------------
    def test_08_index_html_models_exclusions_and_microphone_intact(self):
        """Verifica selector chirp-v6, preservación de opciones legacy, helper de exclusiones y cadena de micrófono intacta."""
        html_path = os.path.join(REPO_DIR, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Modelos nuevos + legacy compatibles
        for m in ["chirp-v6", "chirp-v6-mini", "chirp-v6-wild", "chirp-v5", "chirp-v4-5", "chirp-v3-5"]:
            self.assertIn(f'value="{m}"', html)

        self.assertIn("id=\"chkPreserveOriginalAudio\"", html)
        self.assertIn("mergeUniqueExclusionTags", html)
        self.assertIn("ANTI_SYNTH_BASS_TAGS", html)
        # Cadena física de micrófono Android intacta
        self.assertIn("recMuteGain.connect(recAudioCtx.destination);", html)
        self.assertIn("recMuteGain.gain.value = 0.0;", html)
        # Límites documentados en UI
        self.assertIn('id="lyricsInput" maxlength="5000"', html)
        self.assertIn('id="titleInput" maxlength="100"', html)

    # -------------------------------------------------------------------------
    # 7. Upload & Cover: 1 POST nuevo y ?task_id= con parser unificado (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_09_upload_cover_new_gen_single_post_and_status_task_id(self):
        """[SIMULADO] Nueva generación Upload & Cover prepara 1 solo POST, consulta /upload-cover/status?task_id= y procesa pistas."""
        captured_urls = {"post": [], "get": []}

        async def fake_post(url, headers=None, json=None, **kwargs):
            captured_urls["post"].append((url, dict(json or {})))
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "data": {"task_id": "upcov_sim_new_009"}}
            return m

        async def fake_get(url, headers=None, **kwargs):
            captured_urls["get"].append(url)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "code": 200,
                "data": {
                    "type": "SUCCESS",
                    "response_data": [
                        {"id": "sim_trk_1", "title": "Obra Sim 1", "audio_url": "https://mock.sim/1.mp3", "duration": 140},
                        {"id": "sim_trk_2", "title": "Obra Sim 2", "audio_url": "https://mock.sim/2.mp3", "duration": 141},
                    ],
                },
            }
            return m

        mock_client = AsyncMock()
        mock_client.post.side_effect = fake_post
        mock_client.get.side_effect = fake_get

        engine = music_engine_adapter.UdioProEngine()
        recorded_wids = []
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            tracks = await engine.generate_and_poll(
                task_id="sim-task-09",
                payload={"upload_url": "https://n.uguu.se/sim.mp3", "model": "chirp-v6", "style": "worship", "prompt": "Letra sim"},
                upload_url=None,  # incluso si upload_url arg es None pero está en payload
                log_msg=lambda _m: None,
                is_task_cancelled=lambda: False,
                api_key="mock_sim_key",
                on_work_id=recorded_wids.append,
            )

        self.assertEqual(len(captured_urls["post"]), 1)
        self.assertEqual(captured_urls["post"][0][0], "https://udioapi.pro/api/v2/upload-cover/generate")
        self.assertEqual(recorded_wids, ["upcov_sim_new_009"])
        self.assertEqual(len(captured_urls["get"]), 1)
        self.assertEqual(
            captured_urls["get"][0],
            "https://udioapi.pro/api/v2/upload-cover/status?task_id=upcov_sim_new_009",
        )
        self.assertEqual(len(tracks), 2)
        self.assertEqual([t["id"] for t in tracks], ["sim_trk_1", "sim_trk_2"])

    # -------------------------------------------------------------------------
    # 8. Recuperación Upload & Cover SIN upload_url: ?task_id=, 0 POSTs, IN_PROGRESS -> SUCCESS (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_10_resume_upcov_without_upload_url_uses_task_id_zero_posts(self):
        """[SIMULADO] Recuperación upcov... sin upload_url usa GET /upload-cover/status?task_id=..., 0 POSTs y sigue tras IN_PROGRESS."""
        get_urls = []
        poll_responses = [
            {"code": 200, "data": {"type": "IN_PROGRESS", "response_data": []}},
            {
                "code": 200,
                "data": {
                    "type": "SUCCESS",
                    "response_data": [
                        {"id": "sim_rec_1", "title": "Obra Recuperada Sim", "audio_url": "https://mock.sim/rec1.mp3", "duration": 122}
                    ],
                },
            },
        ]

        async def fake_get(url, headers=None, **kwargs):
            get_urls.append(url)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = poll_responses[min(len(get_urls) - 1, len(poll_responses) - 1)]
            return m

        mock_client = AsyncMock()
        mock_client.get.side_effect = fake_get

        engine = music_engine_adapter.UdioProEngine()
        logs = []
        with patch("httpx.AsyncClient") as client_cls, patch("asyncio.sleep", new_callable=AsyncMock):
            client_cls.return_value.__aenter__.return_value = mock_client
            tracks = await engine.generate_and_poll(
                task_id="sim-task-10",
                payload={"model": "chirp-v6"},  # sin upload_url en payload
                upload_url=None,               # y sin argumento upload_url
                log_msg=logs.append,
                is_task_cancelled=lambda: False,
                api_key="mock_sim_key",
                resume_work_id="upcov_resume_no_url_010",
            )

        self.assertEqual(mock_client.post.call_count, 0, "La reanudación jamás debe ejecutar POST")
        self.assertEqual(len(get_urls), 2, "Tras IN_PROGRESS debe continuar hasta SUCCESS")
        for u in get_urls:
            self.assertEqual(u, "https://udioapi.pro/api/v2/upload-cover/status?task_id=upcov_resume_no_url_010")
            self.assertNotIn("workId=", u)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["id"], "sim_rec_1")
        self.assertIn("IN_PROGRESS", "\n".join(logs))

        # Flujo real de execute_task_recovery con payload vacío en app.TASKS
        tid = "task-rec-app-010"
        app.TASKS[tid] = {
            "id": tid,
            "owner_email": "pastor@rodrix.com",
            "status": "PENDING_VERIFICATION",
            "work_id": "upcov_app_recovery_010",
            "provider_work_id": "upcov_app_recovery_010",
            "title": "Obra Sin URL Guardada",
            "payload": {},
            "logs": "",
        }
        get_urls_app = []
        mock_client_app = AsyncMock()

        async def fake_get_app(url, headers=None, **kwargs):
            get_urls_app.append(url)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "code": 200,
                "data": {
                    "type": "SUCCESS",
                    "response_data": [{"id": "trk_rec_app", "title": "Obra Recuperada", "audio_url": "https://mock.sim/app.mp3", "duration": 95}],
                },
            }
            return m

        mock_client_app.get.side_effect = fake_get_app

        async def sim_cache_app(trk_id, _url):
            out_p = os.path.join(app.TRACKS_DIR, f"{trk_id}.mp3")
            with open(out_p, "wb") as _f:
                _f.write(b"ID3" + b"\x00\xff\xfb\x90\x00" * 400)
            return f"/api/audio_file/{trk_id}"

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "cache_track_audio", AsyncMock(side_effect=sim_cache_app)), \
             patch.object(app, "upload_to_catbox_async", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_upload_track_audio", AsyncMock(return_value={"file_id": "drv_rec_ok", "link": "https://drive.google.com/file/d/drv_rec_ok/view"})), \
             patch.object(app, "gdrive_sync_library_to_cloud", AsyncMock(return_value={"ok": True, "file_id": "drv_lib_rec_010", "tracks_count": 1})), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_tasks_ok"})):
            client_cls.return_value.__aenter__.return_value = mock_client_app
            rec_task = await app.execute_task_recovery(tid)

        self.assertEqual(mock_client_app.post.call_count, 0)
        self.assertEqual(get_urls_app, ["https://udioapi.pro/api/v2/upload-cover/status?task_id=upcov_app_recovery_010"])
        self.assertEqual(rec_task["status"], "COMPLETED")

    # -------------------------------------------------------------------------
    # 9. FAILED conserva error original y Timeout no dispara otro POST (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_11_upload_cover_failed_preserves_error_and_timeout_no_repost(self):
        """[SIMULADO] FAILED conserva el mensaje exacto del proveedor; Timeout termina en ERR_PROCESSING_TIMEOUT con 1 solo POST."""
        # A) FAILED en recuperación (sin upload_url, usando status_json.message y response_data.fail_message)
        fail_client = AsyncMock()
        fail_resp = MagicMock()
        fail_resp.status_code = 200
        fail_resp.json.return_value = {
            "code": 200,
            "data": {
                "type": "FAILED",
                "response_data": [{"status": "FAILED", "fail_message": "Provider original failure: Worker audio codec mismatch"}],
            },
        }
        fail_client.get.return_value = fail_resp

        engine = music_engine_adapter.UdioProEngine()
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = fail_client
            with self.assertRaises(music_engine_adapter.MusicEngineError) as ctx_fail:
                await engine.generate_and_poll(
                    task_id="sim-task-11-fail",
                    payload={},
                    upload_url=None,
                    log_msg=lambda _m: None,
                    is_task_cancelled=lambda: False,
                    api_key="mock_sim_key",
                    resume_work_id="upcov_fail_011",
                )
        self.assertIn("Provider original failure: Worker audio codec mismatch", ctx_fail.exception.message)
        self.assertEqual(fail_client.post.call_count, 0)
        self.assertIn("task_id=upcov_fail_011", fail_client.get.call_args[0][0])

        # Fallback a data.message cuando response_data es [{}] sin fail_message
        fail_resp_msg = MagicMock()
        fail_resp_msg.status_code = 200
        fail_resp_msg.json.return_value = {
            "code": 500,
            "data": {"type": "FAILED", "message": "Top-level simulated queue error", "response_data": [{}]},
        }
        fail_client.get.return_value = fail_resp_msg
        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = fail_client
            with self.assertRaises(music_engine_adapter.MusicEngineError) as ctx_fail_msg:
                await engine.generate_and_poll(
                    task_id="sim-task-11-fail-msg",
                    payload={},
                    upload_url=None,
                    log_msg=lambda _m: None,
                    is_task_cancelled=lambda: False,
                    api_key="mock_sim_key",
                    resume_work_id="upcov_fail_msg_011",
                )
        self.assertIn("Top-level simulated queue error", ctx_fail_msg.exception.message)

        # B) Timeout tras POST inicial -> exactamente 1 POST, nunca reintenta
        post_ok = MagicMock()
        post_ok.status_code = 200
        post_ok.json.return_value = {"code": 200, "workId": "upcov_timeout_sim_011"}
        in_prog = MagicMock()
        in_prog.status_code = 200
        in_prog.json.return_value = {"code": 200, "data": {"type": "IN_PROGRESS", "response_data": []}}

        timeout_client = AsyncMock()
        timeout_client.post.return_value = post_ok
        timeout_client.get.return_value = in_prog

        with patch("httpx.AsyncClient") as client_cls, patch("asyncio.sleep", new_callable=AsyncMock):
            client_cls.return_value.__aenter__.return_value = timeout_client
            with self.assertRaises(music_engine_adapter.MusicEngineError) as ctx_to:
                await engine.generate_and_poll(
                    task_id="sim-task-11-timeout",
                    payload={"upload_url": "https://n.uguu.se/t.mp3", "model": "chirp-v6"},
                    upload_url="https://n.uguu.se/t.mp3",
                    log_msg=lambda _m: None,
                    is_task_cancelled=lambda: False,
                    api_key="mock_sim_key",
                    max_poll_seconds=30,
                )
        self.assertEqual(ctx_to.exception.code, "ERR_PROCESSING_TIMEOUT")
        self.assertTrue(ctx_to.exception.raw_details.get("is_pending_verification"))
        self.assertEqual(timeout_client.post.call_count, 1, "Timeout jamás debe disparar otro POST")
        self.assertGreaterEqual(timeout_client.get.call_count, 3)

    # -------------------------------------------------------------------------
    # 10. Flujo de generación convencional mantiene /api/v2/generate y /feed?workId= (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_12_conventional_generate_uses_feed_work_id_unchanged(self):
        """[SIMULADO] Generación convencional mantiene POST /api/v2/generate y GET /api/v2/feed?workId=..."""
        seen = {"post": [], "get": []}

        async def fake_post(url, headers=None, json=None, **kwargs):
            seen["post"].append(url)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"id": "work_conv_sim_012"}
            return m

        feed_responses = [
            [{"id": "trk_conv_1", "status": "IN_PROGRESS"}],
            [{"id": "trk_conv_1", "status": "SUCCESS", "audio_url": "https://mock.sim/conv.mp3", "title": "Conv Sim"}],
        ]

        async def fake_get(url, headers=None, **kwargs):
            seen["get"].append(url)
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = feed_responses[min(len(seen["get"]) - 1, len(feed_responses) - 1)]
            return m

        conv_client = AsyncMock()
        conv_client.post.side_effect = fake_post
        conv_client.get.side_effect = fake_get

        engine = music_engine_adapter.UdioProEngine()
        with patch("httpx.AsyncClient") as client_cls, patch("asyncio.sleep", new_callable=AsyncMock):
            client_cls.return_value.__aenter__.return_value = conv_client
            tracks = await engine.generate_and_poll(
                task_id="sim-task-12",
                payload={"model": "chirp-v6", "custom_mode": True, "prompt": "[Verse]\nLetra", "style": "Christian rock"},
                upload_url=None,
                log_msg=lambda _m: None,
                is_task_cancelled=lambda: False,
                api_key="mock_sim_key",
            )

        self.assertEqual(seen["post"], ["https://udioapi.pro/api/v2/generate"])
        self.assertEqual(len(seen["get"]), 2)
        for g_url in seen["get"]:
            self.assertEqual(g_url, "https://udioapi.pro/api/v2/feed?workId=work_conv_sim_012")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["id"], "trk_conv_1")

    # -------------------------------------------------------------------------
    # 11. Validación completa de payload y límites en /api/transform + run_transform_task (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_13_payload_limits_and_custom_lyrics_preserved_without_credits(self):
        """[SIMULADO] Valida recorrido /api/transform -> run_transform_task: límites 8min/5000/1000/100 y prompt literal."""
        from fastapi.testclient import TestClient

        app.app.dependency_overrides[app.get_current_user] = lambda: "pastor@rodrix.com"
        client = TestClient(app.app)

        # 1) Rechaza título > 100 caracteres sin consumir créditos ni crear tarea
        r_title = client.post(
            "/api/transform",
            data={"style": "Christian Worship", "lyrics": "[Verse]\nAlabanza", "title": "T" * 101},
        )
        self.assertEqual(r_title.status_code, 400)
        self.assertIn("100 caracteres", r_title.json()["detail"])

        # 2) Rechaza letra > 5000 caracteres sin crear tarea
        r_lyr = client.post(
            "/api/transform",
            data={"style": "Christian Worship", "lyrics": "L" * 5001, "title": "Titulo Valido"},
        )
        self.assertEqual(r_lyr.status_code, 400)
        self.assertIn("5000 caracteres", r_lyr.json()["detail"])

        # 3) Rechaza letra vacía en modo custom con voz para no sustituir 'prompt' por 'style'
        r_empty = client.post(
            "/api/transform",
            data={"style": "Christian Worship", "lyrics": "   ", "title": "Titulo Valido", "include_lyrics": "true"},
        )
        self.assertEqual(r_empty.status_code, 400)

        # 4) Verifica paso de parámetros desde /api/transform con audio válido (<= 8 min) sin ejecutar background real
        src_wav = os.path.join(REPO_DIR, "test.wav")
        with open(src_wav, "rb") as fw:
            wav_bytes = fw.read()

        captured_bg = []
        with patch.object(app.BackgroundTasks, "add_task", side_effect=lambda fn, *args, **kwargs: captured_bg.append((fn, args))):
            r_ok = client.post(
                "/api/transform",
                data={
                    "style": "Christian Worship, acoustic guitar, 84 BPM",
                    "lyrics": "[Verse]\nSubo mi voz hoy\n[Chorus] Te canto solo a Ti",
                    "title": "Cantico Original Test",
                    "include_lyrics": "true",
                    "model": "chirp-v6",
                    "weirdness": "20",
                    "style_influence": "80",
                    "audio_influence": "65",
                    "vocal_gender": "female",
                    "target_bpm": "84",
                    "preserve_original_audio": "true",
                    "lyrics_mode": "custom",
                },
                files={"audio": ("original.wav", wav_bytes, "audio/wav")},
            )
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(len(captured_bg), 1)
        fn, bg_args = captured_bg[0]
        self.assertIs(fn, app.run_transform_task)

        # Ejecutar el worker capturado con Udio/Uguu/Drive SIMULADOS y validar el payload exacto enviado
        captured_posts = []

        async def sim_post(url, headers=None, json=None, **kwargs):
            captured_posts.append((url, dict(json or {})))
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "workId": "upcov_sim_e2e_013"}
            return m

        async def sim_get(url, headers=None, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "data": {"type": "SUCCESS", "response_data": []}}
            return m

        sim_client = AsyncMock()
        sim_client.post.side_effect = sim_post
        sim_client.get.side_effect = sim_get

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/sim_e2e.wav")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_ok"})):
            client_cls.return_value.__aenter__.return_value = sim_client
            await fn(*bg_args)

        self.assertEqual(len(captured_posts), 1)
        post_url, payload = captured_posts[0]
        self.assertEqual(post_url, "https://udioapi.pro/api/v2/upload-cover/generate")
        self.assertEqual(payload["upload_url"], "https://n.uguu.se/sim_e2e.wav")
        self.assertEqual(payload["title"], "Cantico Original Test")
        self.assertLessEqual(len(payload["title"]), 100)
        self.assertTrue(payload["custom_mode"])
        self.assertFalse(payload["make_instrumental"])
        self.assertEqual(payload["model"], "chirp-v6")
        self.assertIn("[Verse]", payload["prompt"])
        self.assertIn("[Chorus] Te canto solo a Ti", payload["prompt"], "No debe borrar etiqueta inline [Chorus]")
        self.assertNotIn("Christian Worship", payload["prompt"], "No debe sustituir prompt por style")
        self.assertLessEqual(len(payload["style"]), 1000)
        self.assertEqual(payload["style_weight"], 0.8)
        self.assertEqual(payload["audio_weight"], 0.65)
        self.assertEqual(payload["weirdness_constraint"], 0.2)

    # -------------------------------------------------------------------------
    # 12. Verificación de descarga MP3, respaldo en Google Drive y biblioteca (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_14_persistence_download_gdrive_and_library_availability(self):
        """[SIMULADO] Verifica descarga de pista tras SUCCESS, respaldo confirmado en Drive y disponibilidad en /api/library y /api/audio_file."""
        from fastapi.testclient import TestClient

        sim_mp3_bytes = b"ID3" + b"\x00\xff\xfb\x90\x00" * 400  # > 1000 bytes
        tid = "task-persist-sim-014"
        app.TASKS[tid] = {"id": tid, "owner_email": "pastor@rodrix.com", "logs": "", "status": "IN_PROGRESS"}

        async def sim_cache(track_id, remote_url):
            out_p = os.path.join(app.TRACKS_DIR, f"{track_id}.mp3")
            with open(out_p, "wb") as f:
                f.write(sim_mp3_bytes)
            return f"/api/audio_file/{track_id}"

        async def sim_post(url, headers=None, json=None, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "workId": "upcov_sim_persist_014"}
            return m

        async def sim_get(url, headers=None, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "code": 200,
                "data": {
                    "type": "SUCCESS",
                    "response_data": [
                        {"id": "sim_track_persist_1", "title": "Obra Persistida Sim", "audio_url": "https://cdn.sim/t1.mp3", "duration": 180}
                    ],
                },
            }
            return m

        mc = AsyncMock()
        mc.post.side_effect = sim_post
        mc.get.side_effect = sim_get

        src_wav = os.path.join(REPO_DIR, "test.wav")
        with open(src_wav, "rb") as fw:
            wav_bytes = fw.read()

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/sim_p.wav")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "cache_track_audio", AsyncMock(side_effect=sim_cache)), \
             patch.object(app, "upload_to_catbox_async", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_upload_or_update", AsyncMock(return_value={"file_id": "drv_mp3_confirmed_014", "webViewLink": "https://drive.google.com/file/d/drv_mp3_confirmed_014/view"})), \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value={"file_id": "drv_tasks_ok"})):
            client_cls.return_value.__aenter__.return_value = mc
            # Permitir gdrive_get_access_token mockeado solo dentro de este test para ejercitar gdrive_upload_track_audio real
            with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_token")):
                await app.run_transform_task(
                    task_id=tid,
                    style="Christian Worship",
                    lyrics="[Verse]\nAlabanza original",
                    title="Obra Persistida Sim",
                    audio_content=wav_bytes,
                    audio_filename="original.wav",
                    ignore_audio=False,
                    include_lyrics=True,
                    bypass_copyright=False,
                    exclude_styles="",
                    vocal_gender="female",
                    weirdness=25,
                    style_influence=75,
                    audio_influence=60,
                    model="chirp-v6",
                    preserve_original_audio=True,
                )

        t_done = app.TASKS[tid]
        self.assertEqual(t_done["status"], "COMPLETED")
        self.assertTrue(t_done["is_permanently_saved"])
        self.assertEqual(t_done["persistence_status"], "PERSISTED_GDRIVE")
        lib = app.load_library()
        saved_tr = next((x for x in lib if x.get("id") == "sim_track_persist_1"), None)
        self.assertIsNotNone(saved_tr)
        self.assertEqual(saved_tr["gdrive_id"], "drv_mp3_confirmed_014")
        self.assertTrue(saved_tr["is_permanently_saved"])

        # Verificar disponibilidad en /api/library y recuperación de audio desde Drive si se borra el archivo local efímero
        os.remove(os.path.join(app.TRACKS_DIR, "sim_track_persist_1.mp3"))
        app.app.dependency_overrides[app.get_current_user] = lambda: app.ADMIN_EMAIL
        client = TestClient(app.app)
        r_lib = client.get("/api/library")
        self.assertEqual(r_lib.status_code, 200)
        self.assertTrue(any(x["id"] == "sim_track_persist_1" for x in r_lib.json()["tracks"]))

        with patch.object(app, "gdrive_download_file_bytes", AsyncMock(return_value=sim_mp3_bytes)) as mock_dl:
            r_audio = client.get("/api/audio_file/sim_track_persist_1")
            self.assertEqual(r_audio.status_code, 200)
            self.assertEqual(r_audio.content, sim_mp3_bytes)
            mock_dl.assert_awaited_once_with("drv_mp3_confirmed_014")
        self.assertEqual(saved_tr.get("owner_email"), "pastor@rodrix.com")

    # -------------------------------------------------------------------------
    # 13. Reinicio de Render -> Recuperación automática segura + aislamiento (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_15_startup_auto_recovery_and_user_session_isolation(self):
        """[SIMULADO] Reinicio con Work ID reanuda automáticamente por GET (0 POSTs), descarga MP3, confirma library.json y aísla usuarios."""
        from fastapi.testclient import TestClient

        sim_mp3_bytes = b"ID3" + b"\x00\xff\xfb\x90\x00" * 400
        task_a = "task-restart-user-a-015"
        task_b = "task-restart-user-b-015"
        cloud_tasks = {
            task_a: {
                "id": task_a,
                "task_id": task_a,
                "work_id": "upcov_restart_auto_015",
                "provider_work_id": "upcov_restart_auto_015",
                "owner_email": "usuario_a@iglesia.com",
                "title": "Himno Usuario A",
                "status": "IN_PROGRESS",
                "model": "chirp-v6",
                "payload": {"upload_url": "https://n.uguu.se/a.wav", "model": "chirp-v6", "style": "worship"},
                "created_at": time.time(),
                "updated_at": time.time(),
            },
            task_b: {
                "id": task_b,
                "task_id": task_b,
                "work_id": "upcov_restart_user_b_015",
                "provider_work_id": "upcov_restart_user_b_015",
                "owner_email": "usuario_b@iglesia.com",
                "title": "Himno Usuario B",
                "status": "IN_PROGRESS",
                "model": "chirp-v6",
                "payload": {"upload_url": "https://n.uguu.se/b.wav", "model": "chirp-v6", "style": "hymn"},
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        }
        cloud_tasks_bytes = json.dumps(cloud_tasks).encode("utf-8")

        # Borrar estado local para simular contenedor efímero nuevo
        app.TASKS.clear()
        if os.path.exists(app.GENERATION_TASKS_FILE):
            os.remove(app.GENERATION_TASKS_FILE)
        if os.path.exists(app.LIBRARY_FILE):
            os.remove(app.LIBRARY_FILE)

        get_calls = []
        post_calls = []

        async def fake_post(url, *args, **kwargs):
            post_calls.append(url)
            raise AssertionError("Recuperación automática NUNCA debe ejecutar POST de generación")

        async def fake_get(url, *args, **kwargs):
            get_calls.append(url)
            m = MagicMock()
            m.status_code = 200
            if "upcov_restart_auto_015" in url:
                m.json.return_value = {
                    "code": 200,
                    "data": {
                        "type": "SUCCESS",
                        "response_data": [{"id": "trk_auto_a1", "title": "Himno Usuario A", "audio_url": "https://cdn.sim/a1.mp3", "duration": 160}],
                    },
                }
            elif "upcov_restart_user_b_015" in url:
                # Usuario B sigue IN_PROGRESS inicialmente en este test para comprobar aislamiento de sesión
                m.json.return_value = {"code": 200, "data": {"type": "IN_PROGRESS", "response_data": []}}
            else:
                m.json.return_value = {"files": []}
            return m

        mc = AsyncMock()
        mc.post.side_effect = fake_post
        mc.get.side_effect = fake_get

        async def fake_cache(tid_tr, url):
            out = os.path.join(app.TRACKS_DIR, f"{tid_tr}.mp3")
            with open(out, "wb") as f:
                f.write(sim_mp3_bytes)
            return f"/api/audio_file/{tid_tr}"

        async def fake_cloud_find(fname, folder_id=None, token=None):
            if fname == app.GENERATION_TASKS_FILE:
                return {"id": "drv_tasks_file_015"}
            return None

        async def fake_cloud_dl(fid, token=None):
            if fid == "drv_tasks_file_015":
                return cloud_tasks_bytes
            return None

        drive_uploads = []

        async def fake_upload_or_update(fname, content_bytes, mime_type="application/octet-stream", folder_id=None):
            drive_uploads.append((fname, len(content_bytes)))
            return {"file_id": f"drv_{fname}_015", "webViewLink": f"https://drive.google.com/file/d/drv_{fname}_015/view"}

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok")), \
             patch.object(app, "gdrive_sync_deleted_tracks_from_cloud", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_sync_users_from_cloud", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_sync_library_from_cloud", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_find_file", AsyncMock(side_effect=fake_cloud_find)), \
             patch.object(app, "gdrive_download_file_bytes", AsyncMock(side_effect=fake_cloud_dl)), \
             patch.object(app, "gdrive_upload_or_update", AsyncMock(side_effect=fake_upload_or_update)), \
             patch.object(app, "cache_track_audio", AsyncMock(side_effect=fake_cache)), \
             patch.object(app, "upload_to_catbox_async", AsyncMock(return_value=None)):
            client_cls.return_value.__aenter__.return_value = mc

            # Pausar tarea B para que startup no bloquee loop con max_poll_seconds largo:
            # Cancelar tarea B después de comprobar aislamiento en /api/tasks/pending
            await app.startup_event()

            # Dar un instante al task programado para A y verificar aislamiento para A antes de que B termine
            await asyncio.sleep(0.05)

            # Comprobar aislamiento estricto de sesión para Usuario A vs Usuario B en /api/tasks/pending
            client = TestClient(app.app)
            app.app.dependency_overrides[app.get_current_user] = lambda: "usuario_a@iglesia.com"
            r_pend_a = client.get("/api/tasks/pending")
            self.assertEqual(r_pend_a.status_code, 200)
            ids_a = [p["task_id"] for p in r_pend_a.json()["pending_tasks"]]
            self.assertNotIn(task_b, ids_a, "Usuario A jamás debe ver tareas pendientes de Usuario B")

            app.app.dependency_overrides[app.get_current_user] = lambda: "usuario_b@iglesia.com"
            r_pend_b = client.get("/api/tasks/pending")
            self.assertEqual(r_pend_b.status_code, 200)
            ids_b = [p["task_id"] for p in r_pend_b.json()["pending_tasks"]]
            self.assertIn(task_b, ids_b)
            self.assertNotIn(task_a, ids_b, "Usuario B jamás debe ver tareas de Usuario A")

            # Esperar a que termine la recuperación automática de A y cancelar suavemente polling de B
            app.TASKS[task_b]["status"] = "CANCELLED"
            for fut in list(app._recovery_tasks.values()):
                try:
                    await asyncio.wait_for(fut, timeout=2.0)
                except Exception:
                    pass

        self.assertEqual(len(post_calls), 0, "Cero POSTs de generación durante toda la recuperación")
        self.assertTrue(any("upcov_restart_auto_015" in u and "task_id=" in u for u in get_calls))
        t_a_done = app.TASKS[task_a]
        self.assertEqual(t_a_done["status"], "COMPLETED")
        self.assertTrue(t_a_done["library_persisted"])
        self.assertTrue(t_a_done["is_permanently_saved"])
        self.assertEqual(t_a_done["persistence_status"], "PERSISTED_GDRIVE")

        lib = app.load_library()
        saved_a = next((x for x in lib if x.get("id") == "trk_auto_a1"), None)
        self.assertIsNotNone(saved_a)
        self.assertEqual(saved_a.get("owner_email"), "usuario_a@iglesia.com")
        self.assertEqual(saved_a.get("gdrive_id"), "drv_trk_auto_a1.mp3_015")
        self.assertTrue(any(fn == app.LIBRARY_FILE for fn, _ in drive_uploads))

    # -------------------------------------------------------------------------
    # 14. Bloqueo sin Work ID, protección de terminales y anti-concurrencia (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_16_no_auto_resume_without_work_id_terminal_intact_and_dedup(self):
        """[SIMULADO] Tareas sin Work ID o en estado terminal NO se reanudan ni alteran; concurrencia se deduplica."""
        from fastapi.testclient import TestClient

        t_no_wid = "task-no-wid-016"
        t_completed = "task-term-comp-016"
        t_error = "task-term-err-016"
        t_cancelled = "task-term-canc-016"
        t_active = "task-dedup-conc-016"

        app.TASKS[t_no_wid] = {"id": t_no_wid, "owner_email": "u1@iglesia.com", "status": "PENDING_VERIFICATION", "work_id": "", "logs": "init"}
        app.TASKS[t_completed] = {"id": t_completed, "owner_email": "u1@iglesia.com", "status": "COMPLETED", "work_id": "upcov_done_016", "tracks": [{"id": "trk_old"}], "logs": "done"}
        app.TASKS[t_error] = {"id": t_error, "owner_email": "u1@iglesia.com", "status": "ERROR", "work_id": "upcov_err_016", "detail": "Original failure", "logs": "err"}
        app.TASKS[t_cancelled] = {"id": t_cancelled, "owner_email": "u1@iglesia.com", "status": "CANCELLED", "work_id": "upcov_canc_016", "logs": "canc"}
        app.TASKS[t_active] = {"id": t_active, "owner_email": "u1@iglesia.com", "status": "PENDING_VERIFICATION", "work_id": "upcov_conc_016", "payload": {}, "logs": ""}

        # 1. Sin Work ID -> no programa recuperación
        res_no_wid = app.schedule_task_recovery(t_no_wid)
        self.assertFalse(res_no_wid["scheduled"])
        self.assertEqual(res_no_wid["reason"], "missing_work_id")

        # 2. Estados terminales -> nunca programa recuperación
        for tid_t in (t_completed, t_error, t_cancelled):
            r_t = app.schedule_task_recovery(tid_t)
            self.assertFalse(r_t["scheduled"])
            self.assertEqual(r_t["reason"], "terminal")
            same = await app._do_execute_task_recovery(tid_t)
            self.assertEqual(same["status"], app.TASKS[tid_t]["status"])

        client = TestClient(app.app)
        app.app.dependency_overrides[app.get_current_user] = lambda: "u1@iglesia.com"

        r_400 = client.post(f"/api/task/{t_no_wid}/resume")
        self.assertEqual(r_400.status_code, 400)

        for tid_t, exp_s in [(t_completed, "COMPLETED"), (t_error, "ERROR"), (t_cancelled, "CANCELLED")]:
            r_term = client.post(f"/api/task/{tid_t}/resume")
            self.assertEqual(r_term.status_code, 200)
            self.assertTrue(r_term.json()["already_terminal"])
            self.assertEqual(r_term.json()["status"], exp_s)
        self.assertEqual(app.TASKS[t_error]["detail"], "Original failure")

        # 3. Concurrencia / duplicados sobre t_active -> exactamente 1 ejecución GET y 0 POSTs
        slow_gate = asyncio.Event()
        get_hits = 0

        async def slow_get(url, *args, **kwargs):
            nonlocal get_hits
            get_hits += 1
            await slow_gate.wait()
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "data": {"type": "FAILED", "response_data": [{"fail_message": "Simulated stopped"}]}}
            return m

        mc = AsyncMock()
        mc.get.side_effect = slow_get

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "gdrive_sync_generation_tasks_to_cloud", AsyncMock(return_value=None)):
            client_cls.return_value.__aenter__.return_value = mc
            s1 = app.schedule_task_recovery(t_active)
            s2 = app.schedule_task_recovery(t_active)
            s3 = app.schedule_task_recovery(t_active)
            self.assertTrue(s1["scheduled"])
            self.assertFalse(s2["scheduled"])
            self.assertEqual(s2["reason"], "already_resuming")
            self.assertFalse(s3["scheduled"])
            await asyncio.sleep(0.02)
            slow_gate.set()
            await app._recovery_tasks[t_active]

        self.assertEqual(mc.post.call_count, 0)
        self.assertEqual(get_hits, 1, "Debe ejecutarse exactamente 1 sondeo ante reanudaciones concurrentes")

    # -------------------------------------------------------------------------
    # 15. Fallo temporal Drive/library.json: no completa, conserva datos y recupera sin regenerar (SIMULADO)
    # -------------------------------------------------------------------------
    async def test_17_library_sync_failure_preserves_data_other_users_and_recovers_without_regen(self):
        """[SIMULADO] Fallo al sincronizar library.json impide COMPLETED, no borra otros usuarios, no re-genera y recupera luego."""
        sim_mp3_bytes = b"ID3" + b"\x00\xff\xfb\x90\x00" * 400
        # Sembrar una canción previa de OTRO usuario en library.json para comprobar no sobrescritura/pérdida
        existing_other = {
            "id": "existing_other_track_999",
            "title": "Himno Previo Otro Usuario",
            "audio_url": "/api/audio_file/existing_other_track_999",
            "gdrive_id": "drv_other_999",
            "owner_email": "otro_usuario@iglesia.com",
            "is_permanently_saved": True,
            "persistence_status": "PERSISTED_GDRIVE",
            "updated_at": time.time() - 500,
        }
        app.save_library_atomic([existing_other])

        tid = "task-lib-fail-017"
        app.TASKS[tid] = {
            "id": tid,
            "owner_email": "cantante@iglesia.com",
            "status": "IN_PROGRESS",
            "title": "Cantico Nuevo",
            "logs": "",
        }

        async def sim_post(url, headers=None, json=None, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {"code": 200, "workId": "upcov_lib_fail_017"}
            return m

        async def sim_get(url, headers=None, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = {
                "code": 200,
                "data": {
                    "type": "SUCCESS",
                    "response_data": [
                        {"id": "trk_new_17a", "title": "Cantico Nuevo 1", "audio_url": "https://cdn.sim/17a.mp3", "duration": 130},
                        {"id": "trk_new_17b", "title": "Cantico Nuevo 2", "audio_url": "https://cdn.sim/17b.mp3", "duration": 131},
                    ],
                },
            }
            return m

        mc = AsyncMock()
        mc.post.side_effect = sim_post
        mc.get.side_effect = sim_get

        async def sim_cache(track_id, remote_url):
            out_p = os.path.join(app.TRACKS_DIR, f"{track_id}.mp3")
            with open(out_p, "wb") as f:
                f.write(sim_mp3_bytes)
            return f"/api/audio_file/{track_id}"

        src_wav = os.path.join(REPO_DIR, "test.wav")
        with open(src_wav, "rb") as fw:
            wav_bytes = fw.read()

        # Simular MP3 subido OK a Drive, pero fallo temporal de Drive al subir library.json (library.json -> None)
        async def fail_on_library_upload(fname, content_bytes, mime_type="application/octet-stream", folder_id=None):
            if fname == app.LIBRARY_FILE:
                app.LAST_GDRIVE_ERROR["error"] = "Error 503: Drive metadata temporary error"
                return None
            return {"file_id": f"drv_{fname}", "webViewLink": f"https://drive.google.com/file/d/drv_{fname}/view"}

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "upload_to_uguu_async", AsyncMock(return_value="https://n.uguu.se/sim17.wav")), \
             patch.object(app, "verify_public_audio_url_async", AsyncMock(return_value=True)), \
             patch.object(app, "cache_track_audio", AsyncMock(side_effect=sim_cache)), \
             patch.object(app, "upload_to_catbox_async", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok")), \
             patch.object(app, "gdrive_find_file", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_upload_or_update", AsyncMock(side_effect=fail_on_library_upload)):
            client_cls.return_value.__aenter__.return_value = mc
            await app.run_transform_task(
                task_id=tid,
                style="Christian Worship",
                lyrics="[Verse]\nLetra fiel original",
                title="Cantico Nuevo",
                audio_content=wav_bytes,
                audio_filename="original.wav",
                ignore_audio=False,
                include_lyrics=True,
                bypass_copyright=False,
                exclude_styles="",
                vocal_gender="female",
                weirdness=20,
                style_influence=75,
                audio_influence=60,
                model="chirp-v6",
                preserve_original_audio=True,
            )

        # Verificaciones tras fallo de library.json:
        self.assertEqual(mc.post.call_count, 1, "No debe repetir generación ante fallo de almacenamiento")
        t_pending = app.TASKS[tid]
        self.assertNotEqual(t_pending["status"], "COMPLETED", "NO debe declarar COMPLETED si library.json falló")
        self.assertEqual(t_pending["status"], "PENDING_PERSISTENCE")
        self.assertFalse(t_pending["library_persisted"])
        self.assertEqual(t_pending["persistence_status"], "PENDING_LIBRARY_SYNC")
        self.assertTrue(app._has_pending_library_metadata_sync())

        # Local library conserva la canción previa del otro usuario + las 2 nuevas con su owner_email, sin duplicados
        lib_now = app.load_library()
        ids_now = [x["id"] for x in lib_now]
        self.assertEqual(len(ids_now), 3)
        self.assertIn("existing_other_track_999", ids_now)
        other_tr = next(x for x in lib_now if x["id"] == "existing_other_track_999")
        self.assertEqual(other_tr["owner_email"], "otro_usuario@iglesia.com")
        for new_id in ("trk_new_17a", "trk_new_17b"):
            tr = next(x for x in lib_now if x["id"] == new_id)
            self.assertEqual(tr["owner_email"], "cantante@iglesia.com")
            self.assertEqual(tr["gdrive_id"], f"drv_{new_id}.mp3")

        # Simular recuperación posterior (ej: tras reinicio o reintento cuando Drive vuelve) -> 0 llamadas a UdioAPI
        async def recover_upload_ok(fname, content_bytes, mime_type="application/octet-stream", folder_id=None):
            return {"file_id": f"drv_recovered_{fname}", "webViewLink": "https://drive.google.com/view"}

        mc_zero = AsyncMock()
        mc_zero.post.side_effect = AssertionError("0 POSTs en recuperación de persistencia")
        mc_zero.get.side_effect = AssertionError("0 GETs a Udio cuando las pistas ya fueron obtenidas")

        with patch("httpx.AsyncClient") as client_cls, \
             patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok")), \
             patch.object(app, "gdrive_find_file", AsyncMock(return_value=None)), \
             patch.object(app, "gdrive_upload_or_update", AsyncMock(side_effect=recover_upload_ok)):
            client_cls.return_value.__aenter__.return_value = mc_zero
            app.recover_pending_generation_tasks()
            self.assertEqual(app.TASKS[tid]["status"], "PENDING_PERSISTENCE")
            await app.recover_pending_uploads()

        t_final = app.TASKS[tid]
        self.assertEqual(t_final["status"], "COMPLETED")
        self.assertTrue(t_final["library_persisted"])
        self.assertTrue(t_final["is_permanently_saved"])
        self.assertEqual(t_final["persistence_status"], "PERSISTED_GDRIVE")
        self.assertFalse(app._has_pending_library_metadata_sync())
        # Verificar cero duplicados tras recuperación
        lib_after = app.load_library()
        self.assertEqual(len(lib_after), 3)

    # -------------------------------------------------------------------------
    # 16. Recuperación de pista tras borrar disco local y verificación de auto-resume en index.html
    # -------------------------------------------------------------------------
    async def test_18_lost_local_files_cloud_restore_and_index_auto_resume_markup(self):
        """[SIMULADO] Pérdida de archivos locales restaura desde Drive conservando owner_email y sin duplicar; index.html reanuda seguro."""
        from fastapi.testclient import TestClient

        sim_mp3 = b"ID3" + b"\x00\xff\xfb\x90\x00" * 400
        cloud_lib = [
            {
                "id": "trk_lost_local_018",
                "title": "Himno En La Nube",
                "audio_url": "/api/audio_file/trk_lost_local_018",
                "gdrive_id": "drv_cloud_mp3_018",
                "owner_email": "miembro@iglesia.com",
                "is_permanently_saved": True,
                "persistence_status": "PERSISTED_GDRIVE",
                "updated_at": time.time(),
            }
        ]
        # Simular disco efímero completamente limpio
        if os.path.exists(app.LIBRARY_FILE):
            os.remove(app.LIBRARY_FILE)
        local_mp3_path = os.path.join(app.TRACKS_DIR, "trk_lost_local_018.mp3")
        if os.path.exists(local_mp3_path):
            os.remove(local_mp3_path)

        with patch.object(app, "gdrive_get_access_token", AsyncMock(return_value="mock_tok")), \
             patch.object(app, "gdrive_find_file", AsyncMock(return_value={"id": "drv_lib_file_018"})), \
             patch.object(app, "gdrive_download_file_bytes", AsyncMock(return_value=json.dumps(cloud_lib).encode("utf-8"))):
            await app.gdrive_sync_library_from_cloud()

        restored_lib = app.load_library()
        self.assertEqual(len(restored_lib), 1)
        self.assertEqual(restored_lib[0]["owner_email"], "miembro@iglesia.com")

        app.app.dependency_overrides[app.get_current_user] = lambda: app.ADMIN_EMAIL
        client = TestClient(app.app)
        with patch.object(app, "gdrive_download_file_bytes", AsyncMock(return_value=sim_mp3)) as dl_spy:
            resp = client.get("/api/audio_file/trk_lost_local_018")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content, sim_mp3)
            dl_spy.assert_awaited_once_with("drv_cloud_mp3_018")

        with open(os.path.join(REPO_DIR, "index.html"), "r", encoding="utf-8") as f_html:
            html = f_html.read()
        self.assertIn("function requestSafeTaskResume(", html)
        self.assertIn("isVerifiableWorkId(", html)
        self.assertIn("autoResumeRequestedTasks", html)
        self.assertIn("PENDING_PERSISTENCE", html)


if __name__ == "__main__":
    unittest.main()
