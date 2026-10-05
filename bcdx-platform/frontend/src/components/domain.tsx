import clsx from 'clsx'
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  ShieldQuestion,
} from 'lucide-react'

import { CONFIDENCE_META, pct, cx } from '@/lib/format'
import type { ConfidenceBand, PredictResult } from '@/types'

/**
 * Verdict presentation.
 *
 * Colour is never the only signal: every verdict carries an icon, a Chinese
 * label and an explicit probability. Residual hue-blindness risk is covered
 * by the text badge.
 */

interface VerdictTheme {
  labelCls: string
  ringCls: string
  glowCls: string
  barCls: string
  Icon: typeof AlertTriangle
}

const THEME: Record<'positive' | 'negative', VerdictTheme> = {
  positive: {
    labelCls: 'text-risk-high',
    ringCls: 'border-risk-high/45 bg-risk-highSoft/40',
    glowCls: 'shadow-glow-risk',
    barCls: 'from-risk-high/25 to-risk-high',
    Icon: AlertTriangle,
  },
  negative: {
    labelCls: 'text-risk-low',
    ringCls: 'border-risk-low/45 bg-risk-lowSoft/40',
    glowCls: 'shadow-glow-safe',
    barCls: 'from-risk-low/25 to-risk-low',
    Icon: CheckCircle2,
  },
}

export function verdictTheme(verdict: string): VerdictTheme {
  return THEME[verdict === 'positive' ? 'positive' : 'negative']
}

/** Big, unmissable verdict block for the diagnosis result. */
export function VerdictHero({ result }: { result: PredictResult }) {
  const theme = verdictTheme(result.verdict)
  const conf = CONFIDENCE_META[result.confidence_band as ConfidenceBand]
  const positive = result.verdict === 'positive'

  return (
    <div
      className={cx(
        'relative overflow-hidden rounded-2xl border p-6',
        theme.ringCls,
        theme.glowCls,
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full opacity-25 blur-3xl"
        style={{
          background: positive
            ? 'radial-gradient(circle, #f2545b 0%, transparent 70%)'
            : 'radial-gradient(circle, #3ecf8e 0%, transparent 70%)',
        }}
      />

      <div className="relative flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0 flex-1">
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-ink-faint">
            模型判定结果
          </p>

          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            <theme.Icon className={cx('h-7 w-7 shrink-0', theme.labelCls)} />
            <h2
              className={cx(
                'text-3xl font-bold tracking-tight',
                theme.labelCls,
              )}
            >
              {result.verdict_label}
            </h2>
            <span className={conf.cls}>{conf.label}置信</span>
          </div>

          <p className="mt-3 text-sm leading-relaxed text-ink-muted">
            {positive
              ? `模型评估该样本属于「${result.verdict_label}」的概率为 `
              : `模型评估该样本属于「${result.verdict_label}」的概率为 `}
            <span className={cx('font-mono font-semibold', theme.labelCls)}>
              {pct(positive ? result.positive_prob : result.negative_prob, 2)}
            </span>
            ，判定阈值为{' '}
            <span className="font-mono text-ink">{result.threshold.toFixed(4)}</span>。
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-2xs text-ink-faint">
            <span>
              算法 <span className="font-semibold text-ink-muted">{result.algorithm_zh}</span>
            </span>
            <span>
              模型 <span className="font-mono text-ink-muted">{result.model_id}</span>
            </span>
            <span>
              耗时 <span className="font-mono text-ink-muted">{result.elapsed_ms} ms</span>
            </span>
            {result.explanation && (
              <span>
                归因方法{' '}
                <span className="font-mono text-ink-muted">
                  {result.explanation.method}
                </span>
              </span>
            )}
          </div>
        </div>

        {/* Probability dial */}
        <ProbabilityDial
          value={result.positive_prob}
          threshold={result.threshold}
          positive={positive}
        />
      </div>

      <p className="relative mt-5 flex items-start gap-2 border-t border-line/60 pt-3.5 text-2xs leading-relaxed text-ink-faint">
        <Info className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>{conf.hint}</span>
      </p>
    </div>
  )
}

/** Compact probability gauge: an arc plus an explicit numeric reading. */
export function ProbabilityDial({
  value,
  threshold,
  positive,
  size = 132,
}: {
  value: number
  threshold: number
  positive: boolean
  size?: number
}) {
  const stroke = 9
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  // 270° sweep gauge, opening at the bottom.
  const sweep = 0.75
  const track = circumference * sweep
  const filled = track * Math.min(Math.max(value, 0), 1)
  const colour = positive ? '#f2545b' : '#3ecf8e'

  const thresholdAngle = -135 + 270 * Math.min(Math.max(threshold, 0), 1)
  const tickX = size / 2 + (r - stroke / 2 - 7) * Math.cos((thresholdAngle * Math.PI) / 180)
  const tickY = size / 2 + (r - stroke / 2 - 7) * Math.sin((thresholdAngle * Math.PI) / 180)
  const tickOuterX =
    size / 2 + (r + stroke / 2 + 3) * Math.cos((thresholdAngle * Math.PI) / 180)
  const tickOuterY =
    size / 2 + (r + stroke / 2 + 3) * Math.sin((thresholdAngle * Math.PI) / 180)

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-[135deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#2c3a52"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${track} ${circumference}`}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={colour}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          style={{ transition: 'stroke-dasharray .9s cubic-bezier(.16,1,.3,1)' }}
        />
        <line
          x1={tickX}
          y1={tickY}
          x2={tickOuterX}
          y2={tickOuterY}
          stroke="#94a3b8"
          strokeWidth={2}
          strokeLinecap="round"
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center pt-1">
        <span className="font-mono text-2xl font-bold tabular-nums tracking-tight text-ink">
          {(value * 100).toFixed(1)}
        </span>
        <span className="text-2xs text-ink-faint">% 阳性概率</span>
        <span className="mt-1 text-[0.625rem] text-ink-ghost">
          阈值 {threshold.toFixed(3)}
        </span>
      </div>
    </div>
  )
}

/**
 * Immutable metrics strip — shows the honest out-of-fold numbers so the
 * verdict is always read in the context of model performance.
 */
export function MetricsStrip({ result }: { result: PredictResult }) {
  const m = result.metrics
  const items = [
    { label: 'ROC-AUC', value: m.roc_auc.toFixed(4), good: m.roc_auc >= 0.9 },
    { label: '准确率', value: pct(m.accuracy, 1) },
    { label: '灵敏度', value: pct(m.recall, 1) },
    { label: '特异度', value: pct(m.specificity, 1) },
    { label: 'F1', value: m.f1.toFixed(4) },
    { label: 'Brier', value: m.brier.toFixed(4), good: m.brier <= 0.15 },
  ]

  return (
    <div className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line/60 sm:grid-cols-6">
      {items.map(({ label, value, good }) => (
        <div key={label} className="bg-canvas-soft/90 px-3 py-3 text-center">
          <p className="text-[0.625rem] font-semibold uppercase tracking-wider text-ink-ghost">
            {label}
          </p>
          <p
            className={cx(
              'mt-1 font-mono text-sm font-semibold tabular-nums',
              good === undefined
                ? 'text-ink-muted'
                : good
                  ? 'text-risk-low'
                  : 'text-risk-warn',
            )}
          >
            {value}
          </p>
        </div>
      ))}
    </div>
  )
}

/** Note shown when inputs fall outside the training distribution. */
export function RangeWarnings({ warnings }: { warnings?: string[] }) {
  if (!warnings?.length) return null
  return (
    <div className="animate-fade-up rounded-xl border border-risk-warn/35 bg-risk-warnSoft/40 px-4 py-3">
      <p className="flex items-center gap-2 text-xs font-semibold text-risk-warn">
        <ShieldQuestion className="h-4 w-4 shrink-0" />
        输入超出训练分布，结论可靠性下降
      </p>
      <ul className="mt-2 space-y-1">
        {warnings.map((w) => (
          <li key={w} className="text-2xs leading-relaxed text-risk-warn/85">
            · {w}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Re-exported so pages can badge a verdict in lists without the hero. */
export function VerdictBadge({
  verdict,
  label,
}: {
  verdict: string
  label?: string
}) {
  const positive = verdict === 'positive'
  return (
    <span className={clsx(positive ? 'chip-risk' : 'chip-safe')}>
      {positive ? '阳性' : '阴性'}
      {label ? ` · ${label}` : ''}
    </span>
  )
}
