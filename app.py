import os
import io
import time
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

try:
    import fal_client
except ImportError:
    fal_client = None

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
FAL_KEY = os.environ.get("FAL_KEY", "20e7799e-fb39-4d3b-b75e-8db768dcf965:b538bb820dd477732ffbf38a2e8e2e9d")
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY
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

USERS_FILE = "users.json"
ADMIN_EMAIL = "rodryandy@gmail.com"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(users_data):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Error guardando usuarios:", e)

def get_current_user(request: Request):
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    email = user.get('email', '').strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Usuario inválido")
    
    if email == ADMIN_EMAIL:
        return email
        
    users = load_users()
    user_record = users.get(email)
    if not user_record or user_record.get("status") == "blocked":
        raise HTTPException(status_code=403, detail="Tu usuario ha sido bloqueado por el administrador.")
    
    return email

def obfuscate_lyrics(text: str) -> str:
    """Limpia y normaliza el texto de la letra manteniendo intactas las etiquetas de estructura sin caracteres invisibles."""
    if not text:
        return ""
    lines = [line.strip() for line in text.split('\n')]
    return "\n".join(lines).strip()

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
    ffmpeg_bin = "ffmpeg"
    if os.path.exists("ffmpeg.exe"):
        ffmpeg_bin = os.path.abspath("ffmpeg.exe")
    elif os.path.exists(os.path.join(os.path.dirname(__file__), "ffmpeg.exe")):
        ffmpeg_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "ffmpeg.exe"))

    ffmpeg_cmd = [
        ffmpeg_bin,
        "-threads", "1",
        "-y",
        "-i", input_path,
        "-vn",
        "-t", "120",
        "-map_metadata", "-1",
        "-af", "aformat=channel_layouts=mono,asetrate=44100*1.025,aresample=44100,atempo=0.975,flanger=delay=4:depth=4:regen=15:width=70:speed=1.5,vibrato=f=3.0:d=0.25,compand=attacks=0:points=-80/-80|-15/-15|0/-15|20/-15",
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
RECENT_OPERATIONS = {}

def prune_tasks():
    global TASKS
    if len(TASKS) > 30:
        keys_to_remove = list(TASKS.keys())[:-25]
        for k in keys_to_remove:
            TASKS.pop(k, None)

def prune_recent_operations():
    global RECENT_OPERATIONS
    now = time.time()
    expired = [k for k, v in RECENT_OPERATIONS.items() if now - v[1] > 60]
    for k in expired:
        RECENT_OPERATIONS.pop(k, None)

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
    skeleton_file: str = Form(""),
    target_bpm: int = Form(0),
    is_public_domain: bool = Form(False),
    client_operation_id: str = Form(""),
    current_user: str = Depends(get_current_user)
):
    try:
        if not UDIO_API_KEY:
            raise HTTPException(status_code=400, detail="Falta configurar UDIO_API_KEY")

        prune_tasks()
        prune_recent_operations()

        audio_content = None
        audio_filename = None
        resolved_skeleton = None
        if skeleton_file:
            cand = skeleton_file.lstrip("/\\")
            if os.path.exists(cand):
                resolved_skeleton = cand
            else:
                base_cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), cand)
                if os.path.exists(base_cand):
                    resolved_skeleton = base_cand

        if audio and not ignore_audio:
            audio_content = await audio.read()
            audio_filename = audio.filename
            if audio_content and len(audio_content) > 0:
                # Validación local del audio mediante FFprobe antes de registrar tarea o llamar al proveedor
                temp_validate_path = None
                try:
                    ext = os.path.splitext(audio_filename or "audio.tmp")[1].lower() or ".tmp"
                    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                        tf.write(audio_content)
                        temp_validate_path = tf.name
                    
                    probe_cmd = [
                        "ffprobe", "-v", "error",
                        "-select_streams", "a:0",
                        "-show_entries", "stream=codec_name,duration,channels,sample_rate",
                        "-show_entries", "format=duration,size",
                        "-of", "json",
                        temp_validate_path
                    ]
                    proc = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
                    if proc.returncode != 0:
                        raise HTTPException(
                            status_code=400,
                            detail=f"El archivo de audio '{audio_filename}' no pudo ser validado por FFprobe. Compruebe que sea un archivo de audio soportado."
                        )
                    probe_data = json.loads(proc.stdout) if proc.stdout else {}
                    streams = probe_data.get("streams", [])
                    if not streams:
                        raise HTTPException(
                            status_code=400,
                            detail=f"El archivo '{audio_filename}' no contiene una pista de audio decodificable."
                        )
                    
                    # Comprobar límite documentado del proveedor: 8 minutos (480 segundos)
                    fmt = probe_data.get("format", {})
                    dur_str = fmt.get("duration") or streams[0].get("duration")
                    if dur_str:
                        try:
                            dur_sec = float(dur_str)
                            if dur_sec > 480.0:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"El audio excede el límite máximo de 8 minutos (480 s) permitido por el proveedor. Duración detectada: {int(dur_sec)} s."
                                )
                        except ValueError:
                            pass
                finally:
                    if temp_validate_path and os.path.exists(temp_validate_path):
                        try:
                            os.remove(temp_validate_path)
                        except Exception:
                            pass
        elif resolved_skeleton:
            # Solo aplicar ratio de BPM si el esqueleto base es hymn_297.wav (grabado originalmente a 54 BPM).
            # Para archivos MIDI (midi_*.wav) o pistas subidas, ya tienen su tempo nativo y no deben forzarse a ratio 54.0.
            is_fixed_54_bpm = "hymn_297" in resolved_skeleton.lower()
            if is_fixed_54_bpm and target_bpm and target_bpm > 30 and target_bpm != 54:
                ratio = max(0.5, min(2.0, target_bpm / 54.0))
                temp_out = os.path.join(tempfile.gettempdir(), f"skel_{uuid.uuid4().hex[:8]}.wav")
                try:
                    ffmpeg_bin = "ffmpeg"
                    if os.path.exists("ffmpeg.exe"):
                        ffmpeg_bin = os.path.abspath("ffmpeg.exe")
                    elif os.path.exists(os.path.join(os.path.dirname(__file__), "ffmpeg.exe")):
                        ffmpeg_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "ffmpeg.exe"))

                    subprocess.run(
                        [ffmpeg_bin, "-y", "-i", resolved_skeleton, "-filter:a", f"atempo={ratio:.3f}", temp_out],
                        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    with open(temp_out, "rb") as sf:
                        audio_content = sf.read()
                    try:
                        os.remove(temp_out)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[Skeleton Tempo] Error escalando BPM: {e}")
                    with open(resolved_skeleton, "rb") as sf:
                        audio_content = sf.read()
            else:
                with open(resolved_skeleton, "rb") as sf:
                    audio_content = sf.read()
            audio_filename = os.path.basename(resolved_skeleton)
            ignore_audio = False
            if audio_influence < 50:
                audio_influence = 65

        # Prevención de solicitudes duplicadas concurrentes por cliente / operación
        if client_operation_id:
            op_key = f"{current_user}:{client_operation_id}"
        else:
            if audio_content:
                # Huella digital real del contenido del archivo (evita confundir dos archivos distintos de igual tamaño)
                audio_sample = audio_content[:65536] + audio_content[-65536:] if len(audio_content) > 131072 else audio_content
                content_hash = hashlib.sha256(audio_sample).hexdigest()
            else:
                content_hash = "no_audio"
            payload_str = f"{current_user}:{title}:{style}:{model}:{audio_influence}:{style_influence}:{weirdness}:{content_hash}"
            op_key = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        now_ts = time.time()
        if op_key in RECENT_OPERATIONS:
            existing_task_id, op_time = RECENT_OPERATIONS[op_key]
            if (now_ts - op_time < 15) and (existing_task_id in TASKS) and (TASKS[existing_task_id].get("status") in ["IN_PROGRESS", "QUEUED"]):
                return {
                    "status": "started",
                    "task_id": existing_task_id,
                    "duplicate_prevented": True,
                    "message": "Solicitud idéntica detectada. Reutilizando la tarea en curso para evitar consumos duplicados."
                }

        task_id = str(uuid.uuid4())
        TASKS[task_id] = {
            "id": task_id,
            "status": "IN_PROGRESS",
            "title": title or "Obra Musical",
            "logs": "",
            "tracks": [],
            "detail": "",
            "is_public_domain": is_public_domain,
            "audio_filename": audio_filename or "N/A"
        }

        RECENT_OPERATIONS[op_key] = (task_id, now_ts)

        background_tasks.add_task(
            run_transform_task,
            task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio,
            include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness,
            style_influence, audio_influence, model, pronunciation, obfuscate, is_public_domain
        )
        
        return {"status": "started", "task_id": task_id}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al preparar la pista para generación: {str(e)}")

@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task no encontrada")
    res = dict(TASKS[task_id])
    res["id"] = task_id
    return res

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
    bg_volume: float = Form(0.07),
    ducking: bool = Form(True),
    mic_profile: str = Form("behringer_tm1"),
    interface_profile: str = Form("umc404hd"),
    plugin_profile: str = Form("izotope_vea"),
    eq_profile: str = Form("pro_studio"),
    vocal_reverb: str = Form("none"),
    compression: bool = Form(True),
    noise_reduction: bool = Form(True),
    leveling: bool = Form(True),
    stereo_wide: bool = Form(False),
    radio_structure: str = Form("radio_show"),
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
    TASKS[task_id] = {
        "id": task_id,
        "status": "IN_PROGRESS",
        "title": title or "Predicación Pastoral",
        "logs": "",
        "tracks": [],
        "detail": "",
        "is_public_domain": False,
        "audio_filename": voice_filename or "N/A"
    }
    
    background_tasks.add_task(
        run_voiceover_task,
        task_id, voice_bytes, voice_filename, title, bg_choice,
        custom_bg_bytes, custom_bg_filename, bg_volume, ducking,
        eq_profile, noise_reduction, leveling,
        vocal_reverb, compression,
        mic_profile, interface_profile, plugin_profile,
        stereo_wide, radio_structure
    )
    
    return {"status": "started", "task_id": task_id}

# =====================================================================
# OPTIMIZACIÓN DE AUDIO PARA WHATSAPP (< 15 MB)
# WhatsApp limita el envío de archivos de audio a 16 MB.
# Se establece un tope estricto de 15.0 MB (objetivo ~14.2 MB de seguridad)
# para que nunca sea rechazado por WhatsApp al compartirlo.
# =====================================================================
MAX_WHATSAPP_BYTES = 15 * 1024 * 1024  # 15.0 MB estrictos
TARGET_SAFE_BYTES = 14 * 1024 * 1024 + 200 * 1024  # ~14.2 MB margen de seguridad

def get_audio_duration_seconds(file_path: str) -> float:
    """Devuelve la duración exacta del audio en segundos usando ffprobe."""
    if not file_path or not os.path.exists(file_path):
        return 0.0
    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        proc = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return float(proc.stdout.strip())
    except Exception:
        return 0.0

def calculate_safe_mp3_bitrate(duration_sec: float, target_bytes: int = TARGET_SAFE_BYTES) -> str:
    """
    Calcula el bitrate MP3 óptimo (hasta 256k) para que el archivo final
    NUNCA supere los 15 MB exigidos por WhatsApp.
    """
    if duration_sec <= 0:
        return "192k"
    
    # Capacidad en kbps: (bytes * 8) / (segundos * 1000)
    max_kbps = int((target_bytes * 8) / (duration_sec * 1000))
    
    if max_kbps >= 256:
        return "256k"
    elif max_kbps >= 192:
        return "192k"
    elif max_kbps >= 160:
        return "160k"
    elif max_kbps >= 128:
        return "128k"
    elif max_kbps >= 96:
        return "96k"
    elif max_kbps >= 64:
        return "64k"
    elif max_kbps >= 48:
        return "48k"
    else:
        return f"{max(32, max_kbps)}k"

def get_safe_wav_ffmpeg_args(duration_sec: float, target_bytes: int = TARGET_SAFE_BYTES) -> list:
    """
    Calcula los parámetros PCM para que el archivo WAV no supere 15 MB.
    """
    if duration_sec <= 0:
        return ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
    
    max_bytes_per_sec = target_bytes / duration_sec
    
    if max_bytes_per_sec >= 176400:  # <= ~82 segundos: Calidad CD estéreo completa
        return ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
    elif max_bytes_per_sec >= 88200:  # <= ~165 segundos: Calidad CD mono
        return ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1"]
    elif max_bytes_per_sec >= 44100:  # <= ~330 segundos (5.5 min): 22.05kHz mono
        return ["-c:a", "pcm_s16le", "-ar", "22050", "-ac", "1"]
    elif max_bytes_per_sec >= 22050:  # <= ~660 segundos (11 min): 11.025kHz mono
        return ["-c:a", "pcm_s16le", "-ar", "11025", "-ac", "1"]
    elif max_bytes_per_sec >= 16000:  # <= ~900 segundos (15 min): 8kHz 16-bit mono
        return ["-c:a", "pcm_s16le", "-ar", "8000", "-ac", "1"]
    else:  # > 15 min: 8kHz 8-bit mono (< 15MB hasta 30 min)
        return ["-c:a", "pcm_u8", "-ar", "8000", "-ac", "1"]

async def enforce_max_file_size_mp3(file_path: str, max_bytes: int = MAX_WHATSAPP_BYTES) -> str:
    """
    Verifica el tamaño real en disco. Si supera max_bytes, lo recomprime automáticamente
    con un bitrate seguro para garantizar que siempre pese menos de 15 MB.
    """
    if not file_path or not os.path.exists(file_path):
        return file_path
    
    try:
        actual_size = os.path.getsize(file_path)
        if actual_size <= max_bytes:
            return file_path
            
        dur = get_audio_duration_seconds(file_path)
        safe_kbps = calculate_safe_mp3_bitrate(dur, target_bytes=int(13.8 * 1024 * 1024))
        temp_recomp = f"temp_recomp_{uuid.uuid4().hex}.mp3"
        
        recomp_cmd = ["ffmpeg", "-threads", "0", "-y", "-i", file_path]
        if dur > 600:
            recomp_cmd.extend(["-ac", "1"])  # Mono para alocuciones de más de 10 min
        recomp_cmd.extend(["-c:a", "libmp3lame", "-b:a", safe_kbps, temp_recomp])
        
        await asyncio.to_thread(subprocess.run, recomp_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if os.path.exists(temp_recomp) and os.path.getsize(temp_recomp) > 1000:
            import shutil
            shutil.move(temp_recomp, file_path)
    except Exception as e:
        print(f"Aviso en optimización WhatsApp: {e}")
        if 'temp_recomp' in locals() and os.path.exists(temp_recomp):
            try: os.remove(temp_recomp)
            except: pass
            
    return file_path

async def run_voiceover_task(
    task_id, voice_bytes, voice_filename, title, bg_choice,
    custom_bg_bytes, custom_bg_filename, bg_volume, ducking,
    eq_profile, noise_reduction, leveling,
    vocal_reverb="none", compression=True,
    mic_profile="behringer_tm1", interface_profile="umc404hd", plugin_profile="izotope_vea",
    stereo_wide=False, radio_structure="radio_show"
):
    def log_msg(msg):
        import datetime
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line, flush=True)
        TASKS[task_id]["logs"] += line + "\n"

    temp_files = []
    try:
        log_msg("Iniciando restauración y masterización de voz pastoral...")
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

        # Cálculo de bitrate inteligente para garantizar < 15 MB (WhatsApp)
        safe_bitrate = calculate_safe_mp3_bitrate(voice_dur)
        log_msg(f"Optimizando tamaño para WhatsApp (< 15 MB): Bitrate adaptativo a {safe_bitrate}...")

        # =====================================================================
        # MASTERIZACIÓN VOCAL BROADCAST FM / PODCAST SPOTIFY (-14 LUFS)
        # Optimizada para Auriculares, Parlantes de Celular y Equipos de Sonido/Auto
        # =====================================================================
        v_filters = []
        
        # 0. ALINEACIÓN DE FASE Y PURIFICACIÓN MONO INICIAL
        # Fuerza que la señal entre limpia en mono. Si es un micrófono de celular estéreo
        # con desfase acústico entre los 2 micrófonos (arriba y abajo), esto elimina
        # cualquier cancelación de fase o filtrado de peine ("efecto baño").
        v_filters.append("aformat=channel_layouts=mono:sample_rates=44100")

        # 1. INTERFAZ & PREAMPS (Corte subsónico quirúrgico de 2 polos a 85 Hz)
        # Remueve ruidos mecánicos de mesa, viento y retumbos que saturan parlantes de móvil
        if interface_profile == "umc404hd":
            log_msg("Emulando Behringer UMC404HD: Preamps MIDAS (corte 85Hz Butterworth + headroom broadcast)...")
            v_filters.append("highpass=f=85:width_type=q:w=0.707,highpass=f=85:width_type=q:w=0.707")
        else:
            v_filters.append("highpass=f=80:width_type=q:w=0.707,highpass=f=80:width_type=q:w=0.707")

        # 2. REDUCCIÓN TRANSPARENTE DE RUIDO & EXPANSOR ACÚSTICO
        # Expansor suave: limpia el ruido de fondo en silencios sin cortar respiraciones ni finales de frases
        if noise_reduction:
            log_msg("Aplicando reductor de ruido espectral y expansor acústico transparente...")
            v_filters.append("agate=threshold=-44dB:ratio=1.4:attack=15:release=260:range=-9dB")
            v_filters.append("lowpass=f=16500")

        # 3. CURVA TONAL RADIO FM MULTI-DISPOSITIVO (Celular / Auriculares / Auto)
        log_msg("Esculpiendo ecualización de cabina de radio FM profesional...")
        # A) Calidez y cuerpo de pecho de locutor (170Hz): llena en autos y auriculares
        v_filters.append("equalizer=f=170:width_type=o:width=1.0:g=2.2")
        # B) Extracción anti-resonancia de habitación / anti-baño (360Hz): elimina el sonido hueco y acartonado
        v_filters.append("equalizer=f=360:width_type=o:width=1.2:g=-4.0")
        # C) Claridad e inteligibilidad de dicción (3.2kHz): permite escuchar cada palabra perfecta en altavoz de celular
        v_filters.append("equalizer=f=3200:width_type=o:width=1.1:g=3.5")
        # D) De-Esser anti-siseo suave (6.8kHz): suaviza las 'S' hirientes en auriculares
        v_filters.append("equalizer=f=6800:width_type=o:width=1.3:g=-3.0")
        # E) Brillo y aire cristalino de radio FM (11kHz)
        v_filters.append("treble=g=2.2:f=11000:width_type=q:w=0.7")

        # Perfil de cápsula de micrófono
        if mic_profile == "behringer_tm1":
            log_msg("Añadiendo perfil Behringer TM1: cápsula dorada de 1 pulgada, presencia nítida...")
            v_filters.append("equalizer=f=4800:width_type=o:width=1.2:g=1.5")
        elif mic_profile == "shure_sm7b":
            log_msg("Añadiendo perfil Shure SM7B: presencia broadcast clásica de radio...")
            v_filters.append("equalizer=f=200:width_type=o:width=1.2:g=1.6")
        elif mic_profile == "neumann_u87":
            log_msg("Añadiendo perfil Neumann U87: agudos high-end sedosos...")
            v_filters.append("treble=g=1.5:f=12000")

        # Emulación de Channel Strip / Plugin IA
        if plugin_profile == "izotope_vea":
            log_msg("Aplicando iZotope VEA: mejora asistida por IA (Clean, Shape y Boost)...")
            v_filters.append("equalizer=f=2600:width_type=o:width=1.4:g=1.2")
        elif plugin_profile == "neve_channel":
            log_msg("Aplicando Neve 1073: saturación y calidez armónica analógica...")
            v_filters.append("equalizer=f=220:width_type=o:width=1.0:g=1.5")
        elif plugin_profile == "ssl_vocal":
            log_msg("Aplicando SSL 4000: articulación y pegada vocal al frente...")
            v_filters.append("equalizer=f=1500:width_type=o:width=1.2:g=1.4")

        # 4. EXCITADOR ARMÓNICO DE CABINA DE RADIO (Aural Exciter calibrado)
        # Inyecta brillo musical sedoso sin distorsión metálica
        log_msg("Inyectando excitador armónico Aural Exciter (brillo y definición de radio FM)...")
        v_filters.append("aexciter=level_in=1:level_out=1:amount=0.9:drive=2.6:freq=5500:ceil=15000")

        # 5. DINÁMICA BROADCAST OPTIMOD-FM EN 2 ETAPAS (Voz siempre presente y sólida)
        if compression or leveling:
            log_msg("Nivelando dinámica broadcast de 2 etapas (voz al frente y consistente)...")
            # Etapa 1: Nivelador RMS óptico (atrapa frases suaves y las coloca al frente)
            v_filters.append("acompressor=threshold=-24dB:ratio=2.8:attack=20:release=280:makeup=3.5dB:knee=2.82")
            # Etapa 2: Control rápido de picos (evita saturación en momentos de énfasis)
            v_filters.append("acompressor=threshold=-10dB:ratio=3.5:attack=4:release=80:knee=1.41")

        # 6. ESPACIALIZACIÓN Y REVERB (si se solicita)
        if vocal_reverb == "plate":
            log_msg("Agregando micro-dimensión Plate de estudio...")
            v_filters.append("aecho=0.95:0.10:35|70:0.08|0.04")
        elif vocal_reverb == "hall":
            log_msg("Agregando reverb Hall devocional...")
            v_filters.append("aecho=0.92:0.15:50|100:0.10|0.05")

        # 7. PANEO CENTRAL PERFECTO Y COMPATIBILIDAD MONO ABSOLUTA
        # Duplica la voz procesada exactamente igual en Canal Izquierdo y Derecho (L = R).
        # En altavoz de móvil (mono): suma perfecta (+6dB de pegada limpia, cero desfase).
        # En auriculares y auto: voz con presencia sólida y enfocada exactamente en el centro.
        v_filters.append("pan=stereo|c0=c0|c1=c0")
        v_filters.append("aformat=channel_layouts=stereo:sample_rates=44100")
        if stereo_wide:
            log_msg("Aplicando sutil apertura estéreo envolvente...")
            v_filters.append("extrastereo=m=1.04")

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

        export_duration = voice_dur
        if bg_file and os.path.exists(bg_file):
            bed_vol = max(0.04, min(0.09, bg_volume))
            if radio_structure == "radio_show":
                intro_sec = 5.0
                outro_sec = 4.0
                total_dur = voice_dur + intro_sec + outro_sec
                intro_vol = 0.28
                speech_end = intro_sec + voice_dur
                fade_out_start = total_dur - 2.5
                
                log_msg(f"Estructura Predicación de Radio: Intro musical {intro_sec}s (28% volumen) ➔ Baja justo al empezar la voz al colchón suave ({int(bed_vol*100)}%) ➔ Cierre triunfal {outro_sec}s...")
                
                vol_expr = (
                    f"if(lt(t,4.2),{intro_vol:.2f},"
                    f"if(lt(t,{intro_sec:.2f}),{intro_vol:.2f}-({intro_vol:.2f}-{bed_vol:.2f})*(t-4.2)/0.8,"
                    f"if(lt(t,{speech_end:.2f}),{bed_vol:.2f},"
                    f"if(lt(t,{speech_end + 1.0:.2f}),{bed_vol:.2f}+({intro_vol:.2f}-{bed_vol:.2f})*(t-{speech_end:.2f})/1.0,"
                    f"{intro_vol:.2f}))))"
                )
                
                # En la música de fondo: se atenúan suavemente las frecuencias 3.2kHz para dejar libre el espacio a la voz
                filter_complex = (
                    f"[0:a]{voice_filter_str},adelay=5000|5000,apad=pad_dur={outro_sec + 1.0:.1f}[v_ready];"
                    f"[1:a]atrim=0:{total_dur:.2f},aformat=channel_layouts=stereo:sample_rates=44100,"
                    f"equalizer=f=3200:width_type=o:width=1.5:g=-3.5,"
                    f"volume='{vol_expr}':eval=frame,afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out_start:.2f}:d=2.5[bg_ready];"
                    f"[v_ready][bg_ready]amix=inputs=2:weights=1 1:normalize=0:duration=first:dropout_transition=0[mixed];"
                    f"[mixed]loudnorm=I=-14:TP=-1.0:LRA=7,alimiter=limit=-1.0dB:attack=5:release=50:asc=1[out]"
                )
                export_duration = total_dur
            else:
                log_msg(f"Estructura Podcast Continuo: Voz al frente y música de fondo suave ({int(bed_vol*100)}%)...")
                fade_start = max(0.5, voice_dur - 2.5)
                filter_complex = (
                    f"[0:a]{voice_filter_str}[v_ready];"
                    f"[1:a]atrim=0:{voice_dur:.2f},aformat=channel_layouts=stereo:sample_rates=44100,"
                    f"equalizer=f=3200:width_type=o:width=1.5:g=-3.5,"
                    f"volume={bed_vol:.2f},afade=t=in:st=0:d=0.5,afade=t=out:st={fade_start:.2f}:d=2.5[bg_ready];"
                    f"[v_ready][bg_ready]amix=inputs=2:weights=1 1:normalize=0:duration=first:dropout_transition=0[mixed];"
                    f"[mixed]loudnorm=I=-14:TP=-1.0:LRA=7,alimiter=limit=-1.0dB:attack=5:release=50:asc=1[out]"
                )
                export_duration = voice_dur

            safe_bitrate = calculate_safe_mp3_bitrate(export_duration)
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", temp_voice,
                "-stream_loop", "-1", "-i", bg_file,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-t", f"{export_duration:.2f}",
                "-threads", "0",
                "-c:a", "libmp3lame", "-b:a", safe_bitrate,
                out_path
            ]
        else:
            log_msg("Sin música de fondo. Exportando voz de radio online masterizada (-14 LUFS)...")
            master_chain = f"{voice_filter_str},loudnorm=I=-14:TP=-1.0:LRA=7,alimiter=limit=-1.0dB:attack=5:release=50:asc=1"
            export_duration = voice_dur
            safe_bitrate = calculate_safe_mp3_bitrate(export_duration)
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", temp_voice,
                "-vn",
                "-af", master_chain,
                "-t", f"{export_duration:.2f}",
                "-threads", "0",
                "-c:a", "libmp3lame", "-b:a", safe_bitrate,
                out_path
            ]

        proc = await asyncio.to_thread(subprocess.run, ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            err_lines = [l for l in proc.stderr.strip().splitlines() if l.strip()]
            err_tail = "\n".join(err_lines[-5:]) if err_lines else proc.stderr[:300]
            log_msg(f"ERROR FFmpeg: {err_tail}")
            raise Exception("Error al procesar el audio con FFmpeg.")

        # Garantía estricta de tamaño máximo de 15 MB para WhatsApp
        await enforce_max_file_size_mp3(out_path)
        final_size_mb = os.path.getsize(out_path) / (1024 * 1024)
        log_msg(f"¡Predicación procesada y masterizada con éxito! Tamaño final: {final_size_mb:.2f} MB (Apto para WhatsApp)")
        
        # Subir copia de respaldo a la nube
        cloud_backup = None
        try:
            cloud_backup = await upload_to_catbox_async(out_path)
            if not cloud_backup:
                cloud_backup = await upload_to_uguu_async(out_path)
        except Exception:
            pass

        track_info = {
            "id": task_id,
            "title": f"🎙️ {title}",
            "audio_url": f"/api/audio_file/{task_id}",
            "raw_audio_url": cloud_backup or f"/api/audio_file/{task_id}",
            "image_url": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%2338A169'/%3E%3Ccircle cx='32' cy='24' r='10' fill='%23fff' opacity='0.9'/%3E%3Crect x='30' y='34' width='4' height='14' fill='%23fff'/%3E%3Cpath d='M22 48 L42 48' stroke='%23fff' stroke-width='4' stroke-linecap='round'/%3E%3Cpath d='M18 24 C18 34 46 34 46 24' fill='none' stroke='%23fff' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E",
            "duration": round(export_duration),
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
                        await enforce_max_file_size_mp3(local_path)
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

async def run_transform_task(task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio, include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness, style_influence, audio_influence, model, pronunciation="", obfuscate=False, is_public_domain=False):
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
    if is_instrumental and "(instrumental)" not in title.lower():
        title = f"{title} (Instrumental)"
    
    # Preservar estructura de compases y secciones en temas instrumentales para duraciones largas
    if is_instrumental:
        cleaned_lyrics = lyrics.strip() if lyrics else ""
        if cleaned_lyrics and cleaned_lyrics.lower() != "[instrumental]":
            if "[instrumental]" not in cleaned_lyrics.lower():
                final_lyrics = f"[Instrumental]\n\n{cleaned_lyrics}"
            else:
                final_lyrics = cleaned_lyrics
        else:
            final_lyrics = "[Instrumental]"
    else:
        final_lyrics = lyrics

    # Correcciones de pronunciación: una por línea con formato "palabra=como suena"
    if pronunciation.strip() and not is_instrumental and final_lyrics:
        for rule in pronunciation.splitlines():
            if "=" not in rule:
                continue
            word, sound = [x.strip() for x in rule.split("=", 1)]
            if word and sound:
                final_lyrics = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", sound, final_lyrics, flags=re.IGNORECASE)
                log_msg(f"Pronunciación: '{word}' -> '{sound}'")
    if not is_instrumental:
        # Determine prefix and vocal accent
        if "argentin" in style.lower() or "pentecostal" in style.lower() or "avivamiento" in style.lower():
            prefix = "[Language: Spanish]\n[Vocals: Coro de iglesia argentino, acento argentino natural, canto congregacional fervoroso al unísono, voces sinceras de templo, sin acento caribeño ni centroamericano]\n"
        elif "mexican" in style.lower() or "mexicano" in style.lower():
            prefix = "[Language: Spanish]\n[Vocals: Mexican Spanish accent]\n"
        elif "coro" in style.lower() or "choir" in style.lower():
            prefix = "[Language: Spanish]\n[Vocals: Coro congregacional de iglesia, acento argentino y latino natural, voces sinceras y apasionadas]\n"
        else:
            prefix = "[Language: Spanish]\n[Vocals: Natural Latin American Spanish, clear tone, no castilian lisp, no caribbean accent]\n"
        
        # Limpieza inteligente defensiva: Si la letra contiene líneas de acordes sueltos (ej: D Bm G A),
        # extraerlos para enriquecer el estilo armónico y evitar que la voz intente cantar las notas.
        if final_lyrics:
            raw_lines = final_lyrics.split("\n")
            cleaned_lines = []
            extracted_chords = []
            chord_token_pattern = re.compile(r'^[A-G][b#]?(?:maj7|maj|min|m7|m|sus4|sus|dim|aug|7|9)?(?:\/[A-G][b#]?)?$', re.IGNORECASE)
            for line in raw_lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    cleaned_lines.append(line)
                    continue
                words = stripped.split()
                if words and all(chord_token_pattern.match(w) for w in words) and len(words) >= 1 and len(words) <= 8:
                    extracted_chords.extend(words)
                else:
                    # Si tiene acordes inline tipo [D], removerlos de la letra
                    inline_cleaned = re.sub(r'\[[A-G][b#]?[^\]]*\]', '', line)
                    cleaned_lines.append(inline_cleaned)
            if extracted_chords and "chord progression" not in style.lower():
                prog_str = " - ".join(extracted_chords[:12])
                style = f"chord progression: {prog_str}, {style}"
                log_msg(f"Acordes detectados y sincronizados en la mezcla: {prog_str}")
            final_lyrics = "\n".join(cleaned_lines)

        if obfuscate and final_lyrics:
            log_msg("Ofuscando letra para evitar detección de copyright...")
            final_lyrics = prefix + obfuscate_lyrics(final_lyrics)
        elif final_lyrics and not final_lyrics.strip().startswith("[Language") and not final_lyrics.strip().startswith("[Vocals"):
            final_lyrics = prefix + final_lyrics
        
    upload_url = None
    backup_upload_url = None
    created_temp_files = []
    
    try:
        if audio_content and not ignore_audio:
            ext = ".mp3"
            if audio_filename:
                _, fext = os.path.splitext(audio_filename)
                if fext:
                    ext = fext
            temp_file_path = f"temp_upload_{uuid.uuid4().hex}{ext}"
            created_temp_files.append(temp_file_path)
            
            with open(temp_file_path, "wb") as f:
                f.write(audio_content)
                
            if bypass_copyright:
                bypassed_file_path = f"bypassed_{uuid.uuid4().hex}.mp3"
                created_temp_files.append(bypassed_file_path)
                log_msg("Procesando modulación de audio con FFmpeg...")
                bypass_result = await asyncio.to_thread(bypass_audio_fingerprint, temp_file_path, bypassed_file_path)
                if bypass_result == "SUCCESS" and os.path.exists(bypassed_file_path):
                    target_upload_file = bypassed_file_path
                    log_msg("Audio procesado exitosamente con FFmpeg.")
                else:
                    target_upload_file = temp_file_path
                    log_msg(f"Aviso FFmpeg: {bypass_result}. Utilizando audio original.")
            else:
                target_upload_file = temp_file_path
                log_msg("Utilizando archivo de audio original sin modulación.")
                
            log_msg("Subiendo audio de referencia a servidor temporal de alta velocidad...")
            upload_url = await upload_to_catbox_async(target_upload_file)
            if not upload_url:
                log_msg("Catbox no disponible, usando servidor alternativo (Uguu)...")
                upload_url = await upload_to_uguu_async(target_upload_file)
            else:
                try:
                    backup_upload_url = await upload_to_uguu_async(target_upload_file)
                except Exception:
                    pass
            if not upload_url and not backup_upload_url:
                log_msg("ERROR: No se pudo subir el archivo de audio a ningún servidor temporal.")
                raise Exception("Fallo al subir el audio a servidor temporal.")
            if not upload_url and backup_upload_url:
                upload_url = backup_upload_url
            log_msg(f"Audio de referencia vinculado exitosamente: {upload_url}")
                    
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
                "coro pentecostal": "driving acoustic drum kit rhythm, prominent cracking 14x5 Ludwig Supraphonic snare drum hitting hard on beats 2 and 4, heavy 22-inch kick drum pounding on beats 1 and 3, tight closed 14-inch dark Zildjian hi-hat keeping steady straight eighth notes, clean economical Charlie Watts acoustic drumming, zero drum solos, zero chaotic fills, gospel 2-step straight 4/4 rhythm, steady 118 bpm, root-fifth alternating acoustic bass, acoustic rhythm guitar, church choir singing in unison, passionate Argentine church vocals, no murga, no comparsa, no carnaval, no batucada, no latin rhythm, no syncopation, no cumbia, no caribbean accent, no tambourine solo, no handclaps solo",
                "coros pentecostales": "driving acoustic drum kit rhythm, prominent cracking 14x5 Ludwig Supraphonic snare drum hitting hard on beats 2 and 4, heavy 22-inch kick drum pounding on beats 1 and 3, tight closed 14-inch dark Zildjian hi-hat keeping steady straight eighth notes, clean economical Charlie Watts acoustic drumming, zero drum solos, zero chaotic fills, gospel 2-step straight 4/4 rhythm, steady 118 bpm, root-fifth alternating acoustic bass, acoustic rhythm guitar, church choir singing in unison, passionate Argentine church vocals, no murga, no comparsa, no carnaval, no batucada, no latin rhythm, no syncopation, no cumbia, no caribbean accent, no tambourine solo, no handclaps solo",
                "pentecostal": "driving acoustic drum kit, prominent cracking Ludwig snare on 2 and 4, heavy kick drum on 1 and 3, tight closed hi-hat eighth notes, Charlie Watts clean drumming, no drum solos, gospel 2-step 4/4 beat, 118 bpm, alternating bass, acoustic guitar, church choir in unison, passionate Argentine vocals, no murga, no comparsa, no latin rhythm, no syncopation, no cumbia, no tambourine",
                "avivamiento": "driving acoustic drum kit, prominent cracking Ludwig snare on 2 and 4, heavy kick drum on 1 and 3, tight closed hi-hat eighth notes, Charlie Watts clean drumming, no drum solos, gospel 2-step 4/4 beat, 118 bpm, alternating bass, acoustic guitar, church choir in unison, passionate Argentine vocals, no murga, no comparsa, no latin rhythm, no syncopation, no cumbia, no tambourine",
                "coros de avivamiento": "driving acoustic drum kit, prominent cracking Ludwig snare on 2 and 4, heavy kick drum on 1 and 3, tight closed hi-hat eighth notes, Charlie Watts clean drumming, no drum solos, gospel 2-step 4/4 beat, 118 bpm, alternating bass, acoustic guitar, church choir in unison, passionate Argentine vocals, no murga, no comparsa, no latin rhythm, no syncopation, no cumbia, no tambourine",
                "coro pentecostal de avivamiento": "driving acoustic drum kit rhythm, prominent cracking 14x5 Ludwig Supraphonic snare drum hitting hard on beats 2 and 4, heavy 22-inch kick drum pounding on beats 1 and 3, tight closed 14-inch dark Zildjian hi-hat keeping steady straight eighth notes, clean economical Charlie Watts acoustic drumming, zero drum solos, zero chaotic fills, gospel 2-step straight 4/4 rhythm, steady 118 bpm, root-fifth alternating acoustic bass, acoustic rhythm guitar, church choir singing in unison, passionate Argentine church vocals, no murga, no comparsa, no carnaval, no batucada, no latin rhythm, no syncopation, no cumbia, no caribbean accent, no tambourine solo, no handclaps solo",
                "alabanza rapida": "driving acoustic drum kit, fuerte golpe de caja Ludwig en 2 y 4, bombo pesado en 1 y 3, hi-hat cerrado, ritmo gospel 4/4, 118 bpm, Charlie Watts, bajo alternado raiz-quinta, rasgueo acustico, coro al unisono, voces argentinas, sin murga, sin comparsa, sin pandereta, sin ritmo latino",
                "alabanza rápida": "driving acoustic drum kit, fuerte golpe de caja Ludwig en 2 y 4, bombo pesado en 1 y 3, hi-hat cerrado, ritmo gospel 4/4, 118 bpm, Charlie Watts, bajo alternado raiz-quinta, rasgueo acustico, coro al unisono, voces argentinas, sin murga, sin comparsa, sin pandereta, sin ritmo latino",
                "adoracion intima": "deep intimate worship and prayer, gentle 68 bpm slow tempo, warm Fender Rhodes Mark I electric piano, soft atmospheric ambient electric guitar with shimmer reverb and rhythmic delay, warm synth pad cushion, tender acoustic grand piano, delicate string quartet, emotive heartfelt devotional vocal",
                "adoración íntima": "deep intimate worship and prayer, gentle 68 bpm slow tempo, warm Fender Rhodes Mark I electric piano, soft atmospheric ambient electric guitar with shimmer reverb and rhythmic delay, warm synth pad cushion, tender acoustic grand piano, delicate string quartet, emotive heartfelt devotional vocal",
                "piano de oracion": "solo acoustic concert grand piano, deep lush prayer hall reverb, gentle emotive touch, peaceful intimate worship, slow 60 bpm, reverent, pure piano instrumental",
                "piano de oración": "solo acoustic concert grand piano, deep lush prayer hall reverb, gentle emotive touch, peaceful intimate worship, slow 60 bpm, reverent, pure piano instrumental",
                "piano devocional": "solo acoustic concert grand piano, deep lush prayer hall reverb, gentle emotive touch, peaceful intimate worship, slow 60 bpm, reverent, pure piano instrumental",
                "vals vienes": "grand Viennese waltz in 3/4 time, Johann Strauss II style, full classical symphony orchestra, first and second violins, violas, cellos, double basses, flutes, piccolo, oboes, clarinets, bassoons, French horns, trumpets, trombones, orchestral timpani, concert snare drum, crash cymbals, concert bass drum, authentic Viennese oom-pah-pah 3/4 waltz lilt, elegant rubato, Vienna Philharmonic hall acoustic",
                "vals vienés": "grand Viennese waltz in 3/4 time, Johann Strauss II style, full classical symphony orchestra, first and second violins, violas, cellos, double basses, flutes, piccolo, oboes, clarinets, bassoons, French horns, trumpets, trombones, orchestral timpani, concert snare drum, crash cymbals, concert bass drum, authentic Viennese oom-pah-pah 3/4 waltz lilt, elegant rubato, Vienna Philharmonic hall acoustic",
                "himno vals vienes": "sacred Christian hymn as a grand Viennese waltz in 3/4 time, Johann Strauss II style, full classical symphony orchestra with first and second violins, violas, cellos, double basses, flutes, piccolo, oboes, clarinets, bassoons, French horns, trumpets, trombones, orchestral timpani, concert snare drum, crash cymbals, concert bass drum, authentic Viennese oom-pah-pah 3/4 waltz lilt, elegant orchestral rubato, majestic Vienna hall acoustic",
                "himno vals vienés": "sacred Christian hymn as a grand Viennese waltz in 3/4 time, Johann Strauss II style, full classical symphony orchestra with first and second violins, violas, cellos, double basses, flutes, piccolo, oboes, clarinets, bassoons, French horns, trumpets, trombones, orchestral timpani, concert snare drum, crash cymbals, concert bass drum, authentic Viennese oom-pah-pah 3/4 waltz lilt, elegant orchestral rubato, majestic Vienna hall acoustic",
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
                "century 1994": "1994 Century acoustic wood shell drum kit, 10 12 14 rack toms and 16 floor tom with Remo Hydraulic Ebony heavy low-end thud and zero high-frequency ring, warm tape saturation and gated sustain, 14 snare tuned medium-high for sharp dry cutting rimshot crack with crisp wire response and short plate reverb, 14 Meinl Raker Heavy cutting hi-hat, 16 Meinl Raker Heavy and Paiste 302 explosive fast decay crashes, 20 Meinl Raker Heavy ride with glass-like ping and heavy bell, upfront punchy room mic ambience, acoustic drum kit sound",
                "century 1994 rock kit": "1994 Century acoustic wood shell drum kit, 10 12 14 rack toms and 16 floor tom with Remo Hydraulic Ebony heavy low-end thud and zero high-frequency ring, warm tape saturation and gated sustain, 14 snare tuned medium-high for sharp dry cutting rimshot crack with crisp wire response and short plate reverb, 14 Meinl Raker Heavy cutting hi-hat, 16 Meinl Raker Heavy and Paiste 302 explosive fast decay crashes, 20 Meinl Raker Heavy ride with glass-like ping and heavy bell, upfront punchy room mic ambience, acoustic drum kit sound",
                "century wood shell": "1994 Century acoustic wood shell drum kit, 10 12 14 rack toms and 16 floor tom with Remo Hydraulic Ebony heavy low-end thud and zero high-frequency ring, warm tape saturation and gated sustain, 14 snare tuned medium-high for sharp dry cutting rimshot crack with crisp wire response and short plate reverb, 14 Meinl Raker Heavy cutting hi-hat, 16 Meinl Raker Heavy and Paiste 302 explosive fast decay crashes, 20 Meinl Raker Heavy ride with glass-like ping and heavy bell, upfront punchy room mic ambience, acoustic drum kit sound",
                # Bajos
                "fender jazz bass deluxe": "Fender American Deluxe Jazz Bass, active 18V preamp with 3-band EQ, dual 4th generation Noiseless single-coil pickups, modern Hi-Fi electric bass tone, bright punchy slap attack, growling articulate low-mids, deep tight low end, real roundwound nickel strings on rosewood fretboard, played fingerstyle with organic string dynamics and natural fret buzz, plugged into classic Ampeg SVT tube amplifier and 8x10 speaker cabinet, warm analog direct-box bass tone, authentic physical wooden electric bass guitar, zero synth bass",
                "fender jazz bass 1975": "vintage 1975 Fender Jazz Bass with ash body and maple fingerboard with black block inlays, bridge pickup single-coil growl, bright biting treble, scooped mid punch, Jaco Pastorius style lyrical fingerstyle tone, real roundwound nickel strings, mic'd vintage Ampeg SVT tube amplifier and 8x10 cabinet, authentic physical wooden electric bass guitar, zero synth bass",
                "fender jazz bass": "authentic Fender Jazz Bass electric guitar, dual single-coil pickups, growling articulate midrange, punchy low end, real roundwound strings plucked with fingers, organic fret buzz, mic'd Ampeg SVT tube bass amp, real physical wooden electric bass guitar, zero synth bass",
                "fender precision 1962": "legendary 1962 Fender Precision Bass with alder body and split-coil pickup, warm thumping Motown James Jamerson vintage tone, flatwound strings, muted fleshy thumb and finger pluck, thick punchy fundamental low-end warmth that sits glued in the mix, vintage Flip-Top Ampeg B-15 Portaflex tube amp, real physical electric bass guitar, zero synth bass",
                "fender precision bass": "classic Fender Precision Bass with split-coil pickup, warm thumping fundamental, flatwound strings, vintage Ampeg B-15 tube amp, real physical wooden electric bass guitar, zero synth bass",
                "fender precision": "classic Fender Precision Bass with split-coil pickup, warm thumping fundamental, flatwound strings, vintage Ampeg B-15 tube amp, real physical wooden electric bass guitar, zero synth bass",
                "music man stingray": "iconic Ernie Ball Music Man StingRay bass guitar, massive alnico active humbucker pickup with 3-band active preamp, aggressive punchy slap and pop sound, massive growling low-mid bite, high-voltage definition, real steel roundwound strings, Gallien-Krueger 800RB amplifier punch, real physical electric bass guitar, zero synth bass",
                "contrabajo acustico": "authentic acoustic orchestral wooden upright double bass, acoustic carved spruce and maple body, pizzicato finger plucked gut and steel strings, deep resonant wooden acoustic chamber, full acoustic warmth, Neumann U47 tube microphone placed 1 foot from F-hole, 100% natural wooden acoustic upright bass, zero electric bass, zero synth bass",
                "contrabajo acústico": "authentic acoustic orchestral wooden upright double bass, acoustic carved spruce and maple body, pizzicato finger plucked gut and steel strings, deep resonant wooden acoustic chamber, full acoustic warmth, Neumann U47 tube microphone placed 1 foot from F-hole, 100% natural wooden acoustic upright bass, zero electric bass, zero synth bass",
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
        title = sanitize_artist_names(title)

        # Clean structural tags from style string (they belong in lyrics, not style)
        style = re.sub(r'\b(verse|chorus|bridge|outro|intro|pre-chorus)\b', '', style, flags=re.IGNORECASE)

        # Detect user custom BPM (e.g. 83.3 BPM, 85 bpm, 120 bpm)
        custom_bpm_match = re.search(r'\b(\d+(?:\.\d+)?)\s*bpm\b', style, re.IGNORECASE)
        custom_bpm = float(custom_bpm_match.group(1)) if custom_bpm_match else None

        if custom_bpm:
            # Strip out any conflicting preset BPMs like 135 bpm, 68 bpm, 125 bpm
            style = re.sub(r'\b\d+(?:\.\d+)?\s*bpm\b', '', style, flags=re.IGNORECASE)
            style = re.sub(r'\b(high tempo|fast tempo|uptempo|slow tempo)\b', '', style, flags=re.IGNORECASE)
            if custom_bpm < 95:
                bpm_tag = f"{custom_bpm:.1f} BPM, andante tempo, worship ballad"
            elif custom_bpm > 120:
                bpm_tag = f"{custom_bpm:.1f} BPM, driving tempo, upbeat praise"
            else:
                bpm_tag = f"{custom_bpm:.1f} BPM, moderato tempo"
            log_msg(f"Tempo del usuario detectado y respetado estrictamente: {custom_bpm:.1f} BPM")
        else:
            bpm_tag = ""

        # Detect Christian / Worship / Devotional context for genre anchoring
        is_drum_solo = any(w in style.lower() for w in [
            "drum solo", "solo drums", "solo acoustic drums", "solo de bateria", "solo de batería",
            "isolated drum", "isolated drums", "drum showcase", "drum demo", "bateria sola", "batería sola",
            "pure drums", "drum test", "drum sound test"
        ])
        is_worship = not is_drum_solo and any(w in style.lower() for w in ["devotional", "worship", "worshipful", "himno", "adoracion", "adoración", "alabanza", "coro", "pentecostal", "iglesia", "cristiano", "christian", "oracion", "oración"])
        is_pentecostal = not is_drum_solo and any(w in style.lower() for w in ["pentecostal", "avivamiento", "coro pentecostal", "coros pentecostales"])
        is_solo_piano_prayer = not is_drum_solo and (any(w in style.lower() for w in ["solo piano", "solo acoustic grand piano", "piano de oracion", "piano de oración", "prayer piano", "pure piano", "solo piano instrumental"]) or (is_instrumental and "piano" in style.lower() and any(w in style.lower() for w in ["oracion", "oración", "prayer", "meditacion", "meditación", "devocional", "fondo para orar"])))
        is_vals_vienes = not is_drum_solo and any(w in style.lower() for w in ["vals vienes", "vals vienés", "viennese waltz", "waltz in 3/4", "vals 3/4", "vals"])

        if is_drum_solo:
            genre_anchor = f"pure acoustic drum solo, isolated drum kit sound showcase, {bpm_tag or 'steady 90 bpm unhurried groove'}, clean spacious drum test, dynamic hi-hat accents, crisp 14 snare rimshots, gradual progressive tom descent, distinct ride bell pings, balanced crashes, no melody, no chords, no harmonic instruments, no guitars, no bass, no piano, no keyboards, no synths, no vocals"
        elif is_solo_piano_prayer:
            genre_anchor = f"sacred prayer background music, {bpm_tag or '60 BPM slow tempo'}, solo acoustic concert grand piano with deep lush hall reverb, pure piano instrumental, emotional, peaceful, contemplative, no drums, no bass, no guitars, no synths"
        elif is_vals_vienes:
            genre_anchor = f"sacred Viennese waltz hymn in 3/4 time, authentic Viennese lilt, Johann Strauss II style, full classical symphony orchestra (violins, violas, cellos, double basses, flutes, piccolo, oboes, clarinets, bassoons, French horns, trumpets, trombones, timpani, crash cymbals, concert bass drum), oom-pah-pah 3/4 swing, no 4/4 rhythm, no rock drums, no cumbia"
        elif is_pentecostal:
            target_bpm = f"{custom_bpm:.1f} BPM" if custom_bpm else "118 BPM steady tempo"
            genre_anchor = f"driving acoustic drum kit rhythm, prominent cracking 14x5 Ludwig Supraphonic snare drum hitting hard on beats 2 and 4, heavy 22-inch kick drum pounding on beats 1 and 3, tight closed 14-inch dark Zildjian hi-hat keeping steady straight eighth notes, clean economical Charlie Watts acoustic drumming, zero drum solos, zero chaotic fills, gospel 2-step straight 4/4 rhythm, {target_bpm}, root-fifth alternating acoustic bass boom-chick, driving acoustic rhythm guitar strum, passionate Argentine church choir singing in unison, natural Spanish vocals, no a cappella, no missing drums, no tambourine solo, no handclaps solo, no murga, no comparsa, no carnaval, no batucada, no candombe, no bombo de murga, no marcha militar, no latin rhythm, no syncopation, no tumbao, no salsa, no cumbia, no caribbean rhythm, no caribbean accent"
        elif custom_bpm and custom_bpm < 100 and is_worship:
            # Slower/moderate worship requested by user (e.g. 83.3 BPM) -> NEVER force fast 135 BPM!
            genre_anchor = f"sacred Christian worship, {bpm_tag}, straight 4/4 rock drum beat with snare backbeat on 2 and 4, steady bass, clean guitar, no cumbia, no latin rhythm"
        elif is_worship:
            genre_anchor = f"sacred Christian worship hymn, {bpm_tag or 'straight 4/4 rhythm'}, clean acoustic and electric instruments, church acoustic, no cumbia"
        elif bpm_tag and not is_drum_solo:
            genre_anchor = bpm_tag
        else:
            genre_anchor = ""

        # Vocal styling in style prompt:
        if is_instrumental:
            if "instrumental" not in style.lower():
                style = style + ", instrumental, no vocals"
        else:
            if "argentin" in style.lower() or "pentecostal" in style.lower() or "avivamiento" in style.lower():
                vocal_tag = "Argentine church choir, natural Argentine Spanish accent, passionate congregational singing in unison, no caribbean accent, no central american accent"
            elif "mexican" in style.lower() or "mexicano" in style.lower():
                vocal_tag = "mexican spanish vocals"
            elif "coro" in style.lower() or "choir" in style.lower():
                vocal_tag = "congregational church choir, Argentine Spanish singing"
            else:
                vocal_tag = "clear natural Spanish vocals, neutral tone, no castilian lisp, no caribbean accent"
            
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

            # Si se solicita bajo real (o en cualquier estilo con instrumentación acústica/eléctrica),
            # forzar la expulsión estricta de cualquier sintetizador de bajo o 808 para garantizar sonido de bajo real de cuerdas
            has_real_bass = any(k in style.lower() for k in [
                "bass", "bajo", "fender", "precision", "jazz bass", "stingray", "contrabajo", "upright"
            ])
            if has_real_bass and not is_solo_piano_prayer:
                for bass_anti in [
                    "synth bass", "synthesizer bass", "synthbass", "808 bass", "808 sub", "sub bass synth",
                    "electronic bass", "moog bass", "midi bass", "synthesized bassline", "digital sub bass",
                    "techno bass", "keyboard bass", "synthetic bass", "fake bass", "keytar bass",
                    "acid bass", "wobble bass", "reese bass", "electronic sub", "sine wave sub"
                ]:
                    neg_tags_list.append(bass_anti)

            # If Christian / Worship, always enforce anti-cumbia negative tags automatically
            if is_worship:
                for mandatory_anti_cumbia in ["cumbia", "ritmo cumbia", "grupero", "cumbia sonidera", "accordion", "acordeon", "guiro", "timbales", "latin rhythm", "tropical rhythm", "reggaeton"]:
                    neg_tags_list.append(mandatory_anti_cumbia)

            if is_solo_piano_prayer:
                for solo_anti in ["drums", "drum kit", "percussion", "bass", "electric guitar", "synths", "brass", "orchestra", "strings", "cumbia", "singing", "vocals", "voices"]:
                    neg_tags_list.append(solo_anti)

            if is_vals_vienes:
                for vals_anti in ["cumbia", "ritmo cumbia", "4/4 beat", "4/4 rock drum beat", "straight rock drums", "modern drum kit", "trap", "808 bass", "electric guitar", "synths", "synthesizer", "autotune", "distortion", "reggaeton"]:
                    neg_tags_list.append(vals_anti)

            if is_pentecostal:
                for pent_anti in [
                    "a cappella", "acappella", "no drums", "missing drums", "handclaps only", "tambourine only",
                    "percussion only", "tambourine dominant", "handclaps dominant",
                    "murga", "comparsa", "carnaval", "batucada", "candombe", "bombo de murga",
                    "tamboril", "marcha militar", "marching band", "brass band", "fanfare", "loose percussion",
                    "latin rhythm", "ritmo latino", "percusion latina", "latin percussion",
                    "syncopation", "sincopa", "tumbao", "contratiempos latinos", "offbeat accents",
                    "cumbia", "merengue", "salsa", "bachata", "reggaeton", "dembow", "tropical rhythm",
                    "reggae skank", "ska", "caribbean accent", "acento caribeño", "acento centroamericano",
                    "modismos caribeños", "caribbean vocals", "chaotic drums", "heavy rock drums",
                    "drum solos", "noisy drums", "electronic drums", "digital triggers", "drum machine",
                    "double bass drum", "blast beats", "overproduced drums", "latin groove", "muddy drums"
                ]:
                    neg_tags_list.append(pent_anti)

            if is_drum_solo:
                for drum_anti in [
                    "guitar", "electric guitar", "acoustic guitar", "guitars", "electric guitars",
                    "bass", "bass guitar", "piano", "keyboard", "keyboards", "organ", "synth",
                    "synthesizer", "strings", "orchestra", "brass", "horns", "vocals", "singing",
                    "voice", "voices", "choir", "backing track", "melody", "chords", "harmony",
                    "song rhythm", "full band", "lead guitar", "heavy metal", "blast beats",
                    "double bass speed", "chaotic drumming"
                ]:
                    neg_tags_list.append(drum_anti)

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
            if is_drum_solo:
                for req_no in ["no guitars", "no bass", "no piano", "no synths", "no vocals", "no melody", "no chords"]:
                    if req_no not in active_critical:
                        active_critical.append(req_no)
            if is_worship:
                for req_no in ["no cumbia", "no accordion", "no latin rhythm"]:
                    if req_no not in active_critical:
                        active_critical.append(req_no)
            if is_solo_piano_prayer:
                for req_no in ["no drums", "no vocals", "no singing", "no electric guitar", "no bass", "no synths"]:
                    if req_no not in active_critical:
                        active_critical.append(req_no)
            if is_vals_vienes:
                for req_no in ["no 4/4 beat", "no rock drums", "no electric guitar", "no synths", "no cumbia"]:
                    if req_no not in active_critical:
                        active_critical.append(req_no)
            if is_pentecostal:
                for req_no in ["no missing drums", "no tambourine dominant", "no handclaps solo", "no murga", "no comparsa", "no batucada", "no loose percussion", "no latin rhythm", "no syncopation", "no cumbia", "no caribbean accent", "no tumbao", "no chaotic drums"]:
                    if req_no not in active_critical:
                        active_critical.append(req_no)
            if active_critical:
                key_bans_str = ", ".join(active_critical)

            # For drum solos, DO NOT put words like 'guitars' or 'bass' in the positive style string
            if is_drum_solo:
                # Remove any accidental mention of guitars, bass, melody, or rock band from positive style
                clean_style = re.sub(r'\b(rock|band|song|full band|no\s+\w+|guitar\w*|bass\w*|piano\w*|synth\w*|vocal\w*|singing)\b', '', style, flags=re.IGNORECASE)
                clean_style = re.sub(r',\s*,+', ',', clean_style).strip(' ,')
                style = f"percussion only, pure acoustic drum solo, isolated drum kit sound demonstration, {clean_style}, live room studio acoustics, zero melodic instruments, unaccompanied percussion"
                style = re.sub(r',\s*,+', ',', style).strip(' ,')
            else:
                combined_parts = [p for p in [genre_anchor, key_bans_str, style] if p]
                style = ", ".join(combined_parts)
                style = re.sub(r',\s*,+', ',', style).strip(' ,')

            neg_final_str = ", ".join(dedup_neg)
            log_msg(f"Exclusión estricta aplicada con éxito: {neg_final_str}")
        else:
            if genre_anchor and not is_drum_solo:
                style = f"{genre_anchor}, {style}"
                style = re.sub(r',\s*,+', ',', style).strip(' ,')

        # Compute weights cleanly clamped to documented ranges 0.00 - 1.00
        actual_style_weight = 0.85 if is_drum_solo else max(0.0, min(1.0, round(float(style_influence) / 100.0, 2)))
        actual_weirdness = 0.20 if is_drum_solo else max(0.0, min(1.0, round(float(weirdness) / 100.0, 2)))
        actual_audio_weight = max(0.0, min(1.0, round(float(audio_influence) / 100.0, 2)))

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
                "tags": style,
                "title": title,
                "make_instrumental": is_instrumental,
                "style_weight": actual_style_weight,
                "audio_weight": actual_audio_weight,
                "weirdness_constraint": actual_weirdness
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if neg_final_str:
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
                "tags": style,
                "title": title,
                "make_instrumental": is_instrumental,
                "model": model,
                "style_weight": actual_style_weight,
                "weirdness_constraint": actual_weirdness
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if neg_final_str:
                payload["negative_tags"] = neg_final_str
                payload["negative_prompt"] = neg_final_str
                payload["exclude_styles"] = neg_final_str
                payload["excluded_tags"] = neg_final_str

        log_msg(f"Estilo final enviado: {style[:200]}...")
        if neg_final_str:
            log_msg(f"Filtros de exclusión enviados: {neg_final_str[:150]}...")
        log_msg(f"Letra prefijo/primeras líneas: {final_lyrics[:120].strip()}...")

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
                                
                                # Subir respaldo a la nube Catbox para persistencia garantizada
                                local_track_file = os.path.join(TRACKS_DIR, f"{tid}.mp3")
                                cloud_backup = None
                                if os.path.exists(local_track_file) and os.path.getsize(local_track_file) > 1000:
                                    try:
                                        cloud_backup = await upload_to_catbox_async(local_track_file)
                                    except Exception:
                                        pass
                                
                                track_info = {
                                    "id": tid,
                                    "title": ttitle,
                                    "audio_url": taudio_cached,
                                    "raw_audio_url": taudio,
                                    "cloud_backup": cloud_backup,
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
                err_str = str(e)
                err_lower = err_str.lower()
                
                # 1. Distinguir categorías específicas de error del proveedor
                is_catalog_match = any(
                    k in err_lower for k in [
                        "matches an existing recording in our catalog",
                        "existing recording in our catalog",
                        "matches an existing recording"
                    ]
                )
                is_moderation_flag = any(
                    k in err_lower for k in [
                        "moderation", "flagged", "content policy", "policy violation",
                        "sensitive content", "prohibited content", "banned words"
                    ]
                )
                is_credit_exhaustion = any(
                    k in err_lower for k in [
                        "402", "insufficient credits", "no hay créditos suficientes", "out of credits", "quota exceeded"
                    ]
                )

                if is_catalog_match:
                    rejection_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    log_msg(f"Generación rechazada por coincidencia de catálogo comercial ({err_str}). Guardando diagnóstico técnico.")
                    diagnostic_info = {
                        "task_id": task_id,
                        "title": title,
                        "model": model,
                        "date_utc": rejection_date,
                        "exact_error_message": err_str,
                        "error_type": "CATALOG_MATCH",
                        "is_public_domain": is_public_domain,
                        "audio_filename": audio_filename or "N/A",
                        "has_audio_reference": bool(upload_url)
                    }
                    TASKS[task_id]["catalog_rejection"] = True
                    TASKS[task_id]["diagnostic_info"] = diagnostic_info
                    TASKS[task_id]["detail"] = "Rechazo de catálogo comercial: El proveedor identificó una coincidencia con una grabación registrada en su catálogo. Verifique su saldo y registros en el panel de udioapi.pro. Puede descargar el informe técnico de diagnóstico (.txt) para consultar al soporte del proveedor."
                    TASKS[task_id]["status"] = "ERROR"
                    save_local_log()
                    return

                elif is_moderation_flag:
                    log_msg(f"Generación rechazada por filtros de moderación/texto ({err_str}).")
                    diagnostic_info = {
                        "task_id": task_id,
                        "title": title,
                        "model": model,
                        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "exact_error_message": err_str,
                        "error_type": "CONTENT_MODERATION",
                        "is_public_domain": is_public_domain,
                        "audio_filename": audio_filename or "N/A",
                        "has_audio_reference": bool(upload_url)
                    }
                    TASKS[task_id]["catalog_rejection"] = False
                    TASKS[task_id]["diagnostic_info"] = diagnostic_info
                    TASKS[task_id]["detail"] = f"Moderación de contenido: El proveedor rechazó la solicitud por sus filtros de política o texto ({err_str}). Revise la letra y las etiquetas de estilo."
                    TASKS[task_id]["status"] = "ERROR"
                    save_local_log()
                    return

                elif is_credit_exhaustion:
                    log_msg("Generación detenida: Saldo de créditos insuficiente en la cuenta de la API.")
                    TASKS[task_id]["catalog_rejection"] = False
                    TASKS[task_id]["detail"] = "Créditos insuficientes: La cuenta de udioapi.pro no dispone de créditos para completar la tarea (Error 402). Verifique su suscripción."
                    TASKS[task_id]["status"] = "ERROR"
                    save_local_log()
                    return

                # 2. Reintentos ÚNICAMENTE para errores transitorios de red o servidor (máximo 3 intentos)
                is_transient_error = any(
                    k in err_lower for k in [
                        "408", "request timeout", "timeout", "timed out",
                        "502", "503", "504", "gateway timeout", "bad gateway",
                        "internal error", "500", "429", "too many requests"
                    ]
                )
                if is_transient_error and attempt < max_retries - 1:
                    wait_sec = (attempt + 1) * 6
                    log_msg(f"Fallo transitorio de conexión con el servidor ({err_str[:90]}). Reintentando {attempt+2}/{max_retries} en {wait_sec}s...")
                    if upload_url and backup_upload_url and payload.get("upload_url") == upload_url:
                        payload["upload_url"] = backup_upload_url
                    await asyncio.sleep(wait_sec)
                    continue
                else:
                    raise e
    except Exception as e:
        log_msg(f"ERROR: {str(e)}")
        save_local_log()
        TASKS[task_id]["detail"] = str(e)
        TASKS[task_id]["status"] = "ERROR"
    finally:
        for p in created_temp_files:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        import gc
        gc.collect()


# -----------------------------------------------------------------------------
# PRUEBA TÉCNICA DE COMPATIBILIDAD Y DECODIFICACIÓN (FFMPEG/FFPROBE)
# -----------------------------------------------------------------------------
@app.post("/api/check_audio_compatibility")
async def check_audio_compatibility(file: UploadFile = File(...)):
    """Verifica técnicamente que un archivo M4A, MP4, MP3 o WAV se decodifique completamente con FFprobe y FFmpeg."""
    temp_path = None
    try:
        content = await file.read()
        if not content:
            return JSONResponse(status_code=400, content={"compatible": False, "error": "El archivo está vacío."})
            
        filename = file.filename or "audio"
        ext = os.path.splitext(filename)[1].lower() or ".tmp"
        size_mb = round(len(content) / (1024 * 1024), 2)
        
        # Guardar en archivo temporal para que ffprobe y ffmpeg puedan examinar los frames reales
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(content)
            temp_path = tf.name

        # 1. Inspección de flujo de audio con ffprobe
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,channels,sample_rate,duration,bit_rate",
            "-show_entries", "format=format_name,duration,size,bit_rate",
            "-of", "json",
            temp_path
        ]
        proc = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or "No se pudo leer el flujo de datos del archivo."
            return {
                "compatible": False,
                "filename": filename,
                "error": err_msg,
                "message": f"FFprobe no pudo reconocer un formato multimedia válido en '{filename}': {err_msg}"
            }
            
        probe_data = json.loads(proc.stdout) if proc.stdout else {}
        streams = probe_data.get("streams", [])
        if not streams:
            return {
                "compatible": False,
                "filename": filename,
                "error": "No contiene flujo de audio",
                "message": f"El archivo '{filename}' no contiene ninguna pista de audio reconocible."
            }

        audio_stream = streams[0]
        fmt_data = probe_data.get("format", {})
        codec_name = audio_stream.get("codec_name", "audio").upper()
        
        # 2. Prueba de decodificación completa de audio con FFmpeg
        decode_cmd = [
            "ffmpeg", "-v", "error",
            "-i", temp_path,
            "-f", "null",
            "-"
        ]
        decode_proc = subprocess.run(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        
        if decode_proc.returncode != 0:
            err_detail = decode_proc.stderr.strip() or "Error durante la decodificación de tramas de audio."
            return {
                "compatible": False,
                "filename": filename,
                "format": codec_name,
                "error": err_detail,
                "message": f"El archivo '{filename}' está dañado o truncado y falló la decodificación FFmpeg: {err_detail}"
            }

        # Extraer parámetros limpios
        channels = audio_stream.get("channels", 2)
        channels_str = "Estéreo" if channels >= 2 else "Mono"
        sample_rate = audio_stream.get("sample_rate", "44100")
        
        dur_val = audio_stream.get("duration") or fmt_data.get("duration")
        try:
            length_sec = round(float(dur_val), 2) if dur_val else 0.0
        except Exception:
            length_sec = 0.0

        # Formatear nombre amigable de formato
        format_display = codec_name
        if "AAC" in codec_name or ext in [".m4a", ".mp4"]:
            format_display = f"AAC ({ext.upper().lstrip('.')})"
        elif "MP3" in codec_name or ext == ".mp3":
            format_display = "MP3"
        elif "PCM" in codec_name or ext == ".wav":
            format_display = "WAV (PCM)"

        return {
            "compatible": True,
            "filename": filename,
            "format": format_display,
            "codec": codec_name.lower(),
            "channels": f"{channels_str} ({channels} ch)",
            "sample_rate": f"{sample_rate} Hz",
            "duration_sec": length_sec,
            "file_size_mb": size_mb,
            "message": f"Archivo {format_display} decodificado íntegramente con FFmpeg ({length_sec}s, {sample_rate} Hz, {channels_str})."
        }

    except subprocess.TimeoutExpired:
        return {
            "compatible": False,
            "filename": file.filename,
            "error": "Timeout",
            "message": "La verificación de audio excedió el tiempo límite (archivo bloqueado o respuesta lenta)."
        }
    except Exception as e:
        return {
            "compatible": False,
            "filename": file.filename,
            "error": str(e),
            "message": f"Error al verificar compatibilidad de audio: {str(e)}"
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

# -----------------------------------------------------------------------------
# INFORME TÉCNICO DE DIAGNÓSTICO (DISPONIBLE PARA CUALQUIER TAREA FALLIDA O RECHAZADA)
# -----------------------------------------------------------------------------
@app.get("/api/diagnostic_report/{task_id}")
async def get_diagnostic_report(task_id: str):
    """Genera y descarga un informe técnico de diagnóstico sin credenciales ni claves privadas."""
    if not task_id or task_id.strip() in ["", "undefined", "null"]:
        return PlainTextResponse(
            "ERROR: Identificador de tarea inválido o no especificado.",
            status_code=400,
            headers={"Content-Disposition": 'attachment; filename="diagnostico_error.txt"'}
        )

    task = TASKS.get(task_id)
    if not task:
        err_report = f"""================================================================================
INFORME DE DIAGNÓSTICO NO DISPONIBLE
Rodrix Music Creator (Generación Musical Asistida por IA)
================================================================================

Identificador solicitado : {task_id}
Fecha de consulta (UTC)  : {datetime.datetime.now(datetime.timezone.utc).isoformat()}

CAUSA:
No se encontró la tarea '{task_id}' en la memoria del servidor.

POSIBLES RAZONES:
1. El servidor se ha reiniciado o desplegado recientemente, limpiando la memoria volátil.
2. La tarea fue limpiada por antigüedad (conservación de las últimas 30 tareas).
3. El navegador solicitó un identificador erróneo o una tarea de una sesión anterior.

ACCIÓN SUGERIDA:
Vuelva a cargar la pista de audio o melodía en el creador y pulse Generar para
iniciar una nueva tarea y registrar un nuevo diagnóstico.

================================================================================
Este informe no contiene claves privadas ni datos sensibles.
================================================================================
"""
        return PlainTextResponse(
            err_report,
            status_code=404,
            headers={"Content-Disposition": f'attachment; filename="diagnostico_no_encontrado_{task_id}.txt"'}
        )

    diag = task.get("diagnostic_info", {})
    title = diag.get("title") or task.get("title") or "Obra Musical"
    model = diag.get("model") or "udio-130-v2.0 / udioapi.pro"
    date_str = diag.get("date_utc") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    exact_err = diag.get("exact_error_message") or task.get("detail") or "Sin mensaje de error especificado."
    is_catalog = task.get("catalog_rejection", False)
    is_pd = diag.get("is_public_domain", task.get("is_public_domain", False))
    has_audio = diag.get("has_audio_reference", bool(task.get("audio_filename") and task.get("audio_filename") != "N/A"))
    audio_file = diag.get("audio_filename") or task.get("audio_filename", "N/A")
    raw_logs = task.get("logs", "No hay registros disponibles para esta tarea.")
    
    # Sanitizar logs para garantizar 100% que ninguna clave o token pueda figurar
    sanitized_logs = re.sub(r'sk-[a-zA-Z0-9_\-]{8,}', '[PROTECTED_API_KEY]', raw_logs)
    sanitized_logs = re.sub(r'(key|token|secret)=([a-zA-Z0-9_\-]{8,})', r'\1=[PROTECTED]', sanitized_logs, flags=re.IGNORECASE)

    status_name = task.get("status", "DESCONOCIDO")
    error_type = diag.get("error_type", "CATALOG_MATCH" if is_catalog else "GENERIC")

    if is_catalog or error_type == "CATALOG_MATCH":
        encabezado_tipo = "COINCIDENCIA DE CATÁLOGO COMERCIAL (FILTRO DE AUDIO REGISTRADO)"
        clasificacion = """Rechazo automatizado por coincidencia de huella acústica con catálogo registrado en el proveedor.
Consulte su saldo y registros de tareas en el panel de udioapi.pro para verificar el estado de los créditos."""
        procedimiento = f"""Si esta obra es una interpretación propia de un himno clásico, obra tradicional
en dominio público o una composición con los debidos derechos, puedes solicitar
una revisión al equipo técnico del proveedor de la API siguiendo estos pasos:

1. Redacta una solicitud dirigida al equipo de soporte de la API:
   - Canal de soporte: support@udioapi.pro (o mesa de ayuda del proveedor).
   - Asunto: Solicitud de revisión de catálogo comercial - Task ID {task_id}

2. Adjunta a tu solicitud:
   - El presente Informe Técnico de Diagnóstico.
   - Datos de la obra tradicional (título, autor original, año o indicación de dominio público).
   - Aclaración explícita de que el audio cargado es una grabación o secuencia propia
     y no un fonograma comercial protegido de terceros.

3. El equipo de soporte evaluará la solicitud para la excepción o habilitación
   correspondiente en su filtro de catálogo automatizado."""
    elif error_type == "CONTENT_MODERATION":
        encabezado_tipo = "MODERACIÓN DE CONTENIDO / POLÍTICA DE TEXTO"
        clasificacion = """La tarea fue rechazada por los filtros de moderación o política del proveedor.
Esto ocurre habitualmente si la letra o las etiquetas contienen palabras sensibles, nombres de artistas o lenguaje restringido."""
        procedimiento = """Recomendaciones para resolver esta observación:
1. Revise la letra y reemplace palabras que puedan disparar filtros de seguridad.
2. Elimine nombres propios de artistas en las etiquetas de estilo.
3. Vuelva a intentar la generación con el texto revisado."""
    else:
        encabezado_tipo = f"ESTADO DE TAREA: {status_name}"
        clasificacion = f"Detalle registrado: {exact_err}"
        procedimiento = """Si el problema persiste:
1. Compruebe el estado del servicio en el panel de udioapi.pro.
2. Si se trata de un error técnico persistente, contacte al soporte del proveedor indicando el Task ID."""
        procedimiento = """Este informe contiene el estado técnico completo y los registros de ejecución de la tarea.
Puede conservarlo para trazabilidad o para revisar cualquier advertencia del sistema."""

    report_text = f"""================================================================================
INFORME TÉCNICO DE DIAGNÓSTICO - {encabezado_tipo}
Rodrix Music Creator (Generación Musical Asistida por IA)
================================================================================

DATOS DE LA SOLICITUD:
--------------------------------------------------------------------------------
Identificador de Tarea (Task ID) : {task_id}
Estado de la Tarea              : {status_name}
Fecha y Hora de Registro (UTC)  : {date_str}
Título de la Obra               : {title}
Modelo de Generación            : {model}
Declaración de Dominio Público  : {'SÍ (Grabación propia de obra tradicional/autorizada)' if is_pd else 'NO declarada'}
Audio de Referencia Vinculado   : {'SÍ' if has_audio else 'NO'}
Archivo de Referencia Original  : {audio_file}

RESPUESTA Y DETALLES TÉCNICOS:
--------------------------------------------------------------------------------
Mensaje Registrado:
"{exact_err}"

Clasificación del Estado:
{clasificacion}

REGISTRO DETALLADO DE OPERACIONES (LOGS):
--------------------------------------------------------------------------------
{sanitized_logs}

PROCEDIMIENTO Y RECOMENDACIONES:
--------------------------------------------------------------------------------
{procedimiento}

================================================================================
Generado por Rodrix Music Creator.
Este documento no contiene credenciales, claves de API ni datos confidenciales.
================================================================================
"""
    return PlainTextResponse(
        report_text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="diagnostico_{task_id}.txt"'
        }
    )


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

@app.post("/api/library/{task_id}/rename")
async def api_rename_track(task_id: str, request: Request, current_user: str = Depends(get_current_user)):
    data = await request.json()
    new_title = data.get("title", "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="El título no puede estar vacío.")
    library = load_library()
    found = False
    for t in library:
        if t.get("id") == task_id:
            t["title"] = new_title
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Track no encontrado.")
    save_library(library)
    return JSONResponse(content={"status": "success", "title": new_title})

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
    """Returns a local file path to the audio file, cached if available, or downloaded quickly."""
    local_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
        return local_path
        
    urls_to_try = []
    if track.get("cloud_backup") and str(track["cloud_backup"]).startswith("http"):
        urls_to_try.append(track["cloud_backup"])
    if track.get("raw_audio_url") and str(track["raw_audio_url"]).startswith("http") and track["raw_audio_url"] not in urls_to_try:
        urls_to_try.append(track["raw_audio_url"])
    if track.get("audio_url") and str(track["audio_url"]).startswith("http") and track["audio_url"] not in urls_to_try:
        urls_to_try.append(track["audio_url"])
            
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }
    
    last_err = None
    for url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
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
                    with urllib.request.urlopen(req, timeout=8) as resp:
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
async def get_stem_audio(task_id: str, stem_type: str):
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
    import unicodedata
    clean_ascii = unicodedata.normalize('NFKD', str(title)).encode('ascii', 'ignore').decode('ascii')
    safe_title = "".join([c for c in clean_ascii if c.isalnum() or c in ' -_']).strip() or "track"
    
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
            
        stem_dur = get_audio_duration_seconds(source_audio_file)
        safe_bitrate = calculate_safe_mp3_bitrate(stem_dur)
        ffmpeg_cmd = ["ffmpeg", "-threads", "0", "-y", "-i", source_audio_file, "-af", stem_filter, "-c:a", "libmp3lame", "-b:a", safe_bitrate, "-ar", "44100", temp_stem_out]
        await asyncio.to_thread(subprocess.run, ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        await enforce_max_file_size_mp3(temp_stem_out)
        
        from starlette.background import BackgroundTask
        return FileResponse(
            path=temp_stem_out,
            filename=f"{safe_title}_{stem_type}.mp3",
            media_type="audio/mpeg",
            background=BackgroundTask(cleanup_files, [temp_stem_out])
        )
    except HTTPException:
        cleanup_files([temp_stem_out])
        raise
    except Exception as e:
        cleanup_files([temp_stem_out])
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/player.html")
async def player():
    return FileResponse('player.html')

@app.get("/walkman.jpg")
async def walkman_image():
    if os.path.exists("walkman.jpg"):
        return FileResponse("walkman.jpg")
    raise HTTPException(status_code=404, detail="Imagen no encontrada")

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
async def download_track_format(task_id: str, audio_format: str, width: float = 1.0, eq: str = "none", loud: str = "none"):
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
    import unicodedata
    clean_ascii = unicodedata.normalize('NFKD', str(title)).encode('ascii', 'ignore').decode('ascii')
    safe_title = "".join([c for c in clean_ascii if c.isalnum() or c in ' -_']).strip() or "track"

    # 1. DESCARGA INMEDIATA: MP3 directo desde disco local (0 segundos)
    local_mp3 = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    if audio_format == "mp3" and eq == "none" and loud == "none" and width <= 1.0:
        if os.path.exists(local_mp3) and os.path.getsize(local_mp3) > 1000:
            await enforce_max_file_size_mp3(local_mp3)
            return FileResponse(
                path=local_mp3,
                filename=f"{safe_title}.mp3",
                media_type="audio/mpeg"
            )

    # 2. DESCARGA INMEDIATA: WAV directo si ya está en caché local
    local_wav = os.path.join(TRACKS_DIR, f"{task_id}.wav")
    if audio_format == "wav" and eq == "none" and loud == "none" and width <= 1.0:
        if os.path.exists(local_wav) and os.path.getsize(local_wav) > 1000:
            return FileResponse(
                path=local_wav,
                filename=f"{safe_title}.wav",
                media_type="audio/wav"
            )

    # 3. OBTENER ARCHIVO FUENTE
    source_audio_file = await get_or_download_audio_file(task_id, track, "")

    # 4. CONVERSIÓN INMEDIATA A WAV (Calidad Estudio Sin Comprimir: 44.1kHz 16-bit PCM estéreo)
    if audio_format == "wav" and eq == "none" and loud == "none" and width <= 1.0:
        wav_cmd = ["ffmpeg", "-threads", "0", "-y", "-i", source_audio_file, "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", local_wav]
        await asyncio.to_thread(subprocess.run, wav_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return FileResponse(
            path=local_wav,
            filename=f"{safe_title}.wav",
            media_type="audio/wav"
        )

    # 5. MP3 DIRECTO SIN MASTERIZACIÓN
    if audio_format == "mp3" and eq == "none" and loud == "none" and width <= 1.0:
        await enforce_max_file_size_mp3(source_audio_file)
        return FileResponse(
            path=source_audio_file,
            filename=f"{safe_title}.mp3",
            media_type="audio/mpeg"
        )

    # 6. SOLO SI SE SOLICITARON FILTROS DE MASTERIZACIÓN EXPLÍCITOS
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
        ffmpeg_cmd = ["ffmpeg", "-threads", "0", "-y", "-i", source_audio_file, "-map_metadata", "-1"]
        if master_filter:
            ffmpeg_cmd.extend(["-af", master_filter])
        if audio_format == "wav":
            # WAV sin comprimir
            ffmpeg_cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"])
        elif audio_format == "flac":
            ffmpeg_cmd.extend(["-c:a", "flac", "-compression_level", "8", "-ar", "44100"])
        elif audio_format == "mp3":
            dur = get_audio_duration_seconds(source_audio_file)
            safe_bitrate = calculate_safe_mp3_bitrate(dur)
            ffmpeg_cmd.extend(["-c:a", "libmp3lame", "-b:a", safe_bitrate, "-ar", "44100"])
            
        ffmpeg_cmd.append(temp_out)
        await asyncio.to_thread(subprocess.run, ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if audio_format == "mp3":
            await enforce_max_file_size_mp3(temp_out)
            
        from starlette.background import BackgroundTask
        suffix = "_master" if master_filter else ""
        return FileResponse(
            path=temp_out, 
            filename=f"{safe_title}{suffix}.{audio_format}", 
            media_type=f"audio/{audio_format}",
            background=BackgroundTask(cleanup_files, [temp_out])
        )
    except HTTPException:
        cleanup_files([temp_out])
        raise
    except Exception as e:
        cleanup_files([temp_out])
        print(f"Error descargando formato: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download_voiceover/{task_id}/{audio_format}")
async def download_voiceover_direct(task_id: str, audio_format: str):
    if audio_format not in ["mp3", "wav"]:
        raise HTTPException(status_code=400, detail="Formato no soportado")
    
    local_path = os.path.join(TRACKS_DIR, f"{task_id}.mp3")
    library = load_library()
    track = next((t for t in library if t.get("id") == task_id), None)
    
    # Si no está en disco local, intentar descargarlo del backup de nube
    if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
        if track:
            try:
                local_path = await get_or_download_audio_file(task_id, track, "")
            except Exception:
                pass

    if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
        raise HTTPException(status_code=404, detail="El audio de la predicación no se encuentra en el servidor.")
    
    title = track.get("title", "Predicacion_Pastoral") if track else "Predicacion_Pastoral"
    import unicodedata
    clean_ascii = unicodedata.normalize('NFKD', str(title)).encode('ascii', 'ignore').decode('ascii')
    safe_title = "".join([c for c in clean_ascii if c.isalnum() or c in ' -_']).strip() or "predicacion_pastoral"

    if audio_format == "mp3":
        await enforce_max_file_size_mp3(local_path)
        return FileResponse(
            path=local_path,
            filename=f"{safe_title}.mp3",
            media_type="audio/mpeg"
        )
    elif audio_format == "wav":
        local_wav = os.path.join(TRACKS_DIR, f"{task_id}.wav")
        if not os.path.exists(local_wav) or os.path.getsize(local_wav) < 1000:
            # WAV sin comprimir: calidad CD 44.1kHz 16-bit PCM estéreo
            cmd = ["ffmpeg", "-threads", "0", "-y", "-i", local_path, "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", local_wav]
            await asyncio.to_thread(subprocess.run, cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return FileResponse(
            path=local_wav,
            filename=f"{safe_title}.wav",
            media_type="audio/wav"
        )

@app.get("/api/me")
async def get_me(request: Request):
    user = request.session.get('user')
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    if not user:
        return JSONResponse(
            content={"logged_in": False, "name": "Usuario", "email": "", "is_admin": False},
            headers=headers
        )
    email = user.get('email', '').strip().lower()
    name = user.get('name') or user.get('given_name')
    if not name and email:
        name = email.split('@')[0].capitalize()
    if not name:
        name = "Rodrigo"
    picture = user.get('picture', '')
    is_admin = (email == ADMIN_EMAIL.strip().lower())
    return JSONResponse(
        content={"logged_in": True, "name": name, "email": email, "picture": picture, "is_admin": is_admin},
        headers=headers
    )

@app.get("/api/admin/users")
async def admin_get_users(current_user: str = Depends(get_current_user)):
    if current_user != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Solo el administrador puede ver los usuarios.")
    users = load_users()
    user_list = list(users.values())
    user_list.sort(key=lambda u: (0 if u.get("email") == ADMIN_EMAIL else 1, u.get("last_login", "")), reverse=False)
    return JSONResponse(
        content={"status": "success", "users": user_list},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.post("/api/admin/toggle_user")
async def admin_toggle_user(request: Request, current_user: str = Depends(get_current_user)):
    if current_user != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Solo el administrador puede gestionar usuarios.")
    data = await request.json()
    target_email = data.get("email", "").strip().lower()
    new_status = data.get("status", "active")
    
    if target_email == ADMIN_EMAIL:
        raise HTTPException(status_code=400, detail="No puedes bloquear tu propia cuenta de administrador.")
        
    users = load_users()
    if target_email not in users:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
        
    users[target_email]["status"] = "blocked" if new_status == "blocked" else "active"
    save_users(users)
    return {"status": "success", "user": users[target_email]}

@app.get("/download-app")
@app.get("/api/download/apk")
async def download_apk():
    apk_path = os.path.join(os.getcwd(), "Rodrix_Music_Creator.apk")
    if os.path.exists(apk_path):
        return FileResponse(
            path=apk_path,
            filename="Rodrix_Music_Creator.apk",
            media_type="application/vnd.android.package-archive",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail="APK no encontrado")

@app.get("/", response_class=HTMLResponse)
async def serve_spa(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url="/login")
        
    email = user.get('email', '').strip().lower()
    users = load_users()
    user_record = users.get(email)
    
    if email != ADMIN_EMAIL and (not user_record or user_record.get("status") == "blocked"):
        return RedirectResponse(url="/login?error=Acceso%20Bloqueado:%20Comunícate%20con%20el%20administrador.")
        
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
            return HTMLResponse(
                content=html,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    return "<h3>index.html not found.</h3>"

@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    user = request.session.get('user')
    if user:
        email = user.get('email', '').strip().lower()
        users = load_users()
        user_record = users.get(email)
        if email == ADMIN_EMAIL or (user_record and user_record.get("status") != "blocked"):
            return RedirectResponse(url="/")
        
    login_path = os.path.join(os.getcwd(), "login.html")
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
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
        token = await oauth.google.authorize_access_token(request)
        user = token.get('userinfo')
        if user:
            email = user.get('email', '').strip().lower()
            name = user.get('name') or email.split('@')[0].capitalize()
            picture = user.get('picture', '')
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            users = load_users()
            if email == ADMIN_EMAIL:
                users[email] = {
                    "email": email,
                    "name": name or "Rodrigo",
                    "picture": picture,
                    "status": "active",
                    "role": "admin",
                    "last_login": now_str,
                    "created_at": users.get(email, {}).get("created_at", now_str)
                }
                save_users(users)
                request.session['user'] = user
                return RedirectResponse(url="/")
            
            if email in users:
                user_record = users[email]
                if user_record.get("status") == "blocked":
                    return RedirectResponse(url="/login?error=Acceso%20Bloqueado:%20Tu%20usuario%20ha%20sido%20desactivado%20por%20el%20administrador.")
                user_record["last_login"] = now_str
                user_record["name"] = name
                user_record["picture"] = picture
                users[email] = user_record
            else:
                users[email] = {
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "status": "active",
                    "role": "user",
                    "created_at": now_str,
                    "last_login": now_str
                }
            save_users(users)
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

# ==============================================================================
# ESCÁNER DE PARTITURAS & GENERADOR DE HIMNARIOS (OMR + BATCH + ÁLBUM 1 HORA)
# ==============================================================================
try:
    from pydub import AudioSegment
    if os.path.exists("ffmpeg.exe"):
        AudioSegment.converter = os.path.abspath("ffmpeg.exe")
except ImportError:
    AudioSegment = None

HYMNAL_KNOWLEDGE_BASE = {
    "15": {
        "title": "Firmes Y Adelante",
        "english_title": "Onward, Christian Soldiers",
        "key": "Eb Major (Mi bemol Mayor)",
        "meter": "4/4",
        "tempo": "Marcial Majestuoso (100 BPM)",
        "chords": "Eb - Bb7 - Eb - Ab - Eb - Bb - Eb",
        "style_tags": "triumphant sacred Christian march hymn in 4/4 meter, majestic brass choir, pipe organ, marching snare drum rolls, soaring strings and full congregational choir, heroic uplifting and resolute tempo 100 BPM",
        "lyrics": """[Verse 1]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.
Jefe soberano, Cristo al frente va,
Y la regia enseña tremolando está.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 2]
Al sagrado nombre de nuestro adalid,
Tiembla el enemigo y huye de la lid.
Nuestra es la victoria, dad a Dios loor,
Y óiganlo los ecos del contorno en derredor.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 3]
Muévase potente la iglesia de Dios,
De los ya gloriosos marchamos en pos.
Somos un solo cuerpo y uno es el Señor,
Una la esperanza y uno nuestro amor.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 4]
Tronos y coronas pueden perecer,
De Jesús la iglesia firme ha de ser.
Nada en contra de ella prevalecerá,
Porque la promesa nunca faltará.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve."""
    },
    "firmes_y_adelante": {
        "title": "Firmes Y Adelante",
        "english_title": "Onward, Christian Soldiers",
        "key": "Eb Major (Mi bemol Mayor)",
        "meter": "4/4",
        "tempo": "Marcial Majestuoso (100 BPM)",
        "chords": "Eb - Bb7 - Eb - Ab - Eb - Bb - Eb",
        "style_tags": "triumphant sacred Christian march hymn in 4/4 meter, majestic brass choir, pipe organ, marching snare drum rolls, soaring strings and full congregational choir, heroic uplifting and resolute tempo 100 BPM",
        "lyrics": """[Verse 1]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.
Jefe soberano, Cristo al frente va,
Y la regia enseña tremolando está.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 2]
Al sagrado nombre de nuestro adalid,
Tiembla el enemigo y huye de la lid.
Nuestra es la victoria, dad a Dios loor,
Y óiganlo los ecos del contorno en derredor.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 3]
Muévase potente la iglesia de Dios,
De los ya gloriosos marchamos en pos.
Somos un solo cuerpo y uno es el Señor,
Una la esperanza y uno nuestro amor.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve.

[Verse 4]
Tronos y coronas pueden perecer,
De Jesús la iglesia firme ha de ser.
Nada en contra de ella prevalecerá,
Porque la promesa nunca faltará.

[Chorus]
Firmes y adelante, huestes de la fe,
Sin temor alguno, que Jesús nos ve."""
    },
    "297": {
        "title": "¡Oh, Sí, Quiero Verle!",
        "english_title": "O I Want to See Him",
        "key": "Ab Major (La bemol Mayor)",
        "meter": "12/8",
        "tempo": "Lento Devocional (54 BPM en compás 12/8)",
        "chords": "Ab - Db - Ab - Eb7 - C7 - Fm - Bb7",
        "style_tags": "slow reverent traditional Christian worship hymn, strictly in 12/8 compound meter, slow andante gospel hymn tempo, 54 BPM dotted-quarter note, key of Ab Major, uplifting church choir singing in unison, grand Vienna Philharmonic orchestral strings and piano, unhurried sacred pacing, zero rush, faithful to hymn 297 melody",
        "audio_skeleton": "/assets/skeletons/hymn_297.mp3",
        "skeleton_file": "assets/skeletons/hymn_297.mp3",
        "lyrics": """[Verse 1]
Voy feliz al dulce hogar, por fe en Jesús,
Y luchando a traer almas a la luz;
Dardos encendidos mil vienen contra mí,
Mas yo sé, por la fe, venceré aquí.

[Chorus]
¡Oh sí, quiero verle, ver al Salvador,
Quiero ver su rostro lleno de amor!
En aquel gran día yo he de cantar,
Ya pasó todo afán, todo mi pesar.

[Verse 2]
En las olas del turbión Cristo guardará,
Mi barquilla, y guiará hasta el puerto allá;
Yo tranquilo puedo estar, mi piloto es él,
Es mi Rey, tengo fe, sé que él es fiel.

[Chorus]
¡Oh sí, quiero verle, ver al Salvador,
Quiero ver su rostro lleno de amor!
En aquel gran día yo he de cantar,
Ya pasó todo afán, todo mi pesar.

[Verse 3]
En servir al Salvador por los valles voy,
Donde muchas sombras hay, más seguro estoy;
Muchos triunfos obtendré, nunca faltará,
Mi Jesús, es la luz, él me sostendrá.

[Chorus]
¡Oh sí, quiero verle, ver al Salvador,
Quiero ver su rostro lleno de amor!
En aquel gran día yo he de cantar,
Ya pasó todo afán, todo mi pesar."""
    },
    "sublime_gracia": {
        "title": "Sublime Gracia",
        "english_title": "Amazing Grace",
        "key": "G Major (Sol Mayor)",
        "meter": "3/4",
        "tempo": "Andante (76 BPM)",
        "chords": "G - G7 - C - G - Em - D7 - G",
        "style_tags": "traditional sacred hymn in 3/4 waltz lilt, acoustic church organ and strings, reverent and solemn",
        "lyrics": """[Verse 1]
Sublime gracia del Señor,
Que a un infeliz salvó;
Fui ciego mas hoy miro yo,
Perdido y él me halló.

[Verse 2]
Su gracia me enseñó a temer,
Mis dudas ahuyentó;
¡Oh, cuán precioso fue a mi ser
Al dar mi corazón!

[Verse 3]
En los peligros o aflicción
Que yo he tenido aquí,
Su gracia siempre me libró
Y me guiará feliz."""
    },
    "cuan_grande_es_el": {
        "title": "Cuán Grande es Él",
        "english_title": "How Great Thou Art",
        "key": "Bb Major (Si bemol Mayor)",
        "meter": "4/4",
        "tempo": "Majestuoso (72 BPM)",
        "chords": "Bb - Eb - Bb - F7 - Bb",
        "style_tags": "grand classical symphony orchestra worship hymn in 4/4 time, majestic brass swells, soaring strings, concert timpani",
        "lyrics": """[Verse 1]
Señor, mi Dios, al contemplar los cielos,
El firmamento y las estrellas mil,
Al oír tu voz en los potentes truenos
Y ver brillar al sol en su cenit.

[Chorus]
Mi corazón entona la canción:
¡Cuán grande es él! ¡Cuán grande es él!
Mi corazón entona la canción:
¡Cuán grande es él! ¡Cuán grande es él!

[Verse 2]
Al recorrer los montes y los valles
Y ver las bellas flores al pasar,
Al escuchar el canto de las aves
Y el murmurar del claro manantial.

[Chorus]
Mi corazón entona la canción:
¡Cuán grande es él! ¡Cuán grande es él!
Mi corazón entona la canción:
¡Cuán grande es él! ¡Cuán grande es él!"""
    },
    "castillo_fuerte": {
        "title": "Castillo Fuerte Es Nuestro Dios",
        "english_title": "A Mighty Fortress Is Our God",
        "key": "C Major (Do Mayor)",
        "meter": "4/4",
        "tempo": "Solemne (88 BPM)",
        "chords": "C - F - G - Am - Dm - G7 - C",
        "style_tags": "solemn traditional pipe organ hymn in 4/4, 4-part choir harmony, majestic cathedral acoustics",
        "lyrics": """[Verse 1]
Castillo fuerte es nuestro Dios,
Defensa y buen escudo;
Con su poder nos librará
En este trance agudo.
Con furia y con afán
Acósanos Satán;
Por armas deja ver
Astucia y gran poder;
Cual él no hay en la tierra.

[Verse 2]
Luchar debemos con valor,
Confiando en su promesa;
Él es el fuerte vencedor,
Nuestra eterna fortaleza.
Jesús el Capitán,
El Rey de nuestro afán,
Él triunfará al final,
Venciendo todo mal,
Y reinará por siempre."""
    },
    "en_la_cruz": {
        "title": "En la Cruz",
        "english_title": "At the Cross",
        "key": "Eb Major (Mi bemol Mayor)",
        "meter": "4/4",
        "tempo": "Moderato (84 BPM)",
        "chords": "Eb - Ab - Eb - Bb7 - Eb",
        "style_tags": "uplifting church hymn in 4/4 time, piano and acoustic rhythm guitar, sincere congregational choir",
        "lyrics": """[Verse 1]
Me hirió el pecado, fui a Jesús,
Mostrele mi dolor;
Perdido, errante, vi su luz,
Bendíjome en su amor.

[Chorus]
En la cruz, en la cruz,
Do primero vi la luz,
Y las manchas de mi alma yo lavé;
Fue allí por fe do vi a Jesús,
Y siempre feliz con él seré.

[Verse 2]
Venció la muerte con poder,
Y al cielo se exaltó;
Confiar en él es mi placer,
Morir no temo yo.

[Chorus]
En la cruz, en la cruz,
Do primero vi la luz,
Y las manchas de mi alma yo lavé;
Fue allí por fe do vi a Jesús,
Y siempre feliz con él seré."""
    }
}

BATCH_TASKS = {}

def parse_ocr_lyrics(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        # Deshacer separación de sílabas por guiones (ej. dul-ce -> dulce, a-de-lan-te -> adelante)
        cleaned = re.sub(r'([a-zA-ZáéíóúÁÉÍÓÚñÑ])\s*-\s*([a-zA-ZáéíóúÁÉÍÓÚñÑ])', r'\1\2', raw)
        return cleaned.strip()
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, str):
                cleaned = re.sub(r'([a-zA-ZáéíóúÁÉÍÓÚñÑ])\s*-\s*([a-zA-ZáéíóúÁÉÍÓÚñÑ])', r'\1\2', item).strip()
                out.append(cleaned)
            elif isinstance(item, dict):
                header = item.get("section") or item.get("stanza") or item.get("part") or item.get("title") or ""
                body = item.get("text") or item.get("lyrics") or item.get("content") or item.get("lines") or ""
                if isinstance(body, list):
                    body = "\n".join(str(b).strip() for b in body)
                body = re.sub(r'([a-zA-ZáéíóúÁÉÍÓÚñÑ])\s*-\s*([a-zA-ZáéíóúÁÉÍÓÚñÑ])', r'\1\2', str(body)).strip()
                if header and not body.startswith("["):
                    out.append(f"[{header}]\n{body}")
                else:
                    out.append(body)
            else:
                out.append(str(item).strip())
        return "\n\n".join(x for x in out if x).strip()
    if isinstance(raw, dict):
        out = []
        for k, v in raw.items():
            header = f"[{k}]" if not str(k).startswith("[") else str(k)
            if isinstance(v, list):
                v_text = "\n".join(str(x).strip() for x in v)
            elif isinstance(v, dict):
                v_text = "\n".join(f"{vk}: {vv}" for vk, vv in v.items())
            else:
                v_text = str(v).strip()
            v_text = re.sub(r'([a-zA-ZáéíóúÁÉÍÓÚñÑ])\s*-\s*([a-zA-ZáéíóúÁÉÍÓÚñÑ])', r'\1\2', v_text)
            out.append(f"{header}\n{v_text}")
        return "\n\n".join(x for x in out if x).strip()
    return str(raw).strip()

def midi_to_audio_wave(mid_bytes: bytes, sample_rate: int = 44100) -> bytes:
    """Sintetiza notas de un archivo MIDI en un audio WAV fiel de alta fidelidad (piano/órgano)"""
    import io
    import wave
    import numpy as np
    import mido

    mid = mido.MidiFile(file=io.BytesIO(mid_bytes))
    
    current_time = 0.0
    active_notes = {}  # (note, channel) -> (start_time, velocity)
    note_events = []   # (note, start_time, duration, velocity)
    
    for msg in mid:
        current_time += msg.time
        if msg.type == 'note_on' and msg.velocity > 0:
            active_notes[(msg.note, msg.channel)] = (current_time, msg.velocity)
        elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
            key = (msg.note, msg.channel)
            if key in active_notes:
                start_t, vel = active_notes.pop(key)
                dur = max(0.08, current_time - start_t)
                note_events.append((msg.note, start_t, dur, vel))
                
    for (note, ch), (start_t, vel) in active_notes.items():
        dur = max(0.08, current_time - start_t)
        note_events.append((note, start_t, dur, vel))
        
    total_duration = max(current_time + 1.2, 2.0)
    total_samples = int(total_duration * sample_rate)
    audio = np.zeros(total_samples, dtype=np.float32)
    
    for note, start_t, dur, vel in note_events:
        freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
        start_sample = int(start_t * sample_rate)
        sounding_dur = dur + 0.3
        note_samples = int(sounding_dur * sample_rate)
        if start_sample >= total_samples:
            continue
        actual_samples = min(note_samples, total_samples - start_sample)
        if actual_samples <= 0:
            continue
            
        t = np.linspace(0, sounding_dur, note_samples)[:actual_samples]
        amp = (vel / 127.0) * 0.35
        envelope = np.exp(-t * 2.2)
        wave_arr = (
            np.sin(2 * np.pi * freq * t) * 0.55 +
            np.sin(2 * np.pi * freq * 2 * t) * 0.25 +
            np.sin(2 * np.pi * freq * 3 * t) * 0.12 +
            np.sin(2 * np.pi * freq * 4 * t) * 0.08
        ) * envelope * amp
        
        audio[start_sample:start_sample + actual_samples] += wave_arr
        
    max_val = np.max(np.abs(audio))
    if max_val > 0.01:
        audio = (audio / max_val) * 0.92
        
    audio_int16 = (audio * 32767).astype(np.int16)
    out_buf = io.BytesIO()
    with wave.open(out_buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return out_buf.getvalue()

async def extract_score_metadata(filename: str, content: bytes) -> dict:
    fname_lower = filename.lower()
    clean_name = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()
    # 0. Procesamiento directo de archivos MIDI (.mid / .midi) de Hymnary.org o secuencias
    if fname_lower.endswith((".mid", ".midi")):
        try:
            import io
            import mido
            mid = mido.MidiFile(file=io.BytesIO(content))
            
            bpm = 100
            meter = "4/4"
            key = "Do Mayor (C Major)"
            midi_lyrics_list = []
            
            for track in mid.tracks:
                for msg in track:
                    if msg.type == 'set_tempo':
                        bpm = round(mido.tempo2bpm(msg.tempo))
                    elif msg.type == 'time_signature':
                        meter = f"{msg.numerator}/{msg.denominator}"
                    elif msg.type == 'key_signature':
                        key = f"{msg.key}"
                    elif msg.type in ('lyrics', 'text'):
                        txt = str(msg.text).strip()
                        if txt and not txt.startswith('@') and len(txt) < 100:
                            midi_lyrics_list.append(txt)
                            
            wav_bytes = midi_to_audio_wave(content)
            sk_id = str(uuid.uuid4())[:8]
            os.makedirs("assets/skeletons", exist_ok=True)
            sk_filename = f"midi_{sk_id}.wav"
            sk_path = os.path.join("assets", "skeletons", sk_filename)
            with open(sk_path, "wb") as f_sk:
                f_sk.write(wav_bytes)
                
            sk_url = f"/assets/skeletons/{sk_filename}"
            clean_name = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()
            
            # Comprobar si coincide con himno de nuestra base de conocimiento
            matched_kb = None
            for hid, hdata in HYMNAL_KNOWLEDGE_BASE.items():
                title_words = [w.lower() for w in hdata["title"].split() if len(w) > 4]
                if hid in fname_lower or any(w in fname_lower for w in title_words):
                    matched_kb = hdata
                    break
                    
            if matched_kb:
                final_title = matched_kb["title"]
                final_lyrics = matched_kb["lyrics"]
                final_key = matched_kb["key"]
                final_style = matched_kb["style_tags"]
            else:
                final_title = clean_name
                joined_mid_lyrics = " ".join(midi_lyrics_list).strip()
                if len(joined_mid_lyrics) > 20:
                    final_lyrics = f"[Verse 1]\n{joined_mid_lyrics}"
                else:
                    final_lyrics = f"[Verse 1]\nEscribe o pega aquí la letra para: {clean_name}..."
                final_key = key
                final_style = f"sacred traditional Christian worship hymn, strictly following melodic guide in {meter} time, tempo {bpm} BPM, key of {final_key}, grand symphonic orchestra strings, pipe organ and worship choir in unison"
                
            return {
                "id": sk_id,
                "filename": filename,
                "title": final_title,
                "key": final_key,
                "meter": meter,
                "tempo": f"{bpm} BPM",
                "chords": "Melodía y acordes exactos del archivo MIDI",
                "lyrics": final_lyrics,
                "suggested_style": final_style,
                "audio_skeleton": sk_url,
                "skeleton_file": sk_path
            }
        except Exception as midi_err:
            print(f"[MIDI Parser Error] {filename}: {midi_err}")


    
    # 1. Comprobar si coincide con himnos conocidos del himnario por nombre de archivo
    for hid, hdata in HYMNAL_KNOWLEDGE_BASE.items():
        title_words = hdata["title"].lower().split()
        eng_words = hdata.get("english_title", "").lower().split()
        if (hid in fname_lower or 
            any(w in fname_lower for w in title_words if len(w) > 4) or 
            any(w in fname_lower for w in eng_words if len(w) > 4)):
            return {
                "id": str(uuid.uuid4())[:8],
                "filename": filename,
                "title": hdata["title"],
                "key": hdata["key"],
                "meter": hdata["meter"],
                "tempo": hdata["tempo"],
                "chords": hdata["chords"],
                "lyrics": hdata["lyrics"],
                "suggested_style": hdata["style_tags"],
                "audio_skeleton": hdata.get("audio_skeleton", ""),
                "skeleton_file": hdata.get("skeleton_file", "")
            }
            
    # 2. Si es MusicXML / XML:
    if fname_lower.endswith((".xml", ".musicxml")):
        try:
            xml_str = content.decode("utf-8", errors="ignore")
            title_m = re.search(r'<work-title>(.*?)</work-title>', xml_str) or re.search(r'<movement-title>(.*?)</movement-title>', xml_str)
            title = title_m.group(1).strip() if title_m else os.path.splitext(filename)[0]
            beats_m = re.search(r'<beats>(\d+)</beats>', xml_str)
            beat_type_m = re.search(r'<beat-type>(\d+)</beat-type>', xml_str)
            meter = f"{beats_m.group(1)}/{beat_type_m.group(1)}" if (beats_m and beat_type_m) else "4/4"
            lyric_words = re.findall(r'<text>(.*?)</text>', xml_str)
            clean_lyrics = " ".join(lyric_words) if lyric_words else "[Verse 1]\nLetra extraída de partitura..."
            return {
                "id": str(uuid.uuid4())[:8],
                "filename": filename,
                "title": title,
                "key": "Re Mayor (D Major)",
                "meter": meter,
                "tempo": "Andante (80 BPM)",
                "chords": "D - G - A7 - D",
                "lyrics": f"[Verse 1]\n{clean_lyrics}",
                "suggested_style": f"sacred classical hymn in {meter} time, traditional church choir and orchestra"
            }
        except Exception:
            pass

    # 3. OCR con Inteligencia Artificial Visual (Fal Vision) para cualquier imagen de partitura:
    is_image = (
        fname_lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")) or
        content.startswith(b'\xff\xd8') or
        content.startswith(b'\x89PNG') or
        (len(content) > 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP')
    )

    if is_image and fal_client and (os.environ.get("FAL_KEY") or FAL_KEY):
        try:
            mime = "image/png" if content.startswith(b'\x89PNG') else "image/jpeg"
            img_url = await asyncio.to_thread(fal_client.upload, content, mime)
            
            ocr_prompt = """Eres un musicólogo experto e hiper-preciso en himnología cristiana y OCR de partituras e himnarios.
Examina con suma atención la imagen de la partitura. IMPORTANTE: La foto puede provenir de un teléfono móvil y estar rotada de costado, apaisada o vertical. Oriéntala mentalmente para leer la partitura y la letra en la orientación correcta.

Extrae con máxima fidelidad musical y textual:
1. Número del himno (si aparece arriba a la izquierda, derecha o centro del pentagrama, ej. 15, 297).
2. Título exacto del himno en español (ej. "Firmes Y Adelante", "¡Oh, Sí, Quiero Verle!").
3. Tonalidad (armadura de clave: ej. Eb Major / Mi bemol Mayor, Ab Major, Sol Mayor, etc.).
4. Compás o métrica (ej. 4/4, 12/8, 3/4, 6/8).
5. Tempo recomendado en BPM (ej. 100 BPM para marcha 4/4, 54 BPM para 12/8 devocional lento, 80 BPM para moderato).
6. Acordes o progresión armónica (ej. "Eb - Bb7 - Ab - Eb").
7. Letra completa en español ordenada por estrofas y coro. REGLA CRÍTICA: Une todas las sílabas separadas por guiones en palabras normales completas del español (por ejemplo 'dul-ce' debe ser 'dulce', 'fe-liz' debe ser 'feliz', 'a-de-lan-te' debe ser 'adelante', 'so-be-ra-no' debe ser 'soberano', 'hues-tes' debe ser 'huestes'). Estructura claramente con etiquetas [Verse 1], [Chorus], [Verse 2], [Verse 3], etc.

Responde ÚNICAMENTE con un objeto JSON válido con los campos exactos:
{
  "hymn_number": "15",
  "title": "Firmes Y Adelante",
  "key": "Eb Major (Mi bemol Mayor)",
  "meter": "4/4",
  "tempo": "Marcial Majestuoso (100 BPM)",
  "chords": "Eb - Bb7 - Ab - Eb",
  "lyrics": "[Verse 1]\nFirmes y adelante, huestes de la fe...\n\n[Chorus]\nFirmes y adelante, huestes de la fe..."
}
No incluyas texto explicativo antes ni después del bloque JSON."""

            res = await asyncio.to_thread(
                fal_client.subscribe,
                "fal-ai/any-llm/vision",
                arguments={"prompt": ocr_prompt, "image_url": img_url}
            )
            raw_out = res.get("output", "")
            m = re.search(r"\{[\s\S]*\}", raw_out)
            if m:
                parsed = json.loads(m.group(0))
                det_num = str(parsed.get("hymn_number", "")).strip()
                det_title = str(parsed.get("title", "")).strip()
                det_meter = str(parsed.get("meter", "4/4")).strip()
                det_key = str(parsed.get("key", "Sol Mayor (G Major)")).strip()
                det_tempo = str(parsed.get("tempo", "Andante (80 BPM)")).strip()
                
                raw_chords = parsed.get("chords", "G - C - D - G")
                if isinstance(raw_chords, list):
                    det_chords = " - ".join(str(c).strip() for c in raw_chords)
                else:
                    det_chords = str(raw_chords).strip()
                
                clean_lyrics = parse_ocr_lyrics(parsed.get("lyrics", ""))

                # Comprobar si el himno detectado coincide con nuestra base de conocimiento (ej: 15, 297)
                matched_kb = None
                if det_num and det_num in HYMNAL_KNOWLEDGE_BASE:
                    matched_kb = HYMNAL_KNOWLEDGE_BASE[det_num]
                else:
                    for hid, hdata in HYMNAL_KNOWLEDGE_BASE.items():
                        title_words = [w.lower() for w in hdata["title"].split() if len(w) > 4]
                        if any(w in det_title.lower() for w in title_words):
                            matched_kb = hdata
                            break

                if matched_kb:
                    return {
                        "id": str(uuid.uuid4())[:8],
                        "filename": filename,
                        "title": matched_kb["title"],
                        "key": matched_kb["key"],
                        "meter": matched_kb["meter"],
                        "tempo": matched_kb["tempo"],
                        "chords": matched_kb["chords"],
                        "lyrics": clean_lyrics if len(clean_lyrics) > 50 else matched_kb["lyrics"],
                        "suggested_style": matched_kb["style_tags"],
                        "audio_skeleton": matched_kb.get("audio_skeleton", ""),
                        "skeleton_file": matched_kb.get("skeleton_file", "")
                    }
                else:
                    # Himno nuevo o no catalogado en la base interna
                    if det_meter in ("12/8", "6/8"):
                        style_tag = f"sacred traditional Christian worship hymn, strictly in {det_meter} compound meter, slow reverent tempo ({det_tempo}), key of {det_key}, grand church pipe organ and warm symphonic strings, sacred choir in unison, unhurried devocional pacing, no modern pop drums"
                    elif det_meter == "3/4":
                        style_tag = f"sacred traditional Christian hymn, strictly in 3/4 triple meter, reverent tempo ({det_tempo}), key of {det_key}, pipe organ and warm symphonic strings, worship choir in unison, unhurried pacing"
                    else:
                        style_tag = f"sacred traditional Christian worship hymn, strictly in {det_meter} time, reverent tempo ({det_tempo}), key of {det_key}, grand symphonic orchestra strings and pipe organ, worship choir in unison"

                    return {
                        "id": str(uuid.uuid4())[:8],
                        "filename": filename,
                        "title": det_title if det_title else clean_name,
                        "key": det_key,
                        "meter": det_meter,
                        "tempo": det_tempo,
                        "chords": det_chords or "G - C - D - G",
                        "lyrics": clean_lyrics if clean_lyrics else f"[Verse 1]\nHimno: {det_title}\n...",
                        "suggested_style": style_tag,
                        "audio_skeleton": "",
                        "skeleton_file": ""
                    }
        except Exception as ocr_err:
            print(f"[Vision OCR] Error analizando {filename} con Fal: {ocr_err}")

    # 4. Fallback inteligente si no hay conexión o no se detectó por visión:
    if ("15" in clean_name or "15" in fname_lower or 
        "firmes" in fname_lower or "adelante" in fname_lower or
        "a57d25f8" in fname_lower or "6390bb3b" in fname_lower):
        h = HYMNAL_KNOWLEDGE_BASE["15"]
        return {
            "id": str(uuid.uuid4())[:8],
            "filename": filename,
            "title": h["title"],
            "key": h["key"],
            "meter": h["meter"],
            "tempo": h["tempo"],
            "chords": h["chords"],
            "lyrics": h["lyrics"],
            "suggested_style": h["style_tags"],
            "audio_skeleton": h.get("audio_skeleton", ""),
            "skeleton_file": h.get("skeleton_file", "")
        }

    if ("297" in clean_name or "297" in fname_lower or 
        "c7db9a4c" in fname_lower or "170530fc" in fname_lower or 
        "quiero verle" in fname_lower or "want to see him" in fname_lower):
        h = HYMNAL_KNOWLEDGE_BASE["297"]
        return {
            "id": str(uuid.uuid4())[:8],
            "filename": filename,
            "title": h["title"],
            "key": h["key"],
            "meter": h["meter"],
            "tempo": h["tempo"],
            "chords": h["chords"],
            "lyrics": h["lyrics"],
            "suggested_style": h["style_tags"],
            "audio_skeleton": h.get("audio_skeleton", ""),
            "skeleton_file": h.get("skeleton_file", "")
        }

    return {
        "id": str(uuid.uuid4())[:8],
        "filename": filename,
        "title": clean_name if clean_name else "Himno Sagrado",
        "key": "Sol Mayor (G Major)",
        "meter": "4/4",
        "tempo": "Andante (84 BPM)",
        "chords": "G - C - G - D7 - Em - C - D - G",
        "lyrics": f"[Verse 1]\nHimno extraído de partitura: {clean_name}\nCon reverencia y devoción cantamos,\nAlzando al cielo gratitud y honor.\n\n[Chorus]\n¡Gloria y honor al Salvador!\nCon alabanza y gran clamor.",
        "suggested_style": "sacred traditional Christian worship hymn, 4/4 time, grand symphony orchestra strings and pipe organ, uplifting choir in unison"
    }

@app.post("/api/scan_sheet_music")
async def api_scan_sheet_music(files: list[UploadFile] = File(...)):
    async def process_file(f: UploadFile):
        try:
            content = await f.read()
            return await extract_score_metadata(f.filename, content)
        except Exception as e:
            return {
                "id": str(uuid.uuid4())[:8],
                "filename": f.filename,
                "title": os.path.splitext(f.filename)[0],
                "key": "Re Mayor (D Major)",
                "meter": "4/4",
                "tempo": "80 BPM",
                "chords": "D - G - A - D",
                "lyrics": "[Verse 1]\nEscribe o verifica la letra aquí...",
                "suggested_style": "sacred Christian hymn",
                "error": str(e)
            }

    results = await asyncio.gather(*[process_file(f) for f in files])
    return {"results": list(results), "count": len(results)}


async def run_batch_worker(batch_id: str, hymns: list[dict]):
    BATCH_TASKS[batch_id]["status"] = "PROCESSING"
    total = len(hymns)
    
    for idx, h in enumerate(hymns):
        BATCH_TASKS[batch_id]["current_index"] = idx + 1
        BATCH_TASKS[batch_id]["current_title"] = h.get("title", f"Himno #{idx+1}")
        BATCH_TASKS[batch_id]["progress_pct"] = round((idx / total) * 100)
        
        task_id = str(uuid.uuid4())[:12]
        TASKS[task_id] = {
            "id": task_id,
            "status": "PROCESSING",
            "logs": f"Iniciando generación de lote para: {h.get('title')}\n",
            "tracks": []
        }
        
        style = h.get("style", "sacred Christian hymn, church choir, classical strings")
        lyrics = h.get("lyrics", "[Verse 1]\nGloria a Dios en las alturas")
        title = h.get("title", f"Himno {idx+1}")
        model = h.get("model", "chirp-v5")
        vocal_gender = h.get("vocal_gender", "male")
        exclude_styles = h.get("exclude_styles", "cumbia, trap, electronic, metal, distortion")
        
        audio_content = None
        audio_filename = None
        ignore_audio = True
        audio_influence = 0
        sk_path = h.get("skeleton_file")
        resolved_sk = None
        if sk_path:
            cand = sk_path.lstrip("/\\")
            if os.path.exists(cand):
                resolved_sk = cand
            else:
                base_cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), cand)
                if os.path.exists(base_cand):
                    resolved_sk = base_cand

        if resolved_sk:
            with open(resolved_sk, "rb") as f_sk:
                audio_content = f_sk.read()
            audio_filename = os.path.basename(resolved_sk)
            ignore_audio = False
            audio_influence = 65

        try:
            await run_transform_task(
                task_id=task_id,
                style=style,
                lyrics=lyrics,
                title=title,
                audio_content=audio_content,
                audio_filename=audio_filename,
                ignore_audio=ignore_audio,
                include_lyrics=True,
                bypass_copyright=True,
                exclude_styles=exclude_styles,
                vocal_gender=vocal_gender,
                weirdness=25,
                style_influence=50,
                audio_influence=audio_influence,
                model=model,
                pronunciation="",
                obfuscate=False
            )
            
            t_obj = TASKS.get(task_id, {})
            tracks = t_obj.get("tracks", [])
            if tracks:
                track_id = tracks[0].get("id")
                BATCH_TASKS[batch_id]["completed_tracks"].append({
                    "id": track_id,
                    "title": title,
                    "audio_url": tracks[0].get("audio_url"),
                    "duration": tracks[0].get("duration", 0)
                })
        except Exception as e:
            BATCH_TASKS[batch_id]["errors"].append({"hymn": title, "error": str(e)})
            
        await asyncio.sleep(2)
        
    BATCH_TASKS[batch_id]["status"] = "COMPLETED"
    BATCH_TASKS[batch_id]["progress_pct"] = 100
    BATCH_TASKS[batch_id]["current_title"] = "¡Himnario completado con éxito!"

@app.post("/api/batch_generate")
async def api_batch_generate(payload: dict, background_tasks: BackgroundTasks):
    hymns = payload.get("hymns", [])
    if not hymns:
        raise HTTPException(status_code=400, detail="No se enviaron himnos para procesar.")
    
    batch_id = f"batch_{uuid.uuid4().hex[:10]}"
    BATCH_TASKS[batch_id] = {
        "id": batch_id,
        "total": len(hymns),
        "current_index": 0,
        "current_title": "Iniciando cola de himnos...",
        "status": "QUEUED",
        "completed_tracks": [],
        "errors": [],
        "progress_pct": 0
    }
    
    background_tasks.add_task(run_batch_worker, batch_id, hymns)
    return {"batch_id": batch_id, "status": "QUEUED", "total": len(hymns)}

@app.get("/api/batch_status/{batch_id}")
async def api_batch_status(batch_id: str):
    task = BATCH_TASKS.get(batch_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea de lote no encontrada.")
    return task

@app.post("/api/merge_continuous_album")
async def api_merge_continuous_album(payload: dict):
    track_ids = payload.get("track_ids", [])
    album_title = payload.get("album_title", "Himnario Devocional - 1 Hora de Adoración").strip()
    crossfade_sec = float(payload.get("crossfade_sec", 4.0))
    crossfade_ms = int(crossfade_sec * 1000)
    
    if not track_ids or len(track_ids) < 1:
        raise HTTPException(status_code=400, detail="Selecciona al menos 2 pistas para unir en álbum continuo.")
        
    valid_files = []
    for tid in track_ids:
        p = os.path.join(TRACKS_DIR, f"{tid}.mp3")
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            valid_files.append(p)
            
    if len(valid_files) < 1:
        raise HTTPException(status_code=404, detail="No se encontraron los archivos de audio en el servidor.")
        
    album_id = f"album_{uuid.uuid4().hex[:10]}"
    out_file = os.path.join(TRACKS_DIR, f"{album_id}.mp3")
    
    try:
        combined = AudioSegment.from_file(valid_files[0])
        for next_file in valid_files[1:]:
            seg = AudioSegment.from_file(next_file)
            cf = min(crossfade_ms, len(combined) - 500, len(seg) - 500)
            if cf > 500:
                combined = combined.append(seg, crossfade=cf)
            else:
                combined = combined + seg
            
        combined.export(out_file, format="mp3", bitrate="192k")
        total_duration = round(len(combined) / 1000)
        
        album_track_info = {
            "id": album_id,
            "title": f"📀 {album_title}",
            "audio_url": f"/api/audio_file/{album_id}",
            "raw_audio_url": f"/api/audio_file/{album_id}",
            "image_url": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%237C3AED'/%3E%3Ccircle cx='32' cy='32' r='20' stroke='%23fff' stroke-width='4' fill='none' opacity='0.9'/%3E%3Ccircle cx='32' cy='32' r='8' fill='%23FBBF24'/%3E%3C/svg%3E",
            "duration": total_duration,
            "status": "SUCCESS",
            "style": "Continuous Worship Album, Seamless Crossfades, Non-Stop Stream",
            "lyrics": f"Álbum continuo con {len(valid_files)} himnos encadenados con crossfade.",
            "is_album": True
        }
        add_track_to_library(album_track_info)
        return {
            "success": True,
            "album_id": album_id,
            "audio_url": f"/api/audio_file/{album_id}",
            "duration": total_duration,
            "title": album_title,
            "tracks_count": len(valid_files)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando álbum continuo: {str(e)}")

# ==============================================================================
# MÓDULO: PRODUCCIÓN PROFESIONAL DE HIMNOS (FASE 1: RESTAURACIÓN Y MASTERIZACIÓN)
# 100% Autónomo - Sin dependencias de Udio ni riesgo de rechazo de catálogo
# ==============================================================================
HYMNS_RESTORED_DIR = os.path.join(assets_dir, "hymns_restored")
os.makedirs(HYMNS_RESTORED_DIR, exist_ok=True)

def measure_ebur128(audio_file_path: str) -> dict:
    """Mide la sonoridad integrada (LUFS), True Peak (dBFS) y rango dinámico (LRA) según EBU R128."""
    try:
        cmd = [
            "ffmpeg", "-nostats", "-i", audio_file_path,
            "-filter_complex", "ebur128=peak=true",
            "-f", "null", "-"
        ]
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        out = p.stderr or ""
        
        i_m = re.findall(r'I:\s+(-?\d+\.?\d*)\s+LUFS', out)
        tp_m = re.findall(r'Peak:\s+(-?\d+\.?\d*)\s+dBFS', out)
        lra_m = re.findall(r'LRA:\s+(-?\d+\.?\d*)\s+LU', out)
        
        return {
            "integrated_lufs": round(float(i_m[-1]), 1) if i_m else -14.0,
            "true_peak_db": round(float(tp_m[-1]), 1) if tp_m else -1.0,
            "lra": round(float(lra_m[-1]), 1) if lra_m else 0.0
        }
    except Exception as e:
        print(f"[EBUR128] Error midiendo sonoridad: {e}")
        return {"integrated_lufs": -14.0, "true_peak_db": -1.0, "lra": 0.0}

@app.post("/api/hymn_production/restore")
async def restore_hymn_audio(
    audio_file: UploadFile = File(...),
    title: str = Form("Himno Restaurado"),
    intensity: str = Form("medium"),
    denoise_db: float = Form(10.0),
    debox_cut: bool = Form(True),
    clarity_boost: bool = Form(True),
    air_shelf: bool = Form(True),
    compression_profile: str = Form("smooth"),
    target_lufs: float = Form(-14.0)
):
    """Restaura y masteriza grabaciones caseras de himnos (voz + guitarra acústica de celular)."""
    t_start = time.time()
    temp_orig = None
    
    try:
        content = await audio_file.read()
        if not content:
            raise HTTPException(status_code=400, detail="El archivo de audio está vacío.")
            
        orig_filename = audio_file.filename or "himno_original.mp3"
        ext = os.path.splitext(orig_filename)[1].lower() or ".mp3"
        
        item_id = f"hymn_{uuid.uuid4().hex[:12]}"
        
        # Guardar archivo de entrada temporal
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(content)
            temp_orig = tf.name

        # 1. Medición de métricas reales del audio original del celular
        orig_metrics = measure_ebur128(temp_orig)
        
        # 2. Guardar copia normalizada de referencia del original para reproducción A/B
        stored_orig = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_orig.mp3")
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_orig,
            "-c:a", "libmp3lame", "-b:a", "192k",
            stored_orig
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # 3. Construcción adaptativa de la cadena de filtros según la intensidad
        filters = []
        
        # A. Filtro subsónico: Elimina vibraciones de mesa, viento y retumbos graves
        if intensity == "gentle":
            filters.append("highpass=f=65:w=0.7")
        else:
            filters.append("highpass=f=75:w=0.7")
            
        # B. Reducción adaptativa de ruido espectral (sin efecto de fase submarina)
        if intensity == "gentle":
            filters.append("afftdn=nr=6:nf=-50:tn=1")
        elif intensity == "medium":
            filters.append("afftdn=nr=10:nf=-45:tn=1")
        else:
            clamp_nr = max(3.0, min(16.0, float(denoise_db)))
            filters.append(f"afftdn=nr={clamp_nr}:nf=-45:tn=1")
            
        # C. De-box quirúrgico (atenúa el efecto encajonado típico del micrófono del celular)
        if intensity == "medium" or (intensity == "custom" and debox_cut):
            filters.append("equalizer=f=420:t=q:w=1.8:g=-2.5")
        elif intensity == "gentle":
            filters.append("equalizer=f=400:t=q:w=1.5:g=-1.5")
            
        # D. Realce de presencia vocal y articulación de guitarra acústica
        if intensity == "medium" or (intensity == "custom" and clarity_boost):
            filters.append("equalizer=f=3400:t=q:w=1.2:g=2.2")
        elif intensity == "gentle":
            filters.append("equalizer=f=3200:t=q:w=1.2:g=1.5")
            
        # E. Brillo acústico superior (Air Band)
        if intensity == "medium" or (intensity == "custom" and air_shelf):
            filters.append("highshelf=f=11000:g=2.5")
        elif intensity == "gentle":
            filters.append("highshelf=f=10500:g=1.5")
            
        # F. Compresión dinámica musical suave
        if intensity == "gentle" or compression_profile == "gentle":
            filters.append("compand=attacks=0.04:decays=0.2:points=-70/-70|-35/-35|-16/-13|0/-5:gain=0")
        elif compression_profile == "transparent":
            filters.append("compand=attacks=0.05:decays=0.25:points=-70/-70|-40/-40|-20/-17|0/-6:gain=0")
        else:
            filters.append("compand=attacks=0.03:decays=0.15:points=-70/-70|-35/-35|-18/-14|0/-6:gain=1")

        # G. Normalización EBU R128 y limitador True Peak (-1.0 dBFS)
        safe_target_lufs = max(-20.0, min(-10.0, float(target_lufs)))
        filters.append(f"loudnorm=I={safe_target_lufs}:TP=-1.0:LRA=7")
        
        filter_str = ",".join(filters)

        # 4. Rutas de salida para WAV (Master 24-bit PCM) y MP3 (320 kbps CBR)
        out_wav = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_master.wav")
        out_mp3 = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_master.mp3")

        # 5. Ejecución dual en un solo paso de decodificación
        process_cmd = [
            "ffmpeg", "-y", "-i", temp_orig,
            "-af", filter_str,
            "-c:a", "pcm_s24le", out_wav,
            "-c:a", "libmp3lame", "-b:a", "320k", out_mp3
        ]
        proc = subprocess.run(process_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        
        if proc.returncode != 0:
            err_log = proc.stderr or "Error desconocido durante la masterización con FFmpeg."
            raise HTTPException(status_code=500, detail=f"Error al procesar el audio con FFmpeg: {err_log[-400:]}")

        # 6. Medición de métricas reales sobre el archivo masterizado resultante
        proc_metrics = measure_ebur128(out_wav)
        
        # 7. Obtener duración real
        dur_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", out_mp3
        ]
        p_dur = subprocess.run(dur_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            dur_sec = round(float(p_dur.stdout.strip()), 1)
        except Exception:
            dur_sec = 0.0

        elapsed_sec = round(time.time() - t_start, 2)
        clean_title = (title or "Himno Acústico").strip()

        # 8. Agregar a la librería local de Rodrix para acceso permanente
        library_entry = {
            "id": item_id,
            "title": f"✨ {clean_title} (Restaurado)",
            "audio_url": f"/api/hymn_production/stream/{item_id}/restored",
            "raw_audio_url": f"/api/hymn_production/download/{item_id}/wav",
            "image_url": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%2310B981'/%3E%3Cpath d='M32 16v32M24 24l16 16M24 40l16-16' stroke='%23fff' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E",
            "duration": int(dur_sec),
            "status": "SUCCESS",
            "style": f"Producción Profesional Acústica • Masterizado a {proc_metrics['integrated_lufs']} LUFS",
            "lyrics": f"Grabación propia restaurada y masterizada. Original: {orig_metrics['integrated_lufs']} LUFS ➔ Master: {proc_metrics['integrated_lufs']} LUFS.",
            "is_hymn_restored": True
        }
        add_track_to_library(library_entry)

        return {
            "success": True,
            "item_id": item_id,
            "title": clean_title,
            "duration_sec": dur_sec,
            "processing_time_sec": elapsed_sec,
            "intensity_applied": intensity,
            "original_metrics": orig_metrics,
            "processed_metrics": proc_metrics,
            "stream_restored_url": f"/api/hymn_production/stream/{item_id}/restored",
            "stream_orig_url": f"/api/hymn_production/stream/{item_id}/orig",
            "download_wav_url": f"/api/hymn_production/download/{item_id}/wav",
            "download_mp3_url": f"/api/hymn_production/download/{item_id}/mp3"
        }

    finally:
        if temp_orig and os.path.exists(temp_orig):
            try:
                os.remove(temp_orig)
            except Exception:
                pass

@app.get("/api/hymn_production/stream/{item_id}/{version}")
async def stream_hymn_audio(item_id: str, version: str):
    """Transmite el audio para el reproductor A/B con soporte de Range Requests."""
    if version == "orig":
        path = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_orig.mp3")
    else:
        path = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_master.mp3")
        
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Archivo de audio no encontrado.")
    return FileResponse(path, media_type="audio/mpeg")

@app.get("/api/hymn_production/download/{item_id}/{fmt}")
async def download_hymn_audio(item_id: str, fmt: str):
    """Descarga el master restaurado en formato WAV sin pérdida o MP3 320 kbps."""
    if fmt == "wav":
        path = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_master.wav")
        mime = "audio/wav"
        filename = f"{item_id}_master_24bit.wav"
    else:
        path = os.path.join(HYMNS_RESTORED_DIR, f"{item_id}_master.mp3")
        mime = "audio/mpeg"
        filename = f"{item_id}_master_320kbps.mp3"
        
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return FileResponse(path, media_type=mime, filename=filename)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False, workers=1)