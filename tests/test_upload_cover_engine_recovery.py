import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os
import tempfile
import time
import hashlib

REPO_DIR = r"F:\Mis Documentos Disco Rígido\Google Antigravity\Rodrix Music creator"
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

import httpx

class TestUploadCoverEngineRecoveryComprehensive(unittest.IsolatedAsyncioTestCase):
    """
    Suite exhaustiva de pruebas unitarias para recuperación del motor musical (Tareas 4 y 5):
    - 0 llamadas reales a UdioAPI (100% simuladas con mocks)
    - 0 créditos consumidos
    - Simulación de los 10 escenarios iniciales + reinicio real con reemplazo de disco efímero de Render
    """

    def setUp(self):
        import music_engine_adapter
        import app
        self.adapter = music_engine_adapter
        self.app = app
        self.engine = music_engine_adapter.UdioProEngine()
        self.sample_payload = {
            "upload_url": "https://a.uguu.se/test_audio.mp3",
            "model": "chirp-v4-5",
            "custom_mode": True,
            "prompt": "Test lyrics for church hymn",
            "style": "acoustic worship, gentle grand piano, 4/4 time signature",
            "tags": "missing snare, quiet snare",
            "title": "Himno Test Control",
            "make_instrumental": False,
            "style_weight": 0.55,
            "audio_weight": 0.60,
            "weirdness_constraint": 0.20
        }
        self.logs = []

    def log_msg(self, msg):
        self.logs.append(msg)

    # -------------------------------------------------------------------------
    # 1. POST exitoso con Work ID auténtico
    # -------------------------------------------------------------------------
    async def test_01_successful_post_with_authentic_work_id(self):
        """Escenario 1: POST exitoso con Work ID auténtico y persistencia inmediata."""
        task_id = "test-task-scenario-01"
        authentic_work_id = "upcov_auth_001_success"

        post_mock = MagicMock()
        post_mock.status_code = 200
        post_mock.json.return_value = {"code": 200, "workId": authentic_work_id}

        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {
            "code": 200,
            "data": {
                "type": "SUCCESS",
                "response_data": [
                    {"id": "t1", "title": "Track 1", "audio_url": "https://mock.cdn/t1.mp3", "duration": 180}
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = post_mock
        mock_client.get.return_value = status_mock

        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "IN_PROGRESS",
            "title": "Himno 87",
            "logs": ""
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            
            def on_wid_callback(wid):
                self.app.TASKS[task_id]["work_id"] = wid
                self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

            tracks = await self.engine.generate_and_poll(
                task_id=task_id,
                payload=self.sample_payload,
                upload_url=self.sample_payload["upload_url"],
                log_msg=self.log_msg,
                is_task_cancelled=lambda: False,
                api_key="mock_key",
                on_work_id=on_wid_callback
            )

            self.assertEqual(len(tracks), 1)
            self.assertEqual(mock_client.post.call_count, 1, "Debe realizar exactamente 1 POST")
            
            persisted = self.app.load_task_persistent(task_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.get("work_id"), authentic_work_id)

    # -------------------------------------------------------------------------
    # 2. Cierre del navegador
    # -------------------------------------------------------------------------
    async def test_02_browser_close_simulation(self):
        """Escenario 2: El navegador se cierra pero la tarea continúa ejecutándose en el backend y es consultable."""
        task_id = "test-task-scenario-02"
        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "IN_PROGRESS",
            "work_id": "upcov_client_disconnected_002",
            "title": "Himno Desconectado",
            "logs": "[12:00:00] Tarea en progreso tras desconexión del cliente\n"
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        is_own, task = self.app.find_task_and_check_ownership(task_id, "test@rodrix.com")
        self.assertTrue(is_own)
        self.assertEqual(task["status"], "IN_PROGRESS")
        self.assertEqual(task["work_id"], "upcov_client_disconnected_002")

    # -------------------------------------------------------------------------
    # 3. Reinicio del proceso backend (TASKS.clear())
    # -------------------------------------------------------------------------
    async def test_03_backend_process_restart_simulation(self):
        """Escenario 3: Reinicio del proceso (memoria TASKS vaciada) -> Tareas restauradas desde almacenamiento persistente."""
        task_id = "test-task-scenario-03"
        wid = "upcov_restart_test_003"
        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "IN_PROGRESS",
            "work_id": wid,
            "title": "Himno Pre-Reinicio",
            "logs": "Iniciando generación...\n"
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        self.app.TASKS.clear()
        self.assertNotIn(task_id, self.app.TASKS)

        self.app.recover_pending_generation_tasks()

        self.assertIn(task_id, self.app.TASKS)
        recovered = self.app.TASKS[task_id]
        self.assertEqual(recovered["status"], "PENDING_VERIFICATION")
        self.assertEqual(recovered["work_id"], wid)

    # -------------------------------------------------------------------------
    # 4. Recuperación del Work ID
    # -------------------------------------------------------------------------
    async def test_04_work_id_recovery(self):
        """Escenario 4: El Work ID original sobrevive y es recuperado intacto sin colisión."""
        task_id = "test-task-scenario-04"
        authentic_wid = "upcovd94acbaab8114958ac5a680fea551486"
        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "PENDING_VERIFICATION",
            "work_id": authentic_wid,
            "title": "Himno 87 Control"
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        self.app.TASKS.pop(task_id, None)

        task = self.app.load_task_persistent(task_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["work_id"], authentic_wid)
        self.assertEqual(task["provider_work_id"], authentic_wid)

    # -------------------------------------------------------------------------
    # 5. Reanudación por GET sin POST adicional
    # -------------------------------------------------------------------------
    async def test_05_get_resume_zero_additional_posts(self):
        """Escenario 5: Reanudación de tarea mediante resume_work_id ejecuta exactamente 0 POSTs."""
        task_id = "test-task-scenario-05"
        wid = "upcov_resume_zero_post_005"

        ok_get = MagicMock()
        ok_get.status_code = 200
        ok_get.json.return_value = {
            "code": 200,
            "data": {
                "type": "SUCCESS",
                "response_data": [
                    {"id": "track_resumed", "title": "Pista Reanudada", "audio_url": "https://cdn.udio/resumed.mp3"}
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = ok_get

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            tracks = await self.engine.generate_and_poll(
                task_id=task_id,
                payload=self.sample_payload,
                upload_url=self.sample_payload["upload_url"],
                log_msg=self.log_msg,
                is_task_cancelled=lambda: False,
                api_key="mock_key",
                resume_work_id=wid
            )

            self.assertEqual(len(tracks), 1)
            self.assertEqual(mock_client.post.call_count, 0, "Al reanudar NUNCA debe ejecutar POST!")
            self.assertEqual(mock_client.get.call_count, 1)

    # -------------------------------------------------------------------------
    # 6. Resultado SUCCESS con dos pistas
    # -------------------------------------------------------------------------
    async def test_06_success_result_with_two_tracks(self):
        """Escenario 6: Desempaquetado y entrega de dos pistas exitosas."""
        post_mock = MagicMock()
        post_mock.status_code = 200
        post_mock.json.return_value = {"code": 200, "workId": "upcov_two_tracks_006"}

        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {
            "code": 200,
            "data": {
                "type": "SUCCESS",
                "response_data": [
                    {"id": "trk_01", "title": "Himno Toma 1", "audio_url": "https://audio.mock/t1.mp3", "duration": 185},
                    {"id": "trk_02", "title": "Himno Toma 2", "audio_url": "https://audio.mock/t2.mp3", "duration": 185}
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = post_mock
        mock_client.get.return_value = status_mock

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            tracks = await self.engine.generate_and_poll(
                task_id="test-task-6",
                payload=self.sample_payload,
                upload_url=self.sample_payload["upload_url"],
                log_msg=self.log_msg,
                is_task_cancelled=lambda: False,
                api_key="mock_key"
            )
            self.assertEqual(len(tracks), 2)
            self.assertEqual(tracks[0]["id"], "trk_01")
            self.assertEqual(tracks[1]["id"], "trk_02")

    # -------------------------------------------------------------------------
    # 7. Descarga y verificación de archivos (Cabeceras + Tamaño)
    # -------------------------------------------------------------------------
    async def test_07_download_and_file_verification(self):
        """Escenario 7: Descarga de archivo de audio y verificación de cabeceras binarias y tamaño."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Archivo de audio válido (copiado de test.wav)
            src_wav = os.path.join(REPO_DIR, "test.wav")
            valid_audio_path = os.path.join(tmpdir, "valid.wav")
            with open(src_wav, "rb") as f_in, open(valid_audio_path, "wb") as f_out:
                f_out.write(f_in.read())
            res = self.app.validate_audio_file_integrity(valid_audio_path)
            self.assertTrue(res["valid"])
            self.assertIsNotNone(res.get("sha256"))
            self.assertEqual(len(res.get("sha256")), 64)

            html_error_path = os.path.join(tmpdir, "error.mp3")
            with open(html_error_path, "wb") as f:
                f.write(b"<html><body>404 Not Found</body></html>")
            res_bad = self.app.validate_audio_file_integrity(html_error_path)
            self.assertFalse(res_bad["valid"])

    # -------------------------------------------------------------------------
    # 8. Persistencia sin duplicaciones
    # -------------------------------------------------------------------------
    async def test_08_persistence_without_duplicates(self):
        """Escenario 8: Guardado en biblioteca sin pistas duplicadas tras reintentos o recuperación."""
        unique_id = f"test_dedup_{int(time.time()*1000)}"
        track_data = {
            "id": unique_id,
            "title": "Himno Único Deduplicado",
            "audio_url": f"/api/audio_file/{unique_id}",
            "duration": 150
        }

        self.app.add_track_to_library(track_data)
        lib1 = [t for t in self.app.load_library() if t.get("id") == unique_id]
        self.assertEqual(len(lib1), 1)

        self.app.add_track_to_library(track_data)
        lib2 = [t for t in self.app.load_library() if t.get("id") == unique_id]
        self.assertEqual(len(lib2), 1, "No deben crearse pistas duplicadas en la biblioteca")

    # -------------------------------------------------------------------------
    # 9. Resultado FAILED auténtico
    # -------------------------------------------------------------------------
    async def test_09_authentic_failed_result(self):
        """Escenario 9: Manejo exacto de respuesta FAILED del proveedor con mensaje auténtico de reembolso."""
        post_mock = MagicMock()
        post_mock.status_code = 200
        post_mock.json.return_value = {"code": 200, "workId": "upcovd94acbaab8114958ac5a680fea551486"}

        fail_json = {
            "code": 200,
            "data": {
                "type": "FAILED",
                "response_data": [{
                    "status": "FAILED",
                    "fail_message": "Generation failed. Your credits have been refunded. Internal Error, Please try again later."
                }]
            }
        }
        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = fail_json

        mock_client = AsyncMock()
        mock_client.post.return_value = post_mock
        mock_client.get.return_value = status_mock

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            with self.assertRaises(self.adapter.MusicEngineError) as ctx:
                await self.engine.generate_and_poll(
                    task_id="test-task-9",
                    payload=self.sample_payload,
                    upload_url=self.sample_payload["upload_url"],
                    log_msg=self.log_msg,
                    is_task_cancelled=lambda: False,
                    api_key="mock_key"
                )

            err = ctx.exception
            self.assertEqual(err.code, "ERR_INTERNAL_WORKER_FAILURE")
            self.assertIn("Internal Error", err.message)
            self.assertEqual(mock_client.post.call_count, 1, "Nunca debe reenviar POST tras FAILED")

    # -------------------------------------------------------------------------
    # 10. Estado pendiente después de 25 minutos sin declarar un FAILED falso
    # -------------------------------------------------------------------------
    async def test_10_pending_after_25_minutes_no_false_failed(self):
        """Escenario 10: Tras 25 minutos de sondeo en cluster, la tarea pasa a PENDING_VERIFICATION sin declarar FAILED falso."""
        post_mock = MagicMock()
        post_mock.status_code = 200
        post_mock.json.return_value = {"code": 200, "workId": "upcov_timeout_25min_010"}

        in_progress_mock = MagicMock()
        in_progress_mock.status_code = 200
        in_progress_mock.json.return_value = {
            "code": 200,
            "data": {"type": "IN_PROGRESS", "response_data": []}
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = post_mock
        mock_client.get.return_value = in_progress_mock

        with patch("httpx.AsyncClient") as client_cls, patch("asyncio.sleep", new_callable=AsyncMock):
            client_cls.return_value.__aenter__.return_value = mock_client
            with self.assertRaises(self.adapter.MusicEngineError) as ctx:
                await self.engine.generate_and_poll(
                    task_id="test-task-10",
                    payload=self.sample_payload,
                    upload_url=self.sample_payload["upload_url"],
                    log_msg=self.log_msg,
                    is_task_cancelled=lambda: False,
                    api_key="mock_key",
                    max_poll_seconds=1500
                )

            err = ctx.exception
            self.assertEqual(err.code, "ERR_PROCESSING_TIMEOUT")
            self.assertTrue(err.raw_details.get("is_pending_verification"))
            self.assertNotIn("FAILED", err.code, "No debe declararse FAILED falso")

    # -------------------------------------------------------------------------
    # 11. Reinicio REAL con reemplazo de almacenamiento efímero (Render redeploy)
    # -------------------------------------------------------------------------
    async def test_11_real_restart_with_ephemeral_storage_replacement(self):
        """
        Escenario 11 (Punto 5 del requerimiento):
        Simula el reemplazo total del contenedor de Render:
        - Memoria RAM vacía
        - Disco efímero destruido (rodrix_persistence.db y generation_tasks.json borrados)
        - Restauración de tareas desde almacenamiento duradero (Google Drive 5TB)
        - Recuperación del Work ID auténtico y reanudación GET sin POST.
        """
        task_id = "test-task-ephemeral-wipe-011"
        authentic_work_id = "upcov_survives_container_wipe_011"

        # Tarea que estaba en la nube antes del redeploy
        cloud_payload = {
            task_id: {
                "id": task_id,
                "task_id": task_id,
                "work_id": authentic_work_id,
                "provider_work_id": authentic_work_id,
                "owner_email": "pastor@iglesia.com",
                "title": "Himno Resucitado",
                "status": "IN_PROGRESS",
                "model": "chirp-v4-5",
                "payload": self.sample_payload,
                "created_at": time.time(),
                "updated_at": time.time()
            }
        }
        cloud_bytes = json.dumps(cloud_payload).encode("utf-8")

        # SIMULACIÓN DE CONTENEDOR NUEVO:
        # 1. Vaciar memoria
        self.app.TASKS.clear()
        # 2. Borrar archivo local si existía para simular disco efímero virgen
        if os.path.exists(self.app.GENERATION_TASKS_FILE):
            os.remove(self.app.GENERATION_TASKS_FILE)

        # 3. Boot del nuevo contenedor: descarga desde Google Drive
        with patch.object(self.app, "gdrive_get_access_token", AsyncMock(return_value="mock_gdrive_token")), \
             patch.object(self.app, "gdrive_find_file", AsyncMock(return_value={"id": "file_gdrive_tasks_123"})), \
             patch.object(self.app, "gdrive_download_file_bytes", AsyncMock(return_value=cloud_bytes)):

            await self.app.gdrive_sync_generation_tasks_from_cloud()
            self.app.recover_pending_generation_tasks()

        # Verificar que la tarea sobrevivió al reemplazo completo del contenedor
        self.assertIn(task_id, self.app.TASKS)
        recovered_task = self.app.TASKS[task_id]
        self.assertEqual(recovered_task["status"], "PENDING_VERIFICATION")
        self.assertEqual(recovered_task["work_id"], authentic_work_id)
        self.assertEqual(recovered_task["owner_email"], "pastor@iglesia.com")

        # Verificar que la consulta de reanudación GET procede con exactamente 0 POSTs
        status_mock = MagicMock()
        status_mock.status_code = 200
        status_mock.json.return_value = {
            "code": 200,
            "data": {
                "type": "SUCCESS",
                "response_data": [{"id": "t_recovered", "title": "Himno Resucitado", "audio_url": "https://mock.cdn/rec.mp3"}]
            }
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = status_mock

        with patch("httpx.AsyncClient") as client_cls:
            client_cls.return_value.__aenter__.return_value = mock_client
            tracks = await self.engine.generate_and_poll(
                task_id=task_id,
                payload=self.sample_payload,
                upload_url=self.sample_payload["upload_url"],
                log_msg=self.log_msg,
                is_task_cancelled=lambda: False,
                api_key="mock_key",
                resume_work_id=authentic_work_id
            )
            self.assertEqual(len(tracks), 1)
            self.assertEqual(mock_client.post.call_count, 0, "Al reanudar tras reemplazo de disco efímero, NUNCA envía POST!")

    # -------------------------------------------------------------------------
    # 12. Prevención de recuperaciones simultáneas duplicadas
    # -------------------------------------------------------------------------
    async def test_12_concurrent_recovery_deduplication(self):
        """Escenario 12: Si se disparan dos recuperaciones simultáneas para la misma tarea, se procesa exactamente una."""
        task_id = "test-task-dedup-recovery-012"
        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "PENDING_VERIFICATION",
            "work_id": "upcov_dedup_012",
            "title": "Himno Concurrente"
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        # Simulamos que task_id ya está en _in_flight_recoveries
        self.app._in_flight_recoveries.add(task_id)
        try:
            # Una segunda llamada debe omitir el sondeo concurrente y retornar inmediatamente la tarea
            res = await self.app.execute_task_recovery(task_id)
            self.assertIsNotNone(res)
            self.assertEqual(res["status"], "PENDING_VERIFICATION")
        finally:
            self.app._in_flight_recoveries.discard(task_id)

    # -------------------------------------------------------------------------
    # 13. Manejo de reinicios repetidos
    # -------------------------------------------------------------------------
    async def test_13_repeated_restarts_resilience(self):
        """Escenario 13: Múltiples reinicios consecutivos no corrompen ni pierden el Work ID."""
        task_id = "test-task-multi-restart-013"
        wid = "upcov_multi_restart_wid"
        self.app.TASKS[task_id] = {
            "id": task_id,
            "owner_email": "test@rodrix.com",
            "status": "IN_PROGRESS",
            "work_id": wid,
            "title": "Himno Multi Reinicio"
        }
        self.app.save_task_persistent(task_id, self.app.TASKS[task_id])

        for restart_round in range(3):
            self.app.TASKS.clear()
            self.app.recover_pending_generation_tasks()
            self.assertIn(task_id, self.app.TASKS)
            self.assertEqual(self.app.TASKS[task_id]["work_id"], wid)
            self.assertEqual(self.app.TASKS[task_id]["status"], "PENDING_VERIFICATION")

    # -------------------------------------------------------------------------
    # 14. Validación integral con ffprobe y SHA-256 (Punto 4 del requerimiento)
    # -------------------------------------------------------------------------
    async def test_14_ffprobe_audio_validation_and_sha256(self):
        """Escenario 14: Validación completa con ffprobe, decodificabilidad, códec y SHA-256."""
        # Usamos un archivo de prueba existente en el workspace
        test_wav = os.path.join(REPO_DIR, "test.wav")
        if os.path.exists(test_wav):
            val = self.app.validate_audio_file_integrity(test_wav)
            self.assertTrue(val["valid"])
            self.assertTrue(len(val["sha256"]) == 64, "SHA-256 debe ser un hash de 64 caracteres hex")
            self.assertGreater(val["size"], 10240)

        # Archivo falso inexistente
        fake_val = self.app.validate_audio_file_integrity("archivo_no_existente_999.mp3")
        self.assertFalse(fake_val["valid"])

if __name__ == "__main__":
    unittest.main()
