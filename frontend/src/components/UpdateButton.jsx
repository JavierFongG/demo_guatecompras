import { useEffect, useRef, useState } from 'react'
import { adminToken, api, fmtDateTime } from '../api.js'

// Botón "Actualizar datos": descarga lo más reciente del portal y reconstruye el índice
// en segundo plano. Muestra el progreso y avisa al terminar.
export default function UpdateButton({ meta, onUpdated, big = false, placement = 'down' }) {
  const [st, setSt] = useState(null)
  const [open, setOpen] = useState(false)
  const [showLog, setShowLog] = useState(false)
  const [needToken, setNeedToken] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const timer = useRef(null)
  const wasRunning = useRef(false)

  const poll = async () => {
    try {
      const s = await api.updateStatus()
      setSt(s)
      if (s.running) {
        wasRunning.current = true
        timer.current = setTimeout(poll, 1500)
      } else if (wasRunning.current) {
        wasRunning.current = false
        setOpen(true)
        if (s.ok) onUpdated?.()
      }
    } catch {
      timer.current = setTimeout(poll, 3000)
    }
  }

  useEffect(() => { poll(); return () => clearTimeout(timer.current) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    try {
      const s = await api.updateStart()
      setSt(s); setOpen(true); setNeedToken(false); wasRunning.current = true
      clearTimeout(timer.current); timer.current = setTimeout(poll, 800)
    } catch (e) {
      if (e.status === 401 || e.status === 403) { setNeedToken(true); setOpen(true); return }
      setSt({ ok: false, error: e.message }); setOpen(true)
    }
  }
  const saveToken = (e) => { e.preventDefault(); adminToken.set(tokenInput.trim()); setTokenInput(''); start() }
  const cancel = async () => { await api.updateCancel().catch(() => {}) }

  const running = st?.running
  const pct = st?.progress != null ? Math.round(st.progress * 100) : null
  const elapsed = st?.started_at ? Math.round(((st.finished_at || Date.now() / 1000) - st.started_at) / 60) : 0

  return (
    <div className={`updater ${big ? 'big' : ''} ${placement}`}>
      <button className={`btn update-btn ${running ? 'running' : ''}`} onClick={() => (running ? setOpen(!open) : start())}
        title={meta?.built_at ? `Última actualización: ${fmtDateTime(meta.built_at)}` : 'Descargar datos'}>
        <svg viewBox="0 0 24 24" aria-hidden className={running ? 'spin' : ''}>
          <path d="M20 12a8 8 0 1 1-2.34-5.66" /><path d="M20 4v5h-5" />
        </svg>
        {running ? `Actualizando${pct != null ? ` ${pct}%` : '…'}` : big ? 'Descargar datos y construir índice' : 'Actualizar datos'}
      </button>

      {open && needToken && (
        <form className="upd-pop" onSubmit={saveToken}>
          <button type="button" className="x small" onClick={() => { setOpen(false); setNeedToken(false) }} aria-label="Cerrar">×</button>
          <strong>Clave de administrador</strong>
          <p className="muted small">Actualizar los datos requiere la clave configurada en el servidor (GC_ADMIN_TOKEN).
            Se guarda solo en este navegador.</p>
          <input className="mini" type="password" autoFocus value={tokenInput} onChange={(e) => setTokenInput(e.target.value)}
            placeholder="Clave" aria-label="Clave de administrador" />
          <div className="upd-actions"><button className="btn primary" type="submit">Guardar y actualizar</button></div>
        </form>
      )}

      {open && st && !needToken && (
        <div className="upd-pop" role="status">
          <button className="x small" onClick={() => setOpen(false)} aria-label="Cerrar">×</button>
          {running && (
            <>
              <strong>Actualizando datos</strong>
              <p className="muted">{st.message}</p>
              <div className="progress"><span style={{ width: `${pct ?? 3}%` }} className={pct == null ? 'indet' : ''} /></div>
              <p className="muted small">
                Puedes seguir buscando mientras tanto. {elapsed > 0 && `Lleva ${elapsed} min.`}
                {' '}La primera vez con 18 meses puede tardar 20–40 min; después solo procesa lo nuevo.
              </p>
              <div className="upd-actions">
                <button className="link" onClick={() => setShowLog(!showLog)}>{showLog ? 'Ocultar detalle' : 'Ver detalle'}</button>
                <button className="link danger" onClick={cancel}>Cancelar</button>
              </div>
            </>
          )}
          {!running && st.ok === true && (
            <>
              <strong className="ok">✓ Datos actualizados</strong>
              <p className="muted">{st.summary || st.message}</p>
            </>
          )}
          {!running && st.ok === false && (
            <>
              <strong className="err">No se pudo actualizar</strong>
              <p className="muted">{st.error}</p>
              <div className="upd-actions">
                <button className="link" onClick={() => setShowLog(!showLog)}>{showLog ? 'Ocultar detalle' : 'Ver detalle'}</button>
                <button className="link" onClick={start}>Reintentar</button>
              </div>
            </>
          )}
          {showLog && st.log?.length > 0 && <pre className="upd-log">{st.log.join('\n')}</pre>}
        </div>
      )}
    </div>
  )
}
