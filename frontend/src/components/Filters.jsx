import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Filtros de lista con dos modos:
//   include → se envía `key` con los valores marcados (solo esos)
//   exclude → todo marcado; se envía `key_not` con los valores desmarcados
export const LIST_KEYS = ['status', 'category', 'method', 'departamento', 'entity_type']

export const EMPTY_FILTERS = {
  date_from: '', date_to: '',
  status: [], category: [], method: [], departamento: [], entity_type: [],
  status_not: [], category_not: [], method_not: [], departamento_not: [], entity_type_not: [],
  buyers: [], buyers_not: [],      // entidades completas (nombres)
  units: [], units_not: [],        // unidades compradoras: { entity, unit }
  modes: { status: 'include', category: 'include', method: 'include', departamento: 'include', entity_type: 'include', buyers: 'include' },
  supplier: '',
  amount_min: '', amount_max: '',
  only_awarded: false, open_only: false,
}

// Convierte el estado de filtros de la UI al cuerpo que espera la API
export function filtersToBody(f) {
  const { modes: _modes, ...rest } = f
  return {
    ...rest,
    amount_min: f.amount_min === '' ? null : Number(f.amount_min),
    amount_max: f.amount_max === '' ? null : Number(f.amount_max),
    date_from: f.date_from || null, date_to: f.date_to || null,
    supplier: f.supplier || null,
  }
}

export function countActive(f, base = EMPTY_FILTERS) {
  let n = 0
  for (const [k, v] of Object.entries(f)) {
    if (k === 'modes') continue
    const b = base[k]
    if (Array.isArray(v) ? v.length : typeof v === 'boolean' ? v !== b : v !== '' && v != null) n++
  }
  return n
}

export default function Filters({ facets, value, onChange, onClose, empty = EMPTY_FILTERS, hide = [] }) {
  const set = (k, v) => onChange({ ...value, [k]: v })
  const listProps = (key) => ({
    items: facets?.[key],
    mode: value.modes[key],
    included: value[key],
    excluded: value[`${key}_not`],
    onMode: (m) => onChange({ ...value, modes: { ...value.modes, [key]: m }, [key]: [], [`${key}_not`]: [] }),
    onChange: (inc, exc) => onChange({ ...value, [key]: inc, [`${key}_not`]: exc }),
  })

  return (
    <div className="filters">
      <div className="filters-head">
        <h2>Filtros</h2>
        <button className="link" onClick={() => onChange(empty)}>Limpiar todo</button>
        <button className="link close-mobile" onClick={onClose}>Cerrar</button>
      </div>

      <Group title="Disponibilidad">
        <Toggle label="Solo con recepción de ofertas abierta" checked={value.open_only} onChange={(v) => set('open_only', v)} />
        {!hide.includes('only_awarded') && (
          <Toggle label="Solo adjudicados" checked={value.only_awarded} onChange={(v) => set('only_awarded', v)} />
        )}
      </Group>

      <Group title="Fecha de publicación">
        <div className="row2">
          <label>Desde<input type="date" value={value.date_from} min={facets?.date_min} max={facets?.date_max}
            onChange={(e) => set('date_from', e.target.value)} /></label>
          <label>Hasta<input type="date" value={value.date_to} min={facets?.date_min} max={facets?.date_max}
            onChange={(e) => set('date_to', e.target.value)} /></label>
        </div>
        <div className="quick">
          {[[7, '7 días'], [30, '30 días'], [90, '3 meses'], [180, '6 meses'], [365, '1 año']].map(([d, label]) => (
            <button key={d} className="chip ghost" onClick={() => onChange({ ...value, date_from: daysAgo(d, facets?.date_max), date_to: '' })}>
              {label}
            </button>
          ))}
        </div>
      </Group>

      <MultiFilter title="Categoría" variant="chips" {...listProps('category')} />
      <MultiFilter title="Estado del concurso" {...listProps('status')} />

      <BuyerFilter value={value} onChange={onChange} />

      <MultiFilter title="Departamento" limit={8} {...listProps('departamento')} />
      <MultiFilter title="Tipo de entidad" limit={6} {...listProps('entity_type')} />
      <MultiFilter title="Modalidad de compra" limit={6} {...listProps('method')} />

      {!hide.includes('supplier') && <Group title="Proveedor adjudicado">
        <DebouncedInput placeholder="Nombre o NIT" value={value.supplier} onChange={(v) => set('supplier', v)} />
      </Group>}

      {!hide.includes('amount') && <Group title="Monto adjudicado (Q)">
        <div className="row2">
          <DebouncedInput type="number" min="0" placeholder="Mínimo" value={value.amount_min} onChange={(v) => set('amount_min', v)} />
          <DebouncedInput type="number" min="0" placeholder="Máximo" value={value.amount_max} onChange={(v) => set('amount_max', v)} />
        </div>
      </Group>}
    </div>
  )
}

function daysAgo(n, ref) {
  const d = ref ? new Date(ref + 'T12:00:00') : new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function Group({ title, children }) {
  return (
    <fieldset className="group">
      <legend>{title}</legend>
      {children}
    </fieldset>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track"><span className="thumb" /></span>
      {label}
    </label>
  )
}

function MultiFilter({ title, items, mode, included, excluded, onMode, onChange, limit = 10, variant = 'list' }) {
  const [all, setAll] = useState(false)
  const [filter, setFilter] = useState('')
  if (!items?.length) return null

  const exclude = mode === 'exclude'
  const isChecked = (v) => (exclude ? !excluded.includes(v) : included.includes(v))
  const toggle = (v) => {
    if (exclude) onChange([], excluded.includes(v) ? excluded.filter((x) => x !== v) : [...excluded, v])
    else onChange(included.includes(v) ? included.filter((x) => x !== v) : [...included, v], [])
  }
  // Seleccionar / quitar todos los valores visibles (respeta el buscador interno)
  const filtered = items.filter((i) => i.value.toLowerCase().includes(filter.toLowerCase()))
  const visibleVals = filtered.map((i) => i.value)
  const selectAll = () => exclude
    ? onChange([], excluded.filter((x) => !visibleVals.includes(x)))
    : onChange([...new Set([...included, ...visibleVals])], [])
  const selectNone = () => exclude
    ? onChange([], [...new Set([...excluded, ...visibleVals])])
    : onChange(included.filter((x) => !visibleVals.includes(x)), [])

  const marked = exclude ? excluded : included
  const shown = all || filter || variant === 'chips' ? filtered
    : [...items.filter((i) => marked.includes(i.value)), ...items.filter((i) => !marked.includes(i.value))]
      .slice(0, Math.max(limit, marked.length))

  const summary = exclude
    ? (excluded.length ? `Excluyendo ${excluded.length}` : 'Todos incluidos')
    : (included.length ? `${included.length} seleccionado${included.length > 1 ? 's' : ''}` : 'Sin filtro')

  return (
    <fieldset className="group">
      <legend>{title}</legend>
      <div className="mf-head">
        <div className="seg-mini" role="radiogroup" aria-label={`Modo de ${title}`}>
          <button className={!exclude ? 'on' : ''} onClick={() => !exclude || onMode('include')}
            title="Marca solo lo que quieres ver">Incluir</button>
          <button className={exclude ? 'on' : ''} onClick={() => exclude || onMode('exclude')}
            title="Todo seleccionado; desmarca lo que quieres excluir">Excluir</button>
        </div>
        <span className={`mf-sum ${exclude && excluded.length ? 'neg' : ''}`}>{summary}</span>
      </div>

      {items.length > limit && variant !== 'chips' && (
        <input className="mini" placeholder="Filtrar…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      )}

      {variant === 'chips' ? (
        <div className="chips">
          {shown.map((c) => (
            <button key={c.value} onClick={() => toggle(c.value)}
              className={`chip ${isChecked(c.value) ? 'on' : ''} ${exclude && !isChecked(c.value) ? 'off' : ''}`}>
              {c.value} <span className="n">{c.count.toLocaleString('es-GT')}</span>
            </button>
          ))}
        </div>
      ) : (
        <ul className="checks">
          {shown.map((i) => (
            <li key={i.value} className={exclude && !isChecked(i.value) ? 'excluded' : ''}>
              <label>
                <input type="checkbox" checked={isChecked(i.value)} onChange={() => toggle(i.value)} />
                <span className="lbl" title={i.value}>{i.value}</span>
                <span className="n">{i.count.toLocaleString('es-GT')}</span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <div className="mf-actions">
        <button className="link" onClick={selectAll}>Seleccionar todo</button>
        <button className="link" onClick={selectNone}>Ninguno</button>
        {items.length > limit && !filter && variant !== 'chips' && (
          <button className="link right" onClick={() => setAll(!all)}>{all ? 'Ver menos' : `Ver los ${items.length}`}</button>
        )}
      </div>
    </fieldset>
  )
}

function DebouncedInput({ value, onChange, delay = 450, ...rest }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  useEffect(() => {
    if (v === value) return
    const t = setTimeout(() => onChange(v), delay)
    return () => clearTimeout(t)
  }, [v]) // eslint-disable-line react-hooks/exhaustive-deps
  return <input {...rest} value={v} onChange={(e) => setV(e.target.value)} />
}

// Entidad / unidad compradora. Hay cientos, así que se eligen con autocompletado y quedan como etiquetas.
//   Entidad  → abarca todas sus unidades (p. ej. IGSS = 91 hospitales y oficinas)
//   Unidad   → solo esa unidad dentro de su entidad (p. ej. IGSS › Hospital General de Enfermedades)
//   Incluir → solo lo elegido · Excluir → todo menos lo elegido
const unitKey = (u) => `${u.entity}\u0000${u.unit}`

export function addBuyerExclusion(f, { entity, unit }) {
  // Pasa a modo excluir (si estaba en incluir, limpia lo incluido) y agrega la entidad o unidad
  const base = f.modes.buyers === 'exclude' ? f
    : { ...f, buyers: [], units: [], modes: { ...f.modes, buyers: 'exclude' } }
  if (unit) {
    if (base.units_not.some((u) => unitKey(u) === unitKey({ entity, unit }))) return base
    return { ...base, units_not: [...base.units_not, { entity, unit }] }
  }
  if (base.buyers_not.includes(entity)) return base
  // Excluir la entidad completa hace redundantes sus unidades excluidas
  return { ...base, buyers_not: [...base.buyers_not, entity], units_not: base.units_not.filter((u) => u.entity !== entity) }
}

function BuyerFilter({ value, onChange }) {
  const exclude = value.modes.buyers === 'exclude'
  const ents = exclude ? value.buyers_not : value.buyers
  const units = exclude ? value.units_not : value.units
  const [text, setText] = useState('')
  const [opts, setOpts] = useState({ entities: [], units: [] })
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)

  useEffect(() => {
    if (text.trim().length < 2) { setOpts({ entities: [], units: [] }); return }
    const t = setTimeout(() => api.buyers(text).then((o) => { setOpts(o); setHi(0) }).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [text])

  const commit = (e, u) => onChange(exclude
    ? { ...value, buyers: [], units: [], buyers_not: e, units_not: u }
    : { ...value, buyers: e, units: u, buyers_not: [], units_not: [] })
  const setMode = (m) => onChange({ ...value, modes: { ...value.modes, buyers: m }, buyers: [], buyers_not: [], units: [], units_not: [] })

  // Opciones navegables: primero entidades, luego unidades (omitiendo lo ya elegido o cubierto)
  const options = [
    ...opts.entities.filter((o) => !ents.includes(o.value)).map((o) => ({ type: 'entity', entity: o.value, count: o.count, units: o.units })),
    ...opts.units.filter((o) => !ents.includes(o.entity) && !units.some((u) => unitKey(u) === unitKey(o)))
      .map((o) => ({ type: 'unit', entity: o.entity, unit: o.unit, count: o.count })),
  ]
  const add = (o) => {
    if (o.type === 'entity') commit([...ents, o.entity], units.filter((u) => u.entity !== o.entity))
    else commit(ents, [...units, { entity: o.entity, unit: o.unit }])
    setText(''); setOpts({ entities: [], units: [] }); setOpen(false)
  }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (options[hi]) add(options[hi]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  const n = ents.length + units.length
  const summary = exclude ? (n ? `Excluyendo ${n}` : 'Todas incluidas') : (n ? `${n} seleccionada${n > 1 ? 's' : ''}` : 'Sin filtro')
  const firstUnit = options.findIndex((o) => o.type === 'unit')
  const sign = exclude ? '✕' : '+'

  return (
    <fieldset className="group">
      <legend>Entidad / unidad compradora</legend>
      <div className="mf-head">
        <div className="seg-mini" role="radiogroup" aria-label="Modo de entidad compradora">
          <button className={!exclude ? 'on' : ''} onClick={() => !exclude || setMode('include')}
            title="Solo las entidades o unidades que elijas">Incluir</button>
          <button className={exclude ? 'on' : ''} onClick={() => exclude || setMode('exclude')}
            title="Todas excepto las entidades o unidades que elijas">Excluir</button>
        </div>
        <span className={`mf-sum ${exclude && n ? 'neg' : ''}`}>{summary}</span>
      </div>

      <div className="autocomplete">
        <input
          placeholder={exclude ? 'Entidad o unidad a excluir…' : 'Entidad o unidad, p. ej. IGSS, Roosevelt…'}
          value={text}
          onChange={(e) => { setText(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          onBlur={() => setTimeout(() => setOpen(false), 150)} />
        {open && options.length > 0 && (
          <ul className="menu">
            {options.map((o, i) => (
              <li key={o.type + unitKey(o)} className={`opt ${i === hi ? 'hi' : ''}`}
                onMouseEnter={() => setHi(i)} onMouseDown={() => add(o)}>
                {i === 0 && o.type === 'entity' && <div className="menu-h">Entidad completa (todas sus unidades)</div>}
                {i === firstUnit && <div className="menu-h">Unidad compradora</div>}
                <div className="opt-row">
                  <span className="opt-main">
                    <span className="sgn">{sign}</span>{o.type === 'entity' ? o.entity : o.unit}
                    <span className="opt-sub">
                      {o.type === 'entity' ? `${o.units} unidad${o.units === 1 ? '' : 'es'}` : o.entity}
                    </span>
                  </span>
                  <span className="n">{o.count.toLocaleString('es-GT')}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
        {open && text.trim().length >= 2 && !options.length && (
          <ul className="menu"><li className="muted">Sin coincidencias</li></ul>
        )}
      </div>

      {n > 0 && (
        <>
          <div className="tags">
            {ents.map((e) => (
              <span key={'e' + e} className={`tagx ${exclude ? 'neg' : ''}`} title={`Entidad completa: ${e}`}>
                <span className="kind">Entidad</span><span className="t">{e}</span>
                <button onClick={() => commit(ents.filter((x) => x !== e), units)} aria-label={`Quitar ${e}`}>×</button>
              </span>
            ))}
            {units.map((u) => (
              <span key={'u' + unitKey(u)} className={`tagx ${exclude ? 'neg' : ''}`} title={`${u.unit} — ${u.entity}`}>
                <span className="kind">Unidad</span><span className="t">{u.unit}</span>
                <button onClick={() => commit(ents, units.filter((x) => unitKey(x) !== unitKey(u)))} aria-label={`Quitar ${u.unit}`}>×</button>
              </span>
            ))}
          </div>
          <div className="mf-actions">
            <button className="link" onClick={() => commit([], [])}>{exclude ? 'Incluir todas de nuevo' : 'Quitar todas'}</button>
          </div>
        </>
      )}
    </fieldset>
  )
}
