import { getAccessToken, signOut } from './auth.js'

// URL de la API. Vacía = mismo origen (API y frontend juntos, o proxy de Vite en desarrollo).
// Para publicar el frontend aparte: VITE_API_BASE=https://mi-api.example.com npm run build
export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

// Clave de administrador: solo para el modo "todo en uno" (botón Actualizar datos en un servidor
// propio). En producción (modo api) la administración usa el rol "admin" del login.
const TOKEN_KEY = 'gc_admin_token'
export const adminToken = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY) || '' } catch { return '' } },
  set: (v) => { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY) } catch { /* sin storage */ } },
}

async function req(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  const session = await getAccessToken()
  if (session) headers.Authorization = `Bearer ${session}`
  const tok = adminToken.get()
  if (tok && opts.admin) headers['X-Admin-Token'] = tok
  const r = await fetch(API_BASE + path, { ...opts, headers })
  if (r.status === 401 && session && !opts.admin) {
    // La sesión venció o fue revocada: volver a la pantalla de login
    await signOut()
  }
  if (!r.ok) {
    let msg = `Error ${r.status}`
    try { msg = (await r.json()).detail || msg } catch { /* sin cuerpo */ }
    const err = new Error(msg)
    err.status = r.status
    throw err
  }
  return r.json()
}

export const api = {
  health: () => req('/api/health'),
  me: () => req('/api/me'),
  facets: () => req('/api/facets'),
  search: (body) => req('/api/search', { method: 'POST', body: JSON.stringify(body) }),
  buyers: (q) => req(`/api/buyers?q=${encodeURIComponent(q)}`),
  concurso: (nog) => req(`/api/concursos/${nog}`),
  referencias: (nog, k = 5) => req(`/api/concursos/${nog}/referencias?k=${k}`),
  suppliers: (q) => req(`/api/suppliers?q=${encodeURIComponent(q)}`),
  supplier: (nit) => req(`/api/suppliers/${encodeURIComponent(nit)}`),
  recommend: (body) => req('/api/recommend', { method: 'POST', body: JSON.stringify(body) }),
  updateStart: () => req('/api/update', { method: 'POST', admin: true }),
  updateStatus: () => req('/api/update/status'),
  updateCancel: () => req('/api/update/cancel', { method: 'POST', admin: true }),
}

const qtz = new Intl.NumberFormat('es-GT', { style: 'currency', currency: 'GTQ', maximumFractionDigits: 2 })
export const money = (v) => (v == null ? '—' : qtz.format(v))
export const fmtDate = (s) =>
  s ? new Date(s).toLocaleDateString('es-GT', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
export const fmtDateTime = (s) =>
  s ? new Date(s).toLocaleString('es-GT', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
