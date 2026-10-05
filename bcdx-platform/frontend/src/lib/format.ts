import clsx from 'clsx'

import type { ConfidenceBand } from '@/types'

/** Formatting + presentation helpers shared across features. */

export const pct = (value: number, digits = 1): string =>
  `${(value * 100).toFixed(digits)}%`

export const num = (value: number, digits = 4): string => value.toFixed(digits)

export const signed = (value: number, digits = 4): string =>
  `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Date.now() - then
  const min = Math.floor(diff / 60_000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} 天前`
  return formatDateTime(iso)
}

/** Confidence band -> label + chip class. Always paired with text, never colour alone. */
export const CONFIDENCE_META: Record<
  ConfidenceBand,
  { label: string; cls: string; hint: string }
> = {
  very_high: {
    label: '很高',
    cls: 'chip-risk',
    hint: '概率与判定阈值差距显著，模型判断稳定',
  },
  high: {
    label: '较高',
    cls: 'chip-risk',
    hint: '概率明显偏离阈值，判断较为稳定',
  },
  moderate: {
    label: '中等',
    cls: 'chip-warn',
    hint: '概率接近参考区间，建议结合其他检查综合判断',
  },
  low: {
    label: '偏低',
    cls: 'chip-warn',
    hint: '概率紧邻判定阈值，结论不确定性较大',
  },
}

export const ALGO_LABEL: Record<string, string> = {
  lr: '逻辑回归',
  rf: '随机森林',
  xgb: 'XGBoost',
}

/** Number of decimal places appropriate for a feature's magnitude. */
export function featurePrecision(spec: { max: number; min: number }): number {
  const span = Math.abs(spec.max - spec.min)
  if (span >= 1000) return 2
  if (span >= 100) return 2
  if (span >= 1) return 3
  return 5
}

export const cx = clsx
