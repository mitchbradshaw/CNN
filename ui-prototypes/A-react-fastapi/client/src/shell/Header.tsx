/* Header (frame shell-header): "Explore | Corpus  bird's-eye across every channel" on the left;
   search pill, "N need you" and "M4 held out" chips on the right. */
import { useApp } from '../state'

export interface HeaderSpec { workspace: string; page: string; subtitle?: string }

export function Header({ workspace, page, subtitle }: HeaderSpec) {
  const { needYou } = useApp()
  return (
    <header className="hdr" data-testid="header">
      <div className="hdr-left">
        <span className="hdr-ws">{workspace}</span>
        <span className="divider-v" />
        <span className="hdr-page">{page}</span>
        {subtitle && <span className="hdr-sub mono">{subtitle}</span>}
      </div>
      <div className="hdr-right">
        <div className="hdr-search mono" role="search"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg><span>Search spans, runs, families</span><kbd>Ctrl K</kbd></div>
        <span className={`chip ${needYou ? 'blue' : 'grey'}`} title="runs in this session that failed or need a decision">● {needYou} need you</span>
        <span className="chip grey" title="M4_aug_concat_fs1.mat is held out (D6): every workspace refuses it"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg> M4 held out</span>
      </div>
      <style>{`
        .hdr { height: var(--header-h); display: flex; align-items: center; justify-content: space-between; padding: 0 20px; background: var(--bg); border-bottom: 1px solid var(--border); flex: none; }
        .hdr-left { display: flex; align-items: center; gap: 12px; }
        .hdr-ws { font-weight: 700; font-size: 15px; }
        .hdr-page { font-size: 13.5px; color: var(--text-2); }
        .hdr-sub { font-size: 11px; color: var(--muted); }
        .hdr-right { display: flex; align-items: center; gap: 8px; }
        .hdr-search { display: flex; align-items: center; gap: 8px; height: 28px; padding: 0 12px; border-radius: 999px; background: var(--card); border: 1px solid var(--border); color: var(--muted); font-size: 11.5px; min-width: 280px; }
        .hdr-search kbd { margin-left: auto; font-family: var(--font-mono); font-size: 10px; color: var(--muted-2); }
      `}</style>
    </header>
  )
}
