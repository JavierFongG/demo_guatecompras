# Publicar la plataforma en internet

La plataforma se divide en **cuatro piezas independientes**. Cada una se puede publicar en una
plataforma distinta (o todas en el mismo servidor):

```
             Guatecompras (OCDS)
                    │  zips mensuales
                    ▼
 ┌──────────────────────────────┐  publica   ┌──────────────────────────┐
 │ 1. PIPELINE  (diario)        │──────────▶ │ 2. ÍNDICE versionado     │
 │ download → ingest → publish  │            │ manifest.json            │
 │ GitHub Actions · tu Mac ·    │            │ <versión>/db.gz + emb    │
 │ Cloud Run Jobs · cron        │            │ HF Datasets · R2 · GCS   │
 └──────────────────────────────┘            └────────────┬─────────────┘
                                                          │ descarga y se actualiza sola
                                                          ▼
 ┌──────────────────────────────┐   HTTPS    ┌──────────────────────────┐
 │ 4. FRONTEND  (estático)      │──────────▶ │ 3. API  (solo lectura)   │
 │ Cloudflare Pages · GitHub    │  /api/...  │ FastAPI + ONNX + SQLite  │
 │ Pages · Netlify · Vercel     │            │ Oracle · Cloud Run · VPS │
 └──────────────────────────────┘            └──────────────────────────┘
```

## Qué necesita cada pieza (18 meses ≈ 550 mil concursos)

| Pieza | CPU / RAM | Disco | Notas |
|---|---|---|---|
| Frontend | — | ~0.5 MB | Archivos estáticos. Navegación con `#/`, sin configuración de rutas |
| API | 1 vCPU · **~0.6–0.8 GB** | ~1.3 GB (índice) | Sin PyTorch. Imagen ~450 MB con el modelo incluido |
| Índice publicado | — | **~700 MB** por versión (se guardan 2) | DB comprimida ~490 MB + embeddings int8 ~210 MB |
| Pipeline | 2–4 vCPU · ~1.5 GB | ~2.5 GB (zips + índice) | Diario: minutos. Primera vez: 1–3 h en CPU (mejor en tu Mac) |

**Optimizaciones respecto a la versión anterior:**
- Modelo ONNX int8 en lugar de PyTorch: de ~2 GB de dependencias a 234 MB, y unas 8 veces menos RAM.
- Embeddings en int8: 4 veces menos espacio, con el mismo ranking (98 de los 100 primeros resultados coinciden).
- Índice de texto sin la copia redundante de los textos: −15% de base de datos.
- Respuestas comprimidas con gzip.
- La API no descarga ni procesa datos: solo lee el índice publicado.

## Combinaciones recomendadas (gratis)

> Condiciones revisadas en octubre de 2026. Los planes gratuitos cambian (Oracle y Hugging Face
> los recortaron este año); revisa antes de elegir.

| | Frontend | API | Índice | Pipeline |
|---|---|---|---|---|
| **A. Siempre encendido** ⭐ | Cloudflare Pages | **Oracle Cloud Always Free** (ARM 2 OCPU / 12 GB) | Hugging Face Datasets | GitHub Actions |
| **B. Serverless** | Cloudflare Pages | **Google Cloud Run** (escala a cero) | HF Datasets o Cloud Storage | GitHub Actions |
| **C. Un solo servidor** | — (incluido) | Imagen `allinone` en Oracle / VPS | disco local | botón "Actualizar datos" o cron |

- **A** no tiene arranques en frío y aguanta uso continuo. Pide tarjeta para verificar la cuenta, a veces es difícil conseguir capacidad ARM, y Oracle puede reclamar una VM que pase 7 días inactiva.
- **B** sale gratis con uso bajo: unas 50 horas activas al mes con 2 GiB. Cada arranque en frío tarda 30–60 s, porque descarga el índice. Pide cuenta de facturación.
- **C** es lo más simple: una URL y un contenedor.

---

## Paso 1 · Elegir dónde guardar el índice

### Hugging Face Datasets (gratis, recomendado)
1. Crea una cuenta y un token con permiso **Write** (Settings → Access Tokens).
2. Destino para publicar: `hf://datasets/TU_USUARIO/guatecompras-index/index` (el repo se crea solo).
3. URL de lectura para la API: `https://huggingface.co/datasets/TU_USUARIO/guatecompras-index/resolve/main/index`
4. Si lo haces privado (`HF_PRIVATE=1` al publicar), da a la API un token de lectura en `GC_ARTIFACTS_TOKEN`.

### Cloudflare R2 (10 GB gratis, sin costo de salida)
1. Crea un bucket y activa el **acceso público** (dominio `pub-xxxx.r2.dev` o uno propio).
2. Crea un token de API S3 (Access Key ID / Secret).
3. Destino: `s3://TU_BUCKET/index` con `S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
4. URL de lectura: `https://pub-xxxx.r2.dev/index`.

### Google Cloud Storage (5 GB gratis en us-central1/us-east1/us-west1)
Usa la interoperabilidad S3 (claves HMAC) con `S3_ENDPOINT_URL=https://storage.googleapis.com`,
destino `s3://TU_BUCKET/index`. Lectura pública: `https://storage.googleapis.com/TU_BUCKET/index`.

### Carpeta local
`dir:/ruta` para publicar, y `file:///ruta` para leer. Sirve si la API y el pipeline están en la misma máquina (ver `docker-compose.yml`).

## Paso 2 · Primera publicación (desde tu Mac)

La primera vez se calculan ~550 mil embeddings. Es más rápido hacerlo en tu Mac que en un servidor gratuito:

```bash
cd ~/Documents/wais/guatecompras/demo/backend
.venv/bin/pip install -r requirements.txt -r requirements-publish.txt
.venv/bin/python -m scripts.download            # si aún no tienes los 18 meses
.venv/bin/python -m scripts.ingest
export HF_TOKEN=hf_xxx                           # o AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / S3_ENDPOINT_URL
.venv/bin/python -m scripts.publish --to hf://datasets/TU_USUARIO/guatecompras-index/index
```

## Paso 3 · Pipeline diario con GitHub Actions (gratis)

1. Copia los workflows a su lugar y sube el proyecto a un repositorio de GitHub. `data/` ya está en `.gitignore`.
   ```bash
   mkdir -p .github/workflows && cp deploy/github-workflows/*.yml .github/workflows/
   ```
2. En **Settings → Secrets and variables → Actions**:
   - Variables:
     - `GC_PUBLISH_TARGET`: el destino del paso 1.
     - `GC_ARTIFACTS_URL`: la URL de lectura.
     - `S3_ENDPOINT_URL`: solo si usas R2 o GCS.
     - `API_URL`: opcional, para avisar a la API cuando haya una versión nueva.
   - Secrets:
     - `HF_TOKEN`, o bien `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`.
     - `GC_ADMIN_TOKEN`: opcional, para avisar a la API.
3. **Actions → Actualizar datos → Run workflow** para probar. Después corre solo todos los días a las 04:17 (hora de Guatemala).

Cada corrida hace lo siguiente:
1. Trae el índice publicado.
2. Descarga de Guatecompras solo los meses que cambiaron.
3. Calcula embeddings solo de lo nuevo.
4. Publica la nueva versión y conserva las 2 más recientes.

Los repos públicos tienen minutos ilimitados; los privados, 2,000 al mes.

**Otras opciones de pipeline:**
- **Tu Mac**: `cd backend && GC_PUBLISH_TARGET=… .venv/bin/python -m scripts.run_pipeline`, programado con cron o launchd.
- **Contenedor**: `docker build -f deploy/pipeline.Dockerfile -t gc-pipeline .`, para Cloud Run Jobs o cron en un VPS.

## Paso 4 · API

La imagen `deploy/api.Dockerfile` incluye el modelo ONNX y arranca en modo `api`:
1. Descarga la versión vigente del índice.
2. Revisa cada `GC_ARTIFACTS_POLL` segundos (30 min por defecto) si hay una nueva.
3. Cuando la hay, la cambia sin reiniciar.

```bash
docker build -f deploy/api.Dockerfile -t guatecompras-api .
docker run -d --name gc-api -p 8080:8080 -v gc-data:/data \
  -e GC_ARTIFACTS_URL=https://huggingface.co/datasets/TU_USUARIO/guatecompras-index/resolve/main/index \
  -e GC_CORS_ORIGINS=https://tu-front.pages.dev \
  -e GC_ADMIN_TOKEN=una-clave-larga \
  --restart unless-stopped guatecompras-api
```

### A · Oracle Cloud Always Free
1. Crea una instancia **VM.Standard.A1.Flex** (Ubuntu, 2 OCPU, 12 GB) con 50–100 GB de disco.
2. Instala Docker (`curl -fsSL https://get.docker.com | sh`), clona el repo y ejecuta el `docker run` de arriba. La imagen es multiplataforma y funciona en ARM.
3. HTTPS sin abrir puertos, con **Cloudflare Tunnel** (gratis):
   ```bash
   # prueba rápida (URL temporal *.trycloudflare.com)
   docker run -d --network host cloudflare/cloudflared tunnel --url http://localhost:8080
   ```
   Para una URL fija, crea un túnel con nombre en el panel de Cloudflare (Zero Trust → Tunnels).
4. Alternativa: abrir el puerto 443 en la *Security List* y usar Caddy como proxy con certificado automático.

### B · Google Cloud Run
El sistema de archivos de Cloud Run vive en memoria, así que el índice descargado (~1.3 GB) cuenta como RAM. Usa **2 GiB** (sube a 3 GiB si ves errores de memoria).

```bash
REGION=us-central1; PROJECT=tu-proyecto
IMAGE=$REGION-docker.pkg.dev/$PROJECT/guatecompras/api
gcloud artifacts repositories create guatecompras --repository-format=docker --location=$REGION
docker buildx build --platform linux/amd64 -f deploy/api.Dockerfile -t $IMAGE --push .
gcloud run deploy guatecompras-api --image $IMAGE --region $REGION \
  --memory 2Gi --cpu 1 --min-instances 0 --max-instances 2 --concurrency 20 \
  --allow-unauthenticated \
  --set-env-vars GC_ARTIFACTS_URL=https://…/index,GC_ARTIFACTS_POLL=0,GC_CORS_ORIGINS=https://tu-front.pages.dev
```
Con `GC_ARTIFACTS_POLL=0`, cada instancia nueva descarga la versión vigente al arrancar. Como escala a cero, siempre toma los datos del día.

### Otras
- **Hugging Face Spaces (PRO, ~US$9/mes)**: Space tipo Docker con `deploy/api.Dockerfile`. Agrega `app_port: 8080` en el README del Space y configura las variables en Settings.
- **Cualquier VPS de 1 GB o más**: el mismo `docker run`.
- **Google e2-micro**: tiene 1 GB, así que es justo; agrega 1–2 GB de swap.

## Paso 5 · Frontend

Es un sitio estático. Solo necesita saber dónde está la API, en el momento de compilar:

```bash
cd frontend
VITE_API_BASE=https://tu-api.example.com npm run build     # genera frontend/dist
```

- **Cloudflare Pages**: Create project → conecta el repo.
  - Root directory: `frontend`
  - Build command: `npm run build`
  - Output: `dist`
  - Variable de entorno: `VITE_API_BASE`.
- **GitHub Pages**: workflow incluido en `deploy/github-workflows/frontend-pages.yml`; cópialo a `.github/workflows/`. Define la variable `VITE_API_BASE` y en Settings → Pages elige "GitHub Actions".
- **Netlify / Vercel**: la misma configuración que Cloudflare Pages.

Agrega la URL del frontend a `GC_CORS_ORIGINS` en la API; si son varias, sepáralas con comas.

## Opción C · Todo en uno en un servidor

```bash
GC_ADMIN_TOKEN=una-clave-larga docker compose up -d app       # http://servidor:8000
```

Incluye el frontend, la API y el botón **Actualizar datos**, que pide la clave de administrador. Otra variante del mismo `docker-compose.yml` es `--profile split`: API de solo lectura más un pipeline que publica en `./data/published`.

## Seguridad

- **`GC_ADMIN_TOKEN`**: protege `/api/update`, `/api/reload` y `/api/admin/*`.
  - En modo `api`, sin clave esas rutas quedan deshabilitadas.
  - En la interfaz, el botón pide la clave y la guarda solo en ese navegador.
- **En modo `api` no hay botón de actualizar**: la API pública nunca descarga ni procesa datos.
- **`GC_RATE_LIMIT`**: límite de solicitudes por minuto por IP. Por defecto 120 en modo api; 0 lo desactiva.
- **`GC_CORS_ORIGINS`**: solo esos dominios pueden llamar a la API desde un navegador.
- **Datos personales**: los datos son públicos (licencia CC BY 4.0), pero algunos proveedores son personas individuales con su NIT. Tenlo en cuenta al hacer pública la búsqueda por proveedor.

## Variables de entorno

| Variable | Pieza | Por defecto | Descripción |
|---|---|---|---|
| `GC_MODE` | API | `local` | `local` o `api` |
| `GC_ARTIFACTS_URL` | API, pipeline | — | URL de lectura del índice publicado (`https://…` o `file://…`) |
| `GC_ARTIFACTS_TOKEN` | API, pipeline | — | Token si el índice es privado |
| `GC_ARTIFACTS_POLL` | API | `1800` | Segundos entre revisiones de versión nueva (0 = solo al arrancar) |
| `GC_PUBLISH_TARGET` | pipeline | — | `dir:…` · `s3://…` · `hf://…` |
| `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | pipeline | — | Para R2, B2, GCS o S3 |
| `HF_TOKEN`, `HF_PRIVATE` | pipeline | — | Para Hugging Face Datasets |
| `GC_ADMIN_TOKEN` | API | — | Clave de administración |
| `GC_ADMIN_REQUIRED` | API | `1` en api | Exigir clave también en modo local |
| `GC_CORS_ORIGINS` | API | localhost:5173 | Orígenes permitidos, separados por comas |
| `GC_RATE_LIMIT` | API | 0 local / 120 api | Solicitudes por minuto por IP |
| `GC_DATA_DIR` | todas | `./data` | Carpeta de datos |
| `GC_WINDOW_DAYS` | pipeline | `548` | Ventana de datos (≈ 18 meses) |
| `GC_EMBEDDER` | API, pipeline | `onnx` | `onnx` · `st` · `hash`. **Usa el mismo en pipeline y API** |
| `GC_ONNX_REPO`, `GC_ONNX_FILE` | API, pipeline | `Xenova/multilingual-e5-small`, `onnx/model_quantized.onnx` | Modelo ONNX |
| `GC_MODEL_DIR` | API, pipeline | — | Carpeta con `*.onnx` + `tokenizer.json` (sin descargar de HF) |
| `GC_THREADS`, `GC_MAX_TOKENS` | API, pipeline | auto, `256` | Hilos de ONNX Runtime y longitud máxima de texto |
| `VITE_API_BASE` | frontend (build) | vacío | URL de la API si está en otro dominio |

> El pipeline y la API deben usar **el mismo modelo**. Si no coinciden, `/api/health` muestra una
> advertencia y la búsqueda semántica no funciona bien.
