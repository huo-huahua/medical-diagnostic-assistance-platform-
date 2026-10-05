import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Copy, Home, RotateCcw } from 'lucide-react'

import { Panel } from '@/components/ui'

/**
 * Catches render-time crashes and shows a recoverable panel instead of a blank page.
 *
 * Why this exists at all: an uncaught error during render makes React unmount the
 * whole tree, so one bad property access anywhere takes down the entire
 * application. That is not hypothetical here — reading `health.data.llm.cache`
 * off a response that had not loaded yet did exactly that to the dashboard once,
 * and it was found by opening a browser, not by a test.
 *
 * Two things this deliberately is *not*:
 *
 * - It is not a fix for the underlying bug. It contains the blast radius; the
 *   bad read still has to be fixed where it lives. A boundary that is described
 *   as "solved" hides the real defect.
 * - It is not a hook. `getDerivedStateFromError` / `componentDidCatch` have no
 *   functional equivalent, so this is the one class component in the codebase.
 *
 * The `key` matters more than it looks. Callers should key this by route, or the
 * boundary instance survives navigation with `error` still set and the user is
 * stuck looking at the failure panel forever, unable to reach any other page.
 */
interface Props {
  children: ReactNode
  /** Human name for the crashed region, e.g. a page label. */
  label?: string
  /**
   * Run before the reset. A crash caused by cached data will simply recur unless
   * the cache is dropped, so callers usually pass a query-cache reset here.
   */
  onReset?: () => void
}

interface State {
  error: Error | null
  info: ErrorInfo | null
  copied: boolean
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null, copied: false }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept on the console as well as on screen: the panel is for the reader, and
    // the component stack is what a developer needs to find the throw site.
    console.error('[ErrorBoundary] render failed', error, info.componentStack)
    this.setState({ info })
  }

  private details = () => {
    const { error, info } = this.state
    return [
      `BC-Dx Platform UI error`,
      `region: ${this.props.label ?? 'unknown'}`,
      `url: ${typeof window === 'undefined' ? '-' : window.location.href}`,
      `time: ${new Date().toISOString()}`,
      ``,
      `${error?.name ?? 'Error'}: ${error?.message ?? 'unknown'}`,
      ``,
      error?.stack ?? '(no stack)',
      ``,
      'component stack:',
      info?.componentStack ?? '(none)',
    ].join('\n')
  }

  private handleCopy = async () => {
    const text = this.details()
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        // `navigator.clipboard` is unavailable outside a secure context. The
        // app is normally served over http on localhost, which counts as
        // secure — but a deployment on plain http over a LAN address does not,
        // and "copy" silently doing nothing is a confusing failure.
        const area = document.createElement('textarea')
        area.value = text
        area.style.position = 'fixed'
        area.style.opacity = '0'
        document.body.appendChild(area)
        area.select()
        document.execCommand('copy')
        document.body.removeChild(area)
      }
      this.setState({ copied: true })
    } catch {
      this.setState({ copied: false })
    }
  }

  private handleRetry = () => {
    // Order matters: clear the cache first, then clear the error. Clearing the
    // error first would re-render immediately against the same bad data and
    // throw again before the reset had any effect.
    this.props.onReset?.()
    this.setState({ error: null, info: null, copied: false })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <Panel className="overflow-hidden" raised>
        <div className="flex flex-col gap-4 px-5 py-8">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-risk-high/30 bg-risk-highSoft/40">
              <AlertTriangle className="h-5 w-5 text-risk-high" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">
                这一部分未能正常显示
              </p>
              <p className="mt-1 text-xs leading-relaxed text-ink-faint">
                {this.props.label ? `出错区域：${this.props.label}。` : ''}
                其余页面仍可正常使用 —— 刷新通常能恢复；如果反复出现，请把下面的错误详情反馈给维护者。
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={this.handleRetry} className="btn btn-primary">
              <RotateCcw className="h-3.5 w-3.5" />
              重试
            </button>
            <Link to="/dashboard" className="btn btn-ghost">
              <Home className="h-3.5 w-3.5" />
              返回总览
            </Link>
            <button type="button" onClick={this.handleCopy} className="btn btn-ghost">
              <Copy className="h-3.5 w-3.5" />
              {this.state.copied ? '已复制' : '复制错误详情'}
            </button>
          </div>

          <details className="rounded-xl border border-line bg-canvas/60">
            <summary className="cursor-pointer px-3.5 py-2.5 text-xs font-semibold text-ink-muted">
              错误详情（供排查）
            </summary>
            <pre className="scroll-area max-h-72 overflow-auto border-t border-line px-3.5 py-3 font-mono text-[0.6875rem] leading-relaxed text-ink-faint">
              {error.name}: {error.message}
              {this.state.info?.componentStack
                ? `\n\n组件调用栈：${this.state.info.componentStack}`
                : ''}
            </pre>
          </details>
        </div>
      </Panel>
    )
  }
}
