// Términos de uso y aviso de privacidad (#/terminos). Revisa el texto antes de publicar:
// es una base razonable para un piloto con usuarios invitados, no asesoría legal.
const CONTACT = import.meta.env.VITE_CONTACT_EMAIL || ''

export default function Legal({ standalone = false }) {
  return (
    <div className={standalone ? 'legal standalone' : 'legal'}>
      {standalone && <p><a href="#/">← Volver</a></p>}
      <h1>Términos de uso y privacidad</h1>
      <p className="muted small">Versión piloto · octubre de 2026</p>

      <h2>Qué es este servicio</h2>
      <p>Un buscador de concursos públicos de Guatemala construido sobre los datos abiertos de Guatecompras.
        Está en fase piloto y el acceso es solo por invitación.</p>

      <h2>Origen de los datos</h2>
      <p>Los datos provienen de <a href="https://ocds.guatecompras.gt" target="_blank" rel="noreferrer">Guatecompras OCDS</a>,
        publicados por el Ministerio de Finanzas Públicas (Dirección General de Adquisiciones del Estado) bajo la
        licencia <a href="https://creativecommons.org/licenses/by/4.0/deed.es" target="_blank" rel="noreferrer">CC BY 4.0</a>.
        Se actualizan una vez al día y pueden tener retrasos o diferencias con el portal oficial. Para cualquier
        decisión, verifica la información en <a href="https://www.guatecompras.gt" target="_blank" rel="noreferrer">guatecompras.gt</a>.</p>
      <p>Las referencias de precios, las líneas de negocio de un proveedor y las recomendaciones se calculan
        automáticamente y son orientativas.</p>

      <h2>Datos de personas</h2>
      <p>Algunos proveedores son personas individuales identificadas por su NIT en los registros públicos de
        adjudicaciones. Esta información se muestra tal como la publica el Estado. Úsala solo para fines
        relacionados con la contratación pública.</p>

      <h2>Qué guardamos sobre ti</h2>
      <ul>
        <li>Tu correo electrónico y las fechas en que inicias sesión, para darte acceso.</li>
        <li>Registros técnicos de las solicitudes (sin el contenido de tus búsquedas asociado a tu nombre) para
          detectar errores y abusos.</li>
        <li>Estadísticas de visitas anónimas, sin cookies.</li>
      </ul>
      <p>No vendemos ni compartimos estos datos. Puedes pedir que eliminemos tu cuenta en cualquier momento
        {CONTACT ? <> escribiendo a <a href={`mailto:${CONTACT}`}>{CONTACT}</a></> : ' contactando al administrador'}.</p>

      <h2>Uso aceptable</h2>
      <p>No intentes descargar el índice completo de forma automatizada ni compartir tu acceso. El servicio se
        ofrece tal cual, sin garantías, y puede cambiar o interrumpirse durante el piloto.</p>
    </div>
  )
}
