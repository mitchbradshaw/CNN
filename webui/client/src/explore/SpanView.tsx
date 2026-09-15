/* Tier 2 — SPAN 276.4 – 278.4 h · 2.0 h (frame explore-2): the viewport. The envelope is
   re-fetched per viewport (see useViewport); while a fetch is in flight the previous path is kept
   under a translate/scale transform. Pan = pointer drag, zoom = wheel about the cursor or the
   −/+/fit buttons, ‹ N / M › walks the motif list. Tinted bands + caps mark annotations (green),
   detections (blue), the selected motif (orange) and artifacts (red). Real mV on the y axis. */
import { useEffect, useRef, useState } from 'react'
import type { Channel } from '../api'
import { EnvelopePath, SpanBands, TimeGrid, type BandKind } from '../charts/primitives'
import { makeX, makeY } from '../charts/scale'
import { fmtDuration } from '../state'
import { ErrorCard } from './ErrorCard'
import { MvLabels } from './MvLabels'
import { envelopeOk, fmtInt, fmtMs, fmtRangeH, MALFORMED_WINDOW, mvDigits, viewportHourTicks, vRange, type Motif } from './util'
import type { Viewport } from './useViewport'

const H = 150, TOP = 18, AXIS_H = 20
/** Past this CSS scale the kept path is a stretched/squashed sliver, not a preview: show the skeleton instead (critique r1). */
const MAX_STRETCH = 8
/** Left gutter kept clear of the y labels ("−0.2016 mV" at x=4, 10 px mono ≈ 6.2 px/glyph) so the motif label
 *  never overprints them; widens with the label's digit count, never below the critique's 64 px. */
const labelGutter = (lo: number, hi: number) => Math.max(64, 12 + (mvDigits(lo, hi) + 7) * 6.2)

export interface Band { start_s: number; end_s: number; kind: BandKind; id: string; title: string; motif: Motif }

export function SpanView({ ch, vp, plotRef, width, bands, selected, onBandClick, nav }: {
  ch: Channel; vp: Viewport; plotRef: React.RefObject<HTMLDivElement | null>; width: number
  bands: Band[]; selected: Motif | null; onBandClick: (m: Motif) => void
  nav: { index: number; total: number; capped: boolean; prev: () => void; next: () => void }
}) {
  const W = Math.max(0, width)
  const [a, b] = vp.view
  const x = makeX(a, b, W)
  const win = vp.win
  const envOk = !win || envelopeOk(win.data?.envelope)   // shape guard: a malformed 200 draws an ErrorCard, not a throw
  const range = (win && envOk ? vRange(win.data.envelope.v) : null) ?? ch.y_range
  const y = makeY(range[0], range[1], H, TOP + 6, 8)
  // transform from the fetched viewport onto the current one (kept until the new data lands)
  let transform: string | undefined
  let xf = x
  let stale = false   // the kept path would be stretched > MAX_STRETCH× or does not overlap the new view: draw the skeleton
  if (win) {
    const [fa, fb] = win.view
    xf = makeX(fa, fb, W)
    const s = (fb - fa) / (b - a)
    const dx = ((fa - a) / (b - a)) * W
    if (Math.abs(s - 1) > 1e-9 || Math.abs(dx) > 1e-6) transform = `translate(${dx.toFixed(2)},0) scale(${s.toFixed(6)},1)`
    stale = s > MAX_STRETCH || s < 1 / MAX_STRETCH || fb <= a || fa >= b
  }

  const svgRef = useRef<SVGSVGElement | null>(null)
  const drag = useRef<{ x0: number; view: [number, number]; moved: boolean } | null>(null)
  const [dragging, setDragging] = useState(false)
  const { zoomAt, viewRef, setView } = vp

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const [va, vb] = viewRef.current
      const anchor = va + ((e.clientX - r.left) / r.width) * (vb - va)
      const notches = Math.max(-10, Math.min(10, e.deltaY / 100))
      zoomAt(Math.pow(1.15, notches), anchor)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, viewRef, W])

  const onDown = (e: React.PointerEvent<SVGSVGElement>) => { if (e.button !== 0) return; drag.current = { x0: e.clientX, view: viewRef.current, moved: false } }
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    if (!d || W <= 0) return
    const dx = e.clientX - d.x0
    if (!d.moved) { if (Math.abs(dx) < 3) return; d.moved = true; setDragging(true); e.currentTarget.setPointerCapture(e.pointerId) }
    const [va, vb] = d.view
    const dt = (-dx / W) * (vb - va)
    setView([va + dt, vb + dt])
  }
  const onUp = () => { drag.current = null; setDragging(false) }
  // keyboard (critique r1: pan/zoom were pointer-only): ← → pan a tenth of the view (Shift: half), + − zoom about the centre
  const onKey = (e: React.KeyboardEvent<SVGSVGElement>) => {
    const [va, vb] = viewRef.current
    const span = vb - va
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault()
      const dt = (e.shiftKey ? 0.5 : 0.1) * span * (e.key === 'ArrowLeft' ? -1 : 1)
      setView([va + dt, vb + dt])
    } else if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(1 / 1.5, (va + vb) / 2) }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAt(1.5, (va + vb) / 2) }
  }

  const st = vp.lastStat
  const ticks = viewportHourTicks(a, b)
  // stale numbers (previous view) read as live otherwise: grey from the moment the view moves, not only once the debounced fetch starts
  const dim = vp.fetching || (!!win && (win.view[0] !== a || win.view[1] !== b))

  return (
    <div className="card ex-tier" data-testid="signal-span-card">
      <div className="head">
        <span className="card-title">Span</span>
        <span className="range" data-testid="span-range">{fmtRangeH(a, b)} · {fmtDuration(b - a)}</span>
        {st && <span className="stat" data-testid="zoom-stat" data-dim={dim ? '1' : '0'} style={{ opacity: dim ? 0.4 : 1 }} title={dim ? 'previous viewport — refreshing' : undefined}>{fmtInt(st.n_points)} pts · server {fmtMs(st.decimate_ms)} · round trip {fmtMs(st.round_trip_ms)} · paint {fmtMs(st.paint_ms)}</span>}
        {vp.fetching && <span className="stat">fetching…</span>}
        <span className="grow" />
        <span className="ex-nav" data-testid="motif-nav">
          <button onClick={nav.prev} title="previous motif" data-testid="motif-prev">‹</button>
          <span>{nav.index >= 0 ? nav.index + 1 : '–'} / {fmtInt(nav.total)}{nav.capped ? '+' : ''}</span>
          <button onClick={nav.next} title="next motif" data-testid="motif-next">›</button>
        </span>
        <span className="ex-zoom">
          <button title="zoom out" data-testid="zoom-out" onClick={() => zoomAt(1.5, (a + b) / 2)}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5M8 11h6" /></svg></button>
          <button title="zoom in" data-testid="zoom-in" onClick={() => zoomAt(1 / 1.5, (a + b) / 2)}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5M8 11h6M11 8v6" /></svg></button>
          <button title="fit whole channel" data-testid="zoom-fit" onClick={vp.fit}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /></svg></button>
        </span>
      </div>
      {vp.error && <ErrorCard error={vp.error} title="viewport fetch failed" />}
      {!envOk && <ErrorCard error={MALFORMED_WINDOW} title="viewport payload cannot be drawn" />}
      <div className={`ex-plot pan${dragging ? ' dragging' : ''}`} ref={plotRef} style={{ height: H + AXIS_H }}>
        {W > 0 && (
          <svg ref={svgRef} width={W} height={H + AXIS_H} data-testid="signal-span" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
            tabIndex={0} role="group" aria-label="span viewport: ← → pan, Shift for a larger step, + − zoom" aria-keyshortcuts="ArrowLeft ArrowRight + -" onKeyDown={onKey}>
            <rect x={0} y={0} width={W} height={H + AXIS_H} fill="#fff" />
            <g transform={`translate(0,${TOP})`}><TimeGrid x={x} t0={a} t1={b} height={H - TOP} /></g>
            <g transform={`translate(0,${TOP})`}>
              <SpanBands spans={bands} x={x} height={H - TOP} capY={-13} capH={6} onClick={s => onBandClick((s as Band).motif)} minPx={2} />
            </g>
            {selected && selected.end_s > a && selected.start_s < b && (
              // starts at the band, but never inside the y-label gutter (critique r1: MOTIF_744 overprinted "−0.23 mV")
              <text x={Math.max(labelGutter(range[0], range[1]), x(selected.start_s) + 4)} y={TOP + 12} style={{ fill: 'var(--amber)', fontWeight: 600 }} pointerEvents="none" data-testid="motif-label">MOTIF_{selected.id}</text>
            )}
            {win && envOk && !stale ? (
              <g transform={transform} data-testid="envelope-group" data-transformed={transform ? '1' : '0'}>
                <EnvelopePath t={win.data.envelope.t} v={win.data.envelope.v} x={xf} y={y} testid="envelope-path" />
              </g>
            ) : <rect className="skeleton" x={0} y={TOP + 8} width={W} height={H - TOP - 16} fill="var(--grey-100)" data-testid="span-skeleton" data-reason={!win ? 'no-data' : !envOk ? 'malformed' : 'stale-transform'} />}
            <MvLabels y={y} lo={range[0]} hi={range[1]} dim={dim || stale} />
            <line x1={0} x2={W} y1={H} y2={H} stroke="var(--border)" />
            <g className="time-axis" transform={`translate(0,${H})`}>
              {ticks.map(k => { const px = x(k.t); return <g key={k.t} transform={`translate(${px},0)`}><line y1={0} y2={4} stroke="var(--border-strong)" /><text x={px < 24 ? 2 : 0} y={14} textAnchor={px < 24 ? 'start' : px > W - 24 ? 'end' : 'middle'}>{k.label}</text></g> })}
            </g>
          </svg>
        )}
      </div>
      <div className="row between" style={{ marginTop: 6 }}>
        <span className="legend"><span><i style={{ background: 'var(--blue)' }} />detected</span><span><i style={{ background: 'var(--green)' }} />annotated</span><span><i style={{ background: 'var(--amber)' }} />selected</span><span><i style={{ background: 'var(--red)' }} />artifact</span></span>
        <span className="muted small">drag to pan · wheel to zoom · or click the plot and use ← → and + − · peak-preserving min/max envelope re-fetched for every viewport · real mV, never normalised · click a band to select that motif</span>
      </div>
    </div>
  )
}
