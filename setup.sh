#!/usr/bin/env bash
# Instala dependencias en entornos aislados, descarga los datos y construye el índice.
#   ./setup.sh [días]          por defecto 548 (≈ 18 meses)
#   PYTHON=/ruta/python3.11 ./setup.sh   para forzar un intérprete
#   REINDEX=1 ./setup.sh       recalcula todos los embeddings (normalmente se reutilizan)
# Todo queda contenido en el proyecto:
#   backend/.venv           entorno virtual de Python (nada se instala global)
#   frontend/node_modules   dependencias de Node
set -euo pipefail
cd "$(dirname "$0")"
DAYS="${1:-548}"
VENV=backend/.venv

# --- Elegir un Python >= 3.10 -------------------------------------------------
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; }

find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for c in python3.13 python3.12 python3.11 python3.10 \
           /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 \
           /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
           python3; do
    if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then command -v "$c"; return; fi
  done
  return 1
}

PY=$(find_python) || {
  echo "ERROR: se necesita Python 3.10 o superior. Indica la ruta con PYTHON=/ruta/python3.11 ./setup.sh"
  exit 1
}
echo "==> Usando $PY ($("$PY" --version))"

# Recrear el venv si no existe o si fue creado con una versión vieja (p. ej. 3.9)
if [ -x "$VENV/bin/python" ] && ! py_ok "$VENV/bin/python"; then
  echo "==> El venv existente usa $("$VENV/bin/python" --version); se recrea"
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi

echo "==> Backend: dependencias en $VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r backend/requirements.txt

echo "==> Frontend: dependencias en frontend/node_modules"
(cd frontend && npm install --no-fund --no-audit)

echo "==> Descargando archivos mensuales OCDS (últimos $DAYS días)"
(cd backend && .venv/bin/python -m scripts.download --days "$DAYS")

echo "==> Construyendo índice (incremental; la primera vez descarga el modelo ONNX, ~135 MB)"
if [ -n "${REINDEX:-}" ]; then FULL="--full"; else FULL=""; fi
(cd backend && GC_WINDOW_DAYS="$DAYS" .venv/bin/python -m scripts.ingest --days "$DAYS" $FULL)

echo
echo "Listo. Ejecuta ./start.sh y abre http://localhost:5173"
