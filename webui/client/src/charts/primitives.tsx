/* SVG chart primitives shared by Explore and Analyse. All draw against a caller-supplied
   xScale so several rows can share one time axis. Thin lines, light grounds, tinted bands. */
import { createContext, useContext, type ReactNode } from 'react'
import { polylinePath, timeTicks, type XScale } from './scale'
import { fmtAxis } from '../state'

/** A peak-preserving polyline (interleaved t/v from the server envelope). */
export function EnvelopePath({ t, v, x, y, stroke = 'var(--trace)', width = 1, opacity = 1, testid }:
  { t: number[]; v: (number | null)[]; x: XScale; y: XScale; stroke?: string; width?: number; opacity?: number; testid?: string }) {
  const d = polylinePath(t, v, x, y)
  return <path d={d} fill="none" stroke={stroke} strokeWidth={width} strokeOpacity={opacity} strokeLinejoin="round" data-testid={testid} vectorEffect="non-scaling-stroke" />
}

/** Time axis ticks along the bottom of a surface. */
export function TimeAxis({ x, y, t0, t1, n = 6, showLine = true, ends = false }: { x: XScale; y: number; t0: number; t1: number; n?: number; showLine?: boolean; ends?: boolean }) {
  let ticks = timeTicks(t0, t1, n)
  const [r0, r1] = x.range()
  if (ends) {   // frame chain-1 prints the window's own ends ("825 s … 875 s"); drop interior ticks that would collide
    const span = t1 - t0
    ticks = [{ t: t0, label: fmtAxis(t0, span) }, ...ticks.filter(k => x(k.t) - r0 > 48 && r1 - x(k.t) > 48), { t: t1, label: fmtAxis(t1, span) }]
  }
  return (
    <g className="time-axis">
      {showLine && <line x1={r0} x2={r1} y1={y} y2={y} stroke="var(--border)" />}
      {ticks.map(k => {
        const px = x(k.t)
        // first/last labels anchor inward so nothing renders half off the surface (critique r1)
        const anchor = px - r0 < 24 ? 'start' : r1 - px < 24 ? 'end' : 'middle'
        return (
          <g key={k.t} transform={`translate(${px},${y})`}>
            <line y1={0} y2={4} stroke="var(--border-strong)" />
            <text y={14} textAnchor={anchor}>{k.label}</text>
          </g>
        )
      })}
    </g>
  )
}

/** Faint vertical gridlines at the time ticks. */
export function TimeGrid({ x, t0, t1, height, n = 6 }: { x: XScale; t0: number; t1: number; height: number; n?: number }) {
  return <g>{timeTicks(t0, t1, n).map(k => <line key={k.t} x1={x(k.t)} x2={x(k.t)} y1={0} y2={height} stroke="var(--grey-100)" />)}</g>
}

export type BandKind = 'detected' | 'annotated' | 'selected' | 'artifact' | 'grey'
const BAND_FILL: Record<BandKind, string> = {
  detected: 'var(--band-detected)', annotated: 'var(--band-annotated)', selected: 'var(--band-selected)', artifact: 'var(--band-artifact)', grey: 'rgba(107,114,128,0.14)',
}
const CAP_FILL: Record<BandKind, string> = { detected: 'var(--blue)', annotated: 'var(--green)', selected: 'var(--amber)', artifact: 'var(--red)', grey: 'var(--muted-2)' }

/** Tinted span bands with optional coloured caps above (frame explore-2 tier 2). */
export function SpanBands({ spans, x, height, capY = 0, capH = 0, onClick, minPx = 1 }:
  { spans: { start_s: number; end_s: number; kind: BandKind; id?: number | string; title?: string }[]; x: XScale; height: number; capY?: number; capH?: number; onClick?: (s: any) => void; minPx?: number }) {
  const [r0, r1] = x.range()
  return (
    <g className="span-bands" data-testid="span-bands">
      {spans.map((s, i) => {
        const x0 = Math.max(r0, x(s.start_s)); const x1 = Math.min(r1, x(s.end_s))
        if (x1 < r0 || x0 > r1) return null
        const w = Math.max(minPx, x1 - x0)
        return (
          <g key={s.id ?? i} onClick={onClick ? () => onClick(s) : undefined} style={onClick ? { cursor: 'pointer' } : undefined}>
            <rect x={x0} y={0} width={w} height={height} fill={BAND_FILL[s.kind]} data-kind={s.kind}><title>{s.title ?? s.kind}</title></rect>
            {capH > 0 && <rect x={x0} y={capY} width={w} height={capH} rx={2} fill={CAP_FILL[s.kind]} />}
          </g>
        )
      })}
    </g>
  )
}

/* ---- hover crosshair shared across rows (chain page) ---- */
interface CrosshairState { t: number | null; setT: (t: number | null) => void }
const CrossCtx = createContext<CrosshairState>({ t: null, setT: () => {} })
export const CrosshairProvider = CrossCtx.Provider
export const useCrosshair = () => useContext(CrossCtx)

/** Renders the shared crosshair line at the hovered time and reports pointer moves. */
export function CrosshairLayer({ x, height, children }: { x: XScale; height: number; children?: ReactNode }) {
  const { t, setT } = useCrosshair()
  const [r0, r1] = x.range()
  return (
    <g onPointerMove={e => { const r = (e.currentTarget as SVGGElement).getBoundingClientRect(); const px = e.clientX - r.left; setT(x.invert(px)) }} onPointerLeave={() => setT(null)}>
      <rect x={r0} y={0} width={r1 - r0} height={height} fill="transparent" />
      {children}
      {t !== null && t >= x.domain()[0] && t <= x.domain()[1] && <line x1={x(t)} x2={x(t)} y1={0} y2={height} stroke="var(--blue)" strokeOpacity={0.55} strokeDasharray="3 3" pointerEvents="none" data-testid="crosshair" />}
    </g>
  )
}

/** Small y-axis labels at the left (e.g. "+0.4 mV / 0 / −0.4 mV"). Digits adapt to the
 *  scale's range (a 60 s viewport spans ~0.0005 mV) unless `digits` is given; the group never
 *  intercepts pointer events (bands underneath stay clickable) and text carries a white halo. */
export function YLabels({ y, values, x = 4, unit = '', digits }: { y: XScale; values: number[]; x?: number; unit?: string; digits?: number }) {
  const [d0, d1] = y.domain()
  const range = Math.abs(d1 - d0) || 1
  const nd = digits ?? Math.min(6, Math.max(2, Math.ceil(-Math.log10(range)) + 2))
  return (
    <g pointerEvents="none" style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3, strokeLinejoin: 'round' }}>
      {values.map(v => <text key={v} x={x} y={y(v) + 3}>{(v > 0 ? '+' : '') + (v === 0 ? '0' : v.toFixed(nd))}{unit ? ' ' + unit : ''}</text>)}
    </g>
  )
}
