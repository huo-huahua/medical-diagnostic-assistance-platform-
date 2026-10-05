import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Cpu,
  ExternalLink,
  Info,
  KeyRound,
  Link2,
  Loader2,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, llmApi } from '@/api'
import { Panel, PanelHeader } from '@/components/ui'
import { useToast } from '@/components/Toast'
import type { LlmProbeResult, LlmStatus } from '@/types'

export const LLM_STATUS_KEY = ['llm-status'] as const

/**
 * Live state of the external-model connection, plus a button that proves it.
 *
 * Two things this panel exists to make impossible:
 *
 *  - **Guessing whether a key is configured.** `available: false` collapses
 *    "switched off on purpose", "no key" and "key present but the provider is
 *    unreachable" into one word. The three cases need different responses from
 *    the reader, so they get different labels here.
 *  - **Debugging a broken configuration through the comparison table.** The
 *    only feedback used to be "调用失败", which is the same string for an
 *    expired key, a base URL missing `/v1`, and a machine with no route to the
 *    provider. One 16-token probe names the actual problem.
 */
export default function LlmPanel({ compact = false }: { compact?: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [probe, setProbe] = useState<LlmProbeResult | null>(null)

  const status = useQuery({ queryKey: LLM_STATUS_KEY, queryFn: llmApi.status })
  const catalogue = useQuery({
    queryKey: ['llm-providers'],
    queryFn: llmApi.providers,
    staleTime: 5 * 60_000,
  })

  const test = useMutation({
    mutationFn: () => llmApi.test(),
    onSuccess: (data) => {
      setProbe(data)
      qc.invalidateQueries({ queryKey: LLM_STATUS_KEY })
      if (data.ok) {
        toast.success(
          '连接正常',
          `${data.provider_label} · ${data.model} · ${data.latency_ms} ms`,
        )
      } else {
        toast.error('连接失败', data.error_message ?? undefined)
      }
    },
    onError: (err) => {
      toast.error('测试请求失败', err instanceof ApiError ? err.message : '请稍后重试')
    },
  })

  const s = status.data
  const { tone, label } = describe(s)

  return (
    <Panel>
      <PanelHeader
        title="外部模型连接"
        icon={Cloud}
        subtitle="问答对比里的两条外部路径会发往这里配置的服务商。本地路径与它无关，始终离线运行。"
        actions={
          <div className="flex items-center gap-2">
            <span className={tone}>{label}</span>
            <button
              type="button"
              onClick={() => test.mutate()}
              disabled={test.isPending || status.isLoading}
              className="btn-primary h-8 px-3 text-2xs"
            >
              {test.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Link2 className="h-3.5 w-3.5" />
              )}
              测试连接
            </button>
          </div>
        }
      />

      <div className="space-y-4 p-5">
        {status.isLoading ? (
          <p className="text-xs text-ink-ghost">正在读取配置…</p>
        ) : status.isError ? (
          <p className="text-xs text-risk-warn">
            无法读取 LLM 状态：
            {status.error instanceof ApiError ? status.error.message : '请稍后重试'}
          </p>
        ) : s ? (
          <>
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="服务商" value={s.provider_label} mono={false} />
              <Field label="模型" value={s.model ?? '—'} mono />
              <Field
                label="密钥"
                value={
                  s.key_present
                    ? (s.key_masked ?? '已配置')
                    : s.requires_key
                      ? '未配置'
                      : '无需密钥'
                }
                mono
              />
              <Field
                label="接口地址"
                value={s.base_url || '—'}
                mono
                title={s.base_url}
              />
            </dl>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-2xs text-ink-ghost">
              <span>
                本进程外部调用 <span className="font-mono text-ink-muted">{s.api_calls_this_process}</span> 次
              </span>
              <span>
                失败 <span className="font-mono text-ink-muted">{s.failures_this_process}</span> 次
              </span>
              <span>
                Token 累计{' '}
                <span className="font-mono text-ink-muted">
                  {s.total_prompt_tokens + s.total_completion_tokens}
                </span>
              </span>
              <span>
                缓存命中{' '}
                <span className="font-mono text-ink-muted">
                  {s.cache.hits_exact + s.cache.hits_semantic}
                </span>
              </span>
            </div>

            {s.unknown_provider && (
              <Notice kind="warn">
                `LLM_PROVIDER` 的值 <code className="font-mono">{s.unknown_provider}</code>{' '}
                不是已知服务商，已回退到 {s.provider_label}。
              </Notice>
            )}

            {s.model_overridden && (
              <Notice kind="info">
                模型名被 <code className="font-mono">LLM_MODEL</code> 覆盖为{' '}
                <code className="font-mono">{s.model}</code>，没有使用该服务商的默认模型。
              </Notice>
            )}

            {s.mock_fault && (
              <Notice kind="warn">
                演示通道已开启<b>故障注入</b>（
                <code className="font-mono">LLM_MOCK_FAULT={s.mock_fault}</code>
                ）：所有演示调用都会按这个错误类型失败。这是为了让人能亲手复现错误分类，而不是只能看到成功。
                正常使用请清空该变量后重启后端。
              </Notice>
            )}

            {s.is_demo && (
              <Notice kind="warn">
                当前为<b>内置演示模型</b>：不联网、不产生费用，输出是本地生成的占位文本，
                <b>不是真实模型的回答</b>。用于离线演示三条链路的差异与整套指标，不可作为医学参考。
                要接入真实模型，在 <code className="font-mono">.env</code> 里设置{' '}
                <code className="font-mono">LLM_PROVIDER</code> 与{' '}
                <code className="font-mono">LLM_API_KEY</code> 后重启后端。
              </Notice>
            )}

            {!s.available && !s.is_demo && (
              <Notice kind="warn">
                {!s.enabled
                  ? '外部模型已被全局关闭（LLM_ENABLED=false）。'
                  : s.requires_key && !s.key_present
                    ? '尚未配置 API Key，两条外部路径不会发起任何请求，对比表里会显示为「未启用」。本地路径不受影响。'
                    : '配置不完整，外部路径当前不可用。'}
              </Notice>
            )}

            {probe && <ProbeResult result={probe} />}

            {s.last_error && !probe && (
              <Notice kind="warn">
                最近一次失败：{s.last_error.message}
                {s.last_error.detail && (
                  <span className="mt-1 block font-mono text-[0.625rem] text-ink-ghost">
                    {s.last_error.detail}
                  </span>
                )}
              </Notice>
            )}

            {!compact && catalogue.data && (
              <details className="rounded-xl border border-line bg-canvas/50">
                <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-ink-muted marker:content-none">
                  可接入的服务商（{catalogue.data.providers.length} 家）
                  <span className="ml-2 font-normal text-ink-ghost">
                    修改 .env 的 LLM_PROVIDER 后重启后端生效
                  </span>
                </summary>
                <div className="border-t border-line/70 px-4 py-3">
                  <p className="mb-3 text-2xs leading-relaxed text-ink-ghost">
                    {catalogue.data.override_rules}
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[640px] border-collapse text-2xs">
                      <thead>
                        <tr className="border-b border-line text-left text-ink-ghost">
                          <th className="py-2 pr-4 font-medium">服务商</th>
                          <th className="py-2 pr-4 font-medium">默认模型</th>
                          <th className="py-2 pr-4 font-medium">密钥</th>
                          <th className="py-2 pr-4 font-medium">价格（元/千 token）</th>
                          <th className="py-2 font-medium">说明</th>
                        </tr>
                      </thead>
                      <tbody>
                        {catalogue.data.providers.map((p) => (
                          <tr
                            key={p.id}
                            className={clsx(
                              'border-b border-line/50 align-top',
                              p.id === s.provider && 'bg-brand-500/8',
                            )}
                          >
                            <td className="py-2.5 pr-4">
                              <div className="flex items-center gap-1.5">
                                {p.id === s.provider && (
                                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand-400" />
                                )}
                                <span className="font-semibold text-ink">{p.label}</span>
                              </div>
                              <span className="mt-0.5 block font-mono text-[0.625rem] text-ink-ghost">
                                LLM_PROVIDER={p.id}
                              </span>
                              {p.console_url && (
                                <a
                                  href={p.console_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="mt-1 inline-flex items-center gap-1 text-[0.625rem] text-brand-300 hover:underline"
                                >
                                  获取密钥
                                  <ExternalLink className="h-2.5 w-2.5" />
                                </a>
                              )}
                            </td>
                            <td className="py-2.5 pr-4 font-mono text-ink-muted">
                              {p.default_model || '—'}
                            </td>
                            <td className="py-2.5 pr-4">
                              {p.requires_key ? (
                                <span className="text-ink-muted">需要</span>
                              ) : (
                                <span className="text-risk-low">不需要</span>
                              )}
                            </td>
                            <td className="py-2.5 pr-4 font-mono text-ink-muted">
                              {p.price_prompt_per_1k === 0 && p.price_completion_per_1k === 0
                                ? '免费'
                                : `${p.price_prompt_per_1k} / ${p.price_completion_per_1k}`}
                            </td>
                            <td className="py-2.5 leading-relaxed text-ink-faint">
                              {p.note}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </details>
            )}
          </>
        ) : null}
      </div>
    </Panel>
  )
}

/* -------------------------------------------------------------------------- */

function describe(s?: LlmStatus): { tone: string; label: string } {
  if (!s) return { tone: 'chip-neutral', label: '读取中' }
  if (s.is_demo) return { tone: 'chip-warn', label: '演示模式' }
  if (s.available) return { tone: 'chip-safe', label: '已就绪' }
  if (!s.enabled) return { tone: 'chip-neutral', label: '已关闭' }
  if (s.requires_key && !s.key_present) return { tone: 'chip-neutral', label: '未配置密钥' }
  return { tone: 'chip-neutral', label: '不可用' }
}

function Field({
  label,
  value,
  mono,
  title,
}: {
  label: string
  value: string
  mono?: boolean
  title?: string
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.625rem] font-semibold uppercase tracking-wider text-ink-ghost">
        {label}
      </dt>
      <dd
        title={title}
        className={clsx(
          'mt-1 truncate text-xs text-ink-muted',
          mono && 'font-mono text-[0.6875rem]',
        )}
      >
        {value}
      </dd>
    </div>
  )
}

function Notice({
  kind,
  children,
}: {
  kind: 'info' | 'warn'
  children: React.ReactNode
}) {
  const Icon = kind === 'warn' ? AlertTriangle : Info
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-2xs leading-relaxed',
        kind === 'warn'
          ? 'border-risk-warn/35 bg-risk-warnSoft/25 text-ink-muted'
          : 'border-line bg-canvas/50 text-ink-faint',
      )}
    >
      <Icon
        className={clsx(
          'mt-0.5 h-3.5 w-3.5 shrink-0',
          kind === 'warn' ? 'text-risk-warn' : 'text-ink-ghost',
        )}
      />
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function ProbeResult({ result }: { result: LlmProbeResult }) {
  return (
    <div
      className={clsx(
        'rounded-xl border px-4 py-3',
        result.ok
          ? 'border-risk-low/40 bg-risk-lowSoft/40'
          : 'border-risk-high/35 bg-risk-highSoft/30',
      )}
    >
      <p className="flex items-center gap-2 text-xs font-semibold">
        {result.ok ? (
          <>
            <CheckCircle2 className="h-4 w-4 text-risk-low" />
            <span className="text-risk-low">连接正常</span>
          </>
        ) : (
          <>
            <XCircle className="h-4 w-4 text-risk-high" />
            <span className="text-risk-high">连接失败</span>
            {result.error_kind && (
              <span className="rounded border border-risk-high/30 px-1.5 py-0.5 font-mono text-[0.625rem] font-normal text-risk-high">
                {result.error_kind}
              </span>
            )}
          </>
        )}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[0.625rem] text-ink-faint">
        <span>
          <Cpu className="mr-1 inline h-3 w-3" />
          {result.model}
        </span>
        <span>{result.latency_ms} ms</span>
        <span>
          token {result.prompt_tokens} + {result.completion_tokens}
        </span>
        <span>
          {result.cost_cny > 0 ? `预估 ¥${result.cost_cny.toFixed(6)}` : '本次不计费'}
        </span>
        {result.is_demo && (
          <span className="text-risk-warn">演示模型，未联网</span>
        )}
      </div>

      <p className="mt-2 text-2xs leading-relaxed text-ink-muted">
        {result.ok ? result.reply : result.error_message}
      </p>

      {!result.ok && result.error_detail && (
        <p className="mt-1.5 break-all font-mono text-[0.625rem] text-ink-ghost">
          服务端原始信息：{result.error_detail}
        </p>
      )}

      {result.ok && (
        <p className="mt-1.5 flex items-center gap-1 text-[0.625rem] text-ink-ghost">
          <KeyRound className="h-3 w-3" />
          极小的探活请求，用量已计入上面的累计数字
        </p>
      )}

      {result.is_demo && (
        <p className="mt-1.5 flex items-center gap-1 text-[0.625rem] text-risk-warn">
          <ShieldCheck className="h-3 w-3" />
          以上内容由本地代码生成，不是语言模型的回答
        </p>
      )}
    </div>
  )
}
