/* "View log": the run's traceback lines from GET /api/runs/{id}/log. */
import { useEffect, useState } from 'react'
import { ApiError, getRunLog, type JobError } from '../api'

export function RunLogModal({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const [lines, setLines] = useState<string[] | null>(null)
  const [err, setErr] = useState<JobError | null>(null)
  const [fail, setFail] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    getRunLog(jobId).then(r => { if (alive) { setLines(r.lines); setErr(r.error) } })
      .catch(e => { if (alive) setFail(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) })
    return () => { alive = false }
  }, [jobId])
  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="run-log-modal">
      <div className="modal log-modal" onClick={e => e.stopPropagation()}>
        <div className="hd">
          <h3>Run log · job {jobId}</h3>
          {err && <span className="chip red">{err.type} at step {err.step === null ? '—' : String(err.step + 1).padStart(2, '0')}{err.adapter ? ` · ${err.adapter}` : ''}</span>}
          <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={onClose}>Close</button>
        </div>
        {fail ? <div className="error-card" style={{ margin: 14 }}><h3>log fetch failed</h3><pre>{fail}</pre></div>
          : lines === null ? <div className="muted mono" style={{ padding: 18 }}>loading…</div>
            : <pre>{lines.length ? lines.join('\n\n') : (err?.traceback ?? 'the log is empty — this run wrote no traceback')}</pre>}
      </div>
    </div>
  )
}
