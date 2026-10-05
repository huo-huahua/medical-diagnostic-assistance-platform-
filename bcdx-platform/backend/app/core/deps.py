"""Shared FastAPI dependencies: current user, rate limiting, pagination."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError, ErrorCode
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError()
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Malformed authentication token")

    user = db.scalar(select(User).where(User.id == int(user_id)))
    if user is None:
        raise UnauthorizedError("Account no longer exists")
    if not user.is_active:
        raise ForbiddenError("This account has been disabled")
    return user


class RateLimiter:
    """In-process sliding-window limiter.

    Adequate for a single-worker open-source deployment. Behind multiple
    workers or instances this should be swapped for Redis.
    """

    def __init__(self, times: int, seconds: int, scope: str = "default"):
        self.times = times
        self.seconds = seconds
        self.scope = scope
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        window = self._hits[f"{self.scope}:{key}"]
        while window and now - window[0] > self.seconds:
            window.popleft()
        if len(window) >= self.times:
            retry_after = int(self.seconds - (now - window[0])) + 1
            return False, max(retry_after, 1)
        window.append(now)
        return True, 0


def parse_rate(expr: str) -> tuple[int, int]:
    """Parse '60/minute' -> (60, 60)."""
    try:
        count_s, unit = expr.split("/")
        count = int(count_s)
    except Exception:
        return 60, 60
    unit_seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(
        unit.strip().lower(), 60
    )
    return count, unit_seconds


def rate_limit(expr: str, scope: str, by_user: bool = True) -> Callable[..., None]:
    """Build a dependency enforcing `expr` in `scope`."""
    times, seconds = parse_rate(expr)
    limiter = RateLimiter(times, seconds, scope)

    def dependency(
        request: Request,
        current_user: User | None = Depends(bearer_scheme_optional),
    ) -> None:
        from app.core.errors import AppError

        if by_user and current_user is not None:
            payload = decode_access_token(current_user.credentials)
            key = f"u:{payload.get('sub')}"
        else:
            key = f"ip:{request.client.host if request.client else 'unknown'}"

        allowed, retry_after = limiter.check(key)
        if not allowed:
            err = AppError(
                f"Too many requests. Please retry in {retry_after}s.",
            )
            err.code = ErrorCode.RATE_LIMITED
            err.http_status = 429
            err.details = {"retry_after": retry_after}
            raise err

    return dependency


bearer_scheme_optional = HTTPBearer(auto_error=False)
