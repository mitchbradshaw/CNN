/* Explore › Corpus (frame explore-1-corpus): recording toolbar, the channels × time coverage map,
   the filter rail and the selected-channel bottom bar. All numbers come from /api/recordings and
   /api/corpus/{file}/coverage; the held-out recording renders a locked card and is never fetched. */
import { useEffect, useMemo, useState } from 'react'
import { ApiError, getCoverage, getRecordings, type Coverage, type RecordingFile } from '../api'
import { Header } from '../shell/Header'
import { navigate, useApp } from '../state'
import { ErrorCard } from './ErrorCard'
import { Heatmap } from './Heatmap'
import { LockedCard } from './LockedCard'
import { RightRail, type ShowState } from './RightRail'
import { asApiError, COLOUR_BY, fmtInt, MATRIX_UNIT, RAMP, VERDICTS, type ColourBy } from './util'

const BIN_CHOICES = [28, 57, 114]

function DbIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" strokeWidth="2"><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>
}
function LockIcon() {
  return <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
}

export function CorpusPage() {
  const { explore, setExplore } = useApp()
  const [recs, setRecs] = useState<RecordingFile[] | null>(null)
  const [recErr, setRecErr] = useState<ApiError | null>(null)
  useEffect(() => {
    let alive = true
    getRecordings().then(r => { if (alive) setRecs(r) }).catch(e => { if (alive) setRecErr(asApiError(e)) })
    return () => { alive = false }
  }, [])

  const files = recs ?? []
  const openFiles = useMemo(() => files.filter(f => !f.held_out), [files])
  const file = useMemo(() => files.find(f => f.source_file === explore.file) ?? openFiles[0] ?? null, [files, openFiles, explore.file])
  const colourBy: ColourBy = (COLOUR_BY as string[]).includes(explore.colourBy) ? (explore.colourBy as ColourBy) : 'both'
  const [bins, setBins] = useState(57)
  const [show, setShow] = useState<ShowState>({ annotations: true, detections: true })
  const [verdicts, setVerdicts] = useState<string[]>(VERDICTS)
  const [cov, setCov] = useState<Coverage | null>(null)
  const [covErr, setCovErr] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(false)
  const [lockErr, setLockErr] = useState<ApiError | null>(null)

  const fileName = file?.source_file ?? null
  const heldOut = file?.held_out ?? false
  const verdictKey = verdicts.length === VERDICTS.length ? '' : verdicts.join(',')
  useEffect(() => {
    if (!fileName) return
    let alive = true
    if (heldOut) {
      // Never fetch anything for the held-out recording: the locked card carries the server's own
      // refusal text from /api/recordings (held_out_reason), so no data request is ever made for M4.
      setCov(null)
      setLockErr(new ApiError(423, file?.held_out_reason ?? `${fileName} is held out (spec §0 D6)`))
      return () => { alive = false }
    }
    setLoading(true); setCovErr(null)
    getCoverage(fileName, bins, verdictKey ? verdictKey.split(',') : undefined)
      .then(c => { if (!alive) return; setCov(c); setLoading(false) })
      .catch(e => { if (!alive) return; setCovErr(asApiError(e)); setLoading(false) })
    return () => { alive = false }
  }, [fileName, heldOut, file, bins, verdictKey])

  const matrix: ColourBy | null = show.annotations && show.detections ? colourBy : show.annotations ? 'annotations' : show.detections ? 'detections' : null
  const rows = useMemo(() => (cov && cov.source_file === fileName ? cov.rows : []), [cov, fileName])
  const selId = useMemo(() => {
    if (!rows.length) return null
    if (explore.channelId != null && rows.some(r => r.id === explore.channelId)) return explore.channelId
    return (rows.find(r => r.name === 'CH4_A2') ?? rows[0]).id
  }, [rows, explore.channelId])
  const selRow = rows.find(r => r.id === selId) ?? null
  const matching = useMemo(() => {
    let spans = 0, channels = 0
    if (matrix) for (const r of rows) { let s = 0; for (const c of r[matrix]) s += c; spans += s; if (s > 0) channels++ }
    return { spans, channels, total: rows.length }
  }, [rows, matrix])
  const select = (id: number) => { if (id !== selId) setExplore({ channelId: id, view: null }) }

  const pageIdx = openFiles.findIndex(f => f.source_file === fileName)
  const durH = file?.duration_h ?? 0
  const binH = cov && cov.source_file === fileName ? cov.bin_h : durH / bins
  const c = selRow?.counts

  return (
    <>
      <Header workspace="Explore" page="Corpus" subtitle="bird's-eye across every channel" />
      <div className="page"><div className="page-inner">
        <div className="ex-toolbar" data-testid="corpus-toolbar">
          <span className="chip" style={{ height: 30 }}>
            {heldOut ? <LockIcon /> : <DbIcon />}
            {recs ? (
              <select className="ex-select-bare" value={fileName ?? ''} onChange={e => setExplore({ file: e.target.value, channelId: null, view: null })} data-testid="recording-select">
                {files.map(f => (
                  <option key={f.source_file} value={f.source_file}>
                    {f.held_out ? '🔒 ' : ''}{f.source_file}  {f.n_channels} ch · {Math.round(f.duration_h)} h · {f.fs} Hz{f.held_out ? ' · held out' : ''}
                  </option>
                ))}
              </select>
            ) : <span className="muted">loading recordings…</span>}
          </span>
          <span className="ex-pager chip" data-testid="recording-pager">
            <button disabled={pageIdx <= 0} onClick={() => setExplore({ file: openFiles[pageIdx - 1].source_file, channelId: null, view: null })} title="previous recording">‹</button>
            <span>{pageIdx >= 0 ? pageIdx + 1 : '–'} / {openFiles.length}</span>
            <button disabled={pageIdx < 0 || pageIdx >= openFiles.length - 1} onClick={() => setExplore({ file: openFiles[pageIdx + 1].source_file, channelId: null, view: null })} title="next recording">›</button>
          </span>
          <span className="divider-v" />
          <span className="lbl">time</span>
          <span className="ex-slider inert" title="time range · out of slice scope" />
          <span className="chip" data-testid="time-chip">0 – {Number.isInteger(durH) ? durH : durH >= 10 ? Math.round(durH) : durH.toFixed(2)} h</span>
          <span className="chip" title="bins across the recording">
            <span className="lbl">bin</span>
            <select className="ex-select-bare" value={bins} onChange={e => setBins(Number(e.target.value))} data-testid="bin-select">
              {BIN_CHOICES.map(b => <option key={b} value={b}>{b === 57 ? 'auto · ' : ''}{(durH / b).toFixed(1)} h</option>)}
            </select>
          </span>
          <span className="divider-v" />
          <span className="lbl">colour by</span>
          <div className="seg" data-testid="colour-by">
            {COLOUR_BY.map(k => <button key={k} className={colourBy === k ? 'on' : ''} onClick={() => setExplore({ colourBy: k })} data-testid={`colour-by-${k}`}>{k}</button>)}
          </div>
          {loading && <span className="muted">loading…</span>}
        </div>

        {recErr && <ErrorCard error={recErr} title="GET /api/recordings failed" />}
        {covErr && <ErrorCard error={covErr} title={`coverage for ${fileName} failed`} />}

        {heldOut ? (
          <LockedCard error={lockErr} file={fileName ?? undefined} />
        ) : (
          <div className="ex-corpus-grid">
            <div className="card card-pad" data-testid="coverage-card">
              <div className="ex-card-head">
                <span className="card-title">Coverage map</span>
                <span className="meta">{rows.length || file?.n_channels || '—'} channels · 0 – {Math.round(durH)} h · bin {binH ? binH.toFixed(1) : '—'} h</span>
                <span className="grow" />
                <span className="meta" data-testid="matrix-label">{matrix ?? 'nothing shown'} · spans per bin</span>
                <span className="ex-legend">low {RAMP.slice(1).map(c => <i key={c} style={{ background: c }} />)} high</span>
              </div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--muted-2)', marginBottom: 2 }}>channel</div>
              {cov && cov.source_file === fileName ? (
                <Heatmap cov={cov} matrix={matrix} unit={matrix ? MATRIX_UNIT[matrix] : 'spans'} selectedId={selId} onSelect={select} />
              ) : covErr ? null : <div className="skeleton" style={{ height: 16 * 34 + 22 }} data-testid="coverage-skeleton" />}
              <p className="muted small" style={{ margin: '8px 0 0' }}>each cell counts spans whose start falls in that bin · darker is more · click a row to select the channel</p>
            </div>
            <RightRail cov={cov && cov.source_file === fileName ? cov : null} show={show} setShow={setShow} verdicts={verdicts} setVerdicts={setVerdicts} matching={matching} />
          </div>
        )}

        <div className="card ex-bottom" data-testid="corpus-bottom-bar">
          <div className="row" style={{ gap: 18 }}>
            <span className="name" data-testid="selected-channel-name">{heldOut ? '—' : selRow?.name ?? '—'}</span>
            <span className="counts">
              {heldOut ? 'held out · no channel can be opened' : c
                ? `${fmtInt(c.annotations)} annotations · ${fmtInt(c.detections)} detections · ${fmtInt(c.disagree)} disagree · ${c.reviewed_pct == null ? '—' : Math.round(c.reviewed_pct) + ' %'} reviewed`
                : 'select a channel'}
            </span>
          </div>
          <div className="row">
            <button className="btn inert" title="out of slice scope" aria-disabled>Cross-channel from {selRow?.name ?? '…'}</button>
            <button className="btn primary" disabled={!selRow || heldOut} onClick={() => selRow && navigate(`explore/signal/${selRow.id}`)} data-testid="open-channel">Open {selRow?.name ?? '…'} →</button>
          </div>
        </div>
      </div></div>
    </>
  )
}
