/* Shared time-axis helpers. One xScale per surface; every row on a chain page
   uses the same one, which is what makes the rows share a time axis. */
import { scaleLinear, type ScaleLinear } from 'd3'
import { fmtAxis } from '../state'

export type XScale = ScaleLinear<number, number>

export function makeX(t0: number, t1: number, width: number, padL = 0, padR = 0): XScale {
  return scaleLinear().domain([t0, t1]).range([padL, Math.max(padL + 1, width - padR)])
}
export function makeY(lo: number, hi: number, height: number, padT = 4, padB = 4): XScale {
  if (!(hi > lo)) { const c = lo || 0; lo = c - 1; hi = c + 1 }
  const m = (hi - lo) * 0.06
  return scaleLinear().domain([lo - m, hi + m]).range([height - padB, padT])
}

/** ~n nice ticks over [t0,t1] in seconds, plus labels in the span's natural unit. */
export function timeTicks(t0: number, t1: number, n = 6): { t: number; label: string }[] {
  const span = t1 - t0
  const s = scaleLinear().domain([t0, t1])
  return s.ticks(n).map(t => ({ t, label: fmtAxis(t, span) }))
}

/** Build an SVG path "M x y L x y ..." from interleaved (t, v) arrays; null breaks the line. */
export function polylinePath(t: number[], v: (number | null)[], x: XScale, y: XScale): string {
  let d = ''
  let pen = false
  for (let i = 0; i < t.length; i++) {
    const vv = v[i]
    if (vv === null || vv === undefined || Number.isNaN(vv)) { pen = false; continue }
    const px = x(t[i]); const py = y(vv)
    d += (pen ? 'L' : 'M') + px.toFixed(1) + ' ' + py.toFixed(1)
    pen = true
  }
  return d
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
