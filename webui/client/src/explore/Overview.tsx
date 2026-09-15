/* Tier 1 — CHANNEL 0 – 721 h (frame explore-2): the full-channel envelope, a blue selected-span box
   with two draggable grip handles, then the coverage ribbon (verdict colours per bucket) and the
   detection-density ribbon, on an absolute-hours axis. The box IS the tier-2 viewport. */
import { useEffect, useRef, useState } from 'react'
import { getWindow, type ApiError, type Channel, type WindowData } from '../api'
import { EnvelopePath } from '../charts/primitives'
import { clamp, makeX, makeY } from '../charts/scale'
import { useSize } from '../charts/useSize'
import { ErrorCard } from './ErrorCard'
import { asApiError, envelopeOk, fmtRangeH, hourTicks, MALFORMED_WINDOW, MIN_SPAN_S, VERDICT_COLOUR, vRange } from './util'

const TRACE_H = 64, COV_Y = 72, COV_H = 8, DEN_Y = 84, DEN_H = 14, AXIS_Y = 104, H = 116
const HW = 8, HH = 22

const COV_COLOUR = (v: string | null) => (v === null ? '#e5e7eb' : VERDICT_COLOUR[v] ?? '#e5e7eb')

type Drag = { mode: 'left' | 'right' | 'body'; x0: number; view: [number, number] }

export function Overview({ ch, view, onView }: { ch: Channel; view: [number, number]; onView: (v: [number, number]) => void }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const W = Math.max(0, size.width)
  const widthKey = Math.round(W / 100)
  const [full, setFull] = useState<(WindowData & { round_trip_ms: number }) | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const dur = ch.duration_s
  useEffect(() => {
    if (widthKey <= 0) return
    let alive = true
    getWindow(ch.id, 0, dur, widthKey * 100)
      .then(w => { if (!alive) return; if (!envelopeOk(w?.envelope)) { setFull(null); setErr(MALFORMED_WINDOW); return } setFull(w); setErr(null) })
      .catch(e => { if (alive) setErr(asApiError(e)) })
    return () => { alive = false }
  }, [ch.id, dur, widthKey])

  const x = makeX(0, dur, W)
  const range = (full && vRange(full.envelope.v)) ?? ch.y_range
  const y = makeY(range[0], range[1], TRACE_H, 6, 6)
  const drag = useRef<Drag | null>(null)
  const [dragging, setDragging] = useState(false)

  const start = (mode: Drag['mode']) => (e: React.PointerEvent<SVGElement>) => {
    if (e.button !== 0) return
    e.stopPropagation()
    drag.current = { mode, x0: e.clientX, view }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    setDragging(true)
  }
  const move = (e: React.PointerEvent<SVGElement>) => {
    const d = drag.current
    if (!d || W <= 0) return
    const [a, b] = d.view
    const minSpan = Math.min(dur, MIN_SPAN_S)
    const dt = ((e.clientX - d.x0) / W) * dur
    if (d.mode === 'body') onView([a + dt, b + dt])
    else if (d.mode === 'left') onView([clamp(a + dt, 0, b - minSpan), b])
    else onView([a, clamp(b + dt, a + minSpan, dur)])
  }
  const end = () => { drag.current = null; setDragging(false) }
  // keyboard: ← → nudge a grip (or the whole box) by one overview bucket, Shift = ×10 (critique r1: mouse-only)
  const bucket = ch.ribbons.bucket_s > 0 ? ch.ribbons.bucket_s : dur / Math.max(1, ch.ribbons.buckets)
  const nudge = (mode: Drag['mode'], dir: -1 | 1, big: boolean) => {
    const dt = dir * bucket * (big ? 10 : 1)
    const [a, b] = view
    const minSpan = Math.min(dur, MIN_SPAN_S)
    if (mode === 'body') onView([a + dt, b + dt])
    else if (mode === 'left') onView([clamp(a + dt, 0, b - minSpan), b])
    else onView([a, clamp(b + dt, a + minSpan, dur)])
  }
  const onKey = (mode: Drag['mode']) => (e: React.KeyboardEvent<SVGElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault(); e.stopPropagation()
    nudge(mode, e.key === 'ArrowLeft' ? -1 : 1, e.shiftKey)
  }
  const sliderProps = (mode: Drag['mode']) => ({
    tabIndex: 0, role: 'slider', 'aria-orientation': 'horizontal' as const,
    'aria-label': mode === 'body' ? 'selected span (← → move by one bucket, Shift ×10)' : `span ${mode === 'left' ? 'start' : 'end'} (← → nudge by one bucket, Shift ×10)`,
    'aria-valuemin': 0, 'aria-valuemax': Math.round(dur), 'aria-valuenow': Math.round(mode === 'right' ? view[1] : view[0]),
    'aria-valuetext': mode === 'body' ? fmtRangeH(view[0], view[1]) : `${((mode === 'right' ? view[1] : view[0]) / 3600).toFixed(2)} h`,
    onKeyDown: onKey(mode),
  })
  const clickBg = (e: React.PointerEvent<SVGRectElement>) => {
    // click on the trace outside the box: move the box there, same length
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const t = x.invert(e.clientX - r.left)
    const span = view[1] - view[0]
    onView([t - span / 2, t + span / 2])
  }

  const x0 = x(view[0]), x1 = x(view[1])
  const boxW = Math.max(1, x1 - x0)
  const narrow = boxW < 24
  let lhx = narrow ? x0 - HW - 1 : x0 - HW / 2
  let rhx = narrow ? x1 + 1 : x1 - HW / 2
  if (lhx < 0) { lhx = 0; if (narrow) rhx = Math.max(rhx, lhx + HW + 2) }
  if (rhx > W - HW) { rhx = W - HW; if (narrow) lhx = Math.min(lhx, rhx - HW - 2) }
  const hy = TRACE_H / 2 - HH / 2
  const rb = ch.ribbons
  const bw = W / Math.max(1, rb.buckets)
  const denMax = rb.detection_density.reduce((m, v) => (v > m ? v : m), 0)
  // merge equal-colour runs of the coverage ribbon into rounded segments (frame: green/orange/red bars)
  const covSegs: { i0: number; i1: number; c: string }[] = []
  rb.coverage.forEach((v, i) => {
    const c = COV_COLOUR(v)
    const last = covSegs[covSegs.length - 1]
    if (last && last.c === c && last.i1 === i) last.i1 = i + 1
    else covSegs.push({ i0: i, i1: i + 1, c })
  })

  return (
    <div className="card ex-tier" data-testid="signal-overview-card">
      <div className="head">
        <span className="card-title">Channel</span>
        <span className="range">0 – {Number.isInteger(dur / 3600) ? dur / 3600 : (dur / 3600).toFixed(dur / 3600 >= 10 ? 0 : 2)} h</span>
        <span className="grow" />
        {full && <span className="stat">{full.envelope.n_points.toLocaleString('en-US')} pts · full channel · server {full.decimate_ms.toFixed(1)} ms</span>}
      </div>
      {err && <ErrorCard error={err} title="full-channel envelope failed" />}
      <div className={`ex-plot${dragging ? ' dragging' : ''}`} ref={ref} style={{ height: H }}>
        {W > 0 && (
          <svg width={W} height={H} data-testid="signal-overview">
            <rect x={0} y={0} width={W} height={TRACE_H} fill="#fff" onPointerDown={clickBg} style={{ cursor: 'crosshair' }} />
            <line x1={0} x2={W} y1={TRACE_H} y2={TRACE_H} stroke="var(--border)" />
            {full ? <EnvelopePath t={full.envelope.t} v={full.envelope.v} x={x} y={y} testid="overview-path" /> : <rect className="skeleton" x={0} y={8} width={W} height={TRACE_H - 16} fill="var(--grey-100)" />}
            {/* selected span box: draggable body */}
            <rect x={x0} y={0} width={boxW} height={TRACE_H} fill="var(--blue)" fillOpacity={0.16} stroke="var(--blue)" strokeWidth={1}
              data-testid="span-box" className="ex-focusable" style={{ cursor: 'move' }} onPointerDown={start('body')} onPointerMove={move} onPointerUp={end} onPointerCancel={end} {...sliderProps('body')} />
            {/* grip handles with a centre groove */}
            {([['left', lhx], ['right', rhx]] as const).map(([side, hx]) => (
              <g key={side} data-testid={`span-handle-${side}`} className="ex-focusable" style={{ cursor: 'ew-resize' }} onPointerDown={start(side)} onPointerMove={move} onPointerUp={end} onPointerCancel={end} {...sliderProps(side)}>
                <rect x={hx - 3} y={hy - 3} width={HW + 6} height={HH + 6} fill="transparent" />
                <rect x={hx} y={hy} width={HW} height={HH} rx={3} fill="var(--blue)" />
                <line x1={hx + HW / 2} x2={hx + HW / 2} y1={hy + 6} y2={hy + HH - 6} stroke="#fff" strokeOpacity={0.75} strokeWidth={1.2} />
              </g>
            ))}
            {/* coverage ribbon */}
            <g data-testid="coverage-ribbon">
              {covSegs.map(s => <rect key={s.i0} x={s.i0 * bw + 0.5} y={COV_Y} width={Math.max(0.5, (s.i1 - s.i0) * bw - 1)} height={COV_H} rx={2} fill={s.c}><title>{rb.coverage[s.i0] ?? 'no annotation'}</title></rect>)}
            </g>
            {/* detection density ribbon */}
            <g data-testid="density-ribbon" data-max={denMax}>
              {denMax > 0 ? rb.detection_density.map((d, i) => {
                const h = (d / denMax) * DEN_H
                return d > 0 ? <rect key={i} x={i * bw + 0.5} y={DEN_Y + DEN_H - h} width={Math.max(0.5, bw - 1)} height={h} rx={1} fill="var(--blue)" /> : null
              }) : (
                <>
                  <rect x={0} y={DEN_Y + DEN_H - 3} width={W} height={3} rx={1.5} fill="#dbe7f5" />
                  <text x={0} y={DEN_Y + 9} style={{ fill: 'var(--muted-2)' }}>no detections on this channel</text>
                </>
              )}
            </g>
            <g className="time-axis" transform={`translate(0,${AXIS_Y})`}>
              {hourTicks(dur / 3600).map((k, i, arr) => (
                <text key={k.h} x={x(k.h * 3600) + (i === 0 ? 2 : 0)} y={10} textAnchor={i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle'}>{k.label}</text>
              ))}
            </g>
          </svg>
        )}
      </div>
      <p className="muted small" style={{ margin: '4px 0 0' }}>
        the whole channel at {full ? `${full.envelope.n_points.toLocaleString('en-US')} min/max points` : '…'} · drag the blue box or its grips to choose the span shown below (or Tab to a grip and press ← → · Shift ×10) · ribbons: human verdicts per bucket, then machine detection density
      </p>
    </div>
  )
}
