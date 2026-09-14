/* Four collapsed ribbon cards (frame explore-2 bottom; explore-2b for the open look):
   Filters & search · Annotations N · Detections N · Keyboard shortcuts. Opening Annotations or
   Detections lists the spans currently in view; the other two are out of slice scope and say so. */
import { useState } from 'react'
import type { Annotation, Detection } from '../api'
import { fmtInt, fmtSecs, VERDICT_COLOUR, type Motif } from './util'

type Key = 'filters' | 'annotations' | 'detections' | 'shortcuts'

export function Ribbons({ annotations, detections, totals, capped, selected, onSelect }: {
  annotations: Annotation[]; detections: Detection[]
  totals: { annotations: number; detections: number }; capped: { annotations: boolean; detections: boolean }
  selected: Motif | null; onSelect: (m: Motif) => void
}) {
  const [open, setOpen] = useState<Key | null>(null)
  const toggle = (k: Key) => setOpen(open === k ? null : k)
  const Row = ({ k, label, n }: { k: Key; label: string; n?: number }) => (
    <div className={`card ex-ribbon${open === k ? ' open' : ''}`} onClick={() => toggle(k)} data-testid={`ribbon-${k}`} role="button" aria-expanded={open === k}>
      <span className="chev">›</span><span>{label}</span>{n !== undefined && <span className="n">{fmtInt(n)}</span>}
    </div>
  )
  return (
    <>
      <div className="ex-ribbons">
        <Row k="filters" label="Filters & search" />
        <Row k="annotations" label="Annotations" n={totals.annotations} />
        <Row k="detections" label="Detections" n={totals.detections} />
        <Row k="shortcuts" label="Keyboard shortcuts" />
      </div>
      {open && (
        <div className="card card-pad" data-testid={`ribbon-body-${open}`}>
          {open === 'filters' && <div className="muted small mono">ten filter fields, match count, CSV/JSON export, bulk staging — the drawer (frame explore-2b) is out of slice scope</div>}
          {open === 'shortcuts' && <div className="muted small mono">keyboard shortcuts are out of slice scope · today: drag to pan, wheel to zoom, ‹ › for the motif list</div>}
          {open === 'annotations' && (
            <>
              <div className="muted small mono" style={{ marginBottom: 6 }}>{annotations.length} annotation{annotations.length === 1 ? '' : 's'} in view{capped.annotations ? ' (list capped by the server)' : ''} · of {fmtInt(totals.annotations)} on this channel</div>
              {annotations.length ? (
                <table className="ex-table"><thead><tr><th>id</th><th>start</th><th>duration</th><th>verdict</th><th>tags</th><th>source</th><th>note</th></tr></thead>
                  <tbody>{annotations.map(a => (
                    <tr key={a.id} className={selected?.key === `a:${a.id}` ? 'sel' : ''} onClick={() => onSelect({ key: `a:${a.id}`, kind: 'annotated', id: a.id, start_s: a.start_s, end_s: a.end_s, verdict: a.verdict, tag: a.tag, note: a.note, source: a.source })}>
                      <td>{fmtInt(a.id)}</td><td>{(a.start_s / 3600).toFixed(3)} h</td><td>{fmtSecs(a.end_s - a.start_s)}</td>
                      <td style={{ color: VERDICT_COLOUR[a.verdict] ?? 'inherit' }}>{a.verdict}</td><td>{a.tag ?? '—'}</td><td>{a.source}</td><td>{a.note ?? ''}</td>
                    </tr>))}</tbody></table>
              ) : <div className="muted small mono">none in this viewport</div>}
            </>
          )}
          {open === 'detections' && (
            <>
              <div className="muted small mono" style={{ marginBottom: 6 }}>{detections.length} detection{detections.length === 1 ? '' : 's'} in view{capped.detections ? ' (list capped by the server)' : ''} · of {fmtInt(totals.detections)} on this channel</div>
              {detections.length ? (
                <table className="ex-table"><thead><tr><th>id</th><th>start</th><th>duration</th><th>score</th><th>run</th></tr></thead>
                  <tbody>{detections.map(d => (
                    <tr key={d.id} className={selected?.key === `d:${d.id}` ? 'sel' : ''} onClick={() => onSelect({ key: `d:${d.id}`, kind: 'detected', id: d.id, start_s: d.start_s, end_s: d.end_s, run_id: d.run_id, score: d.score })}>
                      <td>{fmtInt(d.id)}</td><td>{(d.start_s / 3600).toFixed(3)} h</td><td>{fmtSecs(d.end_s - d.start_s)}</td><td>{d.score == null ? '—' : d.score.toFixed(3)}</td><td>{d.run_id}</td>
                    </tr>))}</tbody></table>
              ) : <div className="muted small mono">{totals.detections === 0 ? 'no detections on this channel' : 'none in this viewport'}</div>}
            </>
          )}
        </div>
      )}
    </>
  )
}
