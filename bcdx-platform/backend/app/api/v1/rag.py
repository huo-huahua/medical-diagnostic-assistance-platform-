"""Medical Q&A routes (RAG)."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, rate_limit
from app.core.logging import get_logger
from app.db.models import Conversation, LlmUsage, Message, QaComparison, User
from app.db.session import get_db
from app.schemas import (
    AskRequest,
    AskResponse,
    Citation,
    Envelope,
    QaCompareRequest,
    QaCompareResponse,
)
from app.services.llm_gateway import get_gateway
from app.services.rag_service import (
    GREETING_REPLY,
    compose_local_answer,
    get_index,
    group_passages,
    is_greeting,
    synthesize_with_llm,
)

router = APIRouter(prefix="/rag", tags=["rag"])
logger = get_logger(__name__)


def _envelope(data, request: Request) -> Envelope:
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


def _resolve_conversation(db: Session, user: User, conversation_id: int | None,
                          question: str, disease: str) -> Conversation:
    if conversation_id:
        convo = db.get(Conversation, conversation_id)
        if convo is not None and convo.user_id == user.id:
            return convo
    convo = Conversation(
        user_id=user.id,
        disease=disease,
        title=question[:40] + ("…" if len(question) > 40 else ""),
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def _answer(question: str, disease: str, use_llm: bool) -> dict:
    # A greeting short-circuits *before* retrieval. Otherwise we would spend an
    # embedding pass on it, hand the UI a list of five unrelated citations to
    # display under "你好", and — with `use_llm=True` — pay for an external call
    # whose context has nothing to do with the input.
    if is_greeting(question):
        return {
            "answer": GREETING_REPLY,
            "citations": [],
            "refused": False,
            "source": "greeting",
            "llm_used": False,
            "cache_hit": False,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_ms": 0,
        }

    index = get_index()
    # Warm the index before timing: a cold embedding pass would otherwise be
    # recorded as this answer's latency.
    if not index.ready:
        index.build()

    started = time.perf_counter()
    hits = index.search(question, top_k=settings.rag_top_k, disease=disease)

    # Retrieve at chunk granularity (every vector fits the embedding window),
    # but cite one entry per *section* so the answer is not the same heading
    # repeated once per fragment.
    passages = group_passages(hits)
    citations = [
        Citation(
            index=i,
            source=p.source,
            title=p.citation_title,
            snippet=p.text[:220].replace("\n", " "),
            score=round(p.score, 4),
        )
        for i, p in enumerate(passages, start=1)
    ]

    local_answer, refused = compose_local_answer(
        question, hits, disease=disease, passages=passages
    )

    result = {
        "answer": local_answer,
        "citations": citations,
        "refused": refused,
        "source": "refusal" if refused else "knowledge_base",
        "llm_used": False,
        "cache_hit": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }

    if refused or not use_llm:
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    text, meta = synthesize_with_llm(question, hits, index.embed_query)
    if text:
        result["answer"] = text
        result["source"] = "llm_enhanced"
    result["llm_used"] = bool(meta.get("llm_used"))
    result["cache_hit"] = bool(meta.get("cache_hit"))
    result["prompt_tokens"] = int(meta.get("prompt_tokens", 0) or 0)
    result["completion_tokens"] = int(meta.get("completion_tokens", 0) or 0)
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return result


@router.post("/ask", response_model=Envelope,
             dependencies=[Depends(rate_limit(settings.rate_limit_llm, "rag"))])
def ask(payload: AskRequest, request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)) -> Envelope:
    convo = _resolve_conversation(db, user, payload.conversation_id,
                                  payload.question, payload.disease)
    db.add(Message(conversation_id=convo.id, role="user", content=payload.question))
    db.commit()

    outcome = _answer(payload.question, payload.disease, payload.use_llm)

    msg = Message(
        conversation_id=convo.id,
        role="assistant",
        content=outcome["answer"],
        citations=[c.model_dump() for c in outcome["citations"]],
        llm_used=outcome["llm_used"],
        latency_ms=outcome["latency_ms"],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    if outcome["llm_used"] or outcome["cache_hit"]:
        db.add(LlmUsage(
            user_id=user.id,
            purpose="rag",
            model=settings.llm_model if outcome["llm_used"] else "cache",
            cache_hit=outcome["cache_hit"],
            prompt_tokens=outcome["prompt_tokens"],
            completion_tokens=outcome["completion_tokens"],
            latency_ms=outcome["latency_ms"],
        ))
        db.commit()

    return _envelope(AskResponse(
        conversation_id=convo.id,
        message_id=msg.id,
        answer=outcome["answer"],
        citations=outcome["citations"],
        refused=outcome["refused"],
        source=outcome["source"],
        llm_used=outcome["llm_used"],
        latency_ms=outcome["latency_ms"],
    ), request)


@router.post("/ask/stream",
             dependencies=[Depends(rate_limit(settings.rate_limit_llm, "rag"))])
def ask_stream(payload: AskRequest, request: Request,
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> StreamingResponse:
    """SSE stream. The answer is computed first, then emitted progressively.

    Retrieval and answer composition are local and fast; streaming the text
    gives the same perceived responsiveness as token streaming without
    paying for a streaming LLM call.
    """
    convo = _resolve_conversation(db, user, payload.conversation_id,
                                  payload.question, payload.disease)
    convo_id = convo.id
    db.add(Message(conversation_id=convo_id, role="user", content=payload.question))
    db.commit()

    outcome = _answer(payload.question, payload.disease, payload.use_llm)

    msg = Message(
        conversation_id=convo_id,
        role="assistant",
        content=outcome["answer"],
        citations=[c.model_dump() for c in outcome["citations"]],
        llm_used=outcome["llm_used"],
        latency_ms=outcome["latency_ms"],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Snapshot every value the generator needs. The `db` session is closed by
    # FastAPI right after this function returns, so touching ORM attributes
    # (e.g. `convo.id`, `msg.id`) inside the generator would raise
    # DetachedInstanceError and abort the stream with an empty body.
    message_id = msg.id
    citations_json = [c.model_dump() for c in outcome["citations"]]
    meta_frame = _sse("meta", {
        "conversation_id": convo_id,
        "message_id": message_id,
        "refused": outcome["refused"],
        "source": outcome["source"],
        "llm_used": outcome["llm_used"],
        "citations": citations_json,
        "latency_ms": outcome["latency_ms"],
    })
    answer_text = outcome["answer"]

    def event_stream():
        yield meta_frame
        step = 6
        for i in range(0, len(answer_text), step):
            yield _sse("delta", {"text": answer_text[i:i + step]})
        yield _sse("done", {"length": len(answer_text)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/conversations", response_model=Envelope)
def list_conversations(request: Request,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)) -> Envelope:
    from sqlalchemy import select

    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    ).all()
    return _envelope([
        {"id": c.id, "title": c.title, "disease": c.disease,
         "updated_at": c.updated_at.isoformat()}
        for c in rows
    ], request)


@router.get("/conversations/{conversation_id}", response_model=Envelope)
def get_conversation(conversation_id: int, request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> Envelope:
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        from app.core.errors import ForbiddenError
        raise ForbiddenError("Conversation not found")
    return _envelope({
        "id": convo.id,
        "title": convo.title,
        "disease": convo.disease,
        "messages": [
            {
                "id": m.id, "role": m.role, "content": m.content,
                "citations": m.citations, "llm_used": m.llm_used,
                "created_at": m.created_at.isoformat(),
            }
            for m in convo.messages
        ],
    }, request)


@router.delete("/conversations/{conversation_id}", response_model=Envelope)
def delete_conversation(conversation_id: int, request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> Envelope:
    convo = db.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        from app.core.errors import ForbiddenError
        raise ForbiddenError("Conversation not found")
    db.delete(convo)
    db.commit()
    return _envelope({"deleted": conversation_id}, request)


@router.get("/sources", response_model=Envelope)
def list_sources(request: Request) -> Envelope:
    """Public: show what the knowledge base actually covers."""
    index = get_index()
    if not index.ready:
        index.build()
    grouped: dict[str, list[str]] = {}
    for chunk in index.chunks:
        grouped.setdefault(chunk.source, []).append(chunk.title)
    return _envelope(
        [{"source": k, "entries": v, "count": len(v)} for k, v in grouped.items()],
        request,
    )


@router.get("/usage", response_model=Envelope)
def llm_usage(request: Request, user: User = Depends(get_current_user)) -> Envelope:
    """Transparency endpoint: show exactly how much LLM budget was consumed."""
    return _envelope(get_gateway().health(), request)


# --------------------------------------------------------------------------- #
# Q&A path comparison
# --------------------------------------------------------------------------- #

@router.post("/compare", response_model=Envelope,
             dependencies=[Depends(rate_limit(settings.rate_limit_llm, "rag"))])
def compare_paths(payload: QaCompareRequest, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> Envelope:
    """Answer the same question several ways and report what differs.

    One retrieval pass is shared by every path, so any difference in the output
    comes from the composition step rather than from different inputs.

    External paths are opt-in and billed, so this endpoint is rate limited and
    every call is accounted. When no API key is configured the external paths
    come back marked ``skipped`` and the comparison still works.

    Supplying ``models`` runs the two external paths once per model
    (``llm_direct@<model>`` / ``llm_rag@<model>``), which is how several models
    get compared against each other on one question. Omitting it keeps the
    original three-column response.
    """
    from app.services.qa_compare import compare

    outcome = compare(payload.question, payload.disease, payload.paths, payload.models)

    comparison_id = None
    if payload.persist:
        by_key = {p["key"]: p for p in outcome["paths"]}

        def first_answer(base: str) -> str | None:
            """Answer of `base`, or of its first `@model` variant.

            The history table keeps one column per base path. With several
            models the first one is stored there and the complete per-path
            metrics live in `path_metrics`, which is JSON and has no width
            limit.
            """
            if base in by_key:
                return by_key[base].get("answer")
            for path in outcome["paths"]:
                if path["key"].split("@", 1)[0] == base:
                    return path.get("answer")
            return None

        row = QaComparison(
            user_id=user.id,
            question=outcome["question"],
            disease=payload.disease,
            refused=outcome["refused"],
            top_score=outcome["top_score"],
            passage_count=outcome["passage_count"],
            answer_local=first_answer("local_rag"),
            answer_llm_direct=first_answer("llm_direct"),
            answer_llm_rag=first_answer("llm_rag"),
            path_metrics=[
                {k: v for k, v in p.items() if k not in ("answer", "citations")}
                for p in outcome["paths"]
            ],
            external_calls=outcome["summary"]["external_calls"],
            cache_hits=outcome["summary"]["cache_hits"],
            prompt_tokens=outcome["summary"]["prompt_tokens"],
            completion_tokens=outcome["summary"]["completion_tokens"],
            cost_cny=outcome["summary"]["cost_cny"],
            total_latency_ms=outcome["total_latency_ms"],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        comparison_id = row.id

        if outcome["summary"]["external_calls"] or outcome["summary"]["cache_hits"]:
            for path in outcome["paths"]:
                if not path["external_call"] or path["status"] != "ok":
                    continue
                db.add(LlmUsage(
                    user_id=user.id,
                    # `purpose` is String(32), so the model is stripped off the
                    # key rather than risking an overlong value — the model has
                    # its own column right below, and it must be the model this
                    # path actually used rather than whatever the process
                    # default happens to be.
                    purpose=f"qa_{path['key'].split('@', 1)[0]}"[:32],
                    model=(path["model"] or settings.llm_model)[:64]
                    if path["llm_used"] else "cache",
                    cache_hit=path["cache_hit"],
                    prompt_tokens=path["prompt_tokens"],
                    completion_tokens=path["completion_tokens"],
                    latency_ms=path["latency_ms"],
                ))
            db.commit()

    outcome["comparison_id"] = comparison_id
    return _envelope(QaCompareResponse(**outcome), request)


@router.get("/comparisons", response_model=Envelope)
def list_comparisons(request: Request,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)) -> Envelope:
    """Recent comparisons, so the cost/grounding difference stays auditable."""
    from sqlalchemy import select

    rows = db.scalars(
        select(QaComparison)
        .where(QaComparison.user_id == user.id)
        .order_by(QaComparison.created_at.desc())
        .limit(30)
    ).all()
    return _envelope([
        {
            "id": r.id,
            "question": r.question,
            "disease": r.disease,
            "refused": r.refused,
            "external_calls": r.external_calls,
            "cache_hits": r.cache_hits,
            "cost_cny": r.cost_cny,
            "total_latency_ms": r.total_latency_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ], request)


@router.get("/comparisons/{comparison_id}", response_model=Envelope)
def get_comparison(comparison_id: int, request: Request,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> Envelope:
    from app.core.errors import ForbiddenError

    row = db.get(QaComparison, comparison_id)
    if row is None or row.user_id != user.id:
        raise ForbiddenError("Comparison not found")
    return _envelope({
        "id": row.id,
        "question": row.question,
        "disease": row.disease,
        "refused": row.refused,
        "top_score": row.top_score,
        "passage_count": row.passage_count,
        "answer_local": row.answer_local,
        "answer_llm_direct": row.answer_llm_direct,
        "answer_llm_rag": row.answer_llm_rag,
        "path_metrics": row.path_metrics,
        "external_calls": row.external_calls,
        "cache_hits": row.cache_hits,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_cny": row.cost_cny,
        "total_latency_ms": row.total_latency_ms,
        "created_at": row.created_at.isoformat(),
    }, request)


@router.delete("/comparisons/{comparison_id}", response_model=Envelope)
def delete_comparison(comparison_id: int, request: Request,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> Envelope:
    from app.core.errors import ForbiddenError

    row = db.get(QaComparison, comparison_id)
    if row is None or row.user_id != user.id:
        raise ForbiddenError("Comparison not found")
    db.delete(row)
    db.commit()
    return _envelope({"deleted": comparison_id}, request)
