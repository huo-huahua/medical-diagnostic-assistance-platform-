import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  HeartPulse,
  Microscope,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from 'recharts'

import { ApiError, recordApi } from '@/api'
import { CONFIDENCE_META, formatDateTime, formatRelative, pct } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader, StatCard } from '@/components/ui'
import { ContributionChart } from '@/components/ContributionChart'
import { VerdictBadge } from '@/components/domain'
import { useToast } from '@/components/Toast'
import { useWorkspace } from '@/lib/store'
import type { ConfidenceBand, RecordItem } from '@/types'

const PAGE_SIZE = 15

export default function RecordsPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const { diseases } = useWorkspace()

  const [page, setPage] = useState(1)
  const [disease, setDisease] = useState<string>('')
  const [verdict, setVerdict] = useState<string>('')
  const [openId, setOpenId] = useState<number | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)

  const list = useQuery({
    queryKey: ['records', { page, disease, verdict }],
    queryFn: () =>
      recordApi.list({
        page,
        page_size: PAGE_SIZE,
        disease: disease || undefined,
        verdict: verdict || undefined,
      }),
  })

  const stats = useQuery({ queryKey: ['stats'], queryFn: recordApi.stats })

  const detail = useQuery({
    queryKey: ['record', openId],
    queryFn: () => recordApi.detail(openId!),
    enabled: openId !== null,
  })

  const remove = useMutation({
    mutationFn: (id: number) => recordApi.remove(id),
    onSuccess: () => {
      toast.success('已删除记录')
      setConfirming(null)
      if (openId === confirming) setOpenId(null)
      qc.invalidateQueries({ queryKey: ['records'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) =>
      toast.error('删除失败', err instanceof ApiError ? err.message : '请稍后重试'),
  })

  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1
  const items = list.data?.items ?? []

  const resetFilters = () => {
    setDisease('')
    setVerdict('')
    setPage(1)
  }

  const hasFilter = Boolean(disease || verdict)

  const exportCsv = () => {
    if (!items.length) return
    const header = [
      'id',
      'disease',
      'case_label',
      'model_id',
      'verdict',
      'positive_prob',
      'negative_prob',
      'threshold',
      'confidence',
      'elapsed_ms',
      'created_at',
    ]
    const rows = items.map((r) =>
      [
        r.id,
        r.disease,
        `"${(r.case_label ?? '').replace(/"/g, '""')}"`,
        r.model_id,
        r.verdict,
        r.positive_prob,
        r.negative_prob,
        r.threshold,
        r.confidence_band,
        r.elapsed_ms,
        r.created_at,
      ].join(','),
    )
    const csv = [header.join(','), ...rows].join('\n')
    const blob = new Blob([`\uFEFF${csv}`], {
      type: 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `bcdx-records-page${page}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('已导出当前页', `${items.length} 条记录`)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
            History
          </p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            历史记录
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-muted">
            你提交过的每一次评估都会保存在这里，包含完整输入、判定结果与特征归因。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={exportCsv}
            disabled={!items.length}
            className="btn-ghost"
          >
            <Download className="h-4 w-4" />
            导出当前页
          </button>
          <button
            type="button"
            onClick={() => {
              qc.invalidateQueries({ queryKey: ['records'] })
              qc.invalidateQueries({ queryKey: ['stats'] })
            }}
            className="btn-ghost"
          >
            <RefreshCw className={clsx('h-4 w-4', list.isFetching && 'animate-spin')} />
            刷新
          </button>
        </div>
      </header>

      {/* stats */}
      {stats.data && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="累计评估"
            value={stats.data.total_predictions}
            unit="次"
            icon={Activity}
            tone="brand"
          />
          <StatCard
            label="阳性"
            value={stats.data.positives}
            unit="例"
            tone="risk"
            hint={`占比 ${pct(stats.data.positive_rate, 1)}`}
          />
          <StatCard
            label="阴性"
            value={stats.data.negatives}
            unit="例"
            tone="safe"
          />
          <StatCard
            label="最近评估"
            value={
              stats.data.last_prediction_at
                ? formatRelative(stats.data.last_prediction_at)
                : '—'
            }
            hint={
              stats.data.positive_rate > 0
                ? '阳性率仅反映你的输入样本构成'
                : undefined
            }
          />
        </div>
      )}

      {/* distribution chart */}
      {stats.data && stats.data.total_predictions > 0 && (
        <Panel>
          <PanelHeader
            title="病种分布"
            icon={Activity}
            subtitle="你的评估在不同病种模块间的分布"
          />
          <div className="p-5">
            <div className="h-[120px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  accessibilityLayer
                  data={[
                    {
                      name: '乳腺癌',
                      value: stats.data.by_disease.breast ?? 0,
                      fill: '#22c1d0',
                    },
                    {
                      name: '心脏病',
                      value: stats.data.by_disease.heart ?? 0,
                      fill: '#8ae9ee',
                    },
                  ]}
                  layout="vertical"
                  margin={{ top: 0, right: 24, left: 0, bottom: 0 }}
                >
                  <XAxis type="number" hide />
                  <Tooltip
                    cursor={{ fill: 'rgba(148,163,184,.06)' }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <div className="rounded-lg border border-line-strong bg-canvas-raised/95 px-3 py-1.5 shadow-lift">
                          <span className="text-2xs text-ink-muted">
                            {payload[0].payload.name} ·{' '}
                            <span className="font-mono text-ink">
                              {payload[0].value}
                            </span>{' '}
                            次
                          </span>
                        </div>
                      ) : null
                    }
                  />
                  <Bar dataKey="value" radius={[0, 6, 6, 0]} maxBarSize={28}>
                    {[
                      { fill: '#22c1d0' },
                      { fill: '#8ae9ee' },
                    ].map((c, i) => (
                      <Cell key={i} fill={c.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-1 flex justify-center gap-6 text-2xs">
              <span className="inline-flex items-center gap-1.5 text-ink-faint">
                <span className="h-2 w-2 rounded-full bg-brand-400" />
                乳腺癌 {stats.data.by_disease.breast ?? 0}
              </span>
              <span className="inline-flex items-center gap-1.5 text-ink-faint">
                <span className="h-2 w-2 rounded-full bg-brand-200" />
                心脏病 {stats.data.by_disease.heart ?? 0}
              </span>
            </div>
          </div>
        </Panel>
      )}

      {/* table */}
      <Panel>
        <PanelHeader
          title="记录列表"
          icon={Filter}
          subtitle={
            list.data ? `共 ${list.data.total} 条 · 第 ${page}/${totalPages} 页` : undefined
          }
          actions={
            hasFilter && (
              <button
                type="button"
                onClick={resetFilters}
                className="btn-subtle px-3 py-1.5 text-2xs"
              >
                <X className="h-3 w-3" />
                清除筛选
              </button>
            )
          }
        />

        {/* filters */}
        <div className="flex flex-wrap items-center gap-3 border-b border-line/60 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="text-2xs font-semibold uppercase tracking-wider text-ink-ghost">
              病种
            </span>
            {[
              { v: '', label: '全部' },
              { v: 'breast', label: '乳腺癌' },
              { v: 'heart', label: '心脏病' },
            ].map(({ v, label }) => (
              <button
                key={v}
                type="button"
                onClick={() => {
                  setDisease(v)
                  setPage(1)
                }}
                className={clsx(
                  'rounded-lg px-2.5 py-1 text-2xs font-semibold transition-colors',
                  disease === v
                    ? 'bg-brand-500/15 text-brand-200'
                    : 'text-ink-ghost hover:text-ink-muted',
                )}
              >
                {label}
              </button>
            ))}
          </div>

          <span className="h-4 w-px bg-line-strong" />

          <div className="flex items-center gap-2">
            <span className="text-2xs font-semibold uppercase tracking-wider text-ink-ghost">
              判定
            </span>
            {[
              { v: '', label: '全部' },
              { v: 'positive', label: '阳性' },
              { v: 'negative', label: '阴性' },
            ].map(({ v, label }) => (
              <button
                key={v}
                type="button"
                onClick={() => {
                  setVerdict(v)
                  setPage(1)
                }}
                className={clsx(
                  'rounded-lg px-2.5 py-1 text-2xs font-semibold transition-colors',
                  verdict === v
                    ? 'bg-brand-500/15 text-brand-200'
                    : 'text-ink-ghost hover:text-ink-muted',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {list.isLoading ? (
          <LoadingBlock rows={6} />
        ) : list.isError ? (
          <EmptyState
            icon={Activity}
            title="加载失败"
            description={list.error instanceof ApiError ? list.error.message : undefined}
            action={
              <button
                type="button"
                onClick={() => list.refetch()}
                className="btn-primary"
              >
                <RefreshCw className="h-4 w-4" />
                重试
              </button>
            }
          />
        ) : !items.length ? (
          <EmptyState
            icon={Activity}
            title={hasFilter ? '没有符合筛选条件的记录' : '还没有评估记录'}
            description={
              hasFilter
                ? '尝试调整或清除筛选条件。'
                : '前往「智能诊断」输入一组指标后，结果会自动出现在这里。'
            }
            action={
              hasFilter ? (
                <button type="button" onClick={resetFilters} className="btn-ghost">
                  清除筛选
                </button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-xs">
                <thead>
                  <tr className="border-b border-line/70 text-2xs uppercase tracking-wider text-ink-ghost">
                    <th className="px-5 py-3 text-left font-semibold">样本</th>
                    <th className="px-4 py-3 text-left font-semibold">判定</th>
                    <th className="px-4 py-3 text-right font-semibold">阳性概率</th>
                    <th className="px-4 py-3 text-center font-semibold">置信度</th>
                    <th className="px-4 py-3 text-left font-semibold">模型</th>
                    <th className="px-4 py-3 text-right font-semibold">时间</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((r) => (
                    <RecordRow
                      key={r.id}
                      record={r}
                      confirming={confirming === r.id}
                      onOpen={() => setOpenId(r.id)}
                      onAskDelete={() => setConfirming(r.id)}
                      onCancelDelete={() => setConfirming(null)}
                      onConfirmDelete={() => remove.mutate(r.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {/* pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-line/60 px-5 py-3.5">
                <p className="text-2xs text-ink-ghost">
                  第 {(page - 1) * PAGE_SIZE + 1}–
                  {Math.min(page * PAGE_SIZE, list.data?.total ?? 0)} 条，共{' '}
                  {list.data?.total} 条
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="btn-ghost px-3 py-1.5 text-2xs"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                    上一页
                  </button>
                  <span className="font-mono text-2xs text-ink-muted">
                    {page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="btn-ghost px-3 py-1.5 text-2xs"
                  >
                    下一页
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </Panel>

      {/* detail drawer */}
      {openId !== null && (
        <DetailDrawer
          loading={detail.isLoading}
          error={detail.error instanceof ApiError ? detail.error.message : undefined}
          data={detail.data}
          moduleFeatures={
            diseases.find((d) => d.disease === detail.data?.disease)?.feature_schema
          }
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function RecordRow({
  record,
  confirming,
  onOpen,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  record: RecordItem
  confirming: boolean
  onOpen: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}) {
  const conf = CONFIDENCE_META[record.confidence_band as ConfidenceBand]

  return (
    <tr className="group border-b border-line/40 last:border-0 hover:bg-canvas-hover/40">
      <td className="px-5 py-3">
        <button
          type="button"
          onClick={onOpen}
          className="flex items-center gap-2.5 text-left"
        >
          <span
            className={clsx(
              'grid h-7 w-7 shrink-0 place-items-center rounded-lg border',
              record.disease === 'heart'
                ? 'border-brand-500/25 bg-brand-500/8'
                : 'border-brand-500/25 bg-brand-500/8',
            )}
          >
            {record.disease === 'heart' ? (
              <HeartPulse className="h-3.5 w-3.5 text-brand-300" />
            ) : (
              <Microscope className="h-3.5 w-3.5 text-brand-300" />
            )}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium text-ink group-hover:text-brand-200">
              {record.case_label ||
                (record.disease === 'breast' ? '乳腺癌样本' : '心脏病样本')}
            </span>
            <span className="block font-mono text-[0.625rem] text-ink-ghost">
              #{record.id}
            </span>
          </span>
        </button>
      </td>
      <td className="px-4 py-3">
        <VerdictBadge verdict={record.verdict} />
      </td>
      <td className="px-4 py-3 text-right">
        <span
          className={clsx(
            'font-mono text-sm font-semibold tabular-nums',
            record.verdict === 'positive' ? 'text-risk-high' : 'text-risk-low',
          )}
        >
          {pct(record.positive_prob, 1)}
        </span>
        <span className="block font-mono text-[0.625rem] text-ink-ghost">
          阈值 {record.threshold.toFixed(3)}
        </span>
      </td>
      <td className="px-4 py-3 text-center">
        <span className={conf.cls}>{conf.label}</span>
      </td>
      <td className="px-4 py-3">
        <span className="font-mono text-[0.625rem] text-ink-faint">
          {record.model_id}
        </span>
        {record.llm_used && (
          <span className="ml-1.5 text-[0.625rem] text-risk-warn">LLM</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <span className="text-[0.625rem] text-ink-muted">
          {formatRelative(record.created_at)}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        {confirming ? (
          <span className="inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={onConfirmDelete}
              className="rounded-md bg-risk-high/20 px-2 py-1 text-[0.625rem] font-semibold text-risk-high hover:bg-risk-high/30"
            >
              确认删除
            </button>
            <button
              type="button"
              onClick={onCancelDelete}
              className="rounded-md px-2 py-1 text-[0.625rem] text-ink-ghost hover:text-ink-muted"
            >
              取消
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={onAskDelete}
            aria-label="删除记录"
            className="rounded-md p-1.5 text-ink-ghost opacity-0 transition-all hover:text-risk-high group-hover:opacity-100"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </td>
    </tr>
  )
}

function DetailDrawer({
  loading,
  error,
  data,
  moduleFeatures,
  onClose,
}: {
  loading: boolean
  error?: string
  data?: import('@/types').RecordDetail
  moduleFeatures?: import('@/types').FeatureSpec[]
  onClose: () => void
}) {
  const conf = data ? CONFIDENCE_META[data.confidence_band as ConfidenceBand] : null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />
      <aside className="scroll-area relative h-full w-full max-w-2xl animate-fade-in border-l border-line bg-canvas-soft/97 shadow-lift">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-canvas-soft/95 px-5 py-4 backdrop-blur">
          <div>
            <p className="text-2xs font-semibold uppercase tracking-wider text-ink-ghost">
              记录详情
            </p>
            <p className="mt-0.5 text-sm font-bold text-ink">
              {data?.case_label || `#${data?.id ?? ''}`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-lg p-2 text-ink-ghost transition-colors hover:bg-canvas-hover hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <LoadingBlock rows={8} />
        ) : error ? (
          <EmptyState icon={Activity} title="加载失败" description={error} />
        ) : data ? (
          <div className="space-y-6 p-5">
            {/* verdict summary */}
            <div
              className={clsx(
                'flex flex-wrap items-center justify-between gap-4 rounded-2xl border p-5',
                data.verdict === 'positive'
                  ? 'border-risk-high/40 bg-risk-highSoft/35'
                  : 'border-risk-low/40 bg-risk-lowSoft/35',
              )}
            >
              <div>
                <p className="text-2xs uppercase tracking-wider text-ink-ghost">
                  判定结果
                </p>
                <p
                  className={clsx(
                    'mt-1 text-2xl font-bold',
                    data.verdict === 'positive'
                      ? 'text-risk-high'
                      : 'text-risk-low',
                  )}
                >
                  {data.verdict === 'positive' ? '阳性' : '阴性'}
                </p>
                <p className="mt-2 font-mono text-xs text-ink-muted">
                  阳性概率 {pct(data.positive_prob, 2)} · 阴性概率{' '}
                  {pct(data.negative_prob, 2)}
                </p>
              </div>
              <div className="text-right">
                {conf && <span className={conf.cls}>{conf.label}置信</span>}
                <p className="mt-2 font-mono text-[0.625rem] text-ink-ghost">
                  {data.model_id}
                </p>
                <p className="font-mono text-[0.625rem] text-ink-ghost">
                  {formatDateTime(data.created_at)}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {[
                { k: '判定阈值', v: data.threshold.toFixed(4) },
                { k: '推理耗时', v: `${data.elapsed_ms} ms` },
                { k: 'LLM 调用', v: data.llm_used ? '是' : '否' },
              ].map(({ k, v }) => (
                <div
                  key={k}
                  className="rounded-xl border border-line bg-canvas/50 px-3 py-2.5"
                >
                  <p className="text-[0.625rem] uppercase tracking-wider text-ink-ghost">
                    {k}
                  </p>
                  <p className="mt-1 font-mono text-sm font-semibold text-ink">
                    {v}
                  </p>
                </div>
              ))}
            </div>

            {/* contributions */}
            {data.contributions && data.contributions.length > 0 ? (
              <div className="rounded-2xl border border-line bg-canvas-raised/40">
                <div className="border-b border-line/60 px-5 py-3.5">
                  <p className="text-sm font-semibold text-ink">特征归因</p>
                  <p className="mt-0.5 text-2xs text-ink-faint">
                    保存时的 SHAP 贡献值
                  </p>
                </div>
                <ContributionChart
                  contributions={data.contributions}
                  topPositive={data.contributions.filter((c) => c.contribution > 0)}
                  topNegative={data.contributions.filter((c) => c.contribution < 0)}
                  baseValue={0}
                  specs={moduleFeatures}
                />
              </div>
            ) : (
              <p className="rounded-xl border border-line bg-canvas/50 px-4 py-3 text-2xs text-ink-faint">
                该记录未保存归因数据。
              </p>
            )}

            {/* raw features */}
            <div className="rounded-2xl border border-line bg-canvas-raised/40">
              <div className="flex items-center justify-between border-b border-line/60 px-5 py-3.5">
                <div>
                  <p className="text-sm font-semibold text-ink">输入特征</p>
                  <p className="mt-0.5 text-2xs text-ink-faint">
                    原始输入值
                  </p>
                </div>
                <span className="font-mono text-2xs text-ink-ghost">
                  {Object.keys(data.features).length} 项
                </span>
              </div>
              <div className="grid gap-x-5 gap-y-0 divide-y divide-line/40 px-5 sm:grid-cols-2 sm:divide-y-0">
                {Object.entries(data.features).map(([key, value]) => {
                  const spec = moduleFeatures?.find((s) => s.key === key)
                  return (
                    <div
                      key={key}
                      className="flex items-center justify-between border-b border-line/40 py-2.5 last:border-0"
                    >
                      <span className="min-w-0 truncate text-2xs text-ink-muted">
                        {spec?.name_zh ?? key}
                        {spec?.unit && spec.unit !== '—' && (
                          <span className="ml-1 text-ink-ghost">
                            ({spec.unit})
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 font-mono text-2xs font-semibold text-ink">
                        {typeof value === 'number'
                          ? value.toFixed(4)
                          : String(value)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            <p className="pb-4 text-center text-[0.625rem] leading-relaxed text-ink-ghost">
              该记录为历史评估结果，仅供回溯参考，不构成当前医疗建议。
            </p>
          </div>
        ) : null}
      </aside>
    </div>
  )
}
