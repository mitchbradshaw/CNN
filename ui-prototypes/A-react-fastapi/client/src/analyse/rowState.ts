/* Per-row status derivation shared by the chain rows and the block-page ribbon.
   Inputs: the chain draft, the last/live job, its payloads, the stale index and the
   latest validation. Output: one RowInfo per step. */
import type { JobSnapshot, Payload, Step, Validation } from '../api'

export type RowStatus = 'new' | 'cached' | 'stale' | 'running' | 'waiting' | 'failed' | 'blocked' | 'cancelled' | 'invalid'

export interface RowInfo {
  status: RowStatus
  payload: Payload | null        // the result to draw (may be old when stale)
  hasResult: boolean
  timing: number | null          // core step time (0.0 = prefix-cache hit) or wall time while running
  timingIsCore: boolean
  cachedPredicted: boolean
  invalidReason: string | null
  overCeiling: boolean
}

export const sameStep = (a: Step | undefined, b: Step | undefined) => !!a && !!b && a.stage === b.stage && a.algorithm === b.algorithm

/** A job's results are only shown against the source it ran on (recording + sample span). */
export function jobForSource(job: JobSnapshot | null, source: { recording_id: number; start_idx: number; end_idx: number } | null): JobSnapshot | null {
  if (!job || !source) return null
  const r = job.recipe
  if (r.recording_id !== source.recording_id) return null
  if (r.span && (r.span[0] !== source.start_idx || r.span[1] !== source.end_idx)) return null
  return job
}

export function deriveRows(steps: Step[], job: JobSnapshot | null, payloads: Record<number, Payload>, staleFrom: number | null, v: Validation | null): RowInfo[] {
  const live = job?.status === 'running' || job?.status === 'queued'
  return steps.map((step, i) => {
    const jstep = job?.steps[i]
    const matches = !!job && sameStep(job.recipe.steps[i], step)
    const payload = matches && payloads[i] ? payloads[i] : null
    const hasResult = payload !== null
    const junction = v?.junctions?.[i]
    const invalidReason = junction && junction.ok === false ? junction.reason : null
    const overCeiling = !!v?.over_ceiling?.includes(i)
    const coreT = job?.step_timings ? job.step_timings[String(i)] : undefined
    const timing = coreT !== undefined ? coreT : (jstep?.elapsed_s ?? null)
    const base: Omit<RowInfo, 'status'> = { payload, hasResult, timing, timingIsCore: coreT !== undefined, cachedPredicted: !!jstep?.cached_predicted || !!v?.cache?.[i]?.cached, invalidReason, overCeiling }

    if (live && jstep && matches) {
      const s = jstep.status
      const status: RowStatus = s === 'running' ? 'running' : s === 'pending' ? 'waiting' : s === 'done' ? 'cached' : s === 'failed' ? 'failed' : s === 'blocked' ? 'blocked' : s === 'cancelled' ? 'cancelled' : 'new'
      return { ...base, status }
    }
    if (invalidReason) return { ...base, status: 'invalid' }
    if (staleFrom !== null && i >= staleFrom) {
      if (hasResult) return { ...base, status: 'stale' }
      if (job?.status === 'failed' && job.error?.step === i && matches) return { ...base, status: 'failed' }
      return { ...base, status: 'new' }
    }
    if (job && matches && jstep) {
      if (job.status === 'completed') return { ...base, status: hasResult || jstep.status === 'done' ? 'cached' : 'new' }
      if (job.status === 'failed') return { ...base, status: jstep.status === 'done' ? 'cached' : jstep.status === 'failed' ? 'failed' : jstep.status === 'blocked' ? 'blocked' : 'new' }
      if (job.status === 'cancelled') return { ...base, status: jstep.status === 'done' ? 'cached' : jstep.status === 'cancelled' ? 'cancelled' : 'new' }
    }
    if (v?.cache?.[i]?.cached) return { ...base, status: 'cached' }
    return { ...base, status: 'new' }
  })
}

/** First stale step (1-based label) for "Re-run from 0N", or null. */
export function firstStale(rows: RowInfo[], staleFrom: number | null): number | null {
  if (staleFrom !== null) return staleFrom
  const i = rows.findIndex(r => r.status === 'stale')
  return i >= 0 ? i : null
}

export function fmtTiming(t: number | null | undefined): string {
  if (t === null || t === undefined) return ''
  if (t === 0) return '0 s'
  if (t < 0.05) return '<0.1 s'
  return `${t.toFixed(1)} s`
}

/** spec §6.1 wording for the footer's terminal chip. */
export function terminalWording(kind: string | null, label: string | null): { chip: string; kind: 'green' | 'grey' | 'amber' } {
  if (!kind) return { chip: 'no stages — the terminal type is the source', kind: 'grey' }
  if (kind === 'spanset') return { chip: `terminal ${label} → detection template`, kind: 'green' }
  if (kind === 'model') return { chip: `terminal ${label} → training template`, kind: 'green' }
  return { chip: `terminal ${label} — add a stage to reach a template type`, kind: 'grey' }
}
