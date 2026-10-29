import urllib.request
import json
import time
import os
import hashlib

def run_tests():
    # Test 1: Balada acústica en Re menor (74 BPM, balada_menor, 8 compases)
    payload1 = {
        'title': 'Balada Acústica en Re menor',
        'prompt': 'Balada acústica emotiva en Re menor a 74 bpm con guitarra acústica, piano de cola y bajo',
        'lyrics': 'En la calma de la noche busco tu paz...',
        'tracks': [
            {'id': 'piano_cola', 'volume': 1.0},
            {'id': 'guitarra_acustica', 'volume': 1.1},
            {'id': 'bajo_finger', 'volume': 0.95}
        ],
        'bars': 8
    }

    print('=== GENERACIÓN 1: Balada en Re menor ===')
    t0 = time.time()
    req1 = urllib.request.Request(
        'http://127.0.0.1:8000/api/free-instruments/generate', 
        data=json.dumps(payload1).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req1) as r1:
        res1 = json.loads(r1.read().decode('utf-8'))
    dt1 = time.time() - t0

    track1 = res1['track']
    print(f"Generado en {dt1:.2f}s")
    print(f"Track ID 1: {track1['id']}")
    print(f"Title 1: {track1['title']}")
    print(f"BPM 1: {track1['bpm']}")
    print(f"Key 1: {track1['musical_key']}")
    print(f"Estilo 1: {track1['progression_style']}")
    print(f"Duración 1: {track1['duration']}s")
    print(f"Audio URL 1: {track1['audio_url']}")
    print(f"RMS dBFS 1: {res1['synthesis_metrics']['rms_dbfs']} dBFS")

    # Descargar audio 1 para chequear hash y datos
    with urllib.request.urlopen('http://127.0.0.1:8000' + track1['audio_url']) as a1:
        data1 = a1.read()
    hash1 = hashlib.sha256(data1).hexdigest()
    print(f"Audio 1 Size: {len(data1)} bytes | SHA256: {hash1[:16]}...")

    # Test 2: Coro Pentecostal rápido en Sol mayor (135 BPM, 16 compases)
    payload2 = {
        'title': 'Coro Pentecostal de Júbilo',
        'prompt': 'Coro pentecostal rápido de júbilo en Sol mayor dos pasos 135 bpm con batería acústica, bajo slap, guitarra limpia y órgano',
        'lyrics': 'Alaba a Dios con gozo y poder...',
        'tracks': [
            {'id': 'bateria_acustica', 'volume': 1.05},
            {'id': 'bajo_slap', 'volume': 1.0},
            {'id': 'guitarra_limpia', 'volume': 0.9},
            {'id': 'organo', 'volume': 0.95}
        ],
        'bars': 16
    }

    print('\n=== GENERACIÓN 2: Coro Pentecostal 135 BPM ===')
    t0 = time.time()
    req2 = urllib.request.Request(
        'http://127.0.0.1:8000/api/free-instruments/generate', 
        data=json.dumps(payload2).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req2) as r2:
        res2 = json.loads(r2.read().decode('utf-8'))
    dt2 = time.time() - t0

    track2 = res2['track']
    print(f"Generado en {dt2:.2f}s")
    print(f"Track ID 2: {track2['id']}")
    print(f"Title 2: {track2['title']}")
    print(f"BPM 2: {track2['bpm']}")
    print(f"Key 2: {track2['musical_key']}")
    print(f"Estilo 2: {track2['progression_style']}")
    print(f"Duración 2: {track2['duration']}s")
    print(f"Audio URL 2: {track2['audio_url']}")
    print(f"RMS dBFS 2: {res2['synthesis_metrics']['rms_dbfs']} dBFS")

    # Descargar audio 2 para chequear hash y datos
    with urllib.request.urlopen('http://127.0.0.1:8000' + track2['audio_url']) as a2:
        data2 = a2.read()
    hash2 = hashlib.sha256(data2).hexdigest()
    print(f"Audio 2 Size: {len(data2)} bytes | SHA256: {hash2[:16]}...")

    # Verificaciones rigurosas
    assert track1['id'] != track2['id'], 'ERROR: IDs deben ser diferentes'
    assert hash1 != hash2, 'ERROR: Audios deben tener hashes SHA256 diferentes'
    assert track1['bpm'] == 74, f"ERROR: BPM esperado 74, obtenido {track1['bpm']}"
    assert track2['bpm'] == 135, f"ERROR: BPM esperado 135, obtenido {track2['bpm']}"
    assert track1['musical_key'] == 'Dm', f"ERROR: Key 1 esperado Dm, obtenido {track1['musical_key']}"
    assert track2['musical_key'] == 'G', f"ERROR: Key 2 esperado G, obtenido {track2['musical_key']}"
    assert track1['progression_style'] == 'balada_menor', f"ERROR: Estilo 1 {track1['progression_style']}"
    assert track2['progression_style'] == 'gospel_dos_pasos', f"ERROR: Estilo 2 {track2['progression_style']}"
    assert track1['duration'] != track2['duration'], 'ERROR: Duraciones deben ser diferentes'
    assert len(data1) > 50000, 'ERROR: Audio 1 demasiado pequeño o vacío'
    assert len(data2) > 50000, 'ERROR: Audio 2 demasiado pequeño o vacío'
    assert res1['synthesis_metrics']['rms_dbfs'] > -45.0, 'ERROR: Audio 1 es silencio'
    assert res2['synthesis_metrics']['rms_dbfs'] > -45.0, 'ERROR: Audio 2 es silencio'

    print('\n[RESULTADO VERIFICACIONES] ¡TODAS LAS VALIDACIONES OBLIGATORIAS SUPERADAS CON ÉXITO!')

if __name__ == '__main__':
    run_tests()
