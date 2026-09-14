/* Analyse run store — module-level so a run survives navigating Chain ↔ Block and any
   page can start/cancel/observe it. Persists only the small bits (staleFrom) in
   sessionStorage; payloads are refetched from the server on a browser reload
   (jobs live in server memory, see server/runs.py). */
import { useSyncExternalStore } from 'react'
import {
  ApiError, cancelRun as apiCancel, getRun, getStepPayload, startRun as apiStart, subscribeRun,
  type JobSnapshot, type Payload, type RunEvent, type Step, type StepStatus,
} from '../api'

export interface RunState {
  job: JobSnapshot | null
  payloads: Record<number, Payload>
  stepStartedAt: Record<number, number>   // Date.now() when this page saw step_start (for the elapsed ticker)
  live: boolean                            // an SSE subscription is open
  error: string | null                     // e.g. the job vanished (server restarted)
}
export interface AnalyseState {
  staleFrom: number | null   // first step index edited since the last run started; null = nothing stale
  run: RunState
  tick: number               // bumps every 250 ms while a run is live so elapsed labels re-render
}

const SS_KEY = 'ub-proto-a:analyse:staleFrom'
function loadStale(): number | null {
  try { const raw = sessionStorage.getItem(SS_KEY); return raw ? (JSON.parse(raw) as number | null) : null } catch { return null }
}
function saveStale(v: number | null) { try { sessionStorage.setItem(SS_KEY, JSON.stringify(v)) } catch { /* ignore */ } }

const EMPTY_RUN: RunState = { job: null, payloads: {}, stepStartedAt: {}, live: false, error: null }
let state: AnalyseState = { staleFrom: loadStale(), run: EMPTY_RUN, tick: 0 }
const listeners = new Set<() => void>()
let unsubscribe: (() => void) | null = null
let ticker: number | null = null

function emit() { for (const l of listeners) l() }
function set(patch: Partial<AnalyseState>) { state = { ...state, ...patch }; emit() }
function setRun(patch: Partial<RunState>) { set({ run: { ...state.run, ...patch } }) }

export function getAnalyseState() { return state }
export function useAnalyseStore(): AnalyseState {
  return useSyncExternalStore(l => { listeners.add(l); return () => { listeners.delete(l) } }, () => state, () => state)
}

/* ---- staleness ---- */
export function markStale(index: number) {
  const next = state.staleFrom === null ? index : Math.min(state.staleFrom, index)
  if (next !== state.staleFrom) { saveStale(next); set({ staleFrom: next }) }
}
export function clearStale() { if (state.staleFrom !== null) { saveStale(null); set({ staleFrom: null }) } }

/* ---- run lifecycle ---- */
function startTicker() {
  if (ticker !== null) return
  ticker = window.setInterval(() => { if (state.run.job?.status === 'running') set({ tick: state.tick + 1 }); else stopTicker() }, 250)
}
function stopTicker() { if (ticker !== null) { window.clearInterval(ticker); ticker = null } }

function detach() { if (unsubscribe) { unsubscribe(); unsubscribe = null } setRun({ live: false }); stopTicker() }

/** Forget the current run (importing a template, applying a history recipe, changing source). */
export function resetRun() { detach(); set({ run: EMPTY_RUN }) }

async function fetchPayload(jobId: number, i: number) {
  try {
    const p = await getStepPayload(jobId, i)
    if (state.run.job?.job_id !== jobId) return
    setRun({ payloads: { ...state.run.payloads, [i]: p } })
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e)
    if (state.run.job?.job_id !== jobId) return
    setRun({ payloads: { ...state.run.payloads, [i]: { type: 'error', error: `payload fetch failed: ${msg}`, summary: 'payload unavailable' } } })
  }
}

function patchStep(i: number, patch: Partial<JobSnapshot['steps'][number]>) {
  const job = state.run.job
  if (!job || !job.steps[i]) return
  const steps = job.steps.map((s, k) => (k === i ? { ...s, ...patch } : s))
  setRun({ job: { ...job, steps } })
}

function onEvent(jobId: number, e: RunEvent) {
  if (state.run.job?.job_id !== jobId) return
  const job = state.run.job
  switch (e.event) {
    case 'hello': {
      const snap = e as unknown as JobSnapshot & RunEvent
      // the hello carries a full snapshot; keep any payloads we already have
      setRun({ job: { ...snap } })
      for (const s of snap.steps) if (s.has_payload && !state.run.payloads[s.index]) fetchPayload(jobId, s.index)
      break
    }
    case 'step_start': {
      const i = e.step as number
      const n = e.n_steps as number
      const steps = job.steps.map((s, k) => (k === i ? { ...s, status: 'running' as StepStatus, started_at: e.ts, cached_predicted: !!e.cached_predicted }
        : k > i && k < n && s.status !== 'done' ? { ...s, status: 'pending' as StepStatus } : s))
      setRun({ job: { ...job, status: 'running', current_step: i, steps }, stepStartedAt: { ...state.run.stepStartedAt, [i]: Date.now() } })
      break
    }
    case 'step_done': {
      const i = e.step as number
      patchStep(i, { status: 'done', elapsed_s: e.elapsed_s as number, summary: (e.summary as string) ?? null, kind: (e.kind as JobSnapshot['steps'][number]['kind']) ?? null, has_payload: true, cached_predicted: !!e.cached_predicted })
      fetchPayload(jobId, i)
      break
    }
    case 'cancel_requested': break
    case 'run_end': {
      // the definitive state (step_timings, db_run_id, error) comes from the snapshot
      getRun(jobId).then(snap => {
        if (state.run.job?.job_id !== jobId) return
        setRun({ job: snap, live: false })
        for (const s of snap.steps) if (s.has_payload && !state.run.payloads[s.index]) fetchPayload(jobId, s.index)
      }).catch(err => setRun({ error: err instanceof ApiError ? err.message : String(err), live: false }))
      stopTicker()
      break
    }
  }
}

function subscribe(jobId: number) {
  if (unsubscribe) unsubscribe()
  unsubscribe = subscribeRun(jobId, e => onEvent(jobId, e), () => { /* EventSource retries on its own; run_end closes it */ })
  setRun({ live: true })
  startTicker()
}

/** Start a run for the current chain and follow it. Throws ApiError on a refused start. */
export async function startRun(recording_id: number, span: [number, number] | null, steps: Step[], px = 1200): Promise<JobSnapshot> {
  detach()
  set({ run: { ...EMPTY_RUN } })
  const snap = await apiStart(recording_id, span, steps, px)
  clearStale()   // the run covers the chain as it is now; later edits mark stale again
  setRun({ job: snap, payloads: {}, stepStartedAt: {}, error: null })
  subscribe(snap.job_id)
  return snap
}

/** Re-attach to a job (page reload mid-run, or a run started from the other page). */
export async function attachRun(jobId: number): Promise<void> {
  if (state.run.job?.job_id === jobId && (state.run.live || state.run.job.status !== 'running')) return
  try {
    const snap = await getRun(jobId)
    setRun({ job: snap, error: null })
    for (const s of snap.steps) if (s.has_payload && !state.run.payloads[s.index]) fetchPayload(jobId, s.index)
    if (snap.status === 'running' || snap.status === 'queued') subscribe(jobId)
  } catch (e) {
    const msg = e instanceof ApiError ? (e.status === 404 ? `job ${jobId} is gone — the bridge was restarted (jobs live in server memory)` : e.message) : String(e)
    set({ run: { ...EMPTY_RUN, error: msg } })
    throw e
  }
}

export async function cancelCurrent(): Promise<string | null> {
  const job = state.run.job
  if (!job || job.status !== 'running') return null
  const r = await apiCancel(job.job_id)
  return r.note
}

/** Elapsed seconds of the running step, from this page's clock. */
export function stepElapsed(i: number): number {
  const t = state.run.stepStartedAt[i]
  if (t) return (Date.now() - t) / 1000
  const s = state.run.job?.steps[i]
  if (s?.started_at) return Math.max(0, Date.now() / 1000 - s.started_at)
  return 0
}
