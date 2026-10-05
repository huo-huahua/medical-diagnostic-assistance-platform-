"""Authentication routes: register, login, profile."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.errors import EmailTakenError, InvalidCredentialsError
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import AuditLog, User
from app.db.session import get_db
from app.schemas import Envelope, LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _envelope(data, request: Request):
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


def _audit(db: Session, action: str, user_id: int | None,
           request: Request, resource: str | None = None) -> None:
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        resource=resource,
        ip=request.client.host if request.client else None,
    ))
    db.commit()


@router.post("/register", response_model=Envelope)
def register(payload: RegisterRequest, request: Request,
             db: Session = Depends(get_db)) -> Envelope:
    email = payload.email.lower().strip()

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailTakenError()

    # The very first account becomes an admin so a fresh deployment is
    # manageable without touching the database directly.
    is_first = db.scalar(select(User.id).limit(1)) is None

    user = User(
        email=email,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
        role="admin" if is_first else "user",
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _audit(db, "register", user.id, request, resource=email)
    logger.info(f"new account registered: {email} (role={user.role})")

    token = create_access_token(user.id, extra={"email": user.email, "role": user.role})
    return _envelope(
        TokenResponse(
            access_token=token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=UserOut.model_validate(user),
        ),
        request,
    )


@router.post("/login", response_model=Envelope)
def login(payload: LoginRequest, request: Request,
          db: Session = Depends(get_db)) -> Envelope:
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    if user is None or not verify_password(payload.password, user.hashed_password):
        # Identical message for both cases — do not leak account existence.
        raise InvalidCredentialsError()

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    _audit(db, "login", user.id, request, resource=email)

    token = create_access_token(user.id, extra={"email": user.email, "role": user.role})
    return _envelope(
        TokenResponse(
            access_token=token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=UserOut.model_validate(user),
        ),
        request,
    )


@router.get("/me", response_model=Envelope)
def me(request: Request, user: User = Depends(get_current_user)) -> Envelope:
    return _envelope(UserOut.model_validate(user), request)
