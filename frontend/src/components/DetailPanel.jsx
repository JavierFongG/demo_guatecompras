import { useEffect, useState } from 'react'
import { api, fmtDate, fmtDateTime, money } from '../api.js'
import { StatusBadge, titleCase } from './ResultCard.jsx'

export default function DetailPanel({ nog, onClose, onOpen, onExclude }) {
  const [d, setD] = useState(null)
  const [refs, setRefs] = useState(null)   // null = cargando
  const [err, setErr] = useState(null)

  useEffect(() => {
    setD(null); setRefs(null); setErr(null)
    api.concurso(nog).then(setD).catch((e) => setErr(e.message))
    api.referencias(nog, 5).then(setRefs).catch(() => setRefs({ results: [], stats: null, error: true }))
  }, [nog])

  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const det = d?.detail || {}
  return (
    <div className="overlay" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`Concurso ${nog}`}>
        <button className="x" onClick={onClose} aria-label="Cerrar">×</button>
        {err && <div className="alert">{err}</div>}
        {!d && !err && <div className="loading">Cargando…</div>}
        {d && (
          <>
            <div className="card-top">
              <StatusBadge status={d.status_detail} end={d.tender_end} />
              {d.category && <span className="tag">{d.category}</span>}
              <span className="nog mono">NOG {d.nog}</span>
            </div>
            <h2 className="dtitle">{d.title}</h2>
            <div className="dactions">
              <a className="btn primary ext" href={d.url} target="_blank" rel="noreferrer">Ver en Guatecompras ↗</a>
              {onExclude && (
                <>
                  <button className="btn danger" title={`Oculta todos los concursos de ${d.buyer_name}`}
                    onClick={() => onExclude({ entity: d.buyer_name })}>Excluir entidad</button>
                  {d.unit_name && d.unit_name !== d.buyer_name && (
                    <button className="btn danger" title={`Oculta solo los concursos de ${d.unit_name}`}
                      onClick={() => onExclude({ entity: d.buyer_name, unit: d.unit_name })}>Excluir unidad</button>
                  )}
                </>
              )}
            </div>

            <dl className="grid">
              <Info k="Entidad" v={d.buyer_name} />
              <Info k="Unidad compradora" v={d.unit_name} />
              <Info k="Tipo de entidad" v={d.entity_type} />
              <Info k="Ubicación" v={[d.municipio, d.departamento].filter(Boolean).map(titleCase).join(', ')} />
              <Info k="Modalidad" v={d.method_detail} />
              <Info k="Publicado" v={fmtDateTime(d.date_published)} />
              <Info k="Cierre de ofertas" v={fmtDateTime(d.tender_end)} />
              <Info k="Oferentes" v={d.n_tenderers} />
              <Info k="Monto adjudicado" v={d.awarded_amount != null ? money(d.awarded_amount) : null} />
            </dl>

            {det.items?.length > 0 && (
              <Section title={`Ítems (${d.n_items})`}>
                <table className="tbl">
                  <thead><tr><th>Descripción</th><th className="r">Cantidad</th><th>Unidad</th><th>UNSPSC</th></tr></thead>
                  <tbody>
                    {det.items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.description}</td>
                        <td className="r">{it.quantity?.toLocaleString('es-GT') ?? '—'}</td>
                        <td>{it.unit || '—'}</td>
                        <td className="mono">{it.unspsc || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {det.awards?.length > 0 && (
              <Section title="Adjudicaciones">
                {det.awards.map((a) => (
                  <div className="award" key={a.id}>
                    <div><strong>{a.suppliers.map((s) => s.name).join(', ') || '—'}</strong>
                      <span className="muted"> · {a.suppliers.map((s) => s.id).join(', ')}</span></div>
                    <div className="award-row">
                      <span>{money(a.amount)}</span><span className="muted">{a.statusDetails}</span>
                      <span className="muted">{fmtDate(a.date)}</span>
                    </div>
                  </div>
                ))}
              </Section>
            )}

            {det.bids?.length > 0 && (
              <Section title={`Ofertas (${det.bids.length})`}>
                <table className="tbl">
                  <thead><tr><th>Oferente</th><th className="r">Monto</th><th>Fecha</th></tr></thead>
                  <tbody>
                    {det.bids.map((b, i) => (
                      <tr key={i}><td>{b.tenderers.join(', ')}</td><td className="r">{money(b.amount)}</td><td>{fmtDate(b.date)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {det.documents?.length > 0 && (
              <Section title="Documentos">
                <ul className="docs">
                  {det.documents.map((doc, i) => (
                    <li key={i}><a href={doc.url} target="_blank" rel="noreferrer">{doc.title || doc.type || 'Documento'}</a>
                      <span className="muted"> · {fmtDate(doc.date)}</span></li>
                  ))}
                </ul>
              </Section>
            )}

            <PriceReferences refs={refs} current={d} onOpen={onOpen} />
          </>
        )}
      </aside>
    </div>
  )
}

const Info = ({ k, v }) => (v || v === 0 ? <div><dt>{k}</dt><dd>{v}</dd></div> : null)
const Section = ({ title, children }) => (<section className="dsec"><h3>{title}</h3>{children}</section>)

// Referencia de precios: los concursos pasados y adjudicados más parecidos por descripción y entidad
function PriceReferences({ refs, current, onOpen }) {
  const title = 'Referencia de precios · adjudicaciones similares anteriores'
  if (!refs) return <Section title={title}><div className="muted">Buscando adjudicaciones similares…</div></Section>
  if (!refs.results.length) {
    return (
      <Section title={title}>
        <div className="muted">{refs.error ? 'No se pudo cargar la referencia de precios.'
          : 'No hay concursos adjudicados anteriores a este con los que comparar.'}</div>
      </Section>
    )
  }
  const st = refs.stats
  const cur = current?.awarded_amount
  return (
    <Section title={title}>
      {st && (
        <div className="refstats">
          <div><span>Mínimo</span><strong>{money(st.min)}</strong></div>
          <div><span>Mediana</span><strong>{money(st.median)}</strong></div>
          <div><span>Máximo</span><strong>{money(st.max)}</strong></div>
          {cur != null && cur > 0 && (
            <div title="Monto adjudicado de este concurso frente a la mediana de las referencias">
              <span>Este concurso</span>
              <strong>{money(cur)}</strong>
              <em className={cur > st.median ? 'up' : 'down'}>
                {cur >= st.median ? '+' : ''}{(((cur - st.median) / st.median) * 100).toFixed(0)}% vs. mediana
              </em>
            </div>
          )}
        </div>
      )}
      <ul className="refs">
        {refs.results.map((r) => (
          <li key={r.nog} onClick={() => onOpen(r.nog)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onOpen(r.nog)}>
            <div className="ref-head">
              <span className="pct" title="Similitud de la descripción">{(r.similarity * 100).toFixed(0)}%</span>
              <span className="t">{r.title}</span>
              <span className="ref-amt">{money(r.awarded_amount)}</span>
            </div>
            <div className="ref-meta">
              {r.same_unit ? <span className="badge green">Misma unidad</span>
                : r.same_entity ? <span className="badge blue">Misma entidad</span> : null}
              <span>{r.buyer_name}{r.unit_name && r.unit_name !== r.buyer_name ? ` › ${r.unit_name}` : ''}</span>
              <span className="muted">· NOG {r.nog} · {fmtDate(r.award_date || r.date_published)}</span>
            </div>
            <div className="ref-meta muted">
              {r.suppliers && <span>Adjudicado a {r.suppliers.split(' | ').join(', ')}</span>}
              {r.n_tenderers != null && <span>· {r.n_tenderers} oferente{r.n_tenderers === 1 ? '' : 's'}</span>}
              {r.method_detail && <span>· {r.method_detail}</span>}
            </div>
            {r.unit_price != null && (
              <div className="ref-meta">
                <span>≈ {money(r.unit_price)} por {(r.unit_label || 'unidad').toLowerCase()}</span>
                <span className="muted">({r.items[0].quantity.toLocaleString('es-GT')} {r.unit_label || ''})</span>
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="muted small">
        Concursos publicados antes que este y con monto adjudicado, ordenados por similitud de la descripción
        con preferencia a la misma entidad. Los montos son el total adjudicado de cada concurso (Q).
      </p>
    </Section>
  )
}
