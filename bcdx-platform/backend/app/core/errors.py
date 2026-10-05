"""Unified error codes and exception hierarchy.

Error code segments:
    1xxx  input validation
    2xxx  auth / rate limiting
    3xxx  model inference
    4xxx  external dependency (LLM, embedding)
    5xxx  internal
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class ErrorCode:
    VALIDATION_FAILED = 1001
    FEATURE_COUNT_MISMATCH = 1002
    FEATURE_OUT_OF_RANGE = 1003
    UNSUPPORTED_FILE_TYPE = 1004
    FILE_TOO_LARGE = 1005
    INVALID_DISEASE = 1006

    UNAUTHORIZED = 2001
    INVALID_CREDENTIALS = 2002
    EMAIL_TAKEN = 2003
    TOKEN_EXPIRED = 2004
    RATE_LIMITED = 2005
    FORBIDDEN = 2006

    MODEL_NOT_FOUND = 3001
    INFERENCE_FAILED = 3002
    EXPLAIN_FAILED = 3003
    REGISTRY_UNAVAILABLE = 3004

    LLM_UNAVAILABLE = 4001
    LLM_DISABLED = 4002
    EMBEDDING_FAILED = 4003

    INTERNAL = 5001


class AppError(Exception):
    """Base application error carrying a public-facing code and message."""

    code: int = ErrorCode.INTERNAL
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "Internal server error"

    def __init__(self, message: str | None = None, *, details: Any = None):
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class ValidationError(AppError):
    code = ErrorCode.VALIDATION_FAILED
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "Validation failed"


class FeatureCountError(AppError):
    code = ErrorCode.FEATURE_COUNT_MISMATCH
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "Feature count mismatch"


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "Authentication required"


class InvalidCredentialsError(AppError):
    code = ErrorCode.INVALID_CREDENTIALS
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "Incorrect email or password"


class EmailTakenError(AppError):
    code = ErrorCode.EMAIL_TAKEN
    http_status = status.HTTP_409_CONFLICT
    message = "This email is already registered"


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = status.HTTP_403_FORBIDDEN
    message = "Not permitted"


class ModelNotFoundError(AppError):
    code = ErrorCode.MODEL_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND
    message = "Model not found"


class InferenceError(AppError):
    code = ErrorCode.INFERENCE_FAILED
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Inference failed"


class ExternalServiceError(AppError):
    code = ErrorCode.LLM_UNAVAILABLE
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "Upstream service unavailable"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    if exc.http_status >= 500:
        logger.error("app_error", extra={"code": exc.code, "path": request.url.path,
                                         "detail": str(exc)})
    else:
        logger.info("app_error", extra={"code": exc.code, "path": request.url.path,
                                        "detail": str(exc)})
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "details": exc.details,
            "request_id": rid,
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code * 10,
            "message": str(exc.detail),
            "data": None,
            "request_id": rid,
        },
        headers=getattr(exc, "headers", None),
    )


#: How many field errors to spell out. A 500-row batch can produce hundreds, and
#: a wall of text is not more useful than the first few.
_MAX_REPORTED_FIELD_ERRORS = 3


def _describe(errors: list[dict[str, Any]]) -> str:
    """One line a human can act on, from pydantic's structured errors.

    The field path is the useful part — "String should have at least 8
    characters" does not say *which* string. `body` is dropped from the path
    because it is an artefact of how the request was submitted, not part of the
    payload the caller wrote.
    """
    parts = []
    for err in errors[:_MAX_REPORTED_FIELD_ERRORS]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
        msg = err.get("msg", "invalid value")
        parts.append(f"{loc} — {msg}" if loc else msg)
    extra = len(errors) - len(parts)
    suffix = f" (+{extra} more)" if extra > 0 else ""
    return "Validation failed: " + "; ".join(parts) + suffix


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Return FastAPI's 422 in the same envelope as every other error.

    FastAPI installs its own handler for `RequestValidationError`, which wins
    over the generic `Exception` handler — so without this registration a
    validation failure is the one response shape that does *not* carry
    `{code, message, data, request_id}`. The frontend reads `message` and falls
    back to a bare "请求失败", which means the user is told *that* it failed but
    never *why*, even though the server worked out exactly which field was wrong.
    """
    rid = getattr(request.state, "request_id", "-")
    errors = list(getattr(exc, "errors", lambda: [])())
    logger.info(
        "validation_error",
        extra={"path": request.url.path, "fields": [e.get("loc") for e in errors]},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": ErrorCode.VALIDATION_FAILED,
            "message": _describe(errors) if errors else "Validation failed",
            "data": None,
            # The structured list is kept so a client can highlight the exact
            # inputs rather than regex the message. It *must* go through
            # `jsonable_encoder`: when a custom validator raises `ValueError`,
            # pydantic puts the exception object itself into `ctx`, and passing
            # that straight to `JSONResponse` blows up with "Object of type
            # ValueError is not JSON serializable" — turning a tidy 422 into an
            # unhandled 500. FastAPI's own default handler encoded here too;
            # rewriting the handler means re-doing that step.
            "details": jsonable_encoder(errors),
            "request_id": rid,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    logger.exception("unhandled_exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.INTERNAL,
            "message": "An unexpected error occurred. Please try again.",
            "data": None,
            "request_id": rid,
        },
    )
