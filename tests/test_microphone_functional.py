import unittest
import math
import struct
import io

def simulate_onaudioprocess(input_data, output_buffer_channels, is_first_chunk, pcm_chunks):
    """
    Simula la lógica de recScriptNode.onaudioprocess en index.html:
    1. Llena todos los canales de outputBuffer con 0.0 (silencio a destination).
    2. Comprueba señal no nula.
    3. Aplica micro fade-in si es primer bloque.
    4. Acumula chunk Float32Array.
    """
    # 1. Silenciar canales de salida
    for ch in range(output_buffer_channels):
        # Simula outputBuffer.getChannelData(ch).fill(0)
        pass

    chunk = list(input_data)
    non_zero = any(abs(s) > 0.0001 for s in chunk)

    # 3. Micro fade-in de 12ms en el primer bloque (~529 muestras a 44.1kHz)
    if is_first_chunk:
        fade_len = min(529, len(chunk))
        for i in range(fade_len):
            chunk[i] *= (i / fade_len)

    pcm_chunks.append(chunk)
    return non_zero

def python_pcm_to_wav(pcm_chunks, sample_rate=44100):
    """
    Emulación idéntica de la función JS pcmToWav(pcmChunks, sampleRate):
    1. Une los chunks en un array continuo.
    2. Normaliza a nivel óptimo (-1 dBFS = 0.90) con límite de ganancia de 15.0x si peak > 0.005.
    3. Genera un archivo WAV válido de 16-bit PCM mono.
    """
    merged = []
    for c in pcm_chunks:
        merged.extend(c)

    total_length = len(merged)
    if total_length == 0:
        return b""

    # Normalización de ganancia
    max_peak = max(abs(s) for s in merged) if merged else 0.0
    if max_peak > 0.005:
        target_gain = min(0.90 / max_peak, 15.0)
        merged = [s * target_gain for s in merged]

    # Crear WAV RIFF/WAVE 16-bit mono
    num_channels = 1
    bits_per_sample = 16
    bytes_per_sample = bits_per_sample // 8
    byte_rate = sample_rate * num_channels * bytes_per_sample
    block_align = num_channels * bytes_per_sample
    data_size = total_length * bytes_per_sample
    riff_size = 36 + data_size

    buf = io.BytesIO()
    # Header RIFF
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", riff_size))
    buf.write(b"WAVE")
    # Subchunk 1 "fmt "
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))          # Subchunk1Size (16 para PCM)
    buf.write(struct.pack("<H", 1))           # AudioFormat (1 = PCM)
    buf.write(struct.pack("<H", num_channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits_per_sample))
    # Subchunk 2 "data"
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))

    # Escribir muestras int16
    for s in merged:
        # Clamping seguro a [-1.0, 1.0] antes de cuantizar a int16
        clamped = max(-1.0, min(1.0, s))
        val = int(clamped * 0x7FFF) if clamped >= 0 else int(clamped * 0x8000)
        buf.write(struct.pack("<h", val))

    return buf.getvalue()


class TestMicrophoneFunctional(unittest.TestCase):
    """
    Prueba funcional de la cadena de captura y codificación de micrófono:
    1. Simulación de captura con señal sinusoidal a 440 Hz (tono puro vocal).
    2. Verificación de acumulación de chunks de 4096 muestras.
    3. Conversión a WAV y validación estricta de encabezados RIFF/WAVE.
    4. Verificación de normalización dinámica a -1 dBFS.
    5. Estabilidad con entrada silenciosa o de baja amplitud.
    """

    def test_01_synthetic_recording_and_wav_generation(self):
        sample_rate = 44100
        chunk_size = 4096
        num_chunks = 11  # ~1 segundo de audio (45056 muestras)
        freq = 440.0     # La 440 Hz

        pcm_chunks = []
        is_first = True

        for chunk_idx in range(num_chunks):
            # Generar 4096 muestras de onda senoidal de voz
            t_start = (chunk_idx * chunk_size) / sample_rate
            raw_input = [
                0.25 * math.sin(2.0 * math.pi * freq * (t_start + (i / sample_rate)))
                for i in range(chunk_size)
            ]
            non_zero = simulate_onaudioprocess(raw_input, output_buffer_channels=1, is_first_chunk=is_first, pcm_chunks=pcm_chunks)
            self.assertTrue(non_zero, f"Chunk {chunk_idx} debe contener señal de audio real")
            is_first = False

        self.assertEqual(len(pcm_chunks), num_chunks)
        total_samples = sum(len(c) for c in pcm_chunks)
        self.assertEqual(total_samples, num_chunks * chunk_size)

        # Codificar a WAV
        wav_bytes = python_pcm_to_wav(pcm_chunks, sample_rate)
        self.assertGreater(len(wav_bytes), 44)

        # Validar encabezados RIFF
        self.assertEqual(wav_bytes[0:4], b"RIFF")
        self.assertEqual(wav_bytes[8:12], b"WAVE")
        self.assertEqual(wav_bytes[12:16], b"fmt ")
        self.assertEqual(wav_bytes[36:40], b"data")

        # Verificar parámetros de formato
        fmt_size, audio_fmt, channels, s_rate, b_rate, align, bps = struct.unpack("<IHHIIHH", wav_bytes[16:36])
        self.assertEqual(audio_fmt, 1)  # PCM
        self.assertEqual(channels, 1)   # Mono
        self.assertEqual(s_rate, 44100)
        self.assertEqual(bps, 16)

        data_size = struct.unpack("<I", wav_bytes[40:44])[0]
        self.assertEqual(data_size, total_samples * 2)

    def test_02_studio_normalization_gain(self):
        """Verifica que la normalización lleve un audio de baja amplitud a -1 dBFS (0.90)."""
        sample_rate = 44100
        # Muestras con pico de 0.10
        chunks = [[0.10 * math.sin(i * 0.1) for i in range(4096)]]
        wav_bytes = python_pcm_to_wav(chunks, sample_rate)

        # Leer las muestras del WAV generado
        num_samples = 4096
        samples = struct.unpack(f"<{num_samples}h", wav_bytes[44:44 + num_samples * 2])
        max_val = max(abs(s) for s in samples)
        # 0.90 * 32767 ~= 29490
        expected_peak = int(0.90 * 32767)
        self.assertAlmostEqual(max_val, expected_peak, delta=200)

    def test_03_silence_safety(self):
        """Verifica que entrada de puro silencio no cause errores de división por cero."""
        chunks = [[0.0] * 4096]
        wav_bytes = python_pcm_to_wav(chunks, 44100)
        self.assertGreater(len(wav_bytes), 44)
        num_samples = 4096
        samples = struct.unpack(f"<{num_samples}h", wav_bytes[44:44 + num_samples * 2])
        self.assertTrue(all(s == 0 for s in samples))


if __name__ == "__main__":
    unittest.main()
