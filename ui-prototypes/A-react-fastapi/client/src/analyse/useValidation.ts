/* Validation runs on every edit (debounced ~150 ms): junctions, terminal type, estimate,
   prefix-cache prediction and over-ceiling steps all come from POST /api/chain/validate. */
import { useEffect, useRef, useState } from 'react'
import { ApiError, validateChain, type Step, type Validation } from '../api'
import type { SourceSpan } from '../state'

export interface ValidationState { v: Validation | null; error: string | null; pending: boolean }

export function spanOf(source: SourceSpan | null): [number, number] | null {
  return source ? [source.start_idx, source.end_idx] : null
}

export function useValidation(steps: Step[], source: SourceSpan | null, delayMs = 150): ValidationState {
  const [st, setSt] = useState<ValidationState>({ v: null, error: null, pending: true })
  const seq = useRef(0)
  const key = JSON.stringify({ steps, r: source?.recording_id, s: spanOf(source) })
  useEffect(() => {
    const my = ++seq.current
    setSt(s => ({ ...s, pending: true }))
    const id = window.setTimeout(() => {
      validateChain(steps, source?.recording_id, spanOf(source))
        .then(v => { if (my === seq.current) setSt({ v, error: null, pending: false }) })
        .catch(e => { if (my === seq.current) setSt({ v: null, error: e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e), pending: false }) })
    }, delayMs)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return st
}
