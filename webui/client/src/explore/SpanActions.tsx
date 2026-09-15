/* Span-action row (frame explore-2): the selected span with tags + note, Save span (client-side
   stub, says so), Send span to Analyse, Take span for Review (inert). Verdicts are never given here. */
import { useState } from 'react'
import { useToast } from '../shell/Toast'
import { fmtDuration } from '../state'
import { fmtRangeH } from './util'

export function SpanActions({ view, nInView, onSend }: { view: [number, number]; nInView: number; onSend: () => void }) {
  const toast = useToast()
  const [tags, setTags] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState('')
  const commit = () => { const t = draft.trim(); if (t && !tags.includes(t)) setTags([...tags, t]); setDraft(''); setAdding(false) }
  return (
    <div className="card ex-span-act" data-testid="span-actions">
      <div>
        <div className="line mono" style={{ fontSize: 11.5, color: 'var(--muted)' }}>
          <span>Selected span</span>
          <span style={{ color: 'var(--text-2)' }} data-testid="span-action-range">{fmtRangeH(view[0], view[1])} · {fmtDuration(view[1] - view[0])} · {nInView} motif{nInView === 1 ? '' : 's'} in view</span>
        </div>
        <div className="line">
          <span className="k">tags</span>
          {tags.map(t => <span key={t} className="ex-tag" data-testid="span-tag">{t}<button onClick={() => setTags(tags.filter(x => x !== t))} title="remove">×</button></span>)}
          {adding
            ? <input className="input" autoFocus style={{ height: 22, width: 120 }} value={draft} onChange={e => setDraft(e.target.value)} onBlur={commit} onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { setDraft(''); setAdding(false) } }} data-testid="tag-input" />
            : <button className="ex-tag add" onClick={() => setAdding(true)} data-testid="add-tag">+ tag</button>}
        </div>
        <div className="line">
          <span className="k">note</span>
          <input className="input ex-note" placeholder="what you saw — kept with the span, never a verdict" value={note} onChange={e => setNote(e.target.value)} data-testid="span-note" />
        </div>
      </div>
      <div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn" onClick={() => toast.push({ text: 'saved tags and note only (stub — nothing written)' })} data-testid="save-span">Save span</button>
          <button className="btn" onClick={onSend} data-testid="send-span">Send span to Analyse →</button>
          <button className="btn primary inert" title="Review is out of slice scope" aria-disabled>Take span for Review →</button>
        </div>
        <div className="caption" style={{ textAlign: 'right' }}>saving stores tags and note only · verdicts are given in Review</div>
      </div>
    </div>
  )
}
