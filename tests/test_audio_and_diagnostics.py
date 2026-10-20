import os
import unittest
from fastapi.testclient import TestClient
from app import app, TASKS

class TestAudioAndDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_check_audio_compatibility_mp3(self):
        mp3_path = "tests/test_audio/test.mp3"
        self.assertTrue(os.path.exists(mp3_path), "test.mp3 must exist")
        with open(mp3_path, "rb") as f:
            resp = self.client.post(
                "/api/check_audio_compatibility",
                files={"file": ("test.mp3", f, "audio/mpeg")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("compatible"))
        self.assertEqual(data.get("format"), "MP3")
        self.assertIn("Hz", data.get("sample_rate", ""))
        self.assertGreater(data.get("duration_sec", 0), 0)

    def test_check_audio_compatibility_wav(self):
        wav_path = "tests/test_audio/test.wav"
        self.assertTrue(os.path.exists(wav_path), "test.wav must exist")
        with open(wav_path, "rb") as f:
            resp = self.client.post(
                "/api/check_audio_compatibility",
                files={"file": ("test.wav", f, "audio/wav")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("compatible"))
        self.assertIn("WAV", data.get("format"))
        self.assertGreater(data.get("duration_sec", 0), 0)

    def test_check_audio_compatibility_m4a(self):
        m4a_path = "tests/test_audio/test.m4a"
        self.assertTrue(os.path.exists(m4a_path), "test.m4a must exist")
        with open(m4a_path, "rb") as f:
            resp = self.client.post(
                "/api/check_audio_compatibility",
                files={"file": ("test.m4a", f, "audio/mp4")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("compatible"))
        self.assertIn("AAC", data.get("format"))

    def test_check_audio_compatibility_mp4(self):
        mp4_path = "tests/test_audio/test.mp4"
        self.assertTrue(os.path.exists(mp4_path), "test.mp4 must exist")
        with open(mp4_path, "rb") as f:
            resp = self.client.post(
                "/api/check_audio_compatibility",
                files={"file": ("test.mp4", f, "video/mp4")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("compatible"))

    def test_check_audio_compatibility_corrupt(self):
        corrupt_path = "tests/test_audio/corrupt.mp3"
        self.assertTrue(os.path.exists(corrupt_path), "corrupt.mp3 must exist")
        with open(corrupt_path, "rb") as f:
            resp = self.client.post(
                "/api/check_audio_compatibility",
                files={"file": ("corrupt.mp3", f, "audio/mpeg")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("compatible"))
        self.assertIn("error", data)
        self.assertTrue(len(data.get("message", "")) > 0)

    def test_check_audio_compatibility_empty(self):
        resp = self.client.post(
            "/api/check_audio_compatibility",
            files={"file": ("empty.mp3", b"", "audio/mpeg")}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("compatible"))

    def test_check_audio_compatibility_non_audio(self):
        resp = self.client.post(
            "/api/check_audio_compatibility",
            files={"file": ("document.txt", b"Hello world non audio text file", "text/plain")}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("compatible"))

    def test_diagnostic_report_catalog_rejection(self):
        test_task_id = "test-catalog-task-999"
        TASKS[test_task_id] = {
            "id": test_task_id,
            "status": "ERROR",
            "title": "Himno 297 - Cuan Grande Es El",
            "catalog_rejection": True,
            "detail": "Rechazo de catalogo comercial: Coincidencia con fonograma existente",
            "logs": "Generando audio...\nAPI Error: This audio matches an existing recording in our catalog.\nProceso detenido.",
            "diagnostic_info": {
                "task_id": test_task_id,
                "title": "Himno 297 - Cuan Grande Es El",
                "model": "udio-130-v2.0",
                "date_utc": "2026-10-20T11:00:00Z",
                "exact_error_message": "Generation failed. Your credits have been refunded. This audio matches an existing recording in our catalog.",
                "is_public_domain": True,
                "audio_filename": "himno_297.mp3",
                "has_audio_reference": True
            }
        }

        resp = self.client.get(f"/api/diagnostic_report/{test_task_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers.get("content-type", ""))
        self.assertIn(f'attachment; filename="diagnostico_{test_task_id}.txt"', resp.headers.get("content-disposition", ""))
        
        body = resp.text
        self.assertIn("INFORME TÉCNICO DE DIAGNÓSTICO", body)
        self.assertIn("COINCIDENCIA DE CATÁLOGO COMERCIAL", body)
        self.assertIn(test_task_id, body)
        self.assertIn("Himno 297 - Cuan Grande Es El", body)
        self.assertIn("This audio matches an existing recording in our catalog", body)
        self.assertIn("SÍ (Grabación propia de obra tradicional/autorizada)", body)
        self.assertIn("support@udioapi.pro", body)
        # Ensure no private API keys are leaked
        self.assertNotIn("sk-e6c60cad69b44514b66651740a2c5885", body)

    def test_diagnostic_report_general_error(self):
        test_task_id = "test-general-error-555"
        TASKS[test_task_id] = {
            "id": test_task_id,
            "status": "ERROR",
            "title": "Cancion de Prueba",
            "detail": "Fallo HTTP 500 en servidor de generacion",
            "logs": "Inicio de tarea...\nError interno del servidor 500.",
            "audio_filename": "prueba.mp3",
            "is_public_domain": False
        }

        resp = self.client.get(f"/api/diagnostic_report/{test_task_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("test-general-error-555", body)
        self.assertIn("Fallo HTTP 500 en servidor de generacion", body)

    def test_diagnostic_report_not_found(self):
        resp = self.client.get("/api/diagnostic_report/non-existent-task-id-1234")
        self.assertEqual(resp.status_code, 404)
        body = resp.text
        self.assertIn("INFORME DE DIAGNÓSTICO NO DISPONIBLE", body)
        self.assertIn("non-existent-task-id-1234", body)
        self.assertIn("POSIBLES RAZONES", body)

    def test_diagnostic_report_invalid_id(self):
        resp = self.client.get("/api/diagnostic_report/undefined")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Identificador de tarea inválido", resp.text)

    def test_task_status_endpoint_returns_id(self):
        test_task_id = "test-status-check-777"
        TASKS[test_task_id] = {
            "status": "IN_PROGRESS",
            "logs": "Procesando...",
            "tracks": [],
            "detail": ""
        }
        resp = self.client.get(f"/api/status/{test_task_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("id"), test_task_id)

if __name__ == "__main__":
    unittest.main()
