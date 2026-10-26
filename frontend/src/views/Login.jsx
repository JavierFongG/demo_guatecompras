import { useEffect, useState } from 'react'
import { authEnabled, sendMagicLink, supabase } from '../auth.js'
import Legal from './Legal.jsx'

// Muestra la app solo con sesión iniciada. Sin Supabase configurado (desarrollo) pasa directo.
export function AuthGate({ children }) {
  const [session, setSession] = useState(undefined)   // undefined = cargando
  const [hash, setHash] = useState(window.location.hash)

  useEffect(() => {
    const onHash = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (!authEnabled) return
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s))
    return () => sub.subscription.unsubscribe()
  }, [])

  if (!authEnabled) return children(null)
  if (session === undefined) return <div className="notready"><p className="muted">Cargando…</p></div>
  if (!session) return hash.startsWith('#/terminos') ? <Legal standalone /> : <Login />
  return children(session)
}

function Login() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState('idle')   // idle | sending | sent | error
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setState('sending'); setError(null)
    try {
      await sendMagicLink(email.trim())
      setState('sent')
    } catch (err) {
      setState('error')
      setError(/signups not allowed|not found|otp_disabled/i.test(err.message || '')
        ? 'Ese correo no tiene acceso. Pide una invitación al administrador.'
        : 'No se pudo enviar el enlace. Intenta de nuevo en un minuto.')
    }
  }

  return (
    <div className="login">
      <div className="login-card">
        <div className="brand">
          <span className="logo" aria-hidden>
            <svg viewBox="0 0 32 32"><circle cx="14" cy="14" r="7" /><path d="M19 19l6 6" /></svg>
          </span>
          <div>
            <strong>Guatecompras</strong>
            <span>Buscador de concursos</span>
          </div>
        </div>
        {state === 'sent' ? (
          <>
            <h1>Revisa tu correo</h1>
            <p className="muted">Enviamos un enlace de acceso a <strong>{email}</strong>. Ábrelo en este mismo
              navegador. Si no llega en unos minutos, revisa la carpeta de spam.</p>
            <button className="link" onClick={() => setState('idle')}>Usar otro correo</button>
          </>
        ) : (
          <form onSubmit={submit}>
            <h1>Iniciar sesión</h1>
            <p className="muted">Escribe el correo con el que te invitaron y te enviaremos un enlace de acceso.</p>
            <label htmlFor="login-email" className="small">Correo electrónico</label>
            <input id="login-email" type="email" required autoFocus autoComplete="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="nombre@empresa.com" />
            {error && <div className="alert small">{error}</div>}
            <button className="btn primary" type="submit" disabled={state === 'sending' || !email}>
              {state === 'sending' ? 'Enviando…' : 'Enviar enlace de acceso'}
            </button>
          </form>
        )}
        <p className="login-foot small muted">
          Acceso solo por invitación · <a href="#/terminos">Términos y privacidad</a>
        </p>
      </div>
    </div>
  )
}
