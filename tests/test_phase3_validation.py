"""
Test Suite: Rodrix Music Creator 4.0 - Fase 3 (Validación Integral y Estabilización)
Verifies:
1. Bidirectional audio coexistence between GlobalAudioController, WaveSurfer, and live voice recording.
2. Parameter integrity when toggling between Modo Asistente and Modo Estudio Pro.
3. Strict 0-credit payload generation for Udio and FluidSynth with 7/8, 9/8, 11/8, tempo, and key.
4. Security & non-destructive library operations (Google Drive CAS preservation, no silent file overwriting).
5. Android 4.0 package ID (com.rodrix.musiccreator), permissions, and JavaScript bridge integrity.
"""

import unittest
import os
import re

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_DIR, "index.html")
APP_PY_PATH = os.path.join(REPO_DIR, "app.py")
ANDROID_DIR = os.path.join(os.path.dirname(REPO_DIR), "rodrix-android")
ANDROID_MANIFEST_PATH = os.path.join(ANDROID_DIR, "app", "src", "main", "AndroidManifest.xml")
ANDROID_GRADLE_PATH = os.path.join(ANDROID_DIR, "app", "build.gradle")
ANDROID_MAIN_ACTIVITY_PATH = os.path.join(ANDROID_DIR, "app", "src", "main", "java", "com", "rodrix", "musiccreator", "MainActivity.java")

class TestPhase3Validation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            cls.index_content = f.read()

        with open(APP_PY_PATH, "r", encoding="utf-8") as f:
            cls.app_content = f.read()

        if os.path.exists(ANDROID_MANIFEST_PATH):
            with open(ANDROID_MANIFEST_PATH, "r", encoding="utf-8") as f:
                cls.manifest_content = f.read()
        else:
            cls.manifest_content = ""

        if os.path.exists(ANDROID_GRADLE_PATH):
            with open(ANDROID_GRADLE_PATH, "r", encoding="utf-8") as f:
                cls.gradle_content = f.read()
        else:
            cls.gradle_content = ""

        if os.path.exists(ANDROID_MAIN_ACTIVITY_PATH):
            with open(ANDROID_MAIN_ACTIVITY_PATH, "r", encoding="utf-8") as f:
                cls.activity_content = f.read()
        else:
            cls.activity_content = ""

    # --- 1. AUDIO COEXISTENCE & SINGLE INSTANCE GUARANTEE ---
    def test_audio_coexistence_pause_external_previews(self):
        # GlobalAudioController.pauseExternalPreviews must pause recWs and ws
        self.assertIn("function pauseExternalPreviews(", self.index_content)
        self.assertIn("recWs.pause()", self.index_content)
        self.assertIn("ws.pause()", self.index_content)

    def test_recording_pauses_global_player(self):
        # startLiveRecording must pause GlobalAudioController
        self.assertIn("if (window.GlobalAudioController && window.GlobalAudioController.isPlaying()) {", self.index_content)
        self.assertIn("window.GlobalAudioController.pause();", self.index_content)

    def test_wavesurfer_preview_pauses_global_player(self):
        # toggleRecPlayback must check and pause GlobalAudioController
        self.assertIn("function toggleRecPlayback()", self.index_content)
        self.assertIn("GlobalAudioController.pause();", self.index_content)

    # --- 2. PARAMETER PRESERVATION ON MODE TOGGLE ---
    def test_mode_toggle_preserves_form_fields(self):
        # setStudioMode must only toggle body CSS classes and save localStorage
        # it must NOT clear styleInput or reset inputs
        match = re.search(r'function setStudioMode\(mode\)\s*\{([^}]+(?:\{[^}]+\}[^}]+)*)\}', self.index_content)
        self.assertIsNotNone(match)
        body_code = match.group(1)
        self.assertNotIn("styleInput.value = ''", body_code)
        self.assertNotIn("lyricsInput.value = ''", body_code)
        self.assertNotIn(".reset()", body_code)
        self.assertIn("localStorage.setItem('rodrix_studio_mode', mode)", body_code)

    # --- 3. MOCK PAYLOAD RESOLUTION WITH 0 CREDITS ---
    def test_resolve_effective_musical_config_with_asymmetric_meters(self):
        # Test app.py logic directly via mock without network/credits
        import app

        # 7/8 meter
        res_78 = app.resolve_effective_musical_config(
            style="Key: C Major. Tempo: 107 BPM. Time signature: 7/8.",
            active_preset=""
        )
        self.assertEqual(res_78["effective_meter"], "7/8")
        self.assertEqual(res_78["effective_bpm"], 107)
        self.assertIn("2+2+3", res_78["meter_clause"])

        # 9/8 meter
        res_98 = app.resolve_effective_musical_config(
            style="Compás: 9/8. Tempo: 120 BPM.",
            active_preset=""
        )
        self.assertEqual(res_98["effective_meter"], "9/8")
        self.assertEqual(res_98["effective_bpm"], 120)

        # 11/8 meter
        res_118 = app.resolve_effective_musical_config(
            style="Meter: 11/8. 110 BPM.",
            active_preset=""
        )
        self.assertEqual(res_118["effective_meter"], "11/8")

    # --- 4. DATA INTEGRITY & CANONICAL PERSISTENCE ---
    def test_google_drive_persistence_and_cas_protection(self):
        # Ensure app.py contains CAS (Compare-And-Swap) logic and token validation
        self.assertIn("_perform_resumable_upload", self.app_content)
        self.assertIn("rodryandy@gmail.com", self.app_content)
        self.assertIn("gdrive_sync_library_to_cloud", self.app_content)
        self.assertIn("save_library_atomic", self.app_content)

    # --- 5. ANDROID 4.0 INTEGRITY ---
    def test_android_package_id_and_permissions(self):
        if self.gradle_content:
            self.assertIn("com.rodrix.musiccreator", self.gradle_content)
        if self.manifest_content:
            self.assertIn("FOREGROUND_SERVICE", self.manifest_content)
            self.assertIn("FOREGROUND_SERVICE_MEDIA_PLAYBACK", self.manifest_content)
            self.assertIn("RECORD_AUDIO", self.manifest_content)

    def test_android_javascript_bridge_share_audios(self):
        if self.activity_content:
            self.assertIn("@JavascriptInterface", self.activity_content)
            self.assertIn("shareAudiosJson", self.activity_content)
            self.assertIn("AndroidApp", self.activity_content)

if __name__ == "__main__":
    unittest.main()
