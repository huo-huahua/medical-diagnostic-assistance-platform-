"""In-process OpenAI-compatible transport for the offline demo provider.

Why this exists
---------------
The comparison feature is the part of this project worth looking at, and it
used to require a paid API key before it would show anything except a column of
"未启用". That is a bad deal for an open-source showcase: a reader has to spend
money before they can see whether the feature works, and the CI suite can never
exercise the external path at all.

This module closes that gap without pretending to be a language model. It
implements the *wire format* — the same `POST {base_url}/chat/completions`
request body and the same JSON response shape, including the `usage` object —
and plugs into the OpenAI SDK through `httpx.MockTransport`. Because the SDK's
own serialisation, retry and error-mapping code all still run, everything
downstream of the socket behaves exactly as it does against a real service:
token accounting, cost estimation, cache behaviour, error classification.

**What it is not.** Every string this module produces begins with an explicit
watermark and states that it is not a model's answer. It deliberately contains
no medical content: for the retrieval-augmented path it echoes keywords from
the passages it was given (so the "lexical overlap" column still demonstrates
the real direction of that effect — an answer written from the sources reuses
their wording) and for the direct path it explains what the path is for without
asserting anything. It must never be mistaken for advice, and it cannot be: the
watermark is the first line of every answer and the comparison table labels the
provider as a demo.

Fault injection
---------------
`build_transport(fault=...)` can make the fake upstream fail in each of the
ways a real one does. That is how the error taxonomy in `llm_providers` is
tested end-to-end through the actual SDK rather than against a hand-written
stub that might not resemble a real failure at all.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

#: First line of every generated answer. Kept short so it survives any UI
#: truncation, and blunt so it cannot be read as a real recommendation.
DEMO_WATERMARK = "【演示模式】以下内容由内置演示模型生成，不是真实大模型的回答，也不构成医学建议。"

#: Fault modes accepted by `build_transport`.
FAULTS: tuple[str, ...] = (
    "invalid_key",
    "endpoint_not_found",
    "rate_limited",
    "quota",
    "forbidden",
    "server_error",
    "bad_request",
    "timeout",
    "connection",
    "garbage",
    "empty",
)

_COUNT_AS_ONE = re.compile(
    r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]"
)
_CITATION = re.compile(r"^\[\^c(\d+)\]\s*《(.+?)》\s*$", re.MULTILINE)


def count_tokens_approx(text: str) -> int:
    """Deterministic token estimate, good enough for display and assertions.

    Counts CJK characters as one token each and ASCII at four characters per
    token. It is an approximation, not a tokenizer — but it is *stable*, which
    is what the tests and the cost display need, and the OpenAI-compatible
    `usage` field is advisory anyway. A real provider returns its own counts and
    those are what the gateway records.
    """
    if not text:
        return 0
    heavy = len(_COUNT_AS_ONE.findall(text))
    light = len(text) - heavy
    return max(1, heavy + (light + 3) // 4)


def _passages_from(user: str) -> list[tuple[str, str, str]]:
    """Pull `(index, title, body)` out of a retrieval-augmented prompt.

    Both the comparison service and `rag_service.synthesize_with_llm` format the
    context identically — `[^cN] 《title》` on its own line followed by the
    passage body — so one parser covers both call sites.
    """
    matches = list(_CITATION.finditer(user))
    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(user)
        body = user[start:end].strip()
        # The trailing instruction line is not part of the passage.
        body = body.split("用户问题：")[0].strip()
        out.append((m.group(1), m.group(2), body))
    return out


def _keywords(text: str, limit: int = 12) -> list[str]:
    """Terms from a passage, in order of first appearance, deduplicated.

    Used to make the demo answer reuse the source wording, which is what makes
    the "lexical overlap" column behave the way it does for a real
    retrieval-augmented answer. Hyphens are *not* treated as separators, so
    compound terms like `BI-RADS` survive intact.
    """
    terms: list[str] = []
    for token in re.split(r"[，。、；：（）()\s/·]+", text):
        token = token.strip()
        if len(token) >= 2 and token not in terms:
            terms.append(token)
        if len(terms) >= limit:
            break
    return terms


def _question_from(user: str) -> str:
    m = re.search(r"用户问题：(.+)", user)
    if m:
        return m.group(1).strip().splitlines()[0].strip()
    # The direct path sends the question with no wrapper label.
    return user.strip().splitlines()[0].strip() if user.strip() else ""


def build_answer(user: str, *, model: str = "demo-model") -> str:
    """Compose the demo answer for one request."""
    passages = _passages_from(user)
    question = _question_from(user)

    # A connectivity check rather than a question. Detected by shape — no
    # passages and no `用户问题：` wrapper, which every real Q&A call site adds —
    # so the transport does not have to import the probe's prompt text back out
    # of the gateway just to recognise it. Returning a 250-token essay to
    # "只回复两个字：正常" would also make the probe's own token count absurd.
    if not passages and "用户问题：" not in user:
        return (
            f"{DEMO_WATERMARK}\n\n"
            f"演示通道连通，已正常返回。本次未附带任何参考资料，"
            f"也未生成医学内容。\n\n"
            f"（演示模型：{model}。本段文字由本地代码生成，未经过任何语言模型。）"
        )

    if not passages:
        # Stands in for `llm_direct`: no context was supplied, so there is
        # nothing whose provenance could be checked.
        lines = [
            DEMO_WATERMARK,
            "",
            "这条链路没有向模型提供任何参考资料，因此模型只能凭参数化知识作答："
            "文字通常更流畅、更像一篇科普短文，但没有任何一句话能指回可核查的原文出处。",
            "",
            "正常运行时，这里会出现真实模型针对下面这个问题的回答：",
            f"「{question}」" if question else "（未提供问题）",
            "",
            "演示模型不生成医学内容，因此上面的位置留空。"
            "对比表里这一列的「回答带出处」应当为空，「词面重合」通常也低于检索增强的路径——"
            "这正是本页想让人看见的差别。",
            "",
            f"（演示模型：{model}。本段文字由本地代码生成，未经过任何语言模型。）",
        ]
        return "\n".join(lines)

    # Stands in for `llm_rag`: the passages exist, so reproduce their wording.
    lines = [
        DEMO_WATERMARK,
        "",
        f"本次收到 {len(passages)} 段参考资料。真实模型在这里要做的事情，是"
        "把这些片段改写成连贯的科普文字，并保留 [^cN] 引用标记，"
        "使每句结论都能回溯到原文。演示模型不做这种改写，"
        "只把材料中的关键词原样列出，以便「词面重合」这一列仍然能反映"
        "「回答是从原文写出来的」这一事实。",
        "",
    ]
    for index, title, body in passages:
        terms = _keywords(body, limit=10)
        summary = "、".join(terms) if terms else body[:60]
        lines.append(f"[^{index}] 《{title}》涉及：{summary}。")
    lines.extend([
        "",
        "以上仅为关键词复述，不含任何医学结论。"
        "真实模型在此处的输出会是可读性更强的连贯段落，但引用关系与上面一致。",
        "",
        f"（演示模型：{model}。本段文字由本地代码生成，未经过任何语言模型。）",
    ])
    return "\n".join(lines)


def _usage(system: str, user: str, answer: str) -> dict[str, int]:
    prompt = count_tokens_approx(system) + count_tokens_approx(user)
    completion = count_tokens_approx(answer)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _completion_body(answer: str, model: str, system: str, user: str) -> dict[str, Any]:
    """A response shaped exactly like the OpenAI chat completions API."""
    fingerprint = hashlib.sha256(f"{model}::{system}::{user}".encode()).hexdigest()[:24]
    return {
        "id": f"chatcmpl-demo-{fingerprint}",
        "object": "chat.completion",
        "created": 0,                       # deterministic on purpose
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(system, user, answer),
    }


def _parse_body(request: httpx.Request) -> dict[str, Any]:
    try:
        return json.loads(request.content.decode("utf-8"))
    except Exception:
        return {}


def _split_messages(body: dict[str, Any]) -> tuple[str, str]:
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in body.get("messages") or []:
        role = msg.get("role")
        content = msg.get("content") or ""
        if isinstance(content, list):
            # Some clients send content as a list of parts.
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if role == "system":
            system_parts.append(str(content))
        elif role == "user":
            user_parts.append(str(content))
    return "\n".join(system_parts), "\n".join(user_parts)


def build_transport(*, fault: str | None = None, model: str = "demo-model") -> httpx.MockTransport:
    """Build the transport. `fault` makes it fail like a real provider would."""

    # A misspelt fault would otherwise look like a working success and quietly
    # hide the very thing the reader set out to reproduce. Say so instead.
    if fault and fault not in FAULTS:
        logger.warning(
            f"Unknown LLM_MOCK_FAULT={fault!r}; ignoring. Known: {', '.join(FAULTS)}"
        )
        fault = None

    def handler(request: httpx.Request) -> httpx.Response:
        if fault == "timeout":
            raise httpx.ReadTimeout("simulated upstream timeout", request=request)
        if fault == "connection":
            raise httpx.ConnectError("simulated connection failure", request=request)

        path = request.url.path.rstrip("/")

        if request.method == "GET" and path.endswith("/models"):
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": model, "object": "model"}]},
                headers={"x-demo-mode": "true"},
            )

        if fault is not None:
            return _fault_response(fault, model)

        body = _parse_body(request)
        system, user = _split_messages(body)
        answer = build_answer(user, model=str(body.get("model") or model))
        return httpx.Response(
            200,
            json=_completion_body(answer, str(body.get("model") or model), system, user),
            headers={"x-demo-mode": "true"},
        )

    return httpx.MockTransport(handler)


def _fault_response(fault: str, model: str) -> httpx.Response:
    """Replies that look like the real service's failure for each mode."""
    if fault == "garbage":
        # A 200 whose body is not JSON at all — e.g. an HTML error page served
        # by a misconfigured reverse proxy.
        return httpx.Response(200, text="<html><body>not json</body></html>")
    if fault == "empty":
        body = _completion_body("", model, "", "")
        return httpx.Response(200, json=body)

    status, message = {
        "invalid_key": (401, "Authentication Fails, Your api key is invalid"),
        "forbidden": (403, "Permission denied for this model"),
        "endpoint_not_found": (404, "Not Found"),
        "rate_limited": (429, "Rate limit reached"),
        "quota": (402, "Insufficient Balance"),
        "server_error": (500, "Internal Server Error"),
        "bad_request": (400, "Invalid request parameters"),
    }.get(fault, (500, "Unknown simulated fault"))
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": fault, "code": fault}},
    )
