import clsx from 'clsx'

/** Small presentational primitives reused across every feature page. */

export function Panel({
  children,
  className,
  raised,
}: {
  children: React.ReactNode
  className?: string
  raised?: boolean
}) {
  return (
    <section className={clsx(raised ? 'panel-raised' : 'panel', className)}>
      {children}
    </section>
  )
}

export function PanelHeader({
  title,
  subtitle,
  icon: Icon,
  actions,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  actions?: React.ReactNode
}) {
  return (
    <div className="panel-header">
      <div className="min-w-0">
        <h2 className="panel-title">
          {Icon && <Icon className="h-4 w-4 shrink-0 text-brand-400" />}
          <span className="truncate">{title}</span>
        </h2>
        {subtitle && (
          <p className="mt-1 text-xs leading-relaxed text-ink-faint">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatCard({
  label,
  value,
  unit,
  hint,
  tone = 'neutral',
  icon: Icon,
}: {
  label: string
  value: string | number
  unit?: string
  hint?: string
  tone?: 'neutral' | 'brand' | 'risk' | 'safe' | 'warn'
  icon?: React.ComponentType<{ className?: string }>
}) {
  const toneCls = {
    neutral: 'text-ink',
    brand: 'text-brand-300',
    risk: 'text-risk-high',
    safe: 'text-risk-low',
    warn: 'text-risk-warn',
  }[tone]

  return (
    <div className="panel group relative overflow-hidden p-4 transition-colors duration-200 hover:border-line-strong">
      <div className="absolute inset-0 bg-brand-sheen opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="relative">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="text-2xs font-semibold uppercase tracking-wider text-ink-faint">
            {label}
          </p>
          {Icon && <Icon className="h-3.5 w-3.5 text-ink-ghost" />}
        </div>
        <p className={clsx('stat-value', toneCls)}>
          {value}
          {unit && <span className="ml-1 text-sm font-normal text-ink-faint">{unit}</span>}
        </p>
        {hint && <p className="mt-1.5 text-2xs leading-relaxed text-ink-faint">{hint}</p>}
      </div>
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {Icon && (
        <div className="grid h-12 w-12 place-items-center rounded-2xl border border-line-strong bg-canvas-raised/60">
          <Icon className="h-5 w-5 text-ink-ghost" />
        </div>
      )}
      <p className="text-sm font-semibold text-ink-muted">{title}</p>
      {description && (
        <p className="max-w-sm text-xs leading-relaxed text-ink-faint">{description}</p>
      )}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />
}

export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2.5 p-5">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={clsx('h-10', i === rows - 1 && 'w-2/3')} />
      ))}
    </div>
  )
}

export function Disclaimer({ compact }: { compact?: boolean }) {
  return (
    <p
      className={clsx(
        'flex items-start gap-2 rounded-xl border border-risk-warn/25 bg-risk-warnSoft/25 px-3 py-2.5 text-2xs leading-relaxed text-risk-warn/90',
        compact && 'px-2.5 py-2',
      )}
    >
      <span aria-hidden className="mt-px shrink-0">
        ⚠
      </span>
      <span>
        本结果由统计模型生成，反映群体规律而非个体临床结论，
        <strong className="font-semibold">不能作为诊断依据</strong>。
        请携带完整检查报告咨询执业医师。
      </span>
    </p>
  )
}
