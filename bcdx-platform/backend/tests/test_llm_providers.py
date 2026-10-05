"""Provider catalogue, offline demo transport, and multi-model comparison.

The external-API path is the one piece of this project that cannot be exercised
by accident: with no key configured it collapses to `skipped` in every test, so
the code that actually builds a request, parses a response, counts tokens and
classifies a failure would otherwise never run. These tests make it run — not
against a hand-written stub that might not resemble a real service, but through
the OpenAI SDK and `httpx.MockTransport`, which is the same code path as a real
call minus the socket.

What is deliberately covered:

* the provider catalogue, including the precedence rules that decide which base
  URL wins when both a preset and an environment variable are set;
* `classify_error`, because "调用失败" is not an actionable message and the
  whole point of the taxonomy is that a 404 and a 401 need different fixes;
* the demo transport's honesty — every answer carries the watermark, and the
  demo never produces medical content;
* that the cache is keyed by model, so comparing two models does not silently
  return the first model's answer twice;
* that the *semantic* cache does not leak answers across call sites, which
  would collapse the one comparison the feature exists to make.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services import llm_providers as providers
from app.services.llm_gateway import LlmGateway, ResponseCache, get_gateway, prompt_key
from app.services.llm_mock import (
    DEMO_WATERMARK,
    FAULTS,
    build_answer,
    build_transport,
    count_tokens_approx,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

class _StatusError(Exception):
    """Stands in for an SDK exception: `classify_error` reads `status_code`."""

    def __init__(self, code: int, text: str = ""):
        self.status_code = code
        super().__init__(text or f"HTTP {code}")


@pytest.fixture
def demo_gateway(monkeypatch):
    """A gateway wired to the offline demo transport, with a clean cache."""
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")
    return LlmGateway()


@pytest.fixture
def demo_api(monkeypatch):
    """The app's gateway, switched to the demo provider for one test.

    `conftest` has already replaced the singleton with a fresh instance, so this
    only has to point it somewhere offline.
    """
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")
    return get_gateway()


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #

class TestProviderCatalogue:
    def test_ids_match_their_keys(self):
        for key, preset in providers.PROVIDERS.items():
            assert preset.id == key

    def test_expected_providers_are_present(self):
        for pid in ("deepseek", "openai", "qwen", "moonshot", "zhipu",
                    "ollama", "mock", "custom"):
            assert pid in providers.PROVIDERS

    def test_every_preset_explains_itself(self):
        for preset in providers.PROVIDERS.values():
            assert preset.label
            assert preset.note, f"{preset.id} has no note for the picker"

    def test_named_remote_presets_have_a_full_url(self):
        for pid, preset in providers.PROVIDERS.items():
            if pid == "custom":
                continue
            assert preset.base_url.startswith(("http://", "https://")), pid
            assert "://" in preset.base_url and len(preset.base_url) > 10

    def test_keyless_providers(self):
        assert providers.PROVIDERS["mock"].requires_key is False
        assert providers.PROVIDERS["ollama"].requires_key is False
        assert providers.PROVIDERS["deepseek"].requires_key is True

    def test_free_providers_are_priced_at_zero(self):
        for pid in ("mock", "ollama"):
            preset = providers.PROVIDERS[pid]
            assert preset.price_prompt_per_1k == 0.0
            assert preset.price_completion_per_1k == 0.0

    def test_presets_are_immutable(self):
        with pytest.raises(Exception):
            providers.PROVIDERS["deepseek"].base_url = "http://evil.local"  # type: ignore[misc]

    def test_public_catalogue_exposes_only_the_declared_fields(self, monkeypatch):
        """Whitelist rather than blacklist: a new field must be a decision.

        Substring-sniffing for "api_key" would be both too weak (it appears in
        harmless console URLs) and too easy to defeat. Pinning the exact field
        set means any addition to the public payload has to be deliberate.
        """
        monkeypatch.setattr(settings, "llm_api_key", "sk-" + "z" * 40)
        expected = {
            "id", "label", "base_url", "default_model", "requires_key", "is_demo",
            "price_prompt_per_1k", "price_completion_per_1k", "console_url", "note",
        }
        entries = providers.list_presets()
        assert entries
        for entry in entries:
            assert set(entry) == expected, entry["id"]

    def test_public_catalogue_never_carries_the_key(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "sk-supersecret0000111122223333")
        assert "supersecret" not in repr(providers.list_presets())

    def test_unknown_provider_falls_back_and_says_so(self):
        resolved = providers.resolve("definitely-not-a-provider")
        assert resolved.id == providers.DEFAULT_PROVIDER
        assert resolved.unknown_provider == "definitely-not-a-provider"

    def test_known_provider_reports_no_fallback(self):
        assert providers.resolve("openai").unknown_provider is None


class TestResolutionPrecedence:
    """The rules that decide which endpoint a request actually reaches."""

    def test_named_preset_keeps_its_own_url(self, monkeypatch):
        """A stale LLM_BASE_URL must not redirect a freshly chosen provider.

        This is the bug the narrow precedence exists to prevent: the request
        would go to the previous service, fail with a 401, and read as an
        expired key rather than as a leftover setting.
        """
        monkeypatch.setattr(settings, "llm_base_url", "https://stale.example.com/v1")
        monkeypatch.setattr(settings, "llm_provider", "openai")
        assert providers.resolve().base_url == "https://api.openai.com/v1"

    def test_named_preset_accepts_a_model_override(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_model", "deepseek-reasoner")
        resolved = providers.resolve()
        assert resolved.model == "deepseek-reasoner"
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.model_overridden is True

    def test_model_override_equal_to_the_default_is_not_flagged(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_model", "deepseek-chat")
        assert providers.resolve().model_overridden is False

    def test_custom_uses_both_env_values(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "custom")
        monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:8080/v1")
        monkeypatch.setattr(settings, "llm_model", "local-model")
        resolved = providers.resolve()
        assert resolved.base_url == "http://127.0.0.1:8080/v1"
        assert resolved.model == "local-model"
        assert resolved.base_url_overridden is True

    def test_custom_without_an_endpoint_is_not_ready(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "custom")
        monkeypatch.setattr(settings, "llm_base_url", "")
        resolved = providers.resolve()
        assert resolved.has_endpoint is False
        assert providers.is_ready(resolved) is False

    def test_demo_ignores_env_overrides_entirely(self, monkeypatch):
        """Otherwise a mock run would inherit the real provider's base URL.

        The demo transport is keyed off `is_demo`, not off the URL, so a
        leftover `LLM_BASE_URL` is harmless to the call — but it is not harmless
        to the *display*: the table would claim the answer came from DeepSeek.
        """
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "llm_base_url", "https://api.deepseek.com")
        monkeypatch.setattr(settings, "llm_model", "deepseek-chat")
        resolved = providers.resolve()
        assert resolved.base_url == "http://mock.local/v1"
        assert resolved.model == "demo-model"
        assert resolved.is_demo is True
        assert resolved.base_url_overridden is False
        assert resolved.model_overridden is False

    def test_provider_id_is_case_and_space_insensitive(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "  OpenAI  ")
        assert providers.resolve().id == "openai"


class TestReadiness:
    def test_missing_key_blocks_a_keyed_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "")
        assert providers.is_ready() is False

    def test_placeholder_key_does_not_count(self, monkeypatch):
        """`.env.example` ships a placeholder; copying it must not enable billing."""
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "sk-your-key-here-replace-me")
        assert settings.llm_configured is False
        assert providers.is_ready() is False

    def test_a_real_looking_key_unblocks_it(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "sk-" + "a" * 40)
        assert providers.is_ready() is True

    def test_keyless_provider_is_ready_without_a_key(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "")
        assert providers.is_ready(providers.resolve("ollama")) is True


class TestKeyMasking:
    def test_absent_key_masks_to_none(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_api_key", "")
        assert providers.mask_key() is None

    def test_long_key_shows_only_the_ends(self):
        masked = providers.mask_key("sk-abcdefghijklmnopqrstuvwxyz0123456789")
        assert masked.startswith("sk-a")
        assert masked.endswith("6789")
        assert "defghijklm" not in masked

    def test_short_key_is_fully_hidden(self):
        """A 10-character key would be mostly legible if the ends were shown."""
        masked = providers.mask_key("shortkey12")
        assert masked == "*" * 10
        assert "short" not in masked

    def test_masking_a_boundary_length(self):
        assert providers.mask_key("x" * 12) == "*" * 12
        assert providers.mask_key("y" * 13).startswith("yyyy")


class TestErrorTaxonomy:
    def test_every_kind_has_an_actionable_message(self):
        for kind, message in providers.ERROR_KINDS.items():
            assert message and len(message) > 10, kind
            assert message != providers.ERROR_KINDS["unknown"] or kind == "unknown"

    @pytest.mark.parametrize("code,expected", [
        (401, "invalid_key"),
        (402, "quota"),
        (403, "forbidden"),
        (404, "endpoint_not_found"),
        (429, "rate_limited"),
        (500, "server_error"),
        (503, "server_error"),
    ])
    def test_status_codes_map_to_kinds(self, code, expected):
        assert providers.classify_error(_StatusError(code)) == expected

    def test_400_mentioning_a_model_is_a_model_problem(self):
        exc = _StatusError(400, "The model `gpt-9` does not exist")
        assert providers.classify_error(exc) == "model_not_found"

    def test_400_without_a_model_stays_generic(self):
        assert providers.classify_error(_StatusError(400, "bad temperature")) == "bad_request"

    def test_unmapped_client_error_stays_bad_request(self):
        assert providers.classify_error(_StatusError(418)) == "bad_request"

    def test_reads_status_from_a_nested_response_object(self):
        class _WithResponse(Exception):
            response = _StatusError(404)

        assert providers.classify_error(_WithResponse()) == "endpoint_not_found"

    def test_timeouts_are_recognised_by_class_name(self):
        class APITimeoutError(Exception):
            pass

        assert providers.classify_error(APITimeoutError("slow")) == "timeout"

    def test_connection_failures_are_recognised(self):
        class APIConnectionError(Exception):
            pass

        assert providers.classify_error(APIConnectionError("refused")) == "connection"

    def test_http_transport_errors_count_as_connections(self):
        request = httpx.Request("POST", "https://example.com/v1/chat/completions")
        assert providers.classify_error(httpx.ConnectError("nope", request=request)) == "connection"

    def test_real_openai_errors_are_classified(self):
        """The taxonomy must work on the SDK's own exceptions, not just lookalikes."""
        from openai import AuthenticationError, RateLimitError

        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        auth = AuthenticationError(
            "Incorrect API key",
            response=httpx.Response(401, request=request),
            body=None,
        )
        assert providers.classify_error(auth) == "invalid_key"

        limited = RateLimitError(
            "slow down",
            response=httpx.Response(429, request=request),
            body=None,
        )
        assert providers.classify_error(limited) == "rate_limited"

    def test_message_about_the_api_key_without_a_status(self):
        assert providers.classify_error(RuntimeError("No api_key provided")) == "missing_key"

    def test_unrecognised_failures_fall_back(self):
        assert providers.classify_error(RuntimeError("something odd")) == "unknown"

    def test_explanation_is_structured_and_truncated(self):
        info = providers.explain_error(_StatusError(429, "x" * 2000))
        assert info["kind"] == "rate_limited"
        assert info["type"] == "_StatusError"
        assert len(info["detail"]) == 500


# --------------------------------------------------------------------------- #
# Demo transport
# --------------------------------------------------------------------------- #

class TestDemoTransport:
    def test_watermark_is_always_the_first_line(self):
        for prompt in (
            "用户问题：乳腺癌怎么筛查",
            "参考资料：\n[^c1] 《A》\n内容\n\n用户问题：q",
            "只回复两个字：正常",
        ):
            answer = build_answer(prompt)
            assert answer.splitlines()[0] == DEMO_WATERMARK

    def test_every_answer_states_it_is_not_a_model(self):
        answer = build_answer("用户问题：乳腺癌怎么筛查")
        assert "未经过任何语言模型" in answer

    def test_grounded_answer_names_the_passages(self):
        prompt = (
            "参考资料：\n[^c1] 《乳腺癌筛查要点》\n钼靶与超声，按年龄分层。\n\n"
            "[^c2] 《乳腺影像》\nBI-RADS 分级描述恶性可能性。\n\n"
            "用户问题：怎么筛查\n\n请基于以上资料作答，并保留 [^cN] 引用标记。"
        )
        answer = build_answer(prompt)
        assert "[^1]" in answer and "[^2]" in answer
        assert "乳腺癌筛查要点" in answer and "乳腺影像" in answer
        assert "本次收到 2 段参考资料" in answer

    def test_compound_terms_survive_keyword_extraction(self):
        """`BI-RADS` split into `BI` and `RADS` would be a visible defect."""
        prompt = "参考资料：\n[^c1] 《X》\nBI-RADS 分级。\n\n用户问题：q"
        assert "BI-RADS" in build_answer(prompt)

    def test_ungrounded_answer_does_not_invent_medical_content(self):
        answer = build_answer("用户问题：乳腺癌怎么筛查")
        # It may echo the question, but it must not answer it.
        assert "钼靶" not in answer and "BI-RADS" not in answer
        assert "留空" in answer

    def test_a_short_prompt_gets_a_short_reply(self):
        """A connectivity check must not come back as a full-length essay.

        The absolute number matters less than the ratio: the watermark alone is
        ~45 tokens, so the assertion is that the whole probe reply stays well
        under what a real question produces.
        """
        short = build_answer("只回复两个字：正常")
        long_form = build_answer("用户问题：乳腺癌的早期症状有哪些")
        assert count_tokens_approx(short) < 130
        assert count_tokens_approx(short) < count_tokens_approx(long_form)
        assert "演示通道连通" in short

    def test_token_estimate_is_deterministic_and_monotonic(self):
        assert count_tokens_approx("") == 0
        assert count_tokens_approx("你好") == 2
        assert count_tokens_approx("abcd") == 1
        assert count_tokens_approx("a" * 100) == 25
        assert count_tokens_approx("你好世界") > count_tokens_approx("你好")

    def test_response_has_the_openai_shape(self):
        transport = build_transport(model="demo-model")
        client = httpx.Client(transport=transport)
        res = client.post(
            "http://mock.local/v1/chat/completions",
            json={
                "model": "demo-model",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "用户问题：q"},
                ],
            },
        )
        body = res.json()
        assert res.status_code == 200
        assert body["object"] == "chat.completion"
        assert body["model"] == "demo-model"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
        assert res.headers["x-demo-mode"] == "true"

    def test_identical_requests_produce_identical_bodies(self):
        transport = build_transport()
        client = httpx.Client(transport=transport)
        payload = {"model": "m", "messages": [{"role": "user", "content": "用户问题：q"}]}
        first = client.post("http://mock.local/v1/chat/completions", json=payload).json()
        second = client.post("http://mock.local/v1/chat/completions", json=payload).json()
        assert first == second, "the demo must be reproducible to be a useful fixture"

    def test_models_endpoint_is_served(self):
        client = httpx.Client(transport=build_transport(model="demo-model"))
        body = client.get("http://mock.local/v1/models").json()
        assert body["data"][0]["id"] == "demo-model"

    @pytest.mark.parametrize("fault,expected_status", [
        ("invalid_key", 401),
        ("forbidden", 403),
        ("endpoint_not_found", 404),
        ("rate_limited", 429),
        ("quota", 402),
        ("server_error", 500),
        ("bad_request", 400),
    ])
    def test_status_faults_are_injected(self, fault, expected_status):
        client = httpx.Client(transport=build_transport(fault=fault))
        res = client.post("http://mock.local/v1/chat/completions", json={"messages": []})
        assert res.status_code == expected_status
        assert "error" in res.json()

    def test_transport_faults_raise(self):
        client = httpx.Client(transport=build_transport(fault="timeout"))
        with pytest.raises(httpx.ReadTimeout):
            client.post("http://mock.local/v1/chat/completions", json={"messages": []})

        client = httpx.Client(transport=build_transport(fault="connection"))
        with pytest.raises(httpx.ConnectError):
            client.post("http://mock.local/v1/chat/completions", json={"messages": []})

    def test_garbage_fault_returns_non_json(self):
        client = httpx.Client(transport=build_transport(fault="garbage"))
        res = client.post("http://mock.local/v1/chat/completions", json={"messages": []})
        assert res.status_code == 200
        with pytest.raises(Exception):
            res.json()

    def test_empty_fault_returns_an_empty_completion(self):
        client = httpx.Client(transport=build_transport(fault="empty"))
        body = client.post(
            "http://mock.local/v1/chat/completions", json={"messages": []}
        ).json()
        assert body["choices"][0]["message"]["content"] == ""

    def test_every_declared_fault_is_handled(self):
        """Every declared fault must actually change the outcome.

        Rebuilding the transport for each name is not enough: that passes even
        when a fault is silently ignored, which is precisely the failure mode
        `LLM_MOCK_FAULT` exists to be immune to.
        """

        def outcome(fault: str | None) -> tuple:
            client = httpx.Client(transport=build_transport(fault=fault))
            payload = {"messages": [{"role": "user", "content": "hi"}]}
            try:
                res = client.post(
                    "http://mock.local/v1/chat/completions", json=payload
                )
            except (httpx.ReadTimeout, httpx.ConnectError) as exc:
                return ("raised", type(exc).__name__)
            try:
                body = res.json()
            except ValueError:
                return ("non-json", res.status_code)
            if res.status_code != 200:
                return ("status", res.status_code)
            content = body["choices"][0]["message"]["content"]
            return ("empty" if content == "" else "text", content[:20])

        healthy = outcome(None)
        assert healthy[0] == "text"  # sanity: the baseline really is an answer
        for fault in FAULTS:
            assert outcome(fault) != healthy, f"fault {fault!r} behaved like success"

    def test_an_unknown_fault_is_ignored_but_announced(self, caplog):
        """A misspelt fault must not pass silently.

        Ignoring it quietly would show the reader a healthy demo call and let
        them conclude the error path is broken, so the transport logs it.
        """
        with caplog.at_level("WARNING"):
            transport = build_transport(fault="no-such-fault")

        assert "no-such-fault" in caplog.text
        res = httpx.Client(transport=transport).post(
            "http://mock.local/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert res.status_code == 200  # falls back to the normal demo answer

    def test_the_configured_fault_reaches_the_gateway(self, monkeypatch):
        """`LLM_MOCK_FAULT` is the only way to reproduce an error by hand.

        Without it the taxonomy is only reachable from unit tests, so a reader
        can never verify the claim that the panel explains *why* a call failed.
        """
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "llm_mock_fault", "quota")
        gateway = LlmGateway()

        result = gateway.probe()
        assert result["ok"] is False
        assert result["error_kind"] == "quota"
        assert gateway.health()["mock_fault"] == "quota"

    def test_the_fault_setting_is_ignored_by_a_real_provider(self, monkeypatch):
        """Fault injection must not be able to break a real integration."""
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_mock_fault", "quota")
        assert LlmGateway().health()["mock_fault"] is None


# --------------------------------------------------------------------------- #
# Gateway against the demo transport
# --------------------------------------------------------------------------- #

class TestGatewayWithDemoProvider:
    def test_demo_makes_the_external_path_available(self, demo_gateway):
        assert demo_gateway.available is True
        assert demo_gateway.provider.is_demo is True

    def test_probe_succeeds_and_costs_nothing(self, demo_gateway):
        result = demo_gateway.probe()
        assert result["ok"] is True
        assert result["error_kind"] is None
        assert result["prompt_tokens"] > 0
        assert result["completion_tokens"] > 0
        assert result["cost_cny"] == 0.0
        assert result["is_demo"] is True
        assert result["provider"] == "mock"

    def test_probe_reply_is_short(self, demo_gateway):
        assert len(demo_gateway.probe()["reply"]) < 200

    def test_complete_returns_the_demo_text(self, demo_gateway):
        text, meta = demo_gateway.complete(
            purpose="qa_direct", system="s", user="用户问题：q",
            cache_payload="direct::q",
        )
        assert text is not None
        assert text.startswith(DEMO_WATERMARK)
        assert meta["llm_used"] is True
        assert meta["cache_hit"] is False
        assert meta["provider"] == "mock"
        assert meta["model"] == "demo-model"

    def test_repeat_call_hits_the_cache(self, demo_gateway):
        kwargs = dict(purpose="qa_direct", system="s", user="用户问题：q",
                      cache_payload="direct::q")
        demo_gateway.complete(**kwargs)
        assert demo_gateway.api_calls == 1
        _, meta = demo_gateway.complete(**kwargs)
        assert meta["cache_hit"] is True
        assert meta["llm_used"] is False
        assert demo_gateway.api_calls == 1, "a cached prompt was paid for twice"

    def test_a_different_model_is_not_a_cache_hit(self, demo_gateway):
        """Regression: the model has to be part of the cache identity.

        Without it, comparing `a` and `b` on one question returns `a`'s answer
        for both columns and the second model is never called at all.
        """
        kwargs = dict(purpose="qa_direct", system="s", user="用户问题：q",
                      cache_payload="direct::q")
        demo_gateway.complete(**kwargs, model="model-a")
        _, meta = demo_gateway.complete(**kwargs, model="model-b")
        assert meta["cache_hit"] is False
        assert meta["llm_used"] is True
        assert demo_gateway.api_calls == 2

    def test_the_second_model_really_runs(self, demo_gateway):
        kwargs = dict(purpose="qa_direct", system="s", user="用户问题：q",
                      cache_payload="direct::q")
        first, _ = demo_gateway.complete(**kwargs, model="model-a")
        second, _ = demo_gateway.complete(**kwargs, model="model-b")
        assert first is not None and second is not None
        # The demo signs its output with the model it was asked for, so the two
        # columns are provably distinct answers rather than one repeated twice.
        assert "model-a" in first
        assert "model-b" in second
        assert first != second

    def test_the_semantic_cache_does_not_cross_call_sites(self, demo_gateway):
        """Regression: `rag` and `qa_direct` embed nearly the same payload.

        Both derive their cache payload from the user's question, so their
        vectors sit at a cosine similarity near 1.0. An unscoped semantic lookup
        would serve the retrieval-grounded answer to the path that deliberately
        has no retrieval — collapsing exactly the comparison this feature exists
        to make.
        """
        embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]  # noqa: E731

        rag_text, _ = demo_gateway.complete(
            purpose="rag", system="s", user="ctx + q",
            cache_payload="乳腺癌怎么筛查", embed_fn=embed,
        )
        direct_text, meta = demo_gateway.complete(
            purpose="qa_direct", system="s", user="用户问题：乳腺癌怎么筛查",
            cache_payload="乳腺癌怎么筛查", embed_fn=embed,
        )
        assert rag_text and direct_text
        assert meta["cache_hit"] is False, "the direct path was served the RAG answer"
        assert meta["llm_used"] is True

    def test_same_call_site_still_gets_a_semantic_hit(self, demo_gateway):
        embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]  # noqa: E731
        demo_gateway.complete(purpose="rag", system="s", user="ctx", cache_payload="q1",
                              embed_fn=embed)
        demo_gateway.complete(purpose="rag", system="s", user="ctx", cache_payload="q2",
                              embed_fn=embed)
        assert demo_gateway.api_calls == 1

    @pytest.mark.parametrize("fault,expected_kind", [
        ("invalid_key", "invalid_key"),
        ("endpoint_not_found", "endpoint_not_found"),
        ("rate_limited", "rate_limited"),
        ("quota", "quota"),
        ("forbidden", "forbidden"),
        ("server_error", "server_error"),
        ("bad_request", "bad_request"),
    ])
    def test_faults_surface_a_specific_kind(self, monkeypatch, fault, expected_kind):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()
        monkeypatch.setattr(
            gateway, "_get_client",
            lambda: __import__("openai").OpenAI(
                api_key="x" * 30, base_url="http://mock.local/v1",
                max_retries=0,
                http_client=httpx.Client(transport=build_transport(fault=fault)),
            ),
        )
        text, meta = gateway.complete(purpose="qa_direct", system="s", user="u",
                                      cache_payload="q")
        assert text is None
        assert meta["llm_used"] is False
        assert meta["error"]["kind"] == expected_kind
        assert meta["error"]["message"] == providers.message_for(expected_kind)

    def test_a_failure_is_remembered_and_a_success_clears_it(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()

        from openai import OpenAI

        bad = OpenAI(api_key="x" * 30, base_url="http://mock.local/v1", max_retries=0,
                     http_client=httpx.Client(transport=build_transport(fault="invalid_key")))
        monkeypatch.setattr(gateway, "_get_client", lambda: bad)
        gateway.complete(purpose="qa_direct", system="s", user="u")
        assert gateway.last_error is not None
        assert gateway.last_error["kind"] == "invalid_key"
        assert gateway.failures == 1

        monkeypatch.setattr(gateway, "_get_client", lambda: OpenAI(
            api_key="x" * 30, base_url="http://mock.local/v1", max_retries=0,
            http_client=httpx.Client(transport=build_transport())))
        gateway.complete(purpose="qa_direct", system="s", user="u2")
        assert gateway.last_error is None

    def test_a_timeout_fault_is_classified(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()
        from openai import OpenAI

        monkeypatch.setattr(gateway, "_get_client", lambda: OpenAI(
            api_key="x" * 30, base_url="http://mock.local/v1", max_retries=0,
            http_client=httpx.Client(transport=build_transport(fault="timeout"))))
        _, meta = gateway.complete(purpose="qa_direct", system="s", user="u")
        assert meta["error"]["kind"] in {"timeout", "connection"}

    def test_an_empty_completion_counts_as_a_spent_call_but_no_answer(
        self, monkeypatch
    ):
        """`llm_used` means "a request was made and billed", not "we got text".

        A 200 with an empty body really did cost tokens — a content filter or a
        reasoning-only response produces exactly this. Reporting `llm_used=False`
        would understate the bill; reporting a non-None answer would invent one.
        Callers treat the `None` text as a failure, which is what the path
        runners check.
        """
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()
        from openai import OpenAI

        monkeypatch.setattr(gateway, "_get_client", lambda: OpenAI(
            api_key="x" * 30, base_url="http://mock.local/v1", max_retries=0,
            http_client=httpx.Client(transport=build_transport(fault="empty"))))
        text, meta = gateway.complete(purpose="qa_direct", system="s", user="u")
        assert text is None
        assert meta["llm_used"] is True
        assert gateway.api_calls == 1
        assert gateway.cache.stats()["size"] == 0, "an empty answer was cached"

    def test_health_describes_the_provider(self, demo_gateway):
        health = demo_gateway.health()
        assert health["provider"] == "mock"
        assert health["is_demo"] is True
        assert health["available"] is True
        assert health["ready"] is True
        assert health["requires_key"] is False
        assert health["key_masked"] is None
        assert health["model"] == "demo-model"
        assert health["base_url"] == "http://mock.local/v1"

    def test_health_never_exposes_the_key(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "sk-verysecretvalue1234567890")
        blob = repr(LlmGateway().health())
        assert "verysecretvalue" not in blob
        assert "sk-v" in blob  # the masked form is present instead

    def test_the_client_is_rebuilt_when_the_provider_changes(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()
        first = gateway._get_client()
        assert gateway._get_client() is first, "unchanged config must reuse the client"

        monkeypatch.setattr(settings, "llm_provider", "ollama")
        second = gateway._get_client()
        assert second is not first, "a stale client would post to the old service"

    def test_probe_needs_no_network_build_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", False)
        monkeypatch.setattr(settings, "llm_provider", "mock")
        gateway = LlmGateway()
        monkeypatch.setattr(
            gateway, "_get_client",
            lambda: pytest.fail("a disabled gateway must not build a client"),
        )
        result = gateway.probe()
        assert result["ok"] is False
        assert result["error_kind"] == "disabled"

    def test_probe_reports_a_missing_key_without_calling(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "")
        gateway = LlmGateway()
        monkeypatch.setattr(
            gateway, "_get_client",
            lambda: pytest.fail("a keyless provider must not be contacted"),
        )
        result = gateway.probe()
        assert result["ok"] is False
        assert result["error_kind"] == "missing_key"
        assert gateway.api_calls == 0

    def test_probe_reports_a_missing_endpoint(self, monkeypatch):
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "custom")
        monkeypatch.setattr(settings, "llm_base_url", "")
        result = LlmGateway().probe()
        assert result["error_kind"] == "no_endpoint"

    def test_probe_is_not_served_from_cache(self, demo_gateway):
        """A cached success would keep reporting healthy after a key was revoked."""
        demo_gateway.probe()
        calls = demo_gateway.api_calls
        demo_gateway.probe()
        assert demo_gateway.api_calls == calls + 1

    def test_probe_counts_its_tokens(self, demo_gateway):
        before = demo_gateway.total_prompt_tokens
        result = demo_gateway.probe()
        assert demo_gateway.total_prompt_tokens == before + result["prompt_tokens"]


class TestCacheScoping:
    """Unit-level checks on the two cache layers, independent of the gateway."""

    def test_semantic_lookup_can_be_scoped(self):
        import numpy as np

        cache = ResponseCache()
        vec = np.array([1.0, 0.0, 0.0])
        cache.put("k1", "A", embedding=vec, purpose="rag")
        assert cache.get_semantic(vec, purpose="rag") == "A"
        assert cache.get_semantic(vec, purpose="qa_direct") is None

    def test_unscoped_lookup_keeps_the_old_behaviour(self):
        import numpy as np

        cache = ResponseCache()
        vec = np.array([1.0, 0.0, 0.0])
        cache.put("k1", "A", embedding=vec, purpose="rag")
        assert cache.get_semantic(vec) == "A"

    def test_prompt_key_ignores_punctuation_and_width(self):
        assert prompt_key("rag", "乳腺癌，怎么筛查？") == prompt_key("rag", "乳腺癌怎么筛查")
        assert prompt_key("rag", "ＡＢＣ") == prompt_key("rag", "abc")
        assert prompt_key("rag", "x") != prompt_key("qa_direct", "x")


# --------------------------------------------------------------------------- #
# Multi-model comparison
# --------------------------------------------------------------------------- #

class TestModelListCleaning:
    def test_empty_input_stays_empty(self):
        from app.services.qa_compare import _clean_models

        assert _clean_models(None) == []
        assert _clean_models([]) == []

    def test_whitespace_is_trimmed(self):
        from app.services.qa_compare import _clean_models

        assert _clean_models(["  m1  ", "m2"]) == ["m1", "m2"]

    def test_duplicates_are_dropped_preserving_order(self):
        from app.services.qa_compare import _clean_models

        assert _clean_models(["b", "a", "b", "a"]) == ["b", "a"]

    def test_blank_entries_are_dropped(self):
        from app.services.qa_compare import _clean_models

        assert _clean_models(["", "  ", "m"]) == ["m"]

    @pytest.mark.parametrize("bad", [
        "has space", "semi;colon", "quote\"d", "<script>", "a" * 65, "换行\n符",
    ])
    def test_implausible_model_names_are_rejected(self, bad):
        from app.services.qa_compare import _clean_models

        assert _clean_models([bad]) == []

    @pytest.mark.parametrize("good", [
        "deepseek-chat", "gpt-4o-mini", "qwen2.5:7b", "meta-llama/Llama-3-8B",
        "glm-4-plus", "moonshot-v1-8k",
    ])
    def test_real_model_names_are_accepted(self, good):
        from app.services.qa_compare import _clean_models

        assert _clean_models([good]) == [good]

    def test_the_cap_is_enforced(self, monkeypatch):
        from app.services.qa_compare import _clean_models

        monkeypatch.setattr(settings, "llm_max_compare_models", 2)
        assert _clean_models(["a", "b", "c", "d"]) == ["a", "b"]


@pytest.fixture
def demo_compare(monkeypatch):
    """The app gateway on the demo provider, with cost gates opened.

    `llm_min_chars_for_call` is lowered because the short retrieval a synthetic
    question produces would otherwise trip the cost gate and leave `llm_rag`
    skipped — the gate itself is covered elsewhere, and here it would only hide
    the code under test.
    """
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "llm_min_chars_for_call", 1)
    monkeypatch.setattr(settings, "qa_compare_allow_llm", True)
    return get_gateway()


class TestMultiModelComparison:
    def test_default_keys_are_unchanged(self, demo_compare):
        """Backwards compatibility: no `models` means the original three columns."""
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast")
        assert [p["key"] for p in outcome["paths"]] == ["local_rag", "llm_direct", "llm_rag"]
        assert outcome["models"] == []
        assert outcome["summary"]["models"] == []

    def test_each_model_produces_two_columns(self, demo_compare):
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast", models=["model-a", "model-b"])
        assert [p["key"] for p in outcome["paths"]] == [
            "local_rag",
            "llm_direct@model-a",
            "llm_direct@model-b",
            "llm_rag@model-a",
            "llm_rag@model-b",
        ]

    def test_columns_group_by_path_then_model(self, demo_compare):
        """Direct columns sit next to each other so the table reads as a table."""
        from app.services.qa_compare import compare

        keys = [p["key"] for p in compare("乳腺癌的早期表现有哪些", "breast",
                                         models=["a", "b", "c"])["paths"]]
        assert keys.index("llm_direct@a") < keys.index("llm_direct@b")
        assert keys.index("llm_direct@c") < keys.index("llm_rag@a")

    def test_local_path_runs_once_regardless_of_model_count(self, demo_compare):
        from app.services.qa_compare import compare

        paths = compare("乳腺癌的早期表现有哪些", "breast",
                        models=["a", "b", "c"])["paths"]
        assert sum(1 for p in paths if p["key"] == "local_rag") == 1

    def test_every_column_declares_its_model_and_provider(self, demo_compare):
        from app.services.qa_compare import compare

        paths = compare("乳腺癌的早期表现有哪些", "breast", models=["model-a"])["paths"]
        by_key = {p["key"]: p for p in paths}
        assert by_key["local_rag"]["model"] is None
        assert by_key["local_rag"]["provider"] == ""
        for key in ("llm_direct@model-a", "llm_rag@model-a"):
            assert by_key[key]["model"] == "model-a"
            assert by_key[key]["provider"] == "mock"
            assert by_key[key]["is_mock"] is True

    def test_the_short_label_carries_the_model_name(self, demo_compare):
        """The column header is the only place the model is visible at a glance."""
        from app.services.qa_compare import compare

        paths = compare("乳腺癌的早期表现有哪些", "breast", models=["model-a"])["paths"]
        direct = next(p for p in paths if p["key"] == "llm_direct@model-a")
        assert "model-a" in direct["short"]
        assert "外部直答" in direct["short"]

    def test_only_the_external_paths_are_fanned_out(self, demo_compare):
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast",
                          paths=["local_rag"], models=["a", "b"])
        assert [p["key"] for p in outcome["paths"]] == ["local_rag"]

    def test_a_single_requested_path_fans_out_alone(self, demo_compare):
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast",
                          paths=["llm_direct"], models=["a", "b"])
        assert [p["key"] for p in outcome["paths"]] == ["llm_direct@a", "llm_direct@b"]

    def test_the_cleaned_model_list_is_echoed_back(self, demo_compare):
        """A dropped model must be visible, not silently missing a column."""
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast",
                          models=["  a  ", "a", "bad name", "b"])
        assert outcome["models"] == ["a", "b"]
        assert outcome["summary"]["models"] == ["a", "b"]

    def test_invalid_models_fall_back_to_the_configured_one(self, demo_compare):
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast", models=["bad name!!"])
        assert outcome["models"] == []
        assert [p["key"] for p in outcome["paths"]] == ["local_rag", "llm_direct", "llm_rag"]

    def test_demo_mode_is_flagged_and_free(self, demo_compare):
        from app.services.qa_compare import compare

        summary = compare("乳腺癌的早期表现有哪些", "breast",
                          models=["a", "b"])["summary"]
        assert summary["demo_mode"] is True
        assert summary["cost_cny"] == 0.0
        assert summary["external_calls"] > 0, "the SDK still really ran"

    def test_the_external_columns_actually_produce_answers(self, demo_compare):
        from app.services.qa_compare import compare

        paths = compare("乳腺癌的早期表现有哪些", "breast", models=["a", "b"])["paths"]
        external = [p for p in paths if p["external_call"]]
        assert external
        for path in external:
            assert path["status"] == "ok", path["note"]
            assert path["answer"].startswith(DEMO_WATERMARK)
            assert path["answer_chars"] > 0

    def test_the_grounding_difference_still_shows_under_the_demo(self, demo_compare):
        """The demo is built to preserve the *direction* of the real effect.

        The retrieval-augmented answer is written from the passages and so
        reuses their wording; the direct answer never saw them. A demo that
        scored both the same would teach the reader the wrong thing.
        """
        from app.services.qa_compare import compare

        paths = compare("乳腺癌的早期表现有哪些", "breast", models=["a"])["paths"]
        by_key = {p["key"]: p for p in paths}
        assert by_key["llm_direct@a"]["lexical_overlap"] < \
            by_key["llm_rag@a"]["lexical_overlap"]
        assert by_key["llm_rag@a"]["citation_count"] > 0
        assert by_key["llm_direct@a"]["citation_count"] == 0

    def test_ungrounded_paths_name_the_fanned_out_keys(self, demo_compare):
        from app.services.qa_compare import compare

        summary = compare("乳腺癌的早期表现有哪些", "breast",
                          models=["a", "b"])["summary"]
        assert "llm_direct@a" in summary["ungrounded_paths"]
        assert "llm_direct@b" in summary["ungrounded_paths"]
        assert "local_rag" in summary["grounded_paths"]

    def test_a_greeting_is_still_not_ungrounded(self, demo_compare):
        from app.services.qa_compare import compare

        summary = compare("你好", "breast", models=["a"])["summary"]
        assert summary["ungrounded_paths"] == []

    def test_out_of_scope_questions_skip_every_model_column(self, demo_compare):
        """Cross-disease isolation must not leak through a second model."""
        from app.services.qa_compare import compare

        paths = compare("心肌梗死怎么急救", "breast", models=["a", "b"])["paths"]
        rag_columns = [p for p in paths if p["key"].startswith("llm_rag@")]
        assert rag_columns
        for path in rag_columns:
            assert path["status"] == "skipped"
            assert path["refused"] is True

    def test_qa_compare_allow_llm_off_leaves_only_the_local_path(self, monkeypatch,
                                                                demo_compare):
        monkeypatch.setattr(settings, "qa_compare_allow_llm", False)
        from app.services.qa_compare import compare

        outcome = compare("乳腺癌的早期表现有哪些", "breast", models=["a", "b"])
        assert [p["key"] for p in outcome["paths"]] == ["local_rag"]
        assert outcome["summary"]["external_calls"] == 0


class TestLlmApi:
    def test_the_catalogue_is_public(self, client):
        res = client.get("/api/v1/llm/providers")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data["providers"]) == len(providers.PROVIDERS)
        assert data["default"] == providers.DEFAULT_PROVIDER
        assert data["override_rules"]

    def test_the_catalogue_names_the_active_provider(self, client):
        data = client.get("/api/v1/llm/providers").json()["data"]
        assert data["active"] in providers.PROVIDERS

    def test_status_requires_a_login(self, client):
        assert client.get("/api/v1/llm/status").status_code == 401

    def test_probe_requires_a_login(self, client):
        assert client.post("/api/v1/llm/test").status_code == 401

    def test_status_describes_the_unconfigured_default(self, client, auth_headers):
        res = client.get("/api/v1/llm/status", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["provider"] == "deepseek"
        assert data["available"] is False
        assert data["ready"] is False
        assert data["key_present"] is False
        assert data["key_masked"] is None

    def test_status_reports_the_demo_provider(self, client, auth_headers, demo_api):
        data = client.get("/api/v1/llm/status", headers=auth_headers).json()["data"]
        assert data["provider"] == "mock"
        assert data["is_demo"] is True
        assert data["available"] is True
        assert data["requires_key"] is False
        assert data["max_compare_models"] >= 1

    def test_probe_endpoint_works_against_the_demo(self, client, auth_headers, demo_api):
        res = client.post("/api/v1/llm/test", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ok"] is True
        assert data["provider"] == "mock"
        assert data["cost_cny"] == 0.0
        assert data["error_kind"] is None

    def test_probe_reports_an_actionable_failure(self, client, auth_headers, monkeypatch):
        """With no key configured the probe must explain, not just fail."""
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "llm_provider", "deepseek")
        monkeypatch.setattr(settings, "llm_api_key", "")
        data = client.post("/api/v1/llm/test", headers=auth_headers).json()["data"]
        assert data["ok"] is False
        assert data["error_kind"] == "missing_key"
        assert "LLM_API_KEY" in data["error_message"]

    def test_probe_prefers_the_global_switch_over_the_key(self, client, auth_headers,
                                                         monkeypatch):
        """`disabled` is checked first because it is the more useful answer.

        Telling someone their key is missing while the whole feature is switched
        off would send them to buy a key they do not need.
        """
        monkeypatch.setattr(settings, "llm_enabled", False)
        monkeypatch.setattr(settings, "llm_api_key", "")
        data = client.post("/api/v1/llm/test", headers=auth_headers).json()["data"]
        assert data["error_kind"] == "disabled"

    def test_compare_accepts_a_model_list(self, client, auth_headers, demo_api,
                                          monkeypatch):
        monkeypatch.setattr(settings, "llm_min_chars_for_call", 1)
        res = client.post(
            "/api/v1/rag/compare",
            headers=auth_headers,
            json={
                "question": "乳腺癌的早期表现有哪些",
                "disease": "breast",
                "models": ["model-a", "model-b"],
                "persist": False,
            },
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["models"] == ["model-a", "model-b"]
        keys = [p["key"] for p in data["paths"]]
        assert "llm_direct@model-a" in keys and "llm_rag@model-b" in keys
        assert data["summary"]["demo_mode"] is True

    def test_compare_omitting_models_keeps_three_columns(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/compare",
            headers=auth_headers,
            json={"question": "乳腺癌的早期表现有哪些", "disease": "breast",
                  "persist": False},
        )
        assert res.status_code == 200
        data = res.json()["data"]
        assert [p["key"] for p in data["paths"]] == ["local_rag", "llm_direct", "llm_rag"]
        assert data["models"] == []

    def test_history_keeps_the_first_model_answer(self, client, auth_headers,
                                                  demo_api, monkeypatch):
        """The legacy answer columns must not go blank under multi-model runs."""
        monkeypatch.setattr(settings, "llm_min_chars_for_call", 1)
        res = client.post(
            "/api/v1/rag/compare",
            headers=auth_headers,
            json={
                "question": "乳腺癌的早期表现有哪些",
                "disease": "breast",
                "models": ["model-a", "model-b"],
                "persist": True,
            },
        )
        comparison_id = res.json()["data"]["comparison_id"]
        assert comparison_id is not None

        detail = client.get(f"/api/v1/rag/comparisons/{comparison_id}",
                            headers=auth_headers).json()["data"]
        assert detail["answer_llm_direct"] is not None
        assert "model-a" in detail["answer_llm_direct"]
        metrics = detail["path_metrics"]
        assert sum(1 for m in metrics if m["key"].startswith("llm_direct@")) == 2

    def test_openapi_exposes_the_new_routes(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for route in ("/api/v1/llm/providers", "/api/v1/llm/status", "/api/v1/llm/test"):
            assert route in paths
