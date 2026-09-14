/* 64 px nav rail (frame shell-nav-rail): logo tile, six workspaces, then Jobs and Settings at the foot. */
import { navigate, useApp } from '../state'

const I = {
  explore: <path d="M3 12h3l2-6 3 12 3-9 2 6 2-3h3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />,
  analyse: <g fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /><path d="M10.5 7h4a2 2 0 0 1 2 2v4.5" /></g>,
  discovery: <g fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" fill="currentColor" /></g>,
  models: <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><path d="M9 4.5a3.5 3.5 0 0 0-3.5 3.5v8A3.5 3.5 0 0 0 9 19.5M15 4.5a3.5 3.5 0 0 1 3.5 3.5v8a3.5 3.5 0 0 1-3.5 3.5M12 4v16M8 9h4M12 15h4" /></g>,
  review: <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 7h8M12 15h8" /></g>,
  library: <g fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="4" y="4" width="4" height="16" rx="1" /><rect x="10" y="4" width="4" height="16" rx="1" /><path d="M16.5 5l3.5 14.5" /></g>,
  jobs: <g fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M12 8v1.5M12 14.5V16M8 12h1.5M14.5 12H16" /></g>,
  settings: <g fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" /></g>,
}

const TOP: { key: string; label: string; icon: keyof typeof I; to: string }[] = [
  { key: 'explore', label: 'Explore', icon: 'explore', to: 'explore/corpus' },
  { key: 'analyse', label: 'Analyse', icon: 'analyse', to: 'analyse/chain' },
  { key: 'discovery', label: 'Discovery', icon: 'discovery', to: 'discovery' },
  { key: 'models', label: 'Models', icon: 'models', to: 'models' },
  { key: 'review', label: 'Review', icon: 'review', to: 'review' },
  { key: 'library', label: 'Library', icon: 'library', to: 'library' },
]

export function NavRail() {
  const { route, liveJobs } = useApp()
  const Item = ({ k, label, icon, to }: { k: string; label: string; icon: keyof typeof I; to: string }) => {
    const on = route.workspace === k
    return (
      <button className={`rail-item${on ? ' on' : ''}`} onClick={() => navigate(to)} title={label} data-testid={`nav-${k}`}>
        <svg width="22" height="22" viewBox="0 0 24 24">{I[icon]}</svg>
        <span>{label}</span>
      </button>
    )
  }
  return (
    <nav className="rail" data-testid="nav-rail">
      <div className="rail-logo" title="Underground Brains">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round"><path d="M12 20V10M12 10c0-4 3-6 7-6 0 4-3 6-7 6zM12 13c0-3-2.5-5-6-5 0 3 2.5 5 6 5z" /></svg>
      </div>
      <div className="rail-group">{TOP.map(t => <Item key={t.key} k={t.key} label={t.label} icon={t.icon} to={t.to} />)}</div>
      <div className="rail-foot">
        <Item k="jobs" label={liveJobs ? `Jobs · ${liveJobs}` : 'Jobs'} icon="jobs" to="jobs" />
        <div className="rail-sep" />
        <Item k="settings" label="Settings" icon="settings" to="settings" />
      </div>
      <style>{`
        .rail { width: var(--rail-w); background: var(--card); border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; padding: 10px 0 12px; height: 100%; }
        .rail-logo { width: 38px; height: 38px; border-radius: 10px; background: var(--blue); display: flex; align-items: center; justify-content: center; margin-bottom: 18px; }
        .rail-group { display: flex; flex-direction: column; gap: 6px; }
        .rail-foot { margin-top: auto; display: flex; flex-direction: column; gap: 6px; align-items: center; }
        .rail-sep { width: 36px; height: 1px; background: var(--border); margin: 4px 0; }
        .rail-item { width: 54px; height: 50px; border: 0; background: transparent; border-radius: 9px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px; color: var(--muted); }
        .rail-item span { font-size: 10px; font-family: var(--font-ui); letter-spacing: 0.01em; white-space: nowrap; }
        .rail-item:hover { background: var(--grey-100); color: var(--text); }
        .rail-item.on { background: var(--blue-100); color: var(--blue); }
      `}</style>
    </nav>
  )
}
