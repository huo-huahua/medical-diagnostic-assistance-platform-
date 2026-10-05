import { useMemo, useState } from 'react'
import {
  Award,
  BarChart3,
  Boxes,
  HeartPulse,
  Info,
  Microscope,
  Scale,
  Sparkles,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import clsx from 'clsx'

import { useWorkspace } from '@/lib/store'
import { ALGO_LABEL, pct } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader } from '@/components/ui'
import type { DiseaseInfo, ModelInfo } from '@/types'

/**
 * Model comparison workbench.
 *
 * All numbers come from the registry: 5-fold cross-validation (mean ± std)
 * and a held-out test split the training code never fitted on. Nothing here
 * is recomputed in the browser — the frontend only presents.
 */

const ALGO_COLORS: Record<string, string> = {
  lr: '#8ae9ee',
  rf: '#22c1d0',
  xgb: '#0b8494',
}

const METRICS = [
  { key: 'roc_auc', label: 'ROC-AUC', fmt: (v: number) => v.toFixed(4), better: 'high' },
  { key: 'accuracy', label: '准确率', fmt: (v: number) => pct(v, 1), better: 'high' },
  { key: 'precision', label: '精确率', fmt: (v: number) => pct(v, 1), better: 'high' },
  { key: 'recall', label: '灵敏度', fmt: (v: number) => pct(v, 1), better: 'high' },
  { key: 'specificity', label: '特异度', fmt: (v: number) => pct(v, 1), better: 'high' },
  { key: 'f1', label: 'F1', fmt: (v: number) => v.toFixed(4), better: 'high' },
  { key: 'brier', label: 'Brier', fmt: (v: number) => v.toFixed(4), better: 'low' },
] as const

export default function ComparePage() {
  const { diseases, loadDiseases } = useWorkspace()
  const [disease, setDisease] = useState<'breast' | 'heart'>('breast')

  useMemo(() => {
    loadDiseases().catch(() => {})
  }, [loadDiseases])

  const module: DiseaseInfo | undefined =
    diseases.find((d) => d.disease === disease) ?? diseases[0]

  if (!diseases.length) {
    return (
      <div className="space-y-6">
        <PageHeader />
        <Panel>
          <LoadingBlock rows={6} />
        </Panel>
      </div>
    )
  }

  if (!module) {
    return (
      <div className="space-y-6">
        <PageHeader />
        <Panel>
          <EmptyState icon={BarChart3} title="暂无可用模型" />
        </Panel>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader />

      {/* disease switch */}
      <div className="flex flex-wrap gap-2">
        {diseases.map((d) => (
          <button
            key={d.disease}
            type="button"
            onClick={() => setDisease(d.disease as 'breast' | 'heart')}
            className={clsx(
              'inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold transition-all duration-150',
              module.disease === d.disease
                ? 'border-brand-500/50 bg-brand-500/12 text-brand-200 shadow-glow'
                : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:border-ink-ghost hover:text-ink-muted',
            )}
          >
            {d.disease === 'heart' ? (
              <HeartPulse className="h-4 w-4" />
            ) : (
              <Microscope className="h-4 w-4" />
            )}
            {d.display_zh}
            <span className="font-mono text-2xs opacity-70">
              {d.models.length}
            </span>
          </button>
        ))}
      </div>

      {/* champion banner */}
      <ChampionBanner module={module} />

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel>
          <PanelHeader
            title="雷达图对比"
            icon={Scale}
            subtitle="六项核心指标归一化后的相对表现，越靠外越好"
          />
          <div className="p-5">
            <div className="h-[330px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData(module)} outerRadius="72%">
                  <PolarGrid stroke="#2c3a52" />
                  <PolarAngleAxis
                    dataKey="metric"
                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                  />
                  <PolarRadiusAxis
                    angle={90}
                    domain={[0, 100]}
                    tick={{ fill: '#475569', fontSize: 9 }}
                    axisLine={false}
                  />
                  {module.models.map((m) => (
                    <Radar
                      key={m.id}
                      name={ALGO_LABEL[m.algorithm] ?? m.algorithm}
                      dataKey={m.algorithm}
                      stroke={ALGO_COLORS[m.algorithm] ?? '#22c1d0'}
                      fill={ALGO_COLORS[m.algorithm] ?? '#22c1d0'}
                      fillOpacity={0.14}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
                    iconType="circle"
                    iconSize={8}
                  />
                  <Tooltip content={<RadarTooltip />} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="交叉验证稳定性"
            icon={BarChart3}
            subtitle="5 折交叉验证 ROC-AUC 均值与标准差 —— 误差线越短越稳定"
          />
          <div className="p-5">
            <div className="h-[330px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  accessibilityLayer
                  data={cvData(module)}
                  margin={{ top: 20, right: 12, left: -20, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#1f2937"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                    axisLine={{ stroke: '#2c3a52' }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0.7, 1]}
                    tick={{ fill: '#475569', fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<CvTooltip />} cursor={{ fill: 'rgba(148,163,184,.06)' }} />
                  <Bar dataKey="mean" radius={[6, 6, 0, 0]} maxBarSize={64}>
                    {cvData(module).map((d) => (
                      <Cell key={d.name} fill={ALGO_COLORS[d.algo] ?? '#22c1d0'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap justify-center gap-x-5 gap-y-1.5">
              {cvData(module).map((d) => (
                <span
                  key={d.name}
                  className="inline-flex items-center gap-1.5 text-2xs text-ink-faint"
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: ALGO_COLORS[d.algo] ?? '#22c1d0' }}
                  />
                  {d.name}
                  <span className="font-mono text-ink-muted">
                    {d.mean.toFixed(4)} ± {d.std.toFixed(4)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      {/* full metric table */}
      <Panel>
        <PanelHeader
          title="完整指标对照"
          icon={Boxes}
          subtitle="留出测试集指标；每列最优值以高亮标出"
          actions={
            <span className="chip-brand">
              <Sparkles className="h-3 w-3" />
              默认 {ALGO_LABEL[module.champion] ?? module.champion}
            </span>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead>
              <tr className="border-b border-line/70">
                <th className="px-5 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-ink-ghost">
                  指标
                </th>
                {module.models.map((m) => (
                  <th
                    key={m.id}
                    className="px-4 py-3 text-right text-2xs font-semibold uppercase tracking-wider"
                  >
                    <span
                      className={clsx(
                        'inline-flex items-center gap-1.5',
                        m.id === module.champion_id
                          ? 'text-brand-300'
                          : 'text-ink-ghost',
                      )}
                    >
                      {m.id === module.champion_id && (
                        <Award className="h-3 w-3" />
                      )}
                      {ALGO_LABEL[m.algorithm] ?? m.algorithm}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map((row) => {
                const values = module.models.map(
                  (m) => (m.test as unknown as Record<string, number>)[row.key],
                )
                const best =
                  row.better === 'high'
                    ? Math.max(...values)
                    : Math.min(...values)

                return (
                  <tr
                    key={row.key}
                    className="border-b border-line/40 last:border-0 hover:bg-canvas-hover/40"
                  >
                    <td className="px-5 py-3 text-ink-muted">{row.label}</td>
                    {module.models.map((m, i) => {
                      const v = values[i]
                      const isBest = Math.abs(v - best) < 1e-9
                      return (
                        <td
                          key={m.id}
                          className={clsx(
                            'px-4 py-3 text-right font-mono tabular-nums',
                            isBest
                              ? 'font-semibold text-brand-200'
                              : 'text-ink-muted',
                          )}
                        >
                          <span
                            className={clsx(
                              isBest &&
                                'rounded-md bg-brand-500/12 px-1.5 py-0.5',
                            )}
                          >
                            {row.fmt(v)}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}

              {/* threshold + calibration + confusion matrix summary */}
              <tr className="border-b border-line/40 bg-canvas/30">
                <td className="px-5 py-3 text-ink-muted">判定阈值</td>
                {module.models.map((m) => (
                  <td
                    key={m.id}
                    className="px-4 py-3 text-right font-mono tabular-nums text-ink-muted"
                  >
                    {m.threshold.toFixed(4)}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-line/40 bg-canvas/30">
                <td className="px-5 py-3 text-ink-muted">概率校准</td>
                {module.models.map((m) => (
                  <td key={m.id} className="px-4 py-3 text-right">
                    <span className={m.calibrated ? 'chip-safe' : 'chip-neutral'}>
                      {m.calibrated ? '已校准' : '未校准'}
                    </span>
                  </td>
                ))}
              </tr>
              <tr className="bg-canvas/30">
                <td className="px-5 py-3 text-ink-muted">混淆矩阵</td>
                {module.models.map((m) => {
                  const c = m.test.confusion_matrix
                  return (
                    <td
                      key={m.id}
                      className="px-4 py-3 text-right font-mono text-[0.625rem] leading-relaxed text-ink-ghost"
                    >
                      TN {c.tn} · FP {c.fp}
                      <br />
                      FN {c.fn} · TP {c.tp}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>

        <p className="flex items-start gap-2 border-t border-line/60 px-5 py-3.5 text-2xs leading-relaxed text-ink-ghost">
          <Info className="mt-px h-3.5 w-3.5 shrink-0" />
          <span>
            灵敏度（召回率）越高，漏诊越少；特异度越高，误报越少。医学场景通常优先保证灵敏度，
            因此默认模型并非单纯追求准确率。Brier 分数衡量概率校准质量，越低越好。
          </span>
        </p>
      </Panel>

      {/* per-model cards */}
      <div className="grid gap-4 lg:grid-cols-3">
        {module.models.map((m) => (
          <ModelCard
            key={m.id}
            model={m}
            champion={m.id === module.champion_id}
          />
        ))}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function PageHeader() {
  return (
    <header>
      <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
        Benchmark
      </p>
      <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
        模型对比
      </h1>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-muted">
        所有指标均来自留出测试集与 5 折交叉验证，测试集在训练过程中从未参与拟合，
        因此数字可直接横向比较。
      </p>
    </header>
  )
}

function ChampionBanner({ module }: { module: DiseaseInfo }) {
  const champ = module.models.find((m) => m.id === module.champion_id)
  if (!champ) return null

  return (
    <div className="relative overflow-hidden rounded-2xl border border-brand-500/35 bg-brand-500/8 p-5 shadow-glow">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-20 -top-20 h-56 w-56 rounded-full opacity-20 blur-3xl"
        style={{
          background: 'radial-gradient(circle, #22c1d0 0%, transparent 70%)',
        }}
      />
      <div className="relative flex flex-wrap items-center gap-6">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-glow">
          <Award className="h-5 w-5 text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-2xs font-semibold uppercase tracking-wider text-brand-300">
            {module.display_zh} · 默认模型
          </p>
          <p className="mt-1 text-lg font-bold text-ink">
            {ALGO_LABEL[champ.algorithm] ?? champ.algorithm}
            <span className="ml-2 font-mono text-xs font-normal text-ink-faint">
              {champ.id}
            </span>
          </p>
        </div>
        <div className="flex flex-wrap gap-x-7 gap-y-3">
          {[
            { k: '测试 AUC', v: champ.test.roc_auc.toFixed(4) },
            { k: '交叉验证', v: `${(champ.cv.roc_auc_mean ?? 0).toFixed(4)} ± ${(champ.cv.roc_auc_std ?? 0).toFixed(4)}` },
            { k: '灵敏度', v: pct(champ.test.recall, 1) },
            { k: '阈值', v: champ.threshold.toFixed(4) },
          ].map(({ k, v }) => (
            <div key={k}>
              <p className="text-[0.625rem] uppercase tracking-wider text-ink-ghost">
                {k}
              </p>
              <p className="mt-0.5 font-mono text-sm font-semibold text-brand-200">
                {v}
              </p>
            </div>
          ))}
        </div>
      </div>
      <p className="relative mt-4 border-t border-brand-500/20 pt-3 text-2xs leading-relaxed text-ink-faint">
        选择依据：交叉验证 ROC-AUC 均值最高者胜出；若并列则优先灵敏度和校准质量。
        阈值由 Youden's J 统计量在训练集上确定，用于平衡漏诊与误报。
      </p>
    </div>
  )
}

function ModelCard({ model, champion }: { model: ModelInfo; champion: boolean }) {
  const c = model.test.confusion_matrix
  const total = c.tn + c.fp + c.fn + c.tp

  return (
    <div
      className={clsx(
        'rounded-2xl border p-5 transition-colors duration-200',
        champion
          ? 'border-brand-500/40 bg-brand-500/6'
          : 'border-line bg-canvas-soft/80 hover:border-line-strong',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span
            className="h-3 w-3 shrink-0 rounded-full"
            style={{ background: ALGO_COLORS[model.algorithm] ?? '#22c1d0' }}
          />
          <div>
            <p className="text-sm font-bold text-ink">
              {ALGO_LABEL[model.algorithm] ?? model.algorithm}
            </p>
            <p className="font-mono text-[0.625rem] text-ink-ghost">
              {model.id}
            </p>
          </div>
        </div>
        {champion && (
          <span className="chip-brand shrink-0">
            <Award className="h-3 w-3" />
            默认
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        {[
          { k: '测试 AUC', v: model.test.roc_auc.toFixed(4) },
          { k: '准确率', v: pct(model.test.accuracy, 1) },
          { k: '灵敏度', v: pct(model.test.recall, 1) },
          { k: '特异度', v: pct(model.test.specificity, 1) },
        ].map(({ k, v }) => (
          <div key={k} className="rounded-lg border border-line bg-canvas/50 px-3 py-2">
            <p className="text-[0.625rem] uppercase tracking-wider text-ink-ghost">
              {k}
            </p>
            <p className="mt-0.5 font-mono text-sm font-semibold text-ink">
              {v}
            </p>
          </div>
        ))}
      </div>

      {/* mini confusion matrix */}
      <div className="mt-4">
        <p className="mb-2 text-[0.625rem] font-semibold uppercase tracking-wider text-ink-ghost">
          测试集混淆矩阵
          <span className="ml-1.5 font-normal normal-case">
            n = {total}
          </span>
        </p>
        <div className="grid grid-cols-2 gap-1.5">
          {[
            { k: 'TN', v: c.tn, tone: 'safe' as const, label: '真阴性' },
            { k: 'FP', v: c.fp, tone: 'warn' as const, label: '假阳性' },
            { k: 'FN', v: c.fn, tone: 'risk' as const, label: '假阴性' },
            { k: 'TP', v: c.tp, tone: 'brand' as const, label: '真阳性' },
          ].map(({ k, v, tone, label }) => (
            <div
              key={k}
              className={clsx(
                'rounded-lg border px-3 py-2',
                tone === 'risk'
                  ? 'border-risk-high/30 bg-risk-highSoft/40'
                  : tone === 'safe'
                    ? 'border-risk-low/30 bg-risk-lowSoft/40'
                    : tone === 'warn'
                      ? 'border-risk-warn/30 bg-risk-warnSoft/40'
                      : 'border-brand-500/30 bg-brand-500/8',
              )}
            >
              <p className="flex items-baseline justify-between">
                <span className="font-mono text-[0.625rem] text-ink-ghost">
                  {k}
                </span>
                <span
                  className={clsx(
                    'font-mono text-base font-bold tabular-nums',
                    tone === 'risk'
                      ? 'text-risk-high'
                      : tone === 'safe'
                        ? 'text-risk-low'
                        : tone === 'warn'
                          ? 'text-risk-warn'
                          : 'text-brand-300',
                  )}
                >
                  {v}
                </span>
              </p>
              <p className="text-[0.625rem] text-ink-ghost">{label}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-line/60 pt-3 text-2xs">
        <span className="text-ink-ghost">
          阈值 <span className="font-mono text-ink-muted">{model.threshold.toFixed(4)}</span>
        </span>
        <span className={model.calibrated ? 'chip-safe' : 'chip-neutral'}>
          {model.calibrated ? '已概率校准' : '未校准'}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------- chart data ------------------------------- */

function radarData(module: DiseaseInfo) {
  const metrics: Array<{ key: keyof ModelInfo['test']; label: string }> = [
    { key: 'roc_auc', label: 'AUC' },
    { key: 'accuracy', label: '准确率' },
    { key: 'precision', label: '精确率' },
    { key: 'recall', label: '灵敏度' },
    { key: 'specificity', label: '特异度' },
    { key: 'f1', label: 'F1' },
  ]

  return metrics.map(({ key, label }) => {
    const row: Record<string, string | number> = { metric: label }
    module.models.forEach((m) => {
      const raw = (m.test as unknown as Record<string, number>)[key as string]
      // Invert Brier-like metrics so "further out = better" holds for all axes.
      row[m.algorithm] = Number((raw * 100).toFixed(1))
    })
    return row
  })
}

function cvData(module: DiseaseInfo) {
  return module.models.map((m) => ({
    name: ALGO_LABEL[m.algorithm] ?? m.algorithm,
    algo: m.algorithm,
    mean: Number((m.cv.roc_auc_mean ?? 0).toFixed(4)),
    std: Number((m.cv.roc_auc_std ?? 0).toFixed(4)),
    champion: m.id === module.champion_id,
  }))
}

function RadarTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-line-strong bg-canvas-raised/95 px-3 py-2 shadow-lift backdrop-blur">
      <p className="text-2xs font-semibold text-ink">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="mt-0.5 flex items-center gap-2 font-mono text-2xs">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: p.color }} />
          <span className="text-ink-ghost">{p.name}</span>
          <span className="text-ink-muted">{p.value}%</span>
        </p>
      ))}
    </div>
  )
}

function CvTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: { name: string; mean: number; std: number } }>
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-xl border border-line-strong bg-canvas-raised/95 px-3 py-2 shadow-lift backdrop-blur">
      <p className="text-2xs font-semibold text-ink">{p.name}</p>
      <p className="mt-0.5 font-mono text-2xs text-ink-muted">
        AUC {p.mean.toFixed(4)} ± {p.std.toFixed(4)}
      </p>
    </div>
  )
}
