/* Corpus right rail (frame explore-1): a filter/options list, not a legend. Show, Detections from,
   Verdict (colour dots + counts from the coverage payload), Morphology tag (honest zeros), and the
   "matching N spans / across K of M channels" readout. */
import type { Coverage } from '../api'
import { fmtInt, TAGS, VERDICT_COLOUR, VERDICTS } from './util'

export interface ShowState { annotations: boolean; detections: boolean }

function Info() { return <span className="i" title="what this section does">i</span> }

export function RightRail({ cov, show, setShow, verdicts, setVerdicts, matching }: {
  cov: Coverage | null
  show: ShowState; setShow: (s: ShowState) => void
  verdicts: string[]; setVerdicts: (v: string[]) => void
  matching: { spans: number; channels: number; total: number }
}) {
  const toggleVerdict = (v: string) => setVerdicts(verdicts.includes(v) ? verdicts.filter(x => x !== v) : VERDICTS.filter(x => x === v || verdicts.includes(x)))
  const counts = cov?.verdict_counts ?? {}
  return (
    <aside className="card ex-rail" data-testid="corpus-rail">
      <div className="sec">
        <h4>Show <Info /></h4>
        <label className="checkbox"><input type="checkbox" checked={show.annotations} onChange={e => setShow({ ...show, annotations: e.target.checked })} data-testid="show-annotations" /> annotations</label>
        <label className="checkbox"><input type="checkbox" checked={show.detections} onChange={e => setShow({ ...show, detections: e.target.checked })} data-testid="show-detections" /> detections</label>
        <label className="checkbox off inert" title="out of slice scope"><input type="checkbox" disabled /> reviewed coverage</label>
        <label className="checkbox off inert" title="out of slice scope"><input type="checkbox" disabled /> unreviewed only</label>
      </div>
      <div className="sec">
        <h4>Detections from <Info /></h4>
        <select className="input" value="all" onChange={() => {}} data-testid="det-runs">
          <option value="all">runs  all · {cov ? cov.n_detection_runs : '—'}</option>
        </select>
        <select className="input inert" value="any" onChange={() => {}} title="out of slice scope" data-testid="det-method">
          <option value="any">method  any</option>
        </select>
      </div>
      <div className="sec">
        <h4>Verdict <Info /></h4>
        {VERDICTS.map(v => {
          const on = verdicts.includes(v)
          return (
            <label key={v} className={`checkbox${on ? '' : ' off'}`}>
              <input type="checkbox" checked={on} onChange={() => toggleVerdict(v)} data-testid={`verdict-${v}`} />
              <span className="dot" style={{ background: VERDICT_COLOUR[v] }} /> {v}
              <span className="cnt">{cov ? fmtInt(counts[v] ?? 0) : '—'}</span>
            </label>
          )
        })}
      </div>
      <div className="sec">
        <h4>Morphology tag <Info /></h4>
        {TAGS.map(t => (
          <label key={t} className="checkbox off inert" title="no tags in this database">
            <input type="checkbox" disabled /> {t}<span className="cnt">0</span>
          </label>
        ))}
        <div className="muted small mono" style={{ marginTop: 4 }} data-testid="tags-caption">no tags in this database</div>
      </div>
      <div className="sec foot" data-testid="rail-matching">
        <div>
          <div>matching</div>
          <div>across {matching.channels} of {matching.total} channels</div>
        </div>
        <b>{fmtInt(matching.spans)} spans</b>
      </div>
    </aside>
  )
}
