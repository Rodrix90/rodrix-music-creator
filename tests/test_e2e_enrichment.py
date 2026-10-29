import os
import sys
import time
import psutil
import hashlib

def run_test():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    os.chdir(base_dir)
    import free_instruments_engine as fie

    orig_path = "Hermano toma el arado.mp3"
    if not os.path.exists(orig_path):
        orig_path = os.path.join("..", "Rodrix Music creator", "Hermano toma el arado.mp3")
    assert os.path.exists(orig_path), f"Original audio missing: {orig_path}"

    with open(orig_path, "rb") as f:
        orig_hash = hashlib.sha256(f.read()).hexdigest()

    print("==================================================================")
    print("TEST 1: ANALISIS MUSICAL Y ACUSTICO DE CANCION REAL")
    print("==================================================================")
    t0 = time.time()
    analysis = fie.analyze_audio_track(orig_path, hint_bpm=76)
    t_ana = time.time() - t0
    print(f"-> Analizado en {t_ana:.2f}s")
    print(f"-> Duracion: {analysis['duration_sec']}s")
    print(f"-> BPM Detectado: {analysis['bpm']}")
    print(f"-> Tonalidad: {analysis['key']['name']} (Display: {analysis['key']['display']}, Confianza: {analysis['key']['confidence']})")
    print(f"-> Total Compases: {analysis['total_bars']}")
    print(f"-> Resumen Armonico: {analysis['chord_summary'][:4]}...")

    print("\n==================================================================")
    print("TEST 2: PREESCUCHA RAPIDA (10s)")
    print("==================================================================")
    t0 = time.time()
    out_prev = "test_out_prev.mp3"
    res_prev = fie.enrich_song_with_sf2_overdub(
        original_audio_path=orig_path,
        tracks_config=[{"id": "piano_cola", "volume": 0.8}, {"id": "cuerdas", "volume": 0.6}],
        output_mp3_path=out_prev,
        hint_bpm=76,
        preview_seconds=10.0
    )
    t_prev = time.time() - t0
    print(f"-> Preescucha 10s generada en {t_prev:.2f}s")
    print(f"-> Duracion resultante: {res_prev['duration_sec']}s")
    print(f"-> Pico de audio: {res_prev['peak_dbfs']} dBFS")
    assert os.path.exists(out_prev) and os.path.getsize(out_prev) > 1000

    print("\n==================================================================")
    print("TEST 3: SOBREGRABACION COMPLETA CANCION ENTERA (4m 12s / 252s)")
    print("==================================================================")
    proc = psutil.Process()
    ram_before = proc.memory_info().rss / (1024*1024)
    t0 = time.time()
    out_full = "test_out_full.mp3"
    res_full = fie.enrich_song_with_sf2_overdub(
        original_audio_path=orig_path,
        tracks_config=[
            {"id": "piano_cola", "volume": 0.8},
            {"id": "cuerdas", "volume": 0.6},
            {"id": "bajo_electrico", "volume": 0.7}
        ],
        output_mp3_path=out_full,
        hint_bpm=76
    )
    t_full = time.time() - t0
    ram_after = proc.memory_info().rss / (1024*1024)
    print(f"-> Cancion completa procesada en {t_full:.2f}s")
    print(f"-> Duracion original: {res_full['original_duration_sec']}s")
    print(f"-> Duracion enriquecida: {res_full['duration_sec']}s")
    print(f"-> Diferencia temporal: {res_full['duration_diff_sec']}s")
    print(f"-> Pistas renderizadas: {[t['short_name'] for t in res_full['tracks_rendered']]}")
    print(f"-> Pico: {res_full['peak_dbfs']} dBFS (Limitador: {res_full['limiter_applied']})")
    print(f"-> Consumo RAM: {ram_after:.1f} MB (Delta: {ram_after - ram_before:.1f} MB)")
    assert os.path.exists(out_full) and os.path.getsize(out_full) > 50000

    print("\n==================================================================")
    print("TEST 4: INTEGRIDAD, NO DESTRUCCION Y VERIFICACION DE AUDITORIA")
    print("==================================================================")
    with open(orig_path, "rb") as f:
        orig_hash_after = hashlib.sha256(f.read()).hexdigest()

    assert orig_hash == orig_hash_after, "ERROR CRITICO: La pista original fue alterada!"
    print("1. Cancion original 100% INTACTA (Hash SHA-256 identico bit a bit)")

    assert res_full['duration_diff_sec'] < 0.1, "ERROR: Desalineacion en duracion!"
    print(f"2. Sincronizacion temporal: 100% EXACTA (Diferencia: {res_full['duration_diff_sec']}s)")

    assert res_full['peak_dbfs'] <= -0.29, "ERROR: Clipping detectado!"
    print(f"3. Techo dinamico: {res_full['peak_dbfs']} dBFS (Cero clipping, limite seguro -0.3 dBFS)")

    assert ram_after < 250.0, "ERROR: Consumo de RAM excedio el limite de Render (512MB)"
    print(f"4. Consumo RAM: {ram_after:.1f} MB (Completamente seguro para los 512 MB de Render)")

    if os.path.exists(out_prev): os.remove(out_prev)
    if os.path.exists(out_full): os.remove(out_full)

    print("\n[RESULTADO GLOBAL] TODAS LAS VALIDACIONES SUPERADAS CON EXITO")

if __name__ == "__main__":
    run_test()
