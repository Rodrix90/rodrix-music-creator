import os
import sys
import unittest
import numpy as np

# Asegurar path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

import virtual_amp_engine as vae
import free_instruments_engine as fie


class TestVirtualAmpsManualSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Crear señal DI de prueba (44100 Hz, 1 segundo, estéreo, amplitud 10000)
        t = np.arange(44100) / 44100.0
        # Mezcla de frecuencias representativas de guitarra/bajo (110 Hz A2, 220 Hz A3, 440 Hz A4)
        sig = 5000.0 * np.sin(2 * np.pi * 110 * t) + 3000.0 * np.sin(2 * np.pi * 220 * t) + 2000.0 * np.sin(2 * np.pi * 440 * t)
        cls.di_mono = sig.astype(np.float32)
        cls.di_stereo = np.column_stack([sig, sig]).astype(np.float32)

    def test_01_catalog_contains_all_5_amps_and_10_cabs(self):
        """Verifica que el catálogo contenga exactamente los 5 amplificadores y 10 gabinetes."""
        cat = vae.get_amp_catalog_payload()
        self.assertEqual(len(cat["amplifiers"]), 5)
        self.assertEqual(len(cat["cabinets"]), 10)
        amp_ids = [a["id"] for a in cat["amplifiers"]]
        self.assertIn("marshall_jcm800", amp_ids)
        self.assertIn("mesa_dual_rectifier", amp_ids)
        self.assertIn("fender_twin_reverb", amp_ids)
        self.assertIn("ampeg_svt", amp_ids)
        self.assertIn("markbass_little_mark", amp_ids)

    def test_02_manual_amp_selection_changes_sound_character(self):
        """Verifica que cambiar de amplificador altere efectivamente el contenido sonoro."""
        out_jcm = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "marshall_jcm800"})
        out_mesa = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "mesa_dual_rectifier"})
        out_fender = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "fender_twin_reverb"})
        out_ampeg = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "ampeg_svt"})
        out_markbass = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "markbass_little_mark"})

        # Comprobar diferencias significativas entre timbres
        diff_jcm_mesa = np.mean(np.abs(out_jcm - out_mesa))
        diff_jcm_fender = np.mean(np.abs(out_jcm - out_fender))
        diff_ampeg_markbass = np.mean(np.abs(out_ampeg - out_markbass))

        self.assertGreater(diff_jcm_mesa, 500.0, "Mesa y Marshall deben tener respuestas distintas")
        self.assertGreater(diff_jcm_fender, 500.0, "Fender y Marshall deben tener respuestas distintas")
        self.assertGreater(diff_ampeg_markbass, 500.0, "Ampeg y Markbass deben tener respuestas distintas")

    def test_03_manual_cabinet_ir_selection_changes_acoustics(self):
        """Verifica que cambiar de gabinete (IR) modifique la respuesta de convolución espectral."""
        for amp_id, cab1, cab2 in [
            ("marshall_jcm800", "cab_marshall_1960a", "cab_marshall_1960av"),
            ("mesa_dual_rectifier", "cab_mesa_oversized", "cab_mesa_traditional"),
            ("fender_twin_reverb", "cab_fender_twin_jensen", "cab_fender_twin_jbl"),
            ("ampeg_svt", "cab_ampeg_svt810", "cab_ampeg_svt410"),
            ("markbass_little_mark", "cab_markbass_104hf", "cab_markbass_121"),
        ]:
            out_c1 = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": amp_id, "cabinet_id": cab1})
            out_c2 = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": amp_id, "cabinet_id": cab2})
            diff = np.mean(np.abs(out_c1 - out_c2))
            self.assertGreater(diff, 100.0, f"Gabinete {cab1} y {cab2} en {amp_id} deben ser acústicamente diferentes")

    def test_04_gain_knob_and_controls_dict_effective(self):
        """Verifica que los controles manuales de Gain y EQ (anidados en 'controls' o planos) modifiquen el audio."""
        # Formato anidado (como lo envía index.html)
        cfg_low = {"amp_id": "marshall_jcm800", "controls": {"gain": 1.0, "bass": 0.0}}
        cfg_high = {"amp_id": "marshall_jcm800", "controls": {"gain": 9.5, "bass": 0.0}}

        out_low = vae.process_audio_through_amplifier(self.di_stereo.copy(), cfg_low)
        out_high = vae.process_audio_through_amplifier(self.di_stereo.copy(), cfg_high)
        diff = np.mean(np.abs(out_low - out_high))
        self.assertGreater(diff, 300.0, "Knob de Gain debe modificar significativamente la saturación")

    def test_05_level_normalization_and_no_clipping_explosion(self):
        """Verifica que el nivel de salida no explote y conserve el rango dinámico del audio original."""
        orig_peak = float(np.max(np.abs(self.di_stereo)))
        out = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "marshall_jcm800"})
        out_peak = float(np.max(np.abs(out)))

        # El pico debe ser aproximadamente igual al original (margen del 5%) y NUNCA en millones
        self.assertLess(out_peak, orig_peak * 1.05)
        self.assertGreater(out_peak, orig_peak * 0.80)
        self.assertLess(out_peak, 32768.0, "No debe exceder 16-bit")

    def test_06_bypass_mode_preserves_audio_strictly(self):
        """Verifica que el modo Bypass devuelva la señal original sin procesar."""
        out_byp1 = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "marshall_jcm800", "bypass": True})
        out_byp2 = vae.process_audio_through_amplifier(self.di_stereo.copy(), {"amp_id": "marshall_jcm800", "enabled": False})
        np.testing.assert_array_equal(self.di_stereo, out_byp1)
        np.testing.assert_array_equal(self.di_stereo, out_byp2)

    def test_07_fluidsynth_generation_applies_amps_to_guitar_and_bass(self):
        """Verifica que la generación multipista aplique los amplificadores seleccionados a guitarra y bajo."""
        out_mp3 = "test_amp_synth_out.mp3"
        try:
            res = fie.synthesize_multitrack_composition(
                tracks_config=[
                    {"id": "guitarra_limpia", "volume": 0.9},
                    {"id": "bajo_finger", "volume": 0.85},
                    {"id": "synth_bass", "volume": 0.8},
                ],
                output_mp3_path=out_mp3,
                bpm=100,
                bars=2,
                amp_configs={
                    "guitar": {"amp_id": "fender_twin_reverb", "cabinet_id": "cab_fender_twin_jensen", "controls": {"gain": 4.0}},
                    "bass": {"amp_id": "markbass_little_mark", "cabinet_id": "cab_markbass_104hf", "controls": {"gain": 5.0}},
                }
            )
            tracks_map = {t["id"]: t for t in res["tracks"]}
            # Guitarra limpia debe tener fender_twin_reverb
            self.assertEqual(tracks_map["guitarra_limpia"]["amp_applied"], "fender_twin_reverb")
            self.assertEqual(tracks_map["guitarra_limpia"]["cabinet_applied"], "cab_fender_twin_jensen")
            # Bajo finger debe tener markbass_little_mark
            self.assertEqual(tracks_map["bajo_finger"]["amp_applied"], "markbass_little_mark")
            self.assertEqual(tracks_map["bajo_finger"]["cabinet_applied"], "cab_markbass_104hf")
            # Synth bass debe tener markbass_little_mark
            self.assertEqual(tracks_map["synth_bass"]["amp_applied"], "markbass_little_mark")
            self.assertTrue(os.path.exists(out_mp3))
            self.assertGreater(os.path.getsize(out_mp3), 1000)
        finally:
            if os.path.exists(out_mp3):
                os.remove(out_mp3)


if __name__ == "__main__":
    unittest.main()
