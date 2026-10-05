import { useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BarChart3,
  Brain,
  FlaskConical,
  HeartPulse,
  Layers,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Microscope,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import clsx from 'clsx'

import { setUnauthorizedHandler } from '@/api'
import { useAuth, useWorkspace } from '@/lib/store'
import { useToast } from '@/components/Toast'
import ErrorBoundary from '@/components/ErrorBoundary'
import type { Disease } from '@/types'

const NAV = [
  { to: '/dashboard', label: '总览', icon: LayoutDashboard, hint: '系统与个人统计' },
  { to: '/diagnosis', label: '智能诊断', icon: Microscope, hint: '输入指标获得评估' },
  { to: '/batch', label: '批量评估', icon: Layers, hint: '一次给多份样本打分' },
  { to: '/explain', label: '可解释分析', icon: Brain, hint: '特征贡献归因' },
  { to: '/assistant', label: '医学问答', icon: MessageSquareText, hint: '本地知识库检索' },
  { to: '/qa-compare', label: '问答对比', icon: FlaskConical, hint: '三条问答链路对照' },
  { to: '/compare', label: '模型对比', icon: BarChart3, hint: '多模型性能对照' },
  { to: '/records', label: '历史记录', icon: Activity, hint: '预测历史回看' },
]

const DISEASES: Array<{ key: Disease; label: string; icon: typeof HeartPulse }> = [
  { key: 'breast', label: '乳腺癌', icon: Microscope },
  { key: 'heart', label: '心脏病', icon: HeartPulse },
]

export default function AppShell() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const toast = useToast()
  const { user, logout, status } = useAuth()
  const { diseases, activeDisease, setActiveDisease, loadDiseases } = useWorkspace()

  useEffect(() => {
    setUnauthorizedHandler(() => {
      toast.warning('登录状态已失效', '请重新登录以继续使用')
      navigate('/login', { replace: true })
    })
  }, [navigate, toast])

  useEffect(() => {
    loadDiseases().catch(() => {
      /* surfaced by individual pages that need the data */
    })
  }, [loadDiseases])

  useEffect(() => {
    if (status === 'anonymous') navigate('/login', { replace: true })
  }, [status, navigate])

  const handleLogout = () => {
    logout()
    toast.info('已退出登录')
    navigate('/login', { replace: true })
  }

  const initial = user?.display_name?.trim()?.[0]?.toUpperCase() ?? 'U'
  const pageLabel = NAV.find((item) => item.to === location.pathname)?.label

  const diseaseSwitcher = (size: 'sidebar' | 'header') => (
    <div
      className={clsx(
        'grid grid-cols-2 gap-1.5',
        size === 'header' && 'gap-1',
      )}
    >
      {DISEASES.map(({ key, label, icon: Icon }) => {
        const available = diseases.some((d) => d.disease === key)
        return (
          <button
            key={key}
            type="button"
            disabled={!available}
            aria-pressed={activeDisease === key}
            onClick={() => setActiveDisease(key)}
            className={clsx(
              'flex items-center gap-1 rounded-lg border font-semibold transition-all duration-150',
              size === 'sidebar'
                ? 'flex-col gap-1 px-2 py-2.5 text-2xs'
                : 'shrink-0 px-2.5 py-1.5 text-2xs',
              activeDisease === key
                ? 'border-brand-500/50 bg-brand-500/12 text-brand-200 shadow-glow'
                : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:border-ink-ghost hover:text-ink-muted',
              !available && 'cursor-not-allowed opacity-40',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="flex h-full">
      {/* Keyboard users should not have to tab through eight nav links to reach
          the page. Visible only on focus. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-brand-600 focus:px-3 focus:py-2 focus:text-xs focus:font-semibold focus:text-white"
      >
        跳到主要内容
      </a>

      {/* ---------------- Sidebar ---------------- */}
      {/*
        Three sizes, not two. `sm`/`md` used to jump straight to `lg`, so the
        tablet range (768–1024px) got the phone layout with a 1024px viewport.
        At `md` the sidebar becomes an icon rail: the labels and the panels are
        hidden, but the disease switcher and the sign-out move into the header
        (which only exists below `lg`), so nothing becomes unreachable.
      */}
      <aside className="hidden shrink-0 flex-col border-r border-line bg-canvas-soft/70 backdrop-blur md:flex md:w-16 lg:w-64">
        <div className="flex items-center gap-2.5 px-3 py-5 md:justify-center lg:justify-start lg:px-5">
          <div className="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-glow">
            <Sparkles className="h-4.5 w-4.5 text-white" strokeWidth={2.2} />
          </div>
          <div className="hidden min-w-0 lg:block">
            <p className="truncate text-sm font-bold tracking-tight text-ink">
              BC-Dx Platform
            </p>
            <p className="truncate text-2xs text-ink-faint">临床决策支持原型</p>
          </div>
        </div>

        <div className="mx-4 mb-4 hidden rounded-xl border border-line bg-canvas/60 p-3 lg:block">
          <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-ink-faint">
            病种模块
          </p>
          {diseaseSwitcher('sidebar')}
        </div>

        <nav className="flex-1 space-y-0.5 px-2 lg:px-3">
          {NAV.map(({ to, label, icon: Icon, hint }) => (
            <NavLink
              key={to}
              to={to}
              title={hint}
              className={({ isActive }) =>
                clsx(
                  'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-150',
                  'md:justify-center lg:justify-start',
                  isActive
                    ? 'bg-brand-500/12 text-brand-100 shadow-[inset_2px_0_0_0] shadow-brand-400'
                    : 'text-ink-muted hover:bg-canvas-hover/70 hover:text-ink',
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {/* `sr-only` rather than `hidden`: display:none would remove the
                  name from the accessibility tree entirely, leaving the rail
                  with eight unlabelled buttons. */}
              <span className="sr-only lg:not-sr-only lg:truncate">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          <div className="mb-2 hidden items-start gap-2 rounded-lg bg-risk-warnSoft/30 px-2.5 py-2 lg:flex">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-risk-warn" />
            <p className="text-2xs leading-relaxed text-risk-warn/90">
              仅供科研与教学演示，非医疗器械，不构成医疗建议
            </p>
          </div>

          <div className="flex items-center gap-2.5 rounded-xl px-2 py-2 md:justify-center lg:justify-start">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-brand-800 text-xs font-bold text-white">
              {initial}
            </div>
            <div className="hidden min-w-0 flex-1 lg:block">
              <p className="truncate text-xs font-semibold text-ink">
                {user?.display_name ?? '未登录'}
              </p>
              <p className="truncate text-2xs text-ink-faint">{user?.email ?? '—'}</p>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              title="退出登录"
              aria-label="退出登录"
              className="hidden rounded-lg p-1.5 text-ink-ghost transition-colors hover:bg-risk-highSoft/50 hover:text-risk-high lg:block"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* ---------------- Main ---------------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Compact header for phone *and* tablet. Two rows instead of one
            horizontally-scrolling row, so the disease switcher fits — without
            it, everything below `lg` had no way to change the active disease
            module at all, even though every page reads it. */}
        <header className="border-b border-line bg-canvas-soft/80 backdrop-blur lg:hidden">
          <div className="flex items-center gap-2.5 px-4 pb-2 pt-3">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-700">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <p className="truncate text-sm font-bold tracking-tight text-ink">
              BC-Dx Platform
            </p>
            <div className="ml-auto">{diseaseSwitcher('header')}</div>
            <button
              type="button"
              onClick={handleLogout}
              title="退出登录"
              aria-label="退出登录"
              className="shrink-0 rounded-lg p-1.5 text-ink-ghost transition-colors hover:text-risk-high"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
          <nav className="flex items-center gap-1.5 overflow-x-auto px-4 pb-2.5">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors',
                    isActive
                      ? 'bg-brand-500/15 text-brand-200'
                      : 'text-ink-muted hover:bg-canvas-hover',
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main
          id="main-content"
          className="scroll-area flex-1 px-4 py-5 md:px-6 md:py-6 lg:px-8 lg:py-7"
        >
          <div className="mx-auto max-w-[1400px] animate-fade-in">
            {/*
              Per-page net so a crash in one page leaves the navigation usable.
              `key` is load-bearing: without it this component instance survives
              navigation with `error` still set, and the reader is trapped on the
              failure panel with no way out.
            */}
            <ErrorBoundary
              key={location.pathname}
              label={pageLabel}
              onReset={() => {
                void queryClient.resetQueries().catch(() => {})
              }}
            >
              <Outlet />
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}
