import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app

class TestTimeSignatureAndPromptLibre(unittest.TestCase):
    """
    Suite de pruebas locales para verificar el respeto estricto de compases regulares,
    compases compuestos e irregulares (7/8, 9/8, 11/8, 5/4, 7/4, 6/8, 12/8, 3/4, 4/4),
    la sanitización de residuos y la preservación de instrumentación, letras y voz.
    """

    def test_1_7_8_grouped_2_2_3(self):
        """Test 1: 7/8 (2+2+3) con acentos en corcheas 1, 3 y 5."""
        cfg = app.resolve_effective_musical_config(
            style="Christian Worship, Acoustic Pop, Drums, 7/8 (2+2+3), 107 BPM",
            active_preset=""
        )
        self.assertEqual(cfg["effective_meter"], "7/8")
        self.assertIn("seven eighth-note subdivisions per measure", cfg["meter_clause"])
        self.assertIn("grouped 2+2+3", cfg["meter_clause"])
        self.assertIn("accents on subdivisions 1, 3 and 5", cfg["meter_clause"])

    def test_2_7_8_grouped_3_2_2(self):
        """Test 2: 7/8 (3+2+2) con acentos en corcheas 1, 4 y 6."""
        cfg = app.resolve_effective_musical_config(
            style="Christian Worship, Folk Rock, 7/8 (3+2+2), 107 BPM",
            active_preset=""
        )
        self.assertEqual(cfg["effective_meter"], "7/8")
        self.assertIn("grouped 3+2+2", cfg["meter_clause"])
        self.assertIn("accents on subdivisions 1, 4 and 6", cfg["meter_clause"])

    def test_3_7_8_grouped_2_3_2(self):
        """Test 3: 7/8 (2+3+2) con acentos en corcheas 1, 3 y 6."""
        cfg = app.resolve_effective_musical_config(
            style="Christian Praise, 7/8 (2+3+2), 110 BPM",
            active_preset=""
        )
        self.assertEqual(cfg["effective_meter"], "7/8")
        self.assertIn("grouped 2+3+2", cfg["meter_clause"])
        self.assertIn("accents on subdivisions 1, 3 and 6", cfg["meter_clause"])

    def test_4_7_8_default_grouping(self):
        """Test 4: 7/8 sin agrupación explícita utiliza 2+2+3 como predeterminado musical."""
        cfg = app.resolve_effective_musical_config(
            style="Key: C Major. Tempo: 107 BPM. Time signature: 7/8.",
            active_preset=""
        )
        self.assertEqual(cfg["effective_meter"], "7/8")
        self.assertEqual(cfg["bpm_tag"], "107 BPM")
        self.assertIn("seven eighth-note subdivisions per measure", cfg["meter_clause"])
        self.assertIn("grouped 2+2+3", cfg["meter_clause"])
        self.assertIn("accents on subdivisions 1, 3 and 5", cfg["meter_clause"])

    def test_5_9_8_alternative_groupings(self):
        """Test 5: 9/8 con agrupación asimétrica (2+2+2+3) vs regular (3+3+3 / compuesto triple)."""
        cfg_balkan = app.resolve_effective_musical_config(
            style="Acoustic worship, compas 9/8 (2+2+2+3), 120 bpm",
            active_preset=""
        )
        self.assertEqual(cfg_balkan["effective_meter"], "9/8")
        self.assertIn("grouped 2+2+2+3", cfg_balkan["meter_clause"])

        cfg_std = app.resolve_effective_musical_config(
            style="Sacred hymn, in 9/8 time, 60 bpm",
            active_preset=""
        )
        self.assertEqual(cfg_std["effective_meter"], "9/8")
        self.assertIn("compound triple meter", cfg_std["meter_clause"])
        self.assertIn("flowing three-beat triplet pulse", cfg_std["meter_clause"])

    def test_6_11_8_alternative_groupings(self):
        """Test 6: 11/8 con agrupaciones asimétricas de corcheas."""
        cfg_11_8 = app.resolve_effective_musical_config(
            style="Praise rock, compas 11/8 (3+3+3+2), 130 bpm",
            active_preset=""
        )
        self.assertEqual(cfg_11_8["effective_meter"], "11/8")
        self.assertIn("eleven eighth-note subdivisions per measure", cfg_11_8["meter_clause"])
        self.assertIn("grouped 3+3+3+2", cfg_11_8["meter_clause"])

        cfg_11_def = app.resolve_effective_musical_config(
            style="Complex worship, time signature: 11/8, 125 bpm",
            active_preset=""
        )
        self.assertEqual(cfg_11_def["effective_meter"], "11/8")
        self.assertIn("grouped 2+2+3+2+2", cfg_11_def["meter_clause"])

    def test_7_compatibility_with_4_4_3_4_5_4_6_8_7_4(self):
        """Test 7: Compatibilidad de regresión para 4/4, 3/4, 5/4, 6/8 y 7/4."""
        # 4/4
        cfg_44 = app.resolve_effective_musical_config(style="4/4 time, 120 bpm", active_preset="")
        self.assertEqual(cfg_44["effective_meter"], "4/4")
        self.assertIn("1-and 2-and 3-and 4-and", cfg_44["hihat_clause"])

        # 3/4
        cfg_34 = app.resolve_effective_musical_config(style="3/4 waltz, 90 bpm", active_preset="")
        self.assertEqual(cfg_34["effective_meter"], "3/4")

        # 5/4
        cfg_54 = app.resolve_effective_musical_config(style="5/4 (3+2), 115 bpm", active_preset="")
        self.assertEqual(cfg_54["effective_meter"], "5/4")
        self.assertIn("3+2 pulse", cfg_54["meter_clause"])

        # 6/8
        cfg_68 = app.resolve_effective_musical_config(style="6/8 worship, 54 bpm", active_preset="")
        self.assertEqual(cfg_68["effective_meter"], "6/8")

        # 7/4
        cfg_74 = app.resolve_effective_musical_config(style="7/4 (4+3), 107 bpm", active_preset="")
        self.assertEqual(cfg_74["effective_meter"], "7/4")
        self.assertIn("4+3 rhythm pulse", cfg_74["meter_clause"])

    def test_8_clean_tempo_residual_artifact(self):
        """Test 8: Limpieza estricta del residuo 'Tempo: .' o 'BPM: .'."""
        raw_prompt = "Key: C Major. Tempo: 107 BPM. Time signature: 7/8."
        cfg = app.resolve_effective_musical_config(style=raw_prompt, active_preset="")
        cleaned = app.sanitize_and_prioritize_style_with_config(raw_prompt, cfg)
        self.assertNotIn("Tempo: .", cleaned)
        self.assertNotIn("Tempo: ,", cleaned)
        self.assertNotIn("BPM: .", cleaned)
        self.assertIn("Key: C Major", cleaned)
        self.assertIn("Time signature: 7/8", cleaned)

    def test_9_fulgor_de_dios_full_payload_simulation(self):
        """Test 9: Simulación completa del payload de 'Fulgor de Dios' con preservación total."""
        user_style = (
            "Christian Worship, Acoustic Pop, Folk Rock, Acoustic guitar, Bass guitar, Drums, "
            "Male Tenor vocals, Spiritual, Uplifting, century 1994 rock kit, "
            "Key: C Major. Tempo: 107 BPM. Time signature: 7/8."
        )
        user_lyrics = "[Verse]\nFulgor de Dios en majestad\n[Chorus]\nTu nombre exaltaré"
        cfg = app.resolve_effective_musical_config(
            style=user_style,
            lyrics=user_lyrics,
            target_bpm=107,
            active_preset=""
        )

        style = user_style
        if "century 1994 rock kit" in style:
            style = style.replace(
                "century 1994 rock kit",
                "1994 Century acoustic wood shell drum kit, dynamic live acoustic drum performance, 10 12 14 rack toms"
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
        final_style = ", ".join(combined)

        # Verificaciones críticas
        self.assertIn("strictly in 7/8 time signature (seven eighth-note subdivisions per measure, grouped 2+2+3, recurring accents on subdivisions 1, 3 and 5)", final_style)
        self.assertIn("107 BPM", final_style)
        self.assertIn("Key: C Major", final_style)
        self.assertNotIn("Tempo: .", final_style)
        self.assertNotIn("4/4", final_style)
        self.assertNotIn("snare 2-4", final_style)
        self.assertNotIn("kick 1-3", final_style)
        self.assertNotIn("1-and 2-and 3-and 4-and", final_style)

if __name__ == "__main__":
    unittest.main()
