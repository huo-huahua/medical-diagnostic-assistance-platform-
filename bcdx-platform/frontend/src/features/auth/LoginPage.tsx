import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  Brain,
  Database,
  Eye,
  EyeOff,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'

import { useAuth } from '@/lib/store'
import { useToast } from '@/components/Toast'
import { ApiError } from '@/api'

type Mode = 'login' | 'register'

const HIGHLIGHTS = [
  {
    icon: Brain,
    title: '可解释推断',
    body: '每个结论都附带 SHAP 特征贡献归因，能看到“为什么”。',
  },
  {
    icon: Database,
    title: '本地知识检索',
    body: '医学问答默认完全离线，不产生任何外部调用费用。',
  },
  {
    icon: ShieldCheck,
    title: '多重账号隔离',
    body: 'JWT 会话 + 逐用户数据隔离，预测历史互不可见。',
  },
]

const DEMO = { email: 'demo@bcdx.dev', password: 'demo12345' }

export default function LoginPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { login, register, status } = useAuth()

  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Already signed in (e.g. token restored) -> go straight through.
  useEffect(() => {
    if (status === 'authenticated') navigate('/dashboard', { replace: true })
  }, [status, navigate])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!email.trim()) return setError('请输入邮箱')
    if (!password) return setError('请输入密码')
    if (mode === 'register') {
      if (!displayName.trim()) return setError('请输入展示名称')
      if (password.length < 8) return setError('密码至少 8 位')
      if (password.length > 128) return setError('密码过长')
    }

    setBusy(true)
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
        toast.success('登录成功', '欢迎回到 BC-Dx Platform')
      } else {
        await register(email.trim(), displayName.trim(), password)
        toast.success('注册成功', '首个注册账号将自动获得管理员权限')
      }
      navigate('/dashboard', { replace: true })
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : '操作失败，请稍后重试'
      setError(msg)
      toast.error(mode === 'login' ? '登录失败' : '注册失败', msg)
    } finally {
      setBusy(false)
    }
  }

  const fillDemo = () => {
    setMode('login')
    setEmail(DEMO.email)
    setPassword(DEMO.password)
    setError(null)
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.05fr_1fr]">
      {/* ------------------------------------------------------------------ */}
      {/* Brand panel                                                        */}
      {/* ------------------------------------------------------------------ */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-line bg-canvas-soft/60 p-10 lg:flex">
        <div className="grid-lines pointer-events-none absolute inset-0 opacity-60" />
        <div
          className="pointer-events-none absolute -left-24 top-1/4 h-[420px] w-[420px] rounded-full opacity-40 blur-3xl"
          style={{
            background:
              'radial-gradient(circle, rgba(14,165,183,.55) 0%, transparent 70%)',
          }}
        />

        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-glow">
              <Sparkles className="h-5 w-5 text-white" strokeWidth={2.2} />
            </div>
            <div>
              <p className="text-base font-bold tracking-tight text-ink">
                BC-Dx Platform
              </p>
              <p className="text-2xs text-ink-faint">
                Clinical Decision Support · Open Source
              </p>
            </div>
          </div>

          <h1 className="mt-12 max-w-md text-3xl font-bold leading-tight tracking-tight text-ink">
            让机器学习模型
            <span className="bg-gradient-to-r from-brand-300 to-brand-500 bg-clip-text text-transparent">
              说出依据
            </span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-ink-muted">
            面向乳腺癌与心脏病的全栈辅助评估平台。统计模型给出风险概率，
            SHAP 给出特征归因，本地知识库给出可核查的医学解释 ——
            全过程可复现、可审计、低成本。
          </p>
        </div>

        <div className="relative mt-10 space-y-3">
          {HIGHLIGHTS.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="flex items-start gap-3.5 rounded-2xl border border-line bg-canvas-raised/50 p-4 backdrop-blur-sm"
            >
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-brand-500/25 bg-brand-500/10">
                <Icon className="h-4 w-4 text-brand-300" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-faint">
                  {body}
                </p>
              </div>
            </div>
          ))}
        </div>

        <div className="relative mt-10 flex flex-wrap items-center gap-x-5 gap-y-2 text-2xs text-ink-ghost">
          <span className="inline-flex items-center gap-1.5">
            <Zap className="h-3 w-3" />
            FastAPI + React 全栈
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Activity className="h-3 w-3" />
            公开数据集训练
          </span>
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="h-3 w-3" />
            MIT License
          </span>
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Form panel                                                         */}
      {/* ------------------------------------------------------------------ */}
      <main className="flex items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-sm animate-fade-up">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-2.5">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-glow">
                <Sparkles className="h-4.5 w-4.5 text-white" />
              </div>
              <p className="text-sm font-bold text-ink">BC-Dx Platform</p>
            </div>
          </div>

          {/* Mode switch */}
          <div className="mb-6 flex rounded-xl border border-line bg-canvas-soft/70 p-1">
            {(
              [
                { key: 'login', label: '登录' },
                { key: 'register', label: '注册' },
              ] as Array<{ key: Mode; label: string }>
            ).map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setMode(key)
                  setError(null)
                }}
                className={clsx(
                  'flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition-all duration-200',
                  mode === key
                    ? 'bg-brand-500/15 text-brand-200 shadow-[inset_0_0_0_1px] shadow-brand-500/30'
                    : 'text-ink-faint hover:text-ink-muted',
                )}
              >
                {label}
              </button>
            ))}
          </div>

          <h2 className="text-xl font-bold tracking-tight text-ink">
            {mode === 'login' ? '登录你的工作台' : '创建新账号'}
          </h2>
          <p className="mt-1.5 text-xs leading-relaxed text-ink-faint">
            {mode === 'login'
              ? '使用邮箱与密码登录，预测记录将按账号隔离保存。'
              : '注册后即可独立使用全部功能，数据仅自己可见。'}
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <div>
              <label className="label" htmlFor="email">
                邮箱
              </label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-ghost" />
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  className="field pl-10"
                />
              </div>
            </div>

            {mode === 'register' && (
              <div className="animate-fade-up">
                <label className="label" htmlFor="display_name">
                  展示名称
                </label>
                <div className="relative">
                  <UserIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-ghost" />
                  <input
                    id="display_name"
                    type="text"
                    autoComplete="nickname"
                    maxLength={40}
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="例如：张医生"
                    className="field pl-10"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="label" htmlFor="password">
                密码
              </label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-ghost" />
                <input
                  id="password"
                  type={reveal ? 'text' : 'password'}
                  autoComplete={
                    mode === 'login' ? 'current-password' : 'new-password'
                  }
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === 'register' ? '至少 8 位，字母+数字' : '••••••••'}
                  className="field pl-10 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setReveal((v) => !v)}
                  aria-label={reveal ? '隐藏密码' : '显示密码'}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-ink-ghost transition-colors hover:text-ink-muted"
                >
                  {reveal ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            {error && (
              <p
                role="alert"
                className="animate-scale-in rounded-xl border border-risk-high/40 bg-risk-highSoft/60 px-3 py-2.5 text-xs leading-relaxed text-risk-high"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="btn-primary w-full"
            >
              {busy ? (
                <>
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  处理中…
                </>
              ) : (
                <>
                  {mode === 'login' ? '登录' : '注册并进入'}
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6">
            <div className="flex items-center gap-3">
              <div className="divider flex-1" />
              <span className="text-2xs uppercase tracking-wider text-ink-ghost">
                或
              </span>
              <div className="divider flex-1" />
            </div>

            <button
              type="button"
              onClick={fillDemo}
              disabled={busy}
              className="btn-ghost mt-5 w-full"
            >
              <Zap className="h-4 w-4 text-brand-400" />
              填入演示账号
            </button>
            <p className="mt-2.5 text-center text-2xs leading-relaxed text-ink-ghost">
              演示账号 <span className="font-mono text-ink-faint">demo@bcdx.dev</span>{' '}
              / <span className="font-mono text-ink-faint">demo12345</span>
              <br />
              首次部署时可先注册一个自己的账号。
            </p>
          </div>

          <p className="mt-8 text-center text-2xs leading-relaxed text-ink-ghost">
            本平台为科研与教学演示用途，非医疗器械，
            <br />
            所有结果不构成医疗建议。
          </p>
        </div>
      </main>
    </div>
  )
}
