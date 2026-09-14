/* COVERAGE MAP body (frame explore-1): one row per channel, one rounded cell per time bin,
   colour = 5-step blue ramp of count / max over the drawn matrix. The selected row gets a blue
   outline and a blue label. Hovering a cell shows "CH4_A2 · 341–354 h · 12 annotations". */
import { useState } from 'react'
import type { Coverage } from '../api'
import { useSize } from '../charts/useSize'
import { hourTicks, RAMP, rampIndex, type ColourBy } from './util'

const LABEL_W = 64, ROW_H = 34, CELL_PAD = 3, AXIS_H = 22, RIGHT_PAD = 6

export function Heatmap({ cov, matrix, unit, selectedId, onSelect }:
  { cov: Coverage; matrix: ColourBy | null; unit: string; selectedId: number | null; onSelect: (id: number) => void }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)
  const W = Math.max(0, size.width)
  const plotW = Math.max(1, W - LABEL_W - RIGHT_PAD)
  const bins = cov.bins
  const cellW = plotW / bins
  const rows = cov.rows
  const H = rows.length * ROW_H + AXIS_H
  let max = 0
  if (matrix) for (const r of rows) for (const c of r[matrix]) if (c > max) max = c
  const edge = (i: number) => {
    const e = cov.bin_edges_h[i] ?? (i * cov.bin_h)
    return cov.bin_h >= 1 ? String(Math.round(e)) : e.toFixed(2)
  }

  return (
    <div className="ex-heat" ref={ref}>
      {W > 0 && (
        <svg width={W} height={H} data-testid="corpus-heatmap" data-matrix={matrix ?? 'none'} data-max={max}>
          {rows.map((r, ri) => {
            const vals = matrix ? r[matrix] : null
            const sel = r.id === selectedId
            const y = ri * ROW_H
            return (
              <g key={r.id} data-testid={`heatmap-row-${r.name}`} data-selected={sel ? '1' : '0'} onClick={() => onSelect(r.id)} style={{ cursor: 'pointer' }}>
                <rect x={0} y={y} width={W} height={ROW_H} fill="transparent" />
                <text x={LABEL_W - 10} y={y + ROW_H / 2 + 3.5} textAnchor="end" style={{ fill: sel ? 'var(--blue)' : 'var(--muted)', fontWeight: sel ? 600 : 400 }}>{r.name}</text>
                {Array.from({ length: bins }, (_, bi) => {
                  const c = vals ? (vals[bi] ?? 0) : 0
                  const lvl = rampIndex(c, max)
                  const cx = LABEL_W + bi * cellW
                  return (
                    <rect key={bi} data-testid="heatmap-cell" data-count={c} data-level={lvl}
                      x={cx + 0.5} y={y + CELL_PAD} width={Math.max(0.5, cellW - 1)} height={ROW_H - 2 * CELL_PAD} rx={2} fill={RAMP[lvl]}
                      onPointerEnter={() => setTip({ x: cx + cellW / 2, y: y + CELL_PAD, text: `${r.name} · ${edge(bi)}–${edge(bi + 1)} h · ${c} ${unit}` })}
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
