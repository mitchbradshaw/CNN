/* Toolbar pieces shared by the chain page and the block page: name chip, source chip,
   estimate chip, the example span, and the source-envelope hook. */
import { useEffect, useState, type ReactNode } from 'react'
import { ApiError, getWindow, type WindowData } from '../api'
import { fmtHours, type ChainDraft, type SourceSpan } from '../state'

export const EXAMPLE_SOURCE: SourceSpan = { recording_id: 4, channel_name: 'CH4_A2', source_file: 'M2_aug_concat_fs1.mat', fs: 1, start_idx: 995040, end_idx: 1002240, label: 'example span' }

export const t0Of = (s: SourceSpan) => s.start_idx / s.fs
export const t1Of = (s: SourceSpan) => s.end_idx / s.fs
export const sourceLabel = (s: SourceSpan) => `Signal span · ${s.channel_name} · ${(t0Of(s) / 3600).toFixed(2)}–${fmtHours(t1Of(s))}`

export function NameChip({ chain, onRename, extra }: { chain: ChainDraft; onRename: (name: string) => void; extra?: ReactNode }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(chain.name)
  useEffect(() => { setDraft(chain.name) }, [chain.name])
  return (
    <span className="an-name" data-testid="chain-name" onClick={() => !editing && setEditing(true)} title="click to rename">
      {editing ? <input autoFocus value={draft} onChange={e => setDraft(e.target.value)} onBlur={() => { setEditing(false); if (draft.trim() && draft !== chain.name) onRename(draft.trim()) }} onKeyDown={e => { if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur(); if (e.key === 'Escape') { setDraft(chain.name); setEditing(false) } }} />
        : <span>{chain.name}</span>}
      {extra}
      <span className="state">{chain.saved ? 'saved' : 'unsaved'}</span>
    </span>
  )
}

export function SourceChip({ source, onClick }: { source: SourceSpan | null; onClick?: () => void }) {
  return (
    <button className="an-source" onClick={onClick} data-testid="source-chip" title={source ? `${source.source_file} · recording ${source.recording_id} · samples ${source.start_idx}–${source.end_idx} · ${source.fs} Hz` : 'no source yet'}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 12h3l2-7 3 14 3-10 2 6 2-3h3" /></svg>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{source ? sourceLabel(source) : 'no source · send a span from Explore'}</span>{onClick && <span style={{ fontSize: 10, flex: 'none' }}>▾</span>}
    </button>
  )
}

export function EstimateChip({ text, kind }: { text: string; kind: 'amber' | 'blue' | 'red' | 'green' }) {
  return <span className={`an-est ${kind}`} data-testid="estimate-chip">{text}</span>
}

export function SurrogateToggle() {
  return (
    <span className="an-toggle-wrap" title="null runs are out of slice scope">
      <span className="toggle on" style={{ opacity: 0.7 }}><span className="knob" /> surrogate 200×</span>
    </span>
  )
}

/** The source row's envelope from GET /api/channels/{id}/window (decimated to ≤ 2·px points). */
export function useSourceEnvelope(source: SourceSpan | null, px = 1200): { env: WindowData | null; error: string | null; status: number | null } {
  const [env, setEnv] = useState<WindowData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<number | null>(null)
  const key = source ? `${source.recording_id}:${source.start_idx}:${source.end_idx}` : ''
  useEffect(() => {
    if (!source) { setEnv(null); setStatus(null); return }
    let alive = true
    setError(null); setStatus(null); setEnv(null)
    getWindow(source.recording_id, t0Of(source), t1Of(source), px).then(w => { if (alive) { setEnv(w); setStatus(200) } })
      .catch(e => { if (alive) { setStatus(e instanceof ApiError ? e.status : 0); setError(e instanceof ApiError ? `${e.status === 423 ? 'held out · ' : ''}${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) } })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, px])
  return { env, error, status }
}
