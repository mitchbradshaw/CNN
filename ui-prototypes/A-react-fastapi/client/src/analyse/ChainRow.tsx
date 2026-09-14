/* One chain row (frame chain-1): left panel 210 px — grip, number + name, badge + mono
   signature, one-line caption, icon row — and the result plot on the shared time axis.
   The row shows the result only (P5); the block page shows the process. */
import type { ReactNode } from 'react'
import { CrosshairLayer } from '../charts/primitives'
import { makeX, type XScale } from '../charts/scale'
import { useSize } from '../charts/useSize'
import { ErrorBoundary } from '../shell/ErrorBoundary'
import type { RowStatus } from './rowState'

export const PLOT_H = 92

export interface ChainRowProps {
  testIndex: number
  rowClass?: string
  num: string | null                 // '01' … or null for the source row
  title: string
  badge: RowStatus | 'source-cached'
  badgeText?: string
  badgeTitle?: string
  timingText?: string | null
  signature: string
  caption: string
  captionTitle?: string
  t0: number; t1: number
  plot: (x: XScale, w: number, h: number) => ReactNode
  replace?: ReactNode                // replaces the plot surface (error card / HPC card)
  overlay?: ReactNode                // over the plot: progress, waiting, stale pill, veil
  onSettings?: () => void
  onDelete?: () => void
  inertIcons?: boolean               // bypass / duplicate (inert everywhere)
}

const I = {
  settings: <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M4 7h10M4 12h16M4 17h7" /><circle cx="16" cy="7" r="2" fill="#fff" /><circle cx="9" cy="12" r="2" fill="#fff" /><circle cx="14" cy="17" r="2" fill="#fff" /></g>,
  bypass: <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z" /><circle cx="12" cy="12" r="2.5" /><path d="M4 4l16 16" /></g>,
  duplicate: <g fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></g>,
  delete: <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></g>,
}

export function ChainRow(p: ChainRowProps) {
  const [ref, size] = useSize<HTMLDivElement>()
  const w = Math.max(10, size.width)
  const x = makeX(p.t0, p.t1, w)
  const label = `row ${p.num ?? 'source'}`
  return (
    <div className={`an-row ${p.rowClass ?? ''}`} data-testid={`chain-row-${p.testIndex}`} data-status={p.badge}>
      <div className="an-row-left">
        <div className="an-row-title">
          <span className="grip" title="drag to reorder · out of slice scope">⋮⋮</span>
          {p.num ? <span className="num">{p.num}</span> : <span style={{ color: 'var(--muted)', fontSize: 10 }}>●</span>}
          <span title={p.title} style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.title}</span>
        </div>
        <div className="an-row-meta">
          <span className={`badge ${p.badge === 'source-cached' ? 'cached' : p.badge === 'waiting' ? 'pending' : p.badge}`} data-testid={`row-badge-${p.testIndex}`} title={p.badgeTitle}>{p.badgeText ?? (p.badge === 'source-cached' ? 'cached' : p.badge)}</span>
          {p.timingText && <span className="timing" title="core step time · 0 s means restored from the prefix cache">{p.timingText}</span>}
          <span title="type signature">{p.signature}</span>
        </div>
        <div className="an-row-caption" title={p.captionTitle ?? p.caption}>{p.caption}</div>
        <div className="an-row-icons">
          <button className="icon-btn active" title="open settings (block page)" onClick={p.onSettings} disabled={!p.onSettings} data-testid={`settings-step-${p.testIndex}`}><svg width="14" height="14" viewBox="0 0 24 24">{I.settings}</svg></button>
          <button className="icon-btn" title="bypass · out of slice scope" disabled><svg width="14" height="14" viewBox="0 0 24 24">{I.bypass}</svg></button>
          <button className="icon-btn" title="duplicate · out of slice scope" disabled><svg width="14" height="14" viewBox="0 0 24 24">{I.duplicate}</svg></button>
          <button className="icon-btn" title={p.onDelete ? 'delete this stage' : 'the source cannot be deleted'} onClick={p.onDelete} disabled={!p.onDelete} data-testid={`delete-step-${p.testIndex}`}><svg width="14" height="14" viewBox="0 0 24 24">{I.delete}</svg></button>
        </div>
      </div>
      {p.replace ? (
        <div data-testid={`row-plot-${p.testIndex}`}>{p.replace}</div>
      ) : (
        <div className="plot-surface an-plot" ref={ref} data-testid={`row-plot-${p.testIndex}`}>
          <ErrorBoundary label={label}>
            {size.width > 0 && p.plot(x, w, PLOT_H)}
          </ErrorBoundary>
          {p.overlay}
          {size.width > 0 && (
            <svg className="cross" width={w} height={PLOT_H}>
              <CrosshairLayer x={x} height={PLOT_H} />
            </svg>
          )}
        </div>
      )}
    </div>
  )
}
