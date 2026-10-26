import { useEffect, useState } from 'react'
import { API_BASE, api, fmtDateTime } from './api.js'
import UpdateButton from './components/UpdateButton.jsx'
import SearchView from './views/SearchView.jsx'
import SupplierView from './views/SupplierView.jsx'

// Funcionalidades disponibles en el menú lateral. Para agregar una nueva: crear la vista en
// src/views y registrarla aquí.
const VIEWS = [
  {
    id: 'buscar', label: 'Buscador', hint: 'Búsqueda de concursos en lenguaje natural',
    icon: <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></svg>,
  },
  {
    id: 'proveedor', label: 'Oportunidades por proveedor', hint: 'Concursos relevantes según el historial de un NIT',
    icon: <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="0.8" /></svg>,
  },
]

// Ruta en el hash: #/buscar  ·  #/proveedor  ·  #/proveedor/<NIT>
function parseHash() {
  const [, view = 'buscar', arg = null] = (window.location.hash || '').replace(/^#/, '').split('/')
  return { view: VIEWS.some((v) => v.id === view) ? view : 'buscar', arg: arg ? decodeURIComponent(arg) : null }
}

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [health, setHealth] = useState(null)
  const [facets, setFacets] = useState(null)
  const [error, setError] = useState(null)
  const [dataVersion, setDataVersion] = useState(0)
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const go = (view, arg) => {
    window.location.hash = `/${view}${arg ? `/${encodeURIComponent(arg)}` : ''}`
    setNavOpen(false)
  }

  // Estado del backend; reintenta cada 2 s mientras arranca.
  useEffect(() => {
    let timer
    let cancelled = false
    const check = () => {
      api.health().then((h) => {
        if (cancelled) return
        setHealth(h)
        if (h.ready) api.facets().then(setFacets).catch((e) => setError(e.message))
        else if (!h.updating) timer = setTimeout(check, 2000)
      }).catch(() => {
        if (cancelled) return
        setHealth({ ready: false, offline: true })
        timer = setTimeout(check, 2000)
      })
    }
    check()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [dataVersion])

  // Tras una actualización exitosa: recargar facetas y repetir las consultas de las vistas
  const onDataUpdated = () => setDataVersion((v) => v + 1)
  const ready = !!health?.ready

  if (health && !ready) return <NotReady health={health} onUpdated={onDataUpdated} />

  // Los "nit" de la ruta se guardan por vista para que cada una conserve su estado al cambiar de menú
  const supplierNit = route.view === 'proveedor' ? route.arg : null
  if (route.view === 'proveedor') lastNit.current = route.arg

  return (
    <div className="shell">
      <nav className={`nav ${navOpen ? 'open' : ''}`} aria-label="Funcionalidades">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32"><circle cx="14" cy="14" r="7" /><path d="M19 19l6 6" /></svg>
          </span>
          <div>
            <strong>Guatecompras</strong>
            <span>Datos abiertos OCDS</span>
          </div>
          <button className="nav-burger" onClick={() => setNavOpen(!navOpen)} aria-label="Menú">
            <svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
          </button>
        </div>

        <ul className="nav-items">
          {VIEWS.map((v) => (
            <li key={v.id}>
              <button className={route.view === v.id ? 'on' : ''} onClick={() => go(v.id, v.id === 'proveedor' ? lastNit.current : null)}
                title={v.hint} aria-current={route.view === v.id ? 'page' : undefined}>
                <span className="nav-ic" aria-hidden>{v.icon}</span>{v.label}
              </button>
            </li>
          ))}
        </ul>

        <div className="nav-foot">
          {facets && (
            <div className="dataset">
              <div><strong>{facets.total.toLocaleString('es-GT')}</strong> concursos</div>
              <div>{facets.date_min} a {facets.date_max}</div>
              {facets.meta?.built_at && <div title={facets.meta?.model}>Actualizado {fmtDateTime(facets.meta.built_at)}</div>}
            </div>
          )}
          {health?.features?.update && <UpdateButton meta={facets?.meta} onUpdated={onDataUpdated} placement="side" />}
          {health?.warning && <div className="alert small">{health.warning}</div>}
        </div>
      </nav>

      <div className="content">
        {error && <div className="hero"><div className="alert">{error}</div></div>}
        <div hidden={route.view !== 'buscar'}>
          <SearchView ready={ready} facets={facets} dataVersion={dataVersion} />
        </div>
        <div hidden={route.view !== 'proveedor'}>
          <SupplierView ready={ready} facets={facets} dataVersion={dataVersion}
            nit={supplierNit ?? (route.view === 'proveedor' ? null : lastNit.current)}
            setNit={(n) => { lastNit.current = n; go('proveedor', n) }} />
        </div>
      </div>
    </div>
  )
}

// Último proveedor consultado, para volver a él al cambiar de menú
const lastNit = { current: null }

function NotReady({ health, onUpdated }) {
  const { offline, syncing, features } = health
  return (
    <div className="notready">
      <h1>{offline ? 'Conectando con el servidor…' : syncing ? 'Descargando el índice publicado…' : 'Todavía no hay datos'}</h1>
      {offline ? (
        <p>Esperando a la API{API_BASE ? <> en <code>{API_BASE}</code></> : ''}. Si acaba de arrancar puede tardar unos
          segundos (o más si el servicio estaba dormido); la página se actualiza sola.</p>
      ) : syncing ? (
        <p>El servidor está descargando la versión más reciente del índice. La página se actualiza sola.</p>
      ) : features?.update ? (
        <>
          <p>Descarga los datos abiertos de Guatecompras (últimos 18 meses) y construye el índice de búsqueda.
            La primera vez puede tardar 20–40 minutos.</p>
          <UpdateButton big onUpdated={onUpdated} />
        </>
      ) : (
        <p>El servidor todavía no tiene un índice. Corre el pipeline de datos para publicarlo (ver DEPLOY.md).</p>
      )}
    </div>
  )
}
