# Pipeline de datos como contenedor (Cloud Run Jobs, cron en un servidor, etc.).
#   docker build -f deploy/pipeline.Dockerfile -t guatecompras-pipeline .
#   docker run --rm -v $PWD/data:/data -e GC_PUBLISH_TARGET=hf://datasets/usuario/guatecompras-index/index \
#              -e GC_ARTIFACTS_URL=https://huggingface.co/datasets/usuario/guatecompras-index/resolve/main/index \
#              -e HF_TOKEN=… guatecompras-pipeline
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GC_MODE=local GC_DATA_DIR=/data GC_CACHE_DIR=/opt/cache
WORKDIR /app/backend

COPY backend/requirements-api.txt backend/requirements-pipeline.txt backend/requirements-publish.txt ./
RUN pip install -r requirements-pipeline.txt -r requirements-publish.txt
COPY backend/app app
COPY backend/scripts scripts
RUN python -c "from app.embedder import model_files; print(model_files())"

VOLUME /data
CMD ["python", "-m", "scripts.run_pipeline"]
