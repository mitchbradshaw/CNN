/* Analyse › block page (frames chain-3, chain-7, chain-7b): the PROCESS for one block —
   what it looked at, what it computed, the output — beside a generated parameters panel.
   Editing a parameter marks this block and everything downstream stale (P5, §6.8). */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, saveTemplate, type EncodingSymbolicPayload, type EnvelopeSeries, type Payload, type ScoresPayload, type SignalPayload, type SpansetPayload, type WindowsetPayload, type GroupingPayload, type ModelPayload } from '../api'
import { EnvelopePath, SpanBands, TimeAxis, YLabels } from '../charts/primitives'
import { clamp, makeX, makeY, polylinePath, type XScale } from '../charts/scale'
import { useSize } from '../charts/useSize'
import { ErrorBoundary } from '../shell/ErrorBoundary'
import { Header } from '../shell/Header'
import { useToast } from '../shell/Toast'
import { fmtDuration, fmtHours, navigate, useApp } from '../state'
import { paramCaption } from './captions'
import { ParamsPanel, fmtParam } from './ParamsPanel'
import { GhostPath, motifLabels, renderByType, SYM3 } from './Renderer'
import { deriveRows, fmtTiming, jobForSource } from './rowState'
import { cancelCurrent, markStale, startRun, stepElapsed, syncToSource, useAnalyseStore } from './store'
import { EstimateChip, isHeldOut, NameChip, RunErrorCard, SourceChip, SurrogateToggle, t0Of, t1Of, useSourceEnvelope } from './toolbar'
import { pad2, stepName, useAdapters } from './useAdapters'
import { spanOf, useValidation } from './useValidation'

const errText = (e: unknown) => e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)

export function BlockPage({ index }: { index: number }) {
  const { source, chain, setChain } = useApp()
  const toast = useToast()
  const adapters = useAdapters()
  const st = useAnalyseStore()
  const { payloads } = st.run
  const job = jobForSource(st.run.job, source)
  const steps = chain.steps
  const step = steps[index] as typeof steps[number] | undefined
  const val = useValidation(steps, source)
  const { env } = useSourceEnvelope(source)
  const rows = useMemo(() => deriveRows(steps, job, payloads, st.staleFrom, val.v), [steps, job, payloads, st.staleFrom, val.v])
  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState<string | null>(null)
  const ad = step ? adapters.byName.get(stepName(step)) : undefined
  const title = ad?.page_name ?? step?.algorithm ?? '?'
  const t0 = source ? t0Of(source) : 0
  const t1 = source ? t1Of(source) : 1
  const running = job?.status === 'running' || job?.status === 'queued'
  const locked = isHeldOut(source)
  const over = val.v?.over_ceiling ?? []
  const overTitle = over.length ? `stage ${pad2(over[0] + 1)} exceeds its local ceiling (${adapters.byName.get(stepName(steps[over[0]]))?.max_span_samples?.toLocaleString() ?? '?'} samples) · shorten the span or use HPC (out of slice scope)` : null
  const canRun = !!source && !running && !busy && !locked && !over.length
  const runTitle = !source ? 'no source' : locked ? 'the held-out recording cannot be run' : running ? 'a run is in progress' : overTitle ?? undefined
  // a source change forgets a job (and stale index) that belongs to another recording/span (critique r1)
  const sourceKey = source ? `${source.recording_id}:${source.start_idx}:${source.end_idx}` : ''
  useEffect(() => { syncToSource(source); setRefused(null) }, [sourceKey])   // eslint-disable-line react-hooks/exhaustive-deps

  const setParam = (name: string, value: unknown) => {
    setChain(c => ({ ...c, saved: false, steps: c.steps.map((s, k) => k === index ? { ...s, params: { ...s.params, [name]: value } } : s) }))
    markStale(index)
  }
  const revert = () => {
    if (!ad) return
    setChain(c => ({ ...c, saved: false, steps: c.steps.map((s, k) => k === index ? { ...s, params: Object.fromEntries(ad.params.map(p => [p.name, p.default])) } : s) }))
    markStale(index)
    toast.push({ text: `${pad2(index + 1)} ${title} reverted to the adapter defaults` })
  }
  // stays on the block page (frames chain-3 / 7b): the ribbon chip and the process card show the run,
  // and the payload refreshes in place when the run ends — the module store keeps streaming (critique r1)
  const rerun = async () => {
    if (!source || busy) return
    setBusy(true)
    try { const snap = await startRun(source.recording_id, spanOf(source), steps, 1200); setRefused(null); setChain(c => ({ ...c, lastRunJobId: snap.job_id })) }
    catch (e) { setRefused(e instanceof ApiError ? e.message : String(e)); toast.push({ kind: 'error', text: `run refused · ${errText(e)}` }) } finally { setBusy(false) }
  }
  const cancel = async () => { try { const note = await cancelCurrent(); toast.push({ text: `cancel requested · ${note ?? 'no run'}` }) } catch (e) { toast.push({ kind: 'error', text: errText(e) }) } }
  const saveAsTemplate = async () => {
    const name = window.prompt('Template name', chain.name)
    if (!name) return
    try { const r = await saveTemplate(name, steps); toast.push({ text: `${r.name} · saved to the throwaway database copy (id ${r.id})` }); setChain(c => ({ ...c, name, saved: true })) }
    catch (e) { toast.push({ kind: 'error', text: errText(e) }) }
  }

  if (!step) {
    return (
      <>
        <Header workspace="Analyse" page={`${pad2(index + 1)} —`} subtitle="process detail · the chain row shows only the result" />
        <div className="page"><div className="page-inner" data-testid="block-page">
          <div className="card card-pad"><div className="b">There is no stage {pad2(index + 1)} in this chain</div><p className="muted">The chain has {steps.length} stage{steps.length === 1 ? '' : 's'}.</p><button className="btn" onClick={() => navigate('analyse/chain')}>‹ full chain</button></div>
        </div></div>
      </>
    )
  }

  const row = rows[index]
  const upstream: Payload | null = index > 0 ? rows[index - 1]?.payload ?? null : null
  const sourceEnvelope: EnvelopeSeries | null = env?.envelope ?? null
  const upstreamSignal: EnvelopeSeries | null = (() => {
    for (let j = index - 1; j >= 0; j--) { const p = rows[j]?.payload; if (p?.type === 'signal') return (p as SignalPayload).envelope }
    return sourceEnvelope
  })()
  const perStep = val.v?.estimate?.per_step_s ?? null
  const staleFrom = job ? st.staleFrom : null      // nothing is stale relative to another source's job
  const rerunFrom = staleFrom !== null ? staleFrom : index
  const cost = perStep ? perStep.slice(rerunFrom).reduce((a, b) => a + b, 0) : null
  const costText = cost === null ? '—' : cost < 0.05 ? '<0.1 s' : cost < 10 ? `${cost.toFixed(1)} s` : fmtDuration(cost)
  const stale = staleFrom !== null && staleFrom <= index
  const stat = statTiles(row.payload)
  const name = stepName(step)
  const curStep = job?.current_step ?? 0
  const runningHere = running && row.status === 'running'
  const runNote = running ? (row.status === 'running' ? `${title} · computing · ${stepElapsed(index).toFixed(1)} s` : row.status === 'waiting' ? `waits for ${pad2(curStep + 1)} · ${pad2(index + 1)} runs after it` : row.status === 'cached' ? `${pad2(index + 1)} done · ${pad2(curStep + 1)} running` : `${pad2(curStep + 1)} running`) : ''

  return (
    <>
      <Header workspace="Analyse" page={`${pad2(index + 1)} ${title}`} subtitle="process detail · the chain row shows only the result" />
      <div className="page"><div className="page-inner" data-testid="block-page">
        <div className="an-toolbar">
          <button className="btn ghost" onClick={() => navigate('analyse/chain')} data-testid="back-to-chain">‹ full chain</button>
          <NameChip chain={chain} onRename={n => setChain(c => ({ ...c, name: n, saved: false }))} />
          <SourceChip source={source} />
          <SurrogateToggle />
          <EstimateChip text={running ? `${pad2(curStep + 1)} running · ${stepElapsed(curStep).toFixed(1)} s` : `≈ ${costText} · ${pad2(rerunFrom + 1)} → ${pad2(steps.length)}${stale ? ' recompute' : ''}${over.length ? ` · ${over.length} over the local ceiling` : ''}`} kind={running ? 'blue' : over.length ? 'red' : 'amber'} />
          <span className="spacer" />
          <button className="btn" onClick={saveAsTemplate} data-testid="save-template">▢ Save template</button>
          {running ? <button className="btn danger" onClick={cancel} data-testid="cancel-button">■ Cancel</button>
            : <button className="btn primary" onClick={rerun} disabled={!canRun} data-testid="run-button" title={runTitle}>↻ Re-run from {pad2(rerunFrom + 1)}</button>}
        </div>
        {st.run.error && <RunErrorCard error={st.run.error} kind={st.run.errorKind} />}
        {refused && <div className="error-card" style={{ padding: '8px 12px' }} data-testid="run-refused-card"><h3>run refused by the bridge (422)</h3><div className="mono small">{refused}</div></div>}

        {/* ribbon */}
        <div className="card bp-ribbon" data-testid="block-ribbon">
          <span className="lbl">chain</span>
          <button className="bp-chip" style={{ flex: 'none', minWidth: 130 }} onClick={() => navigate('analyse/chain')}><div className="t"><span style={{ fontSize: 9 }}>●</span> Source <span className="badge cached">cached</span></div><div className="sg">— → Signal</div></button>
          {steps.map((s, i) => {
            const a = adapters.byName.get(stepName(s)); const r = rows[i]
            return (
              <span key={i} style={{ display: 'contents' }}>
                <span className="sep">›</span>
                <button className={`bp-chip${i === index ? ' on' : ''}`} onClick={() => navigate(`analyse/block/${i}`)} data-testid={`ribbon-${i}`}>
                  <div className="t"><span className="num">{pad2(i + 1)}</span> {a?.page_name ?? s.algorithm} <span className={`badge ${r.status === 'waiting' ? 'pending' : r.status}`} data-testid={`ribbon-badge-${i}`}>{r.status === 'running' ? `running · ${stepElapsed(i).toFixed(1)} s` : r.status}</span></div>
                  <div className="sg">{a?.signature ?? name}</div>
                </button>
              </span>
            )
          })}
          <span className="sep">›</span>
          <button className="bp-chip add" onClick={() => navigate(`analyse/chain?insert=${steps.length}`)} title="insert a stage at the end">+ stage</button>
        </div>

        <div className="bp-main">
          <div className="card card-pad bp-process" data-testid="block-process" data-running={running ? '1' : undefined}>
            {running && (
              <div className="bp-run-veil" data-testid="block-running">
                <div className="an-progress"><div className="bar" /><div className="txt">{runNote}{runningHere && job?.steps[index]?.cached_predicted ? ' · predicted cache hit' : ''}</div><div className="note">the result refreshes here when the run ends · cancel takes effect before the next step</div></div>
              </div>
            )}
            <div className="bp-card-title"><span className="mono muted">{pad2(index + 1)}</span><h3>{title}</h3><span className="sg">{ad?.signature ?? name}</span>
              <span className="sg" style={{ marginLeft: 'auto' }}>{source ? `${fmtHours(t0)}–${fmtHours(t1)} of ${source.channel_name}` : 'no source'}{row.status === 'cached' && row.timing !== null ? ` · ${fmtTiming(row.timing)} core` : ''}</span></div>
            {!source && <div className="muted mono small">no source — the process view needs a span. Use the example span from the chain page.</div>}
            {source && (
              <ErrorBoundary label={`block ${pad2(index + 1)} process`}>
                {name === 'detection.threshold' ? (
                  <ThresholdProcess scores={upstream?.type === 'scores' ? upstream as ScoresPayload : null} result={row.payload?.type === 'spanset' ? row.payload as SpansetPayload : null} threshold={Number(step.params.threshold ?? 0)} onThreshold={v => setParam('threshold', v)} stale={stale} t0={t0} t1={t1} />
                ) : name === 'detection.matrix_profile' ? (
                  <MatrixProfileProcess signal={upstreamSignal} scores={row.payload?.type === 'scores' ? row.payload as ScoresPayload : null} windowMin={Number(step.params.window_min ?? 10)} fs={source.fs} stale={stale} t0={t0} t1={t1} />
                ) : name === 'detection.sax_dsax' ? (
                  <DsaxProcess signal={upstreamSignal} enc={row.payload?.type === 'encoding' && (row.payload as EncodingSymbolicPayload).kind === 'symbolic' ? row.payload as EncodingSymbolicPayload : null} stale={stale} t0={t0} t1={t1} trend={String(step.params.trend_estimator ?? 'ols_slope')} />
                ) : (
                  <GenericProcess payload={row.payload} ghost={upstreamSignal} stale={stale} t0={t0} t1={t1} caption={paramCaption(step, ad)} />
                )}
              </ErrorBoundary>
            )}
            {row.status === 'failed' && job?.error && <div className="error-card" style={{ marginTop: 10 }}><h3>{pad2(index + 1)} {title} failed</h3><div className="mono small">{job.error.message}</div></div>}
            {row.status === 'new' && !row.payload && <div className="muted mono small" style={{ marginTop: 8 }}>no result for this stage yet · the process strips fill in after a run</div>}
          </div>

          <div className="stack">
            <div className="card card-pad pp" data-testid="params-panel">
              <div className="pp-head"><h3>Parameters</h3><span className="muted mono small">{ad ? `${ad.params.length} declared` : ''}</span>
                {ad?.has_recommend && <span className="rec" title="this adapter declares a recommend hook for the span · the values it would recommend are not served by this slice">▏can recommend for this span</span>}</div>
              {ad ? <ParamsPanel adapter={ad} params={step.params} onChange={setParam} disabled={running} /> : <div className="muted mono small">adapter {name} is not in the registry</div>}
              {stat.length > 0 && <div className="bp-tiles" data-testid="stat-tiles">{stat.map(t => <div className="bp-tile" key={t.k}><div className="k" title={t.k}>{t.k}</div><div className={`v${t.red ? ' red' : ''}`}>{t.v}</div></div>)}</div>}
              {row.payload && <div className="bp-info">{row.payload.summary}{stale ? ' · from the last run · stale' : ''}</div>}
            </div>
            {name === 'detection.threshold' && (
              <>
                <SpansVsCut scores={upstream?.type === 'scores' ? upstream as ScoresPayload : null} threshold={Number(step.params.threshold ?? 0)} onThreshold={v => setParam('threshold', v)} resultN={row.payload?.type === 'spanset' ? (row.payload as SpansetPayload).n : null} stale={stale} />
                <div className="card bp-next" data-testid="next-card">
                  <div className="row"><span className="b">Next · SpanSet allows</span><span className="muted mono small" style={{ marginLeft: 'auto' }}>hand-offs</span></div>
                  <div className="s">{row.payload?.type === 'spanset' ? `${(row.payload as SpansetPayload).n} spans from the last run${stale ? ' · stale' : ''}` : 'no SpanSet yet · re-run to produce one'} · a SpanSet terminal makes this chain a detection template</div>
                  <div className="acts">
                    <button className="btn" onClick={saveAsTemplate} data-testid="next-save-template">▢ Save template</button>
                    <button className="btn" disabled aria-disabled="true" title="sends the terminal SpanSet into a new chain · out of slice scope">→ Analyse events</button>
                    <button className="btn primary" disabled aria-disabled="true" title={row.payload?.type === 'spanset' ? 'hands the spans to a Review queue · out of slice scope' : 'needs a completed run · out of slice scope'}>→ Pass {row.payload?.type === 'spanset' ? (row.payload as SpansetPayload).n : ''} to Review</button>
                  </div>
                </div>
              </>
            )}
            <div className="card bp-null" data-testid="null-card">
              <div className="row"><span className="b">This parameter against the null</span><span className="muted mono small" style={{ marginLeft: 'auto' }}>ⓘ</span></div>
              <div className="e">null sweeps are out of slice scope — surrogate runs are not part of this prototype{ad?.input_kind === 'signal' ? '' : ' · this block declares no signal null'}</div>
            </div>
          </div>
        </div>

        <div className="card bp-foot" data-testid="block-footer">
          {running ? <span className="st"><span className="dot" style={{ background: 'var(--blue)' }} /> Running {pad2(curStep + 1)} of {pad2(job?.n_steps ?? steps.length)}</span> : staleFrom !== null ? <span className="st"><span className="dot" /> Unapplied changes</span> : <span className="st">No unapplied changes</span>}
          <span className="sub">{running ? 'stages land as they finish · this page updates in place' : staleFrom !== null ? `${pad2(staleFrom + 1)} and later are stale · re-running costs ≈ ${costText}` : job?.status === 'completed' ? `every stage is cached from job ${job.job_id} · db run #${job.db_run_id ?? '—'} · no null` : job?.status === 'failed' ? `run ${job.db_run_id ? `#${job.db_run_id}` : `job ${job.job_id}`} failed at ${pad2((job.error?.step ?? 0) + 1)}` : 'edit a parameter and the block goes stale'}</span>
          <div className="acts">
            <button className="btn" onClick={revert} disabled={!ad || running} data-testid="revert-defaults" title={running ? 'wait for the run' : 'reset every parameter of this block to the adapter defaults'}>↶ Revert to defaults</button>
            {running ? <button className="btn danger" onClick={cancel}>■ Cancel</button>
              : <button className="btn primary" onClick={rerun} disabled={!canRun} title={runTitle} data-testid="footer-rerun">↻ Re-run from {pad2(rerunFrom + 1)}</button>}
          </div>
        </div>
      </div></div>
    </>
  )
}

/* ---------------- stat tiles from the payload ---------------- */
function statTiles(p: Payload | null): { k: string; v: string; red?: boolean }[] {
  if (!p || 'error' in p) return []
  switch (p.type) {
    case 'spanset': { const s = p as SpansetPayload; const mean = s.n ? s.start_s.reduce((a, x, i) => a + (s.end_s[i] - x), 0) / s.n : 0; return [{ k: 'spans', v: String(s.n) }, { k: 'mean duration', v: s.n ? fmtDuration(mean) : '—' }, { k: 'longest', v: s.n ? fmtDuration(Math.max(...s.start_s.map((x, i) => s.end_s[i] - x))) : '—' }, { k: 'capped', v: s.capped ? 'yes' : 'no', red: s.capped }] }
    case 'scores': { const s = p as ScoresPayload; return [{ k: 'values', v: s.n.toLocaleString() }, { k: 'NaN tail', v: String(s.nan_tail) }, { k: 'min', v: s.value_range ? fmtParam(s.value_range[0]) : '—' }, { k: 'max', v: s.value_range ? fmtParam(s.value_range[1]) : '—' }] }
    case 'signal': { const s = p as SignalPayload; return [{ k: 'samples', v: s.n.toLocaleString() }, { k: 'min mV', v: s.y_range ? fmtParam(s.y_range[0]) : '—' }, { k: 'max mV', v: s.y_range ? fmtParam(s.y_range[1]) : '—' }, { k: 'fs', v: `${s.fs} Hz` }] }
    case 'encoding': { const e = p as EncodingSymbolicPayload; if (e.kind !== 'symbolic') return [{ k: 'kind', v: 'image' }]; return [{ k: 'symbols', v: String(e.n_symbols) }, { k: 'alphabet', v: String(e.alphabet_size) }, { k: 's per symbol', v: e.seconds_per_symbol != null ? fmtParam(e.seconds_per_symbol) : '—' }, { k: 'trimmed', v: e.n_trimmed != null ? String(e.n_trimmed) : '—' }] }
    case 'windowset': { const w = p as WindowsetPayload; return [{ k: 'windows', v: String(w.n_windows) }, { k: 'length', v: `${w.length_s} s` }, { k: 'features', v: w.features ? String(w.features.n_columns) : '—' }, { k: 'capped', v: w.capped ? 'yes' : 'no', red: w.capped }] }
    case 'grouping': { const g = p as GroupingPayload; return [{ k: 'clusters', v: String(g.k) }, { k: 'windows', v: String(g.n) }, { k: 'largest', v: String(Math.max(...g.clusters.map(c => c.count))) }, { k: 'linkage', v: g.linkage ?? '—' }] }
    case 'model': { const m = p as ModelPayload; const c = m.card; return [{ k: 'holdout acc.', v: typeof c.holdout_accuracy === 'number' ? (c.holdout_accuracy as number).toFixed(2) : '—' }, { k: 'classes', v: String(c.n_classes ?? '—') }, { k: 'windows', v: String(c.n_windows ?? '—') }, { k: 'features kept', v: `${String(c.n_features_kept ?? '—')} / ${String(c.n_features_in ?? '—')}` }] }
    default: return []
  }
}

/* ---------------- shared strip scaffolding ---------------- */
function Strip({ label, sub, height, t0, t1, children, axis, testid }: { label: string; sub?: string; height: number; t0: number; t1: number; children: (x: XScale, w: number, h: number) => ReactNode; axis?: boolean; testid?: string }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width)
  const x = makeX(t0, t1, w)
  const h = height + (axis ? 18 : 0)
  return (
    <div className="bp-strip" data-testid={testid}>
      <div className="lbl"><b>{label}</b>{sub}</div>
      <div className="sur plot-surface" ref={ref} style={{ height: h }}>
        {size.width > 0 && <svg width={w} height={h}>{children(x, w, height)}{axis && <TimeAxis x={x} y={height + 2} t0={t0} t1={t1} n={7} />}</svg>}
      </div>
    </div>
  )
}
const Veil = ({ on }: { on: boolean }) => on ? <span className="an-stale-pill" style={{ top: 4 }}>⏱ last run shown · stale</span> : null

/** A draggable horizontal cut line (pointer capture on a wide invisible grab rect). */
function DragLineH({ y, value, onChange, width, label, colour = 'var(--amber)', testid }: { y: XScale; value: number; onChange: (v: number) => void; width: number; label: string; colour?: string; testid?: string }) {
  const drag = useRef(false)
  const py = clamp(y(value), 0, y.range()[0])
  const [lo, hi] = [Math.min(...y.domain()), Math.max(...y.domain())]
  const move = (e: React.PointerEvent<SVGRectElement>) => {
    if (!drag.current) return
    const svg = e.currentTarget.ownerSVGElement; if (!svg) return
    const r = svg.getBoundingClientRect()
    onChange(+clamp(y.invert(e.clientY - r.top), lo, hi).toFixed(2))
  }
  return (
    <g data-testid={testid}>
      <line x1={0} x2={width} y1={py} y2={py} stroke={colour} strokeWidth={1.5} />
      <rect x={width - 136} y={py + 3} width={132} height={14} rx={3} fill={colour} />
      <text x={width - 70} y={py + 13} textAnchor="middle" fill="#fff" style={{ fontSize: 10 }}>{label} · drag</text>
      <rect x={0} y={py - 7} width={width} height={14} fill="transparent" style={{ cursor: 'ns-resize' }}
        onPointerDown={e => { drag.current = true; e.currentTarget.setPointerCapture(e.pointerId) }}
        onPointerMove={move}
        onPointerUp={e => { drag.current = false; e.currentTarget.releasePointerCapture(e.pointerId) }} />
    </g>
  )
}
/** A draggable vertical cut line for value-axis plots (histograms). */
function DragLineV({ x, value, onChange, height, label, colour = 'var(--amber)', testid }: { x: XScale; value: number; onChange: (v: number) => void; height: number; label: string; colour?: string; testid?: string }) {
  const drag = useRef(false)
  const px = clamp(x(value), 0, x.range()[1])
  const [lo, hi] = x.domain()
  const move = (e: React.PointerEvent<SVGRectElement>) => {
    if (!drag.current) return
    const svg = e.currentTarget.ownerSVGElement; if (!svg) return
    const r = svg.getBoundingClientRect()
    onChange(+clamp(x.invert(e.clientX - r.left), lo, hi).toFixed(2))
  }
  return (
    <g data-testid={testid}>
      <line x1={px} x2={px} y1={0} y2={height} stroke={colour} strokeWidth={1.5} />
      <text x={px + 5} y={12} fill={colour} style={{ fontSize: 10, fontWeight: 600 }}>{label}</text>
      <rect x={px - 7} y={0} width={14} height={height} fill="transparent" style={{ cursor: 'ew-resize' }}
        onPointerDown={e => { drag.current = true; e.currentTarget.setPointerCapture(e.pointerId) }}
        onPointerMove={move}
        onPointerUp={e => { drag.current = false; e.currentTarget.releasePointerCapture(e.pointerId) }} />
    </g>
  )
}

/** Contiguous runs of the decimated envelope above a threshold (approximate — the core thresholds every sample). */
function runsAbove(env: EnvelopeSeries, thr: number): { start_s: number; end_s: number }[] {
  const out: { start_s: number; end_s: number }[] = []
  let open: number | null = null
  for (let i = 0; i < env.t.length; i++) {
    const v = env.v[i]
    const above = v !== null && v > thr
    if (above && open === null) open = env.t[i]
    if (!above && open !== null) { out.push({ start_s: open, end_s: env.t[i] }); open = null }
  }
  if (open !== null) out.push({ start_s: open, end_s: env.t[env.t.length - 1] + 1 })
  return out
}

/* ---------------- Scores → SpanSet: threshold ---------------- */
function ThresholdProcess({ scores, result, threshold, onThreshold, stale, t0, t1 }: { scores: ScoresPayload | null; result: SpansetPayload | null; threshold: number; onThreshold: (v: number) => void; stale: boolean; t0: number; t1: number }) {
  if (!scores) return <div className="muted mono small">the upstream Scores are not loaded — run the chain so 0{'N'} Matrix profile has a result, then drag the cut here</div>
  const r = scores.value_range ?? [0, 1]
  const above = runsAbove(scores.envelope, threshold)
  const hist = scores.histogram
  const nAbove = hist ? hist.counts.reduce((a, c, i) => a + (hist.edges[i] >= threshold ? c : hist.edges[i + 1] > threshold ? c * ((hist.edges[i + 1] - threshold) / (hist.edges[i + 1] - hist.edges[i])) : 0), 0) : null
  return (
    <>
      <Strip label="scores + cut" sub="upstream Scores · drag the line" height={150} t0={t0} t1={t1} testid="threshold-strip">
        {(x, w, h) => {
          const y = makeY(Math.min(0, r[0]), r[1], h, 20, 4)
          return (
            <>
              <SpanBands spans={above.map((s, i) => ({ ...s, kind: 'selected' as const, id: i, title: 'above the cut (from the decimated envelope)' }))} x={x} height={h} minPx={2} />
              <EnvelopePath t={scores.envelope.t} v={scores.envelope.v} x={x} y={y} stroke="var(--trace)" />
              <YLabels y={y} values={[r[1], r[0]]} />
              <DragLineH y={y} value={threshold} onChange={onThreshold} width={w} label={`threshold ${fmtParam(threshold)}`} testid="threshold-line" />
              <text x={4} y={h - 4} fill="var(--muted-2)">z-norm distance · amber = above the cut now ({above.length} run{above.length === 1 ? '' : 's'}, approximate)</text>
            </>
          )
        }}
      </Strip>
      <Strip label="spans" sub={result ? `${result.n} from the last run` : 'no result yet'} height={34} t0={t0} t1={t1} axis testid="threshold-result">
        {(x, _w, h) => (
          <>
            {result && <SpanBands spans={result.start_s.map((s, i) => ({ start_s: s, end_s: result.end_s[i], kind: 'detected' as const, id: i, title: `${(result.end_s[i] - s).toFixed(0)} s · peak ${result.scores?.[i]?.toFixed(2) ?? '—'}` }))} x={x} height={h} capY={0} capH={3} minPx={2} />}
            {stale && <rect x={0} y={0} width="100%" height={h} fill="rgba(255,255,255,0.6)" />}
            {!result && <text x={4} y={h / 2 + 3} fill="var(--muted)">run the chain to see the resulting spans</text>}
          </>
        )}
      </Strip>
      <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="bp-card-title" style={{ marginTop: 8 }}><h3 style={{ fontSize: 13 }}>Score histogram</h3><span className="sg">{hist ? `${hist.counts.length} bins · drag the cut` : 'no histogram in the payload'}</span></div>
          {hist && <Histogram counts={hist.counts} edges={hist.edges} cut={threshold} onCut={onThreshold} note={`≈ ${Math.round(nAbove ?? 0).toLocaleString()} values above → ${above.length} span${above.length === 1 ? '' : 's'} (from the decimated envelope)`} />}
        </div>
        <div style={{ width: 300 }}>
          <div className="bp-card-title" style={{ marginTop: 8 }}><h3 style={{ fontSize: 13 }}>Spans produced</h3><span className="sg">{result ? `${result.n}${stale ? ' · stale' : ''}` : '—'}</span></div>
          {result && result.n > 0 ? (
            <div className="kv" style={{ gridTemplateColumns: 'auto auto auto', opacity: stale ? 0.6 : 1 }}>
              <span className="k">start</span><span className="k">duration</span><span className="k">peak</span>
              {result.start_s.slice(0, 10).map((s, i) => <span key={i} style={{ display: 'contents' }}><span>{fmtHours(s, 3)}</span><span>{(result.end_s[i] - s).toFixed(0)} s</span><span>{result.scores?.[i]?.toFixed(2) ?? '—'}</span></span>)}
              {result.n > 10 && <span className="muted" style={{ gridColumn: '1 / -1' }}>1–10 of {result.n} (P8 cap)</span>}
            </div>
          ) : <div className="muted mono small">{result ? '0 spans — nothing crossed the threshold' : 'no result yet'}</div>}
        </div>
      </div>
      <div className="bp-legend"><span><i style={{ background: 'var(--band-selected)' }} />above the cut (live)</span><span><i style={{ background: 'var(--band-detected)' }} />spans (last run)</span><span><i style={{ background: 'var(--amber)' }} />threshold · a parameter (amber = cut)</span></div>
    </>
  )
}

function Histogram({ counts, edges, cut, onCut, note, testid }: { counts: number[]; edges: number[]; cut?: number; onCut?: (v: number) => void; note?: string; testid?: string }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width); const h = 120
  const x = makeX(edges[0], edges[edges.length - 1], w, 4, 4)
  const max = Math.max(1, ...counts)
  const y = makeY(0, max, h - 16, 4, 0)
  return (
    <div className="plot-surface" ref={ref} style={{ height: h }} data-testid={testid ?? 'histogram'}>
      {size.width > 0 && (
        <svg width={w} height={h}>
          {counts.map((c, i) => <rect key={i} x={x(edges[i])} y={y(c)} width={Math.max(1, x(edges[i + 1]) - x(edges[i]) - 0.5)} height={y(0) - y(c)} fill={cut !== undefined && edges[i] >= cut ? 'var(--amber)' : 'var(--blue-200)'} />)}
          <text x={4} y={h - 4} fill="var(--muted-2)">{note ?? ''}</text>
          <text x={w - 4} y={h - 4} textAnchor="end" fill="var(--muted-2)">{edges[0].toFixed(1)} … {edges[edges.length - 1].toFixed(1)}</text>
          {cut !== undefined && onCut && <DragLineV x={x} value={cut} onChange={onCut} height={h - 16} label={`cut ${fmtParam(cut)}`} testid="histogram-cut" />}
        </svg>
      )}
    </div>
  )
}

/* ---------------- Signal → Scores: matrix profile ---------------- */
function MatrixProfileProcess({ signal, scores, windowMin, fs, stale, t0, t1 }: { signal: EnvelopeSeries | null; scores: ScoresPayload | null; windowMin: number; fs: number; stale: boolean; t0: number; t1: number }) {
  const mS = windowMin * 60
  const marks = scores ? motifLabels(scores) : []
  const query = marks.find(m => m.label === 'M1a' || m.label === 'M1')
  const nn = marks.find(m => m.label === 'M1b')
  const r = scores?.value_range ?? null
  return (
    <>
      <Strip label="1 · signal" sub={`subsequence length to scale · m = ${mS.toFixed(0)} s (${Math.round(mS * fs)} samples)`} height={110} t0={t0} t1={t1} testid="mp-signal">
        {(x, w, h) => {
          const mW = Math.max(2, x(t0 + mS) - x(t0))
          return (
            <>
              {signal ? <GhostPath ghost={signal} x={x} height={h} opacity={1} /> : <text x={4} y={14} fill="var(--muted)">upstream signal not loaded</text>}
              {signal && <SignalOwnScale env={signal} x={x} h={h} />}
              {query ? <g><rect x={x(query.t_s)} y={4} width={mW} height={h - 8} fill="var(--band-detected)" stroke="var(--blue)" /><text x={x(query.t_s) > w * 0.7 ? x(query.t_s) - 3 : x(query.t_s) + 3} y={h - 6} textAnchor={x(query.t_s) > w * 0.7 ? 'end' : 'start'} fill="var(--blue-600)">query · m = {mS.toFixed(0)} s · at the lowest profile value</text></g>
                : <g><rect x={x(t0 + (t1 - t0) * 0.1)} y={4} width={mW} height={h - 8} fill="var(--band-detected)" stroke="var(--blue)" strokeDasharray="3 2" /><text x={x(t0 + (t1 - t0) * 0.1) + 3} y={h - 6} fill="var(--blue-600)">m = {mS.toFixed(0)} s to scale · no result yet</text></g>}
              {nn && <g><rect x={x(nn.t_s)} y={4} width={mW} height={h - 8} fill="var(--band-annotated)" stroke="var(--green)" /><text x={x(nn.t_s) > w * 0.7 ? x(nn.t_s) - 3 : x(nn.t_s) + mW + 3} y={14} textAnchor={x(nn.t_s) > w * 0.7 ? 'end' : 'start'} fill="#15794f">nearest neighbour · d {nn.v.toFixed(2)}</text></g>}
              {mS * fs > (t1 - t0) * fs && <text x={w / 2} y={h / 2} textAnchor="middle" fill="var(--red)">m ({Math.round(mS * fs)} samples) is longer than the span ({Math.round((t1 - t0) * fs)}) — the core will refuse this</text>}
            </>
          )
        }}
      </Strip>
      <div className="muted mono small" style={{ paddingLeft: 76, marginBottom: 8 }}>2 · distance profile of the query — the core returns only the matrix profile; a per-query distance profile is not served in this slice</div>
      <Strip label="3 · matrix profile" sub={scores ? `${scores.n.toLocaleString()} values · NaN tail ${scores.nan_tail}` : 'no result yet'} height={140} t0={t0} t1={t1} axis testid="mp-profile">
        {(x, w, h) => scores ? <g>{renderByType(scores, { x, width: w, height: h, ghost: null, t0, t1 })}{stale && <rect x={0} y={0} width={w} height={h} fill="rgba(255,255,255,0.55)" />}</g> : <text x={4} y={14} fill="var(--muted)">run the chain to see the profile</text>}
      </Strip>
      {scores?.histogram && (
        <>
          <div className="bp-card-title" style={{ marginTop: 8 }}><h3 style={{ fontSize: 13 }}>Profile values</h3><span className="sg">{r ? `${r[0].toFixed(2)} … ${r[1].toFixed(2)} z-norm distance` : ''} · no surrogate in this slice</span></div>
          <Histogram counts={scores.histogram.counts} edges={scores.histogram.edges} testid="mp-histogram" />
        </>
      )}
      <div className="bp-legend"><span><i style={{ background: 'var(--band-detected)', border: '1px solid var(--blue)' }} />query subsequence</span><span><i style={{ background: 'var(--band-annotated)', border: '1px solid var(--green)' }} />nearest neighbour</span><span><i style={{ background: 'var(--blue)' }} />profile</span><span><i style={{ background: 'var(--red)' }} />discord</span></div>
    </>
  )
}

/** The upstream signal on its own real scale with a mV axis. */
function SignalOwnScale({ env, x, h }: { env: EnvelopeSeries; x: XScale; h: number }) {
  let lo = Infinity, hi = -Infinity
  for (const v of env.v) if (v !== null) { if (v < lo) lo = v; if (v > hi) hi = v }
  if (!(lo <= hi)) return null
  const y = makeY(lo, hi, h)
  return <g><EnvelopePath t={env.t} v={env.v} x={x} y={y} stroke="var(--trace)" /><YLabels y={y} values={[hi, lo]} unit="mV" /></g>
}

/* ---------------- Signal → Encoding: dSAX ---------------- */
function dsaxTiles(enc: EncodingSymbolicPayload | null): { k: string; v: string }[] {
  if (!enc || enc.alphabet_size !== 3) return []
  const n = enc.symbols.length
  const c = [0, 0, 0]
  for (const s of enc.symbols) if (s >= 0 && s < 3) c[s]++
  const pct = n ? Math.round(100 * c[1] / n) : 0
  return [{ k: 'segments', v: n.toLocaleString() }, { k: 'down (d)', v: String(c[0]) }, { k: 'same', v: String(c[1]) }, { k: 'up (u)', v: String(c[2]) }, { k: '% SAME', v: `${pct} %` }]
}
function DsaxProcess({ signal, enc, stale, t0, t1, trend }: { signal: EnvelopeSeries | null; enc: EncodingSymbolicPayload | null; stale: boolean; t0: number; t1: number; trend: string }) {
  const sps = enc?.seconds_per_symbol ?? null
  const paa = enc?.paa ?? null
  const deltas = paa ? paa.slice(1).map((v, i) => v - paa[i]) : null
  const tiles = dsaxTiles(enc)
  // the strip caption never contradicts the badge: a result without PAA/cutlines says so (the bridge keeps
  // adapter meta in a sidecar since critique r1, so a cached re-run still carries them)
  const noMeta = enc ? (!paa ? 'PAA not served for this result · re-run this stage to compute it' : !sps ? 'seconds per symbol not served for this result' : null) : 'run the chain to see the learned cutlines'
  return (
    <>
      <Strip label="signal + PAA" sub={sps ? `${fmtParam(sps)} s segments` : 'segments'} height={110} t0={t0} t1={t1} testid="dsax-signal">
        {(x, _w, h) => (
          <>
            {signal && <SignalOwnScale env={signal} x={x} h={h} />}
            {paa && sps && enc && <PaaSteps paa={paa} t0={enc.t0_s} sps={sps} x={x} h={h} />}
            {!signal && <text x={4} y={14} fill="var(--muted)">upstream signal not loaded</text>}
          </>
        )}
      </Strip>
      <Strip label="Δ per segment + cutlines" sub={enc?.cutline_domain ? `${enc.cutline_domain} domain` : 'rise per segment'} height={90} t0={t0} t1={t1} testid="dsax-cutlines">
        {(x, w, h) => {
          if (!deltas || !sps || !enc) return <text x={4} y={14} fill="var(--muted)" data-testid="dsax-nometa">{noMeta}</text>
          const cuts = enc.cutlines ?? []
          const ext = Math.max(...deltas.map(Math.abs), ...cuts.map(Math.abs), 1e-9)
          const y = makeY(-ext, ext, h, 6, 6)
          const cw = Math.max(1, x(t0 + sps) - x(t0) - 0.5)
          return (
            <>
              <line x1={0} x2={w} y1={y(0)} y2={y(0)} stroke="var(--border)" />
              {deltas.map((d, i) => <rect key={i} x={x(enc.t0_s + (i + 1) * sps)} y={Math.min(y(0), y(d))} width={cw} height={Math.abs(y(d) - y(0))} fill={enc.alphabet_size === 3 ? SYM3[enc.symbols[i + 1] ?? 1] : 'var(--blue)'} opacity={0.8} />)}
              {cuts.map((c, i) => <g key={i} data-testid="dsax-cutline"><line x1={0} x2={w} y1={y(c)} y2={y(c)} stroke="var(--red)" strokeDasharray="4 3" /><text x={c >= 0 ? w - 4 : 4} y={c >= 0 ? y(c) - 3 : y(c) + 10} textAnchor={c >= 0 ? 'end' : 'start'} fill="var(--red)" style={{ paintOrder: 'stroke', stroke: '#fff', strokeWidth: 3 }}>{c > 0 ? '+' : ''}{c.toExponential(2)} · learned · not a parameter</text></g>)}
              {!cuts.length && <text x={4} y={14} fill="var(--muted)">cutlines not served for this result · the Δ bars are drawn from the PAA</text>}
              <text x={4} y={h - 4} fill="var(--muted-2)">Δ PAA between consecutive segments — approximates the adapter's {trend} estimator</text>
            </>
          )
        }}
      </Strip>
      <Strip label={`dSAX k ${enc?.alphabet_size ?? '?'}`} sub={enc ? `${enc.n_symbols} symbols` : ''} height={40} t0={t0} t1={t1} axis testid="dsax-strip">
        {(x, w, h) => enc ? <g>{renderByType(enc, { x, width: w, height: h, ghost: null, t0, t1 })}{stale && <rect x={0} y={0} width={w} height={h} fill="rgba(255,255,255,0.55)" />}</g> : <text x={4} y={14} fill="var(--muted)">no encoding yet</text>}
      </Strip>
      <div className="bp-legend"><span><i style={{ background: SYM3[0] }} />down</span><span><i style={{ background: SYM3[1] }} />same</span><span><i style={{ background: SYM3[2] }} />up</span><span><i style={{ background: 'var(--blue-600)' }} />PAA mean · own scale</span><span><i style={{ background: 'var(--red)' }} />cutlines · learned</span>{enc?.representatives && <span className="muted">representatives {enc.representatives.map(v => v.toExponential(1)).join(' / ')}</span>}</div>
      {tiles.length > 0 && <div className="bp-tiles" style={{ gridTemplateColumns: 'repeat(5, 1fr)', marginLeft: 76 }} data-testid="dsax-tiles">{tiles.map(t => <div className="bp-tile" key={t.k}><div className="k" title={t.k}>{t.k}</div><div className="v">{t.v}</div></div>)}</div>}
    </>
  )
}

/* ---------------- Spans vs cut (frame chain-7b right column) ---------------- */
/** Span count for ~40 cut values across the score range, from the same decimated envelope the histogram uses;
 *  the current cut is marked. The null curve is not computable in this slice and says so. */
function SpansVsCut({ scores, threshold, onThreshold, resultN, stale }: { scores: ScoresPayload | null; threshold: number; onThreshold: (v: number) => void; resultN: number | null; stale: boolean }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width); const h = 120
  const curve = useMemo(() => {
    if (!scores) return null
    const r = scores.value_range ?? [0, 1]
    const lo = Math.min(0, r[0]), hi = r[1]
    if (!(hi > lo)) return null
    const cuts: number[] = []; const counts: number[] = []
    for (let k = 0; k <= 40; k++) { const c = lo + (hi - lo) * k / 40; cuts.push(c); counts.push(runsAbove(scores.envelope, c).length) }
    return { cuts, counts, lo, hi }
  }, [scores])
  const nowN = scores ? runsAbove(scores.envelope, threshold).length : null
  return (
    <div className="card bp-curve" data-testid="spans-vs-cut">
      <div className="row"><span className="b">Spans vs cut</span><span className="muted mono small" style={{ marginLeft: 'auto' }}>{curve ? '41 cut values · decimated envelope' : 'needs the upstream Scores'}</span></div>
      <div className="plot-surface sur" ref={ref} style={{ height: h }}>
        {size.width > 0 && curve && (() => {
          const x = makeX(curve.lo, curve.hi, w, 6, 6)
          const y = makeY(0, Math.max(1, ...curve.counts), h - 18, 6, 0)
          return (
            <svg width={w} height={h}>
              <path d={polylinePath(curve.cuts, curve.counts, x, y)} fill="none" stroke="var(--blue)" strokeWidth={1.4} />
              <line x1={4} x2={w - 4} y1={h - 26} y2={h - 26} stroke="var(--muted-2)" strokeDasharray="3 3" />
              <text x={w / 2} y={h - 30} textAnchor="middle" fill="var(--muted-2)">null curve · not in this slice</text>
              <YLabels y={y} values={[Math.max(1, ...curve.counts), 0]} digits={0} />
              <text x={4} y={h - 4} fill="var(--muted-2)">{curve.lo.toFixed(1)}</text>
              <text x={w - 4} y={h - 4} textAnchor="end" fill="var(--muted-2)">{curve.hi.toFixed(1)} · cut value</text>
              {nowN !== null && <circle cx={x(threshold)} cy={y(nowN)} r={3.5} fill="var(--amber)" stroke="#fff" strokeWidth={1} />}
              <DragLineV x={x} value={threshold} onChange={onThreshold} height={h - 18} label={`cut ${fmtParam(threshold)} → ${nowN ?? '—'}`} testid="spans-vs-cut-line" />
            </svg>
          )
        })()}
        {size.width > 0 && !curve && <div className="an-plot-empty">run the chain so the upstream Scores are loaded</div>}
      </div>
      <div className="muted mono small" style={{ marginTop: 6 }}>{nowN !== null ? `≈ ${nowN} span${nowN === 1 ? '' : 's'} at the current cut (approximate)` : '—'}{resultN !== null ? ` · last run ${resultN}${stale ? ' · stale' : ''}` : ''} · drag the line to move the cut</div>
    </div>
  )
}
function PaaSteps({ paa, t0, sps, x, h }: { paa: number[]; t0: number; sps: number; x: XScale; h: number }) {
  let lo = Infinity, hi = -Infinity
  for (const v of paa) { if (v < lo) lo = v; if (v > hi) hi = v }
  const y = makeY(lo, hi, h)
  const t: number[] = []; const v: number[] = []
  paa.forEach((p, i) => { t.push(t0 + i * sps, t0 + (i + 1) * sps); v.push(p, p) })
  return <path d={polylinePath(t, v, x, y)} fill="none" stroke="var(--blue-600)" strokeWidth={1.4} />
}

/* ---------------- any other block: the row renderer at full size ---------------- */
function GenericProcess({ payload, ghost, stale, t0, t1, caption }: { payload: Payload | null; ghost: EnvelopeSeries | null; stale: boolean; t0: number; t1: number; caption: string }) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width); const h = 180
  const x = makeX(t0, t1, w)
  return (
    <>
      <div className="muted mono small" style={{ marginBottom: 8 }}>{caption} · this signature has no bespoke process view yet (spec §6.8 table) — the output is shown at full size</div>
      <div className="plot-surface" ref={ref} style={{ height: h, position: 'relative' }} data-testid="generic-process">
        {size.width > 0 && (payload ? renderByType(payload, { x, width: w, height: h, ghost, t0, t1 }) : <div className="an-plot-empty">no result yet · run the chain</div>)}
        {stale && payload && <><div className="an-plot-veil" /><Veil on /></>}
      </div>
      <div style={{ paddingTop: 2 }}><svg width="100%" height={20}><TimeAxis x={x} y={2} t0={t0} t1={t1} n={7} /></svg></div>
    </>
  )
}
