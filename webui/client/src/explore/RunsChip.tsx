/* "detections N runs ▾" chip on the signal top bar. Critique r1: it looked live (▾ affordance) and did
   nothing. It is now a real button that opens a small popover listing the recording's runs from
   GET /api/runs?recording_id=<id> (newest first, capped by the server at `limit`). Filtering the span
   tier by run is out of slice scope and the popover says so. Escape / click-outside close it. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { listRuns, type ApiError, type DbRun } from '../api'
import { useDismiss } from '../shell/useDismiss'
import { ErrorCard } from './ErrorCard'
import { asApiError, fmtInt } from './util'

const LIMIT = 30
type Run = DbRun & { cancelled?: boolean }   // `cancelled` is new on the server; the shared DbRun type does not carry it yet

function fmtStarted(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function RunsChip({ recordingId, channelName, nDetectionRuns, nDetections }:
  { recordingId: number; channelName: string; nDetectionRuns: number; nDetections: number }) {
  const [open, setOpen] = useState(false)
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const ref = useRef<HTMLDivElement | null>(null)
  const close = useCallback(() => setOpen(false), [])
  useDismiss(ref, close, open)

  useEffect(() => {
    if (!open) return
    let alive = true
    setErr(null)
    listRuns(recordingId, LIMIT)
      .then(r => { if (!alive) return; setRuns(Array.isArray(r?.db_runs) ? (r.db_runs as Run[]) : []) })
      .catch(e => { if (alive) setErr(asApiError(e)) })
    return () => { alive = false }
  }, [open, recordingId])

  const status = (r: Run) => (r.cancelled ? 'cancelled' : r.status)
  return (
    <div className="ex-runs" ref={ref}>
      <button type="button" className="chip ex-runs-chip" onClick={() => setOpen(o => !o)} aria-expanded={open} aria-controls="ex-runs-pop"
        title={`runs that wrote detections on ${channelName} · click to list every run on this channel`} data-testid="detection-runs-chip">
        detections <b>{nDetectionRuns} run{nDetectionRuns === 1 ? '' : 's'}</b> ▾
      </button>
      {open && (
        <div className="popover ex-runs-pop" id="ex-runs-pop" role="dialog" aria-label={`runs on ${channelName}`} data-testid="detection-runs-popover">
          <div className="row between" style={{ marginBottom: 6 }}>
            <span className="card-title" style={{ fontSize: 12.5 }}>runs on {channelName}</span>
            <span className="muted small mono">{fmtInt(nDetections)} detections from {nDetectionRuns} run{nDetectionRuns === 1 ? '' : 's'}</span>
          </div>
          {err && <ErrorCard error={err} title="GET /api/runs failed" />}
          {!err && runs === null && <div className="skeleton" style={{ height: 48 }} data-testid="detection-runs-skeleton" />}
          {runs && runs.length === 0 && <div className="muted small mono" data-testid="detection-runs-empty">no runs have been recorded on this channel</div>}
          {runs && runs.length > 0 && (
            <table className="ex-table" data-testid="detection-runs-table">
              <thead><tr><th>run</th><th>chain</th><th>status</th><th style={{ textAlign: 'right' }}>wrote</th><th>started</th></tr></thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} data-testid="detection-run-row" data-status={status(r)}>
                    <td>#{r.id}{r.name ? ` ${r.name}` : ''}</td>
                    <td title={(r.steps ?? []).join(' › ')}>{(r.steps ?? []).map(s => s.split('.').pop()).join(' › ') || '—'}</td>
                    <td style={{ color: status(r) === 'completed' ? 'var(--green)' : status(r) === 'failed' ? 'var(--red)' : 'var(--muted)' }}>{status(r)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtInt(r.n_detections ?? 0)} det.</td>
                    <td className="muted">{fmtStarted(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="muted small mono" style={{ marginTop: 8 }}>
            {runs && runs.length >= LIMIT ? `newest ${LIMIT} shown · ` : ''}every detection drawn below comes from one of these runs · filtering the span tier by run is out of slice scope · Esc closes
          </div>
        </div>
      )}
    </div>
  )
}
