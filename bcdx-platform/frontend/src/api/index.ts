import axios, { AxiosError } from 'axios'

import type {
  AskResult,
  ConfidenceBand,
  Conversation,
  DatasetSampleSet,
  Disease,
  DiseaseInfo,
  Envelope,
  HealthResponse,
  LlmProbeResult,
  LlmProviderCatalogue,
  LlmStatus,
  PredictResult,
  QaComparisonHistoryItem,
  QaCompareResult,
  QaPathKey,
  QaPathResult,
  RecordDetail,
  RecordPage,
  Stats,
  TokenResponse,
  User,
} from '@/types'

const TOKEN_KEY = 'bcdx.token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** Normalised error surfaced to the UI. */
export class ApiError extends Error {
  code: number
  requestId?: string
  status?: number

  constructor(message: string, code: number, status?: number, requestId?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.requestId = requestId
  }
}

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

/** Minimal shape of whatever the server sent on a non-2xx response. */
type ErrorBody = {
  code?: number
  message?: string
  request_id?: string
  /** FastAPI's own validation shape: `{loc, msg, type}[]` or a plain string. */
  detail?: unknown
}

/**
 * Best available explanation from an error body.
 *
 * The backend answers every `/api/v1` error with `{code, message, data}`, so
 * `message` is normally all we need. The other branches exist so that a
 * response which *didn't* go through the envelope handler (a proxy error page,
 * an older backend, a bare FastAPI validation error) still says something
 * actionable instead of collapsing into a useless "请求失败".
 */
function explain(body: ErrorBody | undefined, error: AxiosError): string {
  if (body?.message) return body.message

  const detail = body?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { loc?: unknown[]; msg?: string }
    const field = (first?.loc ?? []).filter((p) => p !== 'body').join('.')
    const msg = first?.msg ?? 'invalid value'
    return field ? `${field}: ${msg}` : String(msg)
  }

  if (error.code === 'ECONNABORTED') return '请求超时，请检查后端服务是否运行'
  if (error.message === 'Network Error') {
    return '无法连接后端服务，请确认 api 已在 127.0.0.1:8000 启动'
  }
  return `请求失败（HTTP ${error.response?.status ?? '无响应'}）`
}

http.interceptors.response.use(
  (res) => res,
  (error: AxiosError<ErrorBody>) => {
    const status = error.response?.status
    const body = error.response?.data

    // 401 -> clear the session and bounce to sign-in.
    if (status === 401) {
      tokenStore.clear()
      onUnauthorized?.()
    }

    return Promise.reject(
      new ApiError(explain(body, error), body?.code ?? status ?? 0, status, body?.request_id),
    )
  },
)

/** Unwrap the standard {code, message, data} envelope. */
async function unwrap<T>(promise: Promise<{ data: Envelope<T> }>): Promise<T> {
  const res = await promise
  return res.data.data
}

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //

export const authApi = {
  register: (payload: { email: string; display_name: string; password: string }) =>
    unwrap<TokenResponse>(http.post('/auth/register', payload)),

  login: (payload: { email: string; password: string }) =>
    unwrap<TokenResponse>(http.post('/auth/login', payload)),

  me: () => unwrap<User>(http.get('/auth/me')),
}

// --------------------------------------------------------------------------- //
// Models
// --------------------------------------------------------------------------- //

export const modelApi = {
  list: () => unwrap<DiseaseInfo[]>(http.get('/models')),
  get: (disease: Disease) => unwrap<DiseaseInfo>(http.get(`/models/${disease}`)),
  metrics: (disease: Disease, algo: string) =>
    unwrap<Record<string, unknown>>(http.get(`/models/${disease}/${algo}/metrics`)),
}

// --------------------------------------------------------------------------- //
// Prediction
// --------------------------------------------------------------------------- //

export interface PredictPayload {
  disease: Disease
  model?: string | null
  features: number[]
  case_label?: string | null
  persist?: boolean
  with_explanation?: boolean
  with_narrative?: boolean
}

export const predictApi = {
  run: (payload: PredictPayload) => unwrap<PredictResult>(http.post('/predict', payload)),

  batch: (payload: {
    disease: Disease
    model?: string | null
    rows: Record<string, number>[]
  }) =>
    unwrap<{
      disease: string
      model_id: string
      /** Champion thresholds are not 0.5 — the UI must display this value. */
      threshold: number
      count: number
      positives: number
      negatives: number
      mean_positive_prob: number
      results: Array<{
        row: number
        verdict: string
        verdict_label: string
        positive_prob: number
        confidence_band: ConfidenceBand
      }>
    }>(http.post('/predict/batch', payload)),

  /**
   * Real rows from the public dataset, for the batch page's demo batch.
   * Synthesising feature values in the browser produced a systematically
   * biased batch, so the demo loads actual specimens instead.
   */
  samples: (params: {
    disease: Disease
    n?: number
    seed?: number
    balanced?: boolean
  }) => unwrap<DatasetSampleSet>(http.get('/predict/samples', { params })),
}

// --------------------------------------------------------------------------- //
// RAG
// --------------------------------------------------------------------------- //

export const ragApi = {
  ask: (payload: {
    question: string
    disease: Disease
    conversation_id?: number | null
    use_llm?: boolean
  }) => unwrap<AskResult>(http.post('/rag/ask', payload)),

  conversations: () => unwrap<Conversation[]>(http.get('/rag/conversations')),

  conversation: (id: number) =>
    unwrap<{
      id: number
      title: string
      disease: string
      messages: Array<{
        id: number
        role: 'user' | 'assistant'
        content: string
        citations: import('@/types').Citation[] | null
        llm_used: boolean
        created_at: string
      }>
    }>(http.get(`/rag/conversations/${id}`)),

  remove: (id: number) => unwrap<{ deleted: number }>(http.delete(`/rag/conversations/${id}`)),

  sources: () =>
    unwrap<Array<{ source: string; entries: string[]; count: number }>>(
      http.get('/rag/sources'),
    ),

  usage: () => unwrap<HealthResponse['llm']>(http.get('/rag/usage')),

  // --- Q&A path comparison ---
  // Opt-in and billed: only call this when the user explicitly asks for it.
  compare: (payload: {
    question: string
    disease: Disease
    paths?: QaPathKey[]
    /** Runs the two external paths once per model, as `llm_direct@<model>`. */
    models?: string[]
    persist?: boolean
  }) => unwrap<QaCompareResult>(http.post('/rag/compare', payload)),

  comparisons: () =>
    unwrap<QaComparisonHistoryItem[]>(http.get('/rag/comparisons')),

  comparison: (id: number) =>
    unwrap<{
      id: number
      question: string
      disease: string
      refused: boolean
      top_score: number
      passage_count: number
      answer_local: string | null
      answer_llm_direct: string | null
      answer_llm_rag: string | null
      path_metrics: QaPathResult[] | null
      external_calls: number
      cache_hits: number
      prompt_tokens: number
      completion_tokens: number
      cost_cny: number
      total_latency_ms: number
      created_at: string
    }>(http.get(`/rag/comparisons/${id}`)),

  removeComparison: (id: number) =>
    unwrap<{ deleted: number }>(http.delete(`/rag/comparisons/${id}`)),

  /**
   * SSE streaming Q&A.
   *
   * Uses fetch rather than EventSource because we must send an Authorization
   * header and a JSON body, neither of which EventSource supports.
   */
  askStream: async (
    payload: { question: string; disease: Disease; conversation_id?: number | null },
    handlers: {
      onMeta?: (meta: Record<string, unknown>) => void
      onDelta?: (text: string) => void
      onDone?: () => void
      onError?: (message: string) => void
    },
    signal?: AbortSignal,
  ): Promise<void> => {
    const token = tokenStore.get()
    try {
      const res = await fetch('/api/v1/rag/ask/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
        signal,
      })

      if (!res.ok || !res.body) {
        let msg = '流式请求失败'
        try {
          const j = await res.json()
          msg = j?.message || msg
        } catch {
          /* response had no JSON body */
        }
        handlers.onError?.(msg)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line.
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          if (!frame.trim()) continue
          let event = 'message'
          let data = ''
          for (const line of frame.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) data += line.slice(5).trim()
          }
          if (!data) continue

          try {
            const parsed = JSON.parse(data)
            if (event === 'meta') handlers.onMeta?.(parsed)
            else if (event === 'delta') handlers.onDelta?.(parsed.text ?? '')
            else if (event === 'done') handlers.onDone?.()
          } catch {
            /* ignore malformed frame */
          }
        }
      }
      handlers.onDone?.()
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      handlers.onError?.((err as Error).message)
    }
  },
}

// --------------------------------------------------------------------------- //
// Records / stats
// --------------------------------------------------------------------------- //

export const recordApi = {
  list: (params: { page?: number; page_size?: number; disease?: string; verdict?: string }) =>
    unwrap<RecordPage>(http.get('/records', { params })),

  detail: (id: number) => unwrap<RecordDetail>(http.get(`/records/${id}`)),

  remove: (id: number) => unwrap<{ deleted: number }>(http.delete(`/records/${id}`)),

  stats: () => unwrap<Stats>(http.get('/records/stats')),
}

// --------------------------------------------------------------------------- //
// LLM providers
// --------------------------------------------------------------------------- //

export const llmApi = {
  /** The catalogue is public; it is what the picker is built from. */
  providers: () => unwrap<LlmProviderCatalogue>(http.get('/llm/providers')),

  /** Which provider is in force, with the key masked. Requires a login. */
  status: () => unwrap<LlmStatus>(http.get('/llm/status')),

  /**
   * One minimal real call, to find out whether the configuration works before
   * a comparison burns tokens discovering the same thing less clearly.
   */
  test: () => unwrap<LlmProbeResult>(http.post('/llm/test')),
}

// --------------------------------------------------------------------------- //
// Meta
// --------------------------------------------------------------------------- //

export const metaApi = {
  health: async (): Promise<HealthResponse> => {
    // /health lives outside the versioned prefix.
    const res = await axios.get<HealthResponse>('/health', { timeout: 8000 })
    return res.data
  },
  limits: () => unwrap<Record<string, unknown>>(http.get('/meta/limits')),
}
