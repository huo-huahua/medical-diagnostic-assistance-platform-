"""Pydantic v2 request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Disease = Literal["breast", "heart"]


class Envelope(BaseModel):
    """Uniform response envelope: {code, message, data, request_id}."""

    code: int = 0
    message: str = "ok"
    data: Any = None
    request_id: str = "-"


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("display_name")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Display name cannot be empty")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.isdigit() or v.isalpha():
            raise ValueError("Password must mix letters and digits")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------- #
# Models / registry
# --------------------------------------------------------------------------- #

class FeatureSpec(BaseModel):
    key: str
    order: int
    group: str
    group_zh: str
    group_en: str
    base: str
    name_zh: str
    name_en: str
    unit: str
    min: float
    max: float
    mean: float


class ModelMetricsOut(BaseModel):
    accuracy: float
    precision: float
    recall: float
    specificity: float
    f1: float
    roc_auc: float
    brier: float
    threshold: float
    confusion_matrix: dict[str, int]


class ModelInfoOut(BaseModel):
    id: str
    disease: str
    algorithm: str
    algorithm_zh: str
    version: str
    calibrated: bool
    threshold: float
    cv: dict[str, float]
    test: ModelMetricsOut


class DiseaseInfoOut(BaseModel):
    disease: str
    display_zh: str
    display_en: str
    n_samples: int
    n_features: int
    positive_label_zh: str
    negative_label_zh: str
    class_balance: dict[str, int]
    feature_schema: list[FeatureSpec]
    default_values: list[float]
    models: list[ModelInfoOut]
    champion: str
    champion_id: str


# --------------------------------------------------------------------------- #
# Predict / explain
# --------------------------------------------------------------------------- #

class PredictRequest(BaseModel):
    disease: Disease = "breast"
    model: str | None = Field(default=None, description="Algorithm key; defaults to champion")
    features: list[float] = Field(min_length=1)
    case_label: str | None = Field(default=None, max_length=80)
    persist: bool = True
    with_explanation: bool = True
    with_narrative: bool = False


class FeatureContribution(BaseModel):
    key: str
    name_zh: str
    name_en: str
    group: str
    value: float
    contribution: float
    direction: Literal["positive", "negative", "neutral"]


class ExplanationOut(BaseModel):
    base_value: float
    contributions: list[FeatureContribution]
    top_positive: list[FeatureContribution]
    top_negative: list[FeatureContribution]
    method: str


class PredictResponse(BaseModel):
    record_id: int | None = None
    disease: str
    model_id: str
    algorithm: str
    algorithm_zh: str
    verdict: str
    verdict_label: str
    positive_prob: float
    negative_prob: float
    threshold: float
    confidence_band: str
    metrics: ModelMetricsOut
    explanation: ExplanationOut | None = None
    narrative: str | None = None
    narrative_source: str | None = None
    elapsed_ms: int


class BatchPredictRequest(BaseModel):
    disease: Disease = "breast"
    model: str | None = None
    rows: list[dict[str, float]] = Field(min_length=1, max_length=500)


class BatchPredictResponse(BaseModel):
    disease: str
    model_id: str
    # Exposed because the champion threshold is NOT 0.5 (breast screening uses
    # 0.1701), so a reader comparing a probability to a personal 50% rule of
    # thumb would misread every row.
    threshold: float
    count: int
    positives: int
    negatives: int
    mean_positive_prob: float
    results: list[dict[str, Any]]


# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #

class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    disease: Disease = "breast"
    conversation_id: int | None = None
    use_llm: bool = False


class Citation(BaseModel):
    index: int
    source: str
    title: str
    snippet: str
    score: float


class AskResponse(BaseModel):
    conversation_id: int | None
    message_id: int | None
    answer: str
    citations: list[Citation]
    refused: bool
    source: Literal["knowledge_base", "llm_synthesis", "llm_enhanced", "refusal",
                    "greeting"]
    llm_used: bool
    latency_ms: int


# --------------------------------------------------------------------------- #
# Q&A path comparison
# --------------------------------------------------------------------------- #

QaPathKey = Literal["local_rag", "llm_direct", "llm_rag"]


class QaCompareRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    disease: Disease = "breast"
    # Omit to run every path. Kept explicit so a caller can pay for just one.
    paths: list[QaPathKey] | None = None
    # Ask several models the same question, producing `llm_direct@<model>` and
    # `llm_rag@<model>` columns. Omit (or leave empty) to use the single
    # configured model, which is the cheaper default and the old behaviour.
    models: list[str] | None = None
    persist: bool = True


class QaPathResult(BaseModel):
    key: str
    label: str
    short: str
    description: str

    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)

    refused: bool = False
    uses_retrieval: bool = False
    external_call: bool = False

    # Which upstream produced this column. Empty for the local path, which has
    # no upstream; `is_mock` marks the offline demo transport so a reader is
    # never left guessing whether a number came from a real model.
    provider: str = ""
    model: str | None = None
    is_mock: bool = False

    llm_used: bool = False
    cache_hit: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_cny: float = 0.0

    answer_chars: int = 0
    lexical_overlap: float = 0.0
    risk_phrases: list[str] = Field(default_factory=list)
    citation_count: int = 0

    status: Literal["ok", "skipped", "failed"] = "ok"
    note: str = ""


class QaCompareSummary(BaseModel):
    external_calls: int
    cache_hits: int
    prompt_tokens: int
    completion_tokens: int
    cost_cny: float
    grounded_paths: list[str]
    ungrounded_paths: list[str]
    llm_available: bool
    #: True when the external columns came from the in-process demo transport.
    #: `external_calls` is still accurate — the SDK really ran — but nothing was
    #: billed and nothing left the machine, so the UI must not claim otherwise.
    demo_mode: bool = False
    models: list[str] = Field(default_factory=list)


class QaCompareResponse(BaseModel):
    question: str
    truncated: bool = False
    disease: str
    refused: bool
    top_score: float
    passage_count: int
    hit_count: int
    citations: list[Citation]
    paths: list[QaPathResult]
    #: The models actually run (after trimming, de-duplication and capping), so
    #: a dropped entry is visible rather than silently missing a column.
    models: list[str] = Field(default_factory=list)
    provider: str = ""
    summary: QaCompareSummary
    total_latency_ms: int
    comparison_id: int | None = None


class QaComparisonHistoryItem(BaseModel):
    id: int
    question: str
    disease: str
    refused: bool
    external_calls: int
    cost_cny: float
    created_at: datetime


# --------------------------------------------------------------------------- #
# LLM providers
# --------------------------------------------------------------------------- #

class LlmProviderInfo(BaseModel):
    """One entry of the public provider catalogue. Carries no credentials."""

    id: str
    label: str
    base_url: str
    default_model: str
    requires_key: bool
    is_demo: bool
    price_prompt_per_1k: float
    price_completion_per_1k: float
    console_url: str
    note: str


class LlmStatus(BaseModel):
    """The provider actually in force, plus how the process is behaving.

    `key_masked` is the only representation of the credential that ever leaves
    the server; the full value is never serialised, logged, or returned.
    """

    enabled: bool
    configured: bool
    available: bool
    ready: bool

    provider: str
    provider_label: str
    base_url: str
    model: str | None
    requires_key: bool
    is_demo: bool

    key_present: bool
    key_masked: str | None

    unknown_provider: str | None
    model_overridden: bool
    base_url_overridden: bool

    api_calls_this_process: int
    failures_this_process: int
    last_error: dict[str, Any] | None
    total_prompt_tokens: int
    total_completion_tokens: int
    max_compare_models: int
    #: Non-null only when the demo channel is deliberately failing
    #: (`LLM_MOCK_FAULT`). Never set for a real provider.
    mock_fault: str | None = None
    cache: dict[str, Any]


class LlmProbeResult(BaseModel):
    """Outcome of one minimal real call to the configured provider."""

    provider: str
    provider_label: str
    model: str
    base_url: str
    is_demo: bool

    ok: bool
    latency_ms: int
    reply: str
    prompt_tokens: int
    completion_tokens: int
    cost_cny: float

    # Populated only on failure. `error_kind` is one of the keys documented in
    # `services.llm_providers.ERROR_KINDS`, and `error_message` is the
    # actionable Chinese explanation for it.
    error_kind: str | None = None
    error_message: str | None = None
    error_detail: str | None = None


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_label: str | None
    disease: str
    model_id: str
    positive_prob: float
    negative_prob: float
    verdict: str
    threshold: float
    confidence_band: str
    created_at: datetime
    elapsed_ms: int
    llm_used: bool


class RecordDetailOut(RecordOut):
    features: dict[str, float]
    contributions: list[Any] | None


class RecordPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[RecordOut]


class StatsOut(BaseModel):
    total_predictions: int
    by_disease: dict[str, int]
    positives: int
    negatives: int
    positive_rate: float
    llm_calls: int
    llm_cache_hits: int
    cache_hit_rate: float
    last_prediction_at: datetime | None


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #

class OcrFieldOut(BaseModel):
    key: str
    name_zh: str
    name_en: str
    value: float | None
    confidence: float
    needs_review: bool
    status: Literal["matched", "uncertain", "missing"]


class OcrResponse(BaseModel):
    disease: str
    fields: list[OcrFieldOut]
    matched_count: int
    needs_review_count: int
    message: str
