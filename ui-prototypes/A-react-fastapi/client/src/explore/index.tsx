/* Explore workspace entry — routes #/explore/corpus and #/explore/signal/<channelId>.
   STUB: replaced by the Explore builder (CorpusPage.tsx, SignalPage.tsx). */
import { Header } from '../shell/Header'
import { useApp } from '../state'

export function ExplorePage() {
  const { route } = useApp()
  return (
    <>
      <Header workspace="Explore" page={route.page === 'signal' ? 'Signal' : 'Corpus'} subtitle="bird's-eye across every channel" />
      <div className="page"><div className="page-inner"><div className="card card-pad">Explore — to be built</div></div></div>
    </>
  )
}
