import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Asegurar path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    resolve_effective_musical_config,
    inject_arrangement_cues_into_lyrics
)
from free_instruments_engine import (
    synthesize_multitrack_composition,
    INSTRUMENT_BY_ID
)

class TestSoloInstrumentIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = os.path.join(os.path.dirname(__file__), "tmp_test_isolation")
        os.makedirs(self.tmp_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmp_dir):
            try:
                shutil.rmtree(self.tmp_dir)
            except Exception:
                pass

    def test_1_solo_guitar_isolation_config(self):
        """Test 1: Solo de guitarra sin acompañamiento: articulaciones de batería y bajo desactivadas."""
        cfg = resolve_effective_musical_config(
            style="Solo de guitarra electrica Fender Stratocaster virtuoso",
            lyrics="",
            exclude_styles="drums, bass, other instruments",
            is_guitar_solo=True
        )
        # En modo solo de guitarra, no debe haber clusulas de bombo, caja, hi-hat ni bajo
        self.assertEqual(cfg["effective_hihat"], "8th")
        self.assertFalse(cfg["crash_toms"])
        self.assertFalse(cfg["tom_grooves"])
        self.assertFalse(cfg["bass_slap"])
        self.assertFalse(cfg["bass_pickup"])
        for clause in cfg.get("priority_clauses", []):
            self.assertNotIn("hi-hat", clause.lower())
            self.assertNotIn("bass", clause.lower())
            self.assertNotIn("snare", clause.lower())

    def test_2_solo_guitar_lyrics_cues_ignored(self):
        """Test 2: Cues de batería o transiciones no deben inyectarse en la estructura del solo de guitarra."""
        cfg = {
            "bpm_tag": "90 BPM",
            "effective_hihat": "16th",
            "crash_toms": True,
            "tom_grooves": True,
            "bass_slap": True,
            "bass_pickup": True
        }
        raw_lyrics = "[Instrumental - Solo Guitar]"
        injected = inject_arrangement_cues_into_lyrics(raw_lyrics, cfg, is_guitar_solo=True)
        self.assertEqual(injected, raw_lyrics, "Los cues de batería/bajo no deben agregarse en solo de guitarra")

    def test_3_solo_bass_isolation_config(self):
        """Test 3: Solo de bajo sin batería ni guitarras."""
        cfg = resolve_effective_musical_config(
            style="Solo de bajo Fender Jazz Bass melodico",
            is_bass_solo=True,
            art_bass_slap=True
        )
        self.assertFalse(cfg["crash_toms"])
        self.assertFalse(cfg["tom_grooves"])
        self.assertTrue(cfg["bass_slap"])
        # No debe haber cláusulas de hi-hat ni batería
        for clause in cfg.get("priority_clauses", []):
            self.assertNotIn("hi-hat", clause.lower())
            self.assertNotIn("snare", clause.lower())

    def test_4_solo_drums_isolation_config(self):
        """Test 4: Batería sola sin armonía ni bajo."""
        cfg = resolve_effective_musical_config(
            style="Drum solo acoustic drum kit showcase",
            is_drum_solo=True
        )
        self.assertFalse(cfg["bass_slap"])
        self.assertFalse(cfg["bass_pickup"])
        for clause in cfg.get("priority_clauses", []):
            self.assertNotIn("bassline", clause.lower())

    def test_5_multiple_instruments_allowed(self):
        """Test 5: Banda completa: si el usuario selecciona batería y bajo, se preservan."""
        cfg = resolve_effective_musical_config(
            style="Alabanza con guitarra, bajo y bateria completa",
            art_crash_toms=True,
            art_bass_slap=True,
            is_guitar_solo=False,
            is_bass_solo=False,
            is_drum_solo=False,
            is_solo_piano_prayer=False
        )
        self.assertTrue(cfg["crash_toms"])
        self.assertTrue(cfg["bass_slap"])
        joined = " ".join(cfg.get("priority_clauses", [])).lower()
        self.assertTrue("hi-hat" in joined or "bass" in joined)

    def test_6_free_instruments_single_guitar_with_amp(self):
        """Test 6: Motor gratuito (FluidSynth) con solo guitarra y amplificador virtual."""
        out_mp3 = os.path.join(self.tmp_dir, "solo_strat.mp3")
        # Generar solo guitarra limpia (guitarra_limpia) con amplificador Fender Twin Reverb
        tracks = [{"id": "guitarra_limpia", "volume": 1.0}]
        amps = {
            "guitar": {
                "amp_id": "fender_twin_reverb",
                "cabinet_id": "cab_fender_twin_2x12",
                "gain": 5.0,
                "bass": 5.0,
                "mid": 5.0,
                "treble": 6.0,
                "presence": 5.0,
                "master": 7.0,
                "bypass": False
            }
        }
        res = synthesize_multitrack_composition(
            tracks_config=tracks,
            output_mp3_path=out_mp3,
            bpm=120,
            bars=2,
            amp_configs=amps
        )
        self.assertTrue(os.path.exists(out_mp3), "El archivo MP3 debe existir")
        self.assertGreater(os.path.getsize(out_mp3), 1000)
        self.assertEqual(len(res["tracks"]), 1)
        self.assertEqual(res["tracks"][0]["id"], "guitarra_limpia")
        # Verificar que se aplicó el amplificador Fender Twin Reverb
        self.assertEqual(res["tracks"][0].get("amp_applied"), "fender_twin_reverb")
        self.assertEqual(res["tracks"][0].get("cabinet_applied"), "cab_fender_twin_2x12")

if __name__ == "__main__":
    unittest.main()
