import unittest
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
INDEX_HTML = os.path.join(REPO_DIR, "index.html")

class TestMicrophoneAudioChain(unittest.TestCase):
    """
    Verifica que la cadena de captura del micrófono en index.html cumpla estrictamente
    con los requisitos de captura continua y seguridad acústica de Android:
    1. Conexión de recMuteGain con ganancia 0.0 hacia audioContext.destination para mantener
       activo el ciclo de reloj Web Audio en Chromium/Android WebView sin fuga sonora.
    2. Buffer de 4096 para baja latencia y estabilidad de hilo en Android.
    3. Silenciado explícito de todos los canales de outputBuffer en onaudioprocess.
    4. Rango dinámico vocal natural preservado (sin limitador digital intrusivo).
    5. Pausa de reproductores activos antes de iniciar grabación.
    6. Liberación de pistas del MediaStream al aplicar o reiniciar.
    7. Medidor VU-Meter aislado de altavoces.
    8. Diagnósticos seguros en consola.
    """

    def setUp(self):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            self.content = f.read()

    def test_01_web_audio_active_clock_chain(self):
        """1. Verificar que la cadena Web Audio mantenga el reloj activo vía MuteGain(0) -> destination."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match, "startLiveRecording no encontrada")
        func_body = start_rec_match.group(1)

        # Conexiones requeridas
        self.assertIn("recSourceNode.connect(analyser);", func_body)
        self.assertIn("recSourceNode.connect(recScriptNode);", func_body)
        self.assertIn("recScriptNode.connect(recMuteGain);", func_body)
        self.assertIn("recMuteGain.connect(recAudioCtx.destination);", func_body)
        self.assertIn("recMuteGain.gain.value = 0.0;", func_body)

    def test_02_script_processor_buffer_size(self):
        """2. ScriptProcessor configurado con 4096 para baja latencia y estabilidad en Android."""
        self.assertIn("recAudioCtx.createScriptProcessor(4096, 1, 1)", self.content)

    def test_03_output_buffer_zeroed(self):
        """3. El buffer de salida del ScriptProcessor se llena de ceros en todos los canales."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match)
        func_body = start_rec_match.group(1)
        self.assertIn("e.outputBuffer.numberOfChannels", func_body)
        self.assertIn(".fill(0)", func_body)

    def test_04_no_intrusive_limiter(self):
        """4. Rango dinámico vocal natural preservado (sin limitador que deforme armónicos o dinámica)."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match)
        func_body = start_rec_match.group(1)
        self.assertNotIn("0.98 + (s - 0.98)", func_body)
        self.assertNotIn("-0.98 + (s + 0.98)", func_body)

    def test_05_pause_existing_playback_before_recording(self):
        """5. Se pausa cualquier reproductor activo (GlobalAudioController y WaveSurfer) antes de grabar."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match)
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

    def test_08_safe_diagnostic_logs_present(self):
        """8. Diagnósticos seguros sin secretos presentes en el flujo de grabación."""
        start_rec_match = re.search(r"async function startLiveRecording\(\)\s*\{(.*?)\n\}", self.content, re.DOTALL)
        self.assertIsNotNone(start_rec_match)
        func_body = start_rec_match.group(1)
        self.assertIn("[REC DIAG]", func_body)
        self.assertIn("[REC AUDIO]", func_body)

if __name__ == "__main__":
    unittest.main()
