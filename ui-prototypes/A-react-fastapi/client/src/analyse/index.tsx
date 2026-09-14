/* Analyse workspace entry — routes #/analyse/chain and #/analyse/block/<index>.
   STUB: replaced by the Analyse builder (ChainPage.tsx, BlockPage.tsx, InsertStageModal.tsx, Renderer.tsx, useRun.ts). */
import { Header } from '../shell/Header'
import { useApp } from '../state'

export function AnalysePage() {
  const { route } = useApp()
  return (
    <>
      <Header workspace="Analyse" page={route.page === 'block' ? 'Block' : 'Chain'} subtitle="build here · open a block to tune it" />
      <div className="page"><div className="page-inner"><div className="card card-pad">Analyse — to be built</div></div></div>
    </>
  )
}
