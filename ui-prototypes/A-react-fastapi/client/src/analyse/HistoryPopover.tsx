/* Run history (frame chain-1b, decision P2): a pop-up behind the History button. Lists
   the DB copy's runs for this recording plus this server's live jobs. "Apply to source"
   loads a run's recipe steps into the chain; disabled with the reason when the recipe's
   recording differs from the current source. */
import { useEffect, useState } from 'react'
import { ApiError, listRuns, type DbRun, type JobSnapshot, type Step } from '../api'
import { fmtDuration, fmtHours, type SourceSpan } from '../state'

interface Props { source: SourceSpan | null; onApply: (steps: Step[], name: string) => void; onClose: () => void }

export function HistoryPopover({ source, onApply, onClose }: Props) {
  const [data, setData] = useState<{ db_runs: DbRun[]; jobs: JobSnapshot[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    listRuns(source?.recording_id, 30).then(d => { if (alive) setData(d) }).catch(e => { if (alive) setErr(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) })
    return () => { alive = false }
  }, [source?.recording_id])
  const spanText = (s0: number | null | undefined, s1: number | null | undefined, fs: number) =>
    s0 != null && s1 != null ? `${fmtHours(s0 / fs)}–${fmtHours(s1 / fs)}` : 'whole channel'
  const fs = source?.fs ?? 1
  return (
    <div className="an-pop hist" data-testid="history-popover">
      <h4>Run history <span>{data ? `${data.db_runs.length} in the database copy · ${data.jobs.length} live in this bridge` : ''}{source ? ` · recording ${source.recording_id} (${source.channel_name})` : ' · all recordings'}</span><button className="btn sm" style={{ marginLeft: 'auto' }} onClick={onClose}>Close</button></h4>
      {err && <div className="error-card"><h3>history failed to load</h3><pre>{err}</pre></div>}
      {!data && !err && <div className="an-pop-note">loading…</div>}
      {data && (
        <div className="hist-list">
          <div className="hist-head"><span>run</span><span>chain</span><span>span</span><span>duration</span><span>result</span><span /></div>
          {data.jobs.map(j => {
            const steps = j.recipe.steps
            const canApply = source ? j.recipe.recording_id === source.recording_id : false
            return (
              <div className="hist-row" key={`job-${j.job_id}`} data-testid={`history-job-${j.job_id}`}>
                <div><div className="name">live job {j.job_id}</div><div className="id"><span className={`badge ${j.status === 'completed' ? 'cached' : j.status === 'failed' ? 'failed' : j.status === 'running' ? 'running' : 'cancelled'}`}>{j.status}</span>{j.db_run_id ? ` · db #${j.db_run_id}` : ''}</div></div>
                <div className="steps">{steps.map((s, i) => <span key={i} title={`${s.stage}.${s.algorithm}`}>{s.algorithm}</span>).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, <i key={`s${i}`}>›</i>, el] : [el]), [])}</div>
                <div>{spanText(j.recipe.span?.[0], j.recipe.span?.[1], fs)}</div>
                <div>{fmtDuration(j.elapsed_s)}</div>
                <div>{j.detections_written ?? '—'}{j.detections_written != null ? ' det' : ''}</div>
                <div><button className="btn sm" disabled={!canApply} title={canApply ? 'load this recipe into the chain' : source ? 'different recording' : 'no source'} onClick={() => onApply(steps, `job ${j.job_id}`)}>↵ Apply to source</button></div>
              </div>
            )
          })}
          {data.db_runs.map(r => {
            // the core records a cancellation as status 'failed' + error_text 'Cancelled …'; the bridge
            // flags it as cancelled so it is not shown as a failure (critique r1)
            const cancelled = !!(r as DbRun & { cancelled?: boolean }).cancelled
            const shown = cancelled ? 'cancelled' : r.status
            const canApply = !!source && !!r.recipe && r.recipe.recording_id === source.recording_id
            const reason = !r.recipe ? 'recipe not stored' : !source ? 'no source' : r.recipe.recording_id !== source.recording_id ? 'different recording' : null
            return (
              <div className="hist-row" key={r.id} data-testid={`history-run-${r.id}`}>
                <div><div className="name">{r.name ?? `run #${r.id}`}</div><div className="id"><span className={`badge ${shown === 'completed' ? 'cached' : shown === 'failed' ? 'failed' : shown === 'running' ? 'running' : 'cancelled'}`} title={cancelled ? r.error_text ?? 'cancelled between steps' : r.error_text ?? undefined}>{shown}</span> · #{r.id} · {r.started_at.slice(0, 10)}</div></div>
                <div className="steps">{r.steps.map((s, i) => <span key={i} title={s}>{s.split('.').pop()}</span>).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, <i key={`s${i}`}>›</i>, el] : [el]), [])}</div>
                <div>{spanText(r.span_start, r.span_end, fs)}</div>
                <div>{r.duration_s != null ? fmtDuration(r.duration_s) : '—'}</div>
                <div>{r.n_detections} det</div>
                <div><button className="btn sm" disabled={!canApply} title={reason ?? 'load this recipe into the chain'} onClick={() => r.recipe && onApply(r.recipe.steps, r.name ?? `run #${r.id}`)}>↵ Apply to source</button></div>
                {reason && reason !== 'no source' && <div className="hist-reason">⊘ {reason}{r.recipe ? ` · recipe is for recording ${r.recipe.recording_id}` : ''}</div>}
              </div>
            )
          })}
          {!data.db_runs.length && !data.jobs.length && <div className="an-pop-note">no runs yet for this recording</div>}
        </div>
      )}
      <div className="an-pop-note">⚠ applying replaces the unsaved chain on the canvas</div>
    </div>
  )
}
