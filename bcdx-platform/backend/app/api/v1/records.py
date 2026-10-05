"""Prediction history and dashboard statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ForbiddenError
from app.db.models import LlmUsage, PredictionRecord, User
from app.db.session import get_db
from app.schemas import Envelope, RecordDetailOut, RecordOut, RecordPage, StatsOut

router = APIRouter(prefix="/records", tags=["records"])


def _envelope(data, request: Request) -> Envelope:
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


@router.get("", response_model=Envelope)
def list_records(request: Request,
                 page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100),
                 disease: str | None = None,
                 verdict: str | None = None,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> Envelope:
    base = select(PredictionRecord).where(PredictionRecord.user_id == user.id)
    if disease:
        base = base.where(PredictionRecord.disease == disease)
    if verdict in ("positive", "negative"):
        base = base.where(PredictionRecord.verdict == verdict)

    total = db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    rows = db.scalars(
        base.order_by(PredictionRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return _envelope(RecordPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[RecordOut.model_validate(r) for r in rows],
    ), request)


@router.get("/stats", response_model=Envelope)
def stats(request: Request,
          user: User = Depends(get_current_user),
          db: Session = Depends(get_db)) -> Envelope:
    uid = user.id

    total = db.scalar(
        select(func.count()).select_from(PredictionRecord)
        .where(PredictionRecord.user_id == uid)
    ) or 0

    by_disease_rows = db.execute(
        select(PredictionRecord.disease, func.count())
        .where(PredictionRecord.user_id == uid)
        .group_by(PredictionRecord.disease)
    ).all()
    by_disease = {d: int(c) for d, c in by_disease_rows}

    positives = db.scalar(
        select(func.count()).select_from(PredictionRecord)
        .where(PredictionRecord.user_id == uid, PredictionRecord.verdict == "positive")
    ) or 0

    llm_calls = db.scalar(
        select(func.count()).select_from(LlmUsage)
        .where(LlmUsage.user_id == uid, LlmUsage.cache_hit.is_(False))
    ) or 0
    llm_hits = db.scalar(
        select(func.count()).select_from(LlmUsage)
        .where(LlmUsage.user_id == uid, LlmUsage.cache_hit.is_(True))
    ) or 0

    last = db.scalar(
        select(func.max(PredictionRecord.created_at))
        .where(PredictionRecord.user_id == uid)
    )

    return _envelope(StatsOut(
        total_predictions=int(total),
        by_disease=by_disease,
        positives=int(positives),
        negatives=int(total - positives),
        positive_rate=round(positives / total, 4) if total else 0.0,
        llm_calls=int(llm_calls),
        llm_cache_hits=int(llm_hits),
        cache_hit_rate=round(llm_hits / (llm_calls + llm_hits), 4)
        if (llm_calls + llm_hits) else 0.0,
        last_prediction_at=last,
    ), request)


@router.get("/{record_id}", response_model=Envelope)
def get_record(record_id: int, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> Envelope:
    record = db.get(PredictionRecord, record_id)
    if record is None or record.user_id != user.id:
        raise ForbiddenError("Record not found")
    return _envelope(RecordDetailOut.model_validate(record), request)


@router.delete("/{record_id}", response_model=Envelope)
def delete_record(record_id: int, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> Envelope:
    record = db.get(PredictionRecord, record_id)
    if record is None or record.user_id != user.id:
        raise ForbiddenError("Record not found")
    db.delete(record)
    db.commit()
    return _envelope({"deleted": record_id}, request)
