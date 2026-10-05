"""LLM provider catalogue — what the platform can talk to, and how.

The gateway speaks exactly one wire protocol: the OpenAI *chat completions*
API. That is not a limitation in practice — DeepSeek, OpenAI, Alibaba
DashScope, Moonshot, Zhipu, Ollama, vLLM, LM Studio, LiteLLM and most
gateways all expose an OpenAI-compatible endpoint. Picking a provider is
therefore a matter of a base URL and a model name, which is precisely what
this module tabulates.

Why a catalogue instead of free-form env vars
---------------------------------------------
Base URLs are easy to get wrong in ways that fail *quietly*: a missing `/v1`
on some hosts returns a 404 that reads like "model not found", and pointing
a newly selected provider at the previous provider's URL produces a 401 that
looks like an expired key. Encoding the known-good values in one place, next
to each provider's price and console URL, removes both failure modes and
gives the UI something honest to display.

Key handling
------------
Two of the presets (`ollama`, `mock`) need no credentials at all, which means
the whole comparison feature can be demonstrated — and its tests run — with
no key, no network and no cost. That property is deliberate: the comparison is
the part of this project worth showing, and it should not require a credit
card to look at.

Nothing in this module ever reads a key out of `settings` except through
`resolve()` and `mask_key()`; the latter exists so a key can be displayed as
`sk-a****91c4` in the UI without the full value ever leaving the server.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings

#: Used when `LLM_PROVIDER` is unset or names something we do not know.
DEFAULT_PROVIDER = "deepseek"

#: Preset used for a self-hosted / proxied endpoint the user names themselves.
CUSTOM_PROVIDER = "custom"

#: Preset that answers from a local transport without any network call.
DEMO_PROVIDER = "mock"


@dataclass(frozen=True)
class ProviderPreset:
    """One provider the platform knows how to reach.

    Prices are CNY per 1K tokens and are used **only** to annotate the
    comparison table; they are never used to bill. A value of `None` means
    "inherit whatever `.env` says", which is what `custom` wants, and `0.0`
    means the provider is genuinely free at the point of use (`ollama` runs on
    your own machine; `mock` never leaves the process).
    """

    id: str
    label: str
    base_url: str
    default_model: str
    requires_key: bool = True
    price_prompt_per_1k: float | None = None
    price_completion_per_1k: float | None = None
    console_url: str = ""
    note: str = ""
    is_demo: bool = False


PROVIDERS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        id="deepseek",
        label="DeepSeek 深度求索",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        price_prompt_per_1k=0.002,
        price_completion_per_1k=0.008,
        console_url="https://platform.deepseek.com/api_keys",
        note="默认选项。中文医学科普语境下表现稳定，价格低。",
    ),
    "openai": ProviderPreset(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        price_prompt_per_1k=0.0011,
        price_completion_per_1k=0.0043,
        console_url="https://platform.openai.com/api-keys",
        note="需要海外网络环境。价格按 gpt-4o-mini 折算为人民币。",
    ),
    "qwen": ProviderPreset(
        id="qwen",
        label="阿里云百炼（通义千问）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        price_prompt_per_1k=0.0008,
        price_completion_per_1k=0.002,
        console_url="https://bailian.console.aliyun.com/",
        note="必须走 compatible-mode 路径才是 OpenAI 兼容接口，漏掉会 404。",
    ),
    "moonshot": ProviderPreset(
        id="moonshot",
        label="Moonshot（Kimi）",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        price_prompt_per_1k=0.012,
        price_completion_per_1k=0.012,
        console_url="https://platform.moonshot.cn/console/api-keys",
        note="长上下文见长，单价高于 DeepSeek。",
    ),
    "zhipu": ProviderPreset(
        id="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        price_prompt_per_1k=0.0,
        price_completion_per_1k=0.0,
        console_url="https://open.bigmodel.cn/usercenter/apikeys",
        note="glm-4-flash 目前免费，因此沿用它的对比结果费用显示为 ¥0。",
    ),
    "ollama": ProviderPreset(
        id="ollama",
        label="本地 Ollama（无需密钥）",
        base_url="http://127.0.0.1:11434/v1",
        default_model="qwen2.5:7b",
        requires_key=False,
        price_prompt_per_1k=0.0,
        price_completion_per_1k=0.0,
        console_url="https://ollama.com/download",
        note=(
            "模型跑在本机，数据不出机器、不产生费用。需要先 "
            "`ollama pull qwen2.5:7b` 并保持 `ollama serve` 运行；"
            "模型名要与 `ollama list` 里的一致。"
        ),
    ),
    "mock": ProviderPreset(
        id="mock",
        label="内置演示模型（离线、无需密钥）",
        base_url="http://mock.local/v1",
        default_model="demo-model",
        requires_key=False,
        price_prompt_per_1k=0.0,
        price_completion_per_1k=0.0,
        is_demo=True,
        note=(
            "不联网、不调用任何外部服务，用进程内的本地传输生成固定格式的"
            "占位回答，用于演示与测试三条问答链路的差异。输出带明显水印，"
            "**不是真实模型的回答，不可作为医学参考**。"
        ),
    ),
    CUSTOM_PROVIDER: ProviderPreset(
        id=CUSTOM_PROVIDER,
        label="自定义 / 自建端点",
        base_url="",
        default_model="",
        console_url="",
        note=(
            "使用 `.env` 中填写的 `LLM_BASE_URL` 与 `LLM_MODEL`。"
            "适用于 vLLM、LM Studio、LiteLLM、One-API 等自建 OpenAI 兼容服务。"
        ),
    ),
}


@dataclass(frozen=True)
class ResolvedProvider:
    """The provider actually in force after env overrides are applied."""

    id: str
    label: str
    base_url: str
    model: str
    requires_key: bool
    is_demo: bool
    price_prompt_per_1k: float
    price_completion_per_1k: float
    console_url: str
    note: str
    #: The value of `LLM_PROVIDER` when it did not name a known provider.
    unknown_provider: str | None = None
    #: True when `LLM_BASE_URL` / `LLM_MODEL` overrode the preset.
    base_url_overridden: bool = False
    model_overridden: bool = False

    @property
    def prices(self) -> tuple[float, float]:
        return (self.price_prompt_per_1k, self.price_completion_per_1k)

    @property
    def has_endpoint(self) -> bool:
        return bool(self.base_url)

    def to_public_dict(self) -> dict:
        """Provider description with no credential material whatsoever."""
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "requires_key": self.requires_key,
            "is_demo": self.is_demo,
            "price_prompt_per_1k": self.price_prompt_per_1k,
            "price_completion_per_1k": self.price_completion_per_1k,
            "console_url": self.console_url,
            "note": self.note,
            "unknown_provider": self.unknown_provider,
            "base_url_overridden": self.base_url_overridden,
            "model_overridden": self.model_overridden,
        }


def get_preset(provider_id: str | None) -> ProviderPreset:
    """Look up a preset, falling back to the default for unknown ids."""
    pid = (provider_id or "").strip().lower()
    return PROVIDERS.get(pid, PROVIDERS[DEFAULT_PROVIDER])


def resolve(
    provider_id: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> ResolvedProvider:
    """Combine the selected preset with any explicit env overrides.

    Precedence is deliberately narrow, because the alternative — "env always
    wins" — produces a failure mode that is genuinely hard to debug: you switch
    `LLM_PROVIDER` to a new service, the request still goes to the old base URL,
    and the resulting 401 reads like an expired key rather than a stale
    setting. The rules are:

    ===================  ====================  ==================
    ``LLM_PROVIDER``     base_url              model
    ===================  ====================  ==================
    a named preset       the preset's          ``LLM_MODEL`` if set,
                         known-good URL        else the preset's
    ``custom``           ``LLM_BASE_URL``      ``LLM_MODEL``
    ``mock`` (demo)      the preset's          the preset's
    ===================  ====================  ==================

    Overriding only the *model* on a named provider is allowed on purpose: the
    host and credentials stay the same, so `LLM_PROVIDER=deepseek` with
    `LLM_MODEL=deepseek-reasoner` is a normal thing to want. The demo provider
    ignores both, since it has no upstream to point anywhere and a model name
    that does not exist would only mislead whoever reads the comparison table.

    The flags on the result record which path was taken so `/llm/status` can
    explain the current state instead of leaving the operator to guess.
    """
    requested = (provider_id if provider_id is not None else settings.llm_provider) or ""
    requested = requested.strip().lower()
    unknown = requested if requested and requested not in PROVIDERS else None
    preset = get_preset(requested)

    env_base = (base_url if base_url is not None else settings.llm_base_url) or ""
    env_model = (model if model is not None else settings.llm_model) or ""
    env_base, env_model = env_base.strip(), env_model.strip()

    price_prompt = preset.price_prompt_per_1k
    price_completion = preset.price_completion_per_1k
    if price_prompt is None:
        price_prompt = settings.llm_price_prompt_per_1k
    if price_completion is None:
        price_completion = settings.llm_price_completion_per_1k

    if preset.is_demo:
        effective_base, effective_model = preset.base_url, preset.default_model
        base_overridden = model_overridden = False
    elif preset.id == CUSTOM_PROVIDER:
        effective_base, effective_model = env_base or preset.base_url, env_model or preset.default_model
        base_overridden = bool(env_base)
        model_overridden = bool(env_model)
    else:
        effective_base = preset.base_url
        effective_model = env_model or preset.default_model
        base_overridden = False
        model_overridden = bool(env_model) and env_model != preset.default_model

    return ResolvedProvider(
        id=preset.id,
        label=preset.label,
        base_url=effective_base,
        model=effective_model,
        requires_key=preset.requires_key,
        is_demo=preset.is_demo,
        price_prompt_per_1k=float(price_prompt),
        price_completion_per_1k=float(price_completion),
        console_url=preset.console_url,
        note=preset.note,
        unknown_provider=unknown,
        base_url_overridden=base_overridden,
        model_overridden=model_overridden,
    )


def key_present() -> bool:
    """Whether a plausible API key is configured.

    Delegates to `settings.llm_configured`, which rejects empty values and the
    `sk-your-...` placeholder shipped in `.env.example`. Rejecting the
    placeholder matters: without it, a copied example config would flip the
    platform into "paid" mode and every comparison would fail with a 401.
    """
    return settings.llm_configured


def is_ready(provider: ResolvedProvider | None = None) -> bool:
    """Whether this provider can actually be called right now."""
    p = provider or resolve()
    if not p.has_endpoint:
        return False
    if p.requires_key and not key_present():
        return False
    return True


def mask_key(key: str | None = None) -> str | None:
    """Render a key for display without revealing it.

    Returns `None` when no key is set, so the caller can distinguish "absent"
    from "present but unprintable". Short values are masked entirely rather
    than partially shown — a 6-character key would otherwise be mostly legible.
    """
    value = (key if key is not None else settings.llm_api_key) or ""
    value = value.strip()
    if not value:
        return None
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 4}{value[-4:]}"


def list_presets() -> list[dict]:
    """Public catalogue for the UI's provider picker."""
    return [
        {
            "id": p.id,
            "label": p.label,
            "base_url": p.base_url,
            "default_model": p.default_model,
            "requires_key": p.requires_key,
            "is_demo": p.is_demo,
            "price_prompt_per_1k": (
                p.price_prompt_per_1k
                if p.price_prompt_per_1k is not None
                else settings.llm_price_prompt_per_1k
            ),
            "price_completion_per_1k": (
                p.price_completion_per_1k
                if p.price_completion_per_1k is not None
                else settings.llm_price_completion_per_1k
            ),
            "console_url": p.console_url,
            "note": p.note,
        }
        for p in PROVIDERS.values()
    ]


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #

#: Every kind `classify_error` can return, mapped to an actionable Chinese
#: message. The point of the taxonomy is that "调用失败" is never the whole
#: story: a 404 and a 401 need completely different fixes, and lumping them
#: together is what turns a five-second configuration mistake into an hour of
#: guessing.
ERROR_KINDS: dict[str, str] = {
    "missing_key": "未配置 API Key。请在 .env 中填写 LLM_API_KEY，或改用无需密钥的本地/演示模型。",
    "invalid_key": "密钥无效或已过期（服务端返回 401）。请到服务商控制台确认密钥状态。",
    "forbidden": "密钥无权访问该模型（403）。可能是模型未开通或账号被限制。",
    "endpoint_not_found": (
        "接口地址不对（404）。常见原因是 base_url 缺少 `/v1` 后缀，"
        "或把上一个服务商的地址留在了配置里。"
    ),
    "model_not_found": "模型名不存在（400/404）。请核对模型名称是否与服务商文档一致。",
    "bad_request": "请求被服务端拒绝（400）。通常是模型名或参数不被支持。",
    "rate_limited": "触发服务商限流（429）。稍后重试，或降低调用频率。",
    "quota": "额度已用尽或欠费（402/403）。请到服务商控制台检查余额。",
    "server_error": "服务商侧返回 5xx。这是对方的问题，稍后重试即可。",
    "timeout": "请求超时。检查网络，或调大 LLM_TIMEOUT_SECONDS。",
    "connection": (
        "无法建立连接。本地模型（如 Ollama）请确认服务已启动；"
        "远程服务请检查网络与代理设置。"
    ),
    "no_endpoint": "未配置接口地址。请设置 LLM_BASE_URL 或选择一个内置服务商。",
    "disabled": "外部模型已被全局关闭（LLM_ENABLED=false）。",
    "empty_response": "服务端返回了空内容。可能是内容被过滤，或模型只输出了推理过程。",
    "bad_response": "返回内容不是预期的结构，无法解析。请确认该地址是 OpenAI 兼容接口。",
    "unknown": "调用失败，原因未能识别。请查看后端日志中的原始异常。",
}


def message_for(kind: str) -> str:
    return ERROR_KINDS.get(kind, ERROR_KINDS["unknown"])


def classify_error(exc: BaseException) -> str:
    """Map an exception to one of `ERROR_KINDS`.

    Prefers the SDK's own exception classes (they carry the semantics), then
    falls back to structural inspection, then to the class-name heuristic. The
    layered approach is what lets the same function classify a real `openai`
    error, an `httpx` error from a custom transport, and a bare `RuntimeError`
    without importing the SDK eagerly.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

    if isinstance(status_code, int):
        if status_code == 401:
            return "invalid_key"
        if status_code == 402:
            return "quota"
        if status_code == 403:
            return "forbidden"
        if status_code == 404:
            return "endpoint_not_found"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "server_error"
        if status_code == 400:
            # A 400 with a "model" in the message is almost always a bad model
            # name, which deserves its own advice.
            text = str(exc).lower()
            return "model_not_found" if "model" in text else "bad_request"
        if 400 <= status_code < 500:
            return "bad_request"

    # Transport-level failures. Checked by name because the OpenAI SDK's
    # exception hierarchy does not inherit from httpx's.
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    if "Timeout" in name or "timeout" in str(exc).lower():
        return "timeout"
    if "Connection" in name or "Connect" in name:
        return "connection"
    if module.startswith("httpx"):
        return "connection"

    text = str(exc).lower()
    if "api key" in text or "api_key" in text or "unauthorized" in text:
        return "missing_key"
    if "expecting value" in text or "json" in text:
        return "bad_response"
    if "connection" in text or "refused" in text or "unreachable" in text:
        return "connection"
    return "unknown"


def explain_error(exc: BaseException) -> dict:
    """Structured, display-ready description of a failed call."""
    kind = classify_error(exc)
    return {
        "kind": kind,
        "message": message_for(kind),
        "detail": str(exc)[:500] or None,
        "type": type(exc).__name__,
    }
