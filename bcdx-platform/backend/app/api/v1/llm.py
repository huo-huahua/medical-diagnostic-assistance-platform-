"""LLM provider routes: what can be reached, what is in force, and does it work.

Three questions, three endpoints, in the order an operator actually asks them:

    GET  /llm/providers   what are my options?
    GET  /llm/status      what am I currently pointed at?
    POST /llm/test        is it actually working right now?

The first is public because it contains no secrets and the UI needs it before
anything is configured. The other two require a login: they expose the shape of
the deployment's configuration (which vendor, which model, whether a key is
present) and the probe spends real tokens, even if only a few dozen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.config import settings
from app.core.deps import get_current_user, rate_limit
from app.core.logging import get_logger
from app.schemas import (
    Envelope,
    LlmProbeResult,
    LlmProviderInfo,
    LlmStatus,
)
from app.services import llm_providers as providers
from app.services.llm_gateway import get_gateway

router = APIRouter(prefix="/llm", tags=["llm"])
logger = get_logger(__name__)


def _envelope(data, request: Request) -> Envelope:
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


@router.get("/providers", response_model=Envelope)
def list_providers(request: Request) -> Envelope:
    """The provider catalogue, for rendering a picker and for documentation.

    Public on purpose. Everything here is either a published base URL or advice
    about it, and requiring a login to discover which vendors are supported
    would make the platform harder to evaluate without protecting anything.
    """
    items = [LlmProviderInfo(**entry) for entry in providers.list_presets()]
    active = providers.resolve()
    return _envelope(
        {
            "providers": [i.model_dump() for i in items],
            "active": active.id,
            "default": providers.DEFAULT_PROVIDER,
            # Spell out the precedence of the env vars, because the answer is
            # "it depends which provider you picked" and guessing gets it wrong.
            "override_rules": (
                "LLM_PROVIDER 选择内置服务商；LLM_MODEL 可覆盖任意服务商的模型名；"
                "LLM_BASE_URL 仅在 LLM_PROVIDER=custom 时生效；"
                "演示服务商（mock）忽略两者。"
            ),
        },
        request,
    )


@router.get("/status", response_model=Envelope,
            dependencies=[Depends(get_current_user)])
def llm_status(request: Request) -> Envelope:
    """Current provider, credential presence (masked), and recent health.

    Reports `ready` alongside `available` so the UI can distinguish "switched
    off on purpose" from "switched on but unusable", which are very different
    facts for whoever is trying to get it working.
    """
    payload = LlmStatus(**get_gateway().health())
    return _envelope(payload.model_dump(), request)


@router.post("/test", response_model=Envelope,
             dependencies=[Depends(rate_limit(settings.rate_limit_llm, "llm_probe"))])
def test_provider(request: Request, _user=Depends(get_current_user)) -> Envelope:
    """Make one minimal call and report exactly what happened.

    A separate rate-limit scope from the comparison endpoint on purpose: a
    probe costs a few dozen tokens, and being unable to diagnose the
    configuration because an earlier comparison used up the budget would be a
    frustrating way to learn that.
    """
    result = LlmProbeResult(**get_gateway().probe())
    if result.ok:
        logger.info(
            f"provider probe ok [{result.provider}/{result.model}] "
            f"{result.latency_ms}ms"
        )
    else:
        logger.warning(
            f"provider probe failed [{result.provider}/{result.model}]: "
            f"{result.error_kind}"
        )
    return _envelope(result.model_dump(), request)
