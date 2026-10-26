"""Actualización de datos en segundo plano: descarga los meses que cambiaron en el portal,
reconstruye el índice (reutilizando embeddings) y recarga el buscador sin reiniciar.

Los pasos corren como subprocesos (los mismos scripts de la línea de comandos), así la
memoria que usan se libera al terminar y su salida sirve como registro de progreso.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable

from . import config

BACKEND_DIR = config.ROOT / "backend"


class Updater:
    def __init__(self, on_done: Callable[[], None]):
        self.on_done = on_done
        self.lock = threading.Lock()
        self.state = {"running": False, "phase": None, "progress": None, "message": None,
                      "started_at": None, "finished_at": None, "ok": None, "error": None, "summary": None}
        self.log: deque[str] = deque(maxlen=200)
        self.proc: subprocess.Popen | None = None

    def status(self) -> dict:
        with self.lock:
            return {**self.state, "log": list(self.log)[-40:]}

    def start(self, days: int | None = None) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.log.clear()
            self.state.update(running=True, phase="download", progress=None, message="Consultando el portal…",
                              started_at=time.time(), finished_at=None, ok=None, error=None, summary=None)
        threading.Thread(target=self._run, args=(days or config.WINDOW_DAYS,), daemon=True).start()
        return True

    def cancel(self) -> None:
        p = self.proc
        if p and p.poll() is None:
            p.terminate()

    # ------------------------------------------------------------------
    def _set(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def _run(self, days: int) -> None:
        try:
            self._step("download", ["-m", "scripts.download", "--days", str(days)])
            self._step("ingest", ["-m", "scripts.ingest", "--days", str(days)])
            self._set(phase="reload", message="Recargando el buscador…", progress=None)
            self.on_done()
            self._set(ok=True, message="Datos actualizados")
        except Exception as e:  # noqa: BLE001
            self._set(ok=False, error=str(e), message="La actualización falló")
        finally:
            self._set(running=False, finished_at=time.time())
            self.proc = None

    def _step(self, phase: str, args: list[str]) -> None:
        self._set(phase=phase, progress=None,
                  message="Descargando archivos del portal…" if phase == "download" else "Procesando concursos…")
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen([sys.executable, *args], cwd=BACKEND_DIR, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        buf = b""
        assert self.proc.stdout
        while True:
            ch = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(1)
            if not ch:
                break
            buf += ch
            # las barras de progreso usan \r; se tratan como líneas
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._line(phase, line)
        if buf.strip():
            self._line(phase, buf.decode("utf-8", "replace").strip())
        code = self.proc.wait()
        if code != 0:
            tail = " | ".join(list(self.log)[-3:])
            raise RuntimeError(f"El paso '{phase}' terminó con código {code}: {tail}")

    def _line(self, phase: str, line: str) -> None:
        # Las barras de descarga se repiten muchas veces: solo se guarda la última en el log
        is_bar = bool(re.match(r"^\s*[\d.]+\s*/\s*[\d.]+ MB$", line))
        with self.lock:
            if is_bar and self.log and re.match(r"^\s*[\d.]+\s*/\s*[\d.]+ MB$", self.log[-1]):
                self.log[-1] = line
            else:
                self.log.append(line)
        if m := re.match(r"\[(\d+)/(\d+)\]\s*(.*)", line):           # download: [i/n] mes
            i, n = int(m[1]), int(m[2])
            self._set(progress=(i - 1) / n, message=f"Revisando mes {i} de {n}: {m[3][:60]}")
        elif m := re.match(r"\s*([\d.]+)\s*/\s*([\d.]+) MB", line):  # barra de descarga
            self._set(message=f"Descargando… {m[1]} / {m[2]} MB")
        elif m := re.match(r"\[leer (\d+)/(\d+)\]", line):
            self._set(progress=int(m[1]) / int(m[2]) * 0.3, message=f"Leyendo archivo {m[1]} de {m[2]}")
        elif line.startswith("Embeddings reutilizados"):
            self._set(progress=0.3, message=line)
        elif m := re.match(r"\[embeddings\] ([\d,]+)/([\d,]+) \((\d+)%\)(.*)", line):
            pct = int(m[3])
            self._set(progress=0.3 + 0.7 * pct / 100, message=f"Calculando embeddings {m[1]} de {m[2]}{m[4]}")
        elif m := re.match(r"Listo en (\d+)s → ([\d,]+) concursos \(([\d,]+) embeddings nuevos\)", line):
            secs = int(m[1])
            took = f"{secs // 60} min" if secs >= 60 else f"{secs} s"
            self._set(summary=f"{m[2]} concursos en el índice · {m[3]} nuevos o modificados · {took}", progress=1.0)
        elif line.startswith("Listo.") and phase == "download":
            self._set(message=line)
