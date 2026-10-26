# Buscador de concursos · Guatecompras

Plataforma para explorar concursos públicos de Guatemala. Corre en tu máquina o publicada en internet
como servicios independientes (ver **[DEPLOY.md](DEPLOY.md)**). Tiene un menú lateral con dos
funcionalidades sobre los mismos datos:

1. **Buscador**: búsqueda en lenguaje natural con filtros.
2. **Oportunidades por proveedor**: escribes un NIT o nombre; la app reúne todo lo que se le ha
   adjudicado, detecta sus líneas de negocio (agrupando los embeddings de su historial) y muestra los
   concursos abiertos más parecidos, explicando a qué adjudicación anterior se parece cada uno.

El buscador combina:

- **Búsqueda semántica**: embeddings multilingües (`multilingual-e5-small` en ONNX cuantizado, sin PyTorch)
  guardados en int8, y similitud coseno.
- **Búsqueda por palabras clave**: SQLite FTS5, sin acentos y con stemming simple para plurales.
- **Modo híbrido** (por defecto): fusión de ambos rankings con Reciprocal Rank Fusion.
- **Filtros clásicos**: fecha de publicación, estado, categoría, modalidad, departamento, tipo de entidad,
  entidad compradora (con autocompletado), proveedor (nombre o NIT), monto adjudicado,
  "solo abiertos" y "solo adjudicados".
- **Ficha del concurso**: ítems, ofertas, adjudicaciones, documentos, enlace a Guatecompras y
  **referencia de precios**: los 5 concursos pasados y adjudicados más parecidos por descripción
  y entidad, con su monto, proveedor y el rango (mínimo · mediana · máximo).

Incluye un botón **Actualizar datos** que descarga lo más reciente del portal y actualiza el
índice en segundo plano, sin reiniciar.

En local, la única conexión a internet es para descargar los datos abiertos de Guatecompras y, la
primera vez, el modelo de embeddings (~135 MB, que luego queda en caché).

```
demo/
├── backend/
│   ├── app/            API: main.py · search.py · suppliers.py · embedder.py (ONNX) · vectors.py (int8)
│   │                   artifacts.py (publicar/sincronizar índice) · updater.py (botón Actualizar)
│   ├── scripts/        download · ingest · publish · run_pipeline
│   └── requirements-*.txt   api (liviano) · pipeline · publish (opcional)
├── frontend/           React + Vite (estático; VITE_API_BASE para API en otro dominio)
├── deploy/             api · pipeline · allinone (Dockerfiles) · github-workflows/ (copiar a .github/workflows)
├── docker-compose.yml
├── data/               (se genera) zips, guatecompras.db, emb_i8.npy, emb_scale.npy
├── setup.sh · start.sh uso local
└── DEPLOY.md           cómo publicar cada servicio
```

## Requisitos

- Python 3.10 o superior
- Node 18 o superior

## Puesta en marcha

```bash
cd ~/Documents/wais/guatecompras/demo
chmod +x setup.sh start.sh
./setup.sh          # últimos 18 meses (o ./setup.sh 365 para un año)
./start.sh          # abre http://localhost:5173
```

`setup.sh` hace lo siguiente:

1. Crea `backend/.venv` e instala dependencias.
2. Ejecuta `npm install`.
3. Descarga los zips mensuales desde `https://ocds.guatecompras.gt/file/json/AAAA/M`.
4. Indexa los concursos publicados en los últimos N días (por defecto 548 ≈ 18 meses, ~550 mil
   concursos) y calcula sus embeddings. La primera vez tarda del orden de 30–60 min en una Mac
   (CPU); las siguientes solo procesan lo nuevo.

> Si ya tenías un índice de la versión anterior (PyTorch, `embeddings.npy`), la primera ingesta
> con esta versión recalcula todos los embeddings con el modelo ONNX, una sola vez.

## Actualizar los datos

**Desde la interfaz:** botón **Actualizar datos** (arriba a la derecha). Hace lo siguiente en
segundo plano mientras sigues buscando:

1. Consulta el portal y descarga solo los meses cuyo archivo cambió.
2. Reconstruye el índice de forma **incremental**: reutiliza el embedding de cada concurso cuyo
   texto no cambió y calcula solo los nuevos o modificados.
3. Recarga el buscador sin reiniciar el servidor.

Muestra el progreso, permite cancelar y ver el detalle del proceso.

**Desde la terminal** (equivalente):

```bash
cd backend
.venv/bin/python -m scripts.download      # solo baja los meses que cambiaron
.venv/bin/python -m scripts.ingest        # incremental; --full recalcula todo
curl -X POST localhost:8000/api/reload    # o reinicia ./start.sh
```

## Modo "una sola URL" (sin Vite)

```bash
cd frontend && npm run build && cd ..
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
# abre http://localhost:8000
```

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET  | `/api/health` | Estado del índice y modelo usado |
| GET  | `/api/facets` | Valores y conteos para los filtros |
| POST | `/api/search` | Búsqueda: `{ q, mode: hybrid\|semantic\|keyword, filtros…, sort, page }` |
| GET  | `/api/buyers?q=` | Autocompletado de entidades compradoras |
| GET  | `/api/concursos/{nog}` | Detalle completo |
| GET  | `/api/concursos/{nog}/referencias?k=5` | Concursos anteriores adjudicados más parecidos por descripción y entidad (referencia de precios) |
| GET  | `/api/suppliers?q=` | Autocompletado de proveedores por NIT o nombre |
| GET  | `/api/suppliers/{nit}` | Perfil: historial de adjudicaciones, montos, principales compradores |
| POST | `/api/recommend` | Concursos relevantes para un NIT según su historial (acepta los mismos filtros que `/api/search`) |
| POST | `/api/reload` | Recarga el índice tras una nueva ingesta 🔒 |
| POST | `/api/update` | Inicia la actualización de datos en segundo plano (solo modo local) 🔒 |
| GET  | `/api/update/status` | Progreso de la actualización |
| POST | `/api/update/cancel` | Cancela la actualización en curso 🔒 |
| POST | `/api/admin/sync` | Fuerza revisar si hay un índice publicado nuevo (modo api) 🔒 |

🔒 = requiere el encabezado `X-Admin-Token` cuando hay `GC_ADMIN_TOKEN` configurado (obligatorio
fuera del modo local).

La documentación interactiva está en http://localhost:8000/docs.

## Configuración (variables de entorno)

Las principales; la lista completa y comentada está en `backend/app/config.py` y en
[DEPLOY.md](DEPLOY.md#variables-de-entorno).

| Variable | Por defecto | Uso |
|---|---|---|
| `GC_MODE` | `local` | `local` (todo en una máquina) o `api` (solo lectura, índice publicado) |
| `GC_WINDOW_DAYS` | `548` | Ventana de datos en días (≈ 18 meses) |
| `GC_DATA_DIR` | `./data` | Carpeta de datos |
| `GC_EMBEDDER` | `onnx` | `st` = sentence-transformers (instalarlo aparte), `hash` = pruebas sin modelo |
| `GC_ADMIN_TOKEN` | — | Clave para actualizar/recargar |

## Notas sobre los datos

- Fuente: [ocds.guatecompras.gt](https://ocds.guatecompras.gt), estándar OCDS 1.1, licencia CC BY 4.0
  (Ministerio de Finanzas Públicas, DGAE).
- El filtro de fechas usa la **fecha de publicación del concurso**.
- Espacio aproximado con 18 meses (~550 mil concursos): ~630 MB de zips (solo pipeline), ~1.1 GB de
  base de datos y ~210 MB de embeddings int8.
- El "monto adjudicado" suma las adjudicaciones activas del concurso, en quetzales.
- No incluye publicaciones NPG ni datos de ejecución o pagos del SIAF/SIGES.
