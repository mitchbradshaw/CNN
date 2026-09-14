/* Tier 3 — MOTIF_<id> (frame explore-2): the selected motif with ± context, ONSET / END lines,
   the motif region tinted orange, an axis relative to onset, and its own Send motif to Analyse. */
import { useEffect, useState } from 'react'
import { getWindow, type ApiError, type Channel, type WindowData } from '../api'
import { EnvelopePath } from '../charts/primitives'
import { makeX, makeY } from '../charts/scale'
import { useSize } from '../charts/useSize'
import { ErrorCard } from './ErrorCard'
import { MvLabels } from './MvLabels'
import { asApiError, fmtSecs, relativeTicks, vRange, type Motif } from './util'

const H = 96, AXIS_H = 20
const CONTEXTS = [10, 20, 60]

export function MotifView({ ch, motif, onSend }: { ch: Channel; motif: Motif | null; onSend: (m: Motif) => void }) {
  const [ctx, setCtx] = useState(20)
  const [ref, size] = useSize<HTMLDivElement>()
  const W = Math.max(0, size.width)
  const widthKey = Math.round(W / 50)
  const [win, setWin] = useState<{ data: WindowData & { round_trip_ms: number }; key: string } | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const key = motif ? `${motif.key}:${ctx}:${widthKey}` : ''
  const t0 = motif ? Math.max(0, motif.start_s - ctx) : 0
  const t1 = motif ? Math.min(ch.duration_s, motif.end_s + ctx) : 0
  useEffect(() => {
    if (!motif || widthKey <= 0) return
    let alive = true
    setErr(null)
    getWindow(ch.id, t0, t1, widthKey * 50).then(w => { if (alive) setWin({ data: w, key }) }).catch(e => { if (alive) setErr(asApiError(e)) })
    return () => { alive = false }
  }, [key, ch.id, t0, t1, widthKey, motif])

  const cur = win && win.key === key ? win.data : null
  const x = makeX(t0, t1, W)
  const range = (cur && vRange(cur.envelope.v)) ?? ch.y_range
  const y = makeY(range[0], range[1], H, 8, 8)
  const origin = motif ? (motif.kind === 'annotated' ? `annotated · ${motif.verdict ?? 'unadjudicated'}` : `detected · run ${motif.run_id}`) : ''

  return (
    <div className="card ex-tier" data-testid="signal-motif">
      <div className="head">
        <span className="card-title">{motif ? `Motif_${motif.id}` : 'Motif'}</span>
        {motif ? (
          <span className="range" data-testid="motif-range">{(motif.start_s / 3600).toFixed(3)} – {(motif.end_s / 3600).toFixed(3)} h · {fmtSecs(motif.end_s - motif.start_s)} · {origin}</span>
        ) : <span className="range muted">no motif selected · click a band in the span, or use ‹ ›</span>}
        <span className="grow" />
        <span className="chip" style={{ height: 26 }}>
          <span className="muted">context</span>
          <select className="ex-select-bare" value={ctx} onChange={e => setCtx(Number(e.target.value))} data-testid="motif-context">
            {CONTEXTS.map(c => <option key={c} value={c}>±{c} s</option>)}
          </select>
        </span>
        <label className="checkbox inert" title="Library medoids are out of slice scope"><input type="checkbox" disabled /> overlay F-03 medoid</label>
      </div>
      {err && <ErrorCard error={err} title="motif window failed" />}
      <div className="ex-plot" ref={ref} style={{ height: H + AXIS_H }}>
        {W > 0 && motif && (
          <svg width={W} height={H + AXIS_H} data-testid="motif-svg">
            <rect x={0} y={0} width={W} height={H + AXIS_H} fill="#fff" />
            <rect x={x(motif.start_s)} y={0} width={Math.max(1, x(motif.end_s) - x(motif.start_s))} height={H} fill="var(--band-selected)" data-testid="motif-region" />
            {cur ? <EnvelopePath t={cur.envelope.t} v={cur.envelope.v} x={x} y={y} stroke="var(--trace-orange)" testid="motif-path" />
              : <rect className="skeleton" x={0} y={8} width={W} height={H - 16} fill="var(--grey-100)" />}
            <line x1={x(motif.start_s)} x2={x(motif.start_s)} y1={0} y2={H} stroke="#374151" strokeWidth={1} />
            <text x={x(motif.start_s) + 4} y={x(motif.start_s) < 70 ? 24 : 12} style={{ fill: 'var(--red)' }}>ONSET</text>
            <line x1={x(motif.end_s)} x2={x(motif.end_s)} y1={0} y2={H} stroke="var(--red)" strokeWidth={1} />
            <text x={x(motif.end_s) + 4} y={12} style={{ fill: 'var(--red)' }}>END</text>
            <MvLabels y={y} lo={range[0]} hi={range[1]} />
            <line x1={0} x2={W} y1={H} y2={H} stroke="var(--border)" />
            <g className="time-axis" transform={`translate(0,${H})`}>
              {relativeTicks(t0, t1, motif.start_s).map(k => <g key={k.t} transform={`translate(${x(k.t)},0)`}><line y1={0} y2={4} stroke="var(--border-strong)" /><text y={14} textAnchor="middle">{k.label}</text></g>)}
            </g>
          </svg>
        )}
        {W > 0 && !motif && <div className="muted small mono" style={{ padding: 12 }}>select a motif to see it here with ±{ctx} s of context</div>}
      </div>
      <div className="ex-motif-foot">
        <span className="fam" data-testid="motif-footer">nearest family — · tagged {motif?.tag ?? '—'} · {motif ? (motif.kind === 'annotated' ? (motif.verdict ?? 'unadjudicated') : 'unadjudicated') : '—'}</span>
        <span className="row">
          <button className="btn" disabled={!motif} onClick={() => motif && onSend(motif)} data-testid="send-motif">Send motif to Analyse →</button>
          <button className="btn primary inert" title="Review is out of slice scope" aria-disabled>Review this motif →</button>
        </span>
      </div>
      <p className="muted small" style={{ margin: '4px 0 0' }}>the selected motif with its context · onset and end are the stored span edges · family and tag are honest dashes: nothing in this database asserts them</p>
    </div>
  )
}
