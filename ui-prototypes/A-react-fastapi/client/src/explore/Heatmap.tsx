/* COVERAGE MAP body (frame explore-1): one row per channel, one rounded cell per time bin,
   colour = 5-step blue ramp by QUANTILE RANK among the non-zero cells of the drawn matrix (critique
   r1: a linear count/max ramp went flat once one hot cell existed). The selected row gets a blue
   outline and a blue label. Hovering a cell shows "CH4_A2 · 341–354 h · 12 annotations". A row
   without its matrix array renders an ErrorCard instead of throwing. Rows are keyboard-selectable. */
import { useMemo, useState } from 'react'
import { ApiError, type Coverage } from '../api'
import { useSize } from '../charts/useSize'
import { ErrorCard } from './ErrorCard'
import { hourTicks, quantileRamp, RAMP, type ColourBy } from './util'

const LABEL_W = 64, ROW_H = 34, CELL_PAD = 3, AXIS_H = 22, RIGHT_PAD = 6

/** What "disagree" counts (server/corpus.py): printed in the tooltip, the caption and the bottom bar. */
export const DISAGREE_DEF = 'annotations with no overlapping detection + detections with no overlapping annotation'

export function Heatmap({ cov, matrix, unit, selectedId, onSelect }:
  { cov: Coverage; matrix: ColourBy | null; unit: string; selectedId: number | null; onSelect: (id: number) => void }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)
  const W = Math.max(0, size.width)
  const plotW = Math.max(1, W - LABEL_W - RIGHT_PAD)
  const bins = cov.bins
  const cellW = plotW / bins
  const rows = Array.isArray(cov.rows) ? cov.rows : null
  const bad = rows && matrix ? rows.find(r => !Array.isArray(r?.[matrix])) : undefined
  const { level, max } = useMemo(() => {
    const all: number[] = []
    if (rows && matrix && !bad) for (const r of rows) for (const c of r[matrix]) all.push(typeof c === 'number' ? c : 0)
    return { level: quantileRamp(all), max: all.reduce((m, v) => (v > m ? v : m), 0) }
  }, [rows, matrix, bad])
  if (!rows) return <ErrorCard error={new ApiError(0, 'malformed coverage payload: rows is not an array')} title="coverage map cannot be drawn" />
  if (bad) return <ErrorCard error={new ApiError(0, `malformed coverage payload: row ${String(bad?.name ?? '?')} has no ${matrix} array`)} title="coverage map cannot be drawn" />
  const H = rows.length * ROW_H + AXIS_H
  const edge = (i: number) => {
    const e = cov.bin_edges_h?.[i] ?? (i * cov.bin_h)
    return cov.bin_h >= 1 ? String(Math.round(e)) : e.toFixed(2)
  }

  return (
    <div className="ex-heat" ref={ref}>
      {W > 0 && (
        <svg width={W} height={H} data-testid="corpus-heatmap" data-matrix={matrix ?? 'none'} data-max={max} data-ramp="quantile">
          {rows.map((r, ri) => {
            const vals = matrix ? r[matrix] : null
            const sel = r.id === selectedId
            const y = ri * ROW_H
            // "disagree" is a comparison: with no detections (or no annotations) on the channel there is nothing to compare
            const nAnn = r.counts?.annotations ?? 0, nDet = r.counts?.detections ?? 0
            const degenerate = matrix === 'disagree' && !(nAnn > 0 && nDet > 0)
            const missing = nDet > 0 ? 'no annotations' : 'no detections'
            return (
              <g key={r.id} data-testid={`heatmap-row-${r.name}`} data-selected={sel ? '1' : '0'} onClick={() => onSelect(r.id)} style={{ cursor: 'pointer' }}
                tabIndex={0} role="button" aria-pressed={sel} aria-label={`channel ${r.name}`}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(r.id) } }}>
                <rect x={0} y={y} width={W} height={ROW_H} fill="transparent" />
                <text x={LABEL_W - 10} y={y + ROW_H / 2 + 3.5} textAnchor="end" style={{ fill: sel ? 'var(--blue)' : 'var(--muted)', fontWeight: sel ? 600 : 400 }}>{r.name}</text>
                {Array.from({ length: bins }, (_, bi) => {
                  const c = vals ? (Number(vals[bi]) || 0) : 0
                  const lvl = degenerate ? 0 : level(c)
                  const cx = LABEL_W + bi * cellW
                  const text = degenerate
                    ? `${r.name} · ${edge(bi)}–${edge(bi + 1)} h · disagree — (${missing} on this channel)`
                    : `${r.name} · ${edge(bi)}–${edge(bi + 1)} h · ${c} ${unit}${matrix === 'disagree' ? ' · unmatched annotations + unmatched detections' : ''}`
                  return (
                    <rect key={bi} data-testid="heatmap-cell" data-count={c} data-level={lvl}
                      x={cx + 0.5} y={y + CELL_PAD} width={Math.max(0.5, cellW - 1)} height={ROW_H - 2 * CELL_PAD} rx={2} fill={RAMP[lvl]}
                      onPointerEnter={() => setTip({ x: cx + cellW / 2, y: y + CELL_PAD, text })}
                      onPointerLeave={() => setTip(null)} />
                  )
                })}
                {sel && <rect x={LABEL_W - 1} y={y + 1} width={plotW + 2} height={ROW_H - 2} rx={4} fill="none" stroke="var(--blue)" strokeWidth={1.5} pointerEvents="none" data-testid="heatmap-selected-outline" />}
              </g>
            )
          })}
          <g className="time-axis" transform={`translate(0,${rows.length * ROW_H})`}>
            {hourTicks(cov.duration_h).map((k, i, arr) => {
              const x = LABEL_W + (cov.duration_h > 0 ? k.h / cov.duration_h : 0) * plotW
              return <text key={k.h} x={x} y={15} textAnchor={i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle'}>{k.label}</text>
            })}
          </g>
        </svg>
      )}
      {tip && <div className="ex-tip" style={{ left: tip.x, top: tip.y }} data-testid="heatmap-tooltip">{tip.text}</div>}
    </div>
  )
}
