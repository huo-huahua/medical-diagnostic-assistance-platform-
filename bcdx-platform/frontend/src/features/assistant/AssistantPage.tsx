import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpen,
  Bot,
  ChevronDown,
  Database,
  Info,
  Loader2,
  MessageSquarePlus,
  MessagesSquare,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  User as UserIcon,
  Zap,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, ragApi } from '@/api'
import { useWorkspace } from '@/lib/store'
import { formatRelative } from '@/lib/format'
import { LoadingBlock, Panel, PanelHeader } from '@/components/ui'
import { useToast } from '@/components/Toast'
import type { ChatMessage, Citation, Disease } from '@/types'

const SUGGESTIONS: Record<Disease, string[]> = {
  breast: [
    '乳腺癌的早期症状有哪些？',
    '乳腺钼靶和超声有什么区别？',
    'BI-RADS 分级是什么意思？',
    '如何预防乳腺癌？',
  ],
  heart: [
    '冠心病如何诊断？',
    '心肌梗死有哪些典型症状？',
    '高血压与心脏病有什么关系？',
    '心电图能查出哪些心脏问题？',
  ],
}

export default function AssistantPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const { diseases, activeDisease, setActiveDisease, loadDiseases } = useWorkspace()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [useLlm, setUseLlm] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    loadDiseases().catch(() => {})
  }, [loadDiseases])

  const sources = useQuery({ queryKey: ['rag-sources'], queryFn: ragApi.sources })
  const usage = useQuery({ queryKey: ['rag-usage'], queryFn: ragApi.usage })
  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: ragApi.conversations,
  })

  // Keep the transcript pinned to the newest message.
  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages])

  const activeDiseaseName =
    diseases.find((d) => d.disease === activeDisease)?.display_zh ??
    (activeDisease === 'heart' ? '心脏病' : '乳腺癌')

  const ask = useMutation({
    mutationFn: async (question: string) => {
      const userMsg: ChatMessage = { role: 'user', content: question }
      const placeholder: ChatMessage = {
        role: 'assistant',
        content: '',
        streaming: true,
      }
      setMessages((m) => [...m, userMsg, placeholder])
      setStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      let meta: Record<string, unknown> | null = null
      let text = ''

      await ragApi.askStream(
        {
          question,
          disease: activeDisease,
          conversation_id: conversationId,
        },
        {
          onMeta: (m) => {
            meta = m
            setConversationId((m.conversation_id as number) ?? null)
            setMessages((msgs) => {
              const copy = [...msgs]
              const last = copy[copy.length - 1]
              if (last?.role === 'assistant') {
                copy[copy.length - 1] = {
                  ...last,
                  citations: (m.citations as Citation[]) ?? [],
                  refused: Boolean(m.refused),
                  source: m.source as string,
                  llm_used: Boolean(m.llm_used),
                }
              }
              return copy
            })
          },
          onDelta: (chunk) => {
            text += chunk
            setMessages((msgs) => {
              const copy = [...msgs]
              const last = copy[copy.length - 1]
              if (last?.role === 'assistant') {
                copy[copy.length - 1] = { ...last, content: text }
              }
              return copy
            })
          },
          onDone: () => {
            setMessages((msgs) => {
              const copy = [...msgs]
              const last = copy[copy.length - 1]
              if (last?.role === 'assistant') {
                copy[copy.length - 1] = { ...last, streaming: false }
              }
              return copy
            })
          },
          onError: (msg) => {
            throw new ApiError(msg, 0)
          },
        },
        controller.signal,
      )

      return { meta, text }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] })
      qc.invalidateQueries({ queryKey: ['rag-usage'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : '提问失败'
      toast.error('问答失败', msg)
      // Drop the in-flight placeholder so the transcript stays honest.
      setMessages((msgs) => {
        const copy = [...msgs]
        const last = copy[copy.length - 1]
        if (last?.role === 'assistant' && !last.content) copy.pop()
        else if (last?.role === 'assistant')
          copy[copy.length - 1] = { ...last, streaming: false }
        return copy
      })
    },
    onSettled: () => {
      setStreaming(false)
      abortRef.current = null
    },
  })

  const submit = (text?: string) => {
    const question = (text ?? input).trim()
    if (!question || streaming) return
    setInput('')
    ask.mutate(question)
  }

  const newChat = () => {
    abortRef.current?.abort()
    setMessages([])
    setConversationId(null)
  }

  const openConversation = async (id: number) => {
    try {
      const convo = await ragApi.conversation(id)
      setConversationId(convo.id)
      setActiveDisease(convo.disease as Disease)
      setMessages(
        convo.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          citations: m.citations ?? [],
          llm_used: m.llm_used,
          created_at: m.created_at,
        })),
      )
    } catch (err) {
      toast.error('读取失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  const removeConversation = async (id: number) => {
    try {
      await ragApi.remove(id)
      qc.invalidateQueries({ queryKey: ['conversations'] })
      if (conversationId === id) newChat()
      toast.success('已删除会话')
    } catch (err) {
      toast.error('删除失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  const suggestions = SUGGESTIONS[activeDisease]
  const kbEntries = useMemo(
    () => (sources.data ?? []).reduce((n, s) => n + s.count, 0),
    [sources.data],
  )

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
            Assistant
          </p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            医学问答
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-ink-muted">
            基于本地知识库的检索增强问答。默认完全离线运行，
            所有回答都附带可核查的原文出处。
          </p>
        </div>
        <button type="button" onClick={newChat} className="btn-ghost">
          <MessageSquarePlus className="h-4 w-4" />
          新建对话
        </button>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
        {/* ------------------------------ chat ------------------------------ */}
        <Panel className="flex min-h-[620px] flex-col overflow-hidden">
          <PanelHeader
            title="对话"
            icon={MessagesSquare}
            subtitle={`当前作用域：${activeDiseaseName}知识库 —— 不同病种内容严格隔离`}
            actions={
              <label
                className={clsx(
                  'flex items-center gap-2 rounded-lg border px-2.5 py-1.5',
                  useLlm
                    ? 'border-risk-warn/40 bg-risk-warnSoft/40'
                    : 'border-line-strong bg-canvas-raised/60',
                )}
                title="开启后会调用外部语言模型润色回答，可能产生费用"
              >
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(e) => setUseLlm(e.target.checked)}
                  className="h-3.5 w-3.5 cursor-pointer accent-risk-warn"
                />
                <span className="text-2xs font-semibold text-ink-muted">
                  外部模型增强
                </span>
              </label>
            }
          />

          {/* transcript */}
          <div
            ref={scroller}
            className="scroll-area flex-1 space-y-5 bg-canvas/30 p-5"
          >
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-5 py-10">
                <div className="grid h-14 w-14 place-items-center rounded-2xl border border-brand-500/25 bg-brand-500/10">
                  <Bot className="h-6 w-6 text-brand-300" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-ink">
                    向 {activeDiseaseName}知识库提问
                  </p>
                  <p className="mt-1 max-w-md text-xs leading-relaxed text-ink-faint">
                    答案从本地整理的 {kbEntries} 条医学知识片段中检索生成。
                    超出知识库范围的问题会被明确拒答，而不是编造内容。
                  </p>
                </div>
                <div className="grid w-full max-w-lg gap-2 sm:grid-cols-2">
                  {suggestions.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => submit(s)}
                      className="rounded-xl border border-line bg-canvas-raised/50 px-3.5 py-2.5 text-left text-xs leading-relaxed text-ink-muted transition-all duration-150 hover:border-brand-500/40 hover:bg-brand-500/8 hover:text-ink"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => <Bubble key={i} message={m} />)
            )}
          </div>

          {/* composer */}
          <div className="border-t border-line/70 bg-canvas-soft/70 p-4">
            <div className="flex items-end gap-2.5">
              <div className="relative flex-1">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      submit()
                    }
                  }}
                  rows={1}
                  maxLength={1000}
                  placeholder={`输入关于${activeDiseaseName}的问题，Enter 发送 / Shift+Enter 换行`}
                  className="field max-h-32 min-h-[46px] resize-none py-3 font-sans leading-relaxed"
                  disabled={streaming}
                />
                <span className="pointer-events-none absolute bottom-1.5 right-3 font-mono text-[0.625rem] text-ink-ghost">
                  {input.length}/1000
                </span>
              </div>
              <button
                type="button"
                onClick={() => submit()}
                disabled={!input.trim() || streaming}
                className="btn-primary h-[46px] shrink-0 px-4"
              >
                {streaming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </button>
            </div>
            <p className="mt-2 flex items-center gap-1.5 text-[0.625rem] text-ink-ghost">
              <ShieldCheck className="h-3 w-3" />
              检索与回答默认在本地完成，不发送任何数据到外部服务。
            </p>
          </div>
        </Panel>

        {/* ---------------------------- side rail ---------------------------- */}
        <div className="space-y-6">
          {/* scope */}
          <Panel>
            <PanelHeader title="检索范围" icon={Database} />
            <div className="space-y-3 p-4">
              <div className="grid grid-cols-2 gap-1.5">
                {(['breast', 'heart'] as Disease[]).map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => {
                      setActiveDisease(d)
                      newChat()
                    }}
                    className={clsx(
                      'rounded-lg border px-2 py-2 text-2xs font-semibold transition-all',
                      activeDisease === d
                        ? 'border-brand-500/50 bg-brand-500/12 text-brand-200'
                        : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:text-ink-muted',
                    )}
                  >
                    {d === 'breast' ? '乳腺癌' : '心脏病'}
                  </button>
                ))}
              </div>
              <p className="text-[0.625rem] leading-relaxed text-ink-ghost">
                切换范围会开启新对话。系统只会检索当前病种的知识片段，
                避免跨病种内容混淆。
              </p>
            </div>
          </Panel>

          {/* usage */}
          <Panel>
            <PanelHeader title="调用状况" icon={Zap} />
            <div className="p-4">
              {usage.isLoading ? (
                <LoadingBlock rows={2} />
              ) : usage.data ? (
                <div className="space-y-2.5">
                  {[
                    {
                      k: '外部调用',
                      v: usage.data.api_calls_this_process,
                      tone: usage.data.api_calls_this_process === 0 ? 'safe' : 'warn',
                    },
                    {
                      k: '缓存命中',
                      v:
                        usage.data.cache.hits_exact +
                        usage.data.cache.hits_semantic,
                      tone: 'brand',
                    },
                    {
                      k: '未命中',
                      v: usage.data.cache.misses,
                      tone: 'neutral',
                    },
                  ].map(({ k, v, tone }) => (
                    <div
                      key={k}
                      className="flex items-center justify-between rounded-lg border border-line bg-canvas/60 px-3 py-2"
                    >
                      <span className="text-2xs text-ink-muted">{k}</span>
                      <span
                        className={clsx(
                          'font-mono text-xs font-semibold',
                          tone === 'safe'
                            ? 'text-risk-low'
                            : tone === 'warn'
                              ? 'text-risk-warn'
                              : tone === 'brand'
                                ? 'text-brand-300'
                                : 'text-ink-muted',
                        )}
                      >
                        {v}
                      </span>
                    </div>
                  ))}
                  <p className="text-[0.625rem] leading-relaxed text-ink-ghost">
                    {usage.data.configured
                      ? `已配置外部模型：${usage.data.model}`
                      : '未配置外部模型 —— 所有回答都来自本地知识库与模板'}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-ink-faint">无法读取</p>
              )}
            </div>
          </Panel>

          {/* knowledge sources */}
          <Panel>
            <PanelHeader
              title="知识来源"
              icon={BookOpen}
              subtitle={`${kbEntries} 条片段`}
            />
            {sources.isLoading ? (
              <LoadingBlock rows={3} />
            ) : (
              <ul className="max-h-72 divide-y divide-line/60 overflow-y-auto scroll-area">
                {sources.data?.map((s) => (
                  <li key={s.source} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate font-mono text-2xs font-semibold text-ink-muted">
                        {s.source}
                      </p>
                      <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
                        {s.count}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[0.625rem] leading-relaxed text-ink-ghost">
                      {s.entries.slice(0, 3).join(' · ')}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {/* history */}
          <Panel>
            <PanelHeader title="历史对话" icon={MessagesSquare} />
            {conversations.isLoading ? (
              <LoadingBlock rows={3} />
            ) : !conversations.data?.length ? (
              <p className="px-4 py-6 text-center text-2xs text-ink-ghost">
                还没有对话记录
              </p>
            ) : (
              <ul className="max-h-64 divide-y divide-line/60 overflow-y-auto scroll-area">
                {conversations.data.map((c) => (
                  <li key={c.id} className="group flex items-center gap-2 px-3 py-2.5">
                    <button
                      type="button"
                      onClick={() => openConversation(c.id)}
                      className={clsx(
                        'min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left transition-colors',
                        conversationId === c.id
                          ? 'bg-brand-500/12'
                          : 'hover:bg-canvas-hover/60',
                      )}
                    >
                      <p className="truncate text-2xs font-medium text-ink-muted">
                        {c.title}
                      </p>
                      <p className="mt-0.5 text-[0.625rem] text-ink-ghost">
                        {formatRelative(c.updated_at)}
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => removeConversation(c.id)}
                      aria-label="删除会话"
                      className="shrink-0 rounded-md p-1.5 text-ink-ghost opacity-0 transition-all hover:text-risk-high group-hover:opacity-100"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'

  return (
    <div
      className={clsx(
        'flex gap-3',
        isUser ? 'flex-row-reverse' : 'flex-row',
        'animate-fade-up',
      )}
    >
      <div
        className={clsx(
          'grid h-8 w-8 shrink-0 place-items-center rounded-xl border',
          isUser
            ? 'border-line-strong bg-canvas-raised'
            : 'border-brand-500/30 bg-brand-500/10',
        )}
      >
        {isUser ? (
          <UserIcon className="h-3.5 w-3.5 text-ink-muted" />
        ) : (
          <Bot className="h-3.5 w-3.5 text-brand-300" />
        )}
      </div>

      <div className={clsx('min-w-0 max-w-[85%]', isUser && 'flex flex-col items-end')}>
        <div
          className={clsx(
            'rounded-2xl border px-4 py-3',
            isUser
              ? 'border-line-strong bg-canvas-raised/80'
              : message.refused
                ? 'border-risk-warn/35 bg-risk-warnSoft/35'
                : 'border-line bg-canvas-soft/80',
          )}
        >
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-muted">
            {message.content || (
              <span className="inline-flex items-center gap-2 text-ink-faint">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-500/30 border-t-brand-400" />
                正在检索知识库…
              </span>
            )}
          </p>

          {/* citations */}
          {!isUser && !!message.citations?.length && (
            <div className="mt-3 space-y-1.5 border-t border-line/60 pt-3">
              <p className="flex items-center gap-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-ink-ghost">
                <BookOpen className="h-3 w-3" />
                引用出处
              </p>
              {message.citations.map((c) => (
                <details
                  key={c.index}
                  className="group rounded-lg border border-line bg-canvas/50 px-3 py-2"
                >
                  <summary className="flex cursor-pointer items-center gap-2 text-2xs text-ink-muted marker:content-none">
                    <span className="grid h-4 w-4 shrink-0 place-items-center rounded bg-brand-500/15 font-mono text-[0.625rem] text-brand-300">
                      {c.index}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{c.title}</span>
                    <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
                      {c.score.toFixed(3)}
                    </span>
                    <ChevronDown className="h-3 w-3 shrink-0 text-ink-ghost transition-transform group-open:rotate-180" />
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
        </div>

        {!isUser && !message.streaming && (
          <div className="mt-1.5 flex items-center gap-2 px-1">
            {message.refused ? (
              <span className="chip-warn">
                <Info className="h-3 w-3" />
                超出知识库范围，已拒答
              </span>
            ) : (
              <span className="chip-neutral">
                <Sparkles className="h-3 w-3" />
                {message.llm_used ? '外部模型增强' : '本地知识库'}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
