/* Real-mV y labels for the signal tiers. Rendering is the shared charts/primitives YLabels (which
   now has adaptive digits, a white halo and pointer-events none, so labels never swallow band
   clicks); this wrapper only chooses WHICH values to print (top / zero-or-mid / bottom) and how many
   decimals (mvDigits: a 60 s viewport whose range is 0.0005 mV still shows three different numbers).
   `dim` greys the labels while a viewport fetch is in flight (critique r1: stale labels read as live). */
import { YLabels } from '../charts/primitives'
import type { XScale } from '../charts/scale'
import { mvDigits } from './util'

export function MvLabels({ y, lo, hi, x = 4, dim = false }: { y: XScale; lo: number; hi: number; x?: number; dim?: boolean }) {
  const d = mvDigits(lo, hi)
  const values = Array.from(new Set(lo < 0 && hi > 0 ? [hi, 0, lo] : [hi, (lo + hi) / 2, lo]))
  return (
    <g data-testid="mv-labels" data-digits={d} data-dim={dim ? '1' : '0'} pointerEvents="none" opacity={dim ? 0.4 : 1}>
      <YLabels y={y} values={values} x={x} unit="mV" digits={d} />
    </g>
  )
}
