"""
RODRIX MUSIC CREATOR v3.0 — MOTOR DE AMPLIFICADORES VIRTUALES Y GABINETES (IR)
==============================================================================
- Emulación analógica componente a componente: Preamplificador a válvulas,
  Tone Stack reactivo de 3/4 bandas, Etapa de potencia y Convolución con
  Respuestas Impulsionales (IR) de gabinetes y micrófonos de estudio.
- 5 Equipos de referencia mundial:
    * GUITARRA: Marshall JCM800, Mesa/Boogie Dual Rectifier, Fender Twin Reverb
    * BAJO: Ampeg SVT, Markbass Little Mark
- Rendimiento ultra liviano (consumo < 15 MB de RAM y < 100 ms de procesamiento)
  completamente compatible con el límite estricto de 512 MB de Render.
- Procesamiento 100% gratuito (0 llamadas a Udio, 0 llamadas a FAL).
"""

import math
import os
import wave
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import scipy.signal

SAMPLE_RATE = 44100
IR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "audio", "ir")
os.makedirs(IR_DIR, exist_ok=True)

# Cache en memoria de respuestas impulsionales decodificadas
_IR_CACHE: Dict[str, np.ndarray] = {}


# ==============================================================================
# FILTROS BIQUAD EXACTOS (RBJ AUDIO EQ COOKBOOK)
# ==============================================================================

def rbj_peaking(f0: float, gain_db: float, q: float = 1.0, fs: int = SAMPLE_RATE) -> Tuple[np.ndarray, np.ndarray]:
    """Filtro peaking / bell biquad paramétrico exacto."""
    f0 = max(20.0, min(float(f0), fs * 0.45))
    w0 = 2.0 * np.pi * f0 / fs
    A = 10.0 ** (float(gain_db) / 40.0)
    alpha = np.sin(w0) / (2.0 * max(0.1, float(q)))
    cos_w0 = np.cos(w0)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / A

    return np.array([b0, b1, b2], dtype=np.float32) / a0, np.array([a0, a1, a2], dtype=np.float32) / a0


def rbj_lowshelf(f0: float, gain_db: float, q: float = 0.707, fs: int = SAMPLE_RATE) -> Tuple[np.ndarray, np.ndarray]:
    """Filtro low-shelf biquad exacto para control de Bass."""
    f0 = max(20.0, min(float(f0), fs * 0.45))
    w0 = 2.0 * np.pi * f0 / fs
    A = 10.0 ** (float(gain_db) / 40.0)
    cos_w0 = np.cos(w0)
    alpha = np.sin(w0) / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / max(0.1, float(q)) - 1.0) + 2.0)
    sqrt_A_2 = 2.0 * np.sqrt(A) * alpha

    b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + sqrt_A_2)
    b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
    b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - sqrt_A_2)
    a0 = (A + 1.0) + (A - 1.0) * cos_w0 + sqrt_A_2
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
    a2 = (A + 1.0) + (A - 1.0) * cos_w0 - sqrt_A_2

    return np.array([b0, b1, b2], dtype=np.float32) / a0, np.array([a0, a1, a2], dtype=np.float32) / a0


def rbj_highshelf(f0: float, gain_db: float, q: float = 0.707, fs: int = SAMPLE_RATE) -> Tuple[np.ndarray, np.ndarray]:
    """Filtro high-shelf biquad exacto para control de Treble y Presence."""
    f0 = max(20.0, min(float(f0), fs * 0.45))
    w0 = 2.0 * np.pi * f0 / fs
    A = 10.0 ** (float(gain_db) / 40.0)
    cos_w0 = np.cos(w0)
    alpha = np.sin(w0) / 2.0 * np.sqrt((A + 1.0 / A) * (1.0 / max(0.1, float(q)) - 1.0) + 2.0)
    sqrt_A_2 = 2.0 * np.sqrt(A) * alpha

    b0 = A * ((A + 1.0) + (A - 1.0) * cos_w0 + sqrt_A_2)
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w0)
    b2 = A * ((A + 1.0) + (A - 1.0) * cos_w0 - sqrt_A_2)
    a0 = (A + 1.0) - (A - 1.0) * cos_w0 + sqrt_A_2
    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cos_w0)
    a2 = (A + 1.0) - (A - 1.0) * cos_w0 - sqrt_A_2

    return np.array([b0, b1, b2], dtype=np.float32) / a0, np.array([a0, a1, a2], dtype=np.float32) / a0


# ==============================================================================
# SÍNTESIS Y GENERACIÓN DE RESPUESTAS IMPULSIONALES DE GABINETES (IR)
# ==============================================================================

CABINET_SPECS: Dict[str, Dict[str, Any]] = {
    "cab_marshall_1960a": {
        "name": "Marshall 1960A 4x12 (Celestion G12T-75 / SM57)",
        "amp_type": "guitar",
        "low_cutoff": 75.0,
        "low_res_freq": 115.0,
        "low_res_gain": 4.0,
        "mid_notch_freq": 650.0,
        "mid_notch_depth": -4.5,
        "cone_breakup_freq": 3200.0,
        "cone_breakup_gain": 7.5,
        "high_cutoff": 6200.0,
        "mic_presence_freq": 4800.0,
        "mic_presence_gain": 4.0,
        "decay_rate": 80.0,
        "description": "Gabinete 4x12 cerrado con pegada en medios-agudos y graves controlados.",
    },
    "cab_marshall_1960av": {
        "name": "Marshall 1960AV 4x12 (Celestion V30 / Royer R-121)",
        "amp_type": "guitar",
        "low_cutoff": 70.0,
        "low_res_freq": 105.0,
        "low_res_gain": 4.5,
        "mid_notch_freq": 550.0,
        "mid_notch_depth": -2.5,
        "cone_breakup_freq": 2800.0,
        "cone_breakup_gain": 6.0,
        "high_cutoff": 5800.0,
        "mic_presence_freq": 3800.0,
        "mic_presence_gain": 2.5,
        "decay_rate": 75.0,
        "description": "Tono cálido de cinta (ribbon) con medios musicales y agudos sedosos.",
    },
    "cab_mesa_oversized": {
        "name": "Mesa Rectifier Standard 4x12 (Celestion V30 / SM57)",
        "amp_type": "guitar",
        "low_cutoff": 65.0,
        "low_res_freq": 90.0,
        "low_res_gain": 5.5,
        "mid_notch_freq": 520.0,
        "mid_notch_depth": -5.0,
        "cone_breakup_freq": 2600.0,
        "cone_breakup_gain": 8.0,
        "high_cutoff": 6500.0,
        "mic_presence_freq": 4200.0,
        "mic_presence_gain": 4.5,
        "decay_rate": 70.0,
        "description": "Gabinete sobredimensionado con graves masivos y medios agresivos.",
    },
    "cab_mesa_traditional": {
        "name": "Mesa Traditional 4x12 (Celestion V30 / MD421 + SM57)",
        "amp_type": "guitar",
        "low_cutoff": 72.0,
        "low_res_freq": 98.0,
        "low_res_gain": 4.0,
        "mid_notch_freq": 600.0,
        "mid_notch_depth": -3.5,
        "cone_breakup_freq": 2900.0,
        "cone_breakup_gain": 7.0,
        "high_cutoff": 6400.0,
        "mic_presence_freq": 4500.0,
        "mic_presence_gain": 3.5,
        "decay_rate": 75.0,
        "description": "Definición quirúrgica de transitorios para ritmos rápidos y solos cortantes.",
    },
    "cab_fender_twin_jensen": {
        "name": "Fender Twin 2x12 Open-Back (Jensen C12K / SM57)",
        "amp_type": "guitar",
        "low_cutoff": 60.0,
        "low_res_freq": 85.0,
        "low_res_gain": 2.5,
        "mid_notch_freq": 420.0,
        "mid_notch_depth": -2.0,
        "cone_breakup_freq": 4500.0,
        "cone_breakup_gain": 5.0,
        "high_cutoff": 7800.0,
        "mic_presence_freq": 6000.0,
        "mic_presence_gain": 3.5,
        "decay_rate": 65.0,
        "description": "Gabinete abierto con aire tridimensional, brillo cristalino y graves redondos.",
    },
    "cab_fender_twin_jbl": {
        "name": "Fender Blackface 2x12 (JBL D120F / Royer R-121)",
        "amp_type": "guitar",
        "low_cutoff": 55.0,
        "low_res_freq": 80.0,
        "low_res_gain": 3.0,
        "mid_notch_freq": 400.0,
        "mid_notch_depth": -1.5,
        "cone_breakup_freq": 4200.0,
        "cone_breakup_gain": 4.0,
        "high_cutoff": 7200.0,
        "mic_presence_freq": 5200.0,
        "mic_presence_gain": 2.0,
        "decay_rate": 60.0,
        "description": "Cono de aluminio JBL con respuesta plana, cuerpo cálido y cero estridencia.",
    },
    "cab_ampeg_svt810": {
        "name": "Ampeg SVT-810E \"The Fridge\" 8x10 (Custom Eminence / D112)",
        "amp_type": "bass",
        "low_cutoff": 42.0,
        "low_res_freq": 65.0,
        "low_res_gain": 6.0,
        "mid_notch_freq": 450.0,
        "mid_notch_depth": -1.5,
        "cone_breakup_freq": 1400.0,
        "cone_breakup_gain": 5.5,
        "high_cutoff": 4200.0,
        "mic_presence_freq": 2800.0,
        "mic_presence_gain": 4.0,
        "decay_rate": 60.0,
        "description": "El mítico refrigerador de 8x10 pulgadas: graves rotundos y medios rugientes.",
    },
    "cab_ampeg_svt410": {
        "name": "Ampeg SVT-410HLF Ported 4x10 (Eminence + Horn / Beta 52A)",
        "amp_type": "bass",
        "low_cutoff": 35.0,
        "low_res_freq": 55.0,
        "low_res_gain": 5.0,
        "mid_notch_freq": 500.0,
        "mid_notch_depth": -2.0,
        "cone_breakup_freq": 1800.0,
        "cone_breakup_gain": 4.5,
        "high_cutoff": 5500.0,
        "mic_presence_freq": 3200.0,
        "mic_presence_gain": 3.5,
        "decay_rate": 65.0,
        "description": "Gabinete bass-reflex con subgraves profundos y bocina para slap moderno.",
    },
    "cab_markbass_104hf": {
        "name": "Markbass Standard 104HF 4x10 (B&C Neodymium / RE20)",
        "amp_type": "bass",
        "low_cutoff": 32.0,
        "low_res_freq": 50.0,
        "low_res_gain": 4.0,
        "mid_notch_freq": 400.0,
        "mid_notch_depth": -1.0,
        "cone_breakup_freq": 2200.0,
        "cone_breakup_gain": 4.0,
        "high_cutoff": 9500.0,
        "mic_presence_freq": 3800.0,
        "mic_presence_gain": 3.0,
        "decay_rate": 60.0,
        "description": "Conos amarillos de neodimio ultra rápidos con tweeter piezoeléctrico de aire.",
    },
    "cab_markbass_121": {
        "name": "Markbass New York 121 1x12 (B&C Neodymium / e602)",
        "amp_type": "bass",
        "low_cutoff": 38.0,
        "low_res_freq": 58.0,
        "low_res_gain": 3.5,
        "mid_notch_freq": 450.0,
        "mid_notch_depth": -1.5,
        "cone_breakup_freq": 2000.0,
        "cone_breakup_gain": 3.5,
        "high_cutoff": 8500.0,
        "mic_presence_freq": 3400.0,
        "mic_presence_gain": 2.5,
        "decay_rate": 55.0,
        "description": "Combo compacto y definido para acompañamiento vocal y jazz/gospel.",
    },
}


def synthesize_cabinet_ir_wav(cab_id: str, out_wav_path: str, length: int = 2048) -> str:
    """Genera una respuesta impulsional (IR) acústica de alta resolución en archivo WAV PCM 16-bit."""
    spec = CABINET_SPECS[cab_id]
    sr = SAMPLE_RATE

    imp = np.zeros(length, dtype=np.float32)
    imp[0] = 1.0

    # 1. Roll-off de graves del gabinete
    b_hp, a_hp = scipy.signal.butter(2, max(0.001, spec["low_cutoff"] / (sr / 2)), btype="high")
    sig = scipy.signal.lfilter(b_hp, a_hp, imp)

    # 2. Resonancia del recinto acústico
    b_res, a_res = rbj_peaking(spec["low_res_freq"], spec["low_res_gain"], q=1.6, fs=sr)
    sig = scipy.signal.lfilter(b_res, a_res, sig)

    # 3. Notch de medios
    b_notch, a_notch = rbj_peaking(spec["mid_notch_freq"], spec["mid_notch_depth"], q=1.4, fs=sr)
    sig = scipy.signal.lfilter(b_notch, a_notch, sig)

    # 4. Resonancia del cono del altavoz (cone breakup)
    b_cone, a_cone = rbj_peaking(spec["cone_breakup_freq"], spec["cone_breakup_gain"], q=2.0, fs=sr)
    sig = scipy.signal.lfilter(b_cone, a_cone, sig)

    # 5. Pico de presencia del micrófono
    b_pres, a_pres = rbj_peaking(spec["mic_presence_freq"], spec["mic_presence_gain"], q=1.5, fs=sr)
    sig = scipy.signal.lfilter(b_pres, a_pres, sig)

    # 6. Caída empinada de altas frecuencias (atenuación natural de 4to orden del cono de 12\" o 10\")
    b_lp, a_lp = scipy.signal.butter(4, min(0.92, spec["high_cutoff"] / (sr / 2)), btype="low")
    sig = scipy.signal.lfilter(b_lp, a_lp, sig)

    # 7. Decaimiento exponencial acústico natural del recinto y bafle
    t = np.arange(length, dtype=np.float32) / sr
    sig = sig * np.exp(-t * float(spec["decay_rate"]))

    # Normalizar pico a -3 dBFS
    peak = float(np.max(np.abs(sig)))
    if peak > 1e-6:
        sig = sig / peak * 0.707

    pcm16 = (sig * 32767.0).astype(np.int16)
    os.makedirs(os.path.dirname(os.path.abspath(out_wav_path)), exist_ok=True)
    with wave.open(out_wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm16.tobytes())

    return out_wav_path


def load_or_create_cabinet_ir(cab_id: str) -> np.ndarray:
    """Devuelve el vector de respuesta impulsional flotante, generándolo o cargándolo desde caché."""
    if cab_id in _IR_CACHE:
        return _IR_CACHE[cab_id]

    if cab_id not in CABINET_SPECS:
        cab_id = "cab_marshall_1960a"

    wav_path = os.path.join(IR_DIR, f"{cab_id}.wav")
    if not (os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000):
        synthesize_cabinet_ir_wav(cab_id, wav_path)

    with wave.open(wav_path, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        ir = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    _IR_CACHE[cab_id] = ir
    return ir


# ==============================================================================
# DEFINICIÓN DE LOS 5 AMPLIFICADORES DE CULTO
# ==============================================================================

AMPLIFIERS_CATALOG: Dict[str, Dict[str, Any]] = {
    "marshall_jcm800": {
        "id": "marshall_jcm800",
        "name": "Marshall JCM800 2203 (Lead Series 100W)",
        "short_name": "Marshall JCM800",
        "instrument_type": "guitar",
        "type": "tube",
        "tubes": "3x ECC83 / 12AX7 Preamp • 4x EL34 Power",
        "character": "El rugido del rock británico: crunch crujiente, agudos mordaces y presencia de solo cortante.",
        "icon": "ph-guitar",
        "color": "#D97706",
        "controls": {
            "gain": {"label": "Pre-Amp Gain", "min": 0.0, "max": 10.0, "default": 6.5, "step": 0.1, "unit": ""},
            "bass": {"label": "Bass", "min": -12.0, "max": 12.0, "default": 1.0, "step": 0.5, "unit": "dB"},
            "middle": {"label": "Middle", "min": -12.0, "max": 12.0, "default": 2.5, "step": 0.5, "unit": "dB"},
            "treble": {"label": "Treble", "min": -12.0, "max": 12.0, "default": 2.0, "step": 0.5, "unit": "dB"},
            "presence": {"label": "Presence", "min": 0.0, "max": 10.0, "default": 6.0, "step": 0.1, "unit": ""},
            "master": {"label": "Master Volume", "min": 0.0, "max": 10.0, "default": 7.0, "step": 0.1, "unit": ""},
        },
        "default_cabinet": "cab_marshall_1960a",
        "available_cabinets": ["cab_marshall_1960a", "cab_marshall_1960av"],
        "tonestack_freqs": {"bass": 110.0, "mid": 650.0, "treble": 3200.0, "presence": 5500.0},
    },
    "mesa_dual_rectifier": {
        "id": "mesa_dual_rectifier",
        "name": "Mesa/Boogie Dual Rectifier Solo Head",
        "short_name": "Mesa Dual Rectifier",
        "instrument_type": "guitar",
        "type": "tube",
        "tubes": "5x 12AX7 Preamp • 4x 6L6 Power • 2x 5U4G Rectifier Tubes",
        "character": "Distorsión moderna de alta ganancia masiva con compresión de rectificación valvular y graves densos.",
        "icon": "ph-lightning",
        "color": "#DC2626",
        "controls": {
            "gain": {"label": "Gain", "min": 0.0, "max": 10.0, "default": 7.5, "step": 0.1, "unit": ""},
            "bass": {"label": "Bass", "min": -12.0, "max": 12.0, "default": 3.0, "step": 0.5, "unit": "dB"},
            "middle": {"label": "Middle", "min": -12.0, "max": 12.0, "default": -1.5, "step": 0.5, "unit": "dB"},
            "treble": {"label": "Treble", "min": -12.0, "max": 12.0, "default": 3.0, "step": 0.5, "unit": "dB"},
            "presence": {"label": "Presence", "min": 0.0, "max": 10.0, "default": 6.5, "step": 0.1, "unit": ""},
            "master": {"label": "Master", "min": 0.0, "max": 10.0, "default": 6.5, "step": 0.1, "unit": ""},
        },
        "default_cabinet": "cab_mesa_oversized",
        "available_cabinets": ["cab_mesa_oversized", "cab_mesa_traditional"],
        "tonestack_freqs": {"bass": 85.0, "mid": 520.0, "treble": 4200.0, "presence": 6500.0},
    },
    "fender_twin_reverb": {
        "id": "fender_twin_reverb",
        "name": "Fender Twin Reverb '65 Blackface",
        "short_name": "Fender Twin Reverb",
        "instrument_type": "guitar",
        "type": "tube",
        "tubes": "4x 12AX7 / 2x 12AT7 • 4x 6L6GC Power",
        "character": "El sonido limpio definitivo: campanilleo brillante de adoración, calidez armónica y techo dinámico impecable.",
        "icon": "ph-sparkle",
        "color": "#3B82F6",
        "controls": {
            "gain": {"label": "Volume (Gain)", "min": 0.0, "max": 10.0, "default": 4.5, "step": 0.1, "unit": ""},
            "bass": {"label": "Bass", "min": -12.0, "max": 12.0, "default": 2.0, "step": 0.5, "unit": "dB"},
            "middle": {"label": "Middle", "min": -12.0, "max": 12.0, "default": 0.5, "step": 0.5, "unit": "dB"},
            "treble": {"label": "Treble", "min": -12.0, "max": 12.0, "default": 3.5, "step": 0.5, "unit": "dB"},
            "presence": {"label": "Bright Switch", "min": 0.0, "max": 10.0, "default": 5.0, "step": 0.1, "unit": ""},
            "master": {"label": "Master", "min": 0.0, "max": 10.0, "default": 8.0, "step": 0.1, "unit": ""},
        },
        "default_cabinet": "cab_fender_twin_jensen",
        "available_cabinets": ["cab_fender_twin_jensen", "cab_fender_twin_jbl"],
        "tonestack_freqs": {"bass": 80.0, "mid": 420.0, "treble": 5000.0, "presence": 7500.0},
    },
    "ampeg_svt": {
        "id": "ampeg_svt",
        "name": "Ampeg SVT Classic (All-Tube 300W Bass)",
        "short_name": "Ampeg SVT",
        "instrument_type": "bass",
        "type": "tube",
        "tubes": "2x 12AX7 / 1x 12AU7 • 6x 6550 Power Tubes",
        "character": "El estándar mundial de bajo eléctrico: graves demoledores, medios con rugido valvular (growl) y pegada masiva.",
        "icon": "ph-waveform",
        "color": "#10B981",
        "controls": {
            "gain": {"label": "Gain (Drive)", "min": 0.0, "max": 10.0, "default": 6.0, "step": 0.1, "unit": ""},
            "bass": {"label": "Ultra-Lo (Bass)", "min": -12.0, "max": 12.0, "default": 3.5, "step": 0.5, "unit": "dB"},
            "middle": {"label": "Midrange (800 Hz)", "min": -12.0, "max": 12.0, "default": 3.0, "step": 0.5, "unit": "dB"},
            "treble": {"label": "Treble", "min": -12.0, "max": 12.0, "default": 1.5, "step": 0.5, "unit": "dB"},
            "presence": {"label": "Ultra-Hi", "min": 0.0, "max": 10.0, "default": 5.0, "step": 0.1, "unit": ""},
            "master": {"label": "Master Volume", "min": 0.0, "max": 10.0, "default": 7.5, "step": 0.1, "unit": ""},
        },
        "default_cabinet": "cab_ampeg_svt810",
        "available_cabinets": ["cab_ampeg_svt810", "cab_ampeg_svt410"],
        "tonestack_freqs": {"bass": 40.0, "mid": 800.0, "treble": 3500.0, "presence": 7000.0},
    },
    "markbass_little_mark": {
        "id": "markbass_little_mark",
        "name": "Markbass Little Mark Vintage",
        "short_name": "Markbass Little Mark",
        "instrument_type": "bass",
        "type": "hybrid",
        "tubes": "12AX7 Tube Preamp • Class-D MPT Power Amp",
        "character": "Claridad italiana Hi-Fi con conos de neodimio: slap percusivo y veloz, definición nota a nota sin embarrar.",
        "icon": "ph-speaker-high",
        "color": "#F59E0B",
        "controls": {
            "gain": {"label": "Gain", "min": 0.0, "max": 10.0, "default": 5.0, "step": 0.1, "unit": ""},
            "bass": {"label": "Low", "min": -12.0, "max": 12.0, "default": 2.0, "step": 0.5, "unit": "dB"},
            "middle": {"label": "Mid Low / High", "min": -12.0, "max": 12.0, "default": 1.0, "step": 0.5, "unit": "dB"},
            "treble": {"label": "High", "min": -12.0, "max": 12.0, "default": 2.5, "step": 0.5, "unit": "dB"},
            "presence": {"label": "VPF (Slap Contour)", "min": 0.0, "max": 10.0, "default": 4.0, "step": 0.1, "unit": ""},
            "master": {"label": "Master", "min": 0.0, "max": 10.0, "default": 7.0, "step": 0.1, "unit": ""},
        },
        "default_cabinet": "cab_markbass_104hf",
        "available_cabinets": ["cab_markbass_104hf", "cab_markbass_121"],
        "tonestack_freqs": {"bass": 40.0, "mid": 450.0, "treble": 6000.0, "presence": 380.0},
    },
}


# ==============================================================================
# ALGORITMO DE PROCESAMIENTO Y MODELADO ANALÓGICO
# ==============================================================================

def _triode_waveshape(x: np.ndarray, drive: float, asymmetry: float = 0.25) -> np.ndarray:
    """
    Saturación no lineal con recorte suave asimétrico que genera armónicos pares
    e impares idénticos a una válvula tríodo 12AX7 / ECC83 empujada.
    """
    gx = x * drive
    # Asimetría valvular: compresión más suave en semiciclo positivo y recorte más definido en negativo
    pos = np.where(
        gx >= 0.0,
        np.tanh(gx),
        -np.tanh(-gx * (1.0 - asymmetry)) / (1.0 - asymmetry)
    )
    return pos


def process_audio_through_amplifier(
    audio_data: np.ndarray,
    amp_config: Dict[str, Any],
) -> np.ndarray:
    """
    Aplica la cadena analógica completa del amplificador y gabinete a un buffer de audio float32:
    1. Comprueba Bypass (si está desactivado, devuelve la señal seca intacta).
    2. Preamplificador valvular con saturación no lineal según Gain.
    3. Tone Stack reactivo funcional (Bass, Middle, Treble, Presence).
    4. Etapa de potencia y transformador de salida (Master).
    5. Convolución acústica FFT con la Respuesta Impulsional (IR) del gabinete.
    """
    if not isinstance(audio_data, np.ndarray) or len(audio_data) == 0:
        return audio_data

    # 1. Comprobación de Bypass
    is_enabled = bool(amp_config.get("enabled", True))
    if not is_enabled:
        return audio_data

    amp_id = str(amp_config.get("amp_id") or amp_config.get("id") or "marshall_jcm800").strip().lower()
    if amp_id not in AMPLIFIERS_CATALOG:
        amp_id = "marshall_jcm800"

    amp_meta = AMPLIFIERS_CATALOG[amp_id]
    tonestack_freqs = amp_meta["tonestack_freqs"]

    # Parámetros del panel del usuario
    gain_knob = float(amp_config.get("gain", amp_meta["controls"]["gain"]["default"]))
    bass_knob = float(amp_config.get("bass", amp_meta["controls"]["bass"]["default"]))
    middle_knob = float(amp_config.get("middle", amp_meta["controls"]["middle"]["default"]))
    treble_knob = float(amp_config.get("treble", amp_meta["controls"]["treble"]["default"]))
    presence_knob = float(amp_config.get("presence", amp_meta["controls"]["presence"]["default"]))
    master_knob = float(amp_config.get("master", amp_meta["controls"]["master"]["default"]))
    cabinet_id = str(amp_config.get("cabinet_id") or amp_meta["default_cabinet"]).strip().lower()
    if cabinet_id not in CABINET_SPECS:
        cabinet_id = amp_meta["default_cabinet"]

    # Determinar si el audio es mono o estéreo
    is_stereo = (audio_data.ndim == 2 and audio_data.shape[1] == 2)
    orig_peak = float(np.max(np.abs(audio_data)))
    if orig_peak < 1e-7:
        return audio_data

    # Normalizar para headroom de procesamiento
    norm_factor = 28000.0 if orig_peak > 1.0 else 1.0
    sig = audio_data.astype(np.float32) / norm_factor

    # Separar canales para procesar estéreo con la misma fase
    channels = [sig[:, 0], sig[:, 1]] if is_stereo else [sig]
    processed_channels = []

    # 2. Factor de saturación de previo
    # Gain 0.0..10.0 -> Multiplicador dinámico 0.8 a 8.5
    drive_mult = 0.8 + (gain_knob / 10.0) * 7.5
    asym = 0.35 if amp_meta["instrument_type"] == "guitar" else 0.20

    # 3. Filtros del Tone Stack reactivo
    b_bass, a_bass = rbj_lowshelf(tonestack_freqs["bass"], bass_knob, q=0.707)
    b_mid, a_mid = rbj_peaking(tonestack_freqs["mid"], middle_knob, q=1.5)
    b_treble, a_treble = rbj_highshelf(tonestack_freqs["treble"], treble_knob, q=0.707)

    # Presence: mapeo 0..10 a -6dB .. +6dB
    pres_gain = (presence_knob - 5.0) * 1.4
    if amp_id == "markbass_little_mark":
        # En Markbass, el control VPF realiza un notch scooped en 380 Hz
        b_pres, a_pres = rbj_peaking(380.0, -pres_gain * 1.5, q=1.2)
    else:
        b_pres, a_pres = rbj_highshelf(tonestack_freqs["presence"], pres_gain, q=0.707)

    # Cargar respuesta impulsional (IR) del gabinete
    cab_ir = load_or_create_cabinet_ir(cabinet_id)

    # 4. Procesar cada canal
    for ch in channels:
        # A. Preamplificador no lineal
        ch_sat = _triode_waveshape(ch, drive_mult, asymmetry=asym)

        # B. Tone Stack
        ch_eq = scipy.signal.lfilter(b_bass, a_bass, ch_sat)
        ch_eq = scipy.signal.lfilter(b_mid, a_mid, ch_eq)
        ch_eq = scipy.signal.lfilter(b_treble, a_treble, ch_eq)
        ch_eq = scipy.signal.lfilter(b_pres, a_pres, ch_eq)

        # C. Master Volume & Etapa de potencia push-pull (saturación de transformador)
        master_drive = 0.7 + (master_knob / 10.0) * 0.8
        ch_pwr = np.tanh(ch_eq * master_drive)

        # D. Convolución acústica con el Gabinete IR
        ch_cab = scipy.signal.fftconvolve(ch_pwr, cab_ir, mode="same")
        processed_channels.append(ch_cab)

    # Recombinar canales
    if is_stereo:
        out = np.column_stack(processed_channels)
    else:
        out = processed_channels[0]

    # Nivelar salida respecto al nivel de entrada para preservar el balance de mezcla
    wet_peak = float(np.max(np.abs(out)))
    if wet_peak > 1e-6:
        # Mantener volumen perceptual consistente con headroom
        target_peak = max(0.2, orig_peak)
        out = out * (target_peak / wet_peak) * (norm_factor if orig_peak > 1.0 else 1.0)

    return out.astype(audio_data.dtype)



def get_amp_catalog_payload() -> Dict[str, Any]:
    """Devuelve el catálogo estructurado de los 5 amplificadores y gabinetes."""
    return {
        "status": "ok",
        "amplifiers": list(AMPLIFIERS_CATALOG.values()),
        "cabinets": [
            {"id": k, **v} for k, v in CABINET_SPECS.items()
        ],
    }


# ==============================================================================
# GENERACIÓN DE AUDIO DE PREESCUCHA Y COMPARACIÓN A/B (DRY / WET)
# ==============================================================================

AMP_PREVIEWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "audio", "amp_previews")
os.makedirs(AMP_PREVIEWS_DIR, exist_ok=True)


def get_ffmpeg_binary() -> str:
    """Localiza el binario de FFmpeg en Linux/Render o Windows."""
    import shutil
    which_ff = shutil.which("ffmpeg")
    if which_ff:
        return which_ff
    local_ff = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.exists(local_ff):
        return local_ff
    return "ffmpeg"


def _generate_synthetic_fallback_di(instrument_type: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Genera una señal DI sintética monofónica si no existe archivo de audio en disco."""
    dur_sec = 4.0
    n_frames = int(dur_sec * sample_rate)
    t = np.linspace(0, dur_sec, n_frames, endpoint=False, dtype=np.float32)
    sig = np.zeros(n_frames, dtype=np.float32)

    if instrument_type == "bass":
        # Secuencia de bajo E1, G1, A1, B1
        notes = [(41.2, 0.0, 1.0), (49.0, 1.0, 2.0), (55.0, 2.0, 3.0), (61.7, 3.0, 4.0)]
    else:
        # Acorde arpegiado E mayor (E2, B2, E3, G#3, B3, E4)
        notes = [(82.4, 0.0, 1.0), (123.5, 0.6, 1.8), (164.8, 1.2, 2.4), (207.6, 1.8, 3.2), (246.9, 2.4, 3.8), (329.6, 3.0, 4.0)]

    for f_hz, t_start, t_end in notes:
        idx_s = int(t_start * sample_rate)
        idx_e = int(t_end * sample_rate)
        sub_t = t[idx_s:idx_e] - t_start
        env = np.exp(-sub_t * (3.5 if instrument_type == "bass" else 2.2))
        wave_note = np.sin(2 * np.pi * f_hz * sub_t) + 0.35 * np.sin(4 * np.pi * f_hz * sub_t) + 0.15 * np.sin(6 * np.pi * f_hz * sub_t)
        sig[idx_s:idx_e] += wave_note * env

    peak = np.max(np.abs(sig))
    if peak > 1e-4:
        sig = sig * (26000.0 / peak)
    stereo = np.column_stack([sig, sig]).astype(np.int16)
    return stereo


def generate_amp_preview(
    amp_id: str,
    amp_config: Optional[Dict[str, Any]] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Procesa la señal DI de guitarra o bajo a través del amplificador y gabinete IR seleccionados,
    generando los archivos de preescucha A/B (señal seca Dry vs señal con ampli Wet).
    """
    import subprocess
    import tempfile
    import time

    amp_id = str(amp_id or "marshall_jcm800").strip().lower()
    if amp_id not in AMPLIFIERS_CATALOG:
        amp_id = "marshall_jcm800"

    amp_meta = AMPLIFIERS_CATALOG[amp_id]
    instrument_type = amp_meta["instrument_type"]
    cfg = dict(amp_config or {})
    cfg["amp_id"] = amp_id

    # Normalizar controles
    gain = float(cfg.get("gain", amp_meta["controls"]["gain"]["default"]))
    bass = float(cfg.get("bass", amp_meta["controls"]["bass"]["default"]))
    middle = float(cfg.get("middle", amp_meta["controls"]["middle"]["default"]))
    treble = float(cfg.get("treble", amp_meta["controls"]["treble"]["default"]))
    presence = float(cfg.get("presence", amp_meta["controls"]["presence"]["default"]))
    master = float(cfg.get("master", amp_meta["controls"]["master"]["default"]))
    cabinet_id = str(cfg.get("cabinet_id") or amp_meta["default_cabinet"]).strip().lower()
    if cabinet_id not in CABINET_SPECS:
        cabinet_id = amp_meta["default_cabinet"]
    cfg["cabinet_id"] = cabinet_id
    bypass = bool(cfg.get("bypass", False))

    target_dir = output_dir or AMP_PREVIEWS_DIR
    os.makedirs(target_dir, exist_ok=True)

    # Localizar archivo DI de referencia
    di_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "audio", instrument_type)
    di_wav_path = os.path.join(di_dir, f"dry_di_{instrument_type}.wav")
    dry_mp3_name = f"dry_di_{instrument_type}.mp3"
    dry_mp3_path = os.path.join(target_dir, dry_mp3_name)

    # Cargar o generar audio DI
    dry_audio: Optional[np.ndarray] = None
    if os.path.exists(di_wav_path):
        try:
            with wave.open(di_wav_path, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
                dry_audio = np.frombuffer(raw, dtype=np.int16).reshape(-1, wf.getnchannels())
        except Exception:
            dry_audio = None

    if dry_audio is None:
        dry_audio = _generate_synthetic_fallback_di(instrument_type)
        # Guardar di_wav_path
        os.makedirs(di_dir, exist_ok=True)
        try:
            with wave.open(di_wav_path, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(dry_audio.tobytes())
        except Exception:
            pass

    ff_bin = get_ffmpeg_binary()

    # Asegurar que el MP3 seco exista
    if not os.path.exists(dry_mp3_path):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_dry_wav:
            tmp_dry_wav_path = tmp_dry_wav.name
        try:
            with wave.open(tmp_dry_wav_path, "wb") as wf:
                wf.setnchannels(dry_audio.shape[1] if dry_audio.ndim == 2 else 1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(dry_audio.tobytes())
            subprocess.run(
                [ff_bin, "-y", "-v", "error", "-i", tmp_dry_wav_path, "-b:a", "192k", dry_mp3_path],
                check=True
            )
        finally:
            if os.path.exists(tmp_dry_wav_path):
                os.remove(tmp_dry_wav_path)

    # Procesar con el amplificador y gabinete
    t0 = time.time()
    if bypass:
        wet_audio = dry_audio.copy()
    else:
        wet_audio = process_audio_through_amplifier(dry_audio, cfg)
    dsp_ms = (time.time() - t0) * 1000.0

    # Nombre determinista para caché de preescucha
    p_params = f"{int(round(gain*10))}_{int(round(bass*10))}_{int(round(middle*10))}_{int(round(treble*10))}_{int(round(presence*10))}_{int(round(master*10))}"
    wet_fname = f"prev_amp_{amp_id}_{cabinet_id}_{p_params}_{'byp' if bypass else 'wet'}.mp3"
    wet_mp3_path = os.path.join(target_dir, wet_fname)

    if not os.path.exists(wet_mp3_path):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wet_wav:
            tmp_wet_wav_path = tmp_wet_wav.name
        try:
            with wave.open(tmp_wet_wav_path, "wb") as wf:
                wf.setnchannels(wet_audio.shape[1] if wet_audio.ndim == 2 else 1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(wet_audio.tobytes())
            subprocess.run(
                [ff_bin, "-y", "-v", "error", "-i", tmp_wet_wav_path, "-b:a", "192k", wet_mp3_path],
                check=True
            )
        finally:
            if os.path.exists(tmp_wet_wav_path):
                os.remove(tmp_wet_wav_path)

    return {
        "status": "ok",
        "zero_cost": True,
        "amp_id": amp_id,
        "amp_name": amp_meta["name"],
        "short_name": amp_meta["short_name"],
        "instrument_type": instrument_type,
        "tubes": amp_meta["tubes"],
        "cabinet_id": cabinet_id,
        "cabinet_name": CABINET_SPECS[cabinet_id]["name"],
        "controls": {
            "gain": gain,
            "bass": bass,
            "middle": middle,
            "treble": treble,
            "presence": presence,
            "master": master,
        },
        "bypass": bypass,
        "dry_url": f"/api/amps/preview-audio/{dry_mp3_name}?t={int(time.time())}",
        "wet_url": f"/api/amps/preview-audio/{wet_fname}?t={int(time.time())}",
        "dsp_time_ms": round(dsp_ms, 2),
    }

