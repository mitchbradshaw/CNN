/* The tier-2 viewport: [t0, t1] in seconds plus the envelope and spans fetched FOR THAT viewport.
   Every pan/zoom re-fetches a peak-preserving decimation from the server (debounced ~60 ms after
   the last event); until it lands the previous path stays on screen under a CSS transform so the
   interaction feels immediate. Every fetch is timed into window.__zoomStats (evidence for the
   stack decision): server decimate_ms, round_trip_ms, and paint_ms (rAF after the state commit). */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getSpans, getWindow, type ApiError, type Channel, type Spans, type WindowData } from '../api'
import { asApiError, clampView, MIN_SPAN_S } from './util'

export interface ZoomStat { seq: number; t0: number; t1: number; px: number; n_points: number; decimate_ms: number; round_trip_ms: number; paint_ms: number }
declare global { interface Window { __zoomStats?: ZoomStat[] } }

export interface Win { data: WindowData & { round_trip_ms: number }; view: [number, number]; px: number; tCommit: number; seq: number }

export const DEBOUNCE_MS = 60

export function useViewport(ch: Channel, initial: () => [number, number], width: number) {
  const dur = ch.duration_s
  const [view, setViewState] = useState<[number, number]>(() => clampView(initial(), dur))
  const viewRef = useRef(view)
  viewRef.current = view
  const setView = useCallback((v: [number, number]) => {
    const c = clampView(v, dur)
    setViewState(prev => (prev[0] === c[0] && prev[1] === c[1] ? prev : c))
  }, [dur])

  const [win, setWin] = useState<Win | null>(null)
  const [spans, setSpans] = useState<Spans | null>(null)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [lastStat, setLastStat] = useState<ZoomStat | null>(null)
  const seq = useRef(0)

  const [t0, t1] = view
  useEffect(() => {
    if (!(width > 0)) return
    const id = window.setTimeout(() => {
      const my = ++seq.current
      const px = Math.round(width)
      setFetching(true)
      getWindow(ch.id, t0, t1, px)
        .then(w => { if (my !== seq.current) return; setWin({ data: w, view: [t0, t1], px, tCommit: performance.now(), seq: my }); setFetching(false); setError(null) })
        .catch(e => { if (my !== seq.current) return; setFetching(false); setError(asApiError(e)) })
      getSpans(ch.id, t0, t1)
        .then(s => { if (my === seq.current) setSpans(s) })
        .catch(e => { if (my === seq.current) setError(asApiError(e)) })
    }, DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [ch.id, t0, t1, width])

  useEffect(() => {
    if (!win) return
    const w = win
    requestAnimationFrame(() => {
      const stat: ZoomStat = {
        seq: w.seq, t0: w.view[0], t1: w.view[1], px: w.px, n_points: w.data.envelope.n_points,
        decimate_ms: w.data.decimate_ms, round_trip_ms: w.data.round_trip_ms, paint_ms: performance.now() - w.tCommit,
      }
      const arr = (window.__zoomStats ??= [])
      if (!arr.some(s => s.seq === stat.seq)) arr.push(stat)
      setLastStat(stat)
    })
  }, [win])

  /** Zoom by `factor` (>1 = out) keeping the time under `anchor` fixed. */
  const zoomAt = useCallback((factor: number, anchor: number) => {
    const [a, b] = viewRef.current
    const span0 = b - a
    const span = Math.min(dur, Math.max(Math.min(dur, MIN_SPAN_S), span0 * factor))
    const f = span / span0
    const na = anchor - (anchor - a) * f
    setView([na, na + span])
  }, [dur, setView])
  const fit = useCallback(() => setView([0, dur]), [dur, setView])
  /** Centre the viewport on [s, e], widening it if the motif would not fit. */
  const centreOn = useCallback((s: number, e: number) => {
    const [a, b] = viewRef.current
    const span = Math.max(b - a, (e - s) * 1.25)
    const c = (s + e) / 2
    setView([c - span / 2, c + span / 2])
  }, [setView])

  return { view, setView, viewRef, win, spans, fetching, error, lastStat, zoomAt, fit, centreOn, dur }
}

export type Viewport = ReturnType<typeof useViewport>
