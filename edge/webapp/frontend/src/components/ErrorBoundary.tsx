import { Component, type ReactNode } from 'react'

// Keeps a WebGL failure (driver/library mismatch, lost context) from taking the
// whole dashboard down — the 3D core degrades to its CSS glow fallback instead.
export class ErrorBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(err: unknown) { console.error('VitalsCore failed:', err) }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}
