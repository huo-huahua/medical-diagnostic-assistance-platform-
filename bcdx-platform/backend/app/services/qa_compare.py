"""Side-by-side comparison of the Q&A answer paths.

The project's default Q&A pipeline is fully local and costs nothing. This module
exists to make that design choice **legible** rather than merely asserted: the
same question is answered by three different pipelines and the results are
reported next to each other, together with the metrics that actually differ.

    1. ``local_rag``   retrieval + local composition        no external call
    2. ``llm_direct``  external model, no retrieval         the "just ask the
                                                            model" baseline
    3. ``llm_rag``     retrieved passages injected into the  best of both, but
                       external model's prompt              still paid per call

Comparing models, not only pipelines
------------------------------------
The two external paths accept a `models` list, which turns them into two
columns *per model* — `llm_direct@deepseek-chat`, `llm_direct@gpt-4o-mini`, and
so on. That answers the other obvious question ("is the expensive model
actually better here?") with the same machinery, the same shared retrieval and
the same metrics, so the two comparisons stay directly comparable.

Why the comparison is the interesting artifact
----------------------------------------------
A large language model answers fluently whether or not it is right. Retrieval
changes what the model is *allowed* to draw on, and gives every claim a
checkable origin. Putting the three side by side shows both effects at once:

* the local path cannot invent a fact — its text is copied from the passages,
  and when nothing matches it refuses instead of guessing;
* the direct path reads better but has no provenance at all, and its lexical
  overlap with the knowledge base is measurably lower;
* the retrieval-augmented path recovers the provenance while keeping the
  model's fluency, at the cost of a paid call.

Cost discipline
---------------
Nothing here runs by default. The endpoint is opt-in, rate limited, length
capped and served from the gateway's cache on repeat, because keeping external
API calls to an absolute minimum is a hard constraint of this project.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_gateway import get_gateway, normalize_zh
from app.services.rag_service import (
    Chunk,
    Passage,
    compose_local_answer,
    get_index,
    group_passages,
    is_greeting,
    synthesize_with_llm,
    tokenize,
)

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Path catalogue
# --------------------------------------------------------------------------- #

PATH_LABELS: dict[str, dict[str, Any]] = {
    "local_rag": {
        "label": "本地检索增强",
        "short": "本地 RAG",
        "uses_retrieval": True,
        "external_call": False,
        "description": (
            "在本地知识库中检索相关条目，直接以原文片段组织答案并标注出处。"
            "全程离线，不调用任何外部服务，成本为零。"
        ),
    },
    "llm_direct": {
        "label": "外部模型直答（无检索）",
        "short": "外部直答",
        "uses_retrieval": False,
        "external_call": True,
        "description": (
            "把问题直接交给外部大模型，不提供任何参考资料。"
            "用于观察模型完全凭参数化知识作答时的表现，"
            "是评估「幻觉」风险的基线路径。"
        ),
    },
    "llm_rag": {
        "label": "外部模型 + 检索增强",
        "short": "外部 + RAG",
        "uses_retrieval": True,
        "external_call": True,
        "description": (
            "先做本地检索，再把检索到的原文片段作为上下文交给外部模型组织语言。"
            "兼顾出处的可核查性与表达的流畅度，代价是每次调用产生费用。"
        ),
    },
}

ALL_PATHS: tuple[str, ...] = ("local_rag", "llm_direct", "llm_rag")

#: Separator between a path key and the model it was fanned out to, e.g.
#: `llm_direct@deepseek-chat`. Chosen because it cannot occur in a model name
#: that passes `_clean_models`, so `key.split("@", 1)[0]` always recovers the
#: base path.
MODEL_SEPARATOR = "@"

#: Model names are user input that ends up in a JSON body sent to a third
#: party, so they are constrained rather than passed through. The allowed set
#: covers every naming scheme in use (`gpt-4o-mini`, `qwen2.5:7b`,
#: `meta-llama/Llama-3-8B`, `deepseek-chat`).
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:\-/]{1,64}$")


def _clean_models(models: list[str] | None) -> list[str]:
    """Normalise a requested model list: trim, dedupe, validate, cap.

    A silently dropped model would leave a column missing with no explanation,
    so the caller echoes the cleaned list back; the cap exists because each
    model adds two paid calls and an unbounded list is an unbounded bill.
    """
    if not models:
        return []
    seen: list[str] = []
    for raw in models:
        name = (raw or "").strip()
        if not name or name in seen or not _MODEL_PATTERN.match(name):
            continue
        seen.append(name)
    return seen[: max(1, settings.llm_max_compare_models)]

# Shallow keyword screen for absolutist wording. At face value this is not a
# safety guarantee and is not presented as one — it is a cheap, explainable
# signal that happens to separate the two styles of answer well.
_ABSOLUTE_TERMS: tuple[str, ...] = (
    "一定", "保证", "绝对", "百分之百", "100%", "彻底治愈", "包治",
    "无需就医", "不用去医院", "肯定",
)

DIRECT_SYSTEM = (
    "你是一位严谨的医学科普助手，正在回答用户的健康相关问题。"
    "要求：\n"
    "1. 用简体中文，条理清晰，可用小标题或编号列表；\n"
    "2. 这次没有为你提供任何参考资料，请仅凭你已有的知识作答；\n"
    "3. 不确定或知识不足的部分，必须明确说明「这方面我不确定」，严禁编造；\n"
    "4. 不给出具体药物剂量，不做出「一定」「保证」等绝对化判断；\n"
    "5. 结尾用一句话提醒用户以医师意见为准。\n"
    "请不要在回答中标注任何引用编号，因为你没有可引用的资料。"
)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

@dataclass
class PathResult:
    """One answer path and everything that differs between paths."""

    key: str
    label: str
    short: str
    description: str

    answer: str | None = None
    citations: list[dict] = field(default_factory=list)

    refused: bool = False
    uses_retrieval: bool = False
    external_call: bool = False

    # Which upstream produced this column, so `llm_direct@a` and `llm_direct@b`
    # are distinguishable in the response and not just in the key.
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
    risk_phrases: list[str] = field(default_factory=list)
    citation_count: int = 0

    status: str = "ok"          # ok | skipped | failed
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _cost_cny(
    prompt_tokens: int,
    completion_tokens: int,
    prices: tuple[float, float] | None = None,
) -> float:
    """Display-only estimate from per-1K-token prices.

    `prices` defaults to the `.env` values, which is right for a single
    provider configured by hand. When the comparison runs several providers in
    one request, each column is priced with its own provider's rates so the
    totals remain additive and comparable.
    """
    prompt_price, completion_price = prices or (
        settings.llm_price_prompt_per_1k,
        settings.llm_price_completion_per_1k,
    )
    return round(
        prompt_tokens / 1000 * prompt_price
        + completion_tokens / 1000 * completion_price,
        6,
    )


def lexical_overlap(answer: str, context: str) -> float:
    """Share of the answer's content terms that also occur in `context`.

    This is a **lexical** proxy, not a correctness measure. Two honest caveats:

    * a high score does not prove the answer is true — it only means the words
      are present in the retrieved text;
    * a low score does not prove the answer is false. Chinese medical
      vocabulary is narrow, so even a purely parametric answer overlaps the
      knowledge base somewhat.

    What it does show reliably is the *direction* of the effect: an answer that
    was written from the passages reuses their phrasing, while one produced
    without them does not.
    """
    answer_terms = {t for t in tokenize(answer) if len(t) >= 2}
    if not answer_terms:
        return 0.0
    context_terms = set(tokenize(context))
    return round(len(answer_terms & context_terms) / len(answer_terms), 4)


def risk_phrases(answer: str) -> list[str]:
    """Absolutist wording found in the answer, for side-by-side viewing."""
    normalized = normalize_zh(answer)
    found = []
    for term in _ABSOLUTE_TERMS:
        if normalize_zh(term) in normalized:
            found.append(term)
    return found


def _citation_dicts(passages: list[Passage]) -> list[dict]:
    return [
        {
            "index": i,
            "source": p.source,
            "title": p.citation_title,
            "snippet": p.text[:220].replace("\n", " "),
            "score": round(p.score, 4),
        }
        for i, p in enumerate(passages, start=1)
    ]


# --------------------------------------------------------------------------- #
# Retrieval (shared by every path, so the paths differ only in composition)
# --------------------------------------------------------------------------- #

@dataclass
class Retrieval:
    hits: list[tuple[Chunk, float]]
    passages: list[Passage]
    citations: list[dict]
    context: str
    top_score: float
    refused: bool
    local_answer: str
    latency_ms: int


def retrieve(question: str, disease: str) -> Retrieval:
    index = get_index()
    # Build (or reuse) the index *before* starting the clock. Otherwise the
    # one-off embedding pass — tens of seconds on a cold process — would be
    # reported as this answer's latency and make the local path look slow.
    if not index.ready:
        index.build()

    started = time.perf_counter()
    hits = index.search(question, top_k=settings.rag_top_k, disease=disease)
    passages = group_passages(hits)
    local_answer, refused = compose_local_answer(
        question, hits, disease=disease, passages=passages
    )
    return Retrieval(
        hits=hits,
        passages=passages,
        citations=_citation_dicts(passages),
        context="\n\n".join(
            f"[^c{i}] 《{p.title}》\n{p.text}" for i, p in enumerate(passages, start=1)
        ),
        top_score=round(hits[0][1], 4) if hits else 0.0,
        refused=refused,
        local_answer=local_answer,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


# --------------------------------------------------------------------------- #
# Path runners
# --------------------------------------------------------------------------- #

def _base(
    key: str,
    *,
    model: str | None = None,
    provider: str = "",
    is_mock: bool = False,
) -> PathResult:
    """Build the skeleton for one column.

    `key` may carry a `@model` suffix, in which case the catalogue entry is
    looked up by the part before the separator and the model name is folded into
    the short label. The table headers are the only place the model can be seen
    at a glance, so it has to be visible there rather than in a tooltip.
    """
    meta = PATH_LABELS[key.split(MODEL_SEPARATOR, 1)[0]]
    short = meta["short"]
    if model:
        short = f"{short}·{model}"
    return PathResult(
        key=key,
        label=meta["label"],
        short=short,
        description=meta["description"],
        uses_retrieval=meta["uses_retrieval"],
        external_call=meta["external_call"],
        provider=provider,
        model=model,
        is_mock=is_mock,
    )


def _demo_note() -> str:
    return "当前使用**内置演示模型**：输出是本地生成的占位文本，不是任何真实模型的回答，不可作为医学参考。"


def run_local_rag(question: str, retrieval: Retrieval) -> PathResult:
    result = _base("local_rag")
    result.answer = retrieval.local_answer
    result.latency_ms = retrieval.latency_ms
    result.risk_phrases = risk_phrases(retrieval.local_answer)
    result.answer_chars = len(retrieval.local_answer)
    result.refused = retrieval.refused

    if is_greeting(question):
        # Retrieval still runs (it is shared and already paid for), but a
        # greeting answer does not *use* any of it, so it must not claim
        # citations — otherwise the table would show provenance that the text
        # never drew on.
        result.citations = []
        result.citation_count = 0
        result.lexical_overlap = 0.0
        result.note = (
            "这是一句问候，返回的是引导文案，没有使用任何知识库内容，"
            "因此不带引用。"
        )
        return result

    result.citations = retrieval.citations
    result.citation_count = len(retrieval.citations)
    result.lexical_overlap = 1.0 if not retrieval.refused else 0.0
    result.note = (
        "回答由检索到的原文片段直接组成，每段都带可核查的出处编号。"
        if not retrieval.refused
        else "本地知识库未命中或超出当前病种范围，已按设计拒答，而不是猜测。"
    )
    return result


def run_llm_direct(
    question: str,
    disease: str,
    retrieval: Retrieval,
    *,
    model: str | None = None,
    path_key: str = "llm_direct",
) -> PathResult:
    """Ask the model with no context. This is the hallucination baseline."""
    gateway = get_gateway()
    resolved = gateway.provider
    effective_model = (model or "").strip() or resolved.model
    result = _base(
        path_key,
        model=effective_model,
        provider=resolved.id,
        is_mock=resolved.is_demo,
    )

    if not gateway.available:
        result.status = "skipped"
        result.note = (
            "未启用外部模型：环境变量中未配置可用的 API Key，或 LLM_ENABLED=false。"
            "该路径为空不代表失败，只是本部署没有开启付费调用。"
        )
        return result

    started = time.perf_counter()
    text, meta = gateway.complete(
        purpose="qa_direct",
        system=DIRECT_SYSTEM,
        user=f"用户问题：{question}",
        # Cache on the question alone: the same question must never be paid for
        # twice, no matter how many comparisons are run. The model is added to
        # the cache identity by the gateway, so different models stay separate.
        cache_payload=f"direct::{question}",
        embed_fn=get_index().embed_query,
        temperature=0.3,
        model=effective_model,
    )
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.llm_used = bool(meta.get("llm_used"))
    result.cache_hit = bool(meta.get("cache_hit"))
    result.prompt_tokens = int(meta.get("prompt_tokens", 0) or 0)
    result.completion_tokens = int(meta.get("completion_tokens", 0) or 0)
    result.cost_cny = _cost_cny(
        result.prompt_tokens, result.completion_tokens, resolved.prices
    )

    if not text:
        result.status = "failed"
        error = meta.get("error") or {}
        result.note = (
            f"外部模型调用失败：{error['message']}"
            if error.get("message")
            else "外部模型调用未返回内容（网络失败、密钥无效或模型名不存在）。"
        )
        return result

    result.answer = text
    result.answer_chars = len(text)
    result.risk_phrases = risk_phrases(text)
    # Compared against the passages it never saw — that is the point.
    result.lexical_overlap = lexical_overlap(text, retrieval.context)
    result.note = (
        "模型没有获得任何参考资料，回答完全来自其参数化知识，"
        "因此没有任何可核查的出处。文字可能非常流畅，但流畅不等于正确。"
    )
    if resolved.is_demo:
        result.note = f"{result.note} {_demo_note()}"
    return result


def run_llm_rag(
    question: str,
    retrieval: Retrieval,
    *,
    model: str | None = None,
    path_key: str = "llm_rag",
) -> PathResult:
    """Inject the retrieved passages into the model's prompt."""
    gateway = get_gateway()
    resolved = gateway.provider
    effective_model = (model or "").strip() or resolved.model
    result = _base(
        path_key,
        model=effective_model,
        provider=resolved.id,
        is_mock=resolved.is_demo,
    )

    if not gateway.available:
        result.status = "skipped"
        result.note = (
            "未启用外部模型：环境变量中未配置可用的 API Key，或 LLM_ENABLED=false。"
            "该路径为空不代表失败，只是本部署没有开启付费调用。"
        )
        return result

    if retrieval.refused:
        # Feeding an out-of-scope question to the model would defeat the
        # knowledge-base isolation that the local path just enforced.
        result.status = "skipped"
        result.refused = True
        result.note = (
            "本地检索已判定该问题超出当前病种知识库范围，"
            "为避免跨病种内容混淆，未把问题转交外部模型。"
        )
        return result

    started = time.perf_counter()
    text, meta = synthesize_with_llm(
        question, retrieval.hits, get_index().embed_query, model=effective_model
    )
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    result.llm_used = bool(meta.get("llm_used"))
    result.cache_hit = bool(meta.get("cache_hit"))
    result.prompt_tokens = int(meta.get("prompt_tokens", 0) or 0)
    result.completion_tokens = int(meta.get("completion_tokens", 0) or 0)
    result.cost_cny = _cost_cny(
        result.prompt_tokens, result.completion_tokens, resolved.prices
    )
    result.citations = retrieval.citations
    result.citation_count = len(retrieval.citations)

    if meta.get("skipped"):
        result.status = "skipped"
        result.note = (
            "检索片段过短，未达到调用外部模型的最小长度阈值，"
            "已由成本控制策略跳过本次调用。"
        )
        return result

    if not text:
        result.status = "failed"
        error = meta.get("error") or {}
        result.note = (
            f"外部模型调用失败：{error['message']}"
            if error.get("message")
            else "外部模型调用未返回内容（网络失败、密钥无效或模型名不存在）。"
        )
        return result

    result.answer = text
    result.answer_chars = len(text)
    result.risk_phrases = risk_phrases(text)
    result.lexical_overlap = lexical_overlap(text, retrieval.context)
    result.note = (
        "在拿到检索片段的前提下组织语言，因此兼具出处的可核查性与表达的流畅度，"
        "代价是每次调用产生 token 费用。"
    )
    if resolved.is_demo:
        result.note = f"{result.note} {_demo_note()}"
    return result


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def compare(
    question: str,
    disease: str,
    paths: list[str] | None = None,
    models: list[str] | None = None,
) -> dict:
    """Run the requested answer paths over one shared retrieval result.

    Retrieval happens exactly once and is shared, so the difference between the
    paths is attributable to the composition step rather than to different
    inputs.

    `models` turns the two external paths into two columns *per model*, keyed
    `llm_direct@<model>` / `llm_rag@<model>`. When it is omitted the response is
    exactly what it was before the feature existed — same three keys, same
    order — so the default behaviour of the endpoint has not moved. Note that
    the requested models are run *instead of* the configured one rather than in
    addition to it: silently adding a paid call the caller did not list would
    make the bill unpredictable, and the UI pre-fills the input with the
    configured model so the common case still includes it.
    """
    requested = [p for p in (paths or list(ALL_PATHS)) if p in PATH_LABELS]
    if not requested:
        requested = list(ALL_PATHS)

    truncated = len(question) > settings.qa_compare_max_question_chars
    question_used = question[: settings.qa_compare_max_question_chars]

    retrieval = retrieve(question_used, disease)

    if not settings.qa_compare_allow_llm:
        requested = [p for p in requested if p == "local_rag"] or ["local_rag"]

    model_list = _clean_models(models)
    # `None` means "whatever the gateway is configured with", which keeps the
    # single-model path free of suffixes.
    models_to_run: list[str | None] = list(model_list) if model_list else [None]

    results: list[PathResult] = []
    for key in requested:
        if key == "local_rag":
            results.append(run_local_rag(question_used, retrieval))
            continue
        for model in models_to_run:
            path_key = f"{key}{MODEL_SEPARATOR}{model}" if model else key
            if key == "llm_direct":
                results.append(
                    run_llm_direct(
                        question_used, disease, retrieval,
                        model=model, path_key=path_key,
                    )
                )
            elif key == "llm_rag":
                results.append(
                    run_llm_rag(
                        question_used, retrieval, model=model, path_key=path_key,
                    )
                )

    provider = get_gateway().provider
    external_calls = sum(1 for r in results if r.llm_used)
    cache_hits = sum(1 for r in results if r.cache_hit)
    prompt_tokens = sum(r.prompt_tokens for r in results)
    completion_tokens = sum(r.completion_tokens for r in results)

    grounded = [r.key for r in results if r.citation_count > 0 and r.status == "ok"]
    # A greeting legitimately has no citations — it is not an *ungrounded
    # answer* (which would mean a claim with no provenance). Counting it as one
    # would flag the safest possible reply as the riskiest.
    ungrounded = [
        r.key for r in results
        if r.citation_count == 0 and r.answer and r.status == "ok"
        and not is_greeting(question_used)
    ]

    summary = {
        "external_calls": external_calls,
        "cache_hits": cache_hits,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_cny": _cost_cny(prompt_tokens, completion_tokens, provider.prices),
        "grounded_paths": grounded,
        "ungrounded_paths": ungrounded,
        "llm_available": get_gateway().available,
        # Every column is priced with the same provider's rates, so the totals
        # above are a fair sum. When `demo_mode` is true the call count is real
        # (the SDK really ran) but nothing was billed and nothing left the
        # process — the UI must not say "已产生费用" for it.
        "demo_mode": provider.is_demo,
        "models": model_list,
    }

    return {
        "question": question_used,
        "truncated": truncated,
        "disease": disease,
        "refused": retrieval.refused,
        "top_score": retrieval.top_score,
        "passage_count": len(retrieval.passages),
        "hit_count": len(retrieval.hits),
        "citations": retrieval.citations,
        "paths": [r.to_dict() for r in results],
        "models": model_list,
        "provider": provider.id,
        "summary": summary,
        "total_latency_ms": sum(r.latency_ms for r in results),
    }
