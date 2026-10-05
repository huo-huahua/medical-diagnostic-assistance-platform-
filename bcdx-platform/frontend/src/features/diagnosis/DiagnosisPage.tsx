import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import {
  AlertTriangle,
  Brain,
  ChevronDown,
  Eraser,
  FlaskConical,
  HeartPulse,
  Info,
  Loader2,
  Microscope,
  Play,
  RotateCcw,
  Save,
  Wand2,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, predictApi, type PredictPayload } from '@/api'
import { resolveAlgo, useWorkspace } from '@/lib/store'
import { ALGO_LABEL, featurePrecision, pct } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader } from '@/components/ui'
import { MetricsStrip, RangeWarnings, VerdictHero } from '@/components/domain'
import { ContributionChart, TopDrivers } from '@/components/ContributionChart'
import { useToast } from '@/components/Toast'
import type { Disease, DiseaseInfo, PredictResult } from '@/types'

export default function DiagnosisPage() {
  const toast = useToast()
  const { diseases, activeDisease, selectedAlgo, setAlgo, loadDiseases } =
    useWorkspace()

  const module: DiseaseInfo | undefined = diseases.find(
    (d) => d.disease === activeDisease,
  )
  const algo = resolveAlgo(diseases, activeDisease, selectedAlgo)

  const [values, setValues] = useState<Record<string, string>>({})
  const [caseLabel, setCaseLabel] = useState('')
  const [withNarrative, setWithNarrative] = useState(false)
  const [result, setResult] = useState<PredictResult | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [invalid, setInvalid] = useState<Set<string>>(new Set())

  useEffect(() => {
    loadDiseases().catch(() => {})
  }, [loadDiseases])

  // When the module changes, seed inputs from the training-set means.
  useEffect(() => {
    if (!module) return
    const next: Record<string, string> = {}
    module.feature_schema.forEach((spec, i) => {
      const hint = module.default_values[i]
      next[spec.key] = hint !== undefined ? trimNum(hint, spec) : ''
    })
    setValues(next)
    setResult(null)
    setInvalid(new Set())
  }, [module?.disease, module])

  const filledCount = useMemo(
    () =>
      module
        ? module.feature_schema.filter(
            (s) => values[s.key] !== undefined && values[s.key] !== '',
          ).length
        : 0,
    [module, values],
  )

  const allFilled = !!module && filledCount === module.feature_schema.length

  const predict = useMutation({
    mutationFn: (payload: PredictPayload) => predictApi.run(payload),
    onSuccess: (data) => {
      setResult(data)
      setShowAll(false)
      toast.success(
        '评估完成',
        `${data.verdict_label} · 阳性概率 ${pct(data.positive_prob, 2)}`,
      )
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
    onError: (err) => {
      toast.error(
        '评估失败',
        err instanceof ApiError ? err.message : '请检查输入后重试',
      )
    },
  })

  const submit = () => {
    if (!module) return
    const bad = new Set<string>()
    const features = module.feature_schema.map((spec) => {
      const raw = values[spec.key]
      const parsed = Number(raw)
      if (raw === undefined || raw === '' || Number.isNaN(parsed)) {
        bad.add(spec.key)
        return spec.mean
      }
      return parsed
    })

    setInvalid(bad)
    if (bad.size) {
      toast.error('存在无效输入', `有 ${bad.size} 个字段未填写或格式不正确`)
      return
    }

    predict.mutate({
      disease: activeDisease,
      model: algo,
      features,
      case_label: caseLabel.trim() || null,
      persist: true,
      with_explanation: true,
      with_narrative: withNarrative,
    })
  }

  const fillMeans = () => {
    if (!module) return
    const next: Record<string, string> = {}
    module.feature_schema.forEach((spec, i) => {
      next[spec.key] = trimNum(module.default_values[i] ?? spec.mean, spec)
    })
    setValues(next)
    setInvalid(new Set())
  }

  const clearAll = () => {
    if (!module) return
    const next: Record<string, string> = {}
    module.feature_schema.forEach((spec) => {
      next[spec.key] = ''
    })
    setValues(next)
  }

  const resetAll = () => {
    setResult(null)
    setCaseLabel('')
    fillMeans()
  }

  if (!module) {
    return (
      <div className="space-y-6">
        <PageHeader />
        <Panel>
          {diseases.length === 0 ? (
            <LoadingBlock rows={5} />
          ) : (
            <EmptyState
              icon={Microscope}
              title="未找到该病种模块"
              description="请确认后端已加载模型注册表。"
            />
          )}
        </Panel>
      </div>
    )
  }

  const grouped = groupFeatures(module)

  return (
    <div className="space-y-6">
      <PageHeader />

      {/* ---------------------------- result ---------------------------- */}
      {result && (
        <div className="space-y-6 animate-fade-up">
          <VerdictHero result={result} />
          <RangeWarnings warnings={result.range_warnings} />

          <div className="grid gap-6 xl:grid-cols-[1.25fr_1fr]">
            <Panel>
              <PanelHeader
                title="特征贡献归因"
                icon={Brain}
                subtitle={`基于 ${result.explanation?.method ?? 'SHAP'} 的加性解释，展示每个指标对本次判定的推动方向与幅度`}
                actions={
                  result.explanation &&
                  result.explanation.contributions.length > 12 && (
                    <button
                      type="button"
                      onClick={() => setShowAll((v) => !v)}
                      className="btn-subtle px-3 py-1.5 text-2xs"
                    >
                      {showAll ? '只看主要项' : '展开全部'}
                    </button>
                  )
                }
              />
              {result.explanation ? (
                <ContributionChart
                  contributions={result.explanation.contributions}
                  topPositive={result.explanation.top_positive}
                  topNegative={result.explanation.top_negative}
                  baseValue={result.explanation.base_value}
                  specs={module.feature_schema}
                  limit={showAll ? undefined : 12}
                />
              ) : (
                <EmptyState
                  icon={Brain}
                  title="未生成归因"
                  description="本次请求未开启可解释分析。"
                />
              )}
            </Panel>

            <div className="space-y-6">
              <Panel>
                <PanelHeader
                  title="归因摘要"
                  icon={FlaskConical}
                  subtitle="按影响幅度排序的主要驱动因素"
                />
                <div className="p-5">
                  {result.explanation ? (
                    <TopDrivers
                      topPositive={result.explanation.top_positive}
                      topNegative={result.explanation.top_negative}
                      specs={module.feature_schema}
                    />
                  ) : (
                    <p className="text-xs text-ink-faint">暂无数据</p>
                  )}
                </div>
              </Panel>

              {result.narrative && (
                <Panel>
                  <PanelHeader
                    title="结果说明"
                    icon={Info}
                    subtitle={
                      result.narrative_source === 'llm'
                        ? '由语言模型基于结构化结果生成'
                        : '由模板基于结构化结果生成（未消耗外部调用）'
                    }
                  />
                  <div className="p-5">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-muted">
                      {result.narrative}
                    </p>
                  </div>
                </Panel>
              )}
            </div>
          </div>

          <Panel>
            <PanelHeader
              title="模型性能参考"
              icon={FlaskConical}
              subtitle={`${result.model_id} 在留出测试集上的表现 —— 结论需结合模型可靠性一并理解`}
            />
            <div className="p-5">
              <MetricsStrip result={result} />
            </div>
          </Panel>
        </div>
      )}

      {/* ---------------------------- inputs ---------------------------- */}
      <Panel>
        <PanelHeader
          title={`输入 ${module.display_zh} 检查指标`}
          icon={module.disease === 'heart' ? HeartPulse : Microscope}
          subtitle={`共 ${module.n_features} 个特征，已填写 ${filledCount} 个。默认值取自训练集均值，可整体替换为你自己的数据。`}
          actions={
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={fillMeans}
                className="btn-subtle px-3 py-1.5 text-2xs"
                title="用训练集均值填充"
              >
                <Wand2 className="h-3.5 w-3.5" />
                填充均值
              </button>
              <button
                type="button"
                onClick={clearAll}
                className="btn-subtle px-3 py-1.5 text-2xs"
                title="清空全部输入"
              >
                <Eraser className="h-3.5 w-3.5" />
                清空
              </button>
            </div>
          }
        />

        <div className="space-y-5 p-5">
          {/* algorithm + label */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="algo">
                推理算法
              </label>
              <div className="relative">
                <select
                  id="algo"
                  value={algo}
                  onChange={(e) => setAlgo(activeDisease as Disease, e.target.value)}
                  className="field appearance-none pr-10"
                >
                  {module.models.map((m) => (
                    <option key={m.id} value={m.algorithm}>
                      {ALGO_LABEL[m.algorithm] ?? m.algorithm} · AUC{' '}
                      {m.test.roc_auc.toFixed(4)}
                      {m.id === module.champion_id ? ' · 默认' : ''}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-ghost" />
              </div>
              <p className="mt-1.5 text-2xs text-ink-ghost">
                默认选择交叉验证表现最优的算法
              </p>
            </div>

            <div>
              <label className="label" htmlFor="case_label">
                病例标签（可选）
              </label>
              <input
                id="case_label"
                type="text"
                maxLength={80}
                value={caseLabel}
                onChange={(e) => setCaseLabel(e.target.value)}
                placeholder="例如：门诊-女-52岁"
                className="field"
              />
              <p className="mt-1.5 text-2xs text-ink-ghost">
                用于在历史记录中区分不同样本，请勿填写真实身份信息
              </p>
            </div>
          </div>

          <div className="divider" />

          {/* feature groups */}
          <div className="space-y-5">
            {grouped.map(({ group, groupZh, specs }) => (
              <div key={group}>
                <div className="mb-3 flex items-center gap-2.5">
                  <h3 className="text-2xs font-semibold uppercase tracking-wider text-brand-300">
                    {groupZh}
                  </h3>
                  <span className="h-px flex-1 bg-line/70" />
                  <span className="text-2xs text-ink-ghost">
                    {specs.length} 项
                  </span>
                </div>

                <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
                  {specs.map((spec) => {
                    const bad = invalid.has(spec.key)
                    const raw = values[spec.key] ?? ''
                    const outOfRange =
                      raw !== '' &&
                      !Number.isNaN(Number(raw)) &&
                      (Number(raw) < spec.min || Number(raw) > spec.max)
                    const digits = featurePrecision(spec)

                    return (
                      <div key={spec.key}>
                        <label className="label" htmlFor={spec.key}>
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
                          id={spec.key}
                          type="number"
                          step="any"
                          inputMode="decimal"
                          value={raw}
                          onChange={(e) => {
                            setValues((v) => ({ ...v, [spec.key]: e.target.value }))
                            setInvalid((s) => {
                              if (!s.has(spec.key)) return s
                              const n = new Set(s)
                              n.delete(spec.key)
                              return n
                            })
                          }}
                          placeholder={trimNum(spec.mean, spec)}
                          className={clsx(
                            'field',
                            bad && 'field-invalid',
                            outOfRange && !bad && 'border-risk-warn/60',
                          )}
                        />
                        <p className="mt-1 flex items-center gap-1.5 font-mono text-[0.625rem] text-ink-ghost">
                          范围 {trimNum(spec.min, spec)} – {trimNum(spec.max, spec)}
                          {outOfRange && (
                            <span className="inline-flex items-center gap-0.5 font-sans text-risk-warn">
                              <AlertTriangle className="h-3 w-3" />
                              超出训练分布
                            </span>
                          )}
                        </p>
                        <span className="sr-only">{digits}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="divider" />

          {/* actions */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <label className="flex cursor-pointer items-start gap-2.5">
              <input
                type="checkbox"
                checked={withNarrative}
                onChange={(e) => setWithNarrative(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-line-strong bg-canvas accent-brand-500"
              />
              <span className="text-xs leading-relaxed text-ink-muted">
                同时生成自然语言说明
                <span className="block text-2xs text-ink-ghost">
                  默认使用本地模板，不产生外部调用费用
                </span>
              </span>
            </label>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={resetAll}
                className="btn-ghost"
                disabled={predict.isPending}
              >
                <RotateCcw className="h-4 w-4" />
                重置
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={predict.isPending || !allFilled}
                className="btn-primary"
                title={!allFilled ? '请先填写全部特征' : undefined}
              >
                {predict.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    正在推理…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" />
                    运行评估
                  </>
                )}
              </button>
            </div>
          </div>

          {!allFilled && (
            <p className="flex items-center gap-2 rounded-xl border border-line bg-canvas/60 px-3.5 py-2.5 text-2xs text-ink-faint">
              <Info className="h-3.5 w-3.5 shrink-0" />
              还需填写 {module.n_features - filledCount} 个字段，或直接点击「填充均值」
              以使用训练集典型值快速体验。
            </p>
          )}

          <p className="flex items-start gap-2 rounded-xl border border-risk-warn/25 bg-risk-warnSoft/25 px-3.5 py-2.5 text-2xs leading-relaxed text-risk-warn/90">
            <Save className="mt-px h-3.5 w-3.5 shrink-0" />
            <span>
              评估结果会保存到你的历史记录。平台不存储任何可直接识别个人身份的信息，
              请勿在病例标签中填写真实姓名或证件号码。
            </span>
          </p>
        </div>
      </Panel>

      <p className="pb-2 text-center text-2xs leading-relaxed text-ink-ghost">
        <Link to="/explain" className="text-brand-300 hover:text-brand-200">
          查看可解释分析
        </Link>{' '}
        ·{' '}
        <Link to="/compare" className="text-brand-300 hover:text-brand-200">
          对比不同算法
        </Link>
      </p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function PageHeader() {
  return (
    <header>
      <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
        Diagnosis
      </p>
      <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
        智能诊断
      </h1>
      <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-muted">
        输入一组检查指标，平台会调用已校准的统计模型给出风险概率、
        判定结论以及每个指标的具体贡献。
      </p>
    </header>
  )
}

function trimNum(value: number, spec: { min: number; max: number }): string {
  const span = Math.abs(spec.max - spec.min)
  const digits = span >= 100 ? 2 : span >= 1 ? 3 : 5
  return Number(value).toFixed(digits)
}

function groupFeatures(module: DiseaseInfo) {
  const map = new Map<
    string,
    { group: string; groupZh: string; specs: typeof module.feature_schema }
  >()
  module.feature_schema.forEach((spec) => {
    if (!map.has(spec.group)) {
      map.set(spec.group, {
        group: spec.group,
        groupZh: spec.group_zh,
        specs: [],
      })
    }
    map.get(spec.group)!.specs.push(spec)
  })
  return [...map.values()]
}
