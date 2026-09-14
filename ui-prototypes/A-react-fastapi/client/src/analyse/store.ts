/* Analyse run store — module-level so a run survives navigating Chain ↔ Block and any
   page can start/cancel/observe it. Persists only the small bits (staleFrom) in
   sessionStorage; payloads are refetched from the server on a browser reload
   (jobs live in server memory, see server/runs.py).

   Robustness (critique r1): the SSE stream is the fast path, never the only path. Any
   stream error closes the socket and switches to polling GET /api/runs/{id} every 2 s;
   while a job is locally "running" and the socket is not OPEN the same poll runs as a
   liveness fallback; the run_end snapshot fetch retries with backoff (0.5/1/2/4 s) and
   then falls back to the poll; payloads whose fetch failed are re-fetched on every
   re-sync; when polling itself fails for > 10 s the page shows one "lost contact" card. */
import { useSyncExternalStore } from 'react'
import {
  ApiError, cancelRun as apiCancel, getRun, getStepPayload, startRun as apiStart, subscribeRun,
  type ErrorPayload, type JobSnapshot, type Payload, type RunEvent, type SseHandle, type Step, type StepStatus,
} from '../api'
import { rememberMyJob } from '../state'

export type RunErrorKind = 'attach' | 'stream' | 'contact'
export interface RunState {
  job: JobSnapshot | null
  payloads: Record<number, Payload>
  stepStartedAt: Record<number, number>   // client-clock ms when a step started (server ts + clock offset)
  live: boolean                            // an SSE subscription is open
  polling: boolean                         // the 2 s GET /api/runs/{id} fallback is active
  error: string | null                     // e.g. the job vanished (server restarted) — see errorKind for the card title
  errorKind: RunErrorKind | null
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

const EMPTY_RUN: RunState = { job: null, payloads: {}, stepStartedAt: {}, live: false, polling: false, error: null, errorKind: null }
let state: AnalyseState = { staleFrom: loadStale(), run: EMPTY_RUN, tick: 0 }
const listeners = new Set<() => void>()
let handle: SseHandle | null = null
let ticker: number | null = null
let poller: number | null = null
let pollInflight = false
let pollFailSince: number | null = null
let finalConfirmed = false          // a terminal snapshot has been fetched from GET /api/runs/{id}
let clockOffsetS = 0                // client seconds − server seconds (from the last snapshot)
let finalRetry: number | null = null

const POLL_MS = 2000
const LOST_CONTACT_MS = 10_000
const FINAL_BACKOFF_MS = [500, 1000, 2000, 4000]

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

/* ---- helpers ---- */
const isRunning = (j: JobSnapshot | null | undefined) => !!j && (j.status === 'running' || j.status === 'queued')
type FetchFailed = ErrorPayload & { fetch_failed?: boolean }
/** A payload slot that must be (re)fetched: missing, or an error card written by a failed client fetch
 *  (a server-side serialisation error is a real result and is NOT refetched). */
export const needsRefetch = (p: Payload | undefined) => !p || ('error' in p && (p as FetchFailed).fetch_failed === true)

function noteClock(snap: JobSnapshot) {
  // elapsed_s is measured on the server clock: started_at + elapsed_s = server "now"
  if (typeof snap.started_at === 'number' && typeof snap.elapsed_s === 'number') clockOffsetS = Date.now() / 1000 - (snap.started_at + snap.elapsed_s)
}

/* ---- run lifecycle ---- */
function startTicker() {
  if (ticker !== null) return
  ticker = window.setInterval(() => { if (state.run.job?.status === 'running') set({ tick: state.tick + 1 }); else stopTicker() }, 250)
}
function stopTicker() { if (ticker !== null) { window.clearInterval(ticker); ticker = null } }

function closeSocket() { if (handle) { handle.close(); handle = null } if (state.run.live) setRun({ live: false }) }
function stopPolling() { if (poller !== null) { window.clearInterval(poller); poller = null } pollFailSince = null; pollInflight = false; if (state.run.polling) setRun({ polling: false }) }
function cancelFinalRetry() { if (finalRetry !== null) { window.clearTimeout(finalRetry); finalRetry = null } }
function detach() { closeSocket(); stopPolling(); cancelFinalRetry(); stopTicker() }

/** Forget the current run (importing a template, applying a history recipe, changing source). */
export function resetRun() { detach(); finalConfirmed = false; set({ run: EMPTY_RUN }) }

async function fetchPayload(jobId: number, i: number) {
  try {
    const p = await getStepPayload(jobId, i)
    if (state.run.job?.job_id !== jobId) return
    setRun({ payloads: { ...state.run.payloads, [i]: p } })
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e)
    if (state.run.job?.job_id !== jobId) return
    const p: FetchFailed = { type: 'error', error: `payload fetch failed: ${msg}`, summary: 'payload unavailable', fetch_failed: true }
    setRun({ payloads: { ...state.run.payloads, [i]: p } })
  }
}

/** Apply a fresh snapshot and (re)fetch every payload slot that is missing or failed to fetch. */
async function applySnapshot(jobId: number, snap: JobSnapshot) {
  if (state.run.job?.job_id !== jobId) return
  noteClock(snap)
  setRun({ job: snap })
  const gaps = snap.steps.filter(s => s.has_payload && needsRefetch(state.run.payloads[s.index]))
  await Promise.all(gaps.map(s => fetchPayload(jobId, s.index)))
}

/** True when the job is terminal, confirmed by a snapshot, and every payload has landed. */
function inSync(): boolean {
  const job = state.run.job
  if (!job) return true
  if (isRunning(job) || !finalConfirmed) return false
  return !job.steps.some(s => s.has_payload && needsRefetch(state.run.payloads[s.index]))
}

async function resync(jobId: number): Promise<boolean> {
  const snap = await getRun(jobId)          // throws on transport/HTTP failure
  if (state.run.job?.job_id !== jobId) return true
  if (!isRunning(snap)) finalConfirmed = true
  await applySnapshot(jobId, snap)
  return inSync()
}

function clearTransientError() {
  if (state.run.errorKind === 'stream' || state.run.errorKind === 'contact') setRun({ error: null, errorKind: null })
}

async function pollTick(jobId: number, force = false) {
  const job = state.run.job
  if (!job || job.job_id !== jobId) { stopPolling(); return }
  if (inSync()) { stopPolling(); closeSocket(); return }
  // a healthy open stream is the source of truth while the job runs; poll only when it is not
  const streamHealthy = handle !== null && handle.isOpen() && state.run.errorKind !== 'stream'
  const gaps = job.steps.some(s => s.has_payload && needsRefetch(state.run.payloads[s.index]))
  if (!force && isRunning(job) && streamHealthy && !gaps) return
  if (pollInflight) return
  pollInflight = true
  try {
    const ok = await resync(jobId)
    pollFailSince = null
    clearTransientError()
    if (ok) { stopPolling(); closeSocket() }
  } catch {
    pollFailSince ??= Date.now()
    if (Date.now() - pollFailSince > LOST_CONTACT_MS && state.run.errorKind !== 'contact')
      setRun({ error: `lost contact with the bridge · retrying every ${POLL_MS / 1000} s`, errorKind: 'contact' })
  } finally { pollInflight = false }
}

function startPolling(jobId: number) {
  if (poller !== null) return
  setRun({ polling: true })
  poller = window.setInterval(() => { void pollTick(jobId) }, POLL_MS)
}

/** The "Retry" button on the lost-contact card: poll right now instead of waiting for the interval. */
export function retryNow() {
  const job = state.run.job
  if (!job) return
  pollFailSince = null
  if (state.run.errorKind === 'contact') setRun({ error: 'retrying…', errorKind: 'contact' })
  startPolling(job.job_id)
  void pollTick(job.job_id, true)
}

function patchStep(i: number, patch: Partial<JobSnapshot['steps'][number]>) {
  const job = state.run.job
  if (!job || !job.steps[i]) return
  const steps = job.steps.map((s, k) => (k === i ? { ...s, ...patch } : s))
  setRun({ job: { ...job, steps } })
}

/** run_end: apply the event's own fields at once (status, timings, db_run_id, error) so the page
 *  reaches its final state even if the follow-up snapshot fetch fails; then confirm with GET. */
function applyRunEnd(job: JobSnapshot, e: RunEvent): JobSnapshot {
  const status = e.status as JobSnapshot['status']
  const at = typeof e.step === 'number' ? (e.step as number) : null
  let steps = job.steps
  if (status === 'failed') steps = steps.map((s, k) => k === at && s.status !== 'done' ? { ...s, status: 'failed' as StepStatus } : s.status === 'pending' ? { ...s, status: 'blocked' as StepStatus } : s)
  if (status === 'cancelled') steps = steps.map((s, k) => (k === at && s.status !== 'done') || s.status === 'pending' ? { ...s, status: 'cancelled' as StepStatus } : s)
  const error = (e.error as JobSnapshot['error']) ?? (status === 'cancelled' ? { step: at, message: String(e.message ?? 'cancelled'), type: 'RecipeCancelled' } : job.error)
  return {
    ...job, status, steps, error,
    step_timings: (e.step_timings as JobSnapshot['step_timings']) ?? job.step_timings,
    detections_written: (e.detections_written as number | null | undefined) ?? job.detections_written,
    config_hash: (e.config_hash as string | null | undefined) ?? job.config_hash,
    db_run_id: (e.db_run_id as number | null | undefined) ?? job.db_run_id,
    finished_at: typeof e.ts === 'number' ? e.ts : job.finished_at,
    elapsed_s: typeof e.elapsed_s === 'number' ? (e.elapsed_s as number) : job.elapsed_s,
  }
}

function syncFinal(jobId: number, attempt: number) {
  finalRetry = null
  resync(jobId).then(ok => {
    if (state.run.job?.job_id !== jobId) return
    clearTransientError()
    if (ok) { closeSocket(); stopPolling() } else startPolling(jobId)
  }).catch(err => {
    if (state.run.job?.job_id !== jobId) return
    const msg = err instanceof ApiError ? err.message : String(err)
    if (attempt < FINAL_BACKOFF_MS.length) {
      setRun({ error: `run finished · result fetch failed (${msg}) · retry ${attempt + 1} of ${FINAL_BACKOFF_MS.length}`, errorKind: 'stream' })
      finalRetry = window.setTimeout(() => syncFinal(jobId, attempt + 1), FINAL_BACKOFF_MS[attempt])
    } else {
      setRun({ error: 'run stream interrupted · polling', errorKind: 'stream' })
      startPolling(jobId)
    }
  })
}

function onEvent(jobId: number, e: RunEvent) {
  if (state.run.job?.job_id !== jobId) return
  const job = state.run.job
  switch (e.event) {
    case 'hello': {
      const snap = e as unknown as JobSnapshot & RunEvent
      // the hello carries a full snapshot; keep any payloads we already have
      noteClock(snap)
      setRun({ job: { ...snap } })
      for (const s of snap.steps) if (s.has_payload && needsRefetch(state.run.payloads[s.index])) fetchPayload(jobId, s.index)
      break
    }
    case 'step_start': {
      const i = e.step as number
      const n = e.n_steps as number
      const steps = job.steps.map((s, k) => (k === i ? { ...s, status: 'running' as StepStatus, started_at: e.ts, cached_predicted: !!e.cached_predicted }
        : k > i && k < n && s.status !== 'done' ? { ...s, status: 'pending' as StepStatus } : s))
      // the event's ts is the server clock: a replayed step_start (late subscriber after a reload)
      // must not restart the elapsed counter from zero (critique r1)
      const startedMs = typeof e.ts === 'number' ? (e.ts + clockOffsetS) * 1000 : Date.now()
      setRun({ job: { ...job, status: 'running', current_step: i, steps }, stepStartedAt: { ...state.run.stepStartedAt, [i]: startedMs } })
      startTicker()
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
      // provisional final state from the event itself, then the definitive snapshot (with backoff)
      finalConfirmed = false
      setRun({ job: applyRunEnd(job, e), live: false })
      handle = null   // api.ts closed the EventSource on run_end
      syncFinal(jobId, 0)
      break
    }
  }
}

function onStreamError(jobId: number, reason: string) {
  if (state.run.job?.job_id !== jobId) return
  if (!handle) return                                  // already closed (run_end landed)
  closeSocket()
  setRun({ error: `${reason} · polling`, errorKind: 'stream' })
  startPolling(jobId)
  void pollTick(jobId, true)
}

function subscribe(jobId: number) {
  closeSocket(); stopPolling(); cancelFinalRetry()
  finalConfirmed = false
  handle = subscribeRun(jobId, e => onEvent(jobId, e), reason => onStreamError(jobId, reason))
  setRun({ live: true })
  startTicker()
  startPolling(jobId)   // liveness fallback: polls only while the socket is not OPEN (or after an error)
}

/** Start a run for the current chain and follow it. Throws ApiError on a refused start
 *  (e.g. 422 for a stage over its local ceiling) — the previous run is kept in that case. */
export async function startRun(recording_id: number, span: [number, number] | null, steps: Step[], px = 1200): Promise<JobSnapshot> {
  const snap = await apiStart(recording_id, span, steps, px)
  detach()
  rememberMyJob(snap.job_id)   // the header's "N need you" counts only this tab's failures
  clearStale()                 // the run covers the chain as it is now; later edits mark stale again
  noteClock(snap)
  set({ run: { ...EMPTY_RUN, job: snap } })
  subscribe(snap.job_id)
  return snap
}

/** Re-attach to a job (page reload mid-run, or a run started from the other page). */
export async function attachRun(jobId: number): Promise<void> {
  if (state.run.job?.job_id === jobId && (state.run.live || state.run.polling || !isRunning(state.run.job))) return
  try {
    const snap = await getRun(jobId)
    noteClock(snap)
    finalConfirmed = !isRunning(snap)
    setRun({ job: snap, error: null, errorKind: null })
    for (const s of snap.steps) if (s.has_payload && needsRefetch(state.run.payloads[s.index])) fetchPayload(jobId, s.index)
    if (isRunning(snap)) subscribe(jobId)
  } catch (e) {
    const msg = e instanceof ApiError ? (e.status === 404 ? `job ${jobId} is gone — the bridge was restarted (jobs live in server memory)` : e.message) : String(e)
    set({ run: { ...EMPTY_RUN, error: msg, errorKind: 'attach' } })
    throw e
  }
}

export async function cancelCurrent(): Promise<string | null> {
  const job = state.run.job
  if (!job || job.status !== 'running') return null
  const r = await apiCancel(job.job_id)
  return r.note
}

/** Elapsed seconds of the running step, on the server's clock. */
export function stepElapsed(i: number): number {
  const t = state.run.stepStartedAt[i]
  if (t) return Math.max(0, (Date.now() - t) / 1000)
  const s = state.run.job?.steps[i]
  if (s?.started_at) return Math.max(0, Date.now() / 1000 - clockOffsetS - s.started_at)
  return 0
}
