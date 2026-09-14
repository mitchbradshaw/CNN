/* Bottom-centre toasts (frame chain-1e: "03 Symbolic encoding deleted  Undo Ctrl Z"). */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'

export interface ToastSpec { id: number; text: string; kind?: 'info' | 'error'; action?: { label: string; onClick: () => void }; ttlMs?: number }
interface ToastApi { push: (t: Omit<ToastSpec, 'id'>) => number; dismiss: (id: number) => void }
const Ctx = createContext<ToastApi | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastSpec[]>([])
  const seq = useRef(1)
  const dismiss = useCallback((id: number) => setItems(xs => xs.filter(x => x.id !== id)), [])
  const push = useCallback((t: Omit<ToastSpec, 'id'>) => {
    const id = seq.current++
    setItems(xs => [...xs, { ...t, id }])
    window.setTimeout(() => dismiss(id), t.ttlMs ?? (t.kind === 'error' ? 12000 : 6000))
    return id
  }, [dismiss])
  const api = useMemo(() => ({ push, dismiss }), [push, dismiss])
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toast-host" data-testid="toasts">
        {items.map(t => (
          <div key={t.id} className={`toast${t.kind === 'error' ? ' error' : ''}`}>
            <span>{t.text}</span>
            {t.action && <button className="btn sm" onClick={() => { t.action!.onClick(); dismiss(t.id) }}>{t.action.label}</button>}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export function useToast(): ToastApi {
  const v = useContext(Ctx)
  if (!v) throw new Error('useToast outside ToastProvider')
  return v
}
