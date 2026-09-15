/* Escape + click-outside dismissal for modals and popovers (critique r1: nothing closed on Escape). */
import { useEffect, type RefObject } from 'react'

export function useDismiss(ref: RefObject<HTMLElement | null>, onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
      // critique r2: keep Tab inside a dialog (aria-modal) instead of walking to the page behind it
      const el = ref.current
      const dlg = el?.matches('[role=dialog]') ? el : el?.querySelector<HTMLElement>('[role=dialog]')
      if (e.key !== 'Tab' || !dlg) return
      const items = Array.from(dlg.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      if (e.shiftKey && (document.activeElement === first || !dlg.contains(document.activeElement))) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (document.activeElement === last || !dlg.contains(document.activeElement))) { e.preventDefault(); first.focus() }
    }
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
