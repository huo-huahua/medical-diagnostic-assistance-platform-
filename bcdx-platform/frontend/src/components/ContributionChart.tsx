import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

import { cx, featurePrecision } from '@/lib/format'
import type { FeatureContribution, FeatureSpec } from '@/types'

/**
 * SHAP contribution visualisation.
 *
 * Rendered as a diverging bar chart in raw SVG rather than a charting
 * library: contributions are already signed floats, and drawing them
 * directly keeps the axis, tooltip and colour semantics fully under control.
 *
 * Reading: bars growing to the right push the sample toward「阳性」,
 * bars growing to the left push it toward「阴性」. Colour always pairs
 * with the signed number and an arrow icon, never colour alone.
 */

interface Props {
  contributions: FeatureContribution[]
  topPositive: FeatureContribution[]
  topNegative: FeatureContribution[]
  baseValue: number
  /** Feature specs, used to show units and sane decimal precision. */
  specs?: FeatureSpec[]
  /** Limit rows in compact mode. */
  limit?: number
}

const POS_COLOR = '#f2545b'
const NEG_COLOR = '#3ecf8e'

/**
 * Direction arrow. Decorative: it restates the sign that is already in the
 * adjacent `+0.1234` text, so it is hidden from assistive tech rather than
 * announced as another image next to every row.
 */
function Arrow({ dir }: { dir: string }) {
  if (dir === 'positive')
    return <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
  if (dir === 'negative')
    return <ArrowDownRight className="h-3.5 w-3.5" aria-hidden />
  return <Minus className="h-3.5 w-3.5" aria-hidden />
}

export function ContributionChart({
  contributions,
  baseValue,
  specs,
  limit,
}: Props) {
  const [hover, setHover] = useState<string | null>(null)

  const specMap = useMemo(() => {
    const m = new Map<string, FeatureSpec>()
    specs?.forEach((s) => m.set(s.key, s))
    return m
  }, [specs])

  const rows = useMemo(() => {
    const sorted = [...contributions].sort(
      (a, b) => Math.abs(b.contribution) - Math.abs(a.contribution),
    )
    return limit ? sorted.slice(0, limit) : sorted
  }, [contributions, limit])

  const maxAbs = useMemo(
    () => Math.max(...rows.map((r) => Math.abs(r.contribution)), 1e-9),
    [rows],
  )

  if (!rows.length) {
    return (
      <p className="px-5 py-8 text-center text-xs text-ink-faint">
        本次预测未生成特征归因数据。
      </p>
    )
  }

  return (
    <div
      className="px-5 pb-5 pt-4"
      role="group"
      // Every number below is real text, so the data is readable without the
      // bars. The label says what the bars add and how to read the direction,
      // because colour and position are the only things that encode it.
      aria-label="特征贡献归因图。每一行给出特征名、取值与贡献值；贡献为正表示推向阳性，为负表示推向阴性。"
    >
      {/* axis legend */}
      <div className="mb-4 flex items-center justify-between text-2xs">
        <span className="inline-flex items-center gap-1.5 font-semibold text-risk-low">
          <ArrowDownRight className="h-3.5 w-3.5" aria-hidden />
          推向「阴性」
        </span>
        <span className="font-mono text-ink-ghost">
          基准值 {baseValue.toFixed(4)}
        </span>
        <span className="inline-flex items-center gap-1.5 font-semibold text-risk-high">
          推向「阳性」
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
        </span>
      </div>

      <div className="space-y-2">
        {rows.map((row, i) => {
          const spec = specMap.get(row.key)
          const digits = spec ? featurePrecision(spec) : 3
          const ratio = Math.abs(row.contribution) / maxAbs
          const positive = row.contribution > 0
          const isHover = hover === row.key
          const unit = spec?.unit && spec.unit !== '—' ? ` ${spec.unit}` : ''

          return (
            <div
              key={row.key}
              onMouseEnter={() => setHover(row.key)}
              onMouseLeave={() => setHover(null)}
              className={cx(
                'group rounded-lg px-2 py-1.5 transition-colors duration-150',
                isHover && 'bg-canvas-hover/60',
              )}
              style={{ animation: `fade-up .4s cubic-bezier(.16,1,.3,1) ${i * 28}ms both` }}
            >
              {/* label row */}
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <div className="flex min-w-0 items-baseline gap-2">
                  <span className="truncate text-xs font-medium text-ink">
                    {row.name_zh}
                  </span>
                  <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
                    {row.value.toFixed(digits)}
                    {unit}
                  </span>
                </div>
                <span
                  className={cx(
                    'inline-flex shrink-0 items-center gap-0.5 font-mono text-2xs font-semibold tabular-nums',
                    row.direction === 'positive'
                      ? 'text-risk-high'
                      : row.direction === 'negative'
                        ? 'text-risk-low'
                        : 'text-ink-faint',
                  )}
                >
                  <Arrow dir={row.direction} />
                  {row.contribution >= 0 ? '+' : ''}
                  {row.contribution.toFixed(4)}
                </span>
              </div>

              {/* diverging bar — decorative: length and colour only restate the
                  signed number printed on the line above, so it contributes
                  nothing for a screen reader and is hidden rather than
                  announced as an unlabelled graphic. */}
              <div
                className="relative h-2 overflow-hidden rounded-full bg-canvas/80"
                aria-hidden
              >
                {/* centre line */}
                <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-line-strong" />
                <span
                  className="absolute top-0 h-full rounded-full transition-[width] duration-700 ease-snap"
                  style={{
                    width: `${Math.max(ratio * 48, 1.5)}%`,
                    left: positive ? '50%' : undefined,
                    right: positive ? undefined : '50%',
                    background: positive
                      ? `linear-gradient(90deg, ${POS_COLOR}55, ${POS_COLOR})`
                      : `linear-gradient(270deg, ${NEG_COLOR}55, ${NEG_COLOR})`,
                  }}
                />
              </div>
            </div>
          )
        })}
      </div>

      {limit && contributions.length > limit && (
        <p className="mt-3 text-center text-2xs text-ink-ghost">
          仅展示影响最大的 {limit} 个特征，共 {contributions.length} 个
        </p>
      )}
    </div>
  )
}

/** Condensed two-column summary of what pushed the verdict each way. */
export function TopDrivers({
  topPositive,
  topNegative,
  specs,
}: {
  topPositive: FeatureContribution[]
  topNegative: FeatureContribution[]
  specs?: FeatureSpec[]
}) {
  const specMap = useMemo(() => {
    const m = new Map<string, FeatureSpec>()
    specs?.forEach((s) => m.set(s.key, s))
    return m
  }, [specs])

  const render = (items: FeatureContribution[], dir: 'pos' | 'neg') => (
    <ul className="space-y-2">
      {items.slice(0, 5).map((c) => {
        const spec = specMap.get(c.key)
        const digits = spec ? featurePrecision(spec) : 3
        return (
          <li key={c.key} className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-xs text-ink-muted">
              {c.name_zh}
              <span className="ml-1.5 font-mono text-[0.625rem] text-ink-ghost">
                {c.value.toFixed(digits)}
              </span>
            </span>
            <span
              className={clsx(
                'shrink-0 font-mono text-2xs font-semibold tabular-nums',
                dir === 'pos' ? 'text-risk-high' : 'text-risk-low',
              )}
            >
              {c.contribution >= 0 ? '+' : ''}
              {c.contribution.toFixed(4)}
            </span>
          </li>
        )
      })}
      {!items.length && (
        <li className="text-2xs text-ink-ghost">无显著贡献特征</li>
      )}
    </ul>
  )

  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <div>
        <p className="mb-2.5 inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-risk-high">
          <ArrowUpRight className="h-3.5 w-3.5" />
          主要阳性驱动因素
        </p>
        {render(topPositive, 'pos')}
      </div>
      <div>
        <p className="mb-2.5 inline-flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-risk-low">
          <ArrowDownRight className="h-3.5 w-3.5" />
          主要阴性驱动因素
        </p>
        {render(topNegative, 'neg')}
      </div>
    </div>
  )
}
