"""LLM gateway — the single egress point for all model API calls.

Cost control is the primary design goal. Three layers of defence:

  1. **Hard switch**   — `LLM_ENABLED=false` disables every call site.
  2. **Exact cache**   — normalised prompt hash -> response, LRU bounded.
  3. **Semantic cache** — embedding similarity against recent prompts, so
     paraphrased questions also hit the cache instead of paying again.

Every call is accounted in the `llm_usage` table so cost is always visible.

Which upstream is called is decided by `services/llm_providers.py`; this module
only has to (a) build a client for whatever it returns, (b) cache correctly
across models, and (c) turn an exception into something a human can act on.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx
import numpy as np

from app.core.config import settings
from app.core.errors import ExternalServiceError
from app.core.logging import get_logger
from app.services import llm_providers as providers
from app.services.llm_mock import build_transport

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #

_WS = re.compile(r"\s+")
# Punctuation to strip before hashing: CJK + ASCII. Escaped explicitly so
# Python does not emit a SyntaxWarning for the character class.
_PUNCT = re.compile(
    r"[\uff0c\u3002\uff01\uff1f\u3001\uff1b\uff1a"
    r"\u201c\u201d\u2018\u2019\uff08\uff09\u300a\u300b\u3010\u3011"
    r",.!?;:\"'()\[\]{}]"
)


def normalize_zh(text: str) -> str:
    """Normalise Chinese/English text so trivial differences still cache-hit."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)   # full-width -> half-width
    t = t.lower()
    t = _PUNCT.sub("", t)
    t = _WS.sub("", t)
    return t.strip()


def prompt_key(purpose: str, payload: str) -> str:
    return hashlib.sha256(f"{purpose}::{normalize_zh(payload)}".encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Caches
# --------------------------------------------------------------------------- #

@dataclass
class CacheEntry:
    value: str
    embedding: np.ndarray | None
    meta: dict[str, Any]
    #: The `purpose` that produced this entry (e.g. `rag`, `qa_direct`).
    #: Stored so a semantic hit cannot cross purposes — see `get_semantic`.
    purpose: str = ""


class ResponseCache:
    """Bounded LRU cache with optional semantic lookup."""

    def __init__(self, maxsize: int = 512, semantic_threshold: float = 0.94):
        self.maxsize = maxsize
        self.semantic_threshold = semantic_threshold
        self._exact: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits_exact = 0
        self.hits_semantic = 0
        self.misses = 0

    # -- exact ---------------------------------------------------------- #
    def get_exact(self, key: str) -> str | None:
        with self._lock:
            entry = self._exact.get(key)
            if entry is None:
                return None
            self._exact.move_to_end(key)
            self.hits_exact += 1
            return entry.value

    def put(self, key: str, value: str, embedding: np.ndarray | None = None,
            meta: dict[str, Any] | None = None, purpose: str = "") -> None:
        with self._lock:
            self._exact[key] = CacheEntry(value, embedding, meta or {}, purpose)
            self._exact.move_to_end(key)
            while len(self._exact) > self.maxsize:
                self._exact.popitem(last=False)

    # -- semantic ------------------------------------------------------- #
    def get_semantic(self, query_vec: np.ndarray, purpose: str | None = None) -> str | None:
        """Nearest cached answer above the similarity threshold.

        `purpose` scopes the search to entries produced by the same call site.
        Without it the semantic layer is actively harmful rather than merely
        imprecise: the embedded text is the *cache payload* (essentially the
        user's question), and different call sites derive that payload from the
        same question — so `rag` and `qa_direct` embeddings for one question sit
        at a cosine similarity near 1.0, and the direct path would be served the
        retrieval-grounded answer. That is the one comparison the whole feature
        exists to make, so it must not be silently collapsed. Passing `None`
        keeps the old unscoped behaviour, which is what the unit tests exercise.
        """
        if query_vec is None:
            return None
        with self._lock:
            best_key, best_sim = None, 0.0
            for key, entry in self._exact.items():
                if entry.embedding is None:
                    continue
                if purpose is not None and entry.purpose != purpose:
                    continue
                sim = float(
                    np.dot(query_vec, entry.embedding)
                    / (np.linalg.norm(query_vec) * np.linalg.norm(entry.embedding) + 1e-9)
                )
                if sim > best_sim:
                    best_key, best_sim = key, sim
            if best_key is not None and best_sim >= self.semantic_threshold:
                self._exact.move_to_end(best_key)
                self.hits_semantic += 1
                logger.info(f"semantic LLM cache hit (sim={best_sim:.4f})")
                return self._exact[best_key].value
        return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits_exact + self.hits_semantic + self.misses
            return {
                "size": len(self._exact),
                "maxsize": self.maxsize,
                "hits_exact": self.hits_exact,
                "hits_semantic": self.hits_semantic,
                "misses": self.misses,
                "hit_rate": round(
                    (self.hits_exact + self.hits_semantic) / total, 4
                ) if total else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._exact.clear()


# --------------------------------------------------------------------------- #
# Gateway
# --------------------------------------------------------------------------- #

# The probe is deliberately the smallest call the API allows. Its job is to
# separate "this deployment cannot reach the model" from "the model answered
# badly", and neither question needs a long prompt.
PROBE_SYSTEM = "你是一个连通性测试助手。"
PROBE_USER = "只回复两个字：正常"


class LlmGateway:
    def __init__(self) -> None:
        self.cache = ResponseCache(maxsize=settings.llm_cache_size)
        self._client = None
        self._client_key: tuple | None = None
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.api_calls = 0
        self.failures = 0
        #: Structured description of the most recent failure, cleared by the
        #: next success. Lets `/llm/status` answer "is it broken right now?".
        self.last_error: dict[str, Any] | None = None

    # -- availability --------------------------------------------------- #
    @property
    def provider(self) -> providers.ResolvedProvider:
        """The provider in force right now, re-resolved on every access.

        Resolution is a dict lookup and a few string comparisons, and reading
        it fresh each time is what makes the environment variables behave like
        configuration rather than like values frozen at first import.
        """
        return providers.resolve()

    @property
    def available(self) -> bool:
        return settings.llm_enabled and providers.is_ready(self.provider)

    # -- client --------------------------------------------------------- #
    def _identity(self) -> tuple:
        p = self.provider
        return (p.id, p.base_url, p.model, bool(settings.llm_api_key), settings.llm_timeout_seconds)

    def _get_client(self):
        """Build the SDK client, rebuilding it whenever the configuration moved.

        Caching on the identity tuple rather than on `None` matters because the
        provider can change while the process lives (tests do it constantly, and
        an operator editing `.env` then restarting only one worker is not
        hypothetical). A stale client would keep posting to the previous
        service's base URL, which looks to the user like an authentication
        failure.
        """
        identity = self._identity()
        if self._client is not None and self._client_key == identity:
            return self._client

        from openai import OpenAI

        p = self.provider
        kwargs: dict[str, Any] = {
            # The SDK refuses to construct without a key. Keyless targets
            # (`ollama`, the in-process demo transport) ignore the value.
            "api_key": settings.llm_api_key or "not-required",
            "base_url": p.base_url,
            "timeout": settings.llm_timeout_seconds,
            "max_retries": 1,
        }
        if p.is_demo:
            # Same request/response contract, no socket. See `llm_mock`.
            # `llm_mock_fault` is a deliberate, demo-only escape hatch so the
            # error taxonomy can be reproduced by hand instead of only in tests.
            kwargs["http_client"] = httpx.Client(
                transport=build_transport(
                    fault=settings.llm_mock_fault or None, model=p.model
                )
            )
            kwargs["max_retries"] = 0

        self._client = OpenAI(**kwargs)
        self._client_key = identity
        logger.info(
            f"LLM client built: provider={p.id} model={p.model} base_url={p.base_url}"
            + (" [demo transport]" if p.is_demo else "")
        )
        return self._client

    # -- core call ------------------------------------------------------ #
    def complete(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        cache_payload: str | None = None,
        embed_fn: Any = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> tuple[str | None, dict[str, Any]]:
        """Return (text, meta). text is None when the LLM is unavailable.

        `cache_payload` lets the caller control what identifies a cache hit
        (e.g. the user's question alone, ignoring the injected context).

        `model` overrides the configured model for this call only, which is what
        lets one comparison ask two different models the same question.
        """
        resolved = self.provider
        model_used = (model or "").strip() or resolved.model

        meta: dict[str, Any] = {
            "llm_used": False, "cache_hit": False,
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
            "model": model_used, "provider": resolved.id,
        }

        if not self.available:
            return None, meta

        payload = cache_payload if cache_payload is not None else f"{system}\n{user}"
        # The model is part of the cache *identity*, not merely of the request.
        # Without it, two models answering the same question would share one
        # entry and the second model would never actually be called — the
        # comparison would silently show the first model's text twice.
        cache_purpose = f"{purpose}@{model_used}"
        key = prompt_key(cache_purpose, payload)

        hit = self.cache.get_exact(key)
        if hit is not None:
            meta["cache_hit"] = True
            logger.info(f"exact LLM cache hit [{purpose}] model={model_used}")
            return hit, meta

        # Semantic layer: only worthwhile for user-question-driven calls, and
        # only within the same call site (see `get_semantic`).
        query_vec = None
        if embed_fn is not None and cache_payload is not None:
            try:
                query_vec = np.asarray(embed_fn([payload])[0], dtype=float)
                sem = self.cache.get_semantic(query_vec, purpose=cache_purpose)
                if sem is not None:
                    meta["cache_hit"] = True
                    return sem, meta
            except Exception as exc:
                logger.debug(f"semantic cache lookup skipped: {exc}")

        # --- real API call --- #
        started = time.perf_counter()
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=model_used,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens or settings.llm_max_tokens,
                stream=False,
            )
            text = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            if usage is not None:
                meta["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
                meta["completion_tokens"] = int(
                    getattr(usage, "completion_tokens", 0) or 0
                )
                self.total_prompt_tokens += meta["prompt_tokens"]
                self.total_completion_tokens += meta["completion_tokens"]
        except Exception as exc:
            info = providers.explain_error(exc)
            self.failures += 1
            self.last_error = {
                **info,
                "purpose": purpose,
                "model": model_used,
                "at": time.time(),
            }
            meta["error"] = info
            logger.warning(
                f"LLM call failed [{purpose}] model={model_used}: "
                f"{info['kind']} — {exc}"
            )
            self.cache.misses += 1
            return None, meta

        meta["latency_ms"] = int((time.perf_counter() - started) * 1000)
        meta["llm_used"] = True
        self.api_calls += 1
        self.last_error = None
        logger.info(
            f"LLM API call [{purpose}] provider={resolved.id} model={model_used} "
            f"{meta['latency_ms']}ms "
            f"tokens={meta['prompt_tokens']}+{meta['completion_tokens']} "
            f"(total calls this process: {self.api_calls})"
        )

        if text:
            self.cache.put(key, text, query_vec, meta, purpose=cache_purpose)
        return text or None, meta

    def health(self) -> dict[str, Any]:
        p = self.provider
        return {
            "enabled": settings.llm_enabled,
            "configured": settings.llm_configured,
            "available": self.available,
            "model": p.model if self.available else None,
            # --- which upstream, exactly ---
            "provider": p.id,
            "provider_label": p.label,
            "base_url": p.base_url,
            "requires_key": p.requires_key,
            "is_demo": p.is_demo,
            "key_present": providers.key_present(),
            "key_masked": providers.mask_key(),
            "ready": providers.is_ready(p),
            "unknown_provider": p.unknown_provider,
            "model_overridden": p.model_overridden,
            "base_url_overridden": p.base_url_overridden,
            # --- counters ---
            "api_calls_this_process": self.api_calls,
            "failures_this_process": self.failures,
            "last_error": self.last_error,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "max_compare_models": settings.llm_max_compare_models,
            # Surfaced so an operator who set `LLM_MOCK_FAULT` for a demo is
            # never left wondering why every call fails. Empty in normal runs.
            "mock_fault": (settings.llm_mock_fault or None) if p.is_demo else None,
            "cache": self.cache.stats(),
        }

    # -- connectivity probe --------------------------------------------- #
    def probe(self) -> dict[str, Any]:
        """Make one tiny real call to find out whether the provider works.

        Exists because the alternative is discovering a broken configuration by
        running a comparison and reading "调用失败" — which is the same message
        for an expired key, a base URL missing `/v1`, a model name that does not
        exist and a machine with no route to the internet. One 16-token request
        tells them apart, and its cost is negligible next to the diagnosis time
        it saves.

        The probe deliberately bypasses the response cache: a cached *success*
        would keep reporting healthy long after the credential was revoked, and
        a liveness check that can be served from cache is not a liveness check.
        Its tokens are still added to the process totals, because they were
        really spent.
        """
        p = self.provider
        result: dict[str, Any] = {
            "provider": p.id,
            "provider_label": p.label,
            "model": p.model,
            "base_url": p.base_url,
            "is_demo": p.is_demo,
            "ok": False,
            "latency_ms": 0,
            "reply": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_cny": 0.0,
            "error_kind": None,
            "error_message": None,
            "error_detail": None,
        }

        # Pre-flight: report the configuration problem directly instead of
        # letting the SDK fail with a less specific error.
        if not settings.llm_enabled:
            return self._probe_failure(result, "disabled", None)
        if not p.has_endpoint:
            return self._probe_failure(result, "no_endpoint", None)
        if p.requires_key and not providers.key_present():
            return self._probe_failure(result, "missing_key", None)

        started = time.perf_counter()
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=p.model,
                messages=[
                    {"role": "system", "content": PROBE_SYSTEM},
                    {"role": "user", "content": PROBE_USER},
                ],
                temperature=0.0,
                max_tokens=16,
                stream=False,
            )
            text = (resp.choices[0].message.content or "").strip()
            usage = getattr(resp, "usage", None)
            if usage is not None:
                result["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
                result["completion_tokens"] = int(
                    getattr(usage, "completion_tokens", 0) or 0
                )
                self.total_prompt_tokens += result["prompt_tokens"]
                self.total_completion_tokens += result["completion_tokens"]
        except Exception as exc:
            result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            self.failures += 1
            info = providers.explain_error(exc)
            self.last_error = {**info, "purpose": "probe", "model": p.model,
                               "at": time.time()}
            result["error_kind"] = info["kind"]
            result["error_message"] = info["message"]
            result["error_detail"] = info["detail"]
            logger.warning(f"LLM probe failed: {info['kind']} — {exc}")
            return result

        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        result["reply"] = text[:200]
        result["cost_cny"] = round(
            result["prompt_tokens"] / 1000 * p.price_prompt_per_1k
            + result["completion_tokens"] / 1000 * p.price_completion_per_1k,
            6,
        )
        self.api_calls += 1

        if not text:
            # A 200 with no content is a real failure mode: a content filter, a
            # reasoning-only response, or a proxy that swallowed the body.
            self.failures += 1
            self.last_error = {
                "kind": "empty_response",
                "message": providers.message_for("empty_response"),
                "detail": None,
                "type": "EmptyResponse",
                "purpose": "probe",
                "model": p.model,
                "at": time.time(),
            }
            return self._probe_failure(result, "empty_response", None)

        result["ok"] = True
        self.last_error = None
        logger.info(
            f"LLM probe ok: provider={p.id} model={p.model} "
            f"{result['latency_ms']}ms tokens={result['prompt_tokens']}"
            f"+{result['completion_tokens']}"
        )
        return result

    @staticmethod
    def _probe_failure(result: dict[str, Any], kind: str, detail: str | None) -> dict[str, Any]:
        result["ok"] = False
        result["error_kind"] = kind
        result["error_message"] = providers.message_for(kind)
        result["error_detail"] = detail
        return result


_gateway: LlmGateway | None = None


def get_gateway() -> LlmGateway:
    global _gateway
    if _gateway is None:
        _gateway = LlmGateway()
        logger.info(
            f"LLM gateway ready: available={_gateway.available} "
            f"model={settings.llm_model} cache_size={settings.llm_cache_size}"
        )
    return _gateway
