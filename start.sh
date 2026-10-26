#!/usr/bin/env bash
# Levanta backend (FastAPI :8000) y frontend (Vite :5173) usando los entornos del proyecto.
# Ctrl+C detiene ambos.
set -euo pipefail
cd "$(dirname "$0")"
VENV=backend/.venv

if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "El entorno backend/.venv no existe o usa Python < 3.10. Corre primero ./setup.sh"
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "Faltan dependencias del frontend. Corre primero ./setup.sh"
  exit 1
fi

"$VENV/bin/python" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT INT TERM

# Esperar a que el backend cargue el índice y el modelo (puede tardar ~10-30 s)
printf "==> Esperando al backend"
for _ in $(seq 1 120); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then echo " listo"; break; fi
  if ! kill -0 $BACK 2>/dev/null; then echo; echo "El backend se detuvo; revisa el error arriba."; exit 1; fi
  printf "."; sleep 1
done

(cd frontend && npm run dev -- --host 127.0.0.1)
