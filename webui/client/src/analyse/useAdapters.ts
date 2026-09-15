/* The adapter registry, fetched once per page load and shared by every Analyse surface. */
import { useEffect, useState } from 'react'
import { ApiError, getAdapters, type AdapterCard, type Step } from '../api'

let cache: AdapterCard[] | null = null
let inflight: Promise<AdapterCard[]> | null = null

export function loadAdapters(): Promise<AdapterCard[]> {
  if (cache) return Promise.resolve(cache)
  if (!inflight) inflight = getAdapters().then(a => { cache = a; return a }).finally(() => { inflight = null })
  return inflight
}

export interface AdapterIndex { list: AdapterCard[]; byName: Map<string, AdapterCard>; error: string | null; loading: boolean }

export function useAdapters(): AdapterIndex {
  const [list, setList] = useState<AdapterCard[]>(cache ?? [])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!cache)
  useEffect(() => {
    let alive = true
    loadAdapters().then(a => { if (alive) { setList(a); setLoading(false) } })
      .catch(e => { if (alive) { setError(e instanceof ApiError ? `${e.message}${e.traceback ? '\n' + e.traceback : ''}` : String(e)); setLoading(false) } })
    return () => { alive = false }
  }, [])
  const byName = new Map(list.map(a => [a.name, a]))
  return { list, byName, error, loading }
}

export const stepName = (s: Step) => `${s.stage}.${s.algorithm}`
export const pad2 = (n: number) => String(n).padStart(2, '0')

/** page_name from the catalogue, falling back to the algorithm id. */
export function pageName(idx: AdapterIndex | Map<string, AdapterCard>, s: Step): string {
  const m = idx instanceof Map ? idx : idx.byName
  return m.get(stepName(s))?.page_name ?? s.algorithm
}
