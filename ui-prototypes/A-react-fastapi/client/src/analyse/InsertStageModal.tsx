/* Insert a stage (frame chain-2, spec §6.4): leads with the type contract as three pills,
   then a grid of every registered block — incompatible ones stay visible and disabled with
   their reason — and a detail panel for the selected block. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, compatibleAt, validateChain, validateParams, TYPE_LABEL, type AdapterCard, type Compatible, type Step } from '../api'
import { useDismiss } from '../shell/useDismiss'
import type { SourceSpan } from '../state'
import { Glyph } from './glyphs'
import { fmtParam } from './ParamsPanel'
import { pad2, type AdapterIndex } from './useAdapters'
import { spanOf } from './useValidation'

interface Props {
  steps: Step[]; position: number; adapters: AdapterIndex; source: SourceSpan | null
  onClose: () => void
  onInsert: (step: Step, openSettings: boolean) => void
}
const CATS = ['all', 'preprocess', 'encode', 'detect', 'cluster', 'model', 'control'] as const

export function InsertStageModal({ steps, position, adapters, source, onClose, onInsert }: Props) {
  const [compat, setCompat] = useState<Compatible | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [cat, setCat] = useState<(typeof CATS)[number]>('all')
  const [sortFits, setSortFits] = useState(true)
  const [showIncompat, setShowIncompat] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)
  const [estimates, setEstimates] = useState<Record<string, number | null>>({})
  const [busy, setBusy] = useState(false)
  // Escape closes (critique r1); the ref is the backdrop, which covers the viewport, so the pointer-outside
  // branch never fires — the backdrop's own onClick handles the click, without a click-through on close
  const backdrop = useRef<HTMLDivElement>(null)
  useDismiss(backdrop, onClose)

  useEffect(() => {
    let alive = true
    compatibleAt(steps, position).then(c => { if (alive) { setCompat(c); const first = c.rows.find(r => r.ok); if (first) setSelected(first.name) } })
      .catch(e => { if (alive) setErr(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)) })
    return () => { alive = false }
  }, [steps, position])

  const atEnd = position >= steps.length
  const prevStep = position > 0 ? steps[position - 1] : null
  const nextStep = atEnd ? null : steps[position]
  const prevName = prevStep ? `${pad2(position)} ${adapters.byName.get(`${prevStep.stage}.${prevStep.algorithm}`)?.page_name ?? prevStep.algorithm}` : 'Source'
  const nextName = nextStep ? `${pad2(position + 1)} ${adapters.byName.get(`${nextStep.stage}.${nextStep.algorithm}`)?.page_name ?? nextStep.algorithm}` : null
  const sel = selected ? adapters.byName.get(selected) ?? null : null
  const rowOf = useMemo(() => new Map((compat?.rows ?? []).map(r => [r.name, r])), [compat])

  // estimate for the selected card = validate the chain with it inserted (only meaningful with a source)
  useEffect(() => {
    if (!sel || !source || estimates[sel.name] !== undefined) return
    const trial = [...steps.slice(0, position), { stage: sel.stage, algorithm: sel.algorithm, params: {} }, ...steps.slice(position)]
    let alive = true
    validateChain(trial, source.recording_id, spanOf(source))
      .then(v => { if (alive) setEstimates(e => ({ ...e, [sel.name]: v.estimate ? v.estimate.per_step_s[position] ?? null : null })) })
      .catch(() => { if (alive) setEstimates(e => ({ ...e, [sel.name]: null })) })
    return () => { alive = false }
  }, [sel, source, steps, position, estimates])

  const cards = useMemo(() => {
    let list = adapters.list.filter(a => cat === 'all' || a.category === cat)
    if (q.trim()) { const s = q.trim().toLowerCase(); list = list.filter(a => a.page_name.toLowerCase().includes(s) || a.name.toLowerCase().includes(s) || a.signature.toLowerCase().includes(s) || a.description.toLowerCase().includes(s)) }
    const fits = list.filter(a => rowOf.get(a.name)?.ok)
    const nofit = list.filter(a => !rowOf.get(a.name)?.ok)
    return { fits, nofit: showIncompat ? nofit : [], all: sortFits ? [...fits, ...nofit] : list }
  }, [adapters.list, cat, q, rowOf, showIncompat, sortFits])

  const estText = (a: AdapterCard) => {
    const e = estimates[a.name]
    if (e !== undefined && e !== null) return `≈ ${e < 0.05 ? '<0.1' : e.toFixed(1)} s`
    return a.has_estimate ? 'est. on select' : 'est. at run'
  }
  const doInsert = async (open: boolean) => {
    if (!sel || busy) return
    setBusy(true)
    try {
      const { params } = await validateParams({ stage: sel.stage, algorithm: sel.algorithm, params: {} })
      onInsert({ stage: sel.stage, algorithm: sel.algorithm, params }, open)
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e))
    } finally { setBusy(false) }
  }

  const Card = ({ a }: { a: AdapterCard }) => {
    const row = rowOf.get(a.name)
    const ok = !!row?.ok
    return (
      <button className={`ins-card${ok ? '' : ' nofit'}${selected === a.name ? ' selected' : ''}`} onClick={() => ok && setSelected(a.name)} disabled={!ok} data-testid={`modal-card-${a.name}`} title={ok ? a.description : row?.reason}>
        <div className="hd"><Glyph adapter={a} /><div style={{ minWidth: 0 }}><div className="nm">{a.page_name}</div><div className="sg">{a.signature}</div></div></div>
        <div className="chips"><span>{estText(a)}</span><span className={a.input_kind === 'signal' ? 'g' : ''}>{a.input_kind === 'signal' ? 'has null' : 'no null'}</span>{a.side_inputs.length > 0 && <span className="purple" style={{ background: 'var(--purple-100)', color: '#6a3ecf' }}>needs {a.side_inputs.map(s => s.name).join(', ')}</span>}</div>
        <div className={`fit${ok ? '' : ' no'}`}>{ok ? '✓ fits here' : `⊘ ${row?.reason ?? 'not evaluated'}`}</div>
        {a.known_broken && <div className="broken" title={a.known_broken}>⚠ known broken · {a.known_broken}</div>}
      </button>
    )
  }

  return (
    <div className="modal-backdrop" onClick={onClose} ref={backdrop}>
      <div className="modal ins" onClick={e => e.stopPropagation()} data-testid="insert-modal" role="dialog" aria-modal="true" aria-labelledby="ins-title">
        <div className="ins-head">
          <h2 id="ins-title">＋ Insert a stage</h2>
          <span className="sub">{atEnd ? 'at the end of the chain' : `between ${prevName} and ${nextName}`}</span>
          <button className="icon-btn x" onClick={onClose} title="close (Esc)" aria-label="close">✕</button>
        </div>
        <div className="ins-ribbon">
          <span>chain</span>
          <span className="rc">● Source</span>
          {steps.map((s, i) => (
            <span key={i} style={{ display: 'contents' }}>
              {i === position && <><span>›</span><span className="rc new">+ new stage</span></>}
              <span>›</span><span className="rc">{pad2(i + 1)} {adapters.byName.get(`${s.stage}.${s.algorithm}`)?.page_name ?? s.algorithm}</span>
            </span>
          ))}
          {atEnd && <><span>›</span><span className="rc new">+ new stage</span></>}
          <span className="note">{atEnd ? 'inserting at the end changes the terminal type' : `inserting makes ${pad2(position + 1)} stale`}</span>
        </div>
        <div className="ins-pills">
          <span className="ins-pill">{prevName.split(' ')[0] === 'Source' ? 'Source' : pad2(position)} outputs <b>{compat?.producing_label ?? '…'}</b></span>
          <span className="arrow">→</span>
          <span className="ins-pill new">new stage accepts <b>{compat?.producing_label ?? '…'}</b> → emits <b>{sel ? TYPE_LABEL[sel.output_kind] : '?'}</b></span>
          {compat?.next_requires_label ? <><span className="arrow">→</span><span className="ins-pill">{pad2(position + 1)} requires <b>{compat.next_requires_label}</b></span></> : <><span className="arrow">→</span><span className="ins-pill" style={{ background: 'var(--grey-100)' }}>end of chain · terminal becomes <b>{sel ? TYPE_LABEL[sel.output_kind] : '?'}</b></span></>}
          <span className="count" data-testid="modal-fit-count">{compat ? `${compat.n_fit} of ${compat.n_total} blocks fit` : '…'}</span>
        </div>
        <div className="ins-controls">
          <input className="input" placeholder="search blocks" value={q} onChange={e => setQ(e.target.value)} data-testid="modal-search" autoFocus aria-label="search blocks" />
          <div className="seg">{CATS.map(c => <button key={c} className={cat === c ? 'on' : ''} onClick={() => setCat(c)}>{c}</button>)}</div>
          <button className={`btn sm${sortFits ? '' : ' ghost'}`} onClick={() => setSortFits(s => !s)} title="fitting blocks first">sort {sortFits ? 'fits first' : 'by registry'}</button>
          <span style={{ flex: 1 }} />
          <button className={`toggle${showIncompat ? ' on' : ''}`} style={{ border: 0, background: 'transparent' }} onClick={() => setShowIncompat(s => !s)} data-testid="modal-show-incompatible"><span className="knob" /> show incompatible</button>
        </div>
        {err && <div className="error-card" style={{ margin: '10px 20px 0' }}><h3>the registry could not answer</h3><pre>{err}</pre></div>}
        <div className="ins-body">
          <div className="ins-grid-wrap">
            {sortFits ? (
              <>
                <div className="ins-group">Fits here <span>{cards.fits.length}</span></div>
                {cards.fits.length ? <div className="ins-grid">{cards.fits.map(a => <Card key={a.name} a={a} />)}</div> : <div className="muted mono small" style={{ marginBottom: 14 }}>no registered block accepts {compat?.producing_label ?? 'this type'} here{compat?.next_requires_label ? ` and emits ${compat.next_requires_label}` : ''}</div>}
                {showIncompat && <><div className="ins-group">Doesn't fit at this point <span>{cards.nofit.length} · reasons shown</span></div><div className="ins-grid">{cards.nofit.map(a => <Card key={a.name} a={a} />)}</div></>}
              </>
            ) : <div className="ins-grid">{cards.all.filter(a => showIncompat || rowOf.get(a.name)?.ok).map(a => <Card key={a.name} a={a} />)}</div>}
          </div>
          <div className="ins-detail" data-testid="modal-detail">
            {sel ? (
              <>
                <h3>{sel.page_name}</h3>
                <div className="sg">{sel.signature}</div>
                <div className="glyph"><Glyph adapter={sel} width={272} height={96} /></div>
                <div className="desc">{sel.description || 'no description registered'}</div>
                <div className="defaults">
                  <div className="k">defaults</div>
                  {sel.params.length ? <div className="kv">{sel.params.map(p => <span key={p.name} style={{ display: 'contents' }}><span className="k">{p.name}</span><span style={{ textAlign: 'right' }}>{fmtParam(p.default)}</span></span>)}</div> : <div className="muted mono small">no parameters</div>}
                </div>
                <div className="tiles">
                  <div className="tile"><div className="k">est. cost</div><div className="v">{estimates[sel.name] != null ? `${estimates[sel.name]! < 0.05 ? '<0.1' : estimates[sel.name]!.toFixed(1)} s` : sel.has_estimate ? (source ? '…' : 'no source') : '—'}</div></div>
                  <div className="tile"><div className="k">null</div><div className="v">{sel.input_kind === 'signal' ? 'yes' : 'no'}</div></div>
                  <div className="tile"><div className="k">side-inputs</div><div className="v" style={{ fontSize: 13 }}>{sel.side_inputs.length ? sel.side_inputs.map(s => s.name).join(', ') : 'none'}</div></div>
                </div>
                {!atEnd && <div className="amber">⏱ {pad2(position + 1)} goes stale · 00–{pad2(position)} stay cached</div>}
                {sel.max_span_samples !== null && source && (source.end_idx - source.start_idx) > sel.max_span_samples && <div className="amber">⚠ this span ({source.end_idx - source.start_idx} samples) exceeds the block's local ceiling ({sel.max_span_samples}) → HPC</div>}
                <div className="grey">ⓘ inserting at the end changes the terminal type</div>
              </>
            ) : <div className="muted mono small">select a block that fits to see its defaults and cost</div>}
          </div>
        </div>
        <div className="ins-foot">
          <span className="n">{adapters.list.length} blocks in the registry · a new technique is one adapter file</span>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={!sel || busy} onClick={() => doInsert(false)} data-testid="modal-insert">+ Insert</button>
          <button className="btn primary" disabled={!sel || busy} onClick={() => doInsert(true)} data-testid="modal-insert-open">→ Insert and open settings</button>
        </div>
      </div>
    </div>
  )
}
