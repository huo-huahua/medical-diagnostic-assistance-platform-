import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import {
  Brain,
  GitCompareArrows,
  HeartPulse,
  Info,
  Layers,
  Loader2,
  Microscope,
  Play,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, predictApi } from '@/api'
import { useWorkspace } from '@/lib/store'
import { ALGO_LABEL, featurePrecision, pct, signed } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader } from '@/components/ui'
import { ContributionChart, TopDrivers } from '@/components/ContributionChart'
import { ProbabilityDial } from '@/components/domain'
import { useToast } from '@/components/Toast'
import type { DiseaseInfo, PredictResult } from '@/types'

/**
 * Cross-algorithm explanation workbench.
 *
 * Runs the same feature vector through every algorithm registered for the
 * disease and lines the explanations up side by side. This is the page that
 * makes model choice legible: the verdict is stable, but *which* features
 * drive it is not.
 */
export default function ExplainPage() {
  const toast = useToast()
  const { diseases, activeDisease, loadDiseases } = useWorkspace()
  const module: DiseaseInfo | undefined = diseases.find(
    (d) => d.disease === activeDisease,
  )

  const [values, setValues] = useState<Record<string, string>>({})
  const [results, setResults] = useState<PredictResult[] | null>(null)
  const [activeTab, setActiveTab] = useState(0)

  useEffect(() => {
    loadDiseases().catch(() => {})
  }, [loadDiseases])

  useEffect(() => {
    if (!module) return
    const next: Record<string, string> = {}
    module.feature_schema.forEach((spec, i) => {
      const hint = module.default_values[i]
      next[spec.key] = hint !== undefined ? trimNum(hint, spec) : ''
    })
    setValues(next)
    setResults(null)
    setActiveTab(0)
  }, [module?.disease, module])

  const runAll = useMutation({
    mutationFn: async (algorithms: string[]) => {
      const features = module!.feature_schema.map(
        (spec) => Number(values[spec.key]) || spec.mean,
      )
      // Sequential rather than parallel: keeps SHAP memory bounded and gives
      // the progress indicator something meaningful to report.
      const out: PredictResult[] = []
      for (const algo of algorithms) {
        out.push(
          await predictApi.run({
            disease: activeDisease,
            model: algo,
            features,
            persist: false,
            with_explanation: true,
            with_narrative: false,
          }),
        )
      }
      return out
    },
    onSuccess: (data) => {
      setResults(data)
      setActiveTab(0)
      toast.success('对比完成', `已完成 ${data.length} 个算法的归因分析`)
    },
    onError: (err) =>
      toast.error('对比失败', err instanceof ApiError ? err.message : '请稍后重试'),
  })

  const handleRun = () => {
    if (!module) return
    runAll.mutate(module.models.map((m) => m.algorithm))
  }

  const current = results?.[activeTab]

  /** Features whose sign flips between algorithms — the interesting ones. */
  const divergence = useMemo(() => {
    if (!results || results.length < 2) return []
    const byKey = new Map<string, { name: string; signs: number[]; mags: number[] }>()
    results.forEach((r) => {
      r.explanation?.contributions.forEach((c) => {
        if (!byKey.has(c.key)) {
          byKey.set(c.key, { name: c.name_zh, signs: [], mags: [] })
        }
        const e = byKey.get(c.key)!
        e.signs.push(Math.sign(c.contribution))
        e.mags.push(c.contribution)
      })
    })
    return [...byKey.entries()]
      .filter(([, v]) => new Set(v.signs).size > 1)
      .map(([key, v]) => ({
        key,
        name: v.name,
        spread: Math.max(...v.mags) - Math.min(...v.mags),
        signs: v.signs,
      }))
      .sort((a, b) => b.spread - a.spread)
      .slice(0, 6)
  }, [results])

  if (!module) {
    return (
      <div className="space-y-6">
        <PageHeader />
        <Panel>
          {diseases.length === 0 ? (
            <LoadingBlock rows={5} />
          ) : (
            <EmptyState icon={Microscope} title="未找到该病种模块" />
          )}
        </Panel>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader />

      <div className="grid gap-6 xl:grid-cols-[1fr_1.5fr]">
        {/* --------------------------- input column --------------------------- */}
        <div className="space-y-6">
          <Panel>
            <PanelHeader
              title="样本指标"
              icon={module.disease === 'heart' ? HeartPulse : Microscope}
              subtitle="用于横向对比三个算法的输入向量"
            />
            <div className="max-h-[560px] space-y-3 overflow-y-auto p-5 scroll-area mask-fade-b">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                {module.feature_schema.map((spec) => (
                  <div key={spec.key}>
                    <label className="label" htmlFor={`ex-${spec.key}`}>
                      <span className="normal-case text-ink-muted">
                        {spec.name_zh}
                      </span>
                      {spec.unit !== '—' && (
                        <span className="ml-1.5 font-normal text-ink-ghost">
                          {spec.unit}
                        </span>
                      )}
                    </label>
                    <input
                      id={`ex-${spec.key}`}
                      type="number"
                      step="any"
                      inputMode="decimal"
                      value={values[spec.key] ?? ''}
                      onChange={(e) =>
                        setValues((v) => ({ ...v, [spec.key]: e.target.value }))
                      }
                      placeholder={trimNum(spec.mean, spec)}
                      className="field py-2 text-xs"
                    />
                  </div>
                ))}
              </div>
            </div>
            <div className="border-t border-line/70 p-5">
              <button
                type="button"
                onClick={handleRun}
                disabled={runAll.isPending}
                className="btn-primary w-full"
              >
                {runAll.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    正在逐个推理…
                  </>
                ) : (
                  <>
                    <GitCompareArrows className="h-4 w-4" />
                    运行全部 {module.models.length} 个算法
                  </>
                )}
              </button>
              <p className="mt-2.5 flex items-start gap-1.5 text-2xs leading-relaxed text-ink-ghost">
                <Info className="mt-px h-3 w-3 shrink-0" />
                对比结果不写入历史记录，仅用于探索。每次运行约需数秒。
              </p>
            </div>
          </Panel>

          {divergence.length > 0 && (
            <Panel className="animate-fade-up">
              <PanelHeader
                title="归因分歧"
                icon={TriangleAlert}
                subtitle="这些特征在不同算法下推动方向相反 —— 说明其作用依赖具体模型结构"
              />
              <ul className="divide-y divide-line/60">
                {divergence.map((d) => (
                  <li key={d.key} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-xs font-medium text-ink">
                        {d.name}
                      </span>
                      <span className="shrink-0 font-mono text-2xs text-ink-ghost">
                        极差 {d.spread.toFixed(4)}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {results!.map((r, i) => {
                        const c = r.explanation?.contributions.find(
                          (x) => x.key === d.key,
                        )
                        return (
                          <span
                            key={i}
                            className={clsx(
                              'chip text-[0.625rem]',
                              c?.contribution === undefined
                                ? 'chip-neutral'
                                : c.contribution > 0
                                  ? 'chip-risk'
                                  : 'chip-safe',
                            )}
                          >
                            {ALGO_LABEL[r.algorithm] ?? r.algorithm}{' '}
                            <span className="font-mono">
                              {c ? signed(c.contribution, 3) : '—'}
                            </span>
                          </span>
                        )
                      })}
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        {/* --------------------------- result column --------------------------- */}
        <div className="space-y-6">
          {!results ? (
            <Panel>
              <EmptyState
                icon={Sparkles}
                title="尚未运行对比"
                description="填写左侧指标后点击「运行全部算法」，即可看到三种模型对同一份数据的不同归因。"
                action={
                  <button
                    type="button"
                    onClick={handleRun}
                    className="btn-primary"
                    disabled={runAll.isPending}
                  >
                    <Play className="h-4 w-4" />
                    立即开始
                  </button>
                }
              />
            </Panel>
          ) : (
            <>
              {/* verdict overview strip */}
              <Panel>
                <PanelHeader
                  title="判定一致性"
                  icon={Layers}
                  subtitle="三种算法的概率与最终判定"
                />
                <div className="grid gap-4 p-5 sm:grid-cols-3">
                  {results.map((r, i) => (
                    <button
                      key={r.model_id}
                      type="button"
                      onClick={() => setActiveTab(i)}
                      className={clsx(
                        'rounded-2xl border p-4 text-left transition-all duration-200',
                        activeTab === i
                          ? 'border-brand-500/50 bg-brand-500/8 shadow-glow'
                          : 'border-line bg-canvas/50 hover:border-line-strong',
                      )}
                    >
                      <p className="text-2xs font-semibold uppercase tracking-wider text-ink-faint">
                        {ALGO_LABEL[r.algorithm] ?? r.algorithm}
                      </p>
                      <div className="mt-2 flex items-center justify-between gap-3">
                        <span
                          className={clsx(
                            'font-mono text-xl font-bold tabular-nums',
                            r.verdict === 'positive'
                              ? 'text-risk-high'
                              : 'text-risk-low',
                          )}
                        >
                          {pct(r.positive_prob, 1)}
                        </span>
                        <span
                          className={
                            r.verdict === 'positive' ? 'chip-risk' : 'chip-safe'
                          }
                        >
                          {r.verdict_label}
                        </span>
                      </div>
                      <p className="mt-2 font-mono text-[0.625rem] text-ink-ghost">
                        AUC {r.metrics.roc_auc.toFixed(4)} · {r.elapsed_ms} ms
                      </p>
                    </button>
                  ))}
                </div>
              </Panel>

              {current && (
                <>
                  <Panel className="animate-fade-up">
                    <PanelHeader
                      title={`归因详情 · ${ALGO_LABEL[current.algorithm] ?? current.algorithm}`}
                      icon={Brain}
                      subtitle={current.model_id}
                      actions={
                        <div className="flex items-center gap-1.5">
                          {results.map((r, i) => (
                            <button
                              key={r.model_id}
                              type="button"
                              onClick={() => setActiveTab(i)}
                              className={clsx(
                                'rounded-lg px-2.5 py-1 text-2xs font-semibold transition-colors',
                                activeTab === i
                                  ? 'bg-brand-500/15 text-brand-200'
                                  : 'text-ink-ghost hover:text-ink-muted',
                              )}
                            >
                              {ALGO_LABEL[r.algorithm] ?? r.algorithm}
                            </button>
                          ))}
                        </div>
                      }
                    />
                    <div className="flex flex-wrap items-center gap-6 border-b border-line/60 px-5 py-4">
                      <ProbabilityDial
                        value={current.positive_prob}
                        threshold={current.threshold}
                        positive={current.verdict === 'positive'}
                        size={112}
                      />
                      <div className="min-w-0 flex-1">
                        <TopDrivers
                          topPositive={current.explanation?.top_positive ?? []}
                          topNegative={current.explanation?.top_negative ?? []}
                          specs={module.feature_schema}
                        />
                      </div>
                    </div>
                    {current.explanation ? (
                      <ContributionChart
                        contributions={current.explanation.contributions}
                        topPositive={current.explanation.top_positive}
                        topNegative={current.explanation.top_negative}
                        baseValue={current.explanation.base_value}
                        specs={module.feature_schema}
                        limit={10}
                      />
                    ) : (
                      <EmptyState icon={Brain} title="未生成归因" />
                    )}
                  </Panel>

                  {/* side-by-side comparison table */}
                  <Panel>
                    <PanelHeader
                      title="贡献值对照表"
                      icon={GitCompareArrows}
                      subtitle="同一特征在各算法下的 SHAP 值，便于观察模型偏好差异"
                    />
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[520px] text-xs">
                        <thead>
                          <tr className="border-b border-line/70 text-2xs uppercase tracking-wider text-ink-ghost">
                            <th className="px-5 py-2.5 text-left font-semibold">
                              特征
                            </th>
                            {results.map((r) => (
                              <th
                                key={r.model_id}
                                className="px-3 py-2.5 text-right font-semibold"
                              >
                                {ALGO_LABEL[r.algorithm] ?? r.algorithm}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {module.feature_schema
                            .map((spec) => ({
                              spec,
                              mag: Math.max(
                                ...results.map((r) =>
                                  Math.abs(
                                    r.explanation?.contributions.find(
                                      (c) => c.key === spec.key,
                                    )?.contribution ?? 0,
                                  ),
                                ),
                              ),
                            }))
                            .sort((a, b) => b.mag - a.mag)
                            .slice(0, 15)
                            .map(({ spec }) => (
                              <tr
                                key={spec.key}
                                className="border-b border-line/40 last:border-0 hover:bg-canvas-hover/40"
                              >
                                <td className="px-5 py-2.5">
                                  <span className="text-ink-muted">
                                    {spec.name_zh}
                                  </span>
                                  <span className="ml-1.5 font-mono text-[0.625rem] text-ink-ghost">
                                    {Number(values[spec.key] || spec.mean).toFixed(
                                      featurePrecision(spec),
                                    )}
                                  </span>
                                </td>
                                {results.map((r) => {
                                  const c = r.explanation?.contributions.find(
                                    (x) => x.key === spec.key,
                                  )
                                  return (
                                    <td
                                      key={r.model_id}
                                      className={clsx(
                                        'px-3 py-2.5 text-right font-mono tabular-nums',
                                        c === undefined
                                          ? 'text-ink-ghost'
                                          : c.contribution > 0
                                            ? 'text-risk-high'
                                            : c.contribution < 0
                                              ? 'text-risk-low'
                                              : 'text-ink-faint',
                                      )}
                                    >
                                      {c ? signed(c.contribution, 4) : '—'}
                                    </td>
                                  )
                                })}
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  </Panel>
                </>
              )}
            </>
          )}
        </div>
      </div>

      <p className="pb-2 text-center text-2xs text-ink-ghost">
        需要单个算法的完整结论？前往{' '}
        <Link to="/diagnosis" className="text-brand-300 hover:text-brand-200">
          智能诊断
        </Link>
      </p>
    </div>
  )
}

function PageHeader() {
  return (
    <header>
      <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
        Explainability
      </p>
      <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
        可解释分析
      </h1>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-muted">
        把同一份检查数据送进不同算法，对比它们的归因结果。
        当判定一致但归因分歧时，说明该结论对模型选择较为敏感。
      </p>
    </header>
  )
}

function trimNum(value: number, spec: { min: number; max: number }): string {
  const span = Math.abs(spec.max - spec.min)
  const digits = span >= 100 ? 2 : span >= 1 ? 3 : 5
  return Number(value).toFixed(digits)
}
