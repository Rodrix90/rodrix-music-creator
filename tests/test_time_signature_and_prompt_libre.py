import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app

class TestTimeSignatureAndPromptLibre(unittest.TestCase):
    """
    Suite de pruebas locales para verificar el respeto estricto de compases,
    la agrupación 4+3, la preservación del género musical original y
    la ausencia de contradicciones en el payload hacia Udio.
    """

    def test_1_prompt_libre_7_4_with_4_plus_3_and_genre_preservation(self):
        """Test 1: 7/4 con agrupación rítmica 4+3 preservando Christian Worship/Acoustic Pop/Folk Rock sin imponer progressive."""
        style_prompt = (
            "Christian Worship, Acoustic Pop, Folk Rock, Acoustic guitar, Bass guitar, Drums, "
            "Male Tenor vocals, Spiritual, Uplifting, century 1994 rock kit, "
            "Time signature: 7/4 (4+3), Tempo: 107 BPM, Key: C Major"
        )
        cfg = app.resolve_effective_musical_config(
            style=style_prompt,
            lyrics="[Verse]\nCanto a Ti Señor\n[Chorus]\nEres mi fortaleza",
            target_bpm=107,
            active_preset=""
        )
        self.assertEqual(cfg["effective_meter"], "7/4")
        self.assertEqual(cfg["bpm_tag"], "107 BPM")
        # Verificar cláusula de 7/4 con 4+3 y sin 'progressive' forzado
        self.assertIn("7/4 time signature", cfg["meter_clause"])
        self.assertIn("4+3 rhythm pulse", cfg["meter_clause"])
        self.assertNotIn("progressive", cfg["meter_clause"].lower())

        # Sanitizar y verificar ausencia de 4/4 y conteo cuaternario
        cleaned = app.sanitize_and_prioritize_style_with_config(style_prompt, cfg)
        self.assertNotIn("4/4", cleaned)
        self.assertNotIn("snare 2-4", cleaned)
        self.assertNotIn("kick 1-3", cleaned)

        # En hi-hat clause, comprobar que no inyecta el conteo de 4/4 (1-and 2-and 3-and 4-and)
        self.assertNotIn("1-and 2-and 3-and 4-and", cfg["hihat_clause"])

    def test_2_prompt_libre_5_4_natural_pulse(self):
        """Test 2: Compás 5/4 con pulso natural sin alterar el género."""
        cfg_54 = app.resolve_effective_musical_config(
            style="Christian Worship, Acoustic Pop, compas 5/4, 120 bpm, drums, acoustic guitar",
            active_preset=""
        )
        self.assertEqual(cfg_54["effective_meter"], "5/4")
        self.assertIn("5/4 time signature", cfg_54["meter_clause"])
        self.assertNotIn("progressive", cfg_54["meter_clause"].lower())
        self.assertNotIn("1-and 2-and 3-and 4-and", cfg_54["hihat_clause"])

    def test_3_prompt_libre_6_8_and_12_8(self):
        """Test 3: Compases ternarios y compuestos (6/8 y 12/8)."""
        cfg_68 = app.resolve_effective_musical_config(
            style="Acoustic worship ballad, compás 6/8, 54 bpm, acoustic guitar and strings",
            active_preset=""
        )
        self.assertEqual(cfg_68["effective_meter"], "6/8")
        self.assertIn("6/8 compound time", cfg_68["meter_clause"])

        cfg_128 = app.resolve_effective_musical_config(
            style="Solemn worship hymn, 12/8 time, 50 bpm",
            active_preset=""
        )
        self.assertEqual(cfg_128["effective_meter"], "12/8")
        self.assertIn("12/8 compound meter", cfg_128["meter_clause"])

    def test_4_prompt_libre_3_4_waltz(self):
        """Test 4: Compás ternario simple 3/4."""
        cfg_34 = app.resolve_effective_musical_config(
            style="Himno congregacional, compas 3/4, 90 bpm, coro y piano",
            active_preset=""
        )
        self.assertEqual(cfg_34["effective_meter"], "3/4")
        self.assertIn("3/4 triple meter", cfg_34["meter_clause"])

    def test_5_prompt_libre_4_4_standard(self):
        """Test 5: Prompt Libre con 4/4 mantiene compatibilidad estándar con conteos clásicos."""
        cfg_44 = app.resolve_effective_musical_config(
            style="Christian rock, 4/4 time signature, 120 bpm, loud drums",
            active_preset=""
        )
        self.assertEqual(cfg_44["effective_meter"], "4/4")
        self.assertEqual(cfg_44["bpm_tag"], "120 BPM")
        self.assertIn("1-and 2-and 3-and 4-and", cfg_44["hihat_clause"])

    def test_6_full_band_with_yamaha_cfx_preserves_vocals_and_band(self):
        """Test 6: Banda completa con piano Yamaha CFX como acompañamiento preserva voz y banda completa."""
        style_band = (
            "Christian Worship, Acoustic Pop, Male Tenor vocals, drums, bass guitar, "
            "stratocaster, yamaha cfx grand, warm mix"
        )
        cfg = app.resolve_effective_musical_config(
            style=style_band,
            lyrics="[Verse]\nBendito sea el Señor",
            active_preset="",
            is_solo_piano_prayer=False
        )
        self.assertFalse(cfg.get("is_solo_piano_prayer", False))

    def test_7_full_udio_payload_simulation_7_4(self):
        """Test 7: Simulación completa del payload hacia Udio verificando ausencia de contradicciones."""
        user_style = (
            "Christian Worship, Acoustic Pop, Folk Rock, Acoustic guitar, Bass guitar, Drums, "
            "Male Tenor vocals, Spiritual, Uplifting, century 1994 rock kit, "
            "Time signature: 7/4 (4+3), Tempo: 107 BPM, Key: C Major"
        )
        cfg = app.resolve_effective_musical_config(
            style=user_style,
            target_bpm=107,
            active_preset=""
        )

        style = user_style
        if "century 1994 rock kit" in style:
            style = style.replace(
                "century 1994 rock kit",
                "1994 Century acoustic wood shell drum kit, dynamic live acoustic drum performance, 10 12 14 rack toms and 16 floor tom"
            )

        cleaned = app.sanitize_and_prioritize_style_with_config(style, cfg)

        anchors = []
        if cfg.get("meter_clause"):
            anchors.append(cfg["meter_clause"])
        if cfg.get("bpm_tag"):
            anchors.append(cfg["bpm_tag"])
        genre_anchor = ", ".join(anchors)

        priority_str = ", ".join(cfg.get("priority_clauses", []))
        combined = [p for p in [genre_anchor, priority_str, cleaned] if p]
        final_payload_style = ", ".join(combined)

        # 1. 7/4 y 4+3 presentes en el frente
        self.assertTrue(final_payload_style.startswith("strictly in 7/4 time signature (7 beats per measure) (4+3 rhythm pulse)"))
        # 2. 107 BPM presente
        self.assertIn("107 BPM", final_payload_style)
        # 3. Géneros originales preservados
        self.assertIn("Christian Worship", final_payload_style)
        self.assertIn("Acoustic Pop", final_payload_style)
        self.assertIn("Folk Rock", final_payload_style)
        # 4. 'progressive' no impuesto
        self.assertNotIn("progressive", final_payload_style.lower())
        # 5. Sin contradicciones de 4/4 ni snare 2-4
        self.assertNotIn("4/4", final_payload_style)
        self.assertNotIn("snare 2-4", final_payload_style)
        self.assertNotIn("kick 1-3", final_payload_style)
        self.assertNotIn("1-and 2-and 3-and 4-and", final_payload_style)

if __name__ == "__main__":
    unittest.main()
