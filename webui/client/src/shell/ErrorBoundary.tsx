/* Loud failure: a thrown render error replaces the failed subtree with a red card
   carrying the message and component stack, and is logged to the console (so the
   Playwright gate fails too). Nothing is silently blank. */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props { children: ReactNode; label?: string; onError?: (error: Error) => void; compact?: boolean }
interface State { error: Error | null; info: string }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: '' }
  static getDerivedStateFromError(error: Error): Partial<State> { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[render error in ${this.props.label ?? 'component'}]`, error, info.componentStack)
    this.setState({ info: info.componentStack ?? '' })
    this.props.onError?.(error)   // lets a host (e.g. a chain row) lift the failure into its own state/badge
  }
  render() {
    if (this.state.error) {
      return (
        <div className="error-card" role="alert" data-testid="render-error">
          <h3>⚠ {this.props.label ?? 'This pane'} failed to render</h3>
          <div className="mono" style={{ fontSize: 12 }}>{String(this.state.error?.message ?? this.state.error)}</div>
          <pre>{this.state.error?.stack}{this.state.info}</pre>
          <button className="btn sm" style={{ marginTop: 8 }} onClick={() => this.setState({ error: null, info: '' })}>Try again</button>
        </div>
      )
    }
    return this.props.children
  }
}
