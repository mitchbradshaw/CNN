/* Shell + routing. Explore and Analyse are live; the other workspaces are visible but inert. */
import { useEffect } from 'react'
import { listRuns } from './api'
import { AnalysePage } from './analyse'
import { ExplorePage } from './explore'
import { ErrorBoundary } from './shell/ErrorBoundary'
import { Header } from './shell/Header'
import { NavRail } from './shell/NavRail'
import { ToastProvider } from './shell/Toast'
import { AppProvider, useApp } from './state'

const INERT: Record<string, { page: string; subtitle: string }> = {
  discovery: { page: 'Runs', subtitle: 'apply finished recipes at scale · out of slice scope' },
  models: { page: 'Launch', subtitle: 'train from Analyse templates · out of slice scope' },
  review: { page: 'Queue', subtitle: 'named queues, one source each · out of slice scope' },
  library: { page: 'Atlas', subtitle: 'motifs · window sets · templates · out of slice scope' },
  jobs: { page: 'All jobs', subtitle: 'every job across workspaces · out of slice scope' },
  settings: { page: 'Datasets', subtitle: 'project and personal settings · out of slice scope' },
}

function Inert({ ws }: { ws: string }) {
  const spec = INERT[ws] ?? { page: '', subtitle: '' }
  return (
    <>
      <Header workspace={ws[0].toUpperCase() + ws.slice(1)} page={spec.page} subtitle={spec.subtitle} />
      <div className="page"><div className="page-inner">
        <div className="card card-pad" style={{ maxWidth: 640 }}>
          <div className="card-title">{ws} — visible, inert</div>
          <p className="muted" style={{ margin: '8px 0 0' }}>This workspace is outside the vertical slice (task brief: the shell must show it; Explore and Analyse are live). Its concept pages live in <span className="mono">prototyping/imgs/{ws}/</span>.</p>
        </div>
      </div></div>
    </>
  )
}

function Body() {
  const { route, setLiveJobs, setNeedYou } = useApp()
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await listRuns(undefined, 1)
        if (!alive) return
        setLiveJobs(r.jobs.filter(j => j.status === 'running').length)
        setNeedYou(r.jobs.filter(j => j.status === 'failed').length)
      } catch { /* header counts are best-effort */ }
    }
    tick(); const id = window.setInterval(tick, 5000)
    return () => { alive = false; window.clearInterval(id) }
  }, [setLiveJobs, setNeedYou])
  const ws = route.workspace
  return (
    <div className="app">
      <NavRail />
      <div className="main">
        <ErrorBoundary label={`${ws} workspace`}>
          {ws === 'explore' ? <ExplorePage /> : ws === 'analyse' ? <AnalysePage /> : <Inert ws={ws} />}
        </ErrorBoundary>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <ToastProvider>
        <ErrorBoundary label="application">
          <Body />
        </ErrorBoundary>
      </ToastProvider>
    </AppProvider>
  )
}
