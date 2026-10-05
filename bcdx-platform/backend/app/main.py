"""BC-Dx Platform — FastAPI application entry point."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.api.v1 import auth, llm, models, predict, rag, records
from app.core.config import settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import get_logger, request_id_var, setup_logging
from app.schemas import Envelope

setup_logging(settings.debug)
logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 68)
    logger.info(f"{settings.app_name} v{settings.app_version} starting")
    logger.info(f"environment={settings.environment} debug={settings.debug}")

    if settings.secret_key_is_placeholder:
        # Anyone who knows this string can mint a valid login token for any
        # account. In production that is not a warning, it is a reason not to
        # start; in development it is worth one loud line so it is fixed before
        # the service is ever exposed.
        message = (
            "SECRET_KEY is still a placeholder value. Anyone who knows it can "
            "mint a valid login token for any account. Generate one with "
            "`openssl rand -hex 32` and put it in .env."
        )
        if settings.is_production:
            raise RuntimeError(f"Refusing to start: {message}")
        logger.warning(f"INSECURE CONFIGURATION — {message}")

    from app.db.session import init_db
    init_db()
    logger.info(f"database ready: {settings.database_url}")

    # Warm the model registry so the first prediction is not cold.
    try:
        from app.ml.registry import get_registry
        registry = get_registry()
        registry.warm_up()
        for disease in registry.diseases():
            info = registry.disease_info(disease)
            champ = info["models"][info["champion"]]
            logger.info(
                f"  [{disease}] champion={info['champion_id']} "
                f"AUC={champ['test']['roc_auc']} thr={champ['threshold']}"
            )
    except Exception as exc:
        logger.error(f"Model registry warm-up failed: {exc}")

    # Build the local RAG index (no API cost).
    try:
        from app.services.rag_service import get_index
        get_index().warm_up()
    except Exception as exc:
        logger.warning(f"RAG index warm-up failed: {exc}")

    from app.services.llm_gateway import get_gateway
    gw = get_gateway()
    health = gw.health()
    if health["available"]:
        logger.info(
            f"LLM available: provider={health['provider']} model={health['model']} "
            f"base_url={health['base_url']} (cached, {health['cache']['maxsize']} entries)"
        )
        if health["is_demo"]:
            logger.warning(
                "  ^^^ OFFLINE DEMO PROVIDER — no network calls, answers are "
                "generated placeholder text. See docs/LLM_INTEGRATION.md"
            )
    elif not health["enabled"]:
        logger.info("LLM disabled — Q&A runs fully local at zero API cost")
    else:
        # Distinguishing these matters: "switched off on purpose" and
        # "switched on but unusable" produce the same `skipped` columns, and a
        # one-line log is what saves the next person from hunting for the cause.
        logger.info(
            f"LLM configured but not usable: provider={health['provider']} "
            f"requires_key={health['requires_key']} key_present={health['key_present']} "
            f"endpoint={health['base_url'] or '(unset)'} — external comparison "
            "columns will report 'skipped'. Verify with POST /api/v1/llm/test"
        )

    logger.info("startup complete")
    logger.info("=" * 68)
    yield
    logger.info("shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Open-source clinical decision **support** prototype.\n\n"
        "Trained on public datasets (WDBC, UCI Heart Disease). "
        "**Not a medical device** — outputs must not be used as the sole "
        "basis for a clinical decision."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Request-ID", "X-Elapsed-MS"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    request_id_var.set(rid)

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    response.headers["X-Request-ID"] = rid
    response.headers["X-Elapsed-MS"] = str(elapsed_ms)

    if request.url.path not in ("/health", "/favicon.ico"):
        logger.info(f"{request.method} {request.url.path} -> "
                    f"{response.status_code} ({elapsed_ms}ms)")
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    return response


# --------------------------------------------------------------------------- #
# Error handlers
# --------------------------------------------------------------------------- #

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
# Must be registered explicitly: FastAPI ships its own handler for this one and
# it beats the generic `Exception` handler, so without this line a 422 would be
# the only response that bypasses the unified envelope.
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(llm.router, prefix=API_PREFIX)
app.include_router(models.router, prefix=API_PREFIX)
app.include_router(predict.router, prefix=API_PREFIX)
app.include_router(rag.router, prefix=API_PREFIX)
app.include_router(records.router, prefix=API_PREFIX)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "disclaimer": (
            "Research and educational decision-support prototype. "
            "Not a medical device. Always consult a licensed clinician."
        ),
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    from app.services.llm_gateway import get_gateway
    from app.services.rag_service import get_index

    index = get_index()
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "rag_ready": index.ready,
        "rag_chunks": len(index.chunks),
        "rag_chunking": index.chunk_stats,
        # Retrieval is reported separately from chunking because "hybrid +
        # reranked" is otherwise an unverifiable claim: without this, a silent
        # degradation to dense-only (reranker model unavailable) looks identical
        # to the feature working.
        "rag_retrieval": index.retrieval_info(),
        "llm": get_gateway().health(),
    }


@app.get("/api/v1/meta/limits", response_model=Envelope, tags=["meta"])
def limits(request: Request) -> Envelope:
    """Expose operational limits so the UI can show accurate guidance.

    Wrapped in the standard envelope like every other route under `/api/v1`:
    the frontend client unwraps `data` unconditionally, so a bare body here
    would resolve to `undefined` at the call site.
    """
    return Envelope(
        data={
            "max_upload_mb": settings.max_upload_mb,
            "rate_limit_predict": settings.rate_limit_predict,
            "rate_limit_llm": settings.rate_limit_llm,
            "rag_top_k": settings.rag_top_k,
            "rag_min_similarity": settings.rag_min_similarity,
            "rag_chunk_max_chars": settings.rag_chunk_max_chars,
            "rag_chunk_overlap_chars": settings.rag_chunk_overlap_chars,
            "rag_hybrid": settings.rag_hybrid_enabled,
            "rag_rerank": settings.rag_rerank_enabled,
            "llm_enabled": settings.llm_configured and settings.llm_enabled,
            "qa_compare_allow_llm": settings.qa_compare_allow_llm,
            "qa_compare_max_question_chars": settings.qa_compare_max_question_chars,
        },
        request_id=getattr(request.state, "request_id", "-"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
