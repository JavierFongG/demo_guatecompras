import { fmtDate, money } from '../api.js'

export function StatusBadge({ status, end }) {
  // Los vigentes casi nunca traen fecha de cierre en los datos; si la traen, debe ser futura
  const open = status === 'Vigente' && (!end || new Date(end) > new Date())
  const tone = open ? 'green' : /adjudicad|finaliz|terminado/i.test(status || '') ? 'blue'
    : /desiert|anulad|cancel|prescind/i.test(status || '') ? 'red' : 'gray'
  return <span className={`badge ${tone}`}>{status || 'Sin estado'}</span>
}

export default function ResultCard({ r, onOpen, active, showScore, onOpenRef }) {
  const sim = r.similarity
  return (
    <article className={`card ${active ? 'active' : ''}`} onClick={onOpen} tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <div className="card-top">
        <StatusBadge status={r.status_detail} end={r.tender_end} />
        {r.category && <span className="tag">{r.category}</span>}
        <span className="nog mono">NOG {r.nog}</span>
        {showScore && sim != null && (
          <span className="sim" title={`Similitud coseno: ${sim}`}>
            <span className="bar"><span style={{ width: `${Math.max(4, Math.min(100, ((sim - 0.7) / 0.25) * 100))}%` }} /></span>
            {(sim * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <h3>{r.title}</h3>
      <div className="card-meta">
        <span className="buyer">{r.buyer_name}</span>
        {r.unit_name && r.unit_name !== r.buyer_name && <span className="unit">› {r.unit_name}</span>}
        {r.departamento && <span>· {titleCase(r.departamento)}</span>}
      </div>
      <div className="card-foot">
        <span>Publicado {fmtDate(r.date_published)}</span>
        {r.tender_end && <span>Cierre {fmtDate(r.tender_end)}</span>}
        {r.method_detail && <span className="muted ellipsis" title={r.method_detail}>{r.method_detail}</span>}
        {r.awarded_amount != null && (
          <span className="amount">{money(r.awarded_amount)}</span>
        )}
      </div>
      {r.suppliers && <div className="suppliers">Adjudicado a: {r.suppliers}</div>}
      {r.because && (
        <div className="because" onClick={(e) => { if (onOpenRef) { e.stopPropagation(); onOpenRef(r.because.nog) } }}
          title="Ver la adjudicación anterior">
          <span className="because-k">Parecido a lo que ganó:</span>
          <span className="because-t">{r.because.title}</span>
          <span className="muted"> · {r.because.buyer_name} · {fmtDate(r.because.date_published)}</span>
        </div>
      )}
    </article>
  )
}

export const titleCase = (s) => (s || '').toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase())
