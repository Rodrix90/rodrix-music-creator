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
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, PlainTextResponse
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
        "-y",
        "-i", input_path,
        "-t", "120",
        "-map_metadata", "-1",
        "-af", "aformat=channel_layouts=stereo,asetrate=44100*0.93,aresample=44100,atempo=1.075,chorus=0.7:0.9:55|70:0.4|0.32:0.25|0.4:2|2.3,bass=g=6,treble=g=-2",
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
    current_user: str = Depends(get_current_user)
):
    if not UDIO_API_KEY:
        raise HTTPException(status_code=400, detail="Falta UDIO_API_KEY")

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
        style_influence, audio_influence, model
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


async def make_permanent_url(original_url: str) -> str:
    if not original_url or "catbox.moe" in original_url:
        return original_url
    try:
        import uuid, os
        temp_file = f"temp_reupload_{uuid.uuid4().hex}.mp3"
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(original_url)
            if r.status_code == 200:
                with open(temp_file, "wb") as f:
                    f.write(r.content)
                new_url = await upload_to_catbox_async(temp_file)
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return new_url or original_url
    except Exception as e:
        print(f"Error re-uploading to catbox: {e}")
    return original_url

async def run_transform_task(task_id, style, lyrics, title, audio_content, audio_filename, ignore_audio, include_lyrics, bypass_copyright, exclude_styles, vocal_gender, weirdness, style_influence, audio_influence, model):
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
            bypass_result = await asyncio.to_thread(bypass_audio_fingerprint, temp_file_path, bypassed_file_path)
            
            if bypass_result == "SUCCESS" and os.path.exists(bypassed_file_path):
                target_upload_file = bypassed_file_path
                log_msg("FFmpeg terminó exitosamente. Usando audio modificado.")
            else:
                target_upload_file = temp_file_path
                log_msg(f"FALLO FFmpeg ({bypass_result}). Subiendo audio original SIN bypass.")
                
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
                "model": model,
                "custom_mode": True,
                "prompt_strength": round(style_influence / 100.0, 2),
                "weirdness": round(weirdness / 100.0, 2)
            }
            if vocal_gender in ["male", "female"]:
                payload["gender"] = vocal_gender
            if exclude_styles.strip():
                payload["negative_tags"] = exclude_styles.strip()

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
                                log_msg(f"Asegurando enlace permanente para {ttitle}...")
                                taudio_perm = await make_permanent_url(taudio)
                                track_info = {
                                    "id": tid,
                                    "title": ttitle,
                                    "audio_url": taudio_perm,
                                    "image_url": timage,
                                    "duration": tduration,
                                    "status": tstatus,
                                    "lyrics": t.get("lyrics") or lyrics
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

@app.get("/api/download/{task_id}/{audio_format}")
async def download_track_format(task_id: str, audio_format: str, current_user: str = Depends(get_current_user)):
    if audio_format not in ["wav", "flac", "mp3"]:
        raise HTTPException(status_code=400, detail="Formato no soportado")
        
    library = load_library()
    track = next((t for t in library if t.get("id") == task_id), None)
    
    if not track or not track.get("audio_url"):
        raise HTTPException(status_code=404, detail="Track no encontrado en la librería")
        
    audio_url = track.get("audio_url")
    title = track.get("title", "Rodrix_Track")
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    
    temp_mp3 = f"temp_dl_{uuid.uuid4().hex}.mp3"
    temp_out = f"temp_out_{uuid.uuid4().hex}.{audio_format}"
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(audio_url)
            if r.status_code != 200:
                raise HTTPException(status_code=500, detail="No se pudo descargar el audio original")
            with open(temp_mp3, "wb") as f:
                f.write(r.content)
                
        ffmpeg_cmd = ["ffmpeg", "-y", "-i", temp_mp3, "-map_metadata", "-1"]
        if audio_format == "wav":
            ffmpeg_cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100"])
        elif audio_format == "flac":
            ffmpeg_cmd.extend(["-c:a", "flac", "-compression_level", "8"])
        elif audio_format == "mp3":
            ffmpeg_cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100"])
            
        ffmpeg_cmd.append(temp_out)
        try:
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except subprocess.CalledProcessError as pe:
            raise Exception(f"FFmpeg Error: {pe.stderr}")
        
        from fastapi.background import BackgroundTasks
        def cleanup_files(files):
            for file in files:
                if os.path.exists(file):
                    try: os.remove(file)
                    except: pass
                    
        return FileResponse(
            path=temp_out, 
            filename=f"{safe_title}.{audio_format}", 
            media_type=f"audio/{audio_format}"
        )
    except Exception as e:
        print(f"Error descargando formato: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def serve_spa(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url="/login")
        
    email = user.get('email', '')
    if email != "rodryandy@gmail.com":
        return RedirectResponse(url="/login?error=Correo%20No%20Autorizado")
        
    index_path = os.path.join(os.getcwd(), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
            html = html.replace("{{USER_EMAIL}}", email if email else "Usuario")
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
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)