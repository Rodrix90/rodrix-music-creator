"""
Test Suite: Rodrix Music Creator 4.0 - Fase 2 (Studio Pro Redesign Web + Android)
Verifies:
- Dual Mode switcher (Modo Asistente vs Modo Estudio Pro)
- Screen 1: Prompt Libre Hero, inspiration pills, visual rhythmic metric widget (7/8, 9/8, 11/8, etc.), tap tempo, key selector
- Screen 2: MIDI piano roll canvas, Hymnary public domain explorer, 1-hour continuous album stitcher
- Screen 3: Broadcast dual LED VU meter (-42dB to 0dB Clip), vocal channel strip (HPF 80Hz, De-Esser, 3-Band EQ, Auto-Ducking)
- Screen 4: Mi Librería search, category filter chips (Todas, IA, Voz en Off, SF2, 1H), sort selector, Drive 5TB backup pills
- Screen 5: User administration panel with protection for rodryandy@gmail.com
- Android Manifest: Foreground service permissions for background playback coexistence
"""

import unittest
import os
import re

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_PATH = os.path.join(REPO_DIR, "index.html")
ANDROID_MANIFEST_PATH = os.path.join(os.path.dirname(REPO_DIR), "rodrix-android", "app", "src", "main", "AndroidManifest.xml")

class TestPhase2StudioPro(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            cls.index_content = f.read()

        if os.path.exists(ANDROID_MANIFEST_PATH):
            with open(ANDROID_MANIFEST_PATH, "r", encoding="utf-8") as f:
                cls.manifest_content = f.read()
        else:
            cls.manifest_content = ""

    # --- 1. DUAL MODE EXPERIENCE ---
    def test_dual_mode_switcher_present_in_markup(self):
        self.assertIn('id="studioModeSwitch"', self.index_content)
        self.assertIn('id="btnModeAssistant"', self.index_content)
        self.assertIn('id="btnModePro"', self.index_content)
        self.assertIn('id="mobileModeToggle"', self.index_content)

    def test_dual_mode_javascript_controllers(self):
        self.assertIn("function setStudioMode(", self.index_content)
        self.assertIn("function toggleStudioMode(", self.index_content)
        self.assertIn("localStorage.setItem('rodrix_studio_mode'", self.index_content)
        self.assertIn("body.mode-assistant .pro-only", self.index_content)

    # --- 2. SCREEN 1: CREAR CANCIÓN ---
    def test_prompt_inspiration_bar_and_pills(self):
        self.assertIn('id="promptInspirationBar"', self.index_content)
        self.assertIn("Adoración Solemne", self.index_content)
        self.assertIn("Himno Clásico", self.index_content)
        self.assertIn("Gospel Power", self.index_content)
        self.assertIn("Acústico Íntimo", self.index_content)
        self.assertIn("Alabanza Rítmica 7/8", self.index_content)
        self.assertIn("Vals Vienés Imperial", self.index_content)
        self.assertIn("Rock Cristiano Épico", self.index_content)

    def test_visual_metric_widget_markup_and_meters(self):
        self.assertIn('id="visualMetricWidget"', self.index_content)
        self.assertIn('id="timeSigSelect"', self.index_content)
        self.assertIn('id="pulseSubdivisionsContainer"', self.index_content)
        self.assertIn('value="7/8"', self.index_content)
        self.assertIn('value="9/8"', self.index_content)
        self.assertIn('value="11/8"', self.index_content)
        self.assertIn('value="7/4"', self.index_content)
        self.assertIn('value="5/4"', self.index_content)

    def test_rhythm_pulse_grouping_and_accents(self):
        self.assertIn("TIME_SIG_CONFIGS", self.index_content)
        # 7/8 must have 7 steps and accents on 1, 3, 5
        self.assertIn("'7/8': { steps: 7, accents: [1, 3, 5]", self.index_content)
        # 9/8 must have 9 steps and accents on 1, 4, 7
        self.assertIn("'9/8': { steps: 9, accents: [1, 4, 7]", self.index_content)
        # 11/8 must have 11 steps
        self.assertIn("'11/8': { steps: 11, accents: [1, 3, 5, 7, 9]", self.index_content)

    def test_tap_tempo_and_key_selector(self):
        self.assertIn('id="btnTapTempo"', self.index_content)
        self.assertIn('id="bpmRangeSlider"', self.index_content)
        self.assertIn('id="keySelectorRoot"', self.index_content)
        self.assertIn('id="keySelectorScale"', self.index_content)
        self.assertIn("function handleTapTempo(", self.index_content)
        self.assertIn("function onBpmSliderChange(", self.index_content)
        self.assertIn("function updateMusicalKey(", self.index_content)

    # --- 3. SCREEN 2: MELODÍAS E HIMNOS ---
    def test_piano_roll_canvas_and_hymn_explorer(self):
        self.assertIn('id="pianoRollCard"', self.index_content)
        self.assertIn('id="midiPianoRollCanvas"', self.index_content)
        self.assertIn('id="hymnExplorerSection"', self.index_content)
        self.assertIn("Sublime Gracia", self.index_content)
        self.assertIn("Cuán Grande Es Él", self.index_content)
        self.assertIn("Castillo Fuerte Es Nuestro Dios", self.index_content)
        self.assertIn("Santo, Santo, Santo", self.index_content)
        self.assertIn("function drawPianoRollDemo(", self.index_content)
        self.assertIn("function loadCuratedHymn(", self.index_content)

    def test_album_stitcher_section(self):
        self.assertIn('id="albumStitcherSection"', self.index_content)
        self.assertIn("Compilador de Álbum Continuo de 1 Hora", self.index_content)
        self.assertIn("openAlbumStitcherModal(", self.index_content)

    # --- 4. SCREEN 3: VOZ EN OFF ---
    def test_broadcast_vu_meter(self):
        self.assertIn('id="broadcastVuMeter"', self.index_content)
        self.assertIn('id="vuMeterFillL"', self.index_content)
        self.assertIn('id="vuMeterFillR"', self.index_content)
        self.assertIn('0 dB CLIP', self.index_content)
        self.assertIn("function initBroadcastVuMeter(", self.index_content)

    def test_vocal_channel_strip(self):
        self.assertIn('id="vocalChannelStrip"', self.index_content)
        self.assertIn('id="chkStripHpf"', self.index_content)
        self.assertIn('id="chkStripDeesser"', self.index_content)
        self.assertIn('id="eqLowGain"', self.index_content)
        self.assertIn('id="eqMidGain"', self.index_content)
        self.assertIn('id="eqHighGain"', self.index_content)
        self.assertIn('id="stripDuckingFader"', self.index_content)
        self.assertIn("function updateVocalProcessing(", self.index_content)

    # --- 5. SCREEN 4: MI LIBRERÍA ---
    def test_library_toolbar_search_chips_and_sort(self):
        self.assertIn('id="libToolbarPro"', self.index_content)
        self.assertIn('id="libSearchInput"', self.index_content)
        self.assertIn('id="libSortSelect"', self.index_content)
        self.assertIn('data-category="all"', self.index_content)
        self.assertIn('data-category="ia"', self.index_content)
        self.assertIn('data-category="voiceover"', self.index_content)
        self.assertIn('data-category="instrumental"', self.index_content)
        self.assertIn('data-category="album"', self.index_content)
        self.assertIn("function onLibSearchOrFilterChange(", self.index_content)
        self.assertIn("function setLibCategoryFilter(", self.index_content)

    def test_track_cards_drive_backup_pill(self):
        self.assertIn("Drive 5TB", self.index_content)
        self.assertIn("GlobalAudioController", self.index_content)

    # --- 6. SCREEN 5: USUARIOS & SEGURIDAD ---
    def test_user_management_safety_lock(self):
        self.assertIn("rodryandy@gmail.com", self.index_content)
        self.assertIn("Cuenta Principal", self.index_content)
        self.assertIn("toggleUserStatus", self.index_content)

    # --- 7. ANDROID COMPATIBILITY ---
    def test_android_manifest_media_playback_foreground_service(self):
        if self.manifest_content:
            self.assertIn("FOREGROUND_SERVICE", self.manifest_content)
            self.assertIn("FOREGROUND_SERVICE_MEDIA_PLAYBACK", self.manifest_content)

if __name__ == "__main__":
    unittest.main()
