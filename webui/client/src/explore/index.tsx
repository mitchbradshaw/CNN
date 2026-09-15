/* Explore workspace entry — routes #/explore/corpus and #/explore/signal/<channelId>. */
import { useApp } from '../state'
import { CorpusPage } from './CorpusPage'
import { SignalPage } from './SignalPage'
import './explore.css'

export function ExplorePage() {
  const { route } = useApp()
  if (route.page === 'signal') return <SignalPage key={route.params.id ?? ''} channelId={Number(route.params.id)} />
  return <CorpusPage />
}
