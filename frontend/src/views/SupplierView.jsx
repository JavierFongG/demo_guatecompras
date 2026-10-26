import { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtDate, money } from '../api.js'
import Filters, { EMPTY_FILTERS, addBuyerExclusion, countActive, filtersToBody } from '../components/Filters.jsx'
import ResultCard from '../components/ResultCard.jsx'
import DetailPanel from '../components/DetailPanel.jsx'
import Pager from '../components/Pager.jsx'

// Por defecto: solo oportunidades que todavía reciben ofertas
const SUPPLIER_FILTERS = { ...EMPTY_FILTERS, open_only: true }
const SORTS = [
  { id: 'relevance', label: 'Más relevantes' },
  { id: 'date_desc', label: 'Más recientes' },
  { id: 'date_asc', label: 'Más antiguos' },
]

export default function SupplierView({ ready, facets, dataVersion, nit, setNit }) {
  const [profile, setProfile] = useState(null)
  const [profileErr, setProfileErr] = useState(null)
  const [filters, setFilters] = useState(SUPPLIER_FILTERS)
  const [refine, setRefine] = useState('')
  const [refineSubmitted, setRefineSubmitted] = useState('')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [sort, setSort] = useState('relevance')
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [showFilters, setShowFilters] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const reqId = useRef(0)

  // Perfil del proveedor
  useEffect(() => {
    setProfile(null); setProfileErr(null); setData(null); setPage(1); setShowHistory(false)
    if (!ready || !nit) return
    api.supplier(nit).then(setProfile).catch((e) => setProfileErr(e.message))
  }, [ready, nit, dataVersion])

  // Recomendaciones
  const run = useCallback(async () => {
    if (!ready || !nit) return
    const id = ++reqId.current
    setLoading(true); setError(null)
    try {
      const res = await api.recommend({
        ...filtersToBody(filters), nit, q: refineSubmitted || null, include_history: includeHistory,
        sort, page, page_size: 20,
      })
      if (id === reqId.current) setData(res)
    } catch (e) {
      if (id === reqId.current) setError(e.message)
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }, [ready, nit, filters, refineSubmitted, includeHistory, sort, page, dataVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { run() }, [run])

  const updateFilters = (f) => { setFilters(f); setPage(1) }
  const activeCount = countActive(filters, SUPPLIER_FILTERS)

  return (
    <>
      <header className="view-head">
        <h1>Oportunidades para un proveedor</h1>
        <p>Escribe un NIT o nombre. Analizamos todo lo que se le ha adjudicado y te mostramos los concursos
          que más se parecen a su historial.</p>
      </header>

      <section className="hero">
        <SupplierPicker nit={nit} name={profile?.name} onPick={(n) => { setNit(n); setPage(1) }} />
      </section>

      {!nit && <SupplierEmpty />}
      {profileErr && <div className="hero"><div className="alert">{profileErr}</div></div>}

      {nit && profile && (
        <section className="hero">
          <div className="profile">
            <div className="profile-head">
              <div>
                <h2>{profile.name}</h2>
                <span className="mono muted">NIT {profile.nit}</span>
              </div>
              <button className="btn" onClick={() => setShowHistory(!showHistory)}>
                {showHistory ? 'Ocultar historial' : `Ver historial (${profile.awards.toLocaleString('es-GT')})`}
              </button>
            </div>
            <div className="stats">
              <Stat k="Concursos adjudicados" v={profile.awards.toLocaleString('es-GT')} />
              <Stat k="Monto adjudicado" v={money(profile.total_amount)} />
              <Stat k="Periodo" v={`${fmtDate(profile.first_date)} – ${fmtDate(profile.last_date)}`} />
              <Stat k="Líneas de negocio detectadas" v={data?.profiles ?? '—'}
                hint="Grupos de productos o servicios distintos encontrados en su historial; cada uno se usa para buscar oportunidades." />
            </div>
            <div className="chiprows">
              <ChipRow label="Principales compradores" items={profile.top_buyers} />
              <ChipRow label="Categorías" items={profile.top_categories} />
              <ChipRow label="Departamentos" items={profile.top_departamentos} />
            </div>
            {showHistory && (
              <div className="history">
                <table className="tbl">
                  <thead><tr><th>Concurso</th><th>Entidad</th><th>Publicado</th><th className="r">Monto adjudicado</th></tr></thead>
                  <tbody>
                    {profile.history.map((h) => (
                      <tr key={h.nog} className="clickable" onClick={() => setSelected(h.nog)}>
                        <td><span className="mono muted">{h.nog}</span> {h.title}</td>
                        <td>{h.buyer_name}{h.unit_name && h.unit_name !== h.buyer_name ? ` › ${h.unit_name}` : ''}</td>
                        <td>{fmtDate(h.date_published)}</td>
                        <td className="r">{money(h.supplier_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {profile.awards > profile.history.length && (
                  <p className="muted small">Mostrando los {profile.history.length} más recientes.</p>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {nit && (
        <main className="layout">
          <aside className={`sidebar ${showFilters ? 'open' : ''}`}>
            <Filters facets={facets} value={filters} onChange={updateFilters} onClose={() => setShowFilters(false)}
              empty={SUPPLIER_FILTERS} hide={['supplier', 'amount', 'only_awarded']} />
          </aside>

          <section className="results">
            <form className="refine" onSubmit={(e) => { e.preventDefault(); setRefineSubmitted(refine.trim()); setPage(1) }}>
              <input value={refine} onChange={(e) => setRefine(e.target.value)}
                placeholder="Afinar (opcional): p. ej. «solo reactivos de laboratorio»" aria-label="Afinar recomendaciones" />
              {refineSubmitted && (
                <button type="button" className="link" onClick={() => { setRefine(''); setRefineSubmitted(''); setPage(1) }}>Quitar</button>
              )}
              <button className="btn" type="submit">Afinar</button>
            </form>

            <div className="results-head">
              <button className="btn filters-toggle" onClick={() => setShowFilters(true)}>
                Filtros{activeCount ? ` (${activeCount})` : ''}
              </button>
              <div className="count">
                {loading ? 'Analizando historial…' : data ? (
                  <>
                    {data.capped ? 'Los ' : ''}<strong>{data.total.toLocaleString('es-GT')}</strong>
                    {' '}{data.capped ? 'concursos más relevantes' : data.total === 1 ? 'concurso relevante' : 'concursos relevantes'}
                    {filters.open_only && ' abiertos'}
                  </>
                ) : null}
              </div>
              <label className="toggle compact">
                <input type="checkbox" checked={includeHistory} onChange={(e) => { setIncludeHistory(e.target.checked); setPage(1) }} />
                <span className="track"><span className="thumb" /></span>
                Incluir los que ya ganó
              </label>
              <label className="sort">
                Ordenar
                <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }}>
                  {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
              </label>
            </div>

            {error && <div className="alert">{error}</div>}

            <div className={`list ${loading ? 'dim' : ''}`}>
              {data?.results.map((r) => (
                <ResultCard key={r.nog} r={r} active={selected === r.nog} onOpen={() => setSelected(r.nog)}
                  showScore onOpenRef={setSelected} />
              ))}
              {data && !data.results.length && !loading && (
                <div className="empty">
                  <p>No hay concursos que coincidan con este perfil y filtros.</p>
                  <p className="muted">
                    {filters.open_only ? 'Prueba desactivar «Solo con recepción de ofertas abierta» para ver concursos pasados similares.' : 'Prueba quitar algunos filtros.'}
                  </p>
                </div>
              )}
            </div>

            <Pager data={data} page={page} setPage={setPage} />
          </section>
        </main>
      )}

      {selected && (
        <DetailPanel nog={selected} onClose={() => setSelected(null)} onOpen={setSelected}
          onExclude={(ref) => { updateFilters(addBuyerExclusion(filters, ref)); setSelected(null) }} />
      )}
    </>
  )
}

function Stat({ k, v, hint }) {
  return <div className="stat" title={hint}><dt>{k}</dt><dd>{v}</dd></div>
}

function ChipRow({ label, items }) {
  if (!items?.length) return null
  return (
    <div className="chiprow">
      <span className="lbl">{label}</span>
      {items.map((i) => <span key={i.value} className="chip static">{i.value} <span className="n">{i.count.toLocaleString('es-GT')}</span></span>)}
    </div>
  )
}

function SupplierEmpty() {
  return (
    <div className="hero">
      <div className="howto">
        <div><strong>1. Elige un proveedor</strong><p>Por NIT (p. ej. 22345388) o por nombre (p. ej. «droguería»).</p></div>
        <div><strong>2. Analizamos su historial</strong><p>Todos los concursos que se le adjudicaron, agrupados en líneas de negocio.</p></div>
        <div><strong>3. Te mostramos oportunidades</strong><p>Concursos abiertos parecidos a lo que ya ganó, con la adjudicación que más se le parece.</p></div>
      </div>
    </div>
  )
}

function SupplierPicker({ nit, name, onPick }) {
  const [text, setText] = useState('')
  const [opts, setOpts] = useState([])
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    const q = text.trim()
    if (q.length < 3) { setOpts([]); setSearched(false); return }
    const t = setTimeout(() => api.suppliers(q).then((o) => { setOpts(o); setHi(0); setSearched(true) }).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [text])

  const pick = (o) => { onPick(o.nit); setText(''); setOpts([]); setOpen(false) }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, opts.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (opts[hi]) pick(opts[hi]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div className="autocomplete supplier-picker">
      <div className="searchbox">
        <svg className="icon" viewBox="0 0 24 24" aria-hidden><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6" /></svg>
        <input value={text} onChange={(e) => { setText(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onKey}
          placeholder={nit ? `Cambiar proveedor (actual: ${name || nit})` : 'NIT o nombre del proveedor, p. ej. 22345388 o «droguería»'}
          aria-label="NIT o nombre del proveedor" />
        {nit && <button type="button" className="clear" onClick={() => onPick(null)} aria-label="Quitar proveedor">×</button>}
      </div>
      {open && opts.length > 0 && (
        <ul className="menu">
          {opts.map((o, i) => (
            <li key={o.nit} className={`opt ${i === hi ? 'hi' : ''}`} onMouseEnter={() => setHi(i)} onMouseDown={() => pick(o)}>
              <div className="opt-row">
                <span className="opt-main">{o.name}<span className="opt-sub">NIT {o.nit}</span></span>
                <span className="n">{o.awards.toLocaleString('es-GT')} adjudicaciones</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {open && searched && !opts.length && (
        <ul className="menu"><li className="muted">Ningún proveedor con adjudicaciones coincide</li></ul>
      )}
    </div>
  )
}
