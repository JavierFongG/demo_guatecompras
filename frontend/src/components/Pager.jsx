export default function Pager({ data, page, setPage }) {
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0
  if (totalPages <= 1) return null
  const go = (p) => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  return (
    <nav className="pager">
      <button className="btn" disabled={page <= 1} onClick={() => go(page - 1)}>← Anterior</button>
      <span>Página {page} de {totalPages}</span>
      <button className="btn" disabled={page >= totalPages} onClick={() => go(page + 1)}>Siguiente →</button>
    </nav>
  )
}
