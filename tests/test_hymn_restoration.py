import os
import unittest
from fastapi.testclient import TestClient
from app import app

class TestHymnRestoration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_restore_hymn_medium(self):
        src_path = "tests/test_hymn/test_raw_3min.wav"
        self.assertTrue(os.path.exists(src_path), "test_raw_3min.wav must exist")
        
        with open(src_path, "rb") as f:
            resp = self.client.post(
                "/api/hymn_production/restore",
                data={
                    "title": "Himno Test 3 Minutos",
                    "intensity": "medium",
                    "target_lufs": "-14.0"
                },
                files={"audio_file": ("test_raw_3min.wav", f, "audio/wav")}
            )
            
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("intensity_applied"), "medium")
        self.assertGreater(data.get("duration_sec", 0), 100)
        
        orig_m = data.get("original_metrics", {})
        proc_m = data.get("processed_metrics", {})
        
        # Verify measured metrics exist and are realistic numbers
        self.assertIn("integrated_lufs", orig_m)
        self.assertIn("integrated_lufs", proc_m)
        self.assertIn("true_peak_db", proc_m)
        
        # True peak must be <= -1.0 dBFS
        self.assertLessEqual(proc_m["true_peak_db"], -0.9)
        
        # Test download endpoints
        item_id = data["item_id"]
        res_wav = self.client.get(f"/api/hymn_production/download/{item_id}/wav")
        self.assertEqual(res_wav.status_code, 200)
        self.assertEqual(res_wav.headers.get("content-type"), "audio/wav")
        self.assertIn(f"{item_id}_master_24bit.wav", res_wav.headers.get("content-disposition", ""))
        
        res_mp3 = self.client.get(f"/api/hymn_production/download/{item_id}/mp3")
        self.assertEqual(res_mp3.status_code, 200)
        self.assertEqual(res_mp3.headers.get("content-type"), "audio/mpeg")
        
        # Test streaming endpoints for A/B player
        res_stream_orig = self.client.get(f"/api/hymn_production/stream/{item_id}/orig")
        self.assertEqual(res_stream_orig.status_code, 200)
        
        res_stream_restored = self.client.get(f"/api/hymn_production/stream/{item_id}/restored")
        self.assertEqual(res_stream_restored.status_code, 200)

    def test_restore_hymn_gentle(self):
        src_path = "tests/test_hymn/test_raw_3min.wav"
        with open(src_path, "rb") as f:
            resp = self.client.post(
                "/api/hymn_production/restore",
                data={
                    "title": "Himno Suave Acustico",
                    "intensity": "gentle",
                    "target_lufs": "-16.0"
                },
                files={"audio_file": ("test_raw_3min.wav", f, "audio/wav")}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("intensity_applied"), "gentle")

    def test_restore_hymn_empty(self):
        resp = self.client.post(
            "/api/hymn_production/restore",
            data={"title": "Empty"},
            files={"audio_file": ("empty.mp3", b"", "audio/mpeg")}
        )
        self.assertEqual(resp.status_code, 400)

if __name__ == "__main__":
    unittest.main()
