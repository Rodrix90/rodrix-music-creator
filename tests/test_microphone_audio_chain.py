import unittest
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INDEX_HTML = os.path.join(REPO_DIR, "index.html")

class TestMicrophoneAudioChain(unittest.TestCase):
    """
    Verifica que la cadena de captura del micrófono en index.html cumpla estrictamente
    con los requisitos de seguridad acústica de Android:
    1. 0 conexiones hacia audioContext.destination (evita realimentación / retorno por altavoz).
    2. Buffer de baja latencia (4096).
    3. Silenciado explícito de outputBuffer en onaudioprocess.
    4. Soft limiter contra clipping digital (> 0.98).
    5. Pausa de reproductores activos antes de iniciar grabación.
    6. Liberación de pistas del MediaStream al aplicar o reiniciar.
    """

    def setUp(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_01_no_connection_to_audio_context_destination(self):
        """1. Garantizar que ninguna salida del micrófono se conecte a audioContext.destination."""
        # Buscar conexiones a .destination en la función startLiveRecording
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match, "startLiveRecording no encontrada")
        func_body = start_rec_match.group(1)

        # No debe haber ninguna llamada a .connect(recAudioCtx.destination) ni a destination
        active_destination_calls = [
            line for line in func_body.splitlines()
            if ".connect(" in line and "destination" in line and not line.strip().startswith("//")
        ]
        self.assertEqual(
            len(active_destination_calls), 0,
            f"Se encontró conexión activa hacia destination que provocaría feedback: {active_destination_calls}"
        )

    def test_02_script_processor_buffer_size(self):
        """2. ScriptProcessor configurado con 4096 para baja latencia y estabilidad en Android."""
        self.assertIn("recAudioCtx.createScriptProcessor(4096, 1, 1)", self.content)

    def test_03_output_buffer_zeroed(self):
        """3. El buffer de salida del ScriptProcessor se llena de ceros (silencio digital)."""
        self.assertIn("outputData.fill(0)", self.content)

    def test_04_soft_clipping_prevention(self):
        """4. Limitador suave de picos (> 0.98) para evitar saturación y clipping digital."""
        self.assertIn("0.98 + (s - 0.98) * 0.1", self.content)
        self.assertIn("-0.98 + (s + 0.98) * 0.1", self.content)

    def test_05_pause_existing_playback_before_recording(self):
        """5. Se pausa cualquier reproductor activo (GlobalAudioController y WaveSurfer) antes de grabar."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        func_body = start_rec_match.group(1)
        self.assertIn("GlobalAudioController.pause()", func_body)
        self.assertIn("recWs.pause()", func_body)

    def test_06_microphone_tracks_released(self):
        """6. Las pistas de MediaStream se detienen al aplicar o descartar la grabación."""
        apply_match = re.search(r"function applyLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(apply_match)
        apply_body = apply_match.group(1)
        self.assertIn("recMediaStream.getTracks().forEach(t => t.stop())", apply_body)

        reset_match = re.search(r"function resetLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(reset_match)
        reset_body = reset_match.group(1)
        self.assertIn("recMediaStream.getTracks().forEach(t => t.stop())", reset_body)

    def test_07_vu_meter_analyser_does_not_route_to_speakers(self):
        """7. Los analizadores de VU-Meter y osciloscopio no se conectan a altavoces."""
        vu_match = re.search(r"function startBroadcastVuMeter\(.*?\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(vu_match)
        vu_body = vu_match.group(1)
        self.assertNotIn("destination", vu_body)

if __name__ == "__main__":
    unittest.main()
