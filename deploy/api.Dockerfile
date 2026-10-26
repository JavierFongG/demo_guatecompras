# API de solo lectura (búsqueda + recomendaciones). ~450 MB de imagen, <1 GB de RAM con 18 meses.
# Construir desde la raíz del proyecto:
#   docker build -f deploy/api.Dockerfile -t guatecompras-api .
# Ejecutar (descarga el índice publicado y lo actualiza solo):
#   docker run -p 8080:8080 -e GC_ARTIFACTS_URL=https://… -e GC_CORS_ORIGINS=https://mi-front.pages.dev guatecompras-api
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GC_MODE=api GC_DATA_DIR=/data GC_CACHE_DIR=/opt/cache
WORKDIR /app

COPY backend/requirements-api.txt backend/
RUN pip install -r backend/requirements-api.txt

COPY backend/app backend/app

# El modelo ONNX (118 MB) queda dentro de la imagen: arranque sin descargas ni dependencia de HF.
ARG BAKE_MODEL=1
RUN if [ "$BAKE_MODEL" = "1" ]; then \
      python -c "import sys; sys.path.insert(0, 'backend'); from app.embedder import model_files; print(model_files())"; \
    fi

RUN useradd -m app && mkdir -p /data && chown -R app /data /opt/cache
USER app
VOLUME /data
EXPOSE 8080
# PORT lo definen Cloud Run, Render, HF Spaces, etc.
CMD exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips='*'
