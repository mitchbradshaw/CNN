/* Typed client for the FastAPI bridge (server/app.py). One function per route.
   Every non-2xx response throws ApiError carrying the server's message and, for
   500s, the traceback — so a backend failure is never silent in the page. */

export class ApiError extends Error {
  status: number
  detail: unknown
  traceback?: string
  constructor(status: number, message: string, detail?: unknown, traceback?: string) {
    super(message)
    this.status = status
    this.detail = detail
    this.traceback = traceback
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'content-type': 'application/json' }, ...init })
  if (!r.ok) {
    let body: any = null
    try { body = await r.json() } catch { /* not json */ }
    const msg = body?.error ?? (typeof body?.detail === 'string' ? body.detail : body?.detail?.message) ?? `${r.status} ${r.statusText}`
    throw new ApiError(r.status, msg, body?.detail ?? body, body?.traceback)
  }
  return r.json() as Promise<T>
}
const post = <T,>(path: string, body: unknown) => req<T>(path, { method: 'POST', body: JSON.stringify(body) })

/* ---------------- explore ---------------- */
export interface ChannelRef { id: number; channel: number; name: string; npy_exists: boolean }
export interface RecordingFile {
  source_file: string; fs: number; n_samples: number; duration_h: number; n_channels: number; held_out: boolean
  held_out_reason: string | null; channels: ChannelRef[]
}
export interface CoverageRow {
  id: number; channel: number; name: string
  annotations: number[]; detections: number[]; both: number[]; disagree: number[]
  counts: { annotations: number; detections: number; disagree: number; reviewed_pct: number | null }
}
export interface Coverage {
  source_file: string; fs: number; n_samples: number; duration_h: number; bins: number; bin_h: number; bin_edges_h: number[]
  rows: CoverageRow[]; verdict_counts: Record<string, number>; n_detection_runs: number; held_out: boolean; compute_ms: number
}
export interface Ribbons { buckets: number; bucket_s: number; coverage: (string | null)[]; detection_density: number[] }
export interface Channel {
  id: number; source_file: string; channel: number; fs: number; n_samples: number; duration_s: number; name: string; held_out: boolean; npy_path: string
  summary: { annotations: number; detections: number; detection_runs: number }; ribbons: Ribbons; y_range: [number, number]
}
export interface Envelope { t: number[]; v: (number | null)[]; n_source: number; n_points: number; decimated: boolean }
export interface WindowData { recording_id: number; fs: number; n_samples: number; t0_s: number; t1_s: number; envelope: Envelope; decimate_ms: number }
export interface Annotation { id: number; start_s: number; end_s: number; verdict: string; tag: string | null; note: string | null; source: string }
export interface Detection { id: number; start_s: number; end_s: number; score: number | null; run_id: number }
export interface Spans { recording_id: number; t0_s: number; t1_s: number; annotations: Annotation[]; detections: Detection[]; annotations_capped: boolean; detections_capped: boolean }

export const getRecordings = () => req<RecordingFile[]>('/api/recordings')
export const getCoverage = (file: string, bins = 57, verdicts?: string[]) =>
  req<Coverage>(`/api/corpus/${encodeURIComponent(file)}/coverage?bins=${bins}${verdicts?.length ? `&verdicts=${verdicts.join(',')}` : ''}`)
export const getChannel = (id: number) => req<Channel>(`/api/channels/${id}`)
export async function getWindow(id: number, t0: number, t1: number, px: number): Promise<WindowData & { round_trip_ms: number }> {
  const t = performance.now()
  const d = await req<WindowData>(`/api/channels/${id}/window?t0=${t0}&t1=${t1}&px=${Math.round(px)}`)
  return { ...d, round_trip_ms: performance.now() - t }
}
export const getSpans = (id: number, t0: number, t1: number) => req<Spans>(`/api/channels/${id}/spans?t0=${t0}&t1=${t1}`)

/* ---------------- analyse: chain ---------------- */
export interface ParamSpec { name: string; type: 'int' | 'float' | 'str' | 'bool'; default: unknown; description: string; choices: unknown[] | null; min: number | null; max: number | null }
export interface AdapterCard {
  name: string; stage: string; algorithm: string; display_name: string; page_name: string; description: string
  input_kind: TypeKind; output_kind: TypeKind; signature: string; category: 'preprocess' | 'encode' | 'detect' | 'cluster' | 'model' | 'control'
  has_estimate: boolean; max_span_samples: number | null; has_recommend: boolean
  side_inputs: { name: string; type_kind: TypeKind; sources: string[] }[]; known_broken: string | null; params: ParamSpec[]
}
export type TypeKind = 'signal' | 'spanset' | 'windowset' | 'encoding' | 'grouping' | 'model' | 'scores'
export const TYPE_LABEL: Record<TypeKind, string> = { signal: 'Signal', spanset: 'SpanSet', windowset: 'WindowSet', encoding: 'Encoding', grouping: 'Grouping', model: 'Model', scores: 'Scores' }

export interface Step { stage: string; algorithm: string; params: Record<string, unknown>; side_inputs?: Record<string, unknown> }
export interface Junction { index: number; ok: boolean; producing: TypeKind; expected: TypeKind | null; reason: string; core_reason?: string }
export interface Validation {
  ok: boolean; junctions: Junction[]; terminal_kind: TypeKind | null; terminal_label: string | null
  estimate?: { total_s: number; per_step_s: number[] }; hashes?: { config_hash: string; recipe_hash: string }
  cache?: { index: number; prefix_hash: string; cached: boolean; path: string | null }[]; over_ceiling?: number[]; recipe_error?: string
}
export interface Compatible {
  position: number; producing: TypeKind; producing_label: string; next_requires: TypeKind | null; next_requires_label: string | null; next_name: string | null
  n_fit: number; n_total: number; rows: { name: string; ok: boolean; reason: string }[]; stale_from: number | null
}
export interface Template { id: string | number; name: string; builtin: boolean; steps: Step[] }

export const getAdapters = () => req<AdapterCard[]>('/api/adapters')
export const validateChain = (steps: Step[], recording_id?: number, span?: [number, number] | null) =>
  post<Validation>('/api/chain/validate', { steps, recording_id, span })
export const compatibleAt = (steps: Step[], position: number) => post<Compatible>('/api/chain/compatible', { steps, position })
export const validateParams = (step: Step) => post<{ params: Record<string, unknown> }>('/api/chain/params', step)
export const getTemplates = () => req<Template[]>('/api/templates')
export const saveTemplate = (name: string, steps: Step[]) => post<{ id: number; name: string; note: string }>('/api/templates', { name, steps })

/* ---------------- analyse: runs ---------------- */
export type StepStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | 'blocked'
export interface JobStep {
  index: number; stage: string; algorithm: string; status: StepStatus; started_at: number | null; elapsed_s: number | null
  cached_predicted: boolean; cached: boolean | null; core_elapsed_s?: number; kind: TypeKind | null; summary: string | null; has_payload: boolean
}
export interface JobError { step: number | null; message: string; type: string; traceback?: string; adapter?: string | null }
export interface JobSnapshot {
  job_id: number; status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; n_steps: number; current_step: number | null
  steps: JobStep[]; error: JobError | null; step_timings: Record<string, number> | null; detections_written: number | null
  config_hash: string | null; db_run_id: number | null; started_at: number; finished_at: number | null; recipe: { recording_id: number; span: [number, number] | null; steps: Step[] }
  recording_id: number; elapsed_s: number
}
export interface RunEvent { event: 'hello' | 'step_start' | 'step_done' | 'run_end' | 'cancel_requested'; job_id: number; ts: number; [k: string]: unknown }
export interface DbRun {
  id: number; config_id: number; recording_id: number; span_start: number; span_end: number; started_at: string; status: string
  finished_at: string | null; duration_s: number | null; error_text: string | null; current_step: number | null; name: string | null
  steps: string[]; recipe: { recording_id: number; span: [number, number] | null; steps: Step[] } | null; step_timings: Record<string, number> | null; n_detections: number; cancelled?: boolean
}

export const startRun = (recording_id: number, span: [number, number] | null, steps: Step[], px = 1200) =>
  post<JobSnapshot>('/api/runs', { recording_id, span, steps, px })
export const getRun = (jobId: number) => req<JobSnapshot>(`/api/runs/${jobId}`)
export const cancelRun = (jobId: number) => post<{ accepted: boolean; status: string; note: string }>(`/api/runs/${jobId}/cancel`, {})
export const getStepPayload = (jobId: number, index: number) => req<Payload>(`/api/runs/${jobId}/steps/${index}`)
export const getRunLog = (jobId: number) => req<{ job_id: number; lines: string[]; error: JobError | null }>(`/api/runs/${jobId}/log`)
export const listRuns = (recording_id?: number, limit = 30) => req<{ db_runs: DbRun[]; jobs: JobSnapshot[] }>(`/api/runs?limit=${limit}${recording_id ? `&recording_id=${recording_id}` : ''}`)
export const exportRun = (jobId: number) => req<{ path: string; bytes: number }>(`/api/runs/${jobId}/export`)

/** Subscribe to a run's SSE stream. Late subscribers get the full replay. Returns an unsubscribe fn.
 *  `onError` fires with a typed reason for a transport error AND for an unparseable frame (critique r1:
 *  a corrupt frame must never leave the page "computing" forever); `isOpen()` lets a store poll as a
 *  liveness fallback while the socket is not OPEN. */
export interface SseHandle { close: () => void; isOpen: () => boolean }
export function subscribeRun(jobId: number, onEvent: (e: RunEvent) => void, onError?: (reason: string) => void): SseHandle {
  const es = new EventSource(`/api/runs/${jobId}/events`)
  const handler = (ev: MessageEvent) => {
    try {
      const data = JSON.parse(ev.data) as RunEvent
      onEvent({ ...data, event: (ev.type as RunEvent['event']) })
      if (ev.type === 'run_end') es.close()
    } catch (err) {
      console.error('bad SSE payload', err, ev.data)
      onError?.(`run stream unreadable (${err instanceof Error ? err.message : String(err)})`)
    }
  }
  for (const name of ['hello', 'step_start', 'step_done', 'run_end', 'cancel_requested']) es.addEventListener(name, handler as EventListener)
  es.onerror = () => { onError?.(es.readyState === EventSource.CLOSED ? 'run stream closed' : 'run stream interrupted') }
  return { close: () => es.close(), isOpen: () => es.readyState === EventSource.OPEN }
}

/* ---------------- the seven payload types (server/serialize.py) ---------------- */
export interface EnvelopeSeries { t: number[]; v: (number | null)[]; n_source: number; n_points: number; decimated: boolean }
export interface SignalPayload { type: 'signal'; fs: number; n: number; t0_s: number; t1_s: number; y_range: [number, number] | null; envelope: EnvelopeSeries; summary: string }
export interface ScoresPayload {
  type: 'scores'; fs: number; n: number; t0_s: number; t1_s: number; nan_tail: number; value_range: [number, number] | null; envelope: EnvelopeSeries
  top: { low: { t_s: number; v: number }[]; high: { t_s: number; v: number }[] }; histogram: { counts: number[]; edges: number[] } | null; m: number | null; summary: string
}
export interface SpansetPayload { type: 'spanset'; fs: number; n: number; capped: boolean; start_s: number[]; end_s: number[]; labels: (string | null)[] | null; scores: (number | null)[] | null; summary: string }
export interface WindowsetPayload {
  type: 'windowset'; fs: number; n_windows: number; length: number; length_s: number; starts_s: number[]; capped: boolean
  features: { n_columns: number; columns: string[]; matrix: (number | null)[][] | null; col_range?: [number | null, number | null][] } | null; summary: string
}
export interface EncodingSymbolicPayload {
  type: 'encoding'; kind: 'symbolic'; n_symbols: number; alphabet_size: number; symbols: number[]; letters: string; capped: boolean
  samples_per_symbol: number | null; seconds_per_symbol: number | null; t0_s: number; fs: number; cutlines: number[] | null; cutline_domain: string | null
  representatives: number[] | null; paa: number[] | null; n_trimmed: number | null; summary: string
}
export interface EncodingImagePayload {
  type: 'encoding'; kind: 'image'; ndim: number; shape: number[]; display_shape?: [number, number]; channels?: number; value_range?: [number, number]
  pixels_b64?: string; series?: number[]; bin_freqs?: number[] | null; summary: string
}
export interface GroupingPayload {
  type: 'grouping'; n: number; k: number; label_base: number; linkage: string | null; clusters: { id: number; count: number }[]; labels: number[]; capped: boolean
  strip: { starts_s: number[]; length_s: number } | null; summary: string
}
export interface ModelPayload { type: 'model'; path: string; exists: boolean; size_bytes: number | null; card: Record<string, unknown>; summary: string }
export interface ErrorPayload { type: string; error: string; traceback?: string; summary: string }
export type Payload = SignalPayload | ScoresPayload | SpansetPayload | WindowsetPayload | EncodingSymbolicPayload | EncodingImagePayload | GroupingPayload | ModelPayload | ErrorPayload
