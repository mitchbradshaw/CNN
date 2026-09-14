import { useEffect, useRef, useState } from 'react'

/** Observe an element's width/height (ResizeObserver) so SVG surfaces size to their card. */
export function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, { width: number; height: number }] {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const { width, height } = e.contentRect
        setSize(s => (Math.abs(s.width - width) > 0.5 || Math.abs(s.height - height) > 0.5) ? { width, height } : s)
      }
    })
    ro.observe(el)
    setSize({ width: el.clientWidth, height: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  return [ref, size]
}
