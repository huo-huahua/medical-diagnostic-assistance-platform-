/** Shared domain types mirroring the backend Pydantic schemas. */

export type Disease = 'breast' | 'heart'

export interface Envelope<T> {
  code: number
  message: string
  data: T
  request_id: string
}

export interface User {
  id: number
  email: string
  display_name: string
  role: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface FeatureSpec {
  key: string
  order: number
  group: string
  group_zh: string
  group_en: string
  base: string
  name_zh: string
  name_en: string
  unit: string
  min: number
  max: number
  mean: number
}

export interface ConfusionMatrix {
  tn: number
  fp: number
  fn: number
  tp: number
}

export interface ModelTestMetrics {
  accuracy: number
  precision: number
  recall: number
  specificity: number
  f1: number
  roc_auc: number
  brier: number
  threshold: number
  confusion_matrix: ConfusionMatrix
}

export interface ModelInfo {
  id: string
  disease: string
  algorithm: string
  algorithm_zh: string
  version: string
  calibrated: boolean
  threshold: number
  cv: Record<string, number>
  test: ModelTestMetrics
}

export interface DiseaseInfo {
  disease: Disease
  display_zh: string
  display_en: string
  n_samples: number
  n_features: number
  positive_label_zh: string
  negative_label_zh: string
  class_balance: Record<string, number>
  feature_schema: FeatureSpec[]
  default_values: number[]
  models: ModelInfo[]
  champion: string
  champion_id: string
}

export interface FeatureContribution {
  key: string
  name_zh: string
  name_en: string
  group: string
  value: number
  contribution: number
  direction: 'positive' | 'negative' | 'neutral'
}

export interface Explanation {
  base_value: number
  contributions: FeatureContribution[]
  top_positive: FeatureContribution[]
  top_negative: FeatureContribution[]
  method: string
}

export type ConfidenceBand = 'very_high' | 'high' | 'moderate' | 'low'

export interface PredictResult {
  record_id: number | null
  disease: string
  model_id: string
  algorithm: string
  algorithm_zh: string
  verdict: 'positive' | 'negative'
  verdict_label: string
  positive_prob: number
  negative_prob: number
  threshold: number
  confidence_band: ConfidenceBand
  metrics: ModelTestMetrics
  explanation: Explanation | null
  narrative: string | null
  narrative_source: string | null
  elapsed_ms: number
  range_warnings?: string[]
  llm_cache_hit?: boolean
}

export interface Citation {
  index: number
  source: string
  title: string
  snippet: string
  score: number
}

export interface AskResult {
  conversation_id: number | null
  message_id: number | null
  answer: string
  citations: Citation[]
  refused: boolean
  source: 'knowledge_base' | 'llm_synthesis' | 'llm_enhanced' | 'refusal' | 'greeting'
  llm_used: boolean
  latency_ms: number
}

export interface RecordItem {
  id: number
  case_label: string | null
  disease: string
  model_id: string
  positive_prob: number
  negative_prob: number
  verdict: string
  threshold: number
  confidence_band: ConfidenceBand
  created_at: string
  elapsed_ms: number
  llm_used: boolean
}

export interface RecordDetail extends RecordItem {
  features: Record<string, number>
  contributions: FeatureContribution[] | null
}

export interface RecordPage {
  total: number
  page: number
  page_size: number
  items: RecordItem[]
}

export interface Stats {
  total_predictions: number
  by_disease: Record<string, number>
  positives: number
  negatives: number
  positive_rate: number
  llm_calls: number
  llm_cache_hits: number
  cache_hit_rate: number
  last_prediction_at: string | null
}

export interface LlmHealth {
  enabled: boolean
  configured: boolean
  available: boolean
  model: string | null
  api_calls_this_process: number
  total_prompt_tokens: number
  total_completion_tokens: number
  cache: {
    size: number
    maxsize: number
    hits_exact: number
    hits_semantic: number
    misses: number
    hit_rate: number
  }
}

export interface HealthResponse {
  status: string
  version: string
  environment: string
  rag_ready: boolean
  rag_chunks: number
  llm: LlmHealth
}

export interface Conversation {
  id: number
  title: string
  disease: string
  updated_at: string
}

/** Which answering pipeline produced a result in the comparison view. */
export type QaPathKey = 'local_rag' | 'llm_direct' | 'llm_rag'

export interface QaPathResult {
  key: QaPathKey | string
  label: string
  short: string
  description: string

  answer: string | null
  citations: Citation[]

  refused: boolean
  uses_retrieval: boolean
  external_call: boolean

  /** Which upstream produced this column. Empty for the purely local path. */
  provider: string
  model: string | null
  /** True when this answer came from the offline demo transport. */
  is_mock: boolean

  llm_used: boolean
  cache_hit: boolean
  prompt_tokens: number
  completion_tokens: number
  latency_ms: number
  cost_cny: number

  answer_chars: number
  lexical_overlap: number
  risk_phrases: string[]
  citation_count: number

  status: 'ok' | 'skipped' | 'failed'
  note: string
}

export interface QaCompareSummary {
  external_calls: number
  cache_hits: number
  prompt_tokens: number
  completion_tokens: number
  cost_cny: number
  grounded_paths: string[]
  ungrounded_paths: string[]
  llm_available: boolean
  /**
   * True when the external columns came from the in-process demo transport.
   * `external_calls` is still accurate — the SDK really ran — but nothing was
   * billed and nothing left the machine, so the UI must not claim otherwise.
   */
  demo_mode: boolean
  models: string[]
}

export interface QaCompareResult {
  question: string
  truncated: boolean
  disease: string
  refused: boolean
  top_score: number
  passage_count: number
  hit_count: number
  citations: Citation[]
  paths: QaPathResult[]
  /** The models actually run, after trimming, de-duplication and capping. */
  models: string[]
  provider: string
  summary: QaCompareSummary
  total_latency_ms: number
  comparison_id: number | null
}

export interface QaComparisonHistoryItem {
  id: number
  question: string
  disease: string
  refused: boolean
  external_calls: number
  cache_hits: number
  cost_cny: number
  total_latency_ms: number
  created_at: string
}

export interface DatasetSampleRow {
  case_label: string
  features: Record<string, number>
  /** Dataset's own label (0 = negative, 1 = positive), for reference only. */
  true_label?: number
}

export interface DatasetSampleSet {
  disease: string
  source: string
  note: string
  feature_keys: string[]
  positive_label_zh: string
  negative_label_zh: string
  rows: DatasetSampleRow[]
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  refused?: boolean
  source?: string
  llm_used?: boolean
  created_at?: string
  streaming?: boolean
}

// --------------------------------------------------------------------------- //
// LLM providers
// --------------------------------------------------------------------------- //

/** One entry of the public provider catalogue. Carries no credentials. */
export interface LlmProviderInfo {
  id: string
  label: string
  base_url: string
  default_model: string
  requires_key: boolean
  is_demo: boolean
  price_prompt_per_1k: number
  price_completion_per_1k: number
  console_url: string
  note: string
}

export interface LlmProviderCatalogue {
  providers: LlmProviderInfo[]
  active: string
  default: string
  /** Plain-language statement of which env var wins, which is not obvious. */
  override_rules: string
}

/** The provider actually in force, plus how the process is behaving. */
export interface LlmStatus {
  enabled: boolean
  configured: boolean
  available: boolean
  ready: boolean

  provider: string
  provider_label: string
  base_url: string
  model: string | null
  requires_key: boolean
  is_demo: boolean

  key_present: boolean
  /** The only representation of the key that ever leaves the server. */
  key_masked: string | null

  unknown_provider: string | null
  model_overridden: boolean
  base_url_overridden: boolean

  api_calls_this_process: number
  failures_this_process: number
  last_error: {
    kind: string
    message: string
    detail: string | null
    type: string
    purpose?: string
    model?: string
  } | null
  total_prompt_tokens: number
  total_completion_tokens: number
  max_compare_models: number
  /** Non-null only when the demo channel is deliberately failing. */
  mock_fault: string | null
  cache: LlmHealth['cache']
}

/** Outcome of one minimal real call to the configured provider. */
export interface LlmProbeResult {
  provider: string
  provider_label: string
  model: string
  base_url: string
  is_demo: boolean

  ok: boolean
  latency_ms: number
  reply: string
  prompt_tokens: number
  completion_tokens: number
  cost_cny: number

  /** Populated only on failure, with an actionable explanation. */
  error_kind: string | null
  error_message: string | null
  error_detail: string | null
}
