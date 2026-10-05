import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Clock,
  Cloud,
  Database,
  FlaskConical,
  Info,
  Loader2,
  MinusCircle,
  Play,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wallet,
  XCircle,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, llmApi, ragApi } from '@/api'
import { useWorkspace } from '@/lib/store'
import { formatRelative, pct } from '@/lib/format'
import { LoadingBlock, Panel, PanelHeader } from '@/components/ui'
import { useToast } from '@/components/Toast'
import LlmPanel, { LLM_STATUS_KEY } from '@/features/llm/LlmPanel'
import type { Disease, QaCompareResult, QaPathResult } from '@/types'

const SUGGESTIONS: Record<Disease, string[]> = {
  breast: [
    '乳腺癌的早期症状有哪些？',
    'BI-RADS 分级是什么意思？',
    '乳腺钼靶和超声有什么区别？',
    '如何预防乳腺癌？',
  ],
  heart: [
    '冠心病如何诊断？',
    '心肌梗死有哪些典型症状？',
    '高血压与心脏病有什么关系？',
    '心电图能查出哪些心脏问题？',
  ],
}

/** One row of the metric table. Keeping them declarative makes it obvious
 *  that the *same* measurement is applied to every path. */
interface MetricRow {
  label: string
  hint?: string
  render: (p: QaPathResult) => React.ReactNode
}

const OK = (
  <span className="inline-flex items-center gap-1 text-risk-low">
    <CheckCircle2 className="h-3.5 w-3.5" />
    是
  </span>
)
const NO = (
  <span className="inline-flex items-center gap-1 text-ink-faint">
    <XCircle className="h-3.5 w-3.5" />
    否
  </span>
)
const SKIPPED = <span className="text-ink-ghost">未启用</span>

const METRICS: MetricRow[] = [
  {
    label: '检索本地知识库',
    hint: '是否先用本地知识库检索，再组织答案',
    render: (p) => (p.status === 'ok' ? (p.uses_retrieval ? OK : NO) : SKIPPED),
  },
  {
    label: '调用外部 API',
    hint: '是否向第三方模型服务发送请求。演示模式下不联网，也不产生费用',
    render: (p) => (p.status === 'ok' ? (p.external_call ? OK : NO) : SKIPPED),
  },
  {
    label: '使用的模型',
    hint: '这一列实际发往哪个模型。演示模型由本地代码生成，不是语言模型',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : !p.external_call ? (
        <span className="text-ink-ghost">本地，无模型</span>
      ) : (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-[0.6875rem] text-ink-muted">{p.model}</span>
          {p.is_mock && (
            <span className="rounded border border-risk-warn/35 px-1 py-0.5 text-[0.625rem] text-risk-warn">
              演示
            </span>
          )}
        </span>
      ),
  },
  {
    label: '回答带出处',
    hint: '每条结论能否指回知识库中的原文条目',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : p.citation_count > 0 ? (
        <span className="inline-flex items-center gap-1 text-risk-low">
          <BookOpen className="h-3.5 w-3.5" />
          {p.citation_count} 条
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 text-risk-warn">
          <AlertTriangle className="h-3.5 w-3.5" />
          无出处
        </span>
      ),
  },
  {
    label: '与知识库词面重合',
    hint: '回答用词有多少比例出现在检索到的原文中。这是词面代理指标，不是正确性证明',
    render: (p) =>
      p.status !== 'ok' || !p.answer ? (
        SKIPPED
      ) : (
        <span className="font-mono tabular-nums">{pct(p.lexical_overlap, 1)}</span>
      ),
  },
  {
    label: '绝对化表述',
    hint: '「一定 / 保证 / 彻底治愈」等措辞的命中数量。浅层词汇筛查，不等于安全审查',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : p.risk_phrases.length === 0 ? (
        <span className="text-risk-low">未发现</span>
      ) : (
        <span className="inline-flex items-center gap-1 text-risk-warn">
          {p.risk_phrases.length} 处
          <span className="text-ink-ghost">（{p.risk_phrases.join('、')}）</span>
        </span>
      ),
  },
  {
    label: '回答长度',
    render: (p) =>
      p.status !== 'ok' ? SKIPPED : <span className="font-mono tabular-nums">{p.answer_chars} 字</span>,
  },
  {
    label: '耗时',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : (
        <span className="font-mono tabular-nums">{p.latency_ms} ms</span>
      ),
  },
  {
    label: 'Token 消耗',
    hint: '输入 + 输出，仅外部路径产生',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : p.prompt_tokens + p.completion_tokens === 0 ? (
        <span className="text-ink-ghost">—</span>
      ) : (
        <span className="font-mono tabular-nums">
          {p.prompt_tokens} + {p.completion_tokens}
        </span>
      ),
  },
  {
    label: '预估费用',
    render: (p) =>
      p.status !== 'ok' ? (
        SKIPPED
      ) : p.cost_cny === 0 ? (
        <span className="text-risk-low">¥0</span>
      ) : (
        <span className="font-mono tabular-nums text-risk-warn">
          ¥{p.cost_cny.toFixed(4)}
        </span>
      ),
  },
  {
    label: '本次命中缓存',
    hint: '缓存命中表示没有真实调用外部接口，因此不产生费用',
    render: (p) =>
      p.status !== 'ok' ? SKIPPED : p.cache_hit ? <span className="text-brand-300">是</span> : NO,
  },
]

export default function QaComparePage() {
  const toast = useToast()
  const qc = useQueryClient()
  const { diseases, activeDisease, setActiveDisease } = useWorkspace()

  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<QaCompareResult | null>(null)
  const [allowExternal, setAllowExternal] = useState(false)
  const [modelsInput, setModelsInput] = useState('')

  const usage = useQuery({ queryKey: ['rag-usage'], queryFn: ragApi.usage })
  const history = useQuery({
    queryKey: ['qa-comparisons'],
    queryFn: ragApi.comparisons,
  })
  // Shares its cache entry with LlmPanel, so this costs one request, not two.
  const llm = useQuery({ queryKey: LLM_STATUS_KEY, queryFn: llmApi.status })

  const activeDiseaseName =
    diseases.find((d) => d.disease === activeDisease)?.display_zh ??
    (activeDisease === 'heart' ? '心脏病' : '乳腺癌')

  /** True only when a key is configured AND LLM_ENABLED is on. */
  const externalAvailable = usage.data?.available ?? false
  const demoMode = llm.data?.is_demo ?? false
  const maxModels = llm.data?.max_compare_models ?? 3

  /* Demo mode costs nothing, so the opt-in starts switched on there. The
     switch exists to authorise spending money; leaving it off for a free
     operation just hides the comparison this page is built to show, which is
     exactly how the three columns went missing once already. A real provider
     keeps the explicit opt-in, because there the switch really does spend. */
  useEffect(() => {
    if (demoMode) setAllowExternal(true)
  }, [demoMode])

  /** Models typed by the user, split on commas or whitespace. */
  const requestedModels = modelsInput
    .split(/[,，\s]+/)
    .map((m) => m.trim())
    .filter(Boolean)
  const tooManyModels = requestedModels.length > maxModels

  const run = useMutation({
    mutationFn: (q: string) =>
      ragApi.compare({
        question: q,
        disease: activeDisease,
        // When no external model is configured the two paid paths cost nothing
        // to *attempt* — the backend marks them "skipped" — so request them
        // anyway. That way the table always has all three columns and the
        // reader can see what is being compared, instead of a one-column table
        // that compares nothing. Demo mode is in the same list for the same
        // reason: it is free, so gating it behind a spend-money switch would
        // hide the comparison rather than protect anyone.
        paths:
          allowExternal || !externalAvailable || demoMode
            ? ['local_rag', 'llm_direct', 'llm_rag']
            : ['local_rag'],
        // Omitted entirely when the field is empty, so the response keeps the
        // original three columns and the default request is unchanged.
        models: requestedModels.length && !tooManyModels ? requestedModels : undefined,
      }),
    onSuccess: (data) => {
      setResult(data)
      qc.invalidateQueries({ queryKey: ['qa-comparisons'] })
      qc.invalidateQueries({ queryKey: ['rag-usage'] })
      qc.invalidateQueries({ queryKey: LLM_STATUS_KEY })
      if (data.summary.external_calls > 0) {
        if (data.summary.demo_mode) {
          toast.info(
            '对比完成（演示模式）',
            `运行了 ${data.summary.external_calls} 条外部链路，但走的是内置演示模型：不联网、不计费。`,
          )
        } else {
          toast.info(
            '对比完成',
            `本次真实调用了 ${data.summary.external_calls} 次外部接口，预估费用 ¥${data.summary.cost_cny.toFixed(4)}`,
          )
        }
      }
      if (data.models.length) {
        toast.success('已完成多模型对比', `模型：${data.models.join('、')}`)
      }
    },
    onError: (err) => {
      toast.error('对比失败', err instanceof ApiError ? err.message : '请稍后重试')
    },
  })

  const removeComparison = useMutation({
    mutationFn: (id: number) => ragApi.removeComparison(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['qa-comparisons'] })
      toast.success('已删除该条记录')
    },
  })

  const submit = (text?: string) => {
    const q = (text ?? question).trim()
    if (!q || run.isPending) return
    setQuestion(q)
    run.mutate(q)
  }

  const columns = result?.paths ?? []

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
            Comparison
          </p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            问答路径对比
          </h1>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-ink-muted">
            同一个问题交给三条不同的问答链路，把差异摊开来看：
            <span className="text-ink-muted">本地检索增强</span>、
            <span className="text-ink-muted">外部模型直答（无检索）</span>、
            <span className="text-ink-muted">外部模型 + 检索增强</span>。
            对比的重点不是「谁写得更好看」，而是
            <span className="text-ink">回答有没有可核查的出处</span>、
            <span className="text-ink">用了多少外部调用</span>。
          </p>
        </div>
        {usage.data && (
          <div className="flex items-center gap-2">
            <span
              className={clsx(
                'chip',
                usage.data.api_calls_this_process === 0
                  ? 'border-risk-low/40 bg-risk-lowSoft/60 text-risk-low'
                  : 'chip-warn',
              )}
            >
              <ShieldCheck className="h-3 w-3" />
              本进程外部调用 {usage.data.api_calls_this_process} 次
            </span>
          </div>
        )}
      </header>

      <LlmPanel />

      {/* ------------------------------ ask ------------------------------ */}
      <Panel>
        <PanelHeader
          title="提出问题"
          icon={FlaskConical}
          subtitle="三条链路共享同一次本地检索，因此差异只来自答案的组织方式，而非不同的输入"
          actions={
            <div className="flex items-center gap-1.5">
              {(['breast', 'heart'] as Disease[]).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => {
                    setActiveDisease(d)
                    setResult(null)
                  }}
                  className={clsx(
                    'rounded-lg border px-2.5 py-1.5 text-2xs font-semibold transition-all',
                    activeDisease === d
                      ? 'border-brand-500/50 bg-brand-500/12 text-brand-200'
                      : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:text-ink-muted',
                  )}
                >
                  {d === 'breast' ? '乳腺癌' : '心脏病'}
                </button>
              ))}
            </div>
          }
        />
        <div className="space-y-4 p-5">
          <div className="flex items-end gap-2.5">
            <div className="relative flex-1">
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    submit()
                  }
                }}
                rows={2}
                maxLength={300}
                placeholder={`输入关于${activeDiseaseName}的问题，Enter 开始对比 / Shift+Enter 换行`}
                className="field max-h-32 min-h-[46px] resize-none py-3 font-sans leading-relaxed"
                disabled={run.isPending}
              />
              <span className="pointer-events-none absolute bottom-1.5 right-3 font-mono text-[0.625rem] text-ink-ghost">
                {question.length}/300
              </span>
            </div>
            <button
              type="button"
              onClick={() => submit()}
              disabled={!question.trim() || run.isPending}
              className="btn-primary h-[46px] shrink-0 px-5"
            >
              {run.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              开始对比
            </button>
          </div>

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS[activeDisease].map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => submit(s)}
                disabled={run.isPending}
                className="rounded-lg border border-line bg-canvas-raised/50 px-3 py-1.5 text-2xs text-ink-muted transition-all hover:border-brand-500/40 hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>

          {/* The opt-in switch is the whole cost-control story, so it states
              the consequence in plain words instead of hiding behind a toggle.
              It is disabled (not just ignored) when no external model exists,
              so it never looks like a control that could do something. */}
          <label
            className={clsx(
              'flex items-start gap-3 rounded-xl border px-4 py-3 transition-colors',
              !externalAvailable
                ? 'cursor-not-allowed border-line bg-canvas/50 opacity-70'
                : allowExternal
                  ? 'cursor-pointer border-risk-warn/40 bg-risk-warnSoft/30'
                  : 'cursor-pointer border-line bg-canvas/60',
            )}
          >
            <input
              type="checkbox"
              checked={allowExternal}
              disabled={!externalAvailable}
              onChange={(e) => setAllowExternal(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-risk-warn disabled:cursor-not-allowed"
            />
            <span className="min-w-0">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                <Cloud className="h-3.5 w-3.5" />
                同时运行两条外部模型路径
              </span>
              <span className="mt-1 block text-2xs leading-relaxed text-ink-faint">
                {!externalAvailable
                  ? '当前部署未配置可用的 API Key（LLM_ENABLED=false 或 LLM_API_KEY 为空），外部路径不会发起任何请求。下方表格仍会为它们留出列，并显示为「未启用」，以便对照三条链路的差异。'
                  : demoMode
                    ? '当前使用内置演示模型：外部路径可以完整跑通，但不联网、不计费。适合先看清三条链路的差异与各项指标，再决定要不要接入真实模型。'
                    : '开启后会向第三方模型服务发送问题与检索片段，产生真实费用。相同问题会命中缓存，不会重复计费；也可以随时关闭，只跑零成本的本地路径。'}
              </span>
            </span>
          </label>

          {/* Comparing models is the second half of the feature: the same
              question, several models, the same metrics. Left empty on
              purpose by default so the request matches the original
              three-column behaviour exactly. */}
          <div className="rounded-xl border border-line bg-canvas/50 px-4 py-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-ink">
              <Sparkles className="h-3.5 w-3.5" />
              多模型并排对比
              <span className="font-normal text-ink-ghost">
                （可选，最多 {maxModels} 个）
              </span>
            </label>
            <input
              type="text"
              value={modelsInput}
              onChange={(e) => setModelsInput(e.target.value)}
              placeholder={
                llm.data?.model
                  ? `例如：${llm.data.model}, gpt-4o-mini`
                  : '例如：deepseek-chat, gpt-4o-mini'
              }
              className="field mt-2.5 font-mono text-xs"
              spellCheck={false}
            />
            <p className="mt-2 text-2xs leading-relaxed text-ink-faint">
              用逗号分隔。填写后，两条外部路径会<b>各模型各跑一列</b>
              （<code className="font-mono">llm_direct@模型名</code>
              ），本地路径仍然只跑一次。留空则只跑当前配置的模型，也就是原来的三列。
            </p>

            {!!requestedModels.length && (
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                {requestedModels.map((m) => (
                  <span
                    key={m}
                    className="rounded-md border border-line-strong bg-canvas-raised/60 px-1.5 py-0.5 font-mono text-[0.625rem] text-ink-muted"
                  >
                    {m}
                  </span>
                ))}
                {tooManyModels && (
                  <span className="text-[0.625rem] text-risk-warn">
                    超过上限，只会使用前 {maxModels} 个
                  </span>
                )}
                <span className="text-[0.625rem] text-ink-ghost">
                  将产生 {requestedModels.length * 2} 条外部链路
                  {demoMode ? '（演示模式，不计费）' : '（每条都是一次真实调用）'}
                </span>
              </div>
            )}
          </div>
        </div>
      </Panel>

      {run.isPending && (
        <Panel>
          <LoadingBlock rows={3} />
        </Panel>
      )}

      {/* --------------------------- metric table --------------------------- */}
      {result && !run.isPending && (
        <>
          <Panel className="overflow-hidden">
            <PanelHeader
              title="指标对照"
              icon={Sparkles}
              subtitle={
                `「${result.question}」 · 本地检索命中 ${result.hit_count} 个分块` +
                `（归并为 ${result.passage_count} 条引用）· 最高相似度 ${result.top_score.toFixed(3)}` +
                (result.models.length ? ` · 模型 ${result.models.join('、')}` : '')
              }
              actions={
                result.summary.external_calls === 0 ? (
                  <span className="chip-safe">
                    <ShieldCheck className="h-3 w-3" />
                    本次零外部调用
                  </span>
                ) : result.summary.demo_mode ? (
                  <span className="chip-neutral">
                    <ShieldCheck className="h-3 w-3" />
                    演示模式 {result.summary.external_calls} 条链路 · 不计费
                  </span>
                ) : (
                  <span className="chip-warn">
                    <Wallet className="h-3 w-3" />
                    本次外部调用 {result.summary.external_calls} 次 · ¥
                    {result.summary.cost_cny.toFixed(4)}
                  </span>
                )
              }
            />
            <div className="overflow-x-auto scroll-area">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line">
                    <th className="sticky left-0 z-10 bg-canvas-soft/95 px-5 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-ink-faint backdrop-blur">
                      指标
                    </th>
                    {columns.map((p) => (
                      <th
                        key={p.key}
                        className="px-4 py-3 text-left align-top"
                      >
                        <div className="flex items-center gap-1.5">
                          {p.uses_retrieval ? (
                            <Database className="h-3.5 w-3.5 text-brand-400" />
                          ) : (
                            <Cloud className="h-3.5 w-3.5 text-ink-ghost" />
                          )}
                          <span className="text-xs font-semibold text-ink">
                            {p.short}
                          </span>
                        </div>
                        <p className="mt-1 text-[0.625rem] font-normal leading-relaxed text-ink-ghost">
                          {p.label}
                        </p>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {METRICS.map((row, i) => (
                    <tr
                      key={row.label}
                      className={clsx(
                        'border-b border-line/50',
                        i % 2 === 1 && 'bg-canvas/30',
                      )}
                    >
                      <th className="sticky left-0 z-10 bg-canvas-soft/95 px-5 py-2.5 text-left align-top font-normal backdrop-blur">
                        <span className="text-xs text-ink-muted">{row.label}</span>
                        {row.hint && (
                          <span
                            title={row.hint}
                            className="ml-1.5 inline-flex cursor-help align-middle"
                          >
                            <Info className="h-3 w-3 text-ink-ghost" />
                          </span>
                        )}
                      </th>
                      {columns.map((p) => (
                        <td key={p.key} className="px-4 py-2.5 align-top text-xs">
                          {row.render(p)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* ---------------------------- answers ---------------------------- */}
          <div className="grid gap-5 xl:grid-cols-3">
            {columns.map((p) => (
              <PathCard key={p.key} path={p} />
            ))}
          </div>

          {/* ---------------------------- reading ---------------------------- */}
          <Panel>
            <PanelHeader title="怎么读这张表" icon={Info} />
            <div className="space-y-3 p-5 text-xs leading-relaxed text-ink-muted">
              <p>
                <strong className="font-semibold text-ink">「回答带出处」是核心差异。</strong>
                本地路径与「外部 + 检索」路径的每一段都能指回知识库中的具体条目；
                「外部直答」没有可引用的资料，因此只能给出没有 provenance 的表述。
                这在医学场景里是能不能被核查的区别，而不只是文风区别。
              </p>
              <p>
                <strong className="font-semibold text-ink">「词面重合」要看方向，不要看绝对值。</strong>
                它衡量回答用词有多少比例出现在检索到的原文里。中文医学术语本身高度集中，
                所以即使是纯凭记忆作答的「外部直答」也会有可观的重合度，这个数字
                <span className="text-ink">偏高不代表正确、偏低也不代表错误</span>。
                有意义的是同一问题下的相对高低：从原文写出来的回答，用词必然更贴近原文。
              </p>
              <p>
                <strong className="font-semibold text-ink">「绝对化表述」是浅层词汇筛查。</strong>
                它只统计「一定 / 保证 / 彻底治愈」这类措辞的出现次数，不构成安全性保证，
                也不替代医学审校。之所以保留，是因为它能稳定地反映两类回答在语气上的差别。
              </p>
              <p>
                <strong className="font-semibold text-ink">费用与缓存。</strong>
                缓存命中表示这次没有真实调用外部接口，因此不计费。相同或近似的问题
                会被复用同一份结果，这也是本系统把外部调用压到极低的机制之一。
              </p>
              <p>
                <strong className="font-semibold text-ink">多模型列怎么读。</strong>
                填入多个模型后，每条外部链路都会按模型各占一列，检索结果对它们是完全相同的——
                所以列与列之间的差异只可能来自模型本身，而不是输入不同。注意「相同问题」在不同
                模型之间<b>不会</b>共用缓存：缓存键包含模型名，否则第二个模型拿到的会是第一个的答案。
              </p>
              <p>
                <strong className="font-semibold text-ink">看到「演示」标记时。</strong>
                说明这一列来自内置演示模型：它走的是和真实服务完全相同的请求、解析、计费与错误处理
                代码，只是不需要联网和密钥，输出是本地生成的占位文本。
                它可以用来说明<b>这套对比机制如何工作</b>，但<b>不能</b>用来评价任何模型的真实能力。
              </p>
            </div>
          </Panel>
        </>
      )}

      {/* ---------------------------- history ---------------------------- */}
      <Panel>
        <PanelHeader
          title="对比历史"
          icon={Clock}
          subtitle="保留历史记录，费用与出处差异可以事后复核，而不只是在屏幕上出现一次"
        />
        {history.isLoading ? (
          <LoadingBlock rows={2} />
        ) : !history.data?.length ? (
          <p className="px-5 py-8 text-center text-xs text-ink-ghost">
            还没有对比记录，先在上方提一个问题吧
          </p>
        ) : (
          <ul className="divide-y divide-line/60">
            {history.data.map((h) => (
              <li key={h.id} className="group flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-ink-muted">
                    {h.question}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.625rem] text-ink-ghost">
                    <span>{h.disease === 'heart' ? '心脏病' : '乳腺癌'}</span>
                    <span>{formatRelative(h.created_at)}</span>
                    <span
                      className={
                        h.external_calls === 0 ? 'text-risk-low' : 'text-risk-warn'
                      }
                    >
                      外部调用 {h.external_calls} 次
                    </span>
                    {h.cache_hits > 0 && <span>缓存命中 {h.cache_hits} 次</span>}
                    <span>{h.total_latency_ms} ms</span>
                    {h.cost_cny > 0 && (
                      <span className="font-mono">¥{h.cost_cny.toFixed(4)}</span>
                    )}
                    {h.refused && <span className="text-risk-warn">已拒答</span>}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removeComparison.mutate(h.id)}
                  aria-label="删除该条对比记录"
                  className="shrink-0 rounded-md p-1.5 text-ink-ghost opacity-0 transition-all hover:text-risk-high group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function PathCard({ path }: { path: QaPathResult }) {
  const isLocal = !path.external_call
  const skipped = path.status !== 'ok'

  return (
    <Panel className="flex flex-col overflow-hidden">
      <div
        className={clsx(
          'flex items-center justify-between gap-2 border-b border-line/70 px-4 py-3',
          isLocal ? 'bg-brand-500/8' : 'bg-risk-warnSoft/25',
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          {isLocal ? (
            <Database className="h-4 w-4 shrink-0 text-brand-400" />
          ) : (
            <Cloud className="h-4 w-4 shrink-0 text-risk-warn" />
          )}
          <span className="truncate text-xs font-semibold text-ink">
            {path.label}
          </span>
          {path.is_mock && (
            <span className="shrink-0 rounded border border-risk-warn/35 px-1 py-0.5 text-[0.625rem] font-normal text-risk-warn">
              演示
            </span>
          )}
        </div>
        <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
          {path.latency_ms} ms
        </span>
      </div>

      <div className="flex flex-1 flex-col p-4">
        {skipped ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
            <MinusCircle className="h-5 w-5 text-ink-ghost" />
            <p className="text-xs font-semibold text-ink-muted">
              {path.status === 'failed' ? '调用失败' : '该路径未运行'}
            </p>
            <p className="max-w-xs text-[0.625rem] leading-relaxed text-ink-ghost">
              {path.note}
            </p>
          </div>
        ) : (
          <>
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-muted">
              {path.answer}
            </p>

            {!!path.citations.length && (
              <div className="mt-3 space-y-1.5 border-t border-line/60 pt-3">
                <p className="flex items-center gap-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-ink-ghost">
                  <BookOpen className="h-3 w-3" />
                  引用出处
                </p>
                {path.citations.map((c) => (
                  <details
                    key={c.index}
                    className="rounded-lg border border-line bg-canvas/50 px-3 py-2"
                  >
                    <summary className="flex cursor-pointer items-center gap-2 text-2xs text-ink-muted marker:content-none">
                      <span className="grid h-4 w-4 shrink-0 place-items-center rounded bg-brand-500/15 font-mono text-[0.625rem] text-brand-300">
                        {c.index}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{c.title}</span>
                      <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
                        {c.score.toFixed(3)}
                      </span>
                    </summary>
                    <p className="mt-2 border-t border-line/60 pt-2 text-[0.625rem] leading-relaxed text-ink-ghost">
                      <span className="font-mono text-ink-faint">{c.source}</span>
                      <br />
                      {c.snippet}
                    </p>
                  </details>
                ))}
              </div>
            )}

            <div className="mt-3 border-t border-line/60 pt-3">
              <p className="text-[0.625rem] leading-relaxed text-ink-ghost">
                {path.note}
              </p>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}
