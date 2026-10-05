"""Database models.

Privacy note: we deliberately store NO direct patient identifiers.
Records are tied to a user account and carry only model inputs/outputs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    records: Mapped[list["PredictionRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PredictionRecord(Base):
    __tablename__ = "prediction_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Optional user-supplied label. Never a real identifier.
    case_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    disease: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)

    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    positive_prob: Mapped[float] = mapped_column(Float, nullable=False)
    negative_prob: Mapped[float] = mapped_column(Float, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_band: Mapped[str] = mapped_column(String(12), nullable=False)
    contributions: Mapped[list | None] = mapped_column(JSON, nullable=True)

    llm_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    user: Mapped["User"] = relationship(back_populates="records")


Index("ix_records_user_created", PredictionRecord.user_id, PredictionRecord.created_at.desc())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="新对话", nullable=False)
    disease: Mapped[str] = mapped_column(String(20), default="breast", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class LlmUsage(Base):
    """Token accounting so cost is always visible."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # explain | rag
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class QaComparison(Base):
    """One side-by-side comparison of the Q&A answer paths.

    Persisted so the trade-off between a purely local pipeline and an
    external-model pipeline stays auditable after the fact — how many external
    calls were actually made, what they cost, and how well each answer stayed
    anchored to the retrievable source text.
    """

    __tablename__ = "qa_comparisons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    question: Mapped[str] = mapped_column(Text, nullable=False)
    disease: Mapped[str] = mapped_column(String(20), nullable=False)

    # Local retrieval outcome, identical across every path in this comparison.
    refused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    top_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    passage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Full answers, so the comparison can be re-read rather than re-billed.
    answer_local: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_llm_direct: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_llm_rag: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Per-path metrics without the text payload: latency, tokens, grounding.
    path_metrics: Mapped[list | None] = mapped_column(JSON, nullable=True)

    external_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_cny: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    __table_args__ = (UniqueConstraint("id", name="uq_audit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
