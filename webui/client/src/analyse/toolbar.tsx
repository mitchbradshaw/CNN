/* Toolbar pieces shared by the chain page and the block page: name chip, source chip,
   estimate chip, the example span, and the source-envelope hook. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError, getWindow, type WindowData } from '../api'
import { useDismiss } from '../shell/useDismiss'
import { fmtHours, type ChainDraft, type SourceSpan } from '../state'
import { retryNow, type RunErrorKind } from './store'

export const EXAMPLE_SOURCE: SourceSpan = { recording_id: 4, channel_name: 'CH4_A2', source_file: 'M2_aug_concat_fs1.mat', fs: 1, start_idx: 995040, end_idx: 1002240, label: 'example span' }

/** The held-out recording (spec §0 D6, Working.config.HELD_OUT_RECORDING_FILE; /api/recordings marks it held_out).
 *  Its data is never requested — the pages show the locked card without asking the bridge (critique r1). */
export const HELD_OUT_FILE = 'M4_aug_concat_fs1.mat'
export const isHeldOut = (s: SourceSpan | null) => !!s && s.source_file === HELD_OUT_FILE

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

/** Null runs are not part of this slice: the toggle renders OFF and disabled so the default chain never claims
 *  a surrogate it does not run (critique r1 — the 200× was the placeholder canon value, not a live setting). */
export function SurrogateToggle() {
  return (
    <span className="an-toggle-wrap" title="surrogate null runs · out of slice scope" data-testid="surrogate-toggle">
      <button className="toggle" disabled aria-disabled="true" title="surrogate null runs · out of slice scope" style={{ border: 0, background: 'transparent', opacity: 0.6, cursor: 'not-allowed', padding: 0 }}><span className="knob" /> surrogate · not in this slice</button>
    </span>
  )
}

/** One card for the run store's error, titled by kind (critique r1: the re-attach title was used for every failure). */
export function RunErrorCard({ error, kind }: { error: string; kind: RunErrorKind | null }) {
  const title = kind === 'contact' ? 'lost contact with the bridge · retrying' : kind === 'stream' ? 'run stream interrupted · polling the bridge' : 'last run could not be re-attached'
  return (
    <div className="error-card" style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 12 }} data-testid="run-error-card" data-kind={kind ?? 'attach'}>
      <div style={{ minWidth: 0, flex: 1 }}><h3>{title}</h3><div className="mono small">{error}</div></div>
      {kind === 'contact' && <button className="btn" onClick={retryNow} data-testid="retry-contact">↻ Retry now</button>}
    </div>
  )
}

/** A popover anchor that closes on Escape and on a pointer-down outside it (shell/useDismiss). The toggle
 *  button lives inside the wrapper so its own click is never "outside". */
export function Popwrap({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null)
  useDismiss(ref, onClose, open)
  return <span className="an-popwrap" ref={ref}>{children}</span>
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
    if (isHeldOut(source)) { setStatus(423); setError(`held out · ${source.source_file} is refused by every workspace (D6) — no data request is made`); return }
    getWindow(source.recording_id, t0Of(source), t1Of(source), px).then(w => { if (alive) { setEnv(w); setStatus(200) } })
      .catch(e => { if (alive) { setStatus(e instanceof ApiError ? e.status : 0); setError(e instanceof ApiError ? `${e.status === 423 ? 'held out · ' : ''}${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) } })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, px])
  return { env, error, status }
}
