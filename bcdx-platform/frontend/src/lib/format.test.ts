import { describe, expect, it } from 'vitest'

import {
  ALGO_LABEL,
  CONFIDENCE_META,
  featurePrecision,
  formatDateTime,
  formatRelative,
  num,
  pct,
  signed,
} from '@/lib/format'

import type { ConfidenceBand } from '@/types'

describe('pct', () => {
  it('renders a probability as a percentage with one decimal by default', () => {
    expect(pct(0.1701)).toBe('17.0%')
  })

  it('takes a precision override — AUCs are reported to two', () => {
    expect(pct(0.9959, 2)).toBe('99.59%')
  })

  it('does not turn a threshold of 0.1701 into a rounded 17% with no decimals', () => {
    // The champion threshold is 0.1701; showing "17%" would read like a
    // coincidence of the metric rather than a chosen operating point.
    expect(pct(0.1701, 2)).toBe('17.01%')
  })
})

describe('num / signed', () => {
  it('formats to four decimals', () => {
    expect(num(0.123456789)).toBe('0.1235')
  })

  it('always shows the sign of a contribution', () => {
    expect(signed(0.5)).toBe('+0.5000')
    expect(signed(-0.5)).toBe('-0.5000')
  })

  it('treats exactly zero as positive, so a column of contributions stays aligned', () => {
    expect(signed(0)).toBe('+0.0000')
  })
})

describe('formatDateTime', () => {
  it('returns a placeholder rather than "Invalid Date" for empty input', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
    expect(formatDateTime('')).toBe('—')
  })

  it('returns the placeholder for an unparseable string', () => {
    expect(formatDateTime('not-a-date')).toBe('—')
  })

  it('renders a real timestamp with a four-digit year', () => {
    expect(formatDateTime('2026-10-05T12:00:00Z')).toMatch(/\d{4}/)
  })
})

describe('formatRelative', () => {
  const ago = (ms: number) => new Date(Date.now() - ms).toISOString()

  it('returns a placeholder for empty or broken input', () => {
    expect(formatRelative(null)).toBe('—')
    expect(formatRelative('nonsense')).toBe('—')
  })

  it('says "刚刚" for anything under a minute', () => {
    expect(formatRelative(ago(30_000))).toBe('刚刚')
  })

  it('counts minutes, hours and days', () => {
    expect(formatRelative(ago(5 * 60_000))).toBe('5 分钟前')
    expect(formatRelative(ago(2 * 3_600_000))).toBe('2 小时前')
    expect(formatRelative(ago(3 * 86_400_000))).toBe('3 天前')
  })

  it('switches to an absolute date past 30 days instead of "200 天前"', () => {
    expect(formatRelative(ago(60 * 86_400_000))).not.toMatch(/天前/)
  })
})

describe('featurePrecision', () => {
  it('uses fewer decimals the larger the feature range is', () => {
    expect(featurePrecision({ min: 0, max: 5000 })).toBe(2)
    expect(featurePrecision({ min: 0, max: 200 })).toBe(2)
    expect(featurePrecision({ min: 0, max: 30 })).toBe(3)
    expect(featurePrecision({ min: 0, max: 0.5 })).toBe(5)
  })

  it('compares the span, not the maximum — a tight range near a big value stays precise', () => {
    expect(featurePrecision({ min: 1000, max: 1000.4 })).toBe(5)
  })
})

describe('presentation tables', () => {
  it('gives every confidence band a label, so colour is never the only signal', () => {
    const bands: ConfidenceBand[] = ['very_high', 'high', 'moderate', 'low']
    for (const band of bands) {
      expect(CONFIDENCE_META[band]?.label).toBeTruthy()
      expect(CONFIDENCE_META[band]?.hint).toBeTruthy()
    }
  })

  it('translates the algorithm keys the registry actually emits', () => {
    expect(ALGO_LABEL.lr).toBe('逻辑回归')
    expect(ALGO_LABEL.rf).toBe('随机森林')
    expect(ALGO_LABEL.xgb).toBe('XGBoost')
  })
})
