/* Escape + click-outside dismissal for modals and popovers (critique r1: nothing closed on Escape). */
import { useEffect, type RefObject } from 'react'

export function useDismiss(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    const onDown = (e: PointerEvent) => {
      const el = ref.current
      if (el && !el.contains(e.target as Node)) onClose()
    }
    document.addEventListener('keydown', onKey)
    // defer so the click that opened the surface does not immediately close it
    const id = window.setTimeout(() => document.addEventListener('pointerdown', onDown), 0)
    return () => { document.removeEventListener('keydown', onKey); window.clearTimeout(id); document.removeEventListener('pointerdown', onDown) }
  }, [ref, onClose, active])
}
