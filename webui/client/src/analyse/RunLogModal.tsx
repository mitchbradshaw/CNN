/* "View log": the run's traceback lines from GET /api/runs/{id}/log. */
import { useEffect, useRef, useState } from 'react'
import { ApiError, getRunLog, type JobError } from '../api'
import { useDismiss } from '../shell/useDismiss'

export function RunLogModal({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const [lines, setLines] = useState<string[] | null>(null)
  const [err, setErr] = useState<JobError | null>(null)
  const [fail, setFail] = useState<string | null>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  useDismiss(backdrop, onClose)   // Escape closes (critique r1)
  useEffect(() => {
    let alive = true
    getRunLog(jobId).then(r => { if (alive) { setLines(r.lines); setErr(r.error) } })
      .catch(e => { if (alive) setFail(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) })
    return () => { alive = false }
  }, [jobId])
  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="run-log-modal" ref={backdrop}>
      <div className="modal log-modal" onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="runlog-title">
        <div className="hd">
          <h3 id="runlog-title">Run log · job {jobId}</h3>
          {err && <span className="chip red">{err.type} at step {err.step === null ? '—' : String(err.step + 1).padStart(2, '0')}{err.adapter ? ` · ${err.adapter}` : ''}</span>}
          <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={onClose} autoFocus title="close (Esc)">Close</button>
        </div>
        {fail ? <div className="error-card" style={{ margin: 14 }}><h3>log fetch failed</h3><pre>{fail}</pre></div>
          : lines === null ? <div className="muted mono" style={{ padding: 18 }}>loading…</div>
            : <pre>{lines.length ? lines.join('\n\n') : (err?.traceback ?? 'the log is empty — this run wrote no traceback')}</pre>}
      </div>
    </div>
  )
}
