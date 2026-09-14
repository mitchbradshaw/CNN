/* Analyse › Chain (frames chain-1, 1b, 1d, 1e, 1f, 1h). Vertical rows (P1), one per block,
   each drawing its result on the shared time axis; validation on every edit; runs streamed
   over SSE; history and templates behind popovers (P2). */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ApiError, compatibleAt, exportRun, saveTemplate, validateParams, TYPE_LABEL,
  type Compatible, type EnvelopeSeries, type SignalPayload, type SpansetPayload, type Step, type Template,
} from '../api'
import { CrosshairProvider, TimeAxis } from '../charts/primitives'
import { makeX, type XScale } from '../charts/scale'
import { useSize } from '../charts/useSize'
import { Header } from '../shell/Header'
import { useToast } from '../shell/Toast'
import { fmtDuration, navigate, useApp } from '../state'
import { paramCaption } from './captions'
import { ChainRow, PLOT_H } from './ChainRow'
import { HistoryPopover } from './HistoryPopover'
import { InsertStageModal } from './InsertStageModal'
import { renderByType } from './Renderer'
import { deriveRows, firstStale, fmtTiming, jobForSource, sameStep, terminalWording } from './rowState'
import { RunLogModal } from './RunLogModal'
import { attachRun, cancelCurrent, clearStale, markStale, resetRun, startRun, stepElapsed, useAnalyseStore } from './store'
import { shortName, TemplatesPopover } from './TemplatesPopover'
import { EstimateChip, EXAMPLE_SOURCE, NameChip, SourceChip, SurrogateToggle, t0Of, t1Of, useSourceEnvelope } from './toolbar'
import { pad2, stepName, useAdapters } from './useAdapters'
import { spanOf, useValidation } from './useValidation'

const errText = (e: unknown) => e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)

export function ChainPage() {
  const { source, setSource, chain, setChain, route } = useApp()
  const toast = useToast()
  const adapters = useAdapters()
  const st = useAnalyseStore()
  const { payloads } = st.run
  const job = jobForSource(st.run.job, source)
  const steps = chain.steps
  const val = useValidation(steps, source)
  const { env, error: envError, status: envStatus } = useSourceEnvelope(source)
  const locked = envStatus === 423
  const [modalPos, setModalPos] = useState<number | null>(route.params.insert !== undefined ? Number(route.params.insert) : null)
  const [pop, setPop] = useState<'history' | 'import' | 'source' | null>(null)
  const [logOpen, setLogOpen] = useState(false)
  const [cross, setCross] = useState<number | null>(null)
  const [suggest, setSuggest] = useState<Compatible | null>(null)
  const [fixes, setFixes] = useState<Record<string, Compatible>>({})
  const [busy, setBusy] = useState(false)

  const t0 = source ? t0Of(source) : 0
  const t1 = source ? t1Of(source) : 1
  const running = job?.status === 'running' || job?.status === 'queued'
  const rows = useMemo(() => deriveRows(steps, job, payloads, st.staleFrom, val.v), [steps, job, payloads, st.staleFrom, val.v])
  const invalid = val.v ? val.v.junctions.filter(j => !j.ok).length : 0
  const stale = firstStale(rows, st.staleFrom)
  const failedStep = job?.status === 'failed' ? job.error?.step ?? null : null

  /* re-attach after a reload (jobs live in server memory; the SSE stream replays) */
  useEffect(() => {
    if (chain.lastRunJobId === null) return
    if (st.run.job && st.run.job.job_id === chain.lastRunJobId) return
    attachRun(chain.lastRunJobId).catch(e => { toast.push({ kind: 'error', text: errText(e) }); setChain(c => ({ ...c, lastRunJobId: null })) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chain.lastRunJobId])

  /* the end-of-chain suggestion and the fix for each invalid junction come from /chain/compatible */
  const stepsKey = JSON.stringify(steps)
  useEffect(() => {
    if (!steps.length) { setSuggest(null); return }
    let alive = true
    compatibleAt(steps, steps.length).then(c => { if (alive) setSuggest(c) }).catch(() => { if (alive) setSuggest(null) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepsKey])
  useEffect(() => {
    if (!val.v) return
    const bad = val.v.junctions.filter(j => !j.ok).map(j => j.index)
    let alive = true
    for (const i of bad) {
      const key = `${i}:${stepsKey}`
      if (fixes[key]) continue
      compatibleAt(steps, i).then(c => { if (alive) setFixes(f => ({ ...f, [key]: c })) }).catch(() => {})
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [val.v, stepsKey])

  /* ---- actions ---- */
  const run = async () => {
    if (!source || busy) return
    setBusy(true)
    try {
      const snap = await startRun(source.recording_id, spanOf(source), steps, 1200)
      setChain(c => ({ ...c, lastRunJobId: snap.job_id }))
    } catch (e) { toast.push({ kind: 'error', text: `run refused · ${errText(e)}` }) } finally { setBusy(false) }
  }
  const cancel = async () => { try { const note = await cancelCurrent(); toast.push({ text: `cancel requested · ${note ?? 'no run'}` }) } catch (e) { toast.push({ kind: 'error', text: errText(e) }) } }
  const deleteStep = (i: number) => {
    const prev = steps
    const name = adapters.byName.get(stepName(steps[i]))?.page_name ?? steps[i].algorithm
    setChain(c => ({ ...c, saved: false, steps: c.steps.filter((_, k) => k !== i) }))
    markStale(i)
    toast.push({ text: `${pad2(i + 1)} ${name} deleted`, action: { label: 'Undo', onClick: () => { setChain(c => ({ ...c, steps: prev })); markStale(i) } } })
  }
  const insertStep = (p: number, step: Step, open: boolean) => {
    setChain(c => ({ ...c, saved: false, steps: [...c.steps.slice(0, p), step, ...c.steps.slice(p)] }))
    markStale(p)
    setModalPos(null)
    if (open) navigate(`analyse/block/${p}`)
  }
  const insertByName = async (p: number, name: string) => {
    const ad = adapters.byName.get(name); if (!ad) return
    try { const { params } = await validateParams({ stage: ad.stage, algorithm: ad.algorithm, params: {} }); insertStep(p, { stage: ad.stage, algorithm: ad.algorithm, params }, false) }
    catch (e) { toast.push({ kind: 'error', text: errText(e) }) }
  }
  const importTemplate = (t: Template) => {
    setChain({ name: shortName(t), saved: false, steps: t.steps, lastRunJobId: null }); resetRun(); clearStale(); setPop(null)
    toast.push({ text: `imported ${shortName(t)} · ${t.steps.length} stages` })
  }
  const applyHistory = (s: Step[], name: string) => {
    setChain({ name, saved: false, steps: s, lastRunJobId: null }); resetRun(); clearStale(); setPop(null)
    toast.push({ text: `applied ${name} to the current source` })
  }
  const saveAsTemplate = async () => {
    const name = window.prompt('Template name', chain.name)
    if (!name) return
    try { const r = await saveTemplate(name, steps); toast.push({ text: `${r.name} · saved to the throwaway database copy (id ${r.id})` }); setChain(c => ({ ...c, name, saved: true })) }
    catch (e) { toast.push({ kind: 'error', text: errText(e) }) }
  }
  const doExport = async () => {
    if (!job) return
    try { const r = await exportRun(job.job_id); toast.push({ text: `exported run ${job.job_id} · ${r.path} · ${(r.bytes / 1024).toFixed(0)} kB`, ttlMs: 10000 }) }
    catch (e) { toast.push({ kind: 'error', text: errText(e) }) }
  }
  const useExample = () => { setSource(EXAMPLE_SOURCE); resetRun(); clearStale(); setChain(c => ({ ...c, lastRunJobId: null })); setPop(null) }

  /* ---- toolbar derivations ---- */
  const n = steps.length
  const perStep = val.v?.estimate?.per_step_s ?? null
  const estFrom = (from: number) => perStep ? perStep.slice(from).reduce((a, b) => a + b, 0) : null
  const fmtEst = (s: number | null) => s === null ? '≈ —' : s < 0.05 ? '≈ <0.1 s' : `≈ ${fmtDuration(s)}`
  let est: { text: string; kind: 'amber' | 'blue' | 'red' | 'green' }
  if (running && job) {
    const cur = job.current_step ?? 0
    est = { text: `${pad2(cur + 1)} running · ${stepElapsed(cur).toFixed(1)} s`, kind: 'blue' }
  } else if (invalid) est = { text: `${invalid} invalid junction${invalid > 1 ? 's' : ''}`, kind: 'red' }
  else if (failedStep !== null && st.staleFrom === null) est = { text: `failed at ${pad2(failedStep + 1)} · ${failedStep > 1 ? `01–${pad2(failedStep)} cached` : failedStep === 1 ? '01 cached' : 'nothing cached'}`, kind: 'red' }
  else if (!source) est = { text: 'no source · nothing to estimate', kind: 'amber' }
  else if (stale !== null) est = { text: `${fmtEst(estFrom(stale))} · ${pad2(stale + 1)} → ${pad2(n)}`, kind: 'amber' }
  else if (job?.status === 'completed') est = { text: `${fmtEst(0)} · all cached`, kind: 'green' }
  else est = { text: `${fmtEst(estFrom(0))} · 01 → ${pad2(n)}`, kind: 'amber' }
  if (val.v?.over_ceiling?.length && !running) est = { ...est, text: `${est.text} · ${val.v.over_ceiling.length} over the local ceiling` }

  const runLabel = failedStep !== null && st.staleFrom === null ? `↻ Retry from ${pad2(failedStep + 1)}` : stale !== null ? `↻ Re-run from ${pad2(stale + 1)}` : '▶ Run chain'
  const canRun = !!source && !invalid && n > 0 && !busy && !locked

  /* ---- footer ---- */
  const term = val.v ? terminalWording(val.v.terminal_kind, val.v.terminal_label) : { chip: val.error ? 'terminal — validation refused' : 'terminal — validating…', kind: 'grey' as const }
  const lastRow = rows[n - 1]
  const terminalPayload = lastRow?.payload ?? null
  const nSpans = terminalPayload?.type === 'spanset' ? (terminalPayload as SpansetPayload).n : null
  let headline: string, sub: string
  if (running && job) { headline = `Running ${pad2((job.current_step ?? 0) + 1)} of ${pad2(job.n_steps)}`; sub = 'stages land as they finish · cancel checks between steps, never mid-step' }
  else if (invalid) { headline = 'Chain is invalid'; sub = 'fix the red junction · validation runs on every edit' }
  else if (job?.status === 'failed') { headline = 'No result'; sub = `run ${job.db_run_id ? `#${job.db_run_id}` : `job ${job.job_id}`} failed at ${pad2((job.error?.step ?? 0) + 1)} · nothing was written to detections` }
  else if (job?.status === 'cancelled') { const at = job.steps.findIndex(s => s.status === 'cancelled'); headline = 'Cancelled'; sub = `stopped before ${pad2((at >= 0 ? at : (job.error?.step ?? 0)) + 1)} · ${job.steps.filter(s => s.status === 'done').length} of ${job.n_steps} stages kept · cancel is checked between steps` }
  else if (job?.status === 'completed') {
    headline = `last run · ${terminalPayload?.summary ?? job.steps[job.n_steps - 1]?.summary ?? 'done'}`
    const core = job.step_timings ? Object.values(job.step_timings).reduce((a, b) => a + b, 0) : null
    sub = `job ${job.job_id} · db run #${job.db_run_id ?? '—'} · ${job.detections_written ?? 0} written to detections · ${core !== null ? fmtTiming(core) + ' core' : ''} · ${fmtDuration(job.elapsed_s)} wall${stale !== null ? ` · ${pad2(stale + 1)} → ${pad2(n)} stale` : ''}`
  } else { headline = 'No result yet'; sub = source ? 'run the chain to see every intermediate' : 'send a span from Explore or use the example span' }

  /* ---- rows ---- */
  const sourceEnvelope: EnvelopeSeries | null = env?.envelope ?? null
  const sourcePayload: SignalPayload | null = env ? { type: 'signal', fs: env.fs, n: env.n_samples, t0_s: env.t0_s, t1_s: env.t1_s, y_range: null, envelope: env.envelope, summary: '' } : null
  const ghostFor = (i: number): EnvelopeSeries | null => {
    for (let j = i - 1; j >= 0; j--) { const p = rows[j]?.payload; if (p && p.type === 'signal') return (p as SignalPayload).envelope }
    return sourceEnvelope
  }
  const throwTest = route.params.throw === '1'

  const rowFor = (i: number): ReactNode => {
    const step = steps[i]; const r = rows[i]
    const ad = adapters.byName.get(stepName(step))
    const title = ad?.page_name ?? step.algorithm
    const sig = ad?.signature ?? `${step.stage}.${step.algorithm}`
    const jstep = job && sameStep(job.recipe.steps[i], step) ? job.steps[i] : undefined
    const caption = r.payload?.summary ?? (r.hasResult ? '' : null) ?? (jstep?.summary && r.status !== 'new' ? jstep.summary : paramCaption(step, ad))
    const timing = (r.status === 'cached' && r.timing !== null && r.timing !== 0) ? fmtTiming(r.timing) : null
    const badgeText = r.status === 'cached' && r.timing === 0 ? 'cached · 0 s' : r.status === 'waiting' ? '⌛ waiting' : undefined
    const badgeTitle = r.status === 'cached' ? (r.timing === 0 ? 'restored from the prefix cache (core step time 0.0 s)' : r.timing !== null ? `core step time ${r.timing.toFixed(3)} s` : 'predicted from the prefix cache · run to load the result') : r.status === 'stale' ? 'a parameter or an upstream stage changed since this result' : undefined
    const ghost = ghostFor(i)
    const elapsed = r.status === 'running' ? stepElapsed(i) : 0

    let overlay: ReactNode = null
    let plot = (x: XScale, w: number, h: number): ReactNode => r.payload ? renderByType(r.payload, { x, width: w, height: h, ghost, t0, t1 }) : null
    switch (r.status) {
      case 'running':
        overlay = <>{r.payload && <div className="an-plot-veil" />}<div className="an-progress" data-testid={`progress-${i + 1}`}><div className="bar" /><div className="txt">{title} · computing · {elapsed.toFixed(1)} s{jstep?.cached_predicted ? ' · predicted cache hit' : ''}</div><div className="note">per-step progress — the core reports no within-step fraction · cancel takes effect before the next step</div></div></>
        break
      case 'waiting':
        plot = () => null
        overlay = <div className="an-plot-empty">⌛ waits for {pad2((job?.current_step ?? 0) + 1)} · last result hidden</div>
        break
      case 'stale':
        overlay = <><div className="an-plot-veil" /><span className="an-stale-pill" data-testid={`stale-pill-${i + 1}`}>⏱ last run shown · stale</span></>
        break
      case 'new':
        plot = () => null
        overlay = <div className="an-plot-empty">{r.cachedPredicted ? 'result predicted in the step cache · run the chain to load it' : 'no result yet · run the chain'}</div>
        break
      case 'blocked':
        plot = () => null
        overlay = <div className="an-plot-empty">blocked · {pad2((job?.error?.step ?? 0) + 1)} failed upstream</div>
        break
      case 'cancelled':
        plot = () => null
        overlay = <div className="an-plot-empty">cancelled before this stage ran</div>
        break
      case 'invalid':
        overlay = r.payload ? <div className="an-plot-veil" /> : <div className="an-plot-empty">this stage cannot run — see the junction above</div>
        break
      case 'cached':
        if (!r.payload) { plot = () => null; overlay = <div className="an-plot-empty">{jstep?.status === 'done' ? 'loading result…' : 'in the step cache · run the chain to load it'}</div> }
        break
    }
    let replace: ReactNode = null
    if (r.status === 'failed' && job) {
      const err = job.error
      replace = (
        <div className="an-fail" data-testid="error-card">
          <div style={{ color: 'var(--red)', fontSize: 18 }}>ⓘ</div>
          <div style={{ minWidth: 0 }}>
            <div className="t">{pad2(i + 1)} {title} failed after {fmtTiming(jstep?.elapsed_s ?? null) || '—'}</div>
            <div className="m" title={err?.message}>{err?.message ?? 'unknown error'}</div>
            <div className="s">adapter {err?.adapter ?? stepName(step)} · recipe {job.config_hash ?? val.v?.hashes?.config_hash ?? `job ${job.job_id}`} · traceback in log</div>
          </div>
          <div className="acts">
            <button className="btn" onClick={() => setLogOpen(true)} data-testid="view-log">View log</button>
            <button className="btn" onClick={() => navigate(`analyse/block/${i}`)}>Open settings</button>
            <button className="btn primary" onClick={run} disabled={!canRun}>↻ Retry {pad2(i + 1)}</button>
          </div>
        </div>
      )
    } else if (r.overCeiling && r.status !== 'running') {
      const nSamples = source ? source.end_idx - source.start_idx : 0
      replace = (
        <div className="an-hpc" data-testid="hpc-card">
          <div>
            <div className="t">⛭ this span exceeds the local ceiling → HPC</div>
            <div className="s">{nSamples.toLocaleString()} samples · {title} caps local runs at {ad?.max_span_samples?.toLocaleString() ?? '?'} samples · the stage pauses here and its result re-enters through the manifest inbox (P4, P24)</div>
          </div>
          <div className="row"><button className="btn" disabled title="out of slice scope">Create SLURM script</button><button className="btn" disabled title="out of slice scope">Upload computed artifact</button></div>
        </div>
      )
    }
    return (
      <ChainRow key={`step-${i}`} testIndex={i + 1} rowClass={r.status === 'failed' || r.status === 'invalid' ? r.status : ''} num={pad2(i + 1)} title={title} badge={r.status} badgeText={badgeText} badgeTitle={badgeTitle} timingText={timing}
        signature={sig} caption={caption} t0={t0} t1={t1} plot={plot} overlay={overlay} replace={replace}
        onSettings={() => navigate(`analyse/block/${i}`)} onDelete={running ? undefined : () => deleteStep(i)} />
    )
  }

  const junctionFor = (i: number): ReactNode => {
    const j = val.v?.junctions[i]
    if (!j || j.ok) return null
    const fix = fixes[`${i}:${stepsKey}`]
    const first = fix?.rows.find(r => r.ok)
    const firstName = first ? adapters.byName.get(first.name)?.page_name ?? first.name : null
    const here = steps[i]; const prev = steps[i - 1]
    const hereName = `${pad2(i + 1)} ${adapters.byName.get(stepName(here))?.page_name ?? here.algorithm}`
    const prevName = prev ? `${pad2(i)} ${adapters.byName.get(stepName(prev))?.page_name ?? prev.algorithm}` : 'Source'
    return (
      <div className="an-junction" key={`junction-${i}`}>
        <div className="an-junction-pill" data-testid="junction-error" title={j.core_reason || j.reason}>
          <span>⊗ {hereName} needs {j.expected ? TYPE_LABEL[j.expected] : '?'} · {prevName} emits {TYPE_LABEL[j.producing]}</span>
          {firstName && <button className="btn sm" onClick={() => insertByName(i, first!.name)} data-testid="junction-insert">+ Insert {firstName} here</button>}
          <button className="btn sm" onClick={() => setModalPos(i)} data-testid="junction-browse">☰ Show blocks that fit</button>
        </div>
      </div>
    )
  }

  const insertPill = (p: number, end = false) => (
    <div className="an-insert-line" key={`ins-${p}`}><button className="an-insert" onClick={() => setModalPos(p)} data-testid={`insert-${p}`} disabled={running} title={running ? 'wait for the run' : 'insert a stage here'}>+ insert{end ? ' · end of chain' : ''}</button></div>
  )
  const fitNames = suggest ? suggest.rows.filter(r => r.ok).map(r => adapters.byName.get(r.name)) : []
  const fitOutputs = Array.from(new Set(fitNames.map(a => a?.output_kind).filter(Boolean))).map(k => TYPE_LABEL[k!])

  return (
    <>
      <Header workspace="Analyse" page="Chain" subtitle="build here · open a block to tune it" />
      <div className="page"><div className="page-inner" data-testid="chain-page">
        {adapters.error && <div className="error-card"><h3>adapter registry failed to load</h3><pre>{adapters.error}</pre></div>}
        {val.error && <div className="error-card"><h3>validation failed</h3><pre>{val.error}</pre></div>}
        {st.run.error && <div className="error-card" style={{ padding: '8px 12px' }}><h3>last run could not be re-attached</h3><div className="mono small">{st.run.error}</div></div>}
        {val.v?.recipe_error && <div className="error-card" style={{ padding: '8px 12px' }}><h3>recipe cannot be built</h3><div className="mono small">{val.v.recipe_error}</div></div>}

        {/* toolbar */}
        <div className="an-toolbar">
          <NameChip chain={chain} onRename={name => setChain(c => ({ ...c, name, saved: false }))} extra={job && failedStep !== null ? <span className="chip red" style={{ height: 20, fontSize: 10, padding: '0 6px' }} title={`job ${job.job_id}`}>#{job.db_run_id ?? job.job_id} failed</span> : null} />
          <span className="an-popwrap">
            <SourceChip source={source} onClick={() => setPop(p => p === 'source' ? null : 'source')} />
            {pop === 'source' && (
              <div className="an-pop left" style={{ width: 380 }} data-testid="source-popover">
                <h4>Source <span>single channel · one span (P3)</span></h4>
                {source ? <div className="an-pop-item"><span className="chip blue" style={{ height: 22 }}>current</span><span>{source.source_file} · {source.channel_name} · samples {source.start_idx}–{source.end_idx}{source.label ? ` · ${source.label}` : ''}</span></div> : <div className="an-pop-note">no source yet</div>}
                <div className="an-pop-item btnlike" onClick={useExample} data-testid="use-example">⌇ Use the example span (CH4_A2 · 276.4–278.4 h)</div>
                <div className="an-pop-item btnlike" onClick={() => navigate('explore/corpus')}>→ Pick in Explore</div>
              </div>
            )}
          </span>
          <SurrogateToggle />
          <EstimateChip text={est.text} kind={est.kind} />
          <span className="spacer" />
          <span className="an-popwrap">
            <button className={`btn${pop === 'history' ? ' primary' : ''}`} onClick={() => setPop(p => p === 'history' ? null : 'history')} data-testid="history-button">⟲ History</button>
            {pop === 'history' && <HistoryPopover source={source} onApply={applyHistory} onClose={() => setPop(null)} />}
          </span>
          <span className="an-popwrap">
            <button className={`btn${pop === 'import' ? ' primary' : ''}`} onClick={() => setPop(p => p === 'import' ? null : 'import')} data-testid="import-button">⤓ Import</button>
            {pop === 'import' && <TemplatesPopover onPick={importTemplate} onClose={() => setPop(null)} />}
          </span>
          <button className="btn" onClick={saveAsTemplate} data-testid="save-template" disabled={!n}>▢ Save template</button>
          {running ? <button className="btn danger" onClick={cancel} data-testid="cancel-button">■ Cancel</button>
            : <button className="btn primary" onClick={run} disabled={!canRun} data-testid="run-button" title={!source ? 'no source' : invalid ? 'fix the red junction first' : !n ? 'add a stage' : undefined}>{runLabel}</button>}
        </div>

        <CrosshairProvider value={{ t: cross, setT: setCross }}>
          {/* source row */}
          {source ? (
            <ChainRow testIndex={0} num={null} title="Source" badge="source-cached" badgeTitle="the span is loaded from the channel's .npy on disk" signature="— → Signal"
              caption={`${source.label === 'example span' ? 'example span' : 'signal span from Explore'} · ${fmtDuration(t1 - t0)} · ${source.fs} Hz`} captionTitle={`${source.source_file} · ${source.channel_name} · samples ${source.start_idx}–${source.end_idx}`} t0={t0} t1={t1}
              plot={(x, w, h) => sourcePayload ? <SourcePlot p={sourcePayload} x={x} w={w} h={h} throwTest={throwTest} /> : null}
              replace={locked ? (
                <div className="an-hpc" data-testid="held-out-card" style={{ background: 'var(--grey-100)', borderColor: 'var(--grey-200)' }}>
                  <div><div className="t" style={{ color: 'var(--text-2)' }}>🔒 {source.source_file} is held out — the bridge refuses it (423) and this page shows none of its data</div><div className="s">D6: the held-out lock stays on in every workspace · pick a span from another recording</div></div>
                  <button className="btn" onClick={useExample}>Use the example span</button>
                </div>
              ) : undefined}
              overlay={envError ? <div className="error-card" style={{ position: 'absolute', inset: 4, padding: '6px 10px' }}><h3>source window failed</h3><pre>{envError}</pre></div> : !env ? <div className="skeleton" style={{ position: 'absolute', inset: 6 }} /> : null} />
          ) : (
            <div className="card an-nosource" data-testid="chain-row-0">
              <span className="badge new">no source</span>
              <span className="mono">no source yet — send a span from Explore</span>
              <span className="spacer" style={{ flex: 1 }} />
              <button className="btn" onClick={() => navigate('explore/corpus')}>Go to Explore</button>
              <button className="btn primary" onClick={useExample} data-testid="use-example">Use the example span (CH4_A2 · 276.4–278.4 h)</button>
            </div>
          )}
          {steps.map((_, i) => (
            <span key={i} style={{ display: 'contents' }}>
              {junctionFor(i) ?? insertPill(i)}
              {rowFor(i)}
            </span>
          ))}
          {insertPill(n, true)}
          {suggest && suggest.n_fit > 0 && n > 0 && (
            <div className="card an-suggest" data-testid="suggest-card">
              <span style={{ color: 'var(--muted)', fontSize: 18 }}>✦</span>
              <div>
                <div className="t">{suggest.producing_label} → {fitOutputs.join(' / ') || '?'} fits here</div>
                <div className="s">{fitNames.slice(0, 6).map(a => a?.page_name ?? '?').join(' · ')}{fitNames.length > 6 ? ' · …' : ''} — {suggest.n_fit} block{suggest.n_fit === 1 ? '' : 's'} accept{suggest.n_fit === 1 ? 's' : ''} {suggest.producing_label}</div>
              </div>
              <div className="row">
                <button className="btn" onClick={() => setModalPos(n)}>☷ Browse compatible</button>
                {fitNames[0] && <button className="btn primary" onClick={() => insertByName(n, fitNames[0]!.name)} disabled={running}>+ Insert {fitNames[0].page_name}</button>}
              </div>
            </div>
          )}
          {/* shared axis */}
          <FooterAxis t0={t0} t1={t1} enabled={!!source} />
        </CrosshairProvider>

        {/* footer */}
        <div className="card an-footer">
          <span className={`chip ${term.kind}`} data-testid="footer-terminal" title="spec §6.1: the terminal type decides what the chain is">{term.chip}</span>
          <div style={{ minWidth: 0 }}>
            <div className="head" data-testid="footer-headline">{headline}</div>
            <div className="sub">{sub}</div>
          </div>
          <div className="acts">
            <button className="btn" onClick={doExport} disabled={job?.status !== 'completed'} data-testid="export-run" title={job?.status === 'completed' ? 'write a JSON report of this run' : 'needs a completed run'}>⤒ Export run</button>
            <button className="btn" disabled title="sends the terminal SpanSet into a new chain · out of slice scope">→ Analyse events</button>
            <button className="btn primary" disabled title="out of slice scope">→ Pass {nSpans ?? ''} to Review</button>
          </div>
        </div>
      </div></div>

      {modalPos !== null && <InsertStageModal steps={steps} position={modalPos} adapters={adapters} source={source} onClose={() => setModalPos(null)} onInsert={(s, open) => insertStep(modalPos, s, open)} />}
      {logOpen && job && <RunLogModal jobId={job.job_id} onClose={() => setLogOpen(false)} />}
    </>
  )
}

function SourcePlot({ p, x, w, h, throwTest }: { p: SignalPayload; x: XScale; w: number; h: number; throwTest: boolean }) {
  // near-black raw signal (frame chain-1): use the shared renderer with the trace colour overridden
  return <div style={{ ['--trace-blue' as string]: 'var(--trace)' } as React.CSSProperties}>{renderByType(p, { x, width: w, height: h, ghost: null, t0: p.t0_s, t1: p.t1_s, throwForTest: throwTest })}</div>
}

function FooterAxis({ t0, t1, enabled }: { t0: number; t1: number; enabled: boolean }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width)
  const x = makeX(t0, t1, w)
  return (
    <div className="an-axis" data-testid="footer-axis">
      <span className="lbl">all rows share this time axis</span>
      <div ref={ref} style={{ height: 22 }}>{enabled && size.width > 0 && <svg width={w} height={22}><TimeAxis x={x} y={2} t0={t0} t1={t1} n={7} /></svg>}</div>
    </div>
  )
}

// keep the type import used (PLOT_H is the shared row height; exported for the block page)
export const ROW_PLOT_H = PLOT_H
