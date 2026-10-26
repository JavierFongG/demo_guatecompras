import React from 'react'
import { createRoot } from 'react-dom/client'
import * as Sentry from '@sentry/react'
import App from './App.jsx'
import { AuthGate } from './views/Login.jsx'
import './styles.css'

// Errores del navegador a Sentry (solo si VITE_SENTRY_DSN está configurado al compilar)
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({ dsn: import.meta.env.VITE_SENTRY_DSN, environment: import.meta.env.MODE, sendDefaultPii: false })
}

createRoot(document.getElementById('root')).render(
  <Sentry.ErrorBoundary fallback={<div className="notready"><h1>Algo salió mal</h1><p>Recarga la página.</p></div>}>
    <AuthGate>{(session) => <App session={session} />}</AuthGate>
  </Sentry.ErrorBoundary>,
)
