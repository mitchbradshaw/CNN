/* Loud fetch failure: message + status, traceback when the server sent one. */
import type { ApiError } from '../api'

export function ErrorCard({ error, title }: { error: ApiError; title?: string }) {
  return (
    <div className="error-card" role="alert" data-testid="error-card">
      <h3>⚠ {title ?? 'Request failed'}</h3>
      <div className="mono" style={{ fontSize: 12 }}>{error.status ? `${error.status} · ` : ''}{error.message}</div>
      {error.traceback && <pre>{error.traceback}</pre>}
    </div>
  )
}
