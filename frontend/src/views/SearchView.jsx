import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import Filters, { EMPTY_FILTERS, addBuyerExclusion, countActive, filtersToBody } from '../components/Filters.jsx'
import ResultCard from '../components/ResultCard.jsx'
import DetailPanel from '../components/DetailPanel.jsx'
import Pager from '../components/Pager.jsx'

const EXAMPLES = [
  'medicamentos e insumos para hospitales',
  'construcción y mejoramiento de carreteras rurales',
  'alimentación escolar para escuelas',
  'equipo de cómputo y licencias de software',
  'servicio de seguridad y vigilancia',
  'compra de fertilizantes para agricultores',
]

const MODES = [
  { id: 'hybrid', label: 'Híbrida', hint: 'Combina significado y palabras exactas' },
  { id: 'semantic', label: 'Semántica', hint: 'Solo por significado (embeddings)' },
  { id: 'keyword', label: 'Palabras clave', hint: 'Coincidencia de texto tradicional' },
]

export const SORTS = [
  { id: 'relevance', label: 'Relevancia' },
  { id: 'date_desc', label: 'Más recientes' },
  { id: 'date_asc', label: 'Más antiguos' },
  { id: 'amount_desc', label: 'Mayor monto' },
  { id: 'amount_asc', label: 'Menor monto' },
]

export default function SearchView({ ready, facets, dataVersion }) {
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [sort, setSort] = useState('relevance')
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [showFilters, setShowFilters] = useState(false)
  const reqId = useRef(0)

  const run = useCallback(async () => {
    if (!ready) return
    const id = ++reqId.current
    setLoading(true)
    setError(null)
    try {
      const body = {
        ...filtersToBody(filters), q: submitted || null, mode, page, page_size: 20,
        sort: !submitted && sort === 'relevance' ? 'date_desc' : sort,
      }
      const res = await api.search(body)
      if (id === reqId.current) setData(res)
    } catch (e) {
      if (id === reqId.current) setError(e.message)
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }, [ready, filters, submitted, mode, sort, page, dataVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { run() }, [run])

  const submit = (q) => {
    const v = (q ?? query).trim()
    setQuery(v)
    setSubmitted(v)
    setPage(1)
    if (v && sort !== 'relevance') setSort('relevance')
  }
  const updateFilters = (f) => { setFilters(f); setPage(1) }
  const activeCount = countActive(filters)

  return (
    <>
      <header className="view-head">
        <h1>Buscador de concursos</h1>
        <p>Describe en tus palabras lo que buscas; la búsqueda entiende el significado, no solo las palabras exactas.</p>
      </header>

      <section className="hero">
        <form className="searchbox" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <svg className="icon" viewBox="0 0 24 24" aria-hidden><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Describe lo que buscas, p. ej. «compra de vacunas para centros de salud en Huehuetenango»"
            aria-label="Búsqueda en lenguaje natural"
          />
          {query && (
            <button type="button" className="clear" onClick={() => { setQuery(''); submit('') }} aria-label="Limpiar">×</button>
          )}
          <button type="submit" className="primary">Buscar</button>
        </form>
        <div className="hero-row">
          <div className="segmented" role="tablist" aria-label="Tipo de búsqueda">
            {MODES.map((m) => (
              <button key={m.id} title={m.hint} className={mode === m.id ? 'on' : ''}
                onClick={() => { setMode(m.id); setPage(1) }}>{m.label}</button>
            ))}
          </div>
          <div className="examples">
            <span>Prueba:</span>
            {EXAMPLES.map((ex) => (
              <button key={ex} className="chip ghost" onClick={() => submit(ex)}>{ex}</button>
            ))}
          </div>
        </div>
      </section>

      <main className="layout">
        <aside className={`sidebar ${showFilters ? 'open' : ''}`}>
          <Filters facets={facets} value={filters} onChange={updateFilters} onClose={() => setShowFilters(false)} />
        </aside>

        <section className="results">
          <div className="results-head">
            <button className="btn filters-toggle" onClick={() => setShowFilters(true)}>
              Filtros{activeCount ? ` (${activeCount})` : ''}
            </button>
            <div className="count">
              {loading ? 'Buscando…' : data ? (
                <>
                  {data.capped ? 'Los ' : ''}
                  <strong>{data.total.toLocaleString('es-GT')}</strong>
                  {' '}{data.total === 1 ? 'concurso' : 'concursos'}{data.capped ? ' más relevantes' : ''}
                  {submitted && <> para <em>«{submitted}»</em></>}
                </>
              ) : null}
            </div>
            <label className="sort">
              Ordenar
              <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1) }}>
                {SORTS.filter((s) => submitted || s.id !== 'relevance').map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </label>
          </div>

          {error && <div className="alert">{error}</div>}

          <div className={`list ${loading ? 'dim' : ''}`}>
            {data?.results.map((r) => (
              <ResultCard key={r.nog} r={r} active={selected === r.nog} onOpen={() => setSelected(r.nog)} showScore={!!submitted} />
            ))}
            {data && !data.results.length && !loading && (
              <div className="empty">
                <p>No hay concursos que coincidan.</p>
                <p className="muted">Prueba otra descripción o quita algunos filtros.</p>
              </div>
            )}
          </div>

          <Pager data={data} page={page} setPage={setPage} />
        </section>
      </main>

      {selected && (
        <DetailPanel nog={selected} onClose={() => setSelected(null)} onOpen={setSelected}
          onExclude={(ref) => { updateFilters(addBuyerExclusion(filters, ref)); setSelected(null) }} />
      )}
    </>
  )
}
