/* Local helpers for the Explore workspace. Nothing here duplicates api.ts, state.tsx or charts/ —
   these are the bits the shared layer does not offer (hour-based axis ticks, verdict colours,
   the motif list built from a Spans payload, view clamping). */
import { ApiError, type Envelope, type Spans } from '../api'

export const MIN_SPAN_S = 60

/** Matrices a coverage row carries (CoverageRow keys the heatmap can colour by). */
export type ColourBy = 'annotations' | 'detections' | 'both' | 'disagree'
export const COLOUR_BY: ColourBy[] = ['annotations', 'detections', 'both', 'disagree']
export const MATRIX_UNIT: Record<ColourBy, string> = { annotations: 'annotations', detections: 'detections', both: 'spans', disagree: 'disagreements' }

export const VERDICTS = ['seed', 'interesting', 'not_interesting', 'artifact', 'unsure']
export const VERDICT_COLOUR: Record<string, string> = {
  seed: '#0a84ff', interesting: '#22a06b', not_interesting: '#8a97a8', artifact: '#e5484d', unsure: '#e8900c',
}
export const TAGS = ['sharkfin', 'spike-train', 'slow-drift', 'burst', 'plateau', 'biphasic']

/** 5-step blue ramp for the coverage map; index 0 is "no spans" (frame explore-1: low → high). */
export const RAMP = ['#F1F3F5', '#D4E4FF', '#AACDFF', '#7AB2FF', '#3F93FF', '#0A84FF']

/** Decimals needed so mV labels spanning [lo, hi] read as different numbers (min 2, max 6). */
export function mvDigits(lo: number, hi: number): number {
  const span = Math.abs(hi - lo)
  if (!(span > 0)) return 3
  return Math.max(2, Math.min(6, Math.ceil(-Math.log10(span)) + 1))
}
export function rampIndex(count: number, max: number): number {
  if (!(count > 0) || !(max > 0)) return 0
  return Math.min(5, Math.max(1, Math.ceil((count / max) * 5)))
}

/** Quantile-rank ramp (critique r1: a linear count/max ramp collapsed the map to one shade once a
 *  single hot cell existed). Level 1–5 is the percentile rank of a cell among the NON-ZERO cells of
 *  the drawn matrix — mid-rank for ties, so a near-uniform matrix sits mid-blue and its small
 *  differences move cells up or down; zero stays level 0 ("no spans"). */
export function quantileRamp(values: number[]): (count: number) => number {
  const nz = values.filter(v => v > 0).sort((p, q) => p - q)
  const n = nz.length
  return (count: number) => {
    if (!(count > 0) || n === 0) return 0
    let lo = 0, hi = n                       // lower bound: values strictly below count
    while (lo < hi) { const mid = (lo + hi) >> 1; if (nz[mid] < count) lo = mid + 1; else hi = mid }
    let up = lo                              // upper bound: values ≤ count
    while (up < n && nz[up] === count) up++
    return 1 + Math.min(4, Math.floor((5 * (lo + up)) / (2 * n)))
  }
}

/* ---- payload shape guards (critique r1: a malformed 200 must land in an ErrorCard, not a render throw) ---- */
export function envelopeOk(e: unknown): e is Envelope {
  const x = e as Envelope | null
  return !!x && Array.isArray(x.t) && Array.isArray(x.v)
}
export function spansOk(s: unknown): s is Spans {
  const x = s as Spans | null
  return !!x && Array.isArray(x.annotations) && Array.isArray(x.detections)
}
export const MALFORMED_WINDOW = new ApiError(0, 'malformed window payload: envelope.t / envelope.v are not arrays')
export const MALFORMED_SPANS = new ApiError(0, 'malformed spans payload: annotations / detections are not arrays')

export function asApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e
  return new ApiError(0, e instanceof Error ? e.message : String(e))
}

/** Clamp a viewport to [0, dur] with the minimum span. */
export function clampView(v: [number, number], dur: number): [number, number] {
  const minSpan = Math.min(dur, MIN_SPAN_S)
  let span = v[1] - v[0]
  if (!(span > 0) || Number.isNaN(span)) span = minSpan
  span = Math.min(dur, Math.max(minSpan, span))
  let a = v[0]
  if (Number.isNaN(a)) a = 0
  a = Math.min(Math.max(0, a), Math.max(0, dur - span))
  return [a, a + span]
}

/* ---- formatting (spec §0: time in hours since start, durations in s) ---- */
export const fmtInt = (n: number) => n.toLocaleString('en-US')
export const fmtSecs = (s: number) => `${+s.toFixed(1)} s`
export const fmtMs = (ms: number) => (ms < 10 ? `${ms.toFixed(1)} ms` : `${Math.round(ms)} ms`)

/** "276.4 – 278.4 h" with enough decimals to tell the two ends apart. */
export function fmtRangeH(a: number, b: number): string {
  const spanH = (b - a) / 3600
  const d = spanH >= 1 ? 1 : spanH >= 0.1 ? 2 : spanH >= 0.01 ? 3 : 4
  return `${(a / 3600).toFixed(d)} – ${(b / 3600).toFixed(d)} h`
}

/** Absolute-hour ticks for a full-recording axis: "0 h 120 h … 721 h" (frame explore-1/2). */
const H_STEPS = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 12, 24, 48, 60, 120, 240, 480, 960]
export function hourTicks(durH: number, maxTicks = 7): { h: number; label: string }[] {
  const step = H_STEPS.find(s => durH / s <= maxTicks) ?? H_STEPS[H_STEPS.length - 1]
  const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2
  const out: { h: number; label: string }[] = []
  for (let h = 0; h <= durH - step * 0.15; h += step) out.push({ h, label: `${h.toFixed(digits)} h` })
  const endLabel = Number.isInteger(durH) ? `${durH} h` : durH >= 10 ? `${Math.round(durH)} h` : `${durH.toFixed(2)} h`
  out.push({ h: durH, label: endLabel })
  return out
}

/** Ticks in hours across a viewport [t0,t1] s with adaptive decimals (tier 2 axis). */
export function viewportHourTicks(t0: number, t1: number, n = 6): { t: number; label: string }[] {
  const h0 = t0 / 3600, h1 = t1 / 3600
  const raw = (h1 - h0) / n
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const norm = raw / mag
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag
  const digits = Math.max(0, Math.min(6, -Math.floor(Math.log10(step))))
  const out: { t: number; label: string }[] = []
  for (let h = Math.ceil(h0 / step) * step; h <= h1 + 1e-9; h += step) out.push({ t: h * 3600, label: `${h.toFixed(digits)} h` })
  return out
}

/** Ticks relative to a motif onset: "−10 s 0 s +10 s" (tier 3 axis). */
const S_STEPS = [0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600]
export function relativeTicks(t0: number, t1: number, onset: number, maxTicks = 8): { t: number; label: string }[] {
  const span = t1 - t0
  const step = S_STEPS.find(s => span / s <= maxTicks) ?? S_STEPS[S_STEPS.length - 1]
  const out: { t: number; label: string }[] = []
  for (let k = Math.ceil((t0 - onset) / step); k * step + onset <= t1 + 1e-9; k++) {
    const rel = k * step
    out.push({ t: onset + rel, label: rel === 0 ? '0 s' : rel < 0 ? `−${+Math.abs(rel).toFixed(1)} s` : `+${+rel.toFixed(1)} s` })
  }
  return out
}

/* ---- motifs: annotations + detections as one list ---- */
export interface Motif {
  key: string; kind: 'annotated' | 'detected'; id: number; start_s: number; end_s: number
  verdict?: string; tag?: string | null; note?: string | null; source?: string; run_id?: number; score?: number | null
}
export function toMotifs(s: Spans): Motif[] {
  const out: Motif[] = []
  for (const a of s.annotations) out.push({ key: `a:${a.id}`, kind: 'annotated', id: a.id, start_s: a.start_s, end_s: a.end_s, verdict: a.verdict, tag: a.tag, note: a.note, source: a.source })
  for (const d of s.detections) out.push({ key: `d:${d.id}`, kind: 'detected', id: d.id, start_s: d.start_s, end_s: d.end_s, run_id: d.run_id, score: d.score })
  out.sort((p, q) => p.start_s - q.start_s || p.end_s - q.end_s || p.id - q.id)
  return out
}

/** min/max of an envelope, ignoring nulls; null when nothing finite. */
export function vRange(v: (number | null)[]): [number, number] | null {
  let lo = Infinity, hi = -Infinity
  for (const x of v) { if (x === null || x === undefined || Number.isNaN(x)) continue; if (x < lo) lo = x; if (x > hi) hi = x }
  return lo <= hi ? [lo, hi] : null
}
