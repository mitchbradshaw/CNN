/* Algorithm glyphs (spec §6.8): a static thumbnail of *the algorithm*, keyed on the
   type signature. Colour key: grey input/context · blue what the block emits · green
   found/kept · amber cut/threshold · red discord/excluded · purple exemplar/second input.
   Drawn in a 44 × 26 box; 44×26 on cards, 272×96 in the detail panel. */
import type { ReactElement } from 'react'
import type { AdapterCard, TypeKind } from '../api'

const G = '#9ca3af', B = '#0a84ff', GR = '#22a06b', AM = '#e8900c', RD = '#e5484d', PU = '#8e5cf7', BL = '#bfdcff'

function wave(y: number, amp: number, stroke: string, w = 1.2, x0 = 2, x1 = 42) {
  const pts: string[] = []
  for (let x = x0; x <= x1; x += 2) pts.push(`${x},${(y + Math.sin(x / 3.1) * amp + Math.sin(x / 1.3) * amp * 0.35).toFixed(1)}`)
  return <polyline points={pts.join(' ')} fill="none" stroke={stroke} strokeWidth={w} strokeLinejoin="round" />
}
function smooth(y: number, amp: number, stroke: string, w = 1.4) {
  const pts: string[] = []
  for (let x = 2; x <= 42; x += 2) pts.push(`${x},${(y + Math.sin(x / 3.1) * amp).toFixed(1)}`)
  return <polyline points={pts.join(' ')} fill="none" stroke={stroke} strokeWidth={w} strokeLinejoin="round" />
}
function blocks(y: number, h: number, colours: string[], x0 = 2, w = 4.6, gap = 0.6) {
  return <g>{colours.map((c, i) => <rect key={i} x={x0 + i * (w + gap)} y={y} width={w} height={h} fill={c} rx={0.6} />)}</g>
}

const BY_SIG: Record<string, () => ReactElement> = {
  'signal→signal': () => <g>{wave(13, 6, G)}{smooth(13, 4, B)}</g>,
  'signal→scores': () => <g>{wave(7, 3, G, 1)}<polyline points="2,19 6,18 10,19 14,17 18,19 22,18 26,8 30,18 34,19 38,17 42,19" fill="none" stroke={B} strokeWidth={1.3} /><circle cx={26} cy={8} r={1.6} fill={RD} /></g>,
  'scores→spanset': () => <g><polyline points="2,19 6,18 10,17 13,8 16,18 20,19 24,17 27,7 30,18 34,19 38,18 42,19" fill="none" stroke={G} strokeWidth={1.2} /><line x1={2} x2={42} y1={12} y2={12} stroke={AM} strokeWidth={1} strokeDasharray="2 1.5" /><rect x={11} y={3} width={5} height={6} fill={B} rx={0.6} /><rect x={25} y={3} width={5} height={6} fill={B} rx={0.6} /></g>,
  'signal→spanset': () => <g>{wave(13, 6, G)}<rect x={9} y={2} width={7} height={22} fill={B} opacity={0.35} /><rect x={28} y={2} width={6} height={22} fill={B} opacity={0.35} /></g>,
  'signal→encoding': () => <g>{wave(8, 3.5, G, 1)}{blocks(15, 8, [B, AM, G, B, B, AM, G, B])}</g>,
  'signal→windowset': () => <g>{wave(11, 5, G)}{[2, 10, 18, 26, 34].map(x => <rect key={x} x={x} y={19} width={7} height={5} fill={BL} stroke={B} strokeWidth={0.8} />)}</g>,
  'windowset→grouping': () => <g>{blocks(4, 7, [G, G, G, G, G, G, G, G])}{blocks(15, 7, [B, GR, B, AM, GR, B, AM, B])}</g>,
  'windowset→windowset': () => <g>{blocks(4, 7, [G, G, G, G, G, G, G, G])}{blocks(15, 7, [B, BL, B, B, BL, B, BL, B])}</g>,
  'windowset→encoding': () => <g>{blocks(3, 5, [G, G, G, G], 2, 8, 1)}{Array.from({ length: 4 }, (_, r) => Array.from({ length: 4 }, (_, c) => <rect key={`${r}-${c}`} x={22 + c * 5} y={4 + r * 5} width={4.4} height={4.4} fill={(r + c) % 3 === 0 ? B : (r + c) % 3 === 1 ? BL : '#5aa9ff'} />))}</g>,
  'grouping→model': () => <g><circle cx={7} cy={8} r={2.5} fill={B} /><circle cx={7} cy={18} r={2.5} fill={GR} /><circle cx={13} cy={13} r={2.5} fill={AM} /><path d="M17 13h6M23 13v-6h6M23 13v6h6" fill="none" stroke={G} strokeWidth={1} /><rect x={31} y={4} width={11} height={18} rx={2} fill={B} /></g>,
  'model→scores': () => <g><rect x={2} y={4} width={9} height={9} rx={1.5} fill={PU} />{blocks(16, 6, [G, G, G, G], 2, 4, 1)}<polyline points="15,20 19,19 23,20 27,10 31,19 35,20 39,18 42,20" fill="none" stroke={B} strokeWidth={1.3} /></g>,
  'spanset→spanset': () => <g><rect x={2} y={4} width={40} height={7} fill={G} opacity={0.4} /><rect x={6} y={15} width={9} height={7} fill={B} /><rect x={20} y={15} width={6} height={7} fill={B} /><rect x={31} y={15} width={9} height={7} fill={B} /></g>,
  'encoding→spanset': () => <g>{blocks(3, 6, [G, AM, G, G, AM, G, G, G])}<rect x={7} y={14} width={6} height={9} fill={B} opacity={0.5} /><rect x={22} y={14} width={6} height={9} fill={B} opacity={0.5} /></g>,
  'encoding→encoding': () => <g>{blocks(4, 7, [BL, BL, BL, BL], 2, 7, 1)}<path d="M20 13h5" stroke={G} strokeWidth={1.2} /><rect x={28} y={3} width={14} height={10} fill={B} rx={1} /></g>,
}

export function glyphKey(input: TypeKind, output: TypeKind) { return `${input}→${output}` }

export function Glyph({ adapter, width = 44, height = 26, className }: { adapter: Pick<AdapterCard, 'input_kind' | 'output_kind'>; width?: number; height?: number; className?: string }) {
  const draw = BY_SIG[glyphKey(adapter.input_kind, adapter.output_kind)]
  return (
    <svg width={width} height={height} viewBox="0 0 44 26" className={className} aria-hidden="true" style={{ flex: 'none' }}>
      <rect x={0.5} y={0.5} width={43} height={25} rx={3} fill="#fff" stroke="#e5e7eb" />
      {draw ? draw() : <g><rect x={3} y={8} width={12} height={10} rx={1.5} fill={G} /><path d="M18 13h7" stroke={G} strokeWidth={1.2} /><rect x={28} y={8} width={12} height={10} rx={1.5} fill={B} /></g>}
    </svg>
  )
}
