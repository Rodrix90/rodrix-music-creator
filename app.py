import os
import re
import gc
import hmac
import hashlib
import httpx
import asyncio
import uuid
import tempfile
import subprocess
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, PlainTextResponse
import json
import datetime
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

from fastapi.staticfiles import StaticFiles

# Load environment variables
load_dotenv()

app = FastAPI(title="Rodrix Music Creator - Udio Engine", version="3.0")

assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UDIO_API_KEY = os.environ.get("UDIO_API_KEY", "sk-e6c60cad69b44514b66651740a2c5885")
SECRET_KEY = os.environ.get("SECRET_KEY", "default_secret_key_12345").encode('utf-8')

# Middleware de sesión para Authlib / Starlette
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY.decode('utf-8'))

# Instanciar OAuth globalmente
oauth = OAuth()

@app.on_event("startup")
async def startup_event():
    # Registrar el cliente de Google usando tu ID REAL inyectado directamente
    oauth.register(
        name='google',
        client_id="813430947107-3aa7i4809aj47jpm0okp92me855l1tt0.apps.googleusercontent.com",
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

def get_current_user(request: Request):
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    email = user.get('email', '')
    # Whitelist estricta en las llamadas del backend para proteger tus créditos de Udio
    if email != "rodryandy@gmail.com":
        raise HTTPException(status_code=403, detail="Tu correo no está en la lista blanca.")
    
    return email

def obfuscate_lyrics(text: str) -> str:
    if not text:
        return text
    processed_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if (stripped.startswith('[') and stripped.endswith(']')) or (stripped.startswith('(') and stripped.endswith(')')):
            processed_lines.append(line)
            continue
            
        obfuscated = ""
        for char in line:
            obfuscated += char + '\u200E'
        processed_lines.append(obfuscated)
        
    return "\n".join(processed_lines)

async def upload_to_catbox_async(file_path: str) -> str | None:
    url = "https://catbox.moe/user/api.php"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, 'rb') as f:
                data = {'reqtype': 'fileupload'}
                files = {'fileToUpload': f}
                response = await client.post(url, data=data, files=files)
            if response.status_code == 200:
                uploaded_url = response.text.strip()
                if uploaded_url.startswith("http"):
                    return uploaded_url
    except Exception as e:
        print("Error subiendo a Catbox:", e)
    return None

async def upload_to_uguu_async(file_path: str) -> str | None:
    url = "https://uguu.se/upload.php"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, 'rb') as f:
                files = {'files[]': f}
                response = await client.post(url, files=files)
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get("success") and resp_json.get("files"):
                    return resp_json["files"][0]["url"]
    except Exception as e:
        print("Error subiendo a Uguu:", e)
    return None

def bypass_audio_fingerprint(input_path: str, output_path: str) -> str:
    ffmpeg_cmd = [
        "ffmpeg",
        "-threads", "1",
        "-y",
        "-i", input_path,
        "-vn",
        "-t", "120",
        "-map_metadata", "-1",
        "-af", "aformat=channel_layouts=mono,asetrate=44100*1.12,aresample=44100,atempo=0.892,flanger=delay=7:depth=7:regen=20:width=80:speed=2,vibrato=f=4.0:d=0.4,compand=attacks=0:points=-80/-80|-15/-15|0/-15|20/-15",
        output_path
    ]
    try:
        process = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, timeout=300)
        return "SUCCESS"
    except FileNotFoundError:
        return "ERROR: FFmpeg no está instalado o no está en el PATH del sistema."
    except subprocess.CalledProcessError as e:
        return f"ERROR FFmpeg: {e.stderr}"
    except Exception as e:
        return f"ERROR inesperado: {str(e)}"

# Funciones de persistencia para la librería
LIBRARY_FILE = "library.json"

def load_library():
    if os.path.exists(LIBRARY_FILE):
        try:
            with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_library(library_data):
    try:
        with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
            json.dump(library_data, f, indent=4)
    except Exception as e:
        print("Error guardando librería:", e)

def log_conversion(payload, response_status, error_msg=None, tracks=None):
    os.makedirs("logs", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_id = str(uuid.uuid4())[:8]
    log_filename = f"logs/conversion_{timestamp}_{log_id}.txt"
    
    with open(log_filename, "w", encoding="utf-8") as f:
        f.write(f"--- LOG DE CONVERSIÓN ---\n")
        f.write(f"Fecha/Hora: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Status: {response_status}\n\n")
        f.write("--- PAYLOAD ENVIADO ---\n")
        f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n\n")
        
        if error_msg:
            f.write("--- ERROR ---\n")
            f.write(str(error_msg) + "\n\n")
            
        if tracks:
            f.write("--- TRACKS RECIBIDOS ---\n")
            f.write(json.dumps(tracks, indent=2, ensure_ascii=False) + "\n")

def add_track_to_library(track_info):
    library = load_library()
    if not any(t.get("id") == track_info.get("id") for t in library):
        library.append(track_info)
        save_library(library)

TASKS = {}

def prune_tasks():
    global TASKS
    if len(TASKS) > 30:
        keys_to_remove = list(TASKS.keys())[:-25]
        for k in keys_to_remove:
            TASKS.pop(k, None)

@app.post("/api/transform")
async def transform_audio(
    background_tasks: BackgroundTasks,
    style: str = Form(...),
    lyrics: str = Form(...),
    title: str = Form(...),
    audio: UploadFile = File(None),
    ignore_audio: bool = Form(False),
    include_lyrics: bool = Form(True),
    bypass_copyright: bool = Form(False),
    exclude_styles: str = Form(""),
    vocal_gender: str = Form("random"),
    weirdness: int = Form(50),
    style_influence: int = Form(50),
    audio_influence: int = Form(25),
    model: str = Form("chirp-v4-5"),
    pronunciation: str = Form(""),
    obfuscate: bool = Form(False),
    current_user: str = Depends(get_current_user)
):
    if not UDIO_API_KEY:
        raise HTTPException(status_code=400, detail="Falta UDIO_API_KEY")

    prune_tasks()

    audio_content = None
    audio_filename = None
    if audio and not ignore_audio:
        audio_content = await audio.read()
        audio_filename = audio.filename

    import uuid
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"status": "IN_PROGRESS", "logs": "", "tracks": [], "detail": ""}

    background_tasks.add_task(
        run_transform_task,
        task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio,
        include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness,
        style_influence, audio_influence, model, pronunciation, obfuscate
    )
    
    return {"status": "started", "task_id": task_id}

@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task no encontrada")
    return TASKS[task_id]

@app.delete("/api/task/{task_id}")
async def cancel_task(task_id: str):
    if task_id in TASKS:
        TASKS[task_id]["status"] = "CANCELLED"
        TASKS[task_id]["detail"] = "Cancelado por el usuario"
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Task no encontrada")

@app.post("/api/process_voiceover")
async def process_voiceover(
    background_tasks: BackgroundTasks,
    voice_audio: UploadFile = File(...),
    title: str = Form("Predicación Pastoral"),
    bg_choice: str = Form("rhodes_pad"),
    custom_bg: UploadFile = File(None),
    bg_volume: float = Form(0.12),
    ducking: bool = Form(True),
    eq_profile: str = Form("clarity"),
    noise_reduction: bool = Form(True),
    leveling: bool = Form(True),
    current_user: str = Depends(get_current_user)
):
    prune_tasks()
    
    voice_bytes = await voice_audio.read()
    voice_filename = voice_audio.filename or "pastor_audio.mp3"
    
    custom_bg_bytes = None
    custom_bg_filename = None
    if custom_bg and bg_choice == "custom":
        custom_bg_bytes = await custom_bg.read()
        custom_bg_filename = custom_bg.filename
        
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"status": "IN_PROGRESS", "logs": "", "tracks": [], "detail": ""}
    
    background_tasks.add_task(
        run_voiceover_task,
        task_id, voice_bytes, voice_filename, title, bg_choice,
        custom_bg_bytes, custom_bg_filename, bg_volume, ducking,
        eq_profile, noise_reduction, leveling
    )
    
    return {"status": "started", "task_id": task_id}

async def run_voiceover_task(
    task_id, voice_bytes, voice_filename, title, bg_choice,
    custom_bg_bytes, custom_bg_filename, bg_volume, ducking,
    eq_profile, noise_reduction, leveling
):
    def log_msg(msg):
        import datetime
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line, flush=True)
        TASKS[task_id]["logs"] += line + "\n"

    temp_files = []
    try:
        log_msg("Iniciando restauración y edición de voz pastoral...")
        ext = os.path.splitext(voice_filename)[1] or ".mp3"
        temp_voice = f"temp_voice_{task_id}{ext}"
        temp_files.append(temp_voice)
        with open(temp_voice, "wb") as f:
            f.write(voice_bytes)
            
        # Get voice duration via ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", temp_voice
        ]
        proc = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            voice_dur = float(proc.stdout.strip())
        except Exception:
            voice_dur = 60.0
        log_msg(f"Audio del pastor detectado: {voice_dur:.1f} segundos.")

        # Build voice processing filter
        v_filters = []
        if noise_reduction:
            log_msg("Aplicando corte de retumbos (85 Hz) y anti-siseo de celular...")
            v_filters.append("highpass=f=85")
            v_filters.append("equalizer=f=360:width_type=o:width=1.5:g=-3.5")
            v_filters.append("lowpass=f=15500")

        if eq_profile == "clarity":
            log_msg("Aplicando ecualización de presencia e inteligibilidad bíblica...")
            v_filters.append("equalizer=f=3400:width_type=o:width=1.2:g=3.2")
            v_filters.append("equalizer=f=10500:width_type=o:width=1.5:g=2.0")
        elif eq_profile == "warm":
            log_msg("Aplicando ecualización cálida y redonda...")
            v_filters.append("equalizer=f=180:width_type=o:width=1.2:g=2.2")
            v_filters.append("equalizer=f=3000:width_type=o:width=1.5:g=1.5")
        elif eq_profile == "gentle":
            log_msg("Aplicando ecualización suave devocional...")
            v_filters.append("equalizer=f=2800:width_type=o:width=1.0:g=1.8")

        if leveling:
            log_msg("Nivelando dinámica de habla (Speech-Norm)...")
            v_filters.append("speechnorm=e=4:r=0.0001:l=1")

        voice_filter_str = ",".join(v_filters) if v_filters else "anull"

        out_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")

        bg_file = None
        if bg_choice in ["rhodes_pad", "strings_intimate", "piano_shimmer"]:
            candidate = f"assets/ambient/{bg_choice}.mp3"
            if os.path.exists(candidate):
                bg_file = candidate
        elif bg_choice == "custom" and custom_bg_bytes:
            bg_ext = os.path.splitext(custom_bg_filename or ".mp3")[1] or ".mp3"
            custom_path = f"temp_bg_{task_id}{bg_ext}"
            temp_files.append(custom_path)
            with open(custom_path, "wb") as f:
                f.write(custom_bg_bytes)
            bg_file = custom_path

        if bg_file and os.path.exists(bg_file):
            log_msg(f"Mezclando música de fondo ambiental muy suave (volumen {int(bg_volume*100)}%)...")
            fade_start = max(0.5, voice_dur - 2.5)
            if ducking:
                log_msg("Activando atenuación inteligente (Auto-Ducking) para ministración...")
                filter_complex = (
                    f"[0:a]{voice_filter_str}[v_clean];"
                    f"[1:a]volume={bg_volume},afade=t=out:st={fade_start}:d=2.5[bg_vol];"
                    f"[bg_vol][v_clean]sidechaincompress=threshold=0.07:ratio=4:attack=50:release=700[bg_ducked];"
                    f"[v_clean][bg_ducked]amix=inputs=2:duration=first:dropout_transition=2[out]"
                )
            else:
                filter_complex = (
                    f"[0:a]{voice_filter_str}[v_clean];"
                    f"[1:a]volume={bg_volume},afade=t=out:st={fade_start}:d=2.5[bg_vol];"
                    f"[v_clean][bg_vol]amix=inputs=2:duration=first:dropout_transition=2[out]"
                )
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", temp_voice,
                "-stream_loop", "-1", "-i", bg_file,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-b:a", "320k",
                out_path
            ]
        else:
            log_msg("Sin música de fondo. Exportando voz restaurada y masterizada...")
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", temp_voice,
                "-af", voice_filter_str,
                "-c:a", "libmp3lame", "-b:a", "320k",
                out_path
            ]

        proc = await asyncio.to_thread(subprocess.run, ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            log_msg(f"ERROR FFmpeg: {proc.stderr[:300]}")
            raise Exception("Error al procesar el audio con FFmpeg.")

        log_msg("¡Predicación procesada y masterizada con éxito!")
        
        track_info = {
            "id": task_id,
            "title": f"🎙️ {title}",
            "audio_url": f"/api/audio_file/{task_id}",
            "raw_audio_url": f"/api/audio_file/{task_id}",
            "image_url": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%2338A169'/%3E%3Ccircle cx='32' cy='24' r='10' fill='%23fff' opacity='0.9'/%3E%3Crect x='30' y='34' width='4' height='14' fill='%23fff'/%3E%3Cpath d='M22 48 L42 48' stroke='%23fff' stroke-width='4' stroke-linecap='round'/%3E%3Cpath d='M18 24 C18 34 46 34 46 24' fill='none' stroke='%23fff' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E",
            "duration": round(voice_dur),
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "tags": ["Voz en Off", "Predicación", "Restauración Vocal"]
        }
        add_track_to_library(track_info)
        TASKS[task_id]["tracks"] = [track_info]
        TASKS[task_id]["status"] = "COMPLETED"

    except Exception as e:
        log_msg(f"ERROR: {e}")
        TASKS[task_id]["status"] = "ERROR"
        TASKS[task_id]["detail"] = str(e)
    finally:
        for f in temp_files:
            if f and os.path.exists(f):
                try: os.remove(f)
                except: pass
        import gc
        gc.collect()


TRACKS_DIR = "tracks_storage"
os.makedirs(TRACKS_DIR, exist_ok=True)

async def cache_track_audio(task_id: str, remote_url: str) -> str:
    """Download audio when fresh and cache locally so it never expires and serves reliably (streamed in chunks to save RAM)."""
    if not remote_url:
        return remote_url
    local_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return f"/api/audio_file/{task_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", remote_url) as resp:
                if resp.status_code == 200:
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            f.write(chunk)
                    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
                        return f"/api/audio_file/{task_id}"
    except Exception as e:
        print(f"Aviso al cachear audio localmente: {e}")
    return remote_url

@app.get("/api/audio_file/{task_id}")
async def serve_cached_audio(task_id: str):
    local_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return FileResponse(path=local_path, media_type="audio/mpeg")
    library = load_library()
    track = next((t for t in library if t.get("id") == task_id), None)
    if track:
        url = track.get("raw_audio_url") or track.get("audio_url")
        if url and url.startswith("http"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=url)
    raise HTTPException(status_code=404, detail="Audio no disponible")

async def run_transform_task(task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio, include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness, style_influence, audio_influence, model, pronunciation="", obfuscate=False):
    def log_msg(msg):
        import datetime
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line, flush=True)
        TASKS[task_id]["logs"] += line + "\n"
        
    def save_local_log():
        import datetime
        os.makedirs("logs", exist_ok=True)
        filename = f"logs/generation_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_id[:6]}.log"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(TASKS[task_id]["logs"])
        return TASKS[task_id]["logs"]

    headers = {
        "Authorization": f"Bearer {UDIO_API_KEY}",
        "Content-Type": "application/json"
    }

    is_instrumental = not include_lyrics or (lyrics.strip().lower() == "[instrumental]")
    if is_instrumental:
        title = f"{title} (Instrumental)"
    
    final_lyrics = lyrics if not is_instrumental else "[Instrumental]"

    # Correcciones de pronunciación: una por línea con formato "palabra=como suena"
    if pronunciation.strip() and not is_instrumental and final_lyrics:
        for rule in pronunciation.splitlines():
            if "=" not in rule:
                continue
            word, sound = [x.strip() for x in rule.split("=", 1)]
            if word and sound:
                final_lyrics = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", sound, final_lyrics, flags=re.IGNORECASE)
                log_msg(f"Pronunciación: '{word}' -> '{sound}'")

    if is_instrumental:
        final_lyrics = "[Instrumental]"
    else:
        # Determine prefix and vocal accent without forcing regional Mexican genre
        if "mexican" in style.lower() or "mexicano" in style.lower():
            prefix = "[Language: Spanish]\n[Vocals: Mexican Spanish accent]\n"
        elif "coro" in style.lower() or "choir" in style.lower():
            prefix = "[Language: Spanish]\n[Vocals: Congregational church choir, natural Latin Spanish vocals]\n"
        else:
            prefix = "[Language: Spanish]\n[Vocals: Natural Latin American Spanish, clear tone, no castilian lisp]\n"
        
        # Ofuscar la letra con caracteres invisibles solo si el usuario lo pide (evita el filtro
        # de copyright de la API, pero puede empeorar la pronunciación).
        if obfuscate and final_lyrics:
            log_msg("Ofuscando letra para evitar detección de copyright...")
            final_lyrics = prefix + obfuscate_lyrics(final_lyrics)
        elif final_lyrics and not final_lyrics.strip().startswith("[Language") and not final_lyrics.strip().startswith("[Vocals"):
            final_lyrics = prefix + final_lyrics
        
    upload_url = None
    temp_file_path = None
    bypassed_file_path = None
    
    try:
        if audio_content and not ignore_audio:
            ext = ".mp3"
            if audio_filename:
                _, fext = os.path.splitext(audio_filename)
                if fext:
                    ext = fext
            temp_file_path = f"temp_upload_{uuid.uuid4().hex}{ext}"
            bypassed_file_path = f"bypassed_{uuid.uuid4().hex}.mp3"
            
            with open(temp_file_path, "wb") as f:
                f.write(audio_content)
                
            if bypass_copyright:
                log_msg("Procesando audio con FFmpeg para evadir Huella Acústica (Copyright)...")
                bypass_result = await asyncio.to_thread(bypass_audio_fingerprint, temp_file_path, bypassed_file_path)
                if bypass_result == "SUCCESS" and os.path.exists(bypassed_file_path):
                    target_upload_file = bypassed_file_path
                    log_msg("FFmpeg terminó exitosamente. Usando audio modificado.")
                else:
                    target_upload_file = temp_file_path
                    log_msg(f"FALLO FFmpeg ({bypass_result}). Subiendo audio original SIN bypass.")
            else:
                target_upload_file = temp_file_path
                log_msg("Usando audio original limpio (sin modulación de huella acústica).")
                
            log_msg("Subiendo MP3 a servidor temporal para obtener URL pública...")
            upload_url = await upload_to_uguu_async(target_upload_file)
            if not upload_url:
                log_msg("ERROR: No se pudo subir el archivo de audio a Uguu.")
                raise Exception("Fallo al subir el audio a servidor temporal.")
            log_msg(f"Audio subido exitosamente a: {upload_url}")
            
            for p in [temp_file_path, bypassed_file_path]:
                if p and os.path.exists(p):
                    try: os.remove(p)
                    except: pass
                    
        # ----------
        # Helper: expand known instrument/effect keywords into richer descriptions
        # ----------
        def enrich_style(style_str: str) -> str:
            """Add detailed descriptors for common instrument/effect keywords."""
            mapping = {
                "stratocaster": "Fender Stratocaster electric guitar",
                "dw": "DW premium drum kit",
                "tama": "TAMA metal progressive kit, metallic power, precise tuning, energetic",
                "ludwig": "Ludwig classic rock kit, deep warm powerful tone",
                "flanger": "flanger effect",
                "chorus": "chorus effect",
                "stereo wide": "stereo wide professional studio mix",
                "fender telecaster": "Fender Telecaster electric guitar, bright crisp, country‑rock tone",
                "gibson les paul": "Gibson Les Paul solid‑body guitar, thick warm sustain",
                "marcos witt piano": "bright acoustic piano, Rhodes‑style electric piano, reverb ambience",
                "yamaha keyboard": "Yamaha synth/keyboard, rich pads, clean piano patches",
                "fender jazz bass": "Fender Jazz Bass, articulate mid‑range, smooth low end",
                "yamaha bass": "Yamaha electric bass, solid low‑end, punchy attack",
                "fender precision bass": "Fender Precision Bass, thick fundamental, vintage rock tone",
                "coro pentecostal": "fast upbeat pentecostal praise choir, straight 4/4 driving rock drum beat, energetic snare backbeat on 2 and 4, punchy 8th-note electric bass, clean rhythm electric guitar, acoustic guitar strum, high tempo 135 bpm, joyful congregational worship, handclaps",
                "coros pentecostales": "fast upbeat pentecostal praise choir, straight 4/4 driving rock drum beat, energetic snare backbeat on 2 and 4, punchy 8th-note electric bass, clean rhythm electric guitar, acoustic guitar strum, high tempo 135 bpm, joyful congregational worship, handclaps",
                "pentecostal": "fast upbeat pentecostal praise, straight 4/4 live drum kit, punchy bass guitar, rhythm guitar, energetic congregational worship, fast tempo 135 bpm",
                "avivamiento": "energetic revival praise, straight 4/4 live drums with snare backbeat, driving bass guitar, rhythm guitar, fast tempo 135 bpm",
                "coros de avivamiento": "energetic revival praise, straight 4/4 live drums with snare backbeat, driving bass guitar, rhythm guitar, fast tempo 135 bpm",
                "coro pentecostal de avivamiento": "fast upbeat pentecostal praise choir, straight 4/4 driving rock drum beat, energetic snare backbeat on 2 and 4, punchy 8th-note electric bass, clean rhythm electric guitar, acoustic guitar strum, high tempo 135 bpm, joyful congregational worship, handclaps",
                "alabanza rapida": "fast joyful Christian praise, straight 4/4 driving rock drums, punchy bass, rhythm electric guitar, fast tempo 135 bpm",
                "alabanza rápida": "fast joyful Christian praise, straight 4/4 driving rock drums, punchy bass, rhythm electric guitar, fast tempo 135 bpm",
                "adoracion intima": "deep intimate worship and prayer, gentle 68 bpm slow tempo, warm Fender Rhodes Mark I electric piano, soft atmospheric ambient electric guitar with shimmer reverb and rhythmic delay, warm synth pad cushion, tender acoustic grand piano, delicate string quartet, emotive heartfelt devotional vocal",
                "adoración íntima": "deep intimate worship and prayer, gentle 68 bpm slow tempo, warm Fender Rhodes Mark I electric piano, soft atmospheric ambient electric guitar with shimmer reverb and rhythmic delay, warm synth pad cushion, tender acoustic grand piano, delicate string quartet, emotive heartfelt devotional vocal",
                "himno solemne tradicional": "traditional sacred hymn, majestic church pipe organ, solemn Hammond B3 swell, subtle symphonic orchestra strings and woodwinds, 4-part SATB choral harmonies, reverent cathedral acoustic ambience, andante 78 bpm tempo, classical sacred Christian hymn",
                "alabanza juvenil pop/rock": "modern Christian youth praise and pop rock, driving 125 bpm, punchy acoustic rock drum kit with solid backbeat, energetic Fender Jazz Bass, crunchy overdrive rhythm electric guitars, dotted eighth-note delay lead guitar riff, modern synth arpeggio, inspiring youth worship leader and anthemic chorus",
                "guitarra bajo bateria": "straight 4/4 rhythm electric guitar and strummed acoustic guitar, driving electric bass guitar, live acoustic rock drums with snare backbeat",
                "guitarra bajo batería": "straight 4/4 rhythm electric guitar and strummed acoustic guitar, driving electric bass guitar, live acoustic rock drums with snare backbeat",
                # Hardware de Estudio y Consolas
                "neve 8048": "Neve 8048 vintage console, Neve 1073 preamp warm analog saturation, rich low-end and silky smooth high frequencies",
                "neve 1073": "Neve 1073 vintage preamp, warm British analog console saturation, thick lows and silky highs",
                "ssl 4000": "Solid State Logic SSL 4000 console mix, crisp transients, punchy drum compression, ultra-clean studio fidelity",
                "ssl 4000 e/g": "Solid State Logic SSL 4000 console mix, crisp transients, punchy drum compression, ultra-clean studio fidelity",
                "api 1608": "API 1608 console, discrete op-amp 312 punchy midrange, aggressive transient punch, American rock studio sound",
                "abbey road tg12345": "Abbey Road TG12345 console, vintage EMI tape saturation, warm tube harmonic distortion",
                # Baterías Pro
                "dw collector's": "DW Collector's Series maple drum kit, punchy kick drum, resonant snare with crack, warm balanced toms",
                "dw collector's maple": "DW Collector's Series maple drum kit, punchy kick drum, resonant snare with crack, warm balanced toms",
                "ludwig classic 70s": "vintage 1970s Ludwig Classic drum kit, deep warm wooden tone, fat vintage snare with ring",
                "yamaha recording custom": "Yamaha Recording Custom birch drum kit, clean punchy attack, perfectly controlled studio drum resonance",
                # Bajos
                "fender jazz bass 1975": "1975 Fender Jazz Bass with active pickups, growling midrange bite, articulate fingerstyle clarity",
                "fender precision 1962": "1962 Fender Precision Bass, deep punchy round low-end, classic Motown and vintage rock bass tone",
                "fender precision bass": "Fender Precision Bass, thick fundamental, vintage rock tone",
                "music man stingray": "Music Man StingRay bass, punchy active humbucker, aggressive slap and finger tone, tight sub-bass",
                "contrabajo acustico": "acoustic upright double bass, warm resonant wooden body, deep woody acoustic pizzicato tone",
                "contrabajo acústico": "acoustic upright double bass, warm resonant wooden body, deep woody acoustic pizzicato tone",
                # Teclados y Pianos
                "yamaha cfx grand": "Yamaha CFX 9-foot concert grand piano, crystal clear brilliant highs, majestic resonant bass, acoustic concert hall reverb",
                "fender rhodes mark i": "vintage 1973 Fender Rhodes Mark I electric piano, warm bell-like tines, gentle tremolo, lush neo-soul worship vibe",
                "rhodes": "vintage Fender Rhodes Mark I electric piano, warm bell-like tines, gentle tremolo",
                "hammond b3": "authentic Hammond B3 tonewheel organ through rotating Leslie 122 speaker horn, gospel overdrive warmth",
                "hammond b3 + leslie": "authentic Hammond B3 tonewheel organ through rotating Leslie 122 speaker horn, gospel overdrive warmth",
                "roland juno-106": "Roland Juno-106 analog polyphonic synthesizer, lush stereo chorus pad, warm atmospheric worship soundscape",
                # Guitarras
                "martin d-28": "Martin D-28 acoustic dreadnought guitar, sitka spruce top and rosewood body, rich balanced acoustic strumming",
                "martin d-28 acustica": "Martin D-28 acoustic dreadnought guitar, sitka spruce top and rosewood body, rich balanced acoustic strumming",
                "martin d-28 acústica": "Martin D-28 acoustic dreadnought guitar, sitka spruce top and rosewood body, rich balanced acoustic strumming",
            }
            parts = [p.strip() for p in style_str.split(",") if p.strip()]
            enriched_parts = []
            for p in parts:
                key = p.lower()
                if key in mapping:
                    enriched_parts.append(mapping[key])
                else:
                    enriched_parts.append(p)
            return ", ".join(enriched_parts)

        # ----------
        # Helper: expand known vocal artist keywords into richer descriptions (REPLACING the artist name)
        # ----------
        def enrich_voice(style_str: str) -> str:
            """Add tags for known vocal artists and replace real names so Udio doesn't reject them."""
            voice_map = {
                "luis miguel": "smooth latin romantic male tenor",
                "cristian castro": "bright soaring latin pop male tenor",
                "phil collings": "1980s pop rock, gated reverb drums, emotive adult contemporary male vocals",
                "phil collins": "1980s pop rock, gated reverb drums, emotive adult contemporary male vocals",
                "freddie mercury": "operatic theatrical rock male tenor",
                "omar farías": "latin christian male tenor",
                "elías álvarez": "latin christian male tenor",
                "steve green": "inspirational classical Christian tenor, lyrical light flexible A2-B4 range",
                "david phelps": "powerful soaring gospel tenor",
                "cuarteto de voz masculina": "male choir classic",
                "filarmónica": "SATB choir",
                "orquesta": "SATB choir",
                "laura pausini": "passionate Italian pop female lyrical",
                "christina aguilera": "powerhouse pop soul female vocals",
                "mariah carey": "virtuosic pop female high-range",
                "celine dion": "dramatic operatic pop female belting",
                "coro pentecostal": "congregational choir, multi-voice church choir, joyful unison vocals",
                "coros pentecostales": "congregational choir, multi-voice church choir, joyful unison vocals",
                "coro": "congregational choir, multi-voice vocal ensemble",
            }
            parts = [p.strip() for p in style_str.split(",") if p.strip()]
            enriched_parts = []
            for p in parts:
                key = p.lower()
                if key in voice_map:
                    enriched_parts.append(voice_map[key])
                else:
                    enriched_parts.append(p)
            return ", ".join(enriched_parts)

        def sanitize_artist_names(style_str: str) -> str:
            """Translates banned artist/band names into allowed sonic/production descriptors to comply with Udio policy."""
            artist_translations = {
                r"\bphil\s+collin[s|g]s?\b": "1980s pop rock, gated reverb drums, dramatic dynamic tom fills, emotive adult contemporary",
                r"\bluis\s+miguel\b": "smooth latin romantic pop, big band brass, emotive male tenor, polished studio production",
                r"\bcristian\s+castro\b": "dramatic latin pop ballad, bright soaring male tenor vocals, orchestral pop",
                r"\bfreddie\s+mercury\b": "operatic theatrical rock, powerhouse male tenor, dramatic dynamic range",
                r"\bmarcos\s+witt\b": "contemporary Christian worship, bright acoustic grand piano, warm devotional praise vocals",
                r"\bsteve\s+green\b": "inspirational classical Christian tenor, lyrical vocal tone, orchestral hymn",
                r"\bdavid\s+phelps\b": "powerful gospel tenor, soaring operatic vocal range, dramatic gospel praise",
                r"\blaura\s+pausini\b": "passionate Italian pop ballad, emotional lyrical female vocals",
                r"\bchristina\s+aguilera\b": "powerhouse pop soul female vocals, wide vocal range, expressive melisma",
                r"\bmariah\s+carey\b": "virtuosic pop R&B female vocals, whistle register, lush vocal harmonies",
                r"\bceline\s+dion\b": "dramatic operatic pop ballad, powerhouse belting female vocals",
                r"\bhillsong(\s+worship|\s+united)?\b": "modern congregational anthemic worship, ambient delay electric guitars, driving drums",
                r"\belevation(\s+worship)?\b": "contemporary arena worship, big drum swells, driving bass, anthemic chorus",
                r"\bbethel(\s+music)?\b": "atmospheric Christian worship, intimate acoustic build, lush ambient synth pads",
                r"\bbeatles\b": "1960s British invasion pop rock, vintage vocal harmonies, classic jangle guitar",
                r"\bqueen\b": "operatic stadium rock, layered vocal harmonies, Brian May style guitar harmonies",
                r"\bcoldplay\b": "anthemic post-Britpop, echoing grand piano, soaring stadium rock vocals",
                r"\bu2\b": "post-punk stadium rock, dotted-eighth rhythmic delay guitar, soaring vocal delivery",
                r"\bmichael\s+jackson\b": "80s dance pop funk, crisp rhythmic drums, percussive vocal accents",
                r"\bwhitney\s+houston\b": "gospel-infused pop powerhouse female vocals, soaring resonant belt",
                r"\bstevie\s+wonder\b": "70s classic soul funk, clavinet, soulful expressive male vocals",
                r"\belton\s+john\b": "70s piano pop rock, driving acoustic grand piano, theatrical vocal delivery",
                r"\bmarcelo\s+patrono\b": "acoustic Christian worship, warm intimate guitar, devotional vocals",
                r"\bcoalo\s+zamorano\b": "upbeat latin Christian gospel pop, energetic brass, joyful worship",
                r"\bjesus\s+adrian\s+romero\b": "intimate acoustic Christian worship, nylon guitar, warm devotional baritone",
                r"\bdanilo\s+montero\b": "congregational Christian praise, uplifting pop worship, bright electric guitars",
                r"\bjuan\s+luis\s+guerra\b": "bachata and merengue latin fusion, rich horn arrangements, poetic vocals",
                r"\bbronco\b": "grupero band, regional mexican romantic cumbia ballad",
                r"\blos\s+bukis\b": "grupero ballad, 80s synthesizer grupero ballad",
            }
            cleaned = style_str
            for pattern, replacement in artist_translations.items():
                match = re.search(pattern, cleaned, flags=re.IGNORECASE)
                if match:
                    found_name = match.group(0)
                    log_msg(f"Filtro de artista Udio: Reemplazando '{found_name}' por descriptores sónicos permitidos para evitar rechazo de la API.")
                    cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
            return cleaned

        style = enrich_style(style)
        style = enrich_voice(style)
        style = sanitize_artist_names(style)

        # Clean structural tags from style string (they belong in lyrics, not style)
        style = re.sub(r'\b(verse|chorus|bridge|outro|intro|pre-chorus)\b', '', style, flags=re.IGNORECASE)
        style = re.sub(r',\s*,+', ',', style).strip(' ,')

        # Detect Christian / Worship / Devotional context for genre anchoring
        is_worship = any(w in style.lower() for w in ["devotional", "worship", "worshipful", "himno", "alabanza", "coro", "pentecostal", "iglesia", "cristiano", "christian"])
        is_fast_pentecostal = any(w in style.lower() for w in ["pentecostal", "avivamiento", "alabanza rapida", "alabanza rápida"])

        if is_fast_pentecostal:
            genre_anchor = "fast joyful pentecostal praise choir, upbeat Christian worship, lively tempo, straight rhythm"
        elif is_worship:
            genre_anchor = "sacred Christian worship hymn, church acoustic, straight 4/4 rhythm"
        else:
            genre_anchor = ""

        # Vocal styling in style prompt:
        if is_instrumental:
            if "instrumental" not in style.lower():
                style = style + ", instrumental, no vocals"
        else:
            if "mexican" in style.lower() or "mexicano" in style.lower():
                vocal_tag = "mexican spanish vocals"
            elif "coro" in style.lower() or "choir" in style.lower():
                vocal_tag = "congregational choir, church choir, natural Spanish singing"
            else:
                vocal_tag = "clear natural Spanish vocals, neutral tone, no castilian lisp"
            
            if "spanish vocals" not in style.lower() and "choir" not in style.lower():
                style = f"{style}, {vocal_tag}"

        # ----------
        # Rigorous Style Exclusion (Negative Prompting)
        # ----------
        neg_final_str = ""
        key_bans_str = ""
        if exclude_styles and exclude_styles.strip():
            raw_excl = [x.strip() for x in re.split(r'[,;\n]+', exclude_styles) if x.strip()]
            
            synonym_map = {
                "cumbia": ["cumbia", "ritmo cumbia", "grupero", "norteño", "accordion", "guiro", "cumbia sonidera"],
                "norteño": ["norteño", "norteno", "accordion", "acordeon", "bajo sexto", "corrido", "polka", "regional mexicano"],
                "norteno": ["norteño", "norteno", "accordion", "acordeon", "bajo sexto", "corrido", "polka", "regional mexicano"],
                "regional mexicano": ["regional mexican", "accordion", "bajo sexto", "corrido", "banda", "ranchera", "mariachi", "sierreño"],
                "mexicano": ["regional mexicano", "norteño", "grupero", "ranchera", "mariachi", "ritmo grupero", "accordion"],
                "mexican": ["regional mexican", "norteño", "grupero", "ranchera", "mariachi", "accordion"],
                "grupero": ["grupero", "onda grupera", "balada grupera", "ritmo grupero", "cumbia grupera", "sintetizador grupero"],
                "bronco": ["ritmo grupero", "cumbia grupera", "norteño", "accordion"],
                "latin ritmics": ["tropical rhythm", "reggaeton beat", "dembow", "latin percussion"],
                "ritmos latinos": ["tropical rhythm", "reggaeton beat", "dembow", "latin percussion"],
                "salsa": ["salsa", "salsa horns", "latin brass", "montuno"],
                "bachata": ["bachata", "bachata bongo", "bongo beat"],
                "autotune": ["autotune", "pitch correction", "robotic voice", "vocoder"],
                "distortion": ["heavy distortion", "fuzz", "distorted guitar", "metal tone"],
                "fuzz": ["fuzz guitar", "heavy distortion"],
                "heavy metal": ["heavy metal", "screaming vocals", "metal drums"],
                "electronics drums": ["electronic drums", "synth drums", "808 drums", "drum machine"],
                "electronic drums": ["electronic drums", "synth drums", "808 drums", "drum machine"],
                "reggaeton": ["reggaeton", "dembow beat", "urban latin"],
                "trap": ["trap beat", "808 sub bass trap", "hi-hat rolls trap"],
            }
            
            neg_tags_list = []
            for item in raw_excl:
                neg_tags_list.append(item)
                # Strip directly from style if it matches
                style = re.sub(rf'\b{re.escape(item)}\b', '', style, flags=re.IGNORECASE)
                key = item.lower()
                if key in synonym_map:
                    for syn in synonym_map[key]:
                        neg_tags_list.append(syn)
                        style = re.sub(rf'\b{re.escape(syn)}\b', '', style, flags=re.IGNORECASE)

            # Deduplicate negative tags & filter out artist names prohibited by Udio API
            banned_artists_pattern = re.compile(r'\b(los\s+bukis|bukis|bronco|luis\s+miguel|cristian\s+castro|marcos\s+witt|steve\s+green|david\s+phelps|hillsong|elevation|bethel|beatles|queen|coldplay|u2|michael\s+jackson|whitney\s+houston|stevie\s+wonder|elton\s+john|juan\s+luis\s+guerra)\b', re.IGNORECASE)
            seen = set()
            dedup_neg = []
            for t in neg_tags_list:
                tl = t.lower().strip()
                if tl and tl not in seen and not banned_artists_pattern.search(tl):
                    seen.add(tl)
                    dedup_neg.append(t.strip())

            # Build direct key bans that MUST be front-loaded in style (e.g. no accordion, no cumbia, no norteño)
            critical_instruments = ["accordion", "bajo sexto", "cumbia", "norteño", "corrido", "grupero", "polka", "distortion", "autotune"]
            active_critical = [f"no {inst}" for inst in critical_instruments if any(inst in tag.lower() for tag in dedup_neg)]
            if active_critical:
                key_bans_str = ", ".join(active_critical)

            # Combine style: Anchor + Style + Front-loaded bans
            combined_parts = [p for p in [genre_anchor, style, key_bans_str] if p]
            style = ", ".join(combined_parts)
            style = re.sub(r',\s*,+', ',', style).strip(' ,')

            # 2. Bracket exclusion meta at top of prompt/lyrics:
            exclude_header = f"[Exclude: {', '.join(dedup_neg[:12])}]\n"
            if genre_anchor:
                exclude_header += f"[Genre: {genre_anchor}]\n"
            final_lyrics = exclude_header + final_lyrics
            
            neg_final_str = ", ".join(dedup_neg)
            log_msg(f"Exclusión estricta aplicada con éxito: {neg_final_str}")
        else:
            if genre_anchor:
                style = f"{genre_anchor}, {style}"
                style = re.sub(r',\s*,+', ',', style).strip(' ,')

        if upload_url:
            log_msg("Usando endpoint V2 Upload & Cover")
            url_generate = "https://udioapi.pro/api/v2/upload-cover/generate"
            url_status = "https://udioapi.pro/api/v2/upload-cover/status"

            payload = {
                "upload_url": upload_url,
                "model": model,
                "custom_mode": True,
                "prompt": final_lyrics,
                "style": style,
                "title": title,
                "make_instrumental": is_instrumental,
                "style_weight": round(style_influence / 100.0, 2),
                "audio_weight": round(audio_influence / 100.0, 2),
                "weirdness_constraint": round(weirdness / 100.0, 2)
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if neg_final_str:
                payload["tags"] = neg_final_str
                payload["negative_tags"] = neg_final_str
                payload["negative_prompt"] = neg_final_str
                payload["exclude_styles"] = neg_final_str
                payload["excluded_tags"] = neg_final_str
        else:
            log_msg("Usando endpoint V2 Generate")
            url_generate = "https://udioapi.pro/api/v2/generate"
            url_status = "https://udioapi.pro/api/v2/feed"
            
            payload = {
                "custom_mode": True,
                "prompt": final_lyrics,
                "style": style,
                "title": title,
                "make_instrumental": is_instrumental,
                "model": model,
                "style_weight": round(style_influence / 100.0, 2),
                "weirdness_constraint": round(weirdness / 100.0, 2)
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if neg_final_str:
                payload["tags"] = neg_final_str
                payload["negative_tags"] = neg_final_str
                payload["negative_prompt"] = neg_final_str
                payload["exclude_styles"] = neg_final_str
                payload["excluded_tags"] = neg_final_str

        max_retries = 3
        for attempt in range(max_retries):
            try:
                log_msg(f"Submitting request to {url_generate} (Attempt {attempt+1}/{max_retries})...")
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.post(url_generate, json=payload, headers=headers)
                    
                    if r.status_code == 402:
                        raise Exception("No hay créditos suficientes en la API de Udio (Status 402).")
                    elif r.status_code != 200:
                        raise Exception(f"Error de API HTTP {r.status_code}: {r.text}")
        
                    resp_json = r.json()
                    work_id = resp_json.get("workId") or resp_json.get("id")
                    
                    if not work_id:
                        data_block = resp_json.get("data", {})
                        if isinstance(data_block, dict):
                            work_id = data_block.get("task_id")
                        if not work_id:
                            raise Exception(f"No se recibió un ID de tarea válido. Respuesta: {r.text}")
        
                    log_msg(f"Task successfully queued. ID: {work_id}")
                    
                    tracks = []
                    for i in range(120):
                        if TASKS.get(task_id, {}).get("status") == "CANCELLED":
                            log_msg("Generación abortada por el usuario.")
                            break
                            
                        if upload_url:
                            r_status = await client.get(f"{url_status}?task_id={work_id}", headers=headers)
                        else:
                            r_status = await client.get(f"{url_status}?workId={work_id}", headers=headers)
                            
                        if r_status.status_code == 200:
                            status_json = r_status.json()
                            error_msg = "La generación falló internamente."
                            
                            if upload_url:
                                raw_data = status_json.get("data", {})
                                status = raw_data.get("type", "") or raw_data.get("status", "")
                                response_array = raw_data.get("response_data", [])
                                if status.upper() in ["SUCCESS", "COMPLETED"]:
                                    tracks = response_array if isinstance(response_array, list) else [response_array]
                                    log_msg("Generación completada exitosamente.")
                                    break
                                elif status.upper() in ["FAILED", "ERROR"]:
                                    if isinstance(response_array, list) and len(response_array) > 0:
                                        error_msg = response_array[0].get("fail_message") or response_array[0].get("error_message") or error_msg
                                    raise Exception(f"API Error: {error_msg}")
                            else:
                                if isinstance(status_json, list):
                                    data = status_json
                                    status = data[0].get("status", "") if len(data) > 0 else ""
                                else:
                                    status = status_json.get("status", "")
                                    raw_data = status_json.get("data", {})
                                    
                                    if isinstance(raw_data, dict):
                                        if not status:
                                            status = raw_data.get("type", "") or raw_data.get("status", "")
                                        response_array = raw_data.get("response_data", [])
                                        if isinstance(response_array, list) and len(response_array) > 0:
                                            data = response_array
                                            if response_array[0].get("fail_message"):
                                                error_msg = response_array[0].get("fail_message")
                                        else:
                                            data = [raw_data]
                                    else:
                                        data = raw_data if isinstance(raw_data, list) else []
        
                                if status.upper() in ["SUCCESS", "COMPLETED"]:
                                    tracks = data
                                    log_msg("Generación completada exitosamente.")
                                    break
                                elif len(data) > 0 and isinstance(data[0], dict) and data[0].get("status", "").upper() in ["SUCCESS", "COMPLETED"]:
                                    tracks = data
                                    log_msg("Generación completada exitosamente.")
                                    break
                                elif status.upper() in ["FAILED", "ERROR"] or (len(data) > 0 and isinstance(data[0], dict) and data[0].get("status", "").upper() in ["FAILED", "ERROR"]):
                                    raise Exception(f"API Error: {error_msg}")
        
                        log_msg(f"Polling (Attempt {i+1}): Status Code={r_status.status_code} | JSON={str(r_status.text)[:250]}")
                        await asyncio.sleep(5)
        
                    if not tracks:
                        raise Exception("Tiempo de espera agotado. La tarea no finalizó a tiempo.")
        
                    final_tracks = []
                    for t in tracks:
                        if isinstance(t, dict):
                            tid = t.get("id") or t.get("task_id")
                            ttitle = t.get("title", title)
                            taudio = t.get("audio_url") or t.get("url") or t.get("song_path")
                            timage = t.get("image_url") or t.get("image_path")
                            tduration = t.get("duration", 0)
                            tstatus = t.get("status", "SUCCESS")
                            
                            if taudio:
                                log_msg(f"Guardando copia permanente para {ttitle}...")
                                taudio_cached = await cache_track_audio(tid, taudio)
                                track_info = {
                                    "id": tid,
                                    "title": ttitle,
                                    "audio_url": taudio_cached,
                                    "raw_audio_url": taudio,
                                    "image_url": timage,
                                    "duration": tduration,
                                    "status": tstatus,
                                    "lyrics": t.get("lyrics") or lyrics,
                                    "style": style,
                                    "model": model,
                                    "vocal_gender": vocal_gender,
                                    "weirdness": weirdness,
                                    "style_influence": style_influence,
                                    "audio_influence": audio_influence,
                                    "pronunciation": pronunciation,
                                    "obfuscate": obfuscate,
                                    "exclude_styles": exclude_styles
                                }
                                final_tracks.append(track_info)
                                add_track_to_library(track_info)
                                log_msg(f"Pista procesada con éxito: {ttitle} (ID: {tid})")
        
                    save_local_log()
                    TASKS[task_id]["tracks"] = final_tracks
                    TASKS[task_id]["status"] = "COMPLETED"
        
                break
            except Exception as e:
                if "Internal Error" in str(e) and attempt < max_retries - 1:
                    log_msg(f"Udio API Error Interno. Reintentando automaticamente en 15 segundos...")
                    await asyncio.sleep(15)
                else:
                    raise e
    except Exception as e:
        log_msg(f"ERROR: {str(e)}")
        save_local_log()
        TASKS[task_id]["detail"] = str(e)
        TASKS[task_id]["status"] = "ERROR"
    finally:
        import gc
        gc.collect()

@app.get("/api/latest-logs")
async def get_latest_logs():
    if not TASKS:
        return PlainTextResponse("No hay tareas registradas desde el último reinicio.")
    latest_task_id = list(TASKS.keys())[-1]
    task = TASKS[latest_task_id]
    
    output = f"--- LOGS DE LA TAREA {latest_task_id} ---\n"
    output += f"Estado actual: {task.get('status')}\n"
    output += f"Error/Detalle: {task.get('detail', '')}\n\n"
    output += task.get("logs", "No hay logs aún.")
    
    return PlainTextResponse(output)

@app.get("/api/library")
async def api_get_library(current_user: str = Depends(get_current_user)):
    library = load_library()
    return JSONResponse(content={"status": "success", "tracks": library[::-1]})

@app.delete("/api/library/{task_id}")
async def api_delete_from_library(task_id: str, current_user: str = Depends(get_current_user)):
    library = load_library()
    new_library = [t for t in library if t.get("id") != task_id]
    if len(new_library) == len(library):
        raise HTTPException(status_code=404, detail="Track no encontrado")
    save_library(new_library)
    return JSONResponse(content={"status": "success"})

DICTIONARY_FILE = "dictionary.txt"

@app.get("/api/dictionary")
async def get_dictionary(current_user: str = Depends(get_current_user)):
    content = ""
    if os.path.exists(DICTIONARY_FILE):
        try:
            with open(DICTIONARY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""
    return JSONResponse(content={"status": "success", "content": content})

@app.post("/api/dictionary")
async def save_dictionary(request: Request, current_user: str = Depends(get_current_user)):
    data = await request.json()
    content = data.get("content", "")
    with open(DICTIONARY_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return JSONResponse(content={"status": "success"})

async def get_or_download_audio_file(task_id: str, track: dict, temp_fallback_file: str) -> str:
    """Returns a local file path to the audio file, cached if available, or downloaded."""
    local_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return local_path
        
    urls_to_try = []
    if track.get("raw_audio_url"):
        urls_to_try.append(track["raw_audio_url"])
    if track.get("audio_url"):
        if track["audio_url"].startswith("http"):
            urls_to_try.append(track["audio_url"])
            
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    
    last_err = None
    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code == 200:
                        with open(local_path, "wb") as f:
                            async for chunk in resp.aiter_bytes(65536):
                                f.write(chunk)
                        if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
                            return local_path
        except Exception as e:
            last_err = e
            try:
                import urllib.request
                def fetch_u():
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        with open(local_path, "wb") as out_f:
                            while True:
                                chunk = resp.read(65536)
                                if not chunk:
                                    break
                                out_f.write(chunk)
                await asyncio.to_thread(fetch_u)
                if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
                    return local_path
            except Exception as e2:
                last_err = e2
                
    raise HTTPException(status_code=500, detail=f"No se pudo descargar el audio original: {last_err or 'enlace no disponible'}")

@app.get("/api/stems/{task_id}/{stem_type}")
async def get_stem_audio(task_id: str, stem_type: str, current_user: str = Depends(get_current_user)):
    if stem_type not in ["vocals", "instrumental"]:
        raise HTTPException(status_code=400, detail="Tipo de stem no válido")
    library = load_library()
    track = next((t for t in library if t.get("id") == task_id), None)
    if not track:
        for task in TASKS.values():
            for t in task.get("tracks", []):
                if t.get("id") == task_id:
                    track = t
                    break
            if track:
                break
    if not track:
        local_check = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
        if os.path.exists(local_check):
            track = {"id": task_id, "title": "Rodrix_Track", "audio_url": f"/api/audio_file/{task_id}"}
    if not track:
        raise HTTPException(status_code=404, detail="Track no encontrado en la librería")

    title = track.get("title", "Rodrix_Track")
    safe_title = "".join([c for c in title if c.isalnum() or c in ' -_']).strip() or "track"
    
    temp_stem_out = f"temp_stem_out_{uuid.uuid4().hex}.mp3"
    
    def cleanup_files(files):
        for f in files:
            if f and os.path.exists(f) and not f.startswith(TRACKS_DIR):
                try: os.remove(f)
                except: pass
        import gc
        gc.collect()

    try:
        source_audio_file = await get_or_download_audio_file(task_id, track, "")
        
        # Separación de stems con técnicas avanzadas de M/S y EQ
        if stem_type == "vocals":
            stem_filter = "stereotools=mlev=1.6:slev=0.015625,equalizer=f=2500:t=q:w=1:g=3,highpass=f=180,lowpass=f=7500"
        else:
            stem_filter = "stereotools=mlev=0.015625:slev=1.5"
            
        ffmpeg_cmd = ["ffmpeg", "-threads", "1", "-y", "-i", source_audio_file, "-af", stem_filter, "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", temp_stem_out]
        await asyncio.to_thread(subprocess.run, ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        from starlette.background import BackgroundTask
        return FileResponse(
            path=temp_stem_out,
            filename=f"{safe_title}_{stem_type}.mp3",
            media_type="audio/mpeg",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}_{stem_type}.mp3"'},
            background=BackgroundTask(cleanup_files, [temp_stem_out])
        )
    except HTTPException:
        cleanup_files([temp_stem_out])
        raise
    except Exception as e:
        cleanup_files([temp_stem_out])
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return FileResponse('index.html')

@app.get("/player.html")
async def player():
    return FileResponse('player.html')

@app.get("/walkman.jpg")
async def walkman_image():
    if os.path.exists("walkman.jpg"):
        return FileResponse("walkman.jpg")
    raise HTTPException(status_code=404, detail="Imagen no encontrada")

@app.get("/api/me")
async def get_me(current_user: str = Depends(get_current_user)):
    return JSONResponse(content={"email": current_user})

def build_master_filter(width: float, eq: str, loud: str) -> str:
    """Construye la cadena de filtros FFmpeg de masterización (valores validados)."""
    filters = []
    # Ecualización (curvas de estudio)
    eq_presets = {
        "warm":    "lowshelf=f=120:g=2.5,highshelf=f=9000:g=-1.5",
        "bright":  "highshelf=f=8000:g=3,lowshelf=f=100:g=-1",
        "air":     "highshelf=f=12000:g=2.5",
        "vocal":   "equalizer=f=3000:t=q:w=1:g=2,highpass=f=30",
        "bass":    "lowshelf=f=100:g=4",
        "smile":   "lowshelf=f=80:g=3,equalizer=f=900:t=q:w=0.8:g=-2,highshelf=f=10000:g=3",
        "clarity": "highpass=f=30,equalizer=f=250:t=q:w=1.2:g=-3,equalizer=f=5000:t=q:w=1:g=1.5",
        "deess":   "equalizer=f=7000:t=q:w=2:g=-3.5",
        "lowcut":  "highpass=f=80",
        "radio":   "highpass=f=100,equalizer=f=2500:t=q:w=1:g=3,lowpass=f=12000",
        "vintage": "lowshelf=f=100:g=2,highshelf=f=10000:g=-3,lowpass=f=14000",
        "smooth":  "equalizer=f=4500:t=q:w=1.2:g=-2.5,highshelf=f=10000:g=-2",
    }
    if eq in eq_presets:
        filters.append(eq_presets[eq])
    # Ancho estéreo (1.0 = original, >1 = más ancho)
    width = max(1.0, min(width, 2.5))
    if width > 1.0:
        filters.append(f"extrastereo=m={width:.2f}")
    # Compresión + loudness de estudio
    loud_presets = {
        "dynamic":    (-16, "acompressor=threshold=-20dB:ratio=2:attack=30:release=300"),
        "commercial": (-11, "acompressor=threshold=-18dB:ratio=3:attack=20:release=250"),
        "loud":       (-9,  "acompressor=threshold=-18dB:ratio=4:attack=15:release=200"),
    }
    if loud in loud_presets:
        target, comp = loud_presets[loud]
        filters.append(comp)
        filters.append(f"loudnorm=I={target}:TP=-1.0:LRA=11")
        filters.append("alimiter=limit=0.95")
    return ",".join(filters)

@app.get("/api/download/{task_id}/{audio_format}")
async def download_track_format(task_id: str, audio_format: str, width: float = 1.0, eq: str = "none", loud: str = "none", current_user: str = Depends(get_current_user)):
    if audio_format not in ["wav", "flac", "mp3"]:
        raise HTTPException(status_code=400, detail="Formato no soportado")
        
    library = load_library()
    track = next((t for t in library if t.get("id") == task_id), None)
    if not track:
        for task in TASKS.values():
            for t in task.get("tracks", []):
                if t.get("id") == task_id:
                    track = t
                    break
            if track:
                break
    if not track:
        local_check = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
        if os.path.exists(local_check):
            track = {"id": task_id, "title": "Rodrix_Track", "audio_url": f"/api/audio_file/{task_id}"}
    if not track:
        raise HTTPException(status_code=404, detail="Track no encontrado en la librería")

    title = track.get("title", "Rodrix_Track")
    safe_title = "".join([c for c in title if c.isalnum() or c in ' -_']).strip() or "track"
    master_filter = build_master_filter(width, eq, loud)
    
    temp_out = f"temp_dl_out_{uuid.uuid4().hex}.{audio_format}"
    
    def cleanup_files(files):
        for f in files:
            if f and os.path.exists(f) and not f.startswith(TRACKS_DIR):
                try: os.remove(f)
                except: pass
        import gc
        gc.collect()

    try:
        source_audio_file = await get_or_download_audio_file(task_id, track, "")
        
        # If MP3 with no mastering filters: return source directly as an attachment!
        if audio_format == "mp3" and not master_filter:
            return FileResponse(
                path=source_audio_file,
                filename=f"{safe_title}.mp3",
                media_type="audio/mpeg",
                headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp3"'}
            )
            
        # Process with FFmpeg
        ffmpeg_cmd = ["ffmpeg", "-threads", "1", "-y", "-i", source_audio_file, "-map_metadata", "-1"]
        if master_filter:
            ffmpeg_cmd.extend(["-af", master_filter])
        if audio_format == "wav":
            ffmpeg_cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100"])
        elif audio_format == "flac":
            ffmpeg_cmd.extend(["-c:a", "flac", "-compression_level", "5", "-ar", "44100"])
        elif audio_format == "mp3":
            ffmpeg_cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100"])
            
        ffmpeg_cmd.append(temp_out)
        try:
            await asyncio.to_thread(subprocess.run, ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as pe:
            raise Exception(f"FFmpeg Error: {pe.stderr}")
            
        from starlette.background import BackgroundTask
        suffix = "_master" if master_filter else ""
        return FileResponse(
            path=temp_out, 
            filename=f"{safe_title}{suffix}.{audio_format}", 
            media_type=f"audio/{audio_format}",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}{suffix}.{audio_format}"'},
            background=BackgroundTask(cleanup_files, [temp_out])
        )
    except HTTPException:
        cleanup_files([temp_out])
        raise
    except Exception as e:
        cleanup_files([temp_out])
        print(f"Error descargando formato: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/me")
async def get_me(request: Request):
    user = request.session.get('user')
    if not user:
        return {"logged_in": False, "name": "Usuario", "email": ""}
    email = user.get('email', '')
    name = user.get('name') or user.get('given_name')
    if not name and email:
        name = email.split('@')[0].capitalize()
    if not name:
        name = "Rodrigo"
    picture = user.get('picture', '')
    return {"logged_in": True, "name": name, "email": email, "picture": picture}

@app.get("/", response_class=HTMLResponse)
async def serve_spa(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url="/login")
        
    email = user.get('email', '')
    if email != "rodryandy@gmail.com":
        return RedirectResponse(url="/login?error=Correo%20No%20Autorizado")
        
    real_name = user.get('name') or user.get('given_name')
    if not real_name and email:
        real_name = email.split('@')[0].capitalize()
    if not real_name:
        real_name = "Rodrigo"

    index_path = os.path.join(os.getcwd(), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
            html = html.replace("{{USER_NAME}}", real_name)
            html = html.replace("{{USER_EMAIL}}", email if email else "")
            return html
    return "<h3>index.html not found.</h3>"

@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    user = request.session.get('user')
    if user:
        email = user.get('email', '')
        if email == "rodryandy@gmail.com":
            return RedirectResponse(url="/")
        
    login_path = os.path.join(os.getcwd(), "login.html")
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>login.html not found.</h3>"

@app.get("/api/login/google")
async def login_via_google(request: Request):
    # Forzar dinámicamente HTTPS en producción (Render) para evitar el desajuste de protocolo http/https
    redirect_uri = str(request.base_url) + "api/auth/callback"
    if "localhost" not in str(request.base_url):
        redirect_uri = redirect_uri.replace("http://", "https://")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/api/auth/callback")
async def auth_callback(request: Request):
    try:
        # Quitamos el redirect_uri de los argumentos para evitar el "multiple values"
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            email = user.get('email', '')
            # Whitelist estricta
            if email != "rodryandy@gmail.com":
                return RedirectResponse(url="/login?error=Acceso%20Denegado:%20Correo%20fuera%20de%20la%20lista%20blanca.")
            
            request.session['user'] = user
            return RedirectResponse(url="/")
    except Exception as e:
        print("Error en OAuth callback:", str(e))
        return RedirectResponse(url="/login?error=Error%20al%20conectar%20con%20Google")
    
    return RedirectResponse(url="/login?error=No%20se%20pudo%20obtener%20el%20usuario")

@app.get("/api/logout")
async def api_logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url="/login")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False, workers=1)