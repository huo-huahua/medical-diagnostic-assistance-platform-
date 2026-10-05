"""The LLM gateway: cost control is the whole point of this module.

Three layers of defence, all of them testable without a network:

  1. **Hard switch**   — `LLM_ENABLED=false` (or a missing key) returns
     `(None, meta)` without touching the client.
  2. **Exact cache**   — normalised prompt hash, so a question that differs only
     by whitespace / punctuation / full-width characters still hits.
  3. **Semantic cache** — near-duplicate questions hit by embedding similarity.

Every test here is pure unit-level and runs in milliseconds, so it is safe to
run in CI on every push.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core.config import settings
from app.services.llm_gateway import (
    LlmGateway,
    ResponseCache,
    normalize_zh,
    prompt_key,
)


# --------------------------------------------------------------------------- #
# Normalisation — the reason trivial rephrasings still cache-hit
# --------------------------------------------------------------------------- #

class TestNormalizeZh:
    def test_strips_whitespace_and_punctuation(self):
        assert normalize_zh("乳腺 癌，如何 筛查？") == normalize_zh("乳腺癌如何筛查")

    def test_folds_full_width_to_half_width(self):
        # NFKC turns full-width latin/digits into ASCII.
        assert normalize_zh("ＡＢＣ１２３") == "abc123"

    def test_is_case_insensitive(self):
        assert normalize_zh("BI-RADS") == normalize_zh("bi-rads")

    def test_distinct_questions_stay_distinct(self):
        assert normalize_zh("乳腺癌如何筛查") != normalize_zh("冠心病如何筛查")

    def test_empty_input_is_safe(self):
        assert normalize_zh("") == ""
        assert normalize_zh("   ，。 ") == ""


class TestPromptKey:
    def test_same_text_same_key(self):
        assert prompt_key("rag", "乳腺癌怎么筛查") == prompt_key("rag", "乳腺癌怎么筛查")

    def test_normalisation_does_not_change_the_key(self):
        assert prompt_key("rag", "乳腺癌，怎么筛查？") == prompt_key("rag", "乳腺癌怎么筛查")

    def test_purpose_namespaces_the_key(self):
        """The same question asked for a different purpose must not collide."""
        assert prompt_key("rag", "问题") != prompt_key("qa_direct", "问题")

    def test_key_is_a_hex_digest(self):
        key = prompt_key("rag", "问题")
        assert len(key) == 64
        int(key, 16)  # raises if not hex


# --------------------------------------------------------------------------- #
# ResponseCache
# --------------------------------------------------------------------------- #

class TestResponseCache:
    def test_exact_roundtrip(self):
        cache = ResponseCache()
        cache.put("k1", "答案")
        assert cache.get_exact("k1") == "答案"

    def test_miss_returns_none(self):
        assert ResponseCache().get_exact("nope") is None

    def test_lru_evicts_the_oldest(self):
        cache = ResponseCache(maxsize=2)
        cache.put("a", "A")
        cache.put("b", "B")
        cache.get_exact("a")          # touch "a" so "b" becomes the oldest
        cache.put("c", "C")
        assert cache.get_exact("b") is None
        assert cache.get_exact("a") == "A"
        assert cache.get_exact("c") == "C"

    def test_semantic_hit_on_a_near_duplicate(self):
        cache = ResponseCache(semantic_threshold=0.9)
        vec = np.array([1.0, 0.0, 0.0])
        cache.put("k", "答案", embedding=vec)

        near = np.array([0.99, 0.05, 0.0])
        assert cache.get_semantic(near) == "答案"
        assert cache.hits_semantic == 1

    def test_semantic_miss_below_the_threshold(self):
        cache = ResponseCache(semantic_threshold=0.9)
        cache.put("k", "答案", embedding=np.array([1.0, 0.0, 0.0]))
        # 45 degrees away -> cosine ~0.707, well under 0.9
        assert cache.get_semantic(np.array([1.0, 1.0, 0.0])) is None

    def test_entries_without_an_embedding_are_not_semantically_matchable(self):
        cache = ResponseCache(semantic_threshold=0.5)
        cache.put("k", "答案")  # no embedding
        assert cache.get_semantic(np.array([1.0, 0.0, 0.0])) is None

    def test_stats_counts_hits_and_misses(self):
        cache = ResponseCache()
        cache.put("k", "v")
        cache.get_exact("k")
        cache.misses += 1
        stats = cache.stats()
        assert stats["hits_exact"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate"] == 0.5

    def test_stats_hit_rate_is_zero_when_unused(self):
        assert ResponseCache().stats()["hit_rate"] == 0.0


# --------------------------------------------------------------------------- #
# The hard switch — nothing may leave the process when the LLM is off
# --------------------------------------------------------------------------- #

class TestHardSwitch:
    def test_unavailable_gateway_never_calls_out(self, monkeypatch):
        gateway = LlmGateway()
        monkeypatch.setattr(settings, "llm_enabled", False)
        monkeypatch.setattr(settings, "llm_api_key", "sk-" + "x" * 40)

        def _explode():  # pragma: no cover - must never run
            raise AssertionError("the client was built despite LLM_ENABLED=false")

        monkeypatch.setattr(gateway, "_get_client", _explode)

        text, meta = gateway.complete(purpose="rag", system="s", user="u")
        assert text is None
        assert meta["llm_used"] is False
        assert meta["cache_hit"] is False
        assert gateway.api_calls == 0

    def test_missing_key_counts_as_unavailable(self, monkeypatch):
        gateway = LlmGateway()
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "")
        assert gateway.available is False

    def test_placeholder_key_counts_as_unavailable(self, monkeypatch):
        """.env.example ships a placeholder; a copy-paste must not cause calls."""
        gateway = LlmGateway()
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "sk-your-key-here")
        assert gateway.available is False


# --------------------------------------------------------------------------- #
# The call path, driven through a fake client
# --------------------------------------------------------------------------- #

class _FakeUsage:
    prompt_tokens = 120
    completion_tokens = 60


class _FakeMessage:
    content = "模型生成的回答"


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, counter: dict):
        self._counter = counter
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self._counter["n"] += 1
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeChat:
    def __init__(self, counter):
        self.completions = _FakeCompletions(counter)


class _FakeClient:
    def __init__(self, counter):
        self.chat = _FakeChat(counter)


@pytest.fixture
def enabled_gateway(monkeypatch):
    """A gateway that looks configured, wired to a fake client and its counter."""
    gateway = LlmGateway()
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "sk-" + "t" * 40)
    counter = {"n": 0}
    client = _FakeClient(counter)
    monkeypatch.setattr(gateway, "_get_client", lambda: client)
    return gateway, counter, client


class TestCallPath:
    def test_successful_call_records_usage(self, enabled_gateway):
        gateway, counter, _ = enabled_gateway
        text, meta = gateway.complete(purpose="rag", system="s", user="u")

        assert text == "模型生成的回答"
        assert meta["llm_used"] is True
        assert meta["cache_hit"] is False
        assert meta["prompt_tokens"] == 120
        assert meta["completion_tokens"] == 60
        assert counter["n"] == 1
        assert gateway.api_calls == 1
        assert gateway.total_prompt_tokens == 120
        assert gateway.total_completion_tokens == 60

    def test_second_identical_call_is_served_from_cache(self, enabled_gateway):
        """The core cost guarantee: the same prompt is paid for exactly once."""
        gateway, counter, _ = enabled_gateway
        gateway.complete(purpose="rag", system="s", user="u")
        text, meta = gateway.complete(purpose="rag", system="s", user="u")

        assert text == "模型生成的回答"
        assert meta["cache_hit"] is True
        assert meta["llm_used"] is False
        assert counter["n"] == 1, "the API was called twice for one prompt"
        assert gateway.api_calls == 1

    def test_a_trivial_rephrasing_hits_the_exact_cache(self, enabled_gateway):
        gateway, counter, _ = enabled_gateway
        gateway.complete(purpose="qa_direct", system="s", user="u",
                         cache_payload="direct::乳腺癌怎么筛查")
        _, meta = gateway.complete(purpose="qa_direct", system="s", user="u",
                                   cache_payload="direct::乳腺癌，怎么筛查？")
        assert meta["cache_hit"] is True
        assert counter["n"] == 1

    def test_cache_payload_decouples_from_the_prompt(self, enabled_gateway):
        """Different injected context, same question -> still one paid call.

        This is what makes the comparison cheap to re-run: `llm_direct` caches
        on the question alone, so re-comparing never re-bills.
        """
        gateway, counter, _ = enabled_gateway
        gateway.complete(purpose="llm_rag", system="s1", user="context A + q",
                         cache_payload="q")
        gateway.complete(purpose="llm_rag", system="s2", user="context B + q",
                         cache_payload="q")
        assert counter["n"] == 1

    def test_semantic_cache_avoids_a_second_call(self, enabled_gateway):
        gateway, counter, _ = enabled_gateway
        vec = np.array([1.0, 0.0, 0.0])
        embed = lambda texts: [vec for _ in texts]  # noqa: E731

        gateway.complete(purpose="qa_direct", system="s", user="u1",
                         cache_payload="q1", embed_fn=embed)
        text, meta = gateway.complete(purpose="qa_direct", system="s", user="u2",
                                      cache_payload="q2", embed_fn=embed)

        assert text == "模型生成的回答"
        assert meta["cache_hit"] is True
        assert counter["n"] == 1
        assert gateway.cache.hits_semantic == 1

    def test_api_failure_degrades_to_none_instead_of_raising(self, monkeypatch):
        """A dead upstream must not 500 the endpoint — the local path still works."""
        gateway = LlmGateway()
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_api_key", "sk-" + "t" * 40)

        class _Boom:
            def create(self, **kwargs):
                raise RuntimeError("upstream is down")

        class _BoomClient:
            def __init__(self):
                self.chat = type("C", (), {"completions": _Boom()})()

        monkeypatch.setattr(gateway, "_get_client", lambda: _BoomClient())

        text, meta = gateway.complete(purpose="rag", system="s", user="u")
        assert text is None
        assert meta["llm_used"] is False
        assert gateway.api_calls == 0

    def test_empty_completion_is_not_cached(self, enabled_gateway, monkeypatch):
        gateway, counter, client = enabled_gateway

        class _Empty:
            content = "   "
        client.chat.completions.create = lambda **kw: type(
            "R", (), {"choices": [type("C", (), {"message": _Empty()})()],
                      "usage": None}
        )()

        assert gateway.complete(purpose="rag", system="s", user="u")[0] is None
        assert gateway.cache.stats()["size"] == 0


class TestHealth:
    def test_health_reports_disabled_state(self, monkeypatch):
        gateway = LlmGateway()
        monkeypatch.setattr(settings, "llm_enabled", False)
        monkeypatch.setattr(settings, "llm_api_key", "")
        health = gateway.health()
        assert health["available"] is False
        assert health["model"] is None
        assert health["api_calls_this_process"] == 0

    def test_health_exposes_cache_stats(self, enabled_gateway):
        gateway, _, _ = enabled_gateway
        gateway.complete(purpose="rag", system="s", user="u")
        gateway.complete(purpose="rag", system="s", user="u")
        health = gateway.health()
        assert health["available"] is True
        assert health["model"] == settings.llm_model
        assert health["cache"]["hits_exact"] == 1


class TestRateLimiter:
    """Unit-tested directly: the suite raises the limits globally (see conftest)."""

    def test_allows_up_to_the_limit_then_blocks(self):
        from app.core.deps import RateLimiter

        limiter = RateLimiter(times=3, seconds=60, scope="unit")
        assert all(limiter.check("u:1")[0] for _ in range(3))
        allowed, retry_after = limiter.check("u:1")
        assert allowed is False
        assert retry_after >= 1

    def test_keys_are_independent(self):
        from app.core.deps import RateLimiter

        limiter = RateLimiter(times=1, seconds=60, scope="unit")
        assert limiter.check("u:1")[0] is True
        assert limiter.check("u:2")[0] is True
        assert limiter.check("u:1")[0] is False

    @pytest.mark.parametrize(
        "expr,expected",
        [("60/minute", (60, 60)), ("12/minute", (12, 60)), ("5/hour", (5, 3600)),
         ("100/day", (100, 86400)), ("garbage", (60, 60))],
    )
    def test_parse_rate(self, expr, expected):
        from app.core.deps import parse_rate

        assert parse_rate(expr) == expected
