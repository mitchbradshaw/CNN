/* App-wide state: the hash route, and the "source" handed from Explore to
   Analyse (a signal span: recording/channel + sample range). Persisted in
   sessionStorage so a reload keeps the source and the chain. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Step } from './api'

export interface Route { workspace: string; page: string; params: Record<string, string> }

export function parseHash(hash: string): Route {
  const h = hash.replace(/^#\/?/, '')
  const [path, query = ''] = h.split('?')
  const parts = path.split('/').filter(Boolean)
  const params: Record<string, string> = {}
  for (const kv of query.split('&')) { if (!kv) continue; const [k, v = ''] = kv.split('='); params[decodeURIComponent(k)] = decodeURIComponent(v) }
  return { workspace: parts[0] || 'explore', page: parts[1] || '', params: { ...params, ...(parts[2] ? { id: parts[2] } : {}) } }
}

export function navigate(to: string) { window.location.hash = to.startsWith('#') ? to : `#/${to.replace(/^\//, '')}` }

export interface SourceSpan {
  recording_id: number; channel_name: string; source_file: string; fs: number
  start_idx: number; end_idx: number       // half-open sample indices into the channel
  label?: string                            // e.g. "MOTIF 233" when a motif was sent
}

export interface ChainDraft {
  name: string; saved: boolean; steps: Step[]
  lastRunJobId: number | null
}

interface AppState {
  route: Route
  source: SourceSpan | null
  setSource: (s: SourceSpan | null) => void
  chain: ChainDraft
  setChain: (c: ChainDraft | ((prev: ChainDraft) => ChainDraft)) => void
  explore: { file: string | null; channelId: number | null; view: [number, number] | null; colourBy: string }
  setExplore: (patch: Partial<AppState['explore']>) => void
  liveJobs: number
  setLiveJobs: (n: number) => void
  needYou: number
  setNeedYou: (n: number) => void
  bridgeDown: boolean
  setBridgeDown: (b: boolean) => void
}

/** Job ids started from THIS browser tab (sessionStorage), so header counts are scoped to the user. */
export function myJobIds(): number[] { return load<number[]>('myjobs', []) }
export function rememberMyJob(id: number) { const xs = myJobIds(); if (!xs.includes(id)) save('myjobs', [...xs, id].slice(-200)) }

const Ctx = createContext<AppState | null>(null)

const SS_KEY = 'ub-proto-a'
function load<T>(key: string, fallback: T): T {
  try { const raw = sessionStorage.getItem(`${SS_KEY}:${key}`); return raw ? JSON.parse(raw) as T : fallback } catch { return fallback }
}
function save(key: string, v: unknown) { try { sessionStorage.setItem(`${SS_KEY}:${key}`, JSON.stringify(v)) } catch { /* ignore */ } }

export const DEFAULT_CHAIN: ChainDraft = {
  name: 'mp_threshold', saved: false, lastRunJobId: null,
  steps: [
    { stage: 'preprocessing', algorithm: 'detrend', params: { mode: 'rolling_mean', window_s: 600 } },
    { stage: 'detection', algorithm: 'matrix_profile', params: { window_min: 1.0, backend: 'stump', scrump_percentage: 1.0 } },
    { stage: 'detection', algorithm: 'threshold', params: { threshold: 8.0 } },
  ],
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  const [source, setSourceState] = useState<SourceSpan | null>(() => load('source', null))
  const [chain, setChainState] = useState<ChainDraft>(() => load('chain', DEFAULT_CHAIN))
  const [explore, setExploreState] = useState<AppState['explore']>(() => load('explore', { file: null, channelId: null, view: null, colourBy: 'both' }))
  const [liveJobs, setLiveJobs] = useState(0)
  const [needYou, setNeedYou] = useState(0)
  const [bridgeDown, setBridgeDown] = useState(false)

  useEffect(() => {
    const onHash = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onHash)
    if (!window.location.hash) navigate('explore/corpus')
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const setSource = useCallback((s: SourceSpan | null) => {
    setSourceState(prev => {
      const changed = !prev || !s || prev.recording_id !== s.recording_id || prev.start_idx !== s.start_idx || prev.end_idx !== s.end_idx
      if (changed) {
        // a new source has no run and nothing stale (critique r1: the stale index leaked across sources)
        try { sessionStorage.removeItem(`${SS_KEY}:analyse:staleFrom`) } catch { /* ignore */ }
        setChainState(c => { const next = { ...c, lastRunJobId: null }; save('chain', next); return next })
      }
      return s
    })
    save('source', s)
  }, [])
  const setChain = useCallback((c: ChainDraft | ((prev: ChainDraft) => ChainDraft)) => {
    setChainState(prev => { const next = typeof c === 'function' ? c(prev) : c; save('chain', next); return next })
  }, [])
  const setExplore = useCallback((patch: Partial<AppState['explore']>) => {
    setExploreState(prev => { const next = { ...prev, ...patch }; save('explore', next); return next })
  }, [])

  const value = useMemo<AppState>(() => ({ route, source, setSource, chain, setChain, explore, setExplore, liveJobs, setLiveJobs, needYou, setNeedYou, bridgeDown, setBridgeDown }),
    [route, source, setSource, chain, setChain, explore, setExplore, liveJobs, needYou, bridgeDown])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}

/* ---- time formatting shared by both workspaces (spec §0: hours since start; durations in s) ---- */
export function fmtHours(s: number, digits = 2) { return `${(s / 3600).toFixed(digits)} h` }
export function fmtDuration(s: number) {
  if (s < 90) return `${+s.toFixed(s < 10 ? 1 : 0)} s`
  if (s < 3600 * 2) return `${(s / 60).toFixed(1)} min`
  return `${(s / 3600).toFixed(1)} h`
}
/** Axis label for absolute time t (s) inside a window of length span (s).
 *  Spec §0: time is displayed as hours since recording start ("192.40 h"), with decimals
 *  adaptive to the span; only very short spans (≤ 15 min) fall back to absolute seconds,
 *  which is what frame chain-1 shows for its 50 s example ("825 s … 875 s"). */
export function fmtAxis(t: number, span: number) {
  const h = t / 3600
  if (span <= 20 * 60) return `${h.toFixed(4)} h`
  if (span <= 3 * 3600) return `${h.toFixed(3)} h`
  if (span <= 36 * 3600) return `${h.toFixed(2)} h`
  return `${Math.round(h)} h`
}
