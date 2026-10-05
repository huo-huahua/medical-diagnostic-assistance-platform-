import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Cpu,
  Database,
  Gauge,
  HeartPulse,
  Microscope,
  MessageSquareText,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  Cell,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

import { metaApi, recordApi } from '@/api'
import { useAuth, useWorkspace } from '@/lib/store'
import { ALGO_LABEL, formatRelative, pct } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader, StatCard } from '@/components/ui'
import type { DiseaseInfo, Stats } from '@/types'

export default function DashboardPage() {
  const { user } = useAuth()
  const { diseases, loadDiseases } = useWorkspace()

  const health = useQuery({
    queryKey: ['health'],
    queryFn: metaApi.health,
    refetchInterval: 30_000,
  })

  const stats = useQuery({
    queryKey: ['stats'],
    queryFn: recordApi.stats,
    refetchInterval: 20_000,
  })

  const recent = useQuery({
    queryKey: ['records', 'recent'],
    queryFn: () => recordApi.list({ page: 1, page_size: 6 }),
  })

  useMemo(() => {
    loadDiseases().catch(() => {})
  }, [loadDiseases])

  const s: Stats | undefined = stats.data
  const totalModels = diseases.reduce((n, d) => n + d.models.length, 0)

  return (
    <div className="space-y-6">
      {/* ------------------------------ header ------------------------------ */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
            Dashboard
          </p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            你好，{user?.display_name ?? '访客'}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            这里是平台整体状态与你个人的使用概览。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/diagnosis" className="btn-primary">
            <Microscope className="h-4 w-4" />
            开始一次评估
          </Link>
          <Link to="/assistant" className="btn-ghost">
            <MessageSquareText className="h-4 w-4" />
            医学问答
          </Link>
        </div>
      </header>

      {/* ------------------------------ stats ------------------------------ */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="累计评估"
          value={s?.total_predictions ?? 0}
          unit="次"
          icon={Activity}
          tone="brand"
          hint={
            s?.last_prediction_at
              ? `最近一次 ${formatRelative(s.last_prediction_at)}`
              : '还没有预测记录'
          }
        />
        <StatCard
          label="阳性占比"
          value={pct(s?.positive_rate ?? 0, 1)}
          icon={TrendingUp}
          tone="risk"
          hint={`阳性 ${s?.positives ?? 0} · 阴性 ${s?.negatives ?? 0}`}
        />
        <StatCard
          label="在线模型"
          value={totalModels}
          unit="个"
          icon={Cpu}
          hint={`${diseases.length} 个病种模块 · 均已概率校准`}
        />
        <StatCard
          label="LLM 调用"
          value={s?.llm_calls ?? 0}
          unit="次"
          icon={Zap}
          tone={(s?.llm_calls ?? 0) === 0 ? 'safe' : 'warn'}
          hint={`缓存命中 ${s?.llm_cache_hits ?? 0} 次 · 命中率 ${pct(s?.cache_hit_rate ?? 0, 0)}`}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
        {/* --------------------------- disease cards --------------------------- */}
        <div className="space-y-6">
          <Panel>
            <PanelHeader
              title="病种模块"
              icon={Cpu}
              subtitle="每个病种独立训练三套算法，自动选出验证集表现最优者作为默认模型"
            />
            {diseases.length === 0 ? (
              <LoadingBlock rows={3} />
            ) : (
              <div className="grid gap-4 p-5 sm:grid-cols-2">
                {diseases.map((d) => (
                  <DiseaseCard key={d.disease} info={d} />
                ))}
              </div>
            )}
          </Panel>

          {/* ----------------------------- recent ----------------------------- */}
          <Panel>
            <PanelHeader
              title="最近评估"
              icon={Activity}
              subtitle="仅显示你自己的记录"
              actions={
                <Link
                  to="/records"
                  className="inline-flex items-center gap-1 text-2xs font-semibold text-brand-300 transition-colors hover:text-brand-200"
                >
                  全部记录
                  <ArrowRight className="h-3 w-3" />
                </Link>
              }
            />
            {recent.isLoading ? (
              <LoadingBlock rows={4} />
            ) : !recent.data?.items.length ? (
              <EmptyState
                icon={Microscope}
                title="还没有评估记录"
                description="前往「智能诊断」输入一组指标，结果会自动保存在这里。"
                action={
                  <Link to="/diagnosis" className="btn-primary">
                    开始第一次评估
                  </Link>
                }
              />
            ) : (
              <ul className="divide-y divide-line/60">
                {recent.data.items.map((r) => (
                  <li key={r.id}>
                    <Link
                      to="/records"
                      className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-canvas-hover/50"
                    >
                      <div
                        className={
                          r.verdict === 'positive'
                            ? 'grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-risk-high/35 bg-risk-highSoft/50'
                            : 'grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-risk-low/35 bg-risk-lowSoft/50'
                        }
                      >
                        {r.disease === 'heart' ? (
                          <HeartPulse
                            className={
                              r.verdict === 'positive'
                                ? 'h-4 w-4 text-risk-high'
                                : 'h-4 w-4 text-risk-low'
                            }
                          />
                        ) : (
                          <Microscope
                            className={
                              r.verdict === 'positive'
                                ? 'h-4 w-4 text-risk-high'
                                : 'h-4 w-4 text-risk-low'
                            }
                          />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">
                          {r.case_label ||
                            (r.disease === 'breast' ? '乳腺癌样本' : '心脏病样本')}
                        </p>
                        <p className="mt-0.5 truncate font-mono text-2xs text-ink-ghost">
                          {r.model_id} · {r.elapsed_ms} ms
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p
                          className={
                            r.verdict === 'positive'
                              ? 'font-mono text-sm font-semibold text-risk-high'
                              : 'font-mono text-sm font-semibold text-risk-low'
                          }
                        >
                          {pct(r.positive_prob, 1)}
                        </p>
                        <p className="text-2xs text-ink-ghost">
                          {formatRelative(r.created_at)}
                        </p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        {/* --------------------------- right column --------------------------- */}
        <div className="space-y-6">
          {/* cache efficiency */}
          <Panel>
            <PanelHeader
              title="成本控制"
              icon={Gauge}
              subtitle="三层缓存让重复问题不产生任何 API 费用"
            />
            <div className="p-5">
              {health.isLoading ? (
                <LoadingBlock rows={2} />
              ) : health.data?.llm?.cache ? (
                <>
                  <div className="relative mx-auto h-40 w-full max-w-[220px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <RadialBarChart
                        innerRadius="68%"
                        outerRadius="100%"
                        data={[
                          {
                            name: 'hit',
                            value: Math.round(
                              (health.data.llm.cache.hit_rate || 0) * 100,
                            ),
                            fill: '#22c1d0',
                          },
                        ]}
                        startAngle={90}
                        endAngle={-270}
                      >
                        <PolarAngleAxis
                          type="number"
                          domain={[0, 100]}
                          tick={false}
                        />
                        <RadialBar
                          dataKey="value"
                          cornerRadius={8}
                          background={{ fill: '#1a2233' }}
                        />
                      </RadialBarChart>
                    </ResponsiveContainer>
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                      <span className="font-mono text-2xl font-bold text-brand-300">
                        {pct(health.data.llm.cache.hit_rate ?? 0, 0)}
                      </span>
                      <span className="text-2xs text-ink-faint">缓存命中率</span>
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-3 gap-3 text-center">
                    {[
                      { k: '精确命中', v: health.data.llm.cache.hits_exact },
                      { k: '语义命中', v: health.data.llm.cache.hits_semantic },
                      { k: '未命中', v: health.data.llm.cache.misses },
                    ].map(({ k, v }) => (
                      <div key={k}>
                        <p className="font-mono text-base font-semibold text-ink">
                          {v}
                        </p>
                        <p className="text-2xs text-ink-ghost">{k}</p>
                      </div>
                    ))}
                  </div>

                  <div className="mt-5 flex items-start gap-2.5 rounded-xl border border-line bg-canvas/60 px-3.5 py-3">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-400" />
                    <div className="min-w-0 text-2xs leading-relaxed text-ink-muted">
                      <p className="font-semibold text-ink">外部模型调用状态</p>
                      <p className="mt-0.5">
                        {health.data.llm.configured
                          ? `已配置 · ${health.data.llm.model}`
                          : '未配置密钥 —— 全流程使用本地模型与模板，零外部调用'}
                      </p>
                      <p className="mt-1 text-ink-ghost">
                        本进程累计外部调用{' '}
                        <span className="font-mono text-ink-muted">
                          {health.data.llm.api_calls_this_process}
                        </span>{' '}
                        次
                      </p>
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-xs text-ink-faint">无法读取服务状态</p>
              )}
            </div>
          </Panel>

          {/* knowledge base */}
          <Panel>
            <PanelHeader
              title="知识库"
              icon={Database}
              subtitle="本地向量检索，问答默认不联网"
            />
            <div className="space-y-3 p-5">
              {health.isLoading ? (
                <LoadingBlock rows={2} />
              ) : (
                <>
                  <div className="flex items-center justify-between rounded-xl border border-line bg-canvas/60 px-4 py-3">
                    <span className="text-xs text-ink-muted">索引片段</span>
                    <span className="font-mono text-sm font-semibold text-ink">
                      {health.data?.rag_chunks ?? 0}
                      <span className="ml-1 text-2xs font-normal text-ink-ghost">
                        chunks
                      </span>
                    </span>
                  </div>
                  <div className="flex items-center justify-between rounded-xl border border-line bg-canvas/60 px-4 py-3">
                    <span className="text-xs text-ink-muted">检索就绪</span>
                    <span
                      className={
                        health.data?.rag_ready ? 'chip-safe' : 'chip-warn'
                      }
                    >
                      <CheckCircle2 className="h-3 w-3" />
                      {health.data?.rag_ready ? '已就绪' : '构建中'}
                    </span>
                  </div>
                  <Link to="/assistant" className="btn-ghost w-full">
                    <MessageSquareText className="h-4 w-4" />
                    打开医学问答
                  </Link>
                </>
              )}
            </div>
          </Panel>
        </div>
      </div>

      {/* ------------------------- model performance ------------------------- */}
      <Panel>
        <PanelHeader
          title="模型性能总览"
          icon={BarChart3}
          subtitle="留出测试集指标（训练时划分，训练过程从未见过该部分数据）"
        />
        <div className="p-5">
          {diseases.length === 0 ? (
            <LoadingBlock rows={3} />
          ) : (
            <div className="h-[260px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  accessibilityLayer
                  data={buildPerformance(diseases)}
                  margin={{ top: 8, right: 8, left: -18, bottom: 0 }}
                  barGap={4}
                >
                  <defs>
                    <linearGradient id="aucGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#22c1d0" stopOpacity={0.95} />
                      <stop offset="100%" stopColor="#0b8494" stopOpacity={0.75} />
                    </linearGradient>
                  </defs>
                  <BarChartTooltip />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={54}>
                    {buildPerformance(diseases).map((d, i) => (
                      <Cell
                        key={i}
                        fill={d.champion ? 'url(#aucGrad)' : '#2c3a52'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {diseases.map((d) => {
              const champ = d.models.find((m) => m.id === d.champion_id)
              return (
                <div
                  key={d.disease}
                  className="flex items-start gap-3 rounded-xl border border-line bg-canvas/50 px-4 py-3"
                >
                  <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-brand-500/25 bg-brand-500/10">
                    {d.disease === 'heart' ? (
                      <HeartPulse className="h-4 w-4 text-brand-300" />
                    ) : (
                      <Microscope className="h-4 w-4 text-brand-300" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-ink">
                      {d.display_zh} · 默认 {ALGO_LABEL[d.champion] ?? d.champion}
                    </p>
                    <p className="mt-0.5 text-2xs leading-relaxed text-ink-faint">
                      ROC-AUC{' '}
                      <span className="font-mono text-ink-muted">
                        {champ?.test.roc_auc.toFixed(4) ?? '—'}
                      </span>{' '}
                      · 交叉验证{' '}
                      <span className="font-mono text-ink-muted">
                        {champ ? (champ.cv.roc_auc_mean ?? 0).toFixed(4) : '—'}
                      </span>{' '}
                      ±{' '}
                      <span className="font-mono text-ink-muted">
                        {champ ? (champ.cv.roc_auc_std ?? 0).toFixed(4) : '—'}
                      </span>
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </Panel>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function buildPerformance(diseases: DiseaseInfo[]) {
  const rows: Array<{
    name: string
    value: number
    label: string
    champion: boolean
  }> = []
  diseases.forEach((d) => {
    d.models.forEach((m) => {
      rows.push({
        name: `${d.disease === 'breast' ? '乳腺' : '心脏'}·${
          ALGO_LABEL[m.algorithm] ?? m.algorithm
        }`,
        value: Number((m.test.roc_auc * 100).toFixed(2)),
        label: m.test.roc_auc.toFixed(4),
        champion: m.id === d.champion_id,
      })
    })
  })
  return rows
}

function BarChartTooltip() {
  return (
    <Tooltip
      cursor={{ fill: 'rgba(148,163,184,.07)' }}
      content={({ active, payload }) => {
        if (!active || !payload?.length) return null
        const p = payload[0].payload as {
          name: string
          label: string
          champion: boolean
        }
        return (
          <div className="rounded-xl border border-line-strong bg-canvas-raised/95 px-3 py-2 shadow-lift backdrop-blur">
            <p className="text-2xs font-semibold text-ink">
              {p.name}
              {p.champion && (
                <span className="ml-1.5 text-brand-300">· 默认</span>
              )}
            </p>
            <p className="mt-0.5 font-mono text-2xs text-ink-muted">
              ROC-AUC {p.label}
            </p>
          </div>
        )
      }}
    />
  )
}

function DiseaseCard({ info }: { info: DiseaseInfo }) {
  const champ = info.models.find((m) => m.id === info.champion_id)
  const total = info.n_samples
  const pos = info.class_balance['1'] ?? 0
  const neg = info.class_balance['0'] ?? 0
  const posPct = total ? (pos / total) * 100 : 0

  return (
    <div className="group relative overflow-hidden rounded-2xl border border-line bg-canvas-raised/50 p-4 transition-colors duration-200 hover:border-line-strong">
      <div className="absolute inset-0 bg-brand-sheen opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
      <div className="relative">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="grid h-9 w-9 place-items-center rounded-xl border border-brand-500/25 bg-brand-500/10">
              {info.disease === 'heart' ? (
                <HeartPulse className="h-4 w-4 text-brand-300" />
              ) : (
                <Microscope className="h-4 w-4 text-brand-300" />
              )}
            </div>
            <div>
              <p className="text-sm font-bold text-ink">{info.display_zh}</p>
              <p className="text-2xs text-ink-ghost">
                {info.n_features} 维特征 · {info.n_samples} 样本
              </p>
            </div>
          </div>
          <span className="chip-brand shrink-0">
            {ALGO_LABEL[info.champion] ?? info.champion}
          </span>
        </div>

        {/* class balance bar */}
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between text-2xs">
            <span className="text-risk-low">
              {info.negative_label_zh} {neg}
            </span>
            <span className="text-risk-high">
              {info.positive_label_zh} {pos}
            </span>
          </div>
          <div className="flex h-1.5 overflow-hidden rounded-full bg-canvas">
            <span
              className="h-full bg-risk-low/70"
              style={{ width: `${100 - posPct}%` }}
            />
            <span className="h-full bg-risk-high/70" style={{ width: `${posPct}%` }} />
          </div>
        </div>

        <div className="mt-4 grid grid-cols-3 gap-2 border-t border-line/60 pt-3.5">
          {[
            { k: 'AUC', v: champ?.test.roc_auc.toFixed(3) ?? '—' },
            { k: '灵敏度', v: champ ? pct(champ.test.recall, 0) : '—' },
            { k: '特异度', v: champ ? pct(champ.test.specificity, 0) : '—' },
          ].map(({ k, v }) => (
            <div key={k}>
              <p className="text-[0.625rem] uppercase tracking-wider text-ink-ghost">
                {k}
              </p>
              <p className="mt-0.5 font-mono text-xs font-semibold text-ink">
                {v}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
