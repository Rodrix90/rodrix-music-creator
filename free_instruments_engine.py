"""
RODRIX MUSIC CREATOR v3.0 — MOTOR DE 20 INSTRUMENTOS GRATUITOS (MIDI + FluidSynth)
===================================================================================
- Sintetiza música real mediante secuencias MIDI algorítmicas y FluidSynth 2.6+.
- Cero costo de API (0 llamadas a Udio, 0 llamadas a FAL).
- Renderizado secuencial pista por pista (nunca carga todos los bancos SF2 a la vez),
  manteniendo el uso de RAM muy por debajo del límite de 512 MB de Render.
- Incluye aprovisionamiento automático de bancos SF2 libres (CC0, CC-BY 3.0/4.0,
  GeneralUser GS v2.0) resistente a reinicios de contenedor.
"""

import concurrent.futures
import json
import math
import os
import re
import shutil
import ssl
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import wave
from typing import Any, Dict, List, Optional, Tuple

import mido
import numpy as np
import scipy.signal

try:
    import psutil
except ImportError:
    psutil = None

try:
    import py7zr
except ImportError:
    py7zr = None

SAMPLE_RATE = 44100

# Directorios candidatos para bancos SF2 (prioriza laboratorio local en Windows si existe)
LOCAL_LAB_POC_DIR = r"C:\Users\Rodrigo\.gemini\antigravity\brain\05f503cb-0a54-41ce-8f18-367e619ee2ee\scratch\piano_poc"
DEFAULT_CACHE_DIR = os.environ.get(
    "RODRIX_SF2_DIR",
    LOCAL_LAB_POC_DIR if os.path.isdir(LOCAL_LAB_POC_DIR) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "soundfonts_cache"),
)


def get_fluidsynth_binary() -> str:
    """Localiza el ejecutable de FluidSynth en Linux/Render o Windows local."""
    env_bin = os.environ.get("FLUIDSYNTH_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin

    which_bin = shutil.which("fluidsynth")
    if which_bin:
        return which_bin

    win_lab_bin = os.path.join(
        LOCAL_LAB_POC_DIR,
        "fluidsynth",
        "fluidsynth-v2.6.1-win10-x64-cpp11",
        "bin",
        "fluidsynth.exe",
    )
    if os.path.exists(win_lab_bin):
        return win_lab_bin

    local_tools_bin = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "tools",
        "fluidsynth",
        "bin",
        "fluidsynth.exe",
    )
    if os.path.exists(local_tools_bin):
        return local_tools_bin

    return "fluidsynth"


def get_ffmpeg_binary() -> str:
    """Localiza el ejecutable de FFmpeg en Linux/Render o Windows local."""
    which_ff = shutil.which("ffmpeg")
    if which_ff:
        return which_ff
    local_ff = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
    if os.path.exists(local_ff):
        return local_ff
    return "ffmpeg"


# ==============================================================================
# DEFINICIÓN DE BANCOS SF2 Y APROVISIONAMIENTO AUTOMÁTICO
# ==============================================================================

SF2_BANKS_METADATA: Dict[str, Dict[str, Any]] = {
    "salamander": {
        "filename": "Salamander-C5-Compact.sf2",
        "substr": "Salamander-C5-Compact",
        "type": "builder_salamander",
        "license": "CC-BY 3.0",
        "attribution": "Alexander Holm (Salamander Grand Piano V3 - Yamaha C5)",
        "source_url": "https://github.com/sfzinstruments/SalamanderGrandPiano",
    },
    "cp80": {
        "filename": "GregSullivan-CP80.sf2",
        "substr": "GregSullivan-CP80",
        "type": "builder_cp80",
        "license": "CC-BY 3.0",
        "attribution": "Greg Sullivan (Yamaha CP80 Electric Grand Piano v1.3)",
        "source_url": "https://github.com/sfzinstruments/GregSullivan.E-Pianos",
    },
    "generaluser": {
        "filename": "GeneralUser-GS.sf2",
        "substr": "GeneralUser-GS",
        "type": "direct",
        "url": "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS v2.0)",
        "source_url": "https://github.com/mrbumpy409/GeneralUser-GS",
    },
    "fm_piano1": {
        "filename": "FM-Piano1 20190916.sf2",
        "substr": "FM-Piano1",
        "type": "7z",
        "archive_name": "FM-Piano1-SF2.7z",
        "url": "https://github.com/freepats/fm-piano1/releases/download/2019-09-16/FM-Piano1-SF2-20190916.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (FM Piano 1 / Yamaha DX7)",
        "source_url": "https://freepats.zenvoid.org/ElectricPiano/synthesized-piano.html",
    },
    "fm_piano2": {
        "filename": "FM-Piano2 20161112.sf2",
        "substr": "FM-Piano2",
        "type": "7z",
        "archive_name": "FM-Piano2-SF2.7z",
        "url": "https://github.com/freepats/fm-piano2/releases/download/2016-11-12/FM-Piano2-SF2-20161112.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (FM Piano 2 / Crystal DX)",
        "source_url": "https://freepats.zenvoid.org/ElectricPiano/synthesized-piano.html",
    },
    "finger_bass": {
        "filename": "FingerBassYR 20190930.sf2",
        "substr": "FingerBassYR",
        "type": "7z",
        "archive_name": "FingerBassYR-SF2.7z",
        "url": "https://github.com/freepats/electric-bass-YR/releases/download/2019-09-30/FingerBassYR-SF2-20190930.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Yamaha RBX Fingered Electric Bass)",
        "source_url": "https://freepats.zenvoid.org/Bass/electric-bass.html",
    },
    "clean_guitar": {
        "filename": "EGuitarFSBS-clean bridge small 20260807.sf2",
        "substr": "EGuitarFSBS-clean",
        "type": "7z",
        "archive_name": "EGuitarFSBS-clean-small-SF2.7z",
        "url": "https://github.com/freepats/electric-guitar-FSBS-clean/releases/download/2026-08-07/EGuitarFSBS-clean-bridge-small-SF2-20260807.7z",
        "license": "CC-BY 4.0",
        "attribution": "FreePats Project (FSBS Clean Stratocaster Bridge Guitar)",
        "source_url": "https://freepats.zenvoid.org/Guitar/clean-electric-guitar.html",
    },
    "spanish_guitar": {
        "filename": "SpanishClassicalGuitar-20190618.sf2",
        "substr": "SpanishClassicalGuitar",
        "type": "7z",
        "archive_name": "SpanishClassicalGuitar-SF2.7z",
        "url": "https://freepats.zenvoid.org/Guitar/SpanishClassicalGuitar/SpanishClassicalGuitar-SF2-20190618.7z",
        "license": "GPLv3+ con excepción MIDI / CC0",
        "attribution": "FreePats Project (Spanish Classical / Acoustic Guitar)",
        "source_url": "https://freepats.zenvoid.org/Guitar/acoustic-guitar.html",
    },
    "world_percussion": {
        "filename": "WorldPercussion 20200905.sf2",
        "substr": "WorldPercussion",
        "type": "7z",
        "archive_name": "WorldPercussion-SF2.7z",
        "url": "https://github.com/freepats/world-percussion/releases/download/2020-09-05/WorldPercussion-SF2-20200905.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project / Xavimart & Versilian Studios (Cajón Flamenco, Bongós, Congas, Maracas)",
        "source_url": "https://freepats.zenvoid.org/Percussion/world-and-rare-percussion.html",
    },
    "lately_bass": {
        "filename": "LatelyBass 20240409.sf2",
        "substr": "LatelyBass",
        "type": "7z",
        "archive_name": "LatelyBass-SF2.7z",
        "url": "https://github.com/freepats/lately-bass/releases/download/2024-04-09/LatelyBass-SF2-20240409.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Yamaha TX81Z Lately Synth Bass)",
        "source_url": "https://freepats.zenvoid.org/Synthesizer/synth-bass.html",
    },
    "synth_fifths": {
        "filename": "SynthFifths 20200519.sf2",
        "substr": "SynthFifths",
        "type": "7z",
        "archive_name": "SynthFifths-SF2.7z",
        "url": "https://github.com/freepats/synth-fifths/releases/download/2020-05-19/SynthFifths-SF2-20200519.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Synth Fifths Lead)",
        "source_url": "https://freepats.zenvoid.org/Synthesizer/synth-lead.html",
    },
    "sweep_pad": {
        "filename": "SweepPad 20190813.sf2",
        "substr": "SweepPad",
        "type": "7z",
        "archive_name": "SweepPad-SF2.7z",
        "url": "https://github.com/freepats/sweep-pad/releases/download/2019-08-13/SweepPad-SF2-20190813.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Atmospheric Sweep Pad)",
        "source_url": "https://freepats.zenvoid.org/Synthesizer/synth-pad.html",
    },
    "tubular_bells": {
        "filename": "TubularBells small 20241130.sf2",
        "substr": "TubularBells",
        "type": "7z",
        "archive_name": "TubularBells-small-SF2.7z",
        "url": "https://github.com/freepats/tubular-bells1/releases/download/2024-11-30/TubularBells-small-SF2-20241130.7z",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Cathedral Tubular Bells)",
        "source_url": "https://freepats.zenvoid.org/ChromaticPercussion/tubular-bells.html",
    },
}


def _riff_chunk(fourcc: bytes, data: bytes) -> bytes:
    if len(data) % 2 == 1:
        data = data + b"\x00"
    return fourcc + struct.pack("<I", len(data)) + data


def _list_chunk(list_type: bytes, body: bytes) -> bytes:
    return _riff_chunk(b"LIST", list_type + body)


def _build_salamander_compact_sf2(out_sf2_path: str, work_dir: str) -> str:
    """Construye Salamander-C5-Compact.sf2 (~44.9 MB) desde muestras FLAC oficiales CC-BY 3.0."""
    sal_dir = os.path.join(work_dir, "salamander_samples")
    os.makedirs(sal_dir, exist_ok=True)
    ctx = ssl._create_unverified_context()

    regions = [
        ("A1", 21, 34, 33), ("C2", 35, 37, 36), ("D#2", 38, 40, 39),
        ("F#2", 41, 43, 42), ("A2", 44, 46, 45), ("C3", 47, 49, 48),
        ("D#3", 50, 52, 51), ("F#3", 53, 55, 54), ("A3", 56, 58, 57),
        ("C4", 59, 61, 60), ("D#4", 62, 64, 63), ("F#4", 65, 67, 66),
        ("A4", 68, 70, 69), ("C5", 71, 73, 72), ("D#5", 74, 76, 75),
        ("F#5", 77, 79, 78), ("A5", 80, 82, 81), ("C6", 83, 108, 84),
    ]
    vel_layers = [("v6", 1, 74), ("v10", 75, 127)]

    needed_files = [f"{note}{vel}.flac" for vel, _, _ in vel_layers for note, _, _, _ in regions]

    def _dl(fn: str):
        dst = os.path.join(sal_dir, fn)
        if not (os.path.exists(dst) and os.path.getsize(dst) > 500):
            url = "https://raw.githubusercontent.com/sfzinstruments/SalamanderGrandPiano/master/Samples/" + urllib.parse.quote(fn)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp, open(dst, "wb") as f:
                f.write(resp.read())

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_dl, needed_files))

    ff_bin = get_ffmpeg_binary()
    smpl_chunks = []
    shdr_records = []
    ibag_records = []
    igen_records = []
    current_sample_offset = 0
    padding_zeros = np.zeros(46, dtype=np.int16).tobytes()

    for vel_tag, lovel, hivel in vel_layers:
        for note_name, lokey, hikey, root_key in regions:
            flac_file = os.path.join(sal_dir, f"{note_name}{vel_tag}.flac")
            cmd = [
                ff_bin, "-v", "error", "-i", flac_file,
                "-ac", "2", "-ar", str(SAMPLE_RATE), "-t", "7.5",
                "-f", "s16le", "pipe:1"
            ]
            raw = subprocess.check_output(cmd)
            stereo = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).copy()
            fade_len = min(int(0.4 * SAMPLE_RATE), len(stereo) // 4)
            if fade_len > 0:
                fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
                stereo[-fade_len:, 0] = (stereo[-fade_len:, 0].astype(np.float32) * fade).astype(np.int16)
                stereo[-fade_len:, 1] = (stereo[-fade_len:, 1].astype(np.float32) * fade).astype(np.int16)

            energy = np.max(np.abs(stereo), axis=1)
            nonzero = np.where(energy > 45)[0]
            start_trim = max(0, int(nonzero[0]) - 8) if len(nonzero) > 0 else 0
            stereo = stereo[start_trim:]

            n_frames = len(stereo)
            idx_left = len(shdr_records)
            idx_right = idx_left + 1

            start_l = current_sample_offset
            end_l = start_l + n_frames
            smpl_chunks.append(stereo[:, 0].tobytes())
            smpl_chunks.append(padding_zeros)
            current_sample_offset = end_l + 46

            start_r = current_sample_offset
            end_r = start_r + n_frames
            smpl_chunks.append(stereo[:, 1].tobytes())
            smpl_chunks.append(padding_zeros)
            current_sample_offset = end_r + 46

            name_l = f"{note_name}_{vel_tag}_L"[:19].encode("ascii")
            name_r = f"{note_name}_{vel_tag}_R"[:19].encode("ascii")
            shdr_records.append(struct.pack("<20sIIIIIBbHH", name_l.ljust(20, b"\x00"), start_l, end_l, end_l - 32, end_l - 4, SAMPLE_RATE, root_key, 0, idx_right, 4))
            shdr_records.append(struct.pack("<20sIIIIIBbHH", name_r.ljust(20, b"\x00"), start_r, end_r, end_r - 32, end_r - 4, SAMPLE_RATE, root_key, 0, idx_left, 2))

            rel_tc = int(1200 * math.log2(1.35)) & 0xFFFF
            for samp_idx, pan_val in [(idx_left, -500), (idx_right, 500)]:
                ibag_records.append(struct.pack("<HH", len(igen_records), 0))
                igen_records.append(struct.pack("<HH", 43, (lokey & 0xFF) | ((hikey & 0xFF) << 8)))
                igen_records.append(struct.pack("<HH", 44, (lovel & 0xFF) | ((hivel & 0xFF) << 8)))
                igen_records.append(struct.pack("<HH", 38, rel_tc))
                igen_records.append(struct.pack("<Hh", 17, pan_val))
                igen_records.append(struct.pack("<HH", 58, root_key))
                igen_records.append(struct.pack("<HH", 53, samp_idx))

    phdr_data = (
        struct.pack("<20sHHHIII", b"Salamander C5 Grand\x00", 0, 0, 0, 0, 0, 0) +
        struct.pack("<20sHHHIII", b"EOP".ljust(20, b"\x00"), 0, 0, 1, 0, 0, 0)
    )
    pbag_data = struct.pack("<HH", 0, 0) + struct.pack("<HH", 1, 0)
    pmod_data = struct.pack("<HHhHH", 0, 0, 0, 0, 0)
    pgen_data = struct.pack("<HH", 41, 0) + struct.pack("<HH", 0, 0)
    inst_data = (
        struct.pack("<20sH", b"Salamander C5".ljust(20, b"\x00"), 0) +
        struct.pack("<20sH", b"EOI".ljust(20, b"\x00"), len(ibag_records))
    )
    ibag_records.append(struct.pack("<HH", len(igen_records), 0))
    imod_data = struct.pack("<HHhHH", 0, 0, 0, 0, 0)
    igen_records.append(struct.pack("<HH", 0, 0))
    shdr_records.append(struct.pack("<20sIIIIIBbHH", b"EOS".ljust(20, b"\x00"), 0, 0, 0, 0, 0, 0, 0, 0, 0))

    info_body = (
        _riff_chunk(b"ifil", struct.pack("<HH", 2, 1)) +
        _riff_chunk(b"isng", b"EMU8000\x00") +
        _riff_chunk(b"INAM", b"Salamander Grand Piano C5 Compact (CC-BY 3.0 Alexander Holm)\x00")
    )
    sdta_body = _riff_chunk(b"smpl", b"".join(smpl_chunks))
    pdta_body = (
        _riff_chunk(b"phdr", phdr_data) +
        _riff_chunk(b"pbag", pbag_data) +
        _riff_chunk(b"pmod", pmod_data) +
        _riff_chunk(b"pgen", pgen_data) +
        _riff_chunk(b"inst", inst_data) +
        _riff_chunk(b"ibag", b"".join(ibag_records)) +
        _riff_chunk(b"imod", imod_data) +
        _riff_chunk(b"igen", b"".join(igen_records)) +
        _riff_chunk(b"shdr", b"".join(shdr_records))
    )
    riff_file = _riff_chunk(b"RIFF", b"sfbk" + _list_chunk(b"INFO", info_body) + _list_chunk(b"sdta", sdta_body) + _list_chunk(b"pdta", pdta_body))
    with open(out_sf2_path, "wb") as f:
        f.write(riff_file)
    shutil.rmtree(sal_dir, ignore_errors=True)
    return out_sf2_path


def _build_cp80_compact_sf2(out_sf2_path: str, work_dir: str) -> str:
    """Construye GregSullivan-CP80.sf2 (~54 MB) desde muestras FLAC oficiales CC-BY 3.0."""
    cp80_dir = os.path.join(work_dir, "cp80_samples")
    os.makedirs(cp80_dir, exist_ok=True)
    ctx = ssl._create_unverified_context()

    sfz_url = "https://raw.githubusercontent.com/sfzinstruments/GregSullivan.E-Pianos/master/CP80/CP80.sfz"
    req = urllib.request.Request(sfz_url, headers={"User-Agent": "Mozilla/5.0"})
    sfz_text = urllib.request.urlopen(req, timeout=20, context=ctx).read().decode("utf-8")

    groups = []
    current_vel = None
    for line in sfz_text.splitlines():
        line = line.strip()
        if line.startswith("group_label=MP"):
            current_vel = (1, 84)
        elif line.startswith("group_label=F"):
            current_vel = (85, 127)
        elif line.startswith("group_label="):
            current_vel = None
        elif current_vel and line.startswith("<region>"):
            m = re.search(r"lokey=(\d+)\s+hikey=(\d+)\s+pitch_keycenter=(\d+).*?sample=([^\s\.]+\.)", line)
            if m:
                lokey, hikey, root, samp_prefix = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                groups.append((current_vel[0], current_vel[1], lokey, hikey, root, samp_prefix + "flac"))

    unique_files = sorted(set(g[5] for g in groups))

    def _dl(fn: str):
        out = os.path.join(cp80_dir, fn)
        if not (os.path.exists(out) and os.path.getsize(out) > 500):
            url = "https://raw.githubusercontent.com/sfzinstruments/GregSullivan.E-Pianos/master/CP80/Samples/" + urllib.parse.quote(fn)
            r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(r, timeout=30, context=ctx) as resp, open(out, "wb") as f:
                f.write(resp.read())

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_dl, unique_files))

    ff_bin = get_ffmpeg_binary()
    smpl_chunks = []
    shdr_records = []
    ibag_records = []
    igen_records = []
    current_sample_offset = 0
    padding_zeros = np.zeros(46, dtype=np.int16).tobytes()

    for lovel, hivel, lokey, hikey, root_key, fn in groups:
        flac_file = os.path.join(cp80_dir, fn)
        cmd = [
            ff_bin, "-v", "error", "-i", flac_file,
            "-ac", "2", "-ar", str(SAMPLE_RATE), "-t", "6.0",
            "-f", "s16le", "pipe:1"
        ]
        raw = subprocess.check_output(cmd)
        stereo = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).copy()
        fade_len = min(int(0.3 * SAMPLE_RATE), len(stereo) // 4)
        if fade_len > 0:
            fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            stereo[-fade_len:, 0] = (stereo[-fade_len:, 0].astype(np.float32) * fade).astype(np.int16)
            stereo[-fade_len:, 1] = (stereo[-fade_len:, 1].astype(np.float32) * fade).astype(np.int16)

        n_frames = len(stereo)
        idx_left = len(shdr_records)
        idx_right = idx_left + 1

        start_l = current_sample_offset
        end_l = start_l + n_frames
        smpl_chunks.append(stereo[:, 0].tobytes())
        smpl_chunks.append(padding_zeros)
        current_sample_offset = end_l + 46

        start_r = current_sample_offset
        end_r = start_r + n_frames
        smpl_chunks.append(stereo[:, 1].tobytes())
        smpl_chunks.append(padding_zeros)
        current_sample_offset = end_r + 46

        base_id = fn.replace(".flac", "")[:17]
        name_l = f"{base_id}_L".encode("ascii")
        name_r = f"{base_id}_R".encode("ascii")

        shdr_records.append(struct.pack("<20sIIIIIBbHH", name_l.ljust(20, b"\x00"), start_l, end_l, end_l - 32, end_l - 4, SAMPLE_RATE, root_key, 0, idx_right, 4))
        shdr_records.append(struct.pack("<20sIIIIIBbHH", name_r.ljust(20, b"\x00"), start_r, end_r, end_r - 32, end_r - 4, SAMPLE_RATE, root_key, 0, idx_left, 2))

        rel_tc = int(1200 * math.log2(1.2)) & 0xFFFF
        for samp_idx, pan_val in [(idx_left, -500), (idx_right, 500)]:
            ibag_records.append(struct.pack("<HH", len(igen_records), 0))
            igen_records.append(struct.pack("<HH", 43, (lokey & 0xFF) | ((hikey & 0xFF) << 8)))
            igen_records.append(struct.pack("<HH", 44, (lovel & 0xFF) | ((hivel & 0xFF) << 8)))
            igen_records.append(struct.pack("<HH", 38, rel_tc))
            igen_records.append(struct.pack("<Hh", 17, pan_val))
            igen_records.append(struct.pack("<HH", 58, root_key))
            igen_records.append(struct.pack("<HH", 53, samp_idx))

    phdr_data = (
        struct.pack("<20sHHHIII", b"GregSullivan CP80\x00\x00\x00", 0, 0, 0, 0, 0, 0) +
        struct.pack("<20sHHHIII", b"EOP".ljust(20, b"\x00"), 0, 0, 1, 0, 0, 0)
    )
    pbag_data = struct.pack("<HH", 0, 0) + struct.pack("<HH", 1, 0)
    pmod_data = struct.pack("<HHhHH", 0, 0, 0, 0, 0)
    pgen_data = struct.pack("<HH", 41, 0) + struct.pack("<HH", 0, 0)
    inst_data = (
        struct.pack("<20sH", b"CP80 ElectricGrand".ljust(20, b"\x00"), 0) +
        struct.pack("<20sH", b"EOI".ljust(20, b"\x00"), len(ibag_records))
    )
    ibag_records.append(struct.pack("<HH", len(igen_records), 0))
    imod_data = struct.pack("<HHhHH", 0, 0, 0, 0, 0)
    igen_records.append(struct.pack("<HH", 0, 0))
    shdr_records.append(struct.pack("<20sIIIIIBbHH", b"EOS".ljust(20, b"\x00"), 0, 0, 0, 0, 0, 0, 0, 0, 0))

    info_body = (
        _riff_chunk(b"ifil", struct.pack("<HH", 2, 1)) +
        _riff_chunk(b"isng", b"EMU8000\x00") +
        _riff_chunk(b"INAM", b"Greg Sullivan Yamaha CP80 Electric Grand (CC-BY 3.0)\x00\x00")
    )
    sdta_body = _riff_chunk(b"smpl", b"".join(smpl_chunks))
    pdta_body = (
        _riff_chunk(b"phdr", phdr_data) +
        _riff_chunk(b"pbag", pbag_data) +
        _riff_chunk(b"pmod", pmod_data) +
        _riff_chunk(b"pgen", pgen_data) +
        _riff_chunk(b"inst", inst_data) +
        _riff_chunk(b"ibag", b"".join(ibag_records)) +
        _riff_chunk(b"imod", imod_data) +
        _riff_chunk(b"igen", b"".join(igen_records)) +
        _riff_chunk(b"shdr", b"".join(shdr_records))
    )
    riff_file = _riff_chunk(b"RIFF", b"sfbk" + _list_chunk(b"INFO", info_body) + _list_chunk(b"sdta", sdta_body) + _list_chunk(b"pdta", pdta_body))
    with open(out_sf2_path, "wb") as f:
        f.write(riff_file)
    shutil.rmtree(cp80_dir, ignore_errors=True)
    return out_sf2_path


def resolve_sf2_path(bank_key: str, cache_dir: Optional[str] = None) -> str:
    """
    Localiza un banco SF2 en disco o lo aprovisiona automáticamente si falta
    (por ejemplo tras un reinicio de contenedor en Render).
    """
    base_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(base_dir, exist_ok=True)
    meta = SF2_BANKS_METADATA[bank_key]
    direct_candidate = os.path.join(base_dir, meta["filename"])
    if os.path.exists(direct_candidate) and os.path.getsize(direct_candidate) > 10000:
        return direct_candidate

    # Buscar recursivamente en base_dir y LOCAL_LAB_POC_DIR
    search_roots = [base_dir]
    if os.path.isdir(LOCAL_LAB_POC_DIR) and LOCAL_LAB_POC_DIR not in search_roots:
        search_roots.append(LOCAL_LAB_POC_DIR)

    substr_low = meta["substr"].lower()
    for root_dir in search_roots:
        for r, _, files in os.walk(root_dir):
            for f in files:
                if f.lower().endswith(".sf2") and substr_low in f.lower():
                    found = os.path.join(r, f)
                    if os.path.getsize(found) > 10000:
                        return found

    # Aprovisionar bajo demanda en base_dir
    ctx = ssl._create_unverified_context()
    btype = meta["type"]
    if btype == "direct":
        req = urllib.request.Request(meta["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(direct_candidate, "wb") as f:
            f.write(resp.read())
        return direct_candidate

    if btype == "7z":
        archive_path = os.path.join(base_dir, meta["archive_name"])
        if not (os.path.exists(archive_path) and os.path.getsize(archive_path) > 1000):
            req = urllib.request.Request(meta["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(archive_path, "wb") as f:
                f.write(resp.read())
        ext_sub = os.path.join(base_dir, "extracted_banks", meta["archive_name"][:-3])
        os.makedirs(ext_sub, exist_ok=True)
        if py7zr is not None:
            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                z.extractall(path=ext_sub)
        else:
            subprocess.run(["7z", "x", "-y", archive_path, f"-o{ext_sub}"], check=True)
        try:
            os.remove(archive_path)
        except OSError:
            pass
        for r, _, files in os.walk(ext_sub):
            for f in files:
                if f.lower().endswith(".sf2") and substr_low in f.lower():
                    return os.path.join(r, f)
        raise FileNotFoundError(f"SF2 {meta['filename']} no encontrado tras extraer {meta['archive_name']}")

    if btype == "builder_salamander":
        return _build_salamander_compact_sf2(direct_candidate, base_dir)

    if btype == "builder_cp80":
        return _build_cp80_compact_sf2(direct_candidate, base_dir)

    raise ValueError(f"Tipo de aprovisionamiento desconocido: {btype}")


def ensure_all_soundfonts(cache_dir: Optional[str] = None) -> Dict[str, str]:
    """Verifica o aprovisiona los 13 bancos SF2 necesarios para los 20 instrumentos."""
    resolved = {}
    for bkey in SF2_BANKS_METADATA:
        resolved[bkey] = resolve_sf2_path(bkey, cache_dir=cache_dir)
    return resolved


# ==============================================================================
# CATÁLOGO DE LOS 20 INSTRUMENTOS GRATUITOS (21 VARIANTES SELECCIONABLES)
# ==============================================================================

FREE_INSTRUMENTS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "piano_cola",
        "num": "1",
        "name": "1. Piano de Cola Acústico",
        "short_name": "Piano de Cola",
        "family": "Teclados & Pianos",
        "role": "piano",
        "layers": [("salamander", 0, 0, 0.90)],
        "chorus": False,
        "default_volume": 1.0,
        "bank_name": "Salamander-C5-Compact.sf2 (Yamaha C5 Grand)",
        "license": "CC-BY 3.0",
        "attribution": "Alexander Holm (Salamander Grand Piano V3)",
        "authenticity": "Auténtico (Muestras reales Yamaha C5 con pedal de sustain)",
    },
    {
        "id": "bajo_finger",
        "num": "2A",
        "name": "2. Bajo Eléctrico (Fingerstyle + Pick-up)",
        "short_name": "Bajo Eléctrico (Finger)",
        "family": "Bajos",
        "role": "bass_finger",
        "layers": [("finger_bass", 0, 0, 0.95)],
        "chorus": False,
        "default_volume": 1.0,
        "bank_name": "FingerBassYR 20190930.sf2 (FreePats Yamaha RBX)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Grabación real Yamaha RBX pulsado con dedos)",
    },
    {
        "id": "bajo_slap",
        "num": "2B",
        "name": "2B. Bajo Eléctrico (Slap & Pop + Pick-up)",
        "short_name": "Bajo Eléctrico (Slap & Pop)",
        "family": "Bajos",
        "role": "bass_slap",
        "layers": [("generaluser", 0, 36, 0.95)],
        "chorus": False,
        "default_volume": 1.0,
        "bank_name": "GeneralUser-GS.sf2 (Prog 36 Slap Bass 1 + Prog 37 Slap Bass 2)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras reales GM (Slap de pulgar + Pop de octava)",
    },
    {
        "id": "bateria_acustica",
        "num": "3",
        "name": "3. Batería Acústica (Hi-Hat, Toms y Crashes)",
        "short_name": "Batería Acústica",
        "family": "Baterías & Percusión",
        "role": "acoustic_drums",
        "layers": [("generaluser", 128, 0, 0.95)],
        "chorus": False,
        "default_volume": 1.0,
        "bank_name": "GeneralUser-GS.sf2 (Bank 128 Prog 0 Standard Kit Multi-Vel)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras acústicas reales con 3 capas de velocidad en caja y 5 toms",
    },
    {
        "id": "organo",
        "num": "4",
        "name": "4. Órgano (Tonewheel Hammond B3)",
        "short_name": "Órgano B3",
        "family": "Teclados & Pianos",
        "role": "organ",
        "layers": [("generaluser", 0, 16, 0.85)],
        "chorus": True,
        "default_volume": 0.85,
        "bank_name": "GeneralUser-GS.sf2 (Bank 0 Prog 16 Tonewheel Organ)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras reales de órgano Tonewheel con chorus rotatorio estéreo",
    },
    {
        "id": "piano_fm_dx",
        "num": "5",
        "name": "5. Piano FM DX (Yamaha DX7 E.Piano 1)",
        "short_name": "Piano FM DX",
        "family": "Teclados & Pianos",
        "role": "epiano_fm",
        "layers": [("fm_piano1", 0, 0, 0.90)],
        "chorus": True,
        "default_volume": 0.90,
        "bank_name": "FM-Piano1 20190916.sf2 (FreePats Yamaha DX7 FM)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Síntesis FM DX7 real multi-velocidad v60/v80/v100)",
    },
    {
        "id": "piano_sintetizado",
        "num": "6",
        "name": "6. Piano Sintetizado (CP80 Electric Grand + FM + Chorus)",
        "short_name": "Piano Sintetizado",
        "family": "Teclados & Pianos",
        "role": "synth_piano",
        "layers": [("cp80", 0, 0, 0.70), ("fm_piano2", 0, 0, 0.45)],
        "chorus": True,
        "default_volume": 0.90,
        "bank_name": "GregSullivan-CP80.sf2 + FM-Piano2 20161112.sf2",
        "license": "CC-BY 3.0 + CC0 1.0",
        "attribution": "Greg Sullivan (Yamaha CP80) & FreePats Project",
        "authenticity": "Auténtico (Yamaha CP80 real + capa FM con Chorus Estéreo tipo MKS-20)",
    },
    {
        "id": "guitarra_acustica",
        "num": "7",
        "name": "7. Guitarra Acústica (Clásica / Acústica Real)",
        "short_name": "Guitarra Acústica",
        "family": "Guitarras",
        "role": "acoustic_guitar",
        "layers": [("spanish_guitar", 0, 0, 0.90)],
        "chorus": False,
        "default_volume": 0.95,
        "bank_name": "SpanishClassicalGuitar-20190618.sf2 (FreePats)",
        "license": "GPLv3+ con excepción MIDI / CC0",
        "attribution": "FreePats Project",
        "authenticity": "Auténtico (Muestras reales nota por cuerda de guitarra acústica)",
    },
    {
        "id": "guitarra_distorsionada",
        "num": "8",
        "name": "8. Guitarra Distorsionada (Overdrive Power Chords + Lead)",
        "short_name": "Guitarra Distorsionada",
        "family": "Guitarras",
        "role": "distorted_guitar",
        "layers": [("generaluser", 0, 29, 0.85)],
        "chorus": False,
        "default_volume": 0.90,
        "bank_name": "GeneralUser-GS.sf2 (Prog 29 Overdrive + Prog 30 Distortion Guitar)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras reales con distorsión (Power chords rítmicos + melodía lead)",
    },
    {
        "id": "guitarra_limpia",
        "num": "9",
        "name": "9. Guitarra Eléctrica Limpia (Stratocaster Clean Bridge)",
        "short_name": "Guitarra Limpia",
        "family": "Guitarras",
        "role": "clean_guitar",
        "layers": [("clean_guitar", 0, 0, 0.90)],
        "chorus": True,
        "default_volume": 0.90,
        "bank_name": "EGuitarFSBS-clean bridge small 20260807.sf2 (FreePats)",
        "license": "CC-BY 4.0",
        "attribution": "FreePats Project (FSBS Clean Electric Guitar)",
        "authenticity": "Auténtico (Grabación real de guitarra eléctrica limpia nota por nota)",
    },
    {
        "id": "bateria_electronica",
        "num": "10",
        "name": "10. Batería Electrónica (Roland TR-808 / 909 Kit)",
        "short_name": "Batería Electrónica",
        "family": "Baterías & Percusión",
        "role": "electronic_drums",
        "layers": [("generaluser", 128, 25, 0.95)],
        "chorus": False,
        "default_volume": 0.95,
        "bank_name": "GeneralUser-GS.sf2 (Bank 128 Prog 25 TR-808/909)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Auténtico (Muestras reales de Roland TR-808 y TR-909)",
    },
    {
        "id": "bongos",
        "num": "11",
        "name": "11. Bongós (Martillo & Repique - 31 Muestras Round-Robin)",
        "short_name": "Bongós",
        "family": "Baterías & Percusión",
        "role": "bongos",
        "layers": [("world_percussion", 0, 0, 0.95)],
        "chorus": False,
        "default_volume": 0.85,
        "bank_name": "WorldPercussion 20200905.sf2 (FreePats - Keys 51, 52, 53)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project / Xavimart (Dominio Público)",
        "authenticity": "Auténtico 100% (31 muestras reales grabadas con micrófonos estéreo)",
    },
    {
        "id": "congas",
        "num": "12",
        "name": "12. Congas (Tumbao Marcha - 5 Articulaciones Reales)",
        "short_name": "Congas",
        "family": "Baterías & Percusión",
        "role": "congas",
        "layers": [("world_percussion", 0, 0, 0.95)],
        "chorus": False,
        "default_volume": 0.85,
        "bank_name": "WorldPercussion 20200905.sf2 (FreePats / Versilian CC0 - Keys 62..66)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project & Versilian Studios (CC0)",
        "authenticity": "Auténtico 100% (Abierta, Grave, Slap, Palma Muteada y Grave Muteada)",
    },
    {
        "id": "cajon",
        "num": "13",
        "name": "13. Cajón Peruano / Flamenco (29 Muestras Round-Robin)",
        "short_name": "Cajón",
        "family": "Baterías & Percusión",
        "role": "cajon",
        "layers": [("world_percussion", 0, 0, 0.95)],
        "chorus": False,
        "default_volume": 0.95,
        "bank_name": "WorldPercussion 20200905.sf2 (FreePats Cajón - Keys 48, 49, 50)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project / Xavimart (Dominio Público)",
        "authenticity": "Auténtico 100% (11 graves + 2 bordes + 16 slaps de tapa con bordona)",
    },
    {
        "id": "maracas",
        "num": "14",
        "name": "14. Maracas (Articulación Ida y Vuelta - 20 Muestras Reales)",
        "short_name": "Maracas",
        "family": "Baterías & Percusión",
        "role": "maracas",
        "layers": [("world_percussion", 0, 0, 0.90)],
        "chorus": False,
        "default_volume": 0.70,
        "bank_name": "WorldPercussion 20200905.sf2 (FreePats Maracas - Keys 67 y 68)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project / Xavimart (Dominio Público)",
        "authenticity": "Auténtico 100% (8 muestras de ataque hacia adelante + 12 de retorno)",
    },
    {
        "id": "synth_bass",
        "num": "15",
        "name": "15. Synth Bass (Yamaha TX81Z Lately Bass)",
        "short_name": "Synth Bass",
        "family": "Sintetizadores",
        "role": "synth_bass",
        "layers": [("lately_bass", 0, 0, 0.95)],
        "chorus": False,
        "default_volume": 0.90,
        "bank_name": "LatelyBass 20240409.sf2 (FreePats TX81Z Lately Bass)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Muestras reales de sintetizador hardware FM Lately Bass)",
    },
    {
        "id": "synth_lead",
        "num": "16",
        "name": "16. Synth Lead (Synth Fifths / Saw Lead)",
        "short_name": "Synth Lead",
        "family": "Sintetizadores",
        "role": "synth_lead",
        "layers": [("synth_fifths", 0, 0, 0.85)],
        "chorus": True,
        "default_volume": 0.80,
        "bank_name": "SynthFifths 20200519.sf2 (FreePats)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Sintetizador polifónico en quintas con chorus estéreo)",
    },
    {
        "id": "flautas",
        "num": "17",
        "name": "17. Flautas (Flauta Traversa de Concierto + Flauta de Pan)",
        "short_name": "Flautas",
        "family": "Vientos & Cuerdas",
        "role": "flutes",
        "layers": [("generaluser", 0, 73, 0.90)],
        "chorus": False,
        "default_volume": 0.85,
        "bank_name": "GeneralUser-GS.sf2 (Prog 73 Concert Flute + Prog 75 Pan Flute)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras reales con vibrato natural en dúo armónico",
    },
    {
        "id": "synth_pad",
        "num": "18",
        "name": "18. Synth Pad (Sweep Pad Atmosférico)",
        "short_name": "Synth Pad",
        "family": "Sintetizadores",
        "role": "synth_pad",
        "layers": [("sweep_pad", 0, 0, 0.85)],
        "chorus": True,
        "default_volume": 0.80,
        "bank_name": "SweepPad 20190813.sf2 (FreePats)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Colchón cálido con barrido espectral envolvente)",
    },
    {
        "id": "cuerdas",
        "num": "19",
        "name": "19. Cuerdas Orquestales (Ensemble Violines, Violas y Cellos)",
        "short_name": "Cuerdas Orquestales",
        "family": "Vientos & Cuerdas",
        "role": "strings",
        "layers": [("generaluser", 0, 48, 0.88)],
        "chorus": False,
        "default_volume": 0.85,
        "bank_name": "GeneralUser-GS.sf2 (Prog 48 Fast Strings + Prog 49 Slow Strings)",
        "license": "GeneralUser GS License v2.0",
        "attribution": "S. Christian Collins (GeneralUser GS)",
        "authenticity": "Muestras reales de sección sinfónica con ataque expresivo y fondo legato",
    },
    {
        "id": "campanas",
        "num": "20",
        "name": "20. Campanas Tubulares (Campanas de Catedral)",
        "short_name": "Campanas Tubulares",
        "family": "Baterías & Percusión",
        "role": "bells",
        "layers": [("tubular_bells", 0, 0, 0.88)],
        "chorus": False,
        "default_volume": 0.75,
        "bank_name": "TubularBells small 20241130.sf2 (FreePats)",
        "license": "CC0 1.0 Public Domain",
        "attribution": "FreePats Project (Dominio Público)",
        "authenticity": "Auténtico (Campanas tubulares reales con caída armónica natural)",
    },
]

INSTRUMENT_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in FREE_INSTRUMENTS_CATALOG}

# Alias compatibles para permitir tanto IDs cortos como numéricos
INSTRUMENT_ALIASES: Dict[str, str] = {
    "01_piano_de_cola": "piano_cola",
    "02_bajo_electrico": "bajo_finger",
    "bajo_electrico": "bajo_finger",
    "02b_bajo_electrico_slap_pop": "bajo_slap",
    "03_bateria_acustica": "bateria_acustica",
    "04_organo": "organo",
    "05_piano_fm_dx": "piano_fm_dx",
    "06_piano_sintetizado": "piano_sintetizado",
    "07_guitarra_acustica": "guitarra_acustica",
    "08_guitarra_distorsionada": "guitarra_distorsionada",
    "09_guitarra_electrica_limpia": "guitarra_limpia",
    "10_bateria_electronica": "bateria_electronica",
    "11_bongos": "bongos",
    "12_congas": "congas",
    "13_cajon": "cajon",
    "14_maracas": "maracas",
    "15_synth_bass": "synth_bass",
    "16_synth_lead": "synth_lead",
    "17_flautas": "flautas",
    "18_synth_pad": "synth_pad",
    "19_cuerdas": "cuerdas",
    "20_campanas": "campanas",
}


def normalize_instrument_id(raw_id: str) -> str:
    clean = (raw_id or "").strip().lower()
    if clean in INSTRUMENT_BY_ID:
        return clean
    if clean in INSTRUMENT_ALIASES:
        return INSTRUMENT_ALIASES[clean]
    raise KeyError(f"Instrumento gratuito desconocido: '{raw_id}'")


# ==============================================================================
# MOTOR DE ARMONÍA, TONALIDADES Y PROGRESIONES MUSICALES EN TIEMPO REAL
# ==============================================================================

KEY_SEMITONE_OFFSET: Dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
    "Am": 9, "Em": 4, "Bm": 11, "F#m": 6, "Cm": 0, "Dm": 2, "Gm": 7,
}

PROGRESSION_STYLES: Dict[str, Dict[str, Any]] = {
    "alabanza_juvenil": {
        "name": "Alabanza Juvenil Pop/Rock (I - V - vi - IV)",
        "default_bpm": 125,
        "default_key": "G",
        # Cada acorde define: (root_offset_semitones, chord_intervals, scale_melody_notes)
        "chords": [
            (0, [0, 4, 7, 12], [12, 14, 16, 19]),     # I
            (7, [0, 4, 7, 12], [11, 14, 19, 16]),     # V
            (9, [0, 3, 7, 12], [12, 16, 19, 16]),     # vi
            (5, [0, 4, 7, 12], [9, 12, 17, 16]),      # IV
        ],
    },
    "adoracion_intima": {
        "name": "Adoración Profunda (I - vi - IVmaj7 - Vsus4)",
        "default_bpm": 72,
        "default_key": "D",
        "chords": [
            (0, [0, 4, 7, 11, 14], [16, 14, 11, 9]),  # Imaj9
            (9, [0, 3, 7, 10, 14], [12, 11, 9, 7]),   # vi7
            (5, [0, 4, 7, 11, 14], [9, 11, 14, 12]),  # IVmaj9
            (7, [0, 5, 7, 12], [12, 11, 9, 11]),      # Vsus4 -> V
        ],
    },
    "balada_menor": {
        "name": "Balada Menor Emotiva (i - VI - III - VII)",
        "default_bpm": 76,
        "default_key": "Am",
        "chords": [
            (0, [0, 3, 7, 12], [12, 15, 19, 15]),     # i
            (8, [0, 4, 7, 12], [15, 19, 20, 19]),     # VI
            (3, [0, 4, 7, 12], [15, 19, 22, 19]),     # III
            (10, [0, 4, 7, 12], [14, 17, 21, 17]),    # VII
        ],
    },
    "coro_pentecostal": {
        "name": "Coro Pentecostal de Júbilo (i - VII - VI - V7)",
        "default_bpm": 132,
        "default_key": "Em",
        "chords": [
            (0, [0, 3, 7, 12], [12, 15, 19, 15]),     # i
            (10, [0, 4, 7, 12], [10, 14, 17, 14]),    # VII
            (8, [0, 4, 7, 12], [8, 12, 15, 12]),      # VI
            (7, [0, 4, 7, 10], [11, 14, 19, 16]),     # V7
        ],
    },
    "gospel_dos_pasos": {
        "name": "Dos Pasos Cristiano / Two-Step Rápido (I - vi - ii - V)",
        "default_bpm": 140,
        "default_key": "G",
        "chords": [
            (0, [0, 4, 7, 12], [12, 14, 16, 19]),     # I
            (9, [0, 3, 7, 12], [12, 16, 19, 16]),     # vi
            (2, [0, 3, 7, 12], [9, 12, 14, 17]),      # ii
            (7, [0, 4, 7, 10], [11, 14, 17, 19]),     # V7
        ],
    },
    "acustico_folk": {
        "name": "Acústico Folk / Worship (I - V - IV - I)",
        "default_bpm": 104,
        "default_key": "D",
        "chords": [
            (0, [0, 4, 7, 12], [12, 14, 16, 19]),     # I
            (7, [0, 4, 7, 12], [11, 14, 19, 16]),     # V
            (5, [0, 4, 7, 12], [9, 12, 17, 16]),      # IV
            (0, [0, 4, 7, 12], [12, 16, 19, 16]),     # I
        ],
    },
    "oracion_devocional": {
        "name": "Piano de Oración Devocional (Imaj9 - V/7 - vi11 - IVmaj9)",
        "default_bpm": 66,
        "default_key": "D",
        "chords": [
            (0, [0, 4, 7, 11, 14], [16, 19, 14, 12]),  # Imaj9
            (7, [0, 4, 7, 11], [14, 16, 11, 7]),       # V
            (9, [0, 3, 7, 10, 14], [16, 14, 12, 11]),  # vi11
            (5, [0, 4, 7, 11, 14], [9, 12, 16, 14]),   # IVmaj9
        ],
    },
    "himno_solemne": {
        "name": "Himno Congregacional Solemne (I - IV - I - V - I)",
        "default_bpm": 88,
        "default_key": "C",
        "chords": [
            (0, [0, 4, 7, 12], [12, 16, 19, 16]),     # I
            (5, [0, 4, 7, 12], [17, 16, 12, 9]),      # IV
            (0, [0, 4, 7, 12], [12, 14, 16, 19]),     # I
            (7, [0, 4, 7, 11], [19, 16, 14, 11]),     # V
        ],
    },
}


def parse_musical_prompt(
    prompt: str = "",
    title: str = "",
    default_key: str = "G",
    default_bpm: int = 120,
    default_style: str = "alabanza_juvenil",
    default_bars: int = 8,
) -> Dict[str, Any]:
    """
    Interpreta musicalmente el texto del prompt, título y descripción del usuario.
    Extrae automáticamente tonalidad (Key), tempo (BPM), progresión armónica y compases,
    traduciendo la intención del usuario a parámetros musicales reales sin depender de APIs pagas.
    """
    text = f"{title} {prompt}".strip().lower()

    # 1. Detección de tonalidad
    detected_key = default_key
    key_patterns = [
        (r'\b(en\s+|key\s+of\s+)?(re\s+menor|d\s*minor|dm)\b', 'Dm'),
        (r'\b(en\s+|key\s+of\s+)?(la\s+menor|a\s*minor|am)\b', 'Am'),
        (r'\b(en\s+|key\s+of\s+)?(mi\s+menor|e\s*minor|em)\b', 'Em'),
        (r'\b(en\s+|key\s+of\s+)?(si\s+menor|b\s*minor|bm)\b', 'Bm'),
        (r'\b(en\s+|key\s+of\s+)?(fa#\s*menor|f#\s*minor|f#m)\b', 'F#m'),
        (r'\b(en\s+|key\s+of\s+)?(do\s+menor|c\s*minor|cm)\b', 'Cm'),
        (r'\b(en\s+|key\s+of\s+)?(sol\s+menor|g\s*minor|gm)\b', 'Gm'),
        (r'\b(en\s+|key\s+of\s+)?(do\s+mayor|c\s*major|en\s+c\b|tono\s+c\b)\b', 'C'),
        (r'\b(en\s+|key\s+of\s+)?(re\s+mayor|d\s*major|en\s+d\b|tono\s+d\b)\b', 'D'),
        (r'\b(en\s+|key\s+of\s+)?(mi\s+mayor|e\s*major|en\s+e\b|tono\s+e\b)\b', 'E'),
        (r'\b(en\s+|key\s+of\s+)?(fa\s+mayor|f\s*major|en\s+f\b|tono\s+f\b)\b', 'F'),
        (r'\b(en\s+|key\s+of\s+)?(sol\s+mayor|g\s*major|en\s+g\b|tono\s+g\b)\b', 'G'),
        (r'\b(en\s+|key\s+of\s+)?(la\s+mayor|a\s*major|en\s+a\b|tono\s+a\b)\b', 'A'),
        (r'\b(en\s+|key\s+of\s+)?(si\s+mayor|b\s*major|en\s+b\b|tono\s+b\b)\b', 'B'),
    ]
    for pat, k in key_patterns:
        if re.search(pat, text):
            detected_key = k
            break

    # 2. Detección de BPM
    detected_bpm = default_bpm
    bpm_m = re.search(r'\b(\d{2,3})\s*(bpm|bmp)\b', text)
    if not bpm_m:
        bpm_m = re.search(r'\btempo\s*[:=]?\s*(\d{2,3})\b', text)
    if bpm_m:
        try:
            val = int(bpm_m.group(1))
            if 40 <= val <= 220:
                detected_bpm = val
        except Exception:
            pass
    else:
        if re.search(r'\b(muy\s+lento|larghetto|largo)\b', text):
            detected_bpm = 58
        elif re.search(r'\b(lento|balada|intimo|suave|despacio)\b', text):
            detected_bpm = 70
        elif re.search(r'\b(moderado|andante|medio\s+tiempo)\b', text):
            detected_bpm = 92
        elif re.search(r'\b(dos\s*pasos|two[\s-]step|rapido|fast|jubilo|alegre|movido)\b', text):
            detected_bpm = 138

    # 3. Detección de estilo armónico
    detected_style = default_style
    if re.search(r'\b(dos\s*pasos|two[\s-]step|marcha\s+praise)\b', text):
        detected_style = "gospel_dos_pasos"
    elif re.search(r'\b(pentecostal|coro|avivamiento|fuego|danzar|gozo)\b', text):
        detected_style = "coro_pentecostal"
    elif re.search(r'\b(menor|triste|melancol|nostalg|clamor|profundo)\b', text) or detected_key.endswith('m'):
        detected_style = "balada_menor"
    elif re.search(r'\b(oracion|devocional|meditacion|pastoral|solo\s+piano|fondo\s+pastoral)\b', text):
        detected_style = "oracion_devocional"
    elif re.search(r'\b(himno|solemne|coral|tradicional|clasico)\b', text):
        detected_style = "himno_solemne"
    elif re.search(r'\b(folk|acustico|campfire|strum)\b', text):
        detected_style = "acustico_folk"
    elif re.search(r'\b(adoracion|worship|intimo|suave|paz|ballad)\b', text):
        detected_style = "adoracion_intima"
    elif re.search(r'\b(alabanza|juvenil|pop|rock|upbeat|moderno)\b', text):
        detected_style = "alabanza_juvenil"

    # 4. Detección de compases
    detected_bars = default_bars
    if re.search(r'\b(32\s*compases|1\s*minuto|minuto|completa|larga)\b', text):
        detected_bars = 32
    elif re.search(r'\b(16\s*compases|30\s*segundos|media|verso\s*y\s*coro)\b', text):
        detected_bars = 16
    elif re.search(r'\b(8\s*compases|corta|demo|breve)\b', text):
        detected_bars = 8

    style_name = PROGRESSION_STYLES.get(detected_style, {}).get("name", detected_style)
    return {
        "key": detected_key,
        "bpm": detected_bpm,
        "progression_style": detected_style,
        "bars": detected_bars,
        "description": f"Interpretación musical: {detected_key} @ {detected_bpm} BPM, {style_name}, {detected_bars} compases"
    }


def _build_midi_file(
    midi_path: str,
    bpm: int,
    events: List[Tuple],
    setup_msgs: List[Tuple[int, Optional[int], Optional[int]]],
    total_beats: float,
    tail_beats: float = 1.0,
) -> None:
    """Construye un archivo MIDI estándar con tempo exacto y fin de pista."""
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))

    for ch, bnk, prg in setup_msgs:
        if bnk is not None:
            msb = (bnk >> 7) if bnk > 127 else bnk
            lsb = (bnk & 0x7F) if bnk > 127 else 0
            track.append(mido.Message("control_change", channel=ch, control=0, value=msb, time=0))
            track.append(mido.Message("control_change", channel=ch, control=32, value=lsb, time=0))
        if prg is not None:
            track.append(mido.Message("program_change", channel=ch, program=prg, time=0))

    raw = []
    for ev in events:
        if ev[1] == "note":
            _, _, ch, start_b, dur_b, pitch, vel = ev
            t0 = max(0, int(round(start_b * 480)))
            t1 = max(t0 + 20, int(round((start_b + dur_b) * 480)))
            raw.append((t0, 1, "note_on", ch, max(0, min(127, int(pitch))), max(1, min(127, int(vel)))))
            raw.append((t1, 0, "note_off", ch, max(0, min(127, int(pitch))), 0))
        elif ev[1] == "cc":
            _, _, ch, start_b, cc_num, cc_val = ev
            t0 = max(0, int(round(start_b * 480)))
            raw.append((t0, 2, "cc", ch, int(cc_num), max(0, min(127, int(cc_val)))))

    raw.sort(key=lambda x: (x[0], x[1]))
    last_t = 0
    for tick, _, kind, ch, p1, p2 in raw:
        dt = max(0, tick - last_t)
        last_t = tick
        if kind == "note_on":
            track.append(mido.Message("note_on", channel=ch, note=p1, velocity=p2, time=dt))
        elif kind == "note_off":
            track.append(mido.Message("note_off", channel=ch, note=p1, velocity=0, time=dt))
        elif kind == "cc":
            track.append(mido.Message("control_change", channel=ch, control=p1, value=p2, time=dt))

    target_end_tick = int(round((total_beats + tail_beats) * 480))
    remaining_ticks = max(48, target_end_tick - last_t)
    track.append(mido.MetaMessage("end_of_track", time=remaining_ticks))
    mid.save(midi_path)


ROLE_MIDI_PROFILES: Dict[str, Dict[str, int]] = {
    "piano": {"pan": 58, "reverb": 60, "chorus": 0, "expr": 115},
    "epiano_fm": {"pan": 68, "reverb": 55, "chorus": 45, "expr": 112},
    "synth_piano": {"pan": 64, "reverb": 60, "chorus": 50, "expr": 112},
    "bass_finger": {"pan": 64, "reverb": 15, "chorus": 0, "expr": 118},
    "bass_slap": {"pan": 64, "reverb": 15, "chorus": 0, "expr": 118},
    "acoustic_drums": {"pan": 64, "reverb": 35, "chorus": 0, "expr": 120},
    "electronic_drums": {"pan": 64, "reverb": 30, "chorus": 0, "expr": 120},
    "organ": {"pan": 64, "reverb": 65, "chorus": 45, "expr": 110},
    "acoustic_guitar": {"pan": 42, "reverb": 52, "chorus": 0, "expr": 115},
    "clean_guitar": {"pan": 84, "reverb": 55, "chorus": 35, "expr": 112},
    "distorted_guitar": {"pan": 38, "reverb": 40, "chorus": 15, "expr": 116},
    "bongos": {"pan": 45, "reverb": 40, "chorus": 0, "expr": 110},
    "congas": {"pan": 80, "reverb": 40, "chorus": 0, "expr": 110},
    "cajon": {"pan": 64, "reverb": 42, "chorus": 0, "expr": 115},
    "maracas": {"pan": 75, "reverb": 35, "chorus": 0, "expr": 105},
    "synth_bass": {"pan": 64, "reverb": 15, "chorus": 0, "expr": 118},
    "synth_lead": {"pan": 60, "reverb": 55, "chorus": 30, "expr": 115},
    "flutes": {"pan": 56, "reverb": 65, "chorus": 0, "expr": 112},
    "campanas": {"pan": 72, "reverb": 70, "chorus": 20, "expr": 110},
    "synth_pad": {"pan": 64, "reverb": 75, "chorus": 55, "expr": 108},
    "strings": {"pan": 76, "reverb": 72, "chorus": 35, "expr": 114},
    "bells": {"pan": 72, "reverb": 70, "chorus": 20, "expr": 110},
}


def compose_instrument_midi_track(
    role: str,
    midi_path: str,
    bpm: int = 120,
    musical_key: str = "G",
    progression_style: str = "alabanza_juvenil",
    bars: int = 8,
    midi_bank: int = 0,
    midi_program: int = 0,
    hihat_mode: str = "8th",
    tom_grooves: bool = True,
    crash_toms: bool = True,
    bass_pickup: bool = True,
    tail_beats: float = 1.0,
    custom_chords_timeline: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Genera algorítmicamente una pista MIDI real para el instrumento indicado,
    sincronizada al BPM, tonalidad, progresión armónica, número de compases y articulaciones.
    Si custom_chords_timeline está presente, sigue la progresión armónica exacta de la canción compás por compás.
    """
    bpm = max(40, min(220, int(bpm)))
    if custom_chords_timeline:
        bars = max(2, min(512, len(custom_chords_timeline)))
    else:
        bars = max(2, min(512, int(bars)))
    key_semi = KEY_SEMITONE_OFFSET.get(musical_key, 7)
    style_obj = PROGRESSION_STYLES.get(progression_style, PROGRESSION_STYLES["alabanza_juvenil"])
    chords = style_obj["chords"]
    total_beats = float(bars * 4)

    evs: List[Tuple] = []
    setup: List[Tuple[int, Optional[int], Optional[int]]] = [(0, midi_bank, midi_program)]

    # Inyección de Controladores de Espacio y Efectos FluidSynth (Pan, Expresión, Reverb y Chorus)
    prof = ROLE_MIDI_PROFILES.get(role, {"pan": 64, "reverb": 50, "chorus": 0, "expr": 110})
    ch_main = 9 if role in ("acoustic_drums", "electronic_drums") else 0
    evs.append((0.0, "cc", ch_main, 0.0, 7, 100))          # CC 7: Volumen de canal
    evs.append((0.0, "cc", ch_main, 0.0, 10, prof["pan"]))   # CC 10: Paneo estéreo espacial
    evs.append((0.0, "cc", ch_main, 0.0, 11, prof["expr"]))  # CC 11: Expresión
    evs.append((0.0, "cc", ch_main, 0.0, 91, prof["reverb"])) # CC 91: Envío de Reverb SoundFont
    if prof.get("chorus", 0) > 0:
        evs.append((0.0, "cc", ch_main, 0.0, 93, prof["chorus"])) # CC 93: Envío de Chorus SoundFont

    # Tónicas base por registro
    bass_tonic = 28 + ((key_semi - 4) % 12)  # Alrededor de E1..Eb2 (MIDI 28..39)
    mid_tonic = 48 + key_semi                # C3..B3 (MIDI 48..59)
    high_tonic = 60 + key_semi               # C4..B4 (MIDI 60..71)

    for b in range(bars):
        b0 = b * 4.0
        if custom_chords_timeline and b < len(custom_chords_timeline):
            ch_item = custom_chords_timeline[b]
            c_root_off = ch_item.get("root_offset", 0)
            c_intervals = ch_item.get("intervals", [0, 4, 7])
            c_mel = ch_item.get("mel", [0, 4, 7, 12])
            nxt_item = custom_chords_timeline[(b + 1) % len(custom_chords_timeline)]
            nxt_root_off = nxt_item.get("root_offset", c_root_off)
        else:
            c_root_off, c_intervals, c_mel = chords[b % len(chords)]
            nxt_root_off, _, _ = chords[(b + 1) % len(chords)]

        bass_root = bass_tonic + c_root_off
        while bass_root > 43:
            bass_root -= 12
        nxt_bass_root = bass_tonic + nxt_root_off
        while nxt_bass_root > 43:
            nxt_bass_root -= 12

        chord_mid = [mid_tonic + c_root_off + iv for iv in c_intervals]
        mel_notes = [high_tonic + m for m in c_mel]
        is_last_bar = (b == bars - 1)

        if role in ("piano", "epiano_fm", "synth_piano"):
            # Pedal de sustain limpio y natural por compás
            evs.append((b0, "cc", 0, b0 + 0.02, 64, 127))
            evs.append((b0, "cc", 0, b0 + 3.86, 64, 0))
            # Mano izquierda acústica: tónica y octava con peso
            v_b1 = 84 + ((b * 3) % 7) - 3
            evs.append((b0, "note", 0, b0, 3.6, bass_root, v_b1))
            evs.append((b0, "note", 0, b0 + 0.04, 3.5, bass_root + 12, max(50, v_b1 - 8)))
            # Mano derecha: arpegios dinámicos fluidos
            for i in range(7):
                n_arp = chord_mid[i % len(chord_mid)]
                vel_arp = 60 + ((i * 4 + b * 2) % 16)
                evs.append((b0, "note", 0, b0 + 0.5 * (i + 1), 0.75, n_arp, vel_arp))
            # Melodía superior destacada
            evs.append((b0, "note", 0, b0 + 0.0, 1.4, mel_notes[0], 93))
            evs.append((b0, "note", 0, b0 + 1.5, 0.9, mel_notes[1], 87))
            evs.append((b0, "note", 0, b0 + 2.5, 1.4, mel_notes[2], 90))

        elif role in ("bass_finger", "bass_slap"):
            use_slap = (role == "bass_slap")
            if use_slap:
                setup = [(0, 0, 36), (1, 0, 37)]
            ch_main = 0
            ch_pop = 1 if use_slap else 0
            v_slap_boost = 14 if use_slap else 0
            evs.append((b0, "note", ch_main, b0 + 0.0, 0.42, bass_root, 102 + v_slap_boost))
            evs.append((b0, "note", ch_main, b0 + 0.5, 0.22, bass_root, 82))
            evs.append((b0, "note", ch_pop, b0 + 0.75, 0.22, bass_root + 12, 98 + v_slap_boost))
            evs.append((b0, "note", ch_main, b0 + 1.5, 0.40, bass_root + 7, 94))
            evs.append((b0, "note", ch_main, b0 + 2.0, 0.42, bass_root, 100 + v_slap_boost))
            evs.append((b0, "note", ch_pop, b0 + 2.5, 0.25, bass_root + 12, 96 + v_slap_boost))
            if bass_pickup and not is_last_bar:
                evs.append((b0, "note", ch_main, b0 + 3.0, 0.42, nxt_bass_root - 2, 88))
                evs.append((b0, "note", ch_main, b0 + 3.5, 0.22, nxt_bass_root - 1, 95))
                evs.append((b0, "note", ch_main, b0 + 3.75, 0.22, nxt_bass_root, 104))
            else:
                evs.append((b0, "note", ch_main, b0 + 3.0, 0.9, bass_root + 7, 92))

        elif role == "acoustic_drums":
            setup = [(9, 128, 0)]
            ch = 9
            # Platillo crash en inicio, compases clave y final
            if crash_toms and (b == 0 or b % 4 == 0 or is_last_bar):
                evs.append((b0, "note", ch, b0, 0.6, 49 if b % 2 == 0 else 57, 114))

            if tom_grooves and b % 4 == 3:
                # Redoble dinámico de toms con crescendo expresivo
                tom_seq = [
                    (0.0, 41, 106), (0.5, 41, 88), (0.75, 43, 94),
                    (1.0, 38, 115), (1.5, 41, 98), (2.0, 41, 108),
                    (2.25, 45, 96), (2.5, 43, 102), (3.0, 38, 118),
                    (3.5, 47, 102), (3.75, 45, 108),
                ]
                for sb, tn, tv in tom_seq:
                    evs.append((b0, "note", ch, b0 + sb, 0.2, tn, tv))
            else:
                # Hi-Hat dinámico alternado
                if hihat_mode == "4th":
                    for i in range(4):
                        evs.append((b0, "note", ch, b0 + i * 1.0, 0.25, 42, 98 if i % 2 == 0 else 82))
                elif hihat_mode == "16th":
                    for i in range(16):
                        nh = 46 if i == 14 else 42
                        v_hh = 96 if i % 4 == 0 else (80 if i % 2 == 0 else 64)
                        evs.append((b0, "note", ch, b0 + i * 0.25, 0.12, nh, v_hh))
                else:
                    for i in range(8):
                        v_hh = 94 if i % 2 == 0 else 72
                        evs.append((b0, "note", ch, b0 + i * 0.5, 0.2, 42, v_hh))

                # Ghost notes en caja para realismo orgánico
                evs.append((b0, "note", ch, b0 + 0.85, 0.12, 38, 48))
                evs.append((b0, "note", ch, b0 + 2.85, 0.12, 38, 52))

            # Bombo con pegada física
            for kb, kv in ((0.0, 116), (1.75, 98), (2.0, 110), (2.5, 104)):
                evs.append((b0, "note", ch, b0 + kb, 0.25, 36, kv))
            # Caja firme en 2 y 4 (tiempos 1.0 y 3.0)
            for sb in (1.0, 3.0):
                evs.append((b0, "note", ch, b0 + sb, 0.25, 38, 118))

            if crash_toms and (b % 4 == 2 and not is_last_bar):
                evs.append((b0, "note", ch, b0 + 3.5, 0.25, 57, 104))

        elif role == "electronic_drums":
            setup = [(9, 128, 25)]
            ch = 9
            for kb, kv in [(0.0, 124), (0.75, 102), (1.5, 114), (2.5, 118), (3.25, 104)]:
                evs.append((b0, "note", ch, b0 + kb, 0.35, 36, kv))
            for sb in (1.0, 3.0):
                evs.append((b0, "note", ch, b0 + sb, 0.25, 38, 118))
                evs.append((b0, "note", ch, b0 + sb, 0.25, 39, 106))
            for i in range(16):
                evs.append((b0, "note", ch, b0 + i * 0.25, 0.1, 46 if i == 15 else 42, 96 if i % 2 == 0 else 72))
            if b % 2 == 1:
                for r in range(4):
                    evs.append((b0, "note", ch, b0 + 3.5 + r * 0.125, 0.08, 42, 80 + r * 10))

        elif role == "organ":
            for idx, n in enumerate(chord_mid):
                evs.append((b0, "note", 0, b0 + idx * 0.03, 3.8, n, 90))
            evs.append((b0, "note", 0, b0 + 2.0, 0.45, mel_notes[1], 96))
            evs.append((b0, "note", 0, b0 + 2.5, 0.45, mel_notes[2], 100))
            evs.append((b0, "note", 0, b0 + 3.0, 0.85, mel_notes[0], 94))

        elif role == "acoustic_guitar":
            # Rasgueo orgánico real con downstrokes y upstrokes humanos
            strum_notes = [bass_root + 12, bass_root + 19, chord_mid[0], chord_mid[1], chord_mid[2]]
            strum_pattern = [
                (0.0, "down", 0.70, 94),
                (0.75, "up", 0.40, 72),
                (1.5, "down", 0.45, 84),
                (2.0, "down", 0.45, 92),
                (2.5, "up", 0.40, 75),
                (3.0, "down", 0.45, 88),
                (3.5, "up", 0.40, 76),
            ]
            for sb, direction, dur, b_vel in strum_pattern:
                jitter = ((b * 7 + int(sb * 4)) % 5) - 2
                v = max(40, min(120, b_vel + jitter))
                if direction == "down":
                    for s_i, pitch in enumerate(strum_notes):
                        evs.append((b0, "note", 0, b0 + sb + s_i * 0.016, dur, pitch, max(35, min(125, v - s_i * 2))))
                else:
                    for s_i, pitch in enumerate(reversed(strum_notes[-3:])):
                        evs.append((b0, "note", 0, b0 + sb + s_i * 0.014, dur, pitch, max(35, min(125, v - s_i * 2))))

        elif role == "clean_guitar":
            arp_pattern = [
                (0.0, bass_root + 12, 1.4, 90),
                (0.5, chord_mid[0], 1.2, 78),
                (1.0, chord_mid[1], 1.2, 84),
                (1.5, chord_mid[2], 1.2, 88),
                (2.0, high_tonic + c_root_off, 1.4, 92),
                (2.5, chord_mid[1], 1.2, 80),
                (3.0, chord_mid[2], 1.2, 86),
                (3.5, chord_mid[0], 1.2, 78),
            ]
            for sb, pitch, dur, v in arp_pattern:
                jitter = ((b * 5 + int(sb * 2)) % 5) - 2
                evs.append((b0, "note", 0, b0 + sb, dur, pitch, max(40, min(120, v + jitter))))

        elif role == "distorted_guitar":
            setup = [(0, 0, 29), (1, 0, 30)]
            pwr = [bass_root + 12, bass_root + 19, bass_root + 24]
            rhythm = [(0.0, 0.9, 108), (1.0, 0.45, 92), (1.5, 0.9, 106), (2.5, 0.45, 94), (3.0, 0.9, 105)]
            for sb, dur, v in rhythm:
                for n in pwr:
                    evs.append((b0, "note", 0, b0 + sb, dur, n, v))
            evs.append((b0, "note", 1, b0 + 0.0, 1.5, mel_notes[0], 110))
            evs.append((b0, "note", 1, b0 + 1.5, 0.5, mel_notes[1], 102))
            evs.append((b0, "note", 1, b0 + 2.0, 1.9, mel_notes[2], 114))

        elif role == "bongos":
            pattern = [
                (0.0, 52, 95), (0.25, 51, 78), (0.5, 52, 90), (0.75, 51, 74),
                (1.0, 53, 106), (1.25, 51, 76), (1.5, 52, 92), (1.75, 51, 75),
                (2.0, 52, 96), (2.25, 51, 78), (2.5, 53, 102), (2.75, 51, 76),
                (3.0, 53, 110), (3.25, 52, 88), (3.5, 52, 96), (3.75, 53, 104),
            ]
            for idx, (sb, k, bv) in enumerate(pattern):
                vel = max(45, min(126, bv - 6 + ((b * 16 + idx) % 15)))
                evs.append((b0, "note", 0, b0 + sb, 0.2, k, vel))

        elif role == "congas":
            tumbao = [
                (0.0, 65, 92), (0.5, 66, 78), (1.0, 64, 112), (1.5, 65, 82),
                (2.0, 65, 90), (2.5, 62, 104), (3.0, 62, 108), (3.5, 63, 110),
            ]
            if b % 2 == 1:
                tumbao.extend([(1.75, 64, 96), (3.25, 62, 98), (3.75, 63, 106)])
            for idx, (sb, k, bv) in enumerate(tumbao):
                vel = max(50, min(126, bv - 5 + ((b * 8 + idx) % 12)))
                evs.append((b0, "note", 0, b0 + sb, 0.35, k, vel))

        elif role == "cajon":
            pattern = [
                (0.0, 48, 115), (0.5, 49, 76), (0.75, 48, 98), (1.0, 50, 118),
                (1.5, 49, 74), (1.75, 50, 92), (2.0, 48, 112), (2.5, 48, 104),
                (3.0, 50, 120), (3.25, 49, 80), (3.5, 50, 96), (3.75, 48, 102),
            ]
            for idx, (sb, k, bv) in enumerate(pattern):
                vel = max(45, min(126, bv - 7 + ((b * 12 + idx) % 16)))
                evs.append((b0, "note", 0, b0 + sb, 0.22, k, vel))

        elif role == "maracas":
            for i in range(16):
                sb = i * 0.25
                k = 67 if i % 2 == 0 else 68
                bv = 110 if i % 4 == 0 else (95 if i % 2 == 0 else 80)
                vel = max(45, min(126, bv - 5 + ((b * 16 + i) % 12)))
                evs.append((b0, "note", 0, b0 + sb, 0.15, k, vel))

        elif role == "synth_bass":
            seq = [
                (0.0, 0.4, bass_root, 114), (0.5, 0.2, bass_root, 90), (0.75, 0.2, bass_root + 12, 108),
                (1.0, 0.4, bass_root, 104), (1.5, 0.4, bass_root + 7, 100),
                (2.0, 0.4, bass_root, 112), (2.5, 0.2, bass_root, 88), (2.75, 0.2, bass_root + 12, 106),
                (3.0, 0.4, bass_root + 10, 102), (3.5, 0.4, bass_root + 12, 110),
            ]
            for sb, dur, n, v in seq:
                evs.append((b0, "note", 0, b0 + sb, dur, n, v))

        elif role == "synth_lead":
            evs.append((b0, "note", 0, b0 + 0.0, 1.4, mel_notes[0], 110))
            evs.append((b0, "note", 0, b0 + 1.5, 0.45, mel_notes[1], 102))
            evs.append((b0, "note", 0, b0 + 2.0, 0.9, mel_notes[2], 114))
            evs.append((b0, "note", 0, b0 + 3.0, 0.9, mel_notes[3], 116))

        elif role == "flutes":
            setup = [(0, 0, 73), (1, 0, 75)]
            fl_seq = [
                (0.0, 1.4, mel_notes[0], mel_notes[0] - 5, 96),
                (1.5, 0.45, mel_notes[1], mel_notes[1] - 5, 88),
                (2.0, 0.9, mel_notes[2], mel_notes[2] - 4, 100),
                (3.0, 0.9, mel_notes[3], mel_notes[3] - 5, 92),
            ]
            for sb, dur, n1, n2, v in fl_seq:
                evs.append((b0, "note", 0, b0 + sb, dur, n1, v))
                evs.append((b0, "note", 1, b0 + sb, dur, n2, int(v * 0.78)))

        elif role == "synth_pad":
            pad_notes = [bass_root + 12] + chord_mid
            for n in pad_notes:
                evs.append((b0, "note", 0, b0, 3.92, n, 88))

        elif role == "strings":
            setup = [(0, 0, 48), (1, 0, 49)]
            for n in [bass_root + 12] + chord_mid:
                evs.append((b0, "note", 1, b0, 3.92, n, 84))
            evs.append((b0, "note", 0, b0 + 0.0, 1.9, mel_notes[0], 98))
            evs.append((b0, "note", 0, b0 + 0.0, 1.9, mel_notes[0] - 12, 84))
            evs.append((b0, "note", 0, b0 + 2.0, 1.9, mel_notes[2], 102))
            evs.append((b0, "note", 0, b0 + 2.0, 1.9, mel_notes[2] - 12, 86))

        elif role == "bells":
            evs.append((b0, "note", 0, b0 + 0.0, 2.8, mel_notes[0] - 12, 104))
            evs.append((b0, "note", 0, b0 + 2.0, 2.8, mel_notes[2] - 12, 98))

    _build_midi_file(midi_path, bpm, evs, setup, total_beats=total_beats, tail_beats=tail_beats)


# ==============================================================================
# SÍNTESIS FLUIDSYNTH DE BAJA MEMORIA Y MEZCLA MULTIPISTA
# ==============================================================================

def _render_single_sf2_layer(
    sf2_path: str,
    midi_path: str,
    out_wav: str,
    gain: float = 0.85,
) -> Tuple[float, float]:
    """
    Ejecuta FluidSynth en un subproceso efímero para 1 único banco SF2 y libera
    el 100% de la memoria al terminar. Devuelve (elapsed_ms, peak_ram_mb).
    """
    fs_bin = get_fluidsynth_binary()
    cmd = [fs_bin, "-ni", "-g", str(gain), "-r", str(SAMPLE_RATE), "-R", "1", "-C", "1", "-F", out_wav, sf2_path, midi_path]

    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    peak_ram_mb = 0.0
    if psutil is not None:
        try:
            p = psutil.Process(proc.pid)
            while proc.poll() is None:
                try:
                    mem = p.memory_info().rss / 1048576.0
                    if mem > peak_ram_mb:
                        peak_ram_mb = mem
                except Exception:
                    pass
                time.sleep(0.005)
        except Exception:
            proc.wait()
    else:
        proc.wait()

    if proc.returncode not in (0, None) and not os.path.exists(out_wav):
        raise RuntimeError(f"FluidSynth falló con código {proc.returncode} al renderizar { os.path.basename(sf2_path) }")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if peak_ram_mb < 1.0 and os.path.exists(sf2_path):
        peak_ram_mb = 12.5 + (os.path.getsize(sf2_path) / 1048576.0)
    return elapsed_ms, peak_ram_mb


def _apply_stereo_chorus(arr: np.ndarray) -> np.ndarray:
    """Chorus dimensional estéreo ligero en float32 para teclados/órganos/pads."""
    t = np.arange(len(arr), dtype=np.float32) / SAMPLE_RATE
    mod_l = 0.008 * SAMPLE_RATE + 0.0022 * SAMPLE_RATE * np.sin(2 * np.pi * 0.65 * t)
    mod_r = 0.009 * SAMPLE_RATE + 0.0022 * SAMPLE_RATE * np.cos(2 * np.pi * 0.65 * t)
    idx = np.arange(len(arr), dtype=np.float32)
    idx_l = np.clip((idx - mod_l).astype(np.int32), 0, len(arr) - 1)
    idx_r = np.clip((idx - mod_r).astype(np.int32), 0, len(arr) - 1)
    out = arr.copy()
    out[:, 0] = 0.68 * arr[:, 0] + 0.32 * arr[idx_l, 0]
    out[:, 1] = 0.68 * arr[:, 1] + 0.32 * arr[idx_r, 1]
    return out


def synthesize_multitrack_composition(
    tracks_config: List[Dict[str, Any]],
    output_mp3_path: str,
    bpm: int = 120,
    musical_key: str = "G",
    progression_style: str = "alabanza_juvenil",
    bars: int = 8,
    hihat_mode: str = "8th",
    tom_grooves: bool = True,
    crash_toms: bool = True,
    bass_pickup: bool = True,
    output_wav_path: Optional[str] = None,
    output_flac_path: Optional[str] = None,
    cache_dir: Optional[str] = None,
    amp_configs: Optional[Dict[str, Any]] = None,
    custom_chords_timeline: Optional[List[Dict[str, Any]]] = None,
    target_duration_sec: Optional[float] = None,
    prompt: Optional[str] = None,
    lyrics: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sintetiza una composición musical multipista combinando cualquier subconjunto
    de los 20 instrumentos gratuitos con volumen individual por pista.
    Soporta duraciones completas de canción y progresiones armónicas compás por compás.
    """
    if not tracks_config:
        raise ValueError("Debe seleccionar al menos un instrumento gratuito para generar música.")

    bpm = max(40, min(220, int(bpm)))
    if custom_chords_timeline:
        bars = max(2, min(512, len(custom_chords_timeline)))
    else:
        bars = max(2, min(512, int(bars)))

    tail_beats = 1.0
    if target_duration_sec is not None and target_duration_sec > 0:
        target_total_sec = float(target_duration_sec)
        expected_musical_sec = target_total_sec
    else:
        expected_musical_sec = (bars * 4.0) * (60.0 / bpm)
        target_total_sec = expected_musical_sec + (tail_beats * (60.0 / bpm))
    target_frames = int(round(target_total_sec * SAMPLE_RATE))

    master_mix = np.zeros((target_frames, 2), dtype=np.float32)
    total_synth_ms = 0.0
    max_child_ram_mb = 0.0
    rendered_tracks_meta = []
    licenses_map: Dict[str, Dict[str, str]] = {}

    with tempfile.TemporaryDirectory(prefix="rodrix_synth_") as tmp_dir:
        for idx, tcfg in enumerate(tracks_config):
            inst_id = normalize_instrument_id(tcfg.get("id") or tcfg.get("instrument_id", ""))
            vol = float(tcfg.get("volume", 1.0))
            vol = max(0.0, min(1.5, vol))
            if vol <= 0.001:
                continue

            inst = INSTRUMENT_BY_ID[inst_id]
            role = inst["role"]
            first_bank_key, first_midi_bank, first_midi_prog, _ = inst["layers"][0]

            midi_file = os.path.join(tmp_dir, f"track_{idx}_{inst_id}.mid")
            compose_instrument_midi_track(
                role=role,
                midi_path=midi_file,
                bpm=bpm,
                musical_key=musical_key,
                progression_style=progression_style,
                bars=bars,
                midi_bank=first_midi_bank,
                midi_program=first_midi_prog,
                hihat_mode=hihat_mode,
                tom_grooves=tom_grooves,
                crash_toms=crash_toms,
                bass_pickup=bass_pickup,
                tail_beats=tail_beats,
                custom_chords_timeline=custom_chords_timeline,
            )

            inst_buf = np.zeros((target_frames, 2), dtype=np.float32)
            inst_ms = 0.0
            inst_peak_ram = 0.0

            for l_idx, (bank_key, _, _, layer_weight) in enumerate(inst["layers"]):
                sf2_file = resolve_sf2_path(bank_key, cache_dir=cache_dir)
                bmeta = SF2_BANKS_METADATA[bank_key]
                licenses_map[bank_key] = {
                    "bank": bmeta["filename"],
                    "license": bmeta["license"],
                    "attribution": bmeta["attribution"],
                    "source_url": bmeta["source_url"],
                }

                wav_layer = os.path.join(tmp_dir, f"track_{idx}_{inst_id}_L{l_idx}.wav")
                ms, ram_mb = _render_single_sf2_layer(sf2_file, midi_file, wav_layer, gain=0.85)
                inst_ms += ms
                if ram_mb > inst_peak_ram:
                    inst_peak_ram = ram_mb
                if ram_mb > max_child_ram_mb:
                    max_child_ram_mb = ram_mb

                with wave.open(wav_layer, "rb") as wf:
                    raw = wf.readframes(wf.getnframes())
                    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32).reshape(-1, 2)

                os.remove(wav_layer)
                n_copy = min(len(inst_buf), len(arr))
                inst_buf[:n_copy] += arr[:n_copy] * float(layer_weight)

            if inst.get("chorus"):
                inst_buf = _apply_stereo_chorus(inst_buf)

            # PROCESAMIENTO ANALÓGICO CON AMPLIFICADOR VIRTUAL Y GABINETE (IR)
            amp_applied_id = None
            cab_applied_id = None
            amp_cfg = tcfg.get("amp")
            if not amp_cfg and amp_configs:
                if inst_id in amp_configs:
                    amp_cfg = amp_configs[inst_id]
                elif (inst["family"] == "Guitarras" or "guitarra" in inst_id) and ("guitar" in amp_configs or "guitarra" in amp_configs):
                    amp_cfg = amp_configs.get("guitar") or amp_configs.get("guitarra")
                elif (inst["family"] == "Bajos" or "bajo" in inst_id or "bass" in inst_id) and ("bass" in amp_configs or "bajo" in amp_configs):
                    amp_cfg = amp_configs.get("bass") or amp_configs.get("bajo")

            if amp_cfg and not amp_cfg.get("bypass", False) and amp_cfg.get("enabled", True):
                try:
                    import virtual_amp_engine
                    inst_buf = virtual_amp_engine.process_audio_through_amplifier(inst_buf, amp_cfg)
                    amp_applied_id = amp_cfg.get("amp_id") or amp_cfg.get("id")
                    cab_applied_id = amp_cfg.get("cabinet_id")
                except Exception as e:
                    print(f"[AMP DSP ERROR] Fallo al procesar {inst_id} con amplificador: {e}")

            master_mix += inst_buf * vol
            total_synth_ms += inst_ms

            rendered_tracks_meta.append({
                "id": inst_id,
                "num": inst["num"],
                "name": inst["name"],
                "short_name": inst["short_name"],
                "family": inst["family"],
                "volume": round(vol, 2),
                "volume_pct": int(round(vol * 100)),
                "bank_name": inst["bank_name"],
                "license": inst["license"],
                "attribution": inst["attribution"],
                "synth_ms": round(inst_ms, 1),
                "peak_ram_mb": round(inst_peak_ram, 2),
                "amp_applied": amp_applied_id,
                "cabinet_applied": cab_applied_id,
            })

        # Fade-out suave en los últimos 0.35s para evitar clics al final
        fade_frames = min(int(0.35 * SAMPLE_RATE), len(master_mix) // 4)
        if fade_frames > 0:
            fade = np.linspace(1.0, 0.0, fade_frames, dtype=np.float32)[:, None]
            master_mix[-fade_frames:] *= fade

        peak = float(np.max(np.abs(master_mix))) if len(master_mix) else 1.0
        if peak > 1e-4:
            master_mix = master_mix * (29200.0 / peak)
        pcm16 = np.clip(master_mix, -32767.0, 32767.0).astype(np.int16)
        rms_db = round(20.0 * math.log10(max(1e-7, float(np.sqrt(np.mean((pcm16.astype(np.float32) / 32768.0) ** 2))))), 2)

        master_wav = output_wav_path or os.path.join(tmp_dir, "master_norm.wav")
        os.makedirs(os.path.dirname(os.path.abspath(output_mp3_path)), exist_ok=True)
        with wave.open(master_wav, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm16.tobytes())

        ff_bin = get_ffmpeg_binary()
        subprocess.run(
            [ff_bin, "-y", "-v", "error", "-i", master_wav, "-b:a", "192k", output_mp3_path],
            check=True,
        )

        if output_flac_path:
            subprocess.run(
                [ff_bin, "-y", "-v", "error", "-i", master_wav, "-c:a", "flac", output_flac_path],
                check=True,
            )

    process_rss_mb = 0.0
    if psutil is not None:
        try:
            process_rss_mb = round(psutil.Process(os.getpid()).memory_info().rss / 1048576.0, 2)
        except Exception:
            pass

    actual_duration_sec = round(len(pcm16) / SAMPLE_RATE, 2)
    return {
        "status": "ok",
        "zero_cost": True,
        "paid_api_calls": 0,
        "bpm": bpm,
        "musical_key": musical_key,
        "progression_style": progression_style,
        "progression_name": PROGRESSION_STYLES.get(progression_style, PROGRESSION_STYLES["alabanza_juvenil"])["name"],
        "bars": bars,
        "expected_musical_sec": round(expected_musical_sec, 2),
        "duration_sec": actual_duration_sec,
        "rms_dbfs": rms_db,
        "tracks_count": len(rendered_tracks_meta),
        "tracks": rendered_tracks_meta,
        "total_synth_ms": round(total_synth_ms, 1),
        "peak_child_ram_mb": round(max_child_ram_mb, 2),
        "process_rss_mb": process_rss_mb,
        "estimated_combined_ram_mb": round(process_rss_mb + max_child_ram_mb, 2),
        "render_512mb_safe": (process_rss_mb + max_child_ram_mb) < 420.0,
        "licenses_used": list(licenses_map.values()),
        "amp_configs_applied": amp_configs,
        "prompt": prompt,
        "lyrics": lyrics,
    }


# ==============================================================================
# ANÁLISIS MUSICAL AVANZADO DE CANCIONES (TIEMPO, TONALIDAD Y ARMONÍA REAL)
# ==============================================================================

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Perfiles de Krumhansl-Schmuckler para detección de tonalidad
KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88], dtype=np.float32)
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17], dtype=np.float32)

CHORD_TEMPLATES_24: Dict[str, Tuple[int, List[int], List[int], np.ndarray]] = {}
for root in range(12):
    # Tríada Mayor
    maj = np.zeros(12, dtype=np.float32)
    maj[root] = 1.0; maj[(root + 4) % 12] = 0.8; maj[(root + 7) % 12] = 0.9
    CHORD_TEMPLATES_24[PITCH_NAMES[root]] = (root, [0, 4, 7], [0, 4, 7, 12], maj / np.linalg.norm(maj))

    # Tríada Menor
    min_t = np.zeros(12, dtype=np.float32)
    min_t[root] = 1.0; min_t[(root + 3) % 12] = 0.8; min_t[(root + 7) % 12] = 0.9
    CHORD_TEMPLATES_24[f"{PITCH_NAMES[root]}m"] = (root, [0, 3, 7], [0, 3, 7, 12], min_t / np.linalg.norm(min_t))


def analyze_audio_track(
    audio_path: str,
    hint_bpm: Optional[int] = None,
    hint_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analiza una pista de audio real extrayendo con precisión matemática:
    - Duración exacta en segundos y número de muestras a 44.1 kHz.
    - BPM detectado mediante análisis de energía espectral y autocorrelación.
    - Métrica y cantidad exacta de compases (bars) necesarios para cubrir el 100% de la canción.
    - Tonalidad global (perfil Krumhansl-Schmuckler sobre cromagrama de 12 notas).
    - Línea de tiempo armónica compás por compás con nombres de acordes, fundamentales y confianza.
    """
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 100:
        raise FileNotFoundError(f"Archivo de audio no encontrado: {audio_path}")

    ff_bin = get_ffmpeg_binary()
    sr_analysis = 22050

    # 1. Decodificar audio mono a 22050 Hz en memoria vía FFmpeg
    cmd_mono = [
        ff_bin, "-y", "-i", audio_path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "1", "-ar", str(sr_analysis), "-"
    ]
    proc = subprocess.Popen(cmd_mono, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw_mono, _ = proc.communicate()
    if not raw_mono or len(raw_mono) < 1024:
        raise ValueError("No se pudo decodificar la señal de audio para análisis.")

    samples_mono = np.frombuffer(raw_mono, dtype=np.float32)
    duration_sec = float(len(samples_mono)) / float(sr_analysis)

    # 2. Análisis de tempo (BPM)
    hop = 512
    f_spec, t_spec, spec = scipy.signal.spectrogram(samples_mono, fs=sr_analysis, nperseg=1024, noverlap=512)
    diff = np.diff(spec, axis=1)
    pos_diff = np.maximum(0, diff)
    onset_env = np.sum(pos_diff, axis=0)

    # Autocorrelación sobre envolvente de transitorios
    corr = np.correlate(onset_env, onset_env, mode='full')
    corr = corr[len(corr) // 2:]

    # Búsqueda en rango 50 a 195 BPM
    min_lag = int((60.0 / 195.0) * (sr_analysis / hop))
    max_lag = int((60.0 / 50.0) * (sr_analysis / hop))
    min_lag = max(1, min_lag)
    max_lag = min(len(corr) - 1, max_lag)

    valid_corr = corr[min_lag:max_lag]
    best_lag = min_lag + int(np.argmax(valid_corr))
    detected_bpm = float((60.0 * sr_analysis) / (best_lag * hop))

    final_bpm = int(round(detected_bpm))

    # Si el usuario o Udio envió un hint_bpm, verificar si es armónico/cercano (ej. 76 vs 78 o doble tempo)
    if hint_bpm and 40 <= hint_bpm <= 220:
        ratio = detected_bpm / float(hint_bpm)
        if 0.92 <= ratio <= 1.08:
            final_bpm = hint_bpm
        elif 1.85 <= ratio <= 2.15:
            final_bpm = hint_bpm
        elif 0.45 <= ratio <= 0.55:
            final_bpm = hint_bpm

    sec_per_beat = 60.0 / float(final_bpm)
    sec_per_bar = sec_per_beat * 4.0
    total_bars = int(math.ceil(duration_sec / sec_per_bar))

    # 3. Cromagrama armónico global y tonalidad (Krumhansl-Schmuckler)
    valid_freq_idx = np.where((f_spec >= 65.0) & (f_spec <= 1100.0))[0]
    global_chroma = np.zeros(12, dtype=np.float32)
    for vi in valid_freq_idx:
        fr = f_spec[vi]
        if fr <= 0:
            continue
        midi_n = int(round(12.0 * np.log2(fr / 440.0) + 69.0))
        global_chroma[midi_n % 12] += np.sum(spec[vi, :])

    norm_g = np.linalg.norm(global_chroma)
    if norm_g > 1e-6:
        global_chroma /= norm_g

    best_key_score = -999.0
    detected_key = "G"
    detected_mode = "Major"
    detected_root = "G"

    for root in range(12):
        rot_c = np.roll(global_chroma, -root)
        score_maj = float(np.corrcoef(rot_c, KRUMHANSL_MAJOR)[0, 1])
        if score_maj > best_key_score:
            best_key_score = score_maj
            detected_key = f"{PITCH_NAMES[root]}"
            detected_mode = "Major"
            detected_root = PITCH_NAMES[root]

        score_min = float(np.corrcoef(rot_c, KRUMHANSL_MINOR)[0, 1])
        if score_min > best_key_score:
            best_key_score = score_min
            detected_key = f"{PITCH_NAMES[root]}m"
            detected_mode = "Minor"
            detected_root = PITCH_NAMES[root]

    # 4. Línea de tiempo armónica compás por compás
    chords_timeline: List[Dict[str, Any]] = []
    last_known_chord = detected_key if detected_key in CHORD_TEMPLATES_24 else "G"

    for b in range(total_bars):
        t0 = b * sec_per_bar
        t1 = min(duration_sec, (b + 1) * sec_per_bar)
        idx0 = int(t0 * sr_analysis)
        idx1 = int(t1 * sr_analysis)
        bar_s = samples_mono[idx0:idx1]

        if len(bar_s) < 512:
            tpl = CHORD_TEMPLATES_24.get(last_known_chord, CHORD_TEMPLATES_24["G"])
            chords_timeline.append({
                "bar": b + 1,
                "start_sec": round(t0, 2),
                "end_sec": round(t1, 2),
                "chord": last_known_chord,
                "root_offset": tpl[0],
                "intervals": tpl[1],
                "mel": tpl[2],
                "confidence": 0.50,
            })
            continue

        fb, tb, spec_b = scipy.signal.spectrogram(bar_s, fs=sr_analysis, nperseg=1024, noverlap=512)
        v_idx = np.where((fb >= 65.0) & (fb <= 950.0))[0]
        bar_c = np.zeros(12, dtype=np.float32)
        for vi in v_idx:
            fr = fb[vi]
            if fr <= 0:
                continue
            midi_n = int(round(12.0 * np.log2(fr / 440.0) + 69.0))
            bar_c[midi_n % 12] += np.sum(spec_b[vi, :])

        norm_b = np.linalg.norm(bar_c)
        if norm_b > 1e-6:
            bar_c /= norm_b
            best_cname = last_known_chord
            best_sim = -1.0
            best_tuple = CHORD_TEMPLATES_24.get(last_known_chord, CHORD_TEMPLATES_24["G"])
            for cname, cinfo in CHORD_TEMPLATES_24.items():
                sim = float(np.dot(bar_c, cinfo[3]))
                if sim > best_sim:
                    best_sim = sim
                    best_cname = cname
                    best_tuple = cinfo

            last_known_chord = best_cname
            chords_timeline.append({
                "bar": b + 1,
                "start_sec": round(t0, 2),
                "end_sec": round(t1, 2),
                "chord": best_cname,
                "root_offset": best_tuple[0],
                "intervals": best_tuple[1],
                "mel": best_tuple[2],
                "confidence": round(best_sim, 2),
            })
        else:
            tpl = CHORD_TEMPLATES_24.get(last_known_chord, CHORD_TEMPLATES_24["G"])
            chords_timeline.append({
                "bar": b + 1,
                "start_sec": round(t0, 2),
                "end_sec": round(t1, 2),
                "chord": last_known_chord,
                "root_offset": tpl[0],
                "intervals": tpl[1],
                "mel": tpl[2],
                "confidence": 0.50,
            })

    chord_sequence_summary = " - ".join(chords_timeline[i]["chord"] for i in range(min(16, len(chords_timeline))))
    if len(chords_timeline) > 16:
        chord_sequence_summary += " ..."

    return {
        "status": "ok",
        "audio_path": audio_path,
        "duration_sec": round(duration_sec, 2),
        "bpm": final_bpm,
        "meter": "4/4",
        "total_bars": total_bars,
        "key": {
            "name": f"{detected_root} {detected_mode}",
            "root": detected_root,
            "mode": detected_mode,
            "display": detected_key,
            "confidence": round(best_key_score, 2),
        },
        "chord_summary": chord_sequence_summary,
        "chords_timeline": chords_timeline,
    }


def enrich_song_with_sf2_overdub(
    original_audio_path: str,
    tracks_config: List[Dict[str, Any]],
    output_mp3_path: str,
    output_wav_path: Optional[str] = None,
    output_flac_path: Optional[str] = None,
    hint_bpm: Optional[int] = None,
    hint_key: Optional[str] = None,
    original_volume: float = 0.95,
    accompaniment_volume: float = 0.75,
    amp_configs: Optional[Dict[str, Any]] = None,
    custom_chords: Optional[List[Dict[str, Any]]] = None,
    hihat_mode: str = "8th",
    tom_grooves: bool = True,
    crash_toms: bool = True,
    bass_pickup: bool = True,
    preview_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Integra de forma no destructiva los 20 instrumentos gratuitos SoundFont2 sobre
    una canción existente de Udio, conservando al 100% voz, melodía, duración exacta y estructura.
    """
    if not os.path.exists(original_audio_path):
        raise FileNotFoundError(f"Canción original no encontrada: {original_audio_path}")

    # 1. Análisis musical completo de la pista original
    analysis = analyze_audio_track(original_audio_path, hint_bpm=hint_bpm, hint_key=hint_key)
    exact_duration_sec = analysis["duration_sec"]
    bpm = analysis["bpm"]
    detected_key = analysis["key"]["root"]
    chords_timeline = list(custom_chords) if custom_chords else list(analysis["chords_timeline"])

    # Si se solicita modo preescucha rápida (ej: 25-30s), acotar duración y compases
    is_preview = False
    if preview_seconds and float(preview_seconds) > 0 and float(preview_seconds) < exact_duration_sec:
        is_preview = True
        exact_duration_sec = float(preview_seconds)
        bar_dur = (60.0 / bpm) * 4.0
        max_bars = max(2, int(math.ceil(exact_duration_sec / bar_dur)))
        chords_timeline = chords_timeline[:max_bars]

    ff_bin = get_ffmpeg_binary()

    # 2. Cargar audio original en estéreo a 44100 Hz float32 (acotado si es preescucha)
    cmd_orig_stereo = [
        ff_bin, "-y"
    ]
    if is_preview:
        cmd_orig_stereo.extend(["-t", str(exact_duration_sec)])
    cmd_orig_stereo.extend([
        "-i", original_audio_path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "2", "-ar", "44100", "-"
    ])
    p_orig = subprocess.Popen(cmd_orig_stereo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw_orig, _ = p_orig.communicate()
    if not raw_orig or len(raw_orig) < 1024:
        raise ValueError("Error al cargar la señal de audio original para sobregrabación.")

    orig_samples = np.frombuffer(raw_orig, dtype=np.float32).reshape(-1, 2)
    num_orig_frames = len(orig_samples)

    # 3. Sintetizar las pistas de acompañamiento a longitud completa exacta
    with tempfile.TemporaryDirectory(prefix="rodrix_enrich_") as tmp_enrich_dir:
        synth_mp3_temp = os.path.join(tmp_enrich_dir, "accompaniment_temp.mp3")
        synth_wav_temp = os.path.join(tmp_enrich_dir, "accompaniment_temp.wav")

        synth_res = synthesize_multitrack_composition(
            tracks_config=tracks_config,
            output_mp3_path=synth_mp3_temp,
            output_wav_path=synth_wav_temp,
            bpm=bpm,
            musical_key=detected_key,
            progression_style="alabanza_juvenil",
            bars=len(chords_timeline),
            hihat_mode=hihat_mode,
            tom_grooves=tom_grooves,
            crash_toms=crash_toms,
            bass_pickup=bass_pickup,
            amp_configs=amp_configs,
            custom_chords_timeline=chords_timeline,
            target_duration_sec=exact_duration_sec,
        )

        # 4. Decodificar acompañamiento sintetizado estéreo a 44100 Hz
        cmd_acc_stereo = [
            ff_bin, "-y", "-i", synth_wav_temp,
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ac", "2", "-ar", "44100", "-"
        ]
        p_acc = subprocess.Popen(cmd_acc_stereo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_acc, _ = p_acc.communicate()
        acc_samples = np.frombuffer(raw_acc, dtype=np.float32).reshape(-1, 2)

        # 5. Alinear muestras exactamente con el audio original (recorte o pad)
        acc_aligned = np.zeros_like(orig_samples)
        copy_len = min(num_orig_frames, len(acc_samples))
        acc_aligned[:copy_len] = acc_samples[:copy_len]

        # 6. Mezcla estéreo digital: Original * orig_vol + Acompañamiento * acc_vol
        orig_vol_clamped = max(0.1, min(1.5, float(original_volume)))
        acc_vol_clamped = max(0.1, min(1.5, float(accompaniment_volume)))
        final_mix = (orig_samples * orig_vol_clamped) + (acc_aligned * acc_vol_clamped)

        # 7. Limitador transparente suave (-0.3 dBFS)
        peak_amp = float(np.max(np.abs(final_mix)))
        ceiling = 10.0 ** (-0.3 / 20.0)  # ~0.966
        attenuation_factor = 1.0
        if peak_amp > ceiling:
            attenuation_factor = ceiling / peak_amp
            final_mix = final_mix * attenuation_factor

        # 8. Exportar a MP3 (320 kbps)
        os.makedirs(os.path.dirname(os.path.abspath(output_mp3_path)), exist_ok=True)
        cmd_out_mp3 = [
            ff_bin, "-y",
            "-f", "f32le", "-ar", "44100", "-ac", "2", "-i", "-",
            "-b:a", "320k",
            output_mp3_path
        ]
        p_out = subprocess.Popen(cmd_out_mp3, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p_out.communicate(input=final_mix.tobytes())

        # Opcional: WAV y FLAC
        if output_wav_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
            cmd_out_wav = [
                ff_bin, "-y",
                "-f", "f32le", "-ar", "44100", "-ac", "2", "-i", "-",
                output_wav_path
            ]
            p_wav = subprocess.Popen(cmd_out_wav, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p_wav.communicate(input=final_mix.tobytes())

        if output_flac_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_flac_path)), exist_ok=True)
            cmd_out_flac = [
                ff_bin, "-y",
                "-f", "f32le", "-ar", "44100", "-ac", "2", "-i", "-",
                output_flac_path
            ]
            p_flac = subprocess.Popen(cmd_out_flac, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p_flac.communicate(input=final_mix.tobytes())

    actual_duration = round(num_orig_frames / 44100.0, 2)
    peak_db = round(20.0 * math.log10(max(1e-6, peak_amp * attenuation_factor)), 2)

    return {
        "status": "ok",
        "zero_cost": True,
        "original_audio_path": original_audio_path,
        "output_mp3_path": output_mp3_path,
        "duration_sec": actual_duration,
        "original_duration_sec": exact_duration_sec,
        "duration_diff_sec": round(abs(actual_duration - exact_duration_sec), 4),
        "bpm": bpm,
        "key": analysis["key"],
        "chord_summary": analysis["chord_summary"],
        "chords_timeline": analysis["chords_timeline"],
        "total_bars": analysis["total_bars"],
        "tracks_rendered": synth_res.get("tracks", []),
        "peak_dbfs": peak_db,
        "limiter_applied": peak_amp > ceiling,
        "attenuation_factor": round(attenuation_factor, 3),
        "licenses_used": synth_res.get("licenses_used", []),
        "amp_configs_applied": amp_configs,
    }


def get_catalog_payload() -> Dict[str, Any]:
    """Devuelve el catálogo completo de los 20 instrumentos gratuitos, estilos, tonalidades y licencias."""
    fs_bin = get_fluidsynth_binary()
    ff_bin = get_ffmpeg_binary()
    return {
        "status": "ok",
        "zero_cost": True,
        "engine": "FluidSynth 2.6+ Sequential Low-RAM Synthesizer",
        "fluidsynth_available": bool(shutil.which(fs_bin) or os.path.exists(fs_bin)),
        "ffmpeg_available": bool(shutil.which(ff_bin) or os.path.exists(ff_bin)),
        "total_instruments": 20,
        "total_variants": len(FREE_INSTRUMENTS_CATALOG),
        "instruments": FREE_INSTRUMENTS_CATALOG,
        "progression_styles": [
            {"id": k, "name": v["name"], "default_bpm": v["default_bpm"], "default_key": v["default_key"]}
            for k, v in PROGRESSION_STYLES.items()
        ],
        "musical_keys": [
            {"id": "C", "name": "Do Mayor (C)"},
            {"id": "D", "name": "Re Mayor (D)"},
            {"id": "E", "name": "Mi Mayor (E)"},
            {"id": "F", "name": "Fa Mayor (F)"},
            {"id": "G", "name": "Sol Mayor (G)"},
            {"id": "A", "name": "La Mayor (A)"},
            {"id": "B", "name": "Si Mayor (B)"},
            {"id": "Am", "name": "La menor (Am)"},
            {"id": "Em", "name": "Mi menor (Em)"},
            {"id": "Bm", "name": "Si menor (Bm)"},
            {"id": "F#m", "name": "Fa# menor (F#m)"},
            {"id": "Dm", "name": "Re menor (Dm)"},
        ],
        "soundfont_banks": list(SF2_BANKS_METADATA.values()),
    }
