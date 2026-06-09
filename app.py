import os
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
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
import json
import datetime
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

# Load environment variables
load_dotenv()

app = FastAPI(title="Rodrix Music Creator - Udio Engine", version="3.0")

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
        if line.strip().startswith('[') and line.strip().endswith(']'):
            processed_lines.append(line)
            continue
            
        obfuscated = ""
        for char in line:
            obfuscated += char + '\u200E'
        processed_lines.append(obfuscated)
        
    return "\n".join(processed_lines)

async def upload_to_tmpfiles_async(file_path: str) -> str | None:
    url = "https://tmpfiles.org/api/v1/upload"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(file_path, 'rb') as f:
                files = {'file': f}
                response = await client.post(url, files=files)
            if response.status_code == 200:
                resp_json = response.json()
                uploaded_url = resp_json.get("data", {}).get("url")
                if uploaded_url:
                    return uploaded_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        print("Error subiendo a Tmpfiles:", e)
    return None

def bypass_audio_fingerprint(input_path: str, output_path: str) -> str:
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-map_metadata", "-1",
        "-af", "asetrate=44100*1.26,aresample=44100,atempo=0.83,vibrato=f=6.0:d=0.6,aecho=0.8:0.9:100:0.5",
        output_path
    ]
    try:
        process = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    current_user: str = Depends(get_current_user)
):
    if not UDIO_API_KEY:
        raise HTTPException(status_code=400, detail="Falta UDIO_API_KEY")

    audio_content = None
    audio_filename = None
    if audio and not ignore_audio:
        audio_content = await audio.read()
        audio_filename = audio.filename

    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"status": "IN_PROGRESS", "logs": "", "tracks": [], "detail": ""}

    background_tasks.add_task(
        run_transform_task,
        task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio,
        include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness,
        style_influence, audio_influence
    )
    
    return {"status": "started", "task_id": task_id}

@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task no encontrada")
    return TASKS[task_id]

async def run_transform_task(task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio, include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness, style_influence, audio_influence):
    def log_msg(msg):
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line)
        TASKS[task_id]["logs"] += line + "\n"
        
    def save_local_log():
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
    if is_instrumental:
        style = style + ", instrumental, no vocals"
    elif bypass_copyright and final_lyrics:
        final_lyrics = "[Vocals in Spanish]\n" + obfuscate_lyrics(final_lyrics)
        style = style + ", spanish vocals"
        
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
            bypassed_file_path = f"bypassed_{uuid.uuid4().hex}{ext}"
            
            with open(temp_file_path, "wb") as f:
                f.write(audio_content)
                
            log_msg("Procesando audio con FFmpeg para evadir Huella Acústica (Copyright)...")
            bypass_result = bypass_audio_fingerprint(temp_file_path, bypassed_file_path)
            
            if bypass_result == "SUCCESS" and os.path.exists(bypassed_file_path):
                target_upload_file = bypassed_file_path
                log_msg("FFmpeg terminó exitosamente. Usando audio modificado.")
            else:
                target_upload_file = temp_file_path
                log_msg(f"FALLO FFmpeg ({bypass_result}). Subiendo audio original SIN bypass.")
                
            log_msg("Subiendo MP3 a servidor temporal para obtener URL pública...")
            upload_url = await upload_to_tmpfiles_async(target_upload_file)
            
            if not upload_url:
                log_msg("ERROR: Fallo al subir el audio a servidor temporal.")
                raise Exception("Fallo al subir el audio a servidor temporal.")
            log_msg(f"Audio subido exitosamente a: {upload_url}")
            
            for p in [temp_file_path, bypassed_file_path]:
                if p and os.path.exists(p):
                    try: os.remove(p)
                    except: pass
                    
        if upload_url:
            log_msg("Usando endpoint V2 Upload & Cover")
            url_generate = "https://udioapi.pro/api/v2/upload-cover/generate"
            url_status = "https://udioapi.pro/api/v2/upload-cover/status"
            
            payload = {
                "upload_url": upload_url,
                "model": "chirp-v4-5",
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
            if exclude_styles.strip():
                payload["negative_tags"] = exclude_styles.strip()
        else:
            log_msg("Usando endpoint estándar Generate")
            url_generate = "https://udioapi.pro/api/generate"
            url_status = "https://udioapi.pro/api/feed"
            
            payload = {
                "prompt": style,
                "lyrics": final_lyrics,
                "tags": style,
                "title": title,
                "make_instrumental": is_instrumental,
                "model": "udio32",
                "custom_mode": True
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if exclude_styles.strip():
                payload["negative_tags"] = exclude_styles.strip()

        log_msg(f"Submitting request to {url_generate}...")
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

                    log_msg(f"Polling (Attempt {i+1}): Status={status}")
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
                        track_info = {
                            "id": tid,
                            "title": ttitle,
                            "audio_url": taudio,
                            "image_url": timage,
                            "duration": tduration,
                            "status": tstatus
                        }
                        final_tracks.append(track_info)
                        add_track_to_library(track_info)
                        log_msg(f"Pista procesada con éxito: {ttitle} (ID: {tid})")

            save_local_log()
            TASKS[task_id]["tracks"] = final_tracks
            TASKS[task_id]["status"] = "COMPLETED"

    except Exception as e:
        log_msg(f"ERROR: {str(e)}")
        save_local_log()
        TASKS[task_id]["detail"] = str(e)
        TASKS[task_id]["status"] = "ERROR"


if __name__ == "__main__":

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)