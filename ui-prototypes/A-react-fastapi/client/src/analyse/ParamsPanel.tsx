/* Parameter controls generated from AdapterCard.params (spec §6.8): segmented for ≤4
   choices, select for more, range + number for bounded numerics, checkbox for bools,
   text otherwise. "= recommended" marks a value equal to the adapter default; the
   description sits behind an info icon (P9). */
import type { AdapterCard, ParamSpec } from '../api'

export interface ParamsPanelProps {
  adapter: AdapterCard
  params: Record<string, unknown>
  onChange: (name: string, value: unknown) => void
  disabled?: boolean
}

const eq = (a: unknown, b: unknown) => a === b || (typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-9) || String(a) === String(b)

function niceStep(spec: ParamSpec): number {
  if (spec.type === 'int') return 1
  if (spec.min !== null && spec.max !== null) { const r = spec.max - spec.min; const raw = r / 200; const p = Math.pow(10, Math.floor(Math.log10(raw))); return +(Math.ceil(raw / p) * p).toPrecision(2) }
  return 0.1
}

export function fmtParam(v: unknown): string {
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(+v.toPrecision(4))
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return v === '' ? '—' : String(v)
}

export function ParamsPanel({ adapter, params, onChange, disabled }: ParamsPanelProps) {
  return (
    <div className="pp-grid">
      {adapter.params.map(spec => {
        const value = params[spec.name] ?? spec.default
        const rec = eq(value, spec.default)
        const numeric = spec.type === 'int' || spec.type === 'float'
        const bounded = numeric && spec.min !== null && spec.max !== null
        const wide = bounded || (spec.choices && spec.choices.length > 4) || spec.type === 'str'
        const testid = `param-${spec.name}`
        let ctl: React.ReactNode
        if (spec.choices && spec.choices.length) {
          ctl = spec.choices.length <= 4 ? (
            <div className="seg" data-testid={testid}>
              {spec.choices.map(c => <button key={String(c)} className={eq(c, value) ? 'on' : ''} disabled={disabled} onClick={() => onChange(spec.name, c)}>{String(c)}</button>)}
            </div>
          ) : (
            <select className="input" data-testid={testid} value={String(value)} disabled={disabled} onChange={e => { const c = spec.choices!.find(o => String(o) === e.target.value); onChange(spec.name, c ?? e.target.value) }}>
              {spec.choices.map(c => <option key={String(c)} value={String(c)}>{String(c)}</option>)}
            </select>
          )
        } else if (spec.type === 'bool') {
          ctl = <label className="checkbox"><input type="checkbox" data-testid={testid} checked={!!value} disabled={disabled} onChange={e => onChange(spec.name, e.target.checked)} /> {value ? 'on' : 'off'}</label>
        } else if (numeric) {
          const step = niceStep(spec)
          const num = typeof value === 'number' ? value : Number(value)
          ctl = (
            <>
              {bounded && <input type="range" min={spec.min!} max={spec.max!} step={step} value={num} disabled={disabled} onChange={e => onChange(spec.name, spec.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value))} />}
              <input type="number" className="input" data-testid={testid} min={spec.min ?? undefined} max={spec.max ?? undefined} step={step} value={Number.isFinite(num) ? num : ''} disabled={disabled}
                onChange={e => { const v = spec.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value); if (Number.isFinite(v)) onChange(spec.name, v) }} />
            </>
          )
        } else {
          ctl = <input type="text" className="input" data-testid={testid} value={String(value ?? '')} disabled={disabled} onChange={e => onChange(spec.name, e.target.value)} />
        }
        return (
          <div className={`pp-row${wide ? ' wide' : ''}`} key={spec.name}>
            <div className="pp-lab">
              <span>{spec.name}</span>
              <span className="info" title={spec.description || 'no description registered'}>i</span>
              {numeric && <span className="val">{fmtParam(value)}</span>}
            </div>
            <div className="pp-ctl">{ctl}</div>
            <div className={`pp-rec${rec ? '' : ' no'}`}>{rec ? '= recommended' : `default ${fmtParam(spec.default)}`}</div>
          </div>
        )
      })}
      {!adapter.params.length && <div className="muted mono small">this block has no parameters</div>}
    </div>
  )
}
