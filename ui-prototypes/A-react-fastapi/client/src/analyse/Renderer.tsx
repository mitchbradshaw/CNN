/* THE single client-side dispatch seam: renderByType(payload, ctx) → ReactNode, keyed on
   payload.type (+ encoding.kind). Every time-aligned renderer draws against the caller's
   xScale so all rows on a chain page share one time axis. Nothing is normalised: signal
   rows carry a real mV axis; the ghosted input is drawn on its own scale (grey) because a
   raw channel sits on a DC offset the detrended output has removed. */
import { useEffect, useRef } from 'react'
import type {
  EncodingImagePayload, EncodingSymbolicPayload, EnvelopeSeries, ErrorPayload, GroupingPayload, ModelPayload, Payload,
  ScoresPayload, SignalPayload, SpansetPayload, WindowsetPayload,
} from '../api'
import { EnvelopePath, SpanBands, YLabels } from '../charts/primitives'
import { makeY, type XScale } from '../charts/scale'

export interface RenderCtx {
  x: XScale; width: number; height: number
  ghost?: EnvelopeSeries | null      // the nearest upstream signal, drawn behind in grey
  t0: number; t1: number
  throwForTest?: boolean             // ?throw=1: prove the ErrorBoundary catches a renderer throw
}

export const CAT9 = ['#0a84ff', '#22a06b', '#e8900c', '#8e5cf7', '#e5484d', '#0891b2', '#7c3aed', '#65a30d', '#db2777']
/** alphabet 3 = down / same / up → amber / grey / blue */
export const SYM3 = ['#e8900c', '#c7cbd1', '#0a84ff']

export function renderByType(payload: Payload, ctx: RenderCtx): React.ReactNode {
  if (ctx.throwForTest) throw new Error('deliberate render failure (?throw=1)')
  if ('error' in payload && payload.error) return <ErrorR p={payload as ErrorPayload} />
  switch (payload.type) {
    case 'signal': return <SignalR p={payload as SignalPayload} ctx={ctx} />
    case 'scores': return <ScoresR p={payload as ScoresPayload} ctx={ctx} />
    case 'spanset': return <SpansetR p={payload as SpansetPayload} ctx={ctx} />
    case 'encoding': return (payload as EncodingSymbolicPayload | EncodingImagePayload).kind === 'symbolic'
      ? <SymbolicR p={payload as EncodingSymbolicPayload} ctx={ctx} /> : <ImageR p={payload as EncodingImagePayload} ctx={ctx} />
    case 'windowset': return <WindowsetR p={payload as WindowsetPayload} ctx={ctx} />
    case 'grouping': return <GroupingR p={payload as GroupingPayload} ctx={ctx} />
    case 'model': return <ModelR p={payload as ModelPayload} />
    default: return <ErrorR p={{ type: payload.type, error: `no renderer for payload type "${payload.type}"`, summary: '' }} />
  }
}

/* ---------- helpers ---------- */
function finiteRange(v: (number | null)[]): [number, number] | null {
  let lo = Infinity, hi = -Infinity
  for (const x of v) if (x !== null && Number.isFinite(x)) { if (x < lo) lo = x; if (x > hi) hi = x }
  return lo <= hi ? [lo, hi] : null
}
export function GhostPath({ ghost, x, height, opacity = 1 }: { ghost: EnvelopeSeries | null | undefined; x: XScale; height: number; opacity?: number }) {
  if (!ghost || !ghost.t.length) return null
  const r = finiteRange(ghost.v) ?? [0, 1]
  const y = makeY(r[0], r[1], height)
  return <EnvelopePath t={ghost.t} v={ghost.v} x={x} y={y} stroke="var(--trace-ghost)" opacity={opacity} testid="ghost" />
}
const Empty = ({ text }: { text: string }) => <div className="an-plot-empty">{text}</div>

/* ---------- signal ---------- */
function SignalR({ p, ctx }: { p: SignalPayload; ctx: RenderCtx }) {
  const r = p.y_range ?? finiteRange(p.envelope.v) ?? [-1, 1]
  const y = makeY(r[0], r[1], ctx.height)
  const mid = r[0] < 0 && r[1] > 0 ? 0 : (r[0] + r[1]) / 2
  return (
    <svg width={ctx.width} height={ctx.height} data-render="signal">
      <GhostPath ghost={ctx.ghost} x={ctx.x} height={ctx.height} />
      <EnvelopePath t={p.envelope.t} v={p.envelope.v} x={ctx.x} y={y} stroke="var(--trace-blue)" testid="signal-path" />
      <YLabels y={y} values={[r[1], mid, r[0]]} unit="mV" />
      {ctx.ghost && <text x={ctx.width - 6} y={ctx.height - 5} textAnchor="end" fill="var(--muted-2)">input ghosted · own scale</text>}
    </svg>
  )
}

/* ---------- scores ---------- */
export function motifLabels(p: ScoresPayload): { t_s: number; v: number; label: string; kind: 'motif' | 'discord' }[] {
  const out: { t_s: number; v: number; label: string; kind: 'motif' | 'discord' }[] = []
  const low = p.top?.low ?? []
  const pair = low.length >= 2 && Math.abs(low[0].v - low[1].v) < 1e-6   // a motif pair has equal profile values at both ends
  low.forEach((m, i) => out.push({ ...m, kind: 'motif', label: pair ? (i === 0 ? 'M1a' : i === 1 ? 'M1b' : `M${i}`) : `M${i + 1}` }))
  ;(p.top?.high ?? []).forEach((d, i) => out.push({ ...d, kind: 'discord', label: `D${i + 1}` }))
  return out
}
function ScoresR({ p, ctx }: { p: ScoresPayload; ctx: RenderCtx }) {
  const r = p.value_range ?? finiteRange(p.envelope.v)
  if (!r) return <Empty text="no finite scores" />
  const y = makeY(Math.min(0, r[0]), r[1], ctx.height, 14, 4)
  const marks = motifLabels(p)
  return (
    <svg width={ctx.width} height={ctx.height} data-render="scores">
      <EnvelopePath t={p.envelope.t} v={p.envelope.v} x={ctx.x} y={y} stroke="var(--blue)" testid="scores-path" />
      {marks.map(m => {
        const px = ctx.x(m.t_s); const c = m.kind === 'motif' ? 'var(--green)' : 'var(--red)'
        return (
          <g key={m.label} data-testid={`mark-${m.label}`}>
            <line x1={px} x2={px} y1={12} y2={ctx.height} stroke={c} strokeOpacity={0.6} />
            <rect x={px - 12} y={1} width={24} height={11} rx={2} fill={c} />
            <text x={px} y={9.5} textAnchor="middle" fill="#fff" style={{ fontSize: 8.5, fontWeight: 600 }}>{m.label}</text>
          </g>
        )
      })}
      <YLabels y={y} values={[r[1], r[0]]} />
      <text x={4} y={ctx.height - 4} fill="var(--muted-2)">z-norm distance{p.nan_tail ? ` · NaN tail ${p.nan_tail}` : ''}</text>
      <g transform={`translate(${ctx.width - 6},${ctx.height - 5})`}>
        <text textAnchor="end" fill="var(--muted)"><tspan fill="var(--blue)">━</tspan> profile   <tspan fill="var(--green)">●</tspan> motif   <tspan fill="var(--red)">●</tspan> discord</text>
      </g>
    </svg>
  )
}

/* ---------- spanset ---------- */
function SpansetR({ p, ctx }: { p: SpansetPayload; ctx: RenderCtx }) {
  const spans = p.start_s.map((s, i) => ({ start_s: s, end_s: p.end_s[i], kind: 'detected' as const, id: i, title: `${(p.end_s[i] - s).toFixed(1)} s${p.scores?.[i] != null ? ` · score ${p.scores[i]!.toFixed(2)}` : ''}${p.labels?.[i] ? ` · ${p.labels[i]}` : ''}` }))
  return (
    <>
      <svg width={ctx.width} height={ctx.height} data-render="spanset">
        <GhostPath ghost={ctx.ghost} x={ctx.x} height={ctx.height} />
        <SpanBands spans={spans} x={ctx.x} height={ctx.height} capY={0} capH={3} minPx={2} />
        <text x={ctx.width - 6} y={ctx.height - 5} textAnchor="end" fill="var(--muted-2)">{p.n} span{p.n === 1 ? '' : 's'}{p.capped ? ' · capped' : ''}</text>
      </svg>
      {p.n === 0 && <Empty text="0 spans — nothing crossed the threshold" />}
    </>
  )
}

/* ---------- encoding · symbolic ---------- */
function SymbolicR({ p, ctx }: { p: EncodingSymbolicPayload; ctx: RenderCtx }) {
  const n = p.symbols.length
  if (!n) return <Empty text="no symbols" />
  const sps = p.seconds_per_symbol ?? (ctx.t1 - ctx.t0) / Math.max(1, p.n_symbols)
  const cell = ctx.x(ctx.t0 + sps) - ctx.x(ctx.t0)
  const colour = (s: number) => p.alphabet_size === 3 ? SYM3[s] ?? '#999' : CAT9[s % CAT9.length]
  const top = 4, h = ctx.height - 8
  return (
    <svg width={ctx.width} height={ctx.height} data-render="symbolic">
      {p.symbols.map((s, i) => {
        const x0 = ctx.x(p.t0_s + i * sps)
        if (x0 > ctx.width) return null
        return (
          <g key={i}>
            <rect x={x0} y={top} width={Math.max(1, cell - (cell > 3 ? 0.5 : 0))} height={h} fill={colour(s)} opacity={0.85}><title>{`symbol ${i} · ${p.letters[i] ?? s} · ${(p.t0_s + i * sps).toFixed(0)} s`}</title></rect>
            {cell >= 10 && <text x={x0 + cell / 2} y={top + h / 2 + 3.5} textAnchor="middle" fill="#fff" style={{ fontSize: 9 }}>{p.letters[i] ?? ''}</text>}
          </g>
        )
      })}
      <text x={ctx.width - 6} y={ctx.height - 5} textAnchor="end" fill="var(--muted)" style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3 }}>
        {p.alphabet_size === 3 ? 'amber down · grey same · blue up' : `alphabet ${p.alphabet_size} · categorical`}{p.capped ? ' · capped' : ''}
      </text>
    </svg>
  )
}

/* ---------- encoding · image ---------- */
const VIRIDIS: [number, number, number][] = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]]
function viridis(u: number): [number, number, number] {
  const k = Math.max(0, Math.min(0.9999, u)) * (VIRIDIS.length - 1); const i = Math.floor(k); const f = k - i
  const a = VIRIDIS[i], b = VIRIDIS[i + 1]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}
function ImageR({ p, ctx }: { p: EncodingImagePayload; ctx: RenderCtx }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const shape = p.display_shape
  useEffect(() => {
    const c = ref.current
    if (!c || !p.pixels_b64 || !shape) return
    const [h, w] = shape
    const raw = atob(p.pixels_b64)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
    const chans = p.channels ?? 1
    const img = new ImageData(w, h)
    for (let i = 0; i < w * h; i++) {
      let r: number, g: number, b: number
      if (chans === 3) { r = bytes[i * 3]; g = bytes[i * 3 + 1]; b = bytes[i * 3 + 2] }
      else { const u = bytes[i * chans] / 255; [r, g, b] = viridis(u) }
      img.data[i * 4] = r; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = b; img.data[i * 4 + 3] = 255
    }
    c.width = w; c.height = h
    c.getContext('2d')?.putImageData(img, 0, 0)
  }, [p.pixels_b64, shape, p.channels])
  if (p.ndim === 1 && p.series) {
    // a 1-D encoding (e.g. log-frequency bins): bars
    const r = finiteRange(p.series) ?? [0, 1]
    const bw = ctx.width / p.series.length
    return (
      <svg width={ctx.width} height={ctx.height} data-render="image-1d">
        {p.series.map((v, i) => { const hh = ((v - r[0]) / ((r[1] - r[0]) || 1)) * (ctx.height - 16); return <rect key={i} x={i * bw} y={ctx.height - 4 - hh} width={Math.max(1, bw - 0.5)} height={hh} fill="var(--blue)" /> })}
        <text x={4} y={11} fill="var(--muted)">{p.summary}</text>
      </svg>
    )
  }
  if (!p.pixels_b64 || !shape) return <Empty text={`encoding image · ${p.summary}`} />
  const side = ctx.height
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, height: ctx.height }} data-render="image">
      <canvas ref={ref} style={{ width: side * (shape[1] / shape[0]), height: side, imageRendering: 'pixelated', flex: 'none' }} />
      <div className="mono" style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
        <div>shape {p.shape.join('×')} · shown at {shape[0]}×{shape[1]}{p.channels && p.channels > 1 ? ` · ${p.channels} channels` : ''}</div>
        {p.value_range && <div>values {p.value_range[0].toFixed(3)} … {p.value_range[1].toFixed(3)} · viridis ramp</div>}
        <div>not time-aligned — both axes are time; the thumbnail keeps its aspect</div>
      </div>
    </div>
  )
}

/* ---------- windowset ---------- */
function WindowsetR({ p, ctx }: { p: WindowsetPayload; ctx: RenderCtx }) {
  const topH = p.features?.matrix ? 28 : ctx.height
  const rows = p.features?.matrix ? Math.min(12, p.features.n_columns) : 0
  const rowH = rows ? (ctx.height - topH - 2) / rows : 0
  const cellW = Math.max(1, ctx.x(ctx.t0 + p.length_s) - ctx.x(ctx.t0) - 0.5)
  const ranges = p.features?.col_range ?? []
  return (
    <svg width={ctx.width} height={ctx.height} data-render="windowset">
      <GhostPath ghost={ctx.ghost} x={ctx.x} height={topH} />
      {p.starts_s.map((s, i) => <line key={i} x1={ctx.x(s)} x2={ctx.x(s)} y1={0} y2={topH} stroke="var(--blue)" strokeOpacity={0.7} />)}
      {rows > 0 && p.features?.matrix && p.features.matrix.map((row, j) => {
        const x0 = ctx.x(p.starts_s[j])
        if (x0 === undefined || Number.isNaN(x0)) return null
        return row.slice(0, rows).map((v, k) => {
          if (v === null) return null
          const r = ranges[k]; const lo = r?.[0] ?? 0; const hi = r?.[1] ?? 1
          const u = hi > lo ? (v - lo) / (hi - lo) : 0.5
          return <rect key={`${j}-${k}`} x={x0} y={topH + 2 + k * rowH} width={cellW} height={Math.max(1, rowH - 0.5)} fill={`rgba(10,132,255,${0.08 + 0.85 * u})`}><title>{`${p.features!.columns[k]} = ${v}`}</title></rect>
        })
      })}
      <text x={ctx.width - 6} y={11} textAnchor="end" fill="var(--muted)" style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3 }}>
        {p.n_windows} windows · {p.length_s} s{p.features ? ` · ${rows} of ${p.features.n_columns} features shown` : ' · no features'}{p.capped ? ' · capped' : ''}
      </text>
    </svg>
  )
}

/* ---------- grouping ---------- */
function GroupingR({ p, ctx }: { p: GroupingPayload; ctx: RenderCtx }) {
  if (!p.strip) return <Empty text={`${p.summary} · no window strip to align (upstream WindowSet not seen)`} />
  const cellW = Math.max(1, ctx.x(ctx.t0 + p.strip.length_s) - ctx.x(ctx.t0) - 0.5)
  const top = 16, h = ctx.height - top - 4
  return (
    <svg width={ctx.width} height={ctx.height} data-render="grouping">
      {p.strip.starts_s.map((s, i) => {
        const lab = p.labels[i]; if (lab === undefined) return null
        return <rect key={i} x={ctx.x(s)} y={top} width={cellW} height={h} fill={CAT9[(lab - p.label_base + 9) % 9]} opacity={0.85}><title>{`window ${i} · cluster ${lab}`}</title></rect>
      })}
      <g>
        <text x={4} y={11} fill="var(--muted)">{p.k} clusters · sizes {p.clusters.map(c => c.count).join(', ')}{p.linkage ? ` · ${p.linkage}` : ''}</text>
        {p.clusters.map((c, i) => (
          <g key={c.id} transform={`translate(${ctx.width - 6 - (p.clusters.length - i) * 56},2)`}>
            <rect width={9} height={9} y={0.5} fill={CAT9[(c.id - p.label_base + 9) % 9]} rx={2} />
            <text x={13} y={9} fill="var(--muted)">{c.id} · {c.count}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}

/* ---------- model ---------- */
function ModelR({ p }: { p: ModelPayload }) {
  const c = p.card ?? {}
  const base = p.path.split(/[\\/]/).pop() ?? p.path
  const acc = typeof c.holdout_accuracy === 'number' ? (c.holdout_accuracy as number).toFixed(2) : '—'
  const hasCard = Object.keys(c).length > 0
  return (
    <div className="bp-model" style={{ padding: '6px 12px' }} data-render="model">
      <div><b>{base}</b> <span className="muted">· {p.exists ? `${((p.size_bytes ?? 0) / 1024).toFixed(0)} kB on disk` : 'file missing'}</span></div>
      {hasCard
        ? <div>holdout accuracy <b>{acc}</b> · classes {String(c.n_classes ?? '—')} · windows {String(c.n_windows ?? '—')} · features kept {String(c.n_features_kept ?? '—')} of {String(c.n_features_in ?? '—')} · train/holdout {String(c.n_train ?? '—')}/{String(c.n_holdout ?? '—')}</div>
        : <div className="muted" data-testid="model-no-meta">model metadata not served for this run · the card comes from the adapter's meta (kept in a sidecar since critique r1)</div>}
      <div className="muted" style={{ fontSize: 10.5 }}>a model has no natural plot · Models judges it against a label-shuffle null</div>
    </div>
  )
}

/* ---------- error ---------- */
function ErrorR({ p }: { p: ErrorPayload }) {
  return (
    <div className="error-card" style={{ padding: '8px 12px' }} data-testid="error-card">
      <h3>payload {p.type} could not be rendered</h3>
      <div className="mono" style={{ fontSize: 11.5 }}>{p.error}</div>
      {p.traceback && <pre>{p.traceback}</pre>}
    </div>
  )
}
