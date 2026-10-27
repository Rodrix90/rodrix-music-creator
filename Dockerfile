FROM python:3.11-slim

# Evitar la creación de archivos pyc y no usar buffer para stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RODRIX_SF2_DIR=/app/soundfonts_cache

WORKDIR /app

# Instalar dependencias del sistema, incluyendo ffmpeg y fluidsynth
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fluidsynth \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalarlos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Pre-aprovisionar los bancos SF2 libres durante el build de la imagen Docker
# para garantizar disponibilidad inmediata tras reinicios de contenedor en Render
RUN python -c "import free_instruments_engine; free_instruments_engine.ensure_all_soundfonts('/app/soundfonts_cache')"

# Comando de ejecución usando app.py para tomar el puerto dinámico de Render
CMD ["python", "app.py"]
