/* Analyse workspace entry — routes #/analyse/chain and #/analyse/block/<index>. */
import './analyse.css'
import { useApp } from '../state'
import { BlockPage } from './BlockPage'
import { ChainPage } from './ChainPage'

export function AnalysePage() {
  const { route } = useApp()
  if (route.page === 'block') {
    const idx = Number(route.params.id)
    return <BlockPage index={Number.isFinite(idx) ? idx : 0} />
  }
  return <ChainPage />
}
