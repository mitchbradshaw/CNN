/* Real-mV y labels with adaptive precision and a white halo, so a 60 s viewport whose range is
   0.0005 mV still shows three different numbers. (charts/primitives YLabels fixes 3 decimals —
   change request filed; this is the local stand-in.) */
import type { XScale } from '../charts/scale'
import { mvDigits } from './util'

export function MvLabels({ y, lo, hi, x = 4 }: { y: XScale; lo: number; hi: number; x?: number }) {
  const d = mvDigits(lo, hi)
  const values = lo < 0 && hi > 0 ? [hi, 0, lo] : [hi, (lo + hi) / 2, lo]
  return (
    <g data-testid="mv-labels" data-digits={d} pointerEvents="none">
      {values.map((v, i) => (
        <text key={i} x={x} y={y(v) + 3.5} style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3, strokeLinejoin: 'round', fill: 'var(--muted)' }}>
          {(v > 0 ? '+' : '') + v.toFixed(d)} mV
        </text>
      ))}
    </g>
  )
}
