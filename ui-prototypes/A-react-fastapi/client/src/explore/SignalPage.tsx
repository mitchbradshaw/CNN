/* Explore › Signal (frame explore-2-signal): three tiers on one channel — overview with the
   draggable span box, the viewport, the selected motif — then the span-action row and the four
   ribbons. The held-out recording renders a locked card from the API's 423. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, getChannel, getRecordings, getSpans, type Channel, type Spans } from '../api'
import type { BandKind } from '../charts/primitives'
import { useSize } from '../charts/useSize'
import { ErrorBoundary } from '../shell/ErrorBoundary'
import { Header } from '../shell/Header'
import { useToast } from '../shell/Toast'
import { navigate, useApp } from '../state'
import { ErrorCard } from './ErrorCard'
import { LockedCard } from './LockedCard'
import { MotifView } from './MotifView'
import { Overview } from './Overview'
import { Ribbons } from './Ribbons'
import { RunsChip } from './RunsChip'
import { SpanActions } from './SpanActions'
import { SpanView, type Band } from './SpanView'
import { useViewport } from './useViewport'
import { asApiError, fmtInt, fmtRangeH, toMotifs, type Motif } from './util'

export function SignalPage({ channelId }: { channelId: number }) {
  const [ch, setCh] = useState<Channel | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  useEffect(() => {
    let alive = true
    setCh(null); setErr(null)
    if (!Number.isFinite(channelId)) { setErr(new ApiError(0, `bad channel id in the route: ${String(channelId)}`)); return }
    // Held-out guard first (spec §0 D6): if this channel id belongs to the held-out recording,
    // show the server's refusal from /api/recordings and never request the channel itself.
    getRecordings().then(files => {
      if (!alive) return
      const owner = files.find(f => f.channels.some(c => c.id === channelId))
      if (owner?.held_out) { setErr(new ApiError(423, owner.held_out_reason ?? `${owner.source_file} is held out (spec §0 D6)`)); return }
      getChannel(channelId).then(c => { if (alive) setCh(c) }).catch(e => { if (alive) setErr(asApiError(e)) })
    }).catch(e => { if (alive) setErr(asApiError(e)) })
    return () => { alive = false }
  }, [channelId])

  if (err) {
    const locked = err.status === 423
    return (
      <>
        <Header workspace="Explore" page="Signal" subtitle={locked ? `channel ${channelId} · held out` : `channel ${channelId} · error`} />
        <div className="page"><div className="page-inner">
          <div className="ex-topbar"><div className="ex-crumb"><a onClick={() => navigate('explore/corpus')}>Corpus</a><span>›</span><span className="cur">channel {channelId}</span></div><span className="grow" /><a className="ex-back" onClick={() => navigate('explore/corpus')}>‹ back to corpus</a></div>
          {locked ? <LockedCard error={err} file="M4_aug_concat_fs1.mat" /> : <ErrorCard error={err} title={`GET /api/channels/${channelId} failed`} />}
        </div></div>
      </>
    )
  }
  if (!ch) {
    return (
      <>
        <Header workspace="Explore" page="Signal" subtitle={`channel ${channelId} · loading…`} />
        <div className="page"><div className="page-inner">
          <div className="skeleton" style={{ height: 30, width: 480 }} />
          <div className="skeleton" style={{ height: 190 }} />
          <div className="skeleton" style={{ height: 240 }} />
        </div></div>
      </>
    )
  }
  return <SignalBody ch={ch} />
}

function SignalBody({ ch }: { ch: Channel }) {
  const { explore, setExplore, setSource } = useApp()
  const toast = useToast()
  const [plotRef, plotSize] = useSize<HTMLDivElement>()
  const initial = useCallback((): [number, number] => {
    if (explore.channelId === ch.id && explore.view) return explore.view
    if (ch.source_file === 'M2_aug_concat_fs1.mat' && ch.name === 'CH4_A2') return [995040, 1002240]  // the frames' example span
    return [0, Math.min(7200, ch.duration_s)]
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps -- initial only
  const vp = useViewport(ch, initial, plotSize.width)

  // persist the viewport so a reload keeps it (debounced: pans fire at pointer rate)
  useEffect(() => {
    const id = window.setTimeout(() => setExplore({ channelId: ch.id, view: vp.view }), 200)
    return () => window.clearTimeout(id)
  }, [vp.view, ch.id, setExplore])

  // every motif on the channel, once, for ‹ N / M › navigation
  const [all, setAll] = useState<Spans | null>(null)
  const [allErr, setAllErr] = useState<ApiError | null>(null)
  useEffect(() => {
    let alive = true
    getSpans(ch.id, 0, ch.duration_s).then(s => { if (alive) setAll(s) }).catch(e => { if (alive) setAllErr(asApiError(e)) })
    return () => { alive = false }
  }, [ch.id, ch.duration_s])
  const motifs = useMemo(() => (all ? toMotifs(all) : []), [all])
  const capped = !!(all && (all.annotations_capped || all.detections_capped))
  const [sel, setSel] = useState<Motif | null>(null)
  const index = sel ? motifs.findIndex(m => m.key === sel.key) : -1
  const go = (m: Motif | undefined) => { if (!m) return; setSel(m); vp.centreOn(m.start_s, m.end_s) }
  const next = () => {
    if (index >= 0) go(motifs[index + 1])
    else go(motifs.find(m => m.start_s >= vp.view[0]) ?? motifs[0])
  }
  const prev = () => {
    if (index >= 0) go(motifs[index - 1])
    else { let last: Motif | undefined; for (const m of motifs) { if (m.start_s <= vp.view[1]) last = m; else break } go(last ?? motifs[motifs.length - 1]) }
  }

  const inView = useMemo(() => (vp.spans ? toMotifs(vp.spans) : []), [vp.spans])
  const bands = useMemo<Band[]>(() => inView.map(m => {
    const kind: BandKind = sel?.key === m.key ? 'selected' : m.kind === 'annotated' ? (m.verdict === 'artifact' ? 'artifact' : 'annotated') : 'detected'
    const title = m.kind === 'annotated' ? `annotation ${m.id} · ${m.verdict}` : `detection ${m.id} · run ${m.run_id}`
    return { start_s: m.start_s, end_s: m.end_s, kind, id: m.key, title, motif: m }
  }), [inView, sel])

  const send = (a: number, b: number, label: string) => {
    setSource({ recording_id: ch.id, channel_name: ch.name, source_file: ch.source_file, fs: ch.fs, start_idx: Math.round(a * ch.fs), end_idx: Math.round(b * ch.fs), label })
    toast.push({ text: `${label} sent to Analyse as the chain source` })
    navigate('analyse/chain')
  }

  return (
    <>
      <Header workspace="Explore" page="Signal" subtitle={`${ch.name} · ${fmtInt(ch.summary.annotations)} annotations · ${fmtInt(ch.summary.detections)} detections`} />
      <div className="page"><div className="page-inner">
        <div className="ex-topbar" data-testid="signal-topbar">
          <div className="ex-crumb">
            <a onClick={() => navigate('explore/corpus')} data-testid="crumb-corpus">Corpus</a><span>›</span>
            <span>{ch.source_file}</span><span>›</span>
            <span className="cur">{ch.name}</span>
          </div>
          <div className="seg" style={{ marginLeft: 8 }}>
            <button className="on">Signal</button>
            <button className="inert" title="out of slice scope">Cross-channel</button>
          </div>
          <RunsChip recordingId={ch.id} channelName={ch.name} nDetectionRuns={ch.summary.detection_runs} nDetections={ch.summary.detections} />
          <span className="chip inert" title="display mode is out of slice scope · raw mV is what is drawn" aria-disabled data-testid="display-chip">display <b>raw</b> ▾</span>
          <span className="grow" />
          <a className="ex-back" onClick={() => navigate('explore/corpus')} data-testid="back-to-corpus">‹ back to corpus</a>
        </div>

        {allErr && <ErrorCard error={allErr} title="span list for the whole channel failed" />}

        {/* one boundary per tier (critique r1: a bad payload in one tier took the whole workspace down) */}
        <ErrorBoundary label="overview tier">
          <Overview ch={ch} view={vp.view} onView={vp.setView} />
        </ErrorBoundary>
        <ErrorBoundary label="span tier">
          <SpanView ch={ch} vp={vp} plotRef={plotRef} width={plotSize.width} bands={bands} selected={sel} onBandClick={m => setSel(m)}
            nav={{ index, total: motifs.length, capped, prev, next }} />
        </ErrorBoundary>
        <ErrorBoundary label="motif tier">
          <MotifView ch={ch} motif={sel} onSend={m => send(m.start_s, m.end_s, `MOTIF ${m.id} · ${ch.name}`)} />
        </ErrorBoundary>
        <ErrorBoundary label="span actions">
          <SpanActions view={vp.view} nInView={inView.length} onSend={() => send(vp.view[0], vp.view[1], `${ch.name} · ${fmtRangeH(vp.view[0], vp.view[1])}`)} />
        </ErrorBoundary>
        <ErrorBoundary label="ribbons">
          <Ribbons annotations={vp.spans?.annotations ?? []} detections={vp.spans?.detections ?? []}
            totals={{ annotations: ch.summary.annotations, detections: ch.summary.detections }}
            capped={{ annotations: !!vp.spans?.annotations_capped, detections: !!vp.spans?.detections_capped }}
            selected={sel} onSelect={m => setSel(m)} />
        </ErrorBoundary>
      </div></div>
    </>
  )
}
