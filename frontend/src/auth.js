// Inicio de sesión con Supabase Auth (enlace mágico por correo, solo usuarios invitados).
// Sin VITE_SUPABASE_URL (desarrollo local) no se pide login y la app funciona como antes.
import { createClient } from '@supabase/supabase-js'

const URL = import.meta.env.VITE_SUPABASE_URL || ''
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || ''

export const authEnabled = !!(URL && ANON_KEY)
export const supabase = authEnabled
  ? createClient(URL, ANON_KEY, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } })
  : null

// Token vigente para la API (supabase-js lo renueva solo antes de que venza)
export async function getAccessToken() {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token || null
}

export async function sendMagicLink(email) {
  const { error } = await supabase.auth.signInWithOtp({
    email,
    // Solo usuarios invitados: no crea cuentas nuevas
    options: { shouldCreateUser: false, emailRedirectTo: window.location.origin + window.location.pathname },
  })
  if (error) throw error
}

export async function signOut() {
  if (supabase) await supabase.auth.signOut()
}
