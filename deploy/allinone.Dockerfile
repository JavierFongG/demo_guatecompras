# Todo en uno: frontend + API + botón "Actualizar datos" en una sola URL (un VPS, Oracle, etc.).
#   docker build -f deploy/allinone.Dockerfile -t guatecompras .
#   docker run -p 8000:8000 -v $PWD/data:/data -e GC_ADMIN_TOKEN=una-clave-larga guatecompras
FROM node:20-slim AS front
WORKDIR /front
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GC_MODE=local GC_ADMIN_REQUIRED=1 GC_DATA_DIR=/data GC_CACHE_DIR=/opt/cache GC_RATE_LIMIT=120 \
    GC_CORS_ORIGINS=
WORKDIR /app
COPY backend/requirements-api.txt backend/requirements-pipeline.txt backend/
RUN pip install -r backend/requirements-pipeline.txt
COPY backend/app backend/app
COPY backend/scripts backend/scripts
COPY --from=front /front/dist frontend/dist
RUN python -c "import sys; sys.path.insert(0, 'backend'); from app.embedder import model_files; print(model_files())"
VOLUME /data
EXPOSE 8000
CMD exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'
