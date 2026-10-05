"""Retrieval-augmented Q&A.

**Default behaviour is fully local and costs zero API calls.** The knowledge
base is parsed into structured entries, embedded once with a local
sentence-transformer, and retrieved with FAISS. Answers are composed from the
retrieved passages directly.

An optional LLM synthesis step exists but is off by default and, even when on,
is skipped for short retrievals and served from cache for repeats.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm_gateway import get_gateway, normalize_zh

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Knowledge base parsing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Chunk:
    """One retrievable knowledge entry.

    A markdown section is normally one chunk. Long sections become several
    chunks that share a heading trail, so the citation still tells the reader
    exactly where the passage came from.
    """

    index: int
    source: str
    title: str
    text: str
    disease: str = "general"
    path: tuple[str, ...] = ()
    part: int = 1
    parts: int = 1

    @property
    def breadcrumb(self) -> str:
        """Heading trail, e.g. ``乳腺癌知识库 > 早期症状``."""
        return " > ".join(self.path) if self.path else self.title

    @property
    def citation_title(self) -> str:
        """Breadcrumb shown to the user; split parts are labelled."""
        if self.parts > 1:
            return f"{self.breadcrumb}（{self.part}/{self.parts}）"
        return self.breadcrumb

    @property
    def embed_text(self) -> str:
        """Text handed to the embedding model.

        The heading trail is part of the embedded string on purpose: a question
        naming a topic ("BI-RADS 分级") then matches the *heading* even when the
        body phrases it differently. Without this the heading contributes
        nothing to retrieval, because headings are stripped out of the body.
        """
        head = self.breadcrumb
        if self.parts > 1:
            head = f"{head}（第 {self.part}/{self.parts} 部分）"
        return f"{head}\n{self.text}"


def lexical_text(chunk: Chunk) -> str:
    """The text every *lexical* signal reads.

    Both the BM25 index and the lexical refusal gate go through here, so the two
    cannot drift apart about what a chunk says. The heading trail is included on
    purpose: it is where the precise term usually lives ("BI-RADS 分级"), while
    the body may phrase the same idea in prose.
    """
    return f"{chunk.breadcrumb} {chunk.text}"


# Heading levels 1-6. Level 1 is the document title and becomes the root of the
# breadcrumb rather than a chunk of its own.
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)

# Optional front matter so a new knowledge file can declare its scope without
# depending on its filename, e.g.
#     ---
#     disease: heart
#     ---
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONT_MATTER_KV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")

# Sentence boundaries used when a single paragraph is itself too long.
_SENTENCE = re.compile(r"(?<=[。！？；!?;])\s*|\n+")

_SEP = "\n\n"

# Map source file stems to a disease module so retrieval can be scoped.
_DISEASE_HINTS = {
    "breast": "breast",
    "heart": "heart",
    "cardiac": "heart",
    "disclaimer": "general",
}


def _infer_disease(source: str) -> str:
    stem = source.lower()
    for hint, disease in _DISEASE_HINTS.items():
        if hint in stem:
            return disease
    return "general"


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Split optional ``---`` front matter from the document body."""
    m = _FRONT_MATTER.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = _FRONT_MATTER_KV.match(line.strip())
        if kv:
            meta[kv.group(1).lower()] = kv.group(2).strip()
    return meta, raw[m.end():]


@dataclass(frozen=True)
class Budget:
    """How a piece of text is measured against the embedding window.

    The embedding model truncates silently at its `max_seq_length`, so any
    chunk larger than the window has its tail made invisible to retrieval —
    quietly, with no error. Chunking must therefore be done in whatever unit
    the model actually counts.

    `measure` defaults to character length, which keeps the chunker fast and
    model-free for tests. At index build time we pass the real tokenizer so the
    budget is exact, including the heading trail that is prepended before
    encoding. See `RagIndex.build`.
    """

    limit: int                     # max size of one embedded body
    overlap: int                   # tail size repeated across a split
    measure: Callable[[str], int] = len

    def fits(self, text: str) -> bool:
        return self.measure(text) <= self.limit


def _clamp(text: str, budget: Budget) -> list[str]:
    """Hard-slice `text` into pieces that each measure within the budget.

    This is the last line of defence and it is measurement-exact: it re-measures
    after every cut instead of trusting an estimated chars-per-unit ratio. That
    matters because the ratio varies a lot between prose and text full of
    digits, Latin abbreviations and bracketed units.
    """
    if budget.measure(text) <= budget.limit:
        return [text]

    pieces: list[str] = []
    rest = text
    while rest and budget.measure(rest) > budget.limit:
        per_char = budget.measure(rest) / max(len(rest), 1)
        cut = max(int(budget.limit / max(per_char, 1e-9)) - 1, 1)
        pieces.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        pieces.append(rest)
    return pieces


def _split_oversized(paragraph: str, budget: Budget) -> list[str]:
    """Break a single paragraph that exceeds the budget at sentence seams."""
    sentences = [s.strip() for s in _SENTENCE.split(paragraph) if s.strip()]
    if not sentences:
        return _clamp(paragraph, budget)

    units: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        joined = current + sentence
        if budget.fits(joined):
            current = joined
            continue
        units.append(current)
        current = sentence
    if current:
        units.append(current)

    # A single sentence can still blow the budget; `_clamp` slices it exactly.
    flat: list[str] = []
    for unit in units:
        flat.extend(_clamp(unit, budget))
    return flat


def _overlap_tail(current: str, unit: str, budget: Budget) -> str:
    """Longest tail of `current` that still leaves room for `unit`.

    The overlap is prepended *after* the pack decision, so it has to be
    trimmed to the space actually left — otherwise the tail silently pushes
    the chunk past the embedding window it was just measured against.
    """
    if budget.overlap <= 0:
        return ""
    room = budget.limit - budget.measure(unit) - budget.measure(_SEP)
    if room <= 0:
        return ""
    tail = current[-budget.overlap:]
    size = budget.measure(tail)
    if size <= room:
        return tail.strip()
    keep = max(int(len(tail) * room / max(size, 1)) - 1, 0)
    return tail[-keep:].strip() if keep else ""


def _pack(units: list[str], budget: Budget) -> list[str]:
    """Greedily pack units, repeating a trimmed tail overlap at each split.

    Invariant: every returned piece measures within `budget.limit`.
    """
    flat: list[str] = []
    for unit in units:
        flat.extend(_clamp(unit, budget))

    pieces: list[str] = []
    current = ""
    for unit in flat:
        if not current:
            current = unit
            continue
        if budget.fits(current + _SEP + unit):
            current = f"{current}{_SEP}{unit}"
            continue
        pieces.append(current)
        tail = _overlap_tail(current, unit, budget)
        current = f"{tail}{_SEP}{unit}" if tail else unit
    if current:
        pieces.append(current)
    return pieces


def _split_body(body: str, budget: Budget) -> list[str]:
    """Split a section body into pieces that each fit the budget."""
    if budget.fits(body):
        return [body]

    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        units.append(paragraph)
    if not units:
        return [body]
    return _pack(units, budget)


def _merge_short(chunks: list[Chunk], min_size: int, budget: Budget) -> list[Chunk]:
    """Fold a too-short entry into its predecessor when there is room.

    Near-empty vectors are noise in a small corpus — they occupy a top-k slot
    while carrying almost no content. Merging keeps them searchable as part of
    a richer entry instead of competing with it. The child's own heading is
    kept inline so the merged text still says what it covers.
    """
    merged: list[Chunk] = []
    for chunk in chunks:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and budget.measure(chunk.text) < min_size
            and chunk.disease == prev.disease
            and budget.fits(prev.text + _SEP + chunk.text)
        ):
            merged[-1] = replace(
                prev,
                text=f"{prev.text}{_SEP}{chunk.title}\n{chunk.text}",
            )
            continue
        merged.append(chunk)
    return merged


def parse_markdown_chunks(
    raw: str,
    source: str,
    *,
    max_chars: int | None = None,
    min_chars: int | None = None,
    overlap_chars: int | None = None,
    max_tokens: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """Turn one markdown document into retrievable chunks.

    Structure is `H1` (document title) > `H2`/`H3`/... (sections). Each section
    becomes one chunk, split further only when it exceeds the budget. The
    heading trail travels with the chunk so citations are self-describing.

    Sizing is character-based unless both `max_tokens` and `count_tokens` are
    supplied, in which case the budget is expressed in real model tokens and
    the per-section allowance is reduced by the cost of its heading trail.
    """
    max_chars = max_chars if max_chars is not None else settings.rag_chunk_max_chars
    min_chars = min_chars if min_chars is not None else settings.rag_chunk_min_chars
    overlap_chars = (
        overlap_chars if overlap_chars is not None else settings.rag_chunk_overlap_chars
    )
    # Reserve room for the "（第 x/y 部分）" suffix added when a section splits.
    trail_reserve = len("（第 99/99 部分）")

    token_mode = max_tokens is not None and count_tokens is not None

    def budget_for(path: tuple[str, ...]) -> Budget:
        trail_len = len(" > ".join(path)) + trail_reserve
        if token_mode:
            # Overlap and the minimum are still expressed in characters; only
            # the packing limit needs to be exact.
            head = count_tokens(" > ".join(path) + "（第 99/99 部分）")
            return Budget(
                limit=max(max_tokens - head, 16),
                overlap=overlap_chars,
                measure=count_tokens,
            )
        return Budget(limit=max(max_chars - trail_len, 16), overlap=overlap_chars)

    meta, body_raw = _parse_front_matter(raw)
    disease = meta.get("disease") or _infer_disease(source)

    headings = list(_HEADING.finditer(body_raw))

    # Walk headings, maintaining the ancestor trail used for breadcrumbs.
    # Level 1 is the document title: it becomes the breadcrumb root rather
    # than a section of its own.
    trail: list[str] = []
    resolved: list[tuple[tuple[str, ...], str]] = []
    doc_title = source

    for pos, m in enumerate(headings):
        level = len(m.group(1))
        title = m.group(2).strip()
        end = headings[pos + 1].start() if pos + 1 < len(headings) else len(body_raw)

        trail = trail[: level - 1]
        trail.append(title)

        if level == 1:
            doc_title = title
            continue

        body = body_raw[m.end():end].strip()
        if body:
            resolved.append((tuple(trail), body))

    # Document intro: the text sitting between the H1 line and the first H2.
    intro = ""
    if headings:
        h1 = next((m for m in headings if len(m.group(1)) == 1), None)
        nxt = next((m for m in headings if len(m.group(1)) > 1), None)
        if h1 is not None and nxt is not None:
            intro = body_raw[h1.end():nxt.start()].strip()
    else:
        intro = body_raw.strip()

    minimum = min_chars if not token_mode else min(min_chars, max_tokens // 2)

    if len(intro) >= minimum:
        resolved.insert(0, ((doc_title, "概述"), intro))

    if not resolved:
        # No markdown structure at all — treat paragraphs as entries.
        resolved = [
            ((source, "知识条目"), block.strip())
            for block in re.split(r"\n\s*\n", body_raw)
            if len(block.strip()) > 40
        ]

    chunks: list[Chunk] = []
    for path, body in resolved:
        if not body:
            continue
        pieces = _split_body(body, budget_for(path))
        for part, piece in enumerate(pieces, start=1):
            chunks.append(Chunk(
                index=len(chunks),
                source=source,
                title=path[-1],
                text=piece,
                disease=disease,
                path=path,
                part=part,
                parts=len(pieces),
            ))

    # Merge across sections, so use the loosest budget in play.
    return _merge_short(chunks, minimum, budget_for(()))


def load_knowledge_dir(
    directory: Path,
    *,
    max_tokens: int | None = None,
    count_tokens: Callable[[str], int] | None = None,
) -> list[Chunk]:
    if not directory.exists():
        logger.warning(f"Knowledge directory missing: {directory}")
        return []

    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")) + sorted(directory.glob("*.txt")):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Cannot read {path.name}: {exc}")
            continue
        file_chunks = parse_markdown_chunks(
            raw, source=path.stem, max_tokens=max_tokens, count_tokens=count_tokens
        )
        # Re-index globally so citations are stable across files.
        # NOTE: `disease`/`path` must be carried across — dropping them here
        # would silently disable per-disease scoping and break breadcrumbs.
        for c in file_chunks:
            chunks.append(Chunk(
                index=len(chunks), source=c.source, title=c.title, text=c.text,
                disease=c.disease, path=c.path, part=c.part, parts=c.parts,
            ))
    logger.info(
        f"Knowledge base: {len(chunks)} chunks from {directory} "
        f"(avg {sum(len(c.text) for c in chunks) // max(len(chunks), 1)} chars)"
    )
    return chunks


# --------------------------------------------------------------------------- #
# Embedding + index
# --------------------------------------------------------------------------- #

def _make_token_counter(model) -> Callable[[str], int]:
    """Exact token counter for the loaded embedding model.

    Chunking deliberately builds oversize pieces before splitting them, so the
    tokenizer's "sequence longer than maximum" warning is expected noise here
    and is silenced once, at the source.
    """
    import logging as _logging

    _logging.getLogger("transformers.tokenization_utils_base").setLevel(_logging.ERROR)
    tokenizer = model.tokenizer

    def count(text: str) -> int:
        if not text:
            return 0
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    return count


# --------------------------------------------------------------------------- #
# Lexical retrieval (BM25) and fusion
# --------------------------------------------------------------------------- #
#
# Dense retrieval alone is weak exactly where this corpus is strongest: proper
# nouns, abbreviations and numbers. "BI-RADS 4A" and "0.1701" carry almost no
# semantic mass for a sentence encoder — they are rare tokens, and the embedding
# of a question containing them drifts toward the surrounding prose. A lexical
# scorer has the opposite bias, which is why the two are combined.
#
# BM25 is implemented here rather than imported. It is about thirty lines of a
# published formula, and — more importantly — it must be driven by *exactly* the
# tokenizer the lexical refusal gate already uses. A second tokenizer would make
# the two lexical signals disagree about the same text.

#: Standard Okapi BM25 constants. `k1` damps term-frequency saturation, `b`
#: controls length normalisation; both are the values from the original paper and
#: neither needed tuning at this corpus size.
_BM25_K1 = 1.5
_BM25_B = 0.75


class _Bm25:
    """Okapi BM25 over the whole corpus, built once next to the vector index."""

    def __init__(self, docs: list[list[str]],
                 k1: float = _BM25_K1, b: float = _BM25_B) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0

        self.tf: list[dict[str, int]] = []
        document_frequency: dict[str, int] = {}
        for doc in docs:
            counts: dict[str, int] = {}
            for token in doc:
                counts[token] = counts.get(token, 0) + 1
            self.tf.append(counts)
            for term in counts:
                document_frequency[term] = document_frequency.get(term, 0) + 1

        # Classic Robertson/Sparck-Jones IDF, clamped at zero. The clamp is
        # load-bearing rather than cosmetic: a term present in *every* document
        # yields a negative value here, which would make a query built from
        # ubiquitous words ("乳腺", say) score chunks that lack the term *higher*
        # than chunks that contain it. Clamping gives exactly 0, and `search`
        # treats a zero score as "not a candidate" — so ubiquitous terms drop out
        # of the lexical ranking entirely instead of dominating it.
        self.idf = {
            term: max(math.log((self.n - df + 0.5) / (df + 0.5)), 0.0)
            for term, df in document_frequency.items()
        }

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        """BM25 score per document. Zero means "shares no term with the query"."""
        out = np.zeros(self.n, dtype="float32")
        if not self.n or self.avgdl <= 0:
            return out
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if not idf:
                continue
            for i, counts in enumerate(self.tf):
                freq = counts.get(term)
                if not freq:
                    continue
                norm = freq + self.k1 * (
                    1 - self.b + self.b * self.doc_len[i] / self.avgdl
                )
                out[i] += idf * (freq * (self.k1 + 1)) / norm
        return out


def _rrf_fuse(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion over several rankings of the same corpus.

    Fuses *ranks*, not scores. BM25 is unbounded while cosine lives in [-1, 1],
    so adding the two would need a normalisation constant — and that constant is
    itself an untested tunable that drifts as the corpus grows. RRF only needs
    the order each retriever produced, so there is nothing to calibrate.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + rank + 1)
    return fused


class RagIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._model = None
        self._index = None
        self._lock = threading.Lock()
        self._ready = False
        self._load_error: str | None = None
        self.chunk_stats: dict[str, Any] = {}
        # Hybrid retrieval state. `_embeddings` is kept alongside the FAISS index
        # so a BM25-only candidate still gets a cosine without a second encode
        # pass — see `search`.
        self._embeddings: np.ndarray | None = None
        self._bm25: _Bm25 | None = None
        #: What the most recent query actually did, surfaced through
        #: `retrieval_info()` so the hybrid path is observable rather than a
        #: claim the reader has to take on trust.
        self.last_retrieval: dict[str, Any] = {}
        self._reranker = None
        self._rerank_failed = False

    # -- lazy init ------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return self._ready

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {settings.embedding_model}")
            self._model = SentenceTransformer(settings.embedding_model)
        return self._model

    def _ensure_reranker(self):
        """Load the cross-encoder, or give up quietly and permanently.

        Reranking is an accuracy improvement, not a dependency. If the model
        cannot be obtained — offline container, empty cache, not enough memory —
        retrieval must keep working on the fused ranking rather than go dark, so
        every failure path returns ``None``. The failure is remembered so the
        warning is logged once instead of on every single query.
        """
        if self._rerank_failed or not settings.rag_rerank_enabled:
            return None
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder

                logger.info(f"Loading reranker: {settings.rag_rerank_model}")
                self._reranker = CrossEncoder(
                    settings.rag_rerank_model,
                    max_length=settings.rag_rerank_max_tokens,
                )
                logger.info("Reranker ready")
            except Exception as exc:
                self._rerank_failed = True
                logger.warning(
                    f"Reranker unavailable ({exc}); retrieval falls back to the "
                    "fused dense + BM25 ranking. Set RAG_RERANK_ENABLED=false to "
                    "silence this."
                )
                return None
        return self._reranker

    def _load_chunks(self, model) -> list[Chunk]:
        """Chunk the knowledge base to fit the model's real window."""
        window = int(getattr(model, "max_seq_length", 128) or 128)
        # Reserve [CLS]/[SEP]; the heading trail is subtracted per section.
        max_tokens = max(window - 4, 24)
        count = _make_token_counter(model)
        chunks = load_knowledge_dir(
            settings.knowledge_dir, max_tokens=max_tokens, count_tokens=count
        )
        oversize = [c for c in chunks if count(c.embed_text) > window - 2]
        self.chunk_stats = {
            "window": window,
            "max_tokens": max_tokens,
            "count": len(chunks),
            "oversize": len(oversize),
            "avg_chars": (
                sum(len(c.text) for c in chunks) // len(chunks) if chunks else 0
            ),
            "split_sections": sum(1 for c in chunks if c.parts > 1),
        }
        if oversize:
            logger.warning(
                f"{len(oversize)} chunk(s) still exceed the {window}-token "
                f"embedding window and will be truncated: "
                f"{[c.citation_title for c in oversize[:3]]}"
            )
        return chunks

    def build(self) -> None:
        with self._lock:
            if self._ready:
                return
            try:
                model = self._ensure_model()
                self.chunks = self._load_chunks(model)
            except Exception as exc:
                # Degraded mode: fall back to character budgeting so Q&A still
                # works, rather than leaving the feature dead.
                logger.warning(
                    f"Token-aware chunking unavailable ({exc}); "
                    "falling back to character budgeting"
                )
                self.chunks = load_knowledge_dir(settings.knowledge_dir)

            if not self.chunks:
                self._load_error = "knowledge base is empty"
                return
            try:
                import faiss

                model = self._ensure_model()
                corpus = [c.embed_text for c in self.chunks]
                embeddings = model.encode(
                    corpus, normalize_embeddings=True, show_progress_bar=False
                ).astype("float32")

                index = faiss.IndexFlatIP(embeddings.shape[1])  # inner product on unit vectors
                index.add(embeddings)
                self._index = index
                # Kept so BM25-only candidates can be given a cosine without
                # re-encoding them one by one.
                self._embeddings = embeddings

                if settings.rag_hybrid_enabled:
                    # Indexed over `lexical_text` — the same string the lexical
                    # refusal gate scores against, so the two agree by
                    # construction rather than by convention.
                    self._bm25 = _Bm25(
                        [tokenize(lexical_text(c)) for c in self.chunks]
                    )

                # Load the reranker here rather than on the first question: a
                # cold query would otherwise absorb a multi-second model load (or
                # a ~1 GB download) and be reported as that answer's latency.
                # Failing here is survivable — see `_ensure_reranker`.
                self._ensure_reranker()

                self._ready = True
                logger.info(
                    f"RAG index built: {index.ntotal} vectors, dim={embeddings.shape[1]}, "
                    f"chunking={self.chunk_stats or 'char-budget'}, "
                    f"retrieval={self.retrieval_info()['mode']}"
                )
            except Exception as exc:
                self._load_error = str(exc)
                logger.error(f"RAG index build failed: {exc}")

    def warm_up(self) -> None:
        self.build()

    # -- observability -------------------------------------------------- #
    def _current_mode(self) -> str:
        """Which retrieval stack is live right now.

        Every branch re-reads its configuration flag rather than just checking
        whether the component is loaded. Reporting "hybrid+rerank" because a
        reranker happens to be in memory would make `retrieval_info` disagree with
        what `search` actually does when the flag is off — and this value exists
        precisely to be the thing a reader can trust.
        """
        if (
            settings.rag_rerank_enabled
            and self._reranker is not None
            and not self._rerank_failed
        ):
            return "hybrid+rerank"
        if settings.rag_hybrid_enabled and self._bm25 is not None:
            return "hybrid"
        return "dense"

    def retrieval_info(self) -> dict[str, Any]:
        """What retrieval is *actually* doing, for `/health`.

        Published deliberately. "We added hybrid retrieval and a reranker" is
        otherwise an unverifiable claim: a reader cannot tell a working BM25 pass
        from one that silently degraded to dense-only because a model download
        failed. `last_query` makes the difference visible per request.
        """
        return {
            "mode": self._current_mode(),
            "hybrid_enabled": settings.rag_hybrid_enabled,
            "hybrid": settings.rag_hybrid_enabled and self._bm25 is not None,
            "bm25": "okapi" if self._bm25 is not None else None,
            "rrf_k": settings.rag_rrf_k,
            "candidates": settings.rag_retrieve_candidates,
            "rerank_enabled": settings.rag_rerank_enabled,
            "rerank_model": (
                settings.rag_rerank_model
                if settings.rag_rerank_enabled
                and self._reranker is not None
                and not self._rerank_failed
                else None
            ),
            "rerank_unavailable": self._rerank_failed,
            "last_query": self.last_retrieval or None,
        }

    # -- retrieval ------------------------------------------------------ #
    def search(self, query: str, top_k: int | None = None,
               disease: str | None = None) -> list[tuple[Chunk, float]]:
        """Retrieve passages, optionally scoped to one disease module.

        General-purpose chunks (e.g. the disclaimer) remain eligible for every
        query; disease-specific chunks from *other* modules are excluded so a
        breast-cancer question can never be answered with cardiology text.

        Ranking is hybrid: dense vectors and BM25 each propose candidates, the two
        rankings are fused with RRF, and — when the cross-encoder is available —
        the fused head is reordered by it.

        The float travelling with each chunk is the passage's **raw cosine**, not
        its ranking score. That separation is not cosmetic: the refusal gate
        compares against `rag_min_similarity`, a threshold calibrated in cosine
        space, and folding a BM25 score into that number would move the threshold
        silently. See `compose_local_answer`.
        """
        if not self._ready:
            self.build()
        if not self._ready or self._index is None or self._embeddings is None:
            return []

        top_k = top_k or settings.rag_top_k
        model = self._ensure_model()
        qvec = model.encode([query], normalize_embeddings=True).astype("float32")[0]

        # Scope is resolved up front and applied to *every* retriever, because
        # fusion must never be able to reintroduce a chunk from another module.
        in_scope = [
            i for i, c in enumerate(self.chunks)
            if not disease or c.disease in ("general", disease)
        ]
        if not in_scope:
            return []
        scope = set(in_scope)

        # -- dense candidates ------------------------------------------- #
        if disease:
            # A scoped search cannot cap its over-fetch. Every medical chunk is
            # lexically similar to any medical question, so a capped fetch could
            # be filled entirely by the *other* module and then filtered down to
            # nothing — which turned a precise "switch module" answer into a
            # generic refusal. The corpus is small enough that scanning it all
            # costs nothing.
            fetch_k = len(self.chunks)
        else:
            fetch_k = min(
                max(top_k * 6, settings.rag_retrieve_candidates), len(self.chunks)
            )
        _, indices = self._index.search(qvec.reshape(1, -1), fetch_k)
        dense_rank = [i for i in (int(x) for x in indices[0]) if i >= 0 and i in scope]

        # -- lexical candidates ----------------------------------------- #
        lexical_rank: list[int] = []
        if settings.rag_hybrid_enabled and self._bm25 is not None:
            bm25 = self._bm25.scores(tokenize(query))
            # `argsort` on the negated scores is descending order; a score of
            # zero means "shares no term with the question" and is not a
            # candidate at all, so it is dropped rather than ranked last.
            top_n = max(top_k * 6, settings.rag_retrieve_candidates)
            lexical_rank = [
                i for i in np.argsort(-bm25).tolist() if bm25[i] > 0 and i in scope
            ][:top_n]

        # -- fusion ----------------------------------------------------- #
        if settings.rag_hybrid_enabled and lexical_rank:
            fused = _rrf_fuse([dense_rank, lexical_rank], settings.rag_rrf_k)
            order = sorted(fused, key=lambda i: (-fused[i], i))
        else:
            order = dense_rank

        # Cosine for every surviving candidate, including the ones only BM25
        # proposed. Stored vectors are already unit-length, so the inner product
        # *is* the cosine; one matmul over the corpus beats the bookkeeping that
        # skipping it would need.
        cosines = self._embeddings @ qvec

        head = order[:settings.rag_retrieve_candidates]

        # -- rerank ----------------------------------------------------- #
        reranked = 0
        reranker = self._ensure_reranker()
        if reranker is not None and len(head) > 1:
            try:
                pairs = [(query, self.chunks[i].embed_text) for i in head]
                raw = np.asarray(reranker.predict(pairs), dtype="float32").reshape(-1)
                head = [head[i] for i in np.argsort(-raw).tolist()]
                reranked = len(head)
            except Exception as exc:
                # A query-time failure is as survivable as a load-time one, and
                # just as permanent: stop paying for it on every request.
                self._rerank_failed = True
                logger.warning(
                    f"Reranking failed at query time ({exc}); "
                    "using the fused ranking from now on"
                )

        self.last_retrieval = {
            "mode": self._current_mode(),
            "dense": len(dense_rank),
            "lexical": len(lexical_rank),
            "fused": len(order),
            "reranked": reranked,
        }
        return [(self.chunks[i], float(cosines[i])) for i in head[:top_k]]

    def embed_query(self, texts: list[str]) -> np.ndarray:
        model = self._ensure_model()
        return model.encode(texts, normalize_embeddings=True)


def tokenize(text: str) -> list[str]:
    """Cheap bilingual tokenizer: CJK bigrams + latin words.

    Public because the answer-comparison metrics reuse it to measure how much
    of an answer's vocabulary is actually present in the retrieved text.
    """
    text = normalize_zh(text)
    tokens = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend("".join(cjk[i:i + 2]) for i in range(max(len(cjk) - 1, 0)))
    return tokens


_index_singleton: RagIndex | None = None


def get_index() -> RagIndex:
    global _index_singleton
    if _index_singleton is None:
        _index_singleton = RagIndex()
    return _index_singleton


# --------------------------------------------------------------------------- #
# Passage assembly (small-to-big)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Passage:
    """One cited block of an answer.

    Retrieval works at chunk granularity so every vector fits the embedding
    window, but a reader should never be shown an article chopped into thirds
    and labelled the same heading three times. Sibling parts of one section are
    therefore recombined here into a single passage with a single citation.
    """

    title: str
    text: str
    source: str
    score: float
    parts: int = 1

    @property
    def citation_title(self) -> str:
        if self.parts > 1:
            return f"{self.title}（合并 {self.parts} 段）"
        return self.title


def group_passages(hits: list[tuple[Chunk, float]]) -> list[Passage]:
    """Collapse retrieved chunks into one passage per source section.

    Grouping preserves the score order of each section's best-scoring part, so
    the passage ranking is still exactly the retrieval ranking.
    """
    order: list[tuple[str, tuple[str, ...]]] = []
    buckets: dict[tuple[str, tuple[str, ...]], list[tuple[Chunk, float]]] = {}

    for chunk, score in hits:
        key = (chunk.source, chunk.path)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append((chunk, score))

    passages: list[Passage] = []
    for key in order:
        members = sorted(buckets[key], key=lambda x: x[0].part)
        title = members[0][0].breadcrumb or members[0][0].title
        passages.append(Passage(
            title=title,
            text=_SEP.join(c.text for c, _ in members),
            source=key[0],
            score=max(s for _, s in members),
            parts=len(members),
        ))
    return passages


# --------------------------------------------------------------------------- #
# Answer composition (local, zero-cost)
# --------------------------------------------------------------------------- #

# Anchored, and deliberately narrow: "你好，乳腺癌怎么筛查" is a real question and
# must not be swallowed by the greeting branch. `？`/`?` are included because
# "在吗？" is an extremely common way to open a chat.
_GREETING = re.compile(
    r"^(你好|您好|hi|hello|hey|在吗)[!！。.？?\s]*$", re.IGNORECASE
)

# A greeting is not an unanswerable medical question, so it must not be met with
# the "nothing relevant was found, please seek a doctor" refusal — that reads as
# a failure and gives the user nothing to act on.
GREETING_REPLY = (
    "你好，我是本系统的医学科普助手，会基于本地知识库回答与当前病种相关的问题。\n\n"
    "你可以试着这样提问：\n"
    "· 这个病通常有哪些早期表现？\n"
    "· 常用的筛查或检查方法有哪些？\n"
    "· 检查报告上的某个指标意味着什么？\n\n"
    "如果你的问题超出了当前知识库的范围，我会直接说明，而不会凭猜测作答。"
)

REFUSAL_TEXT = (
    "抱歉，本地知识库中没有检索到与该问题直接相关的内容，因此不便凭猜测作答。\n\n"
    "为了您的健康，建议：\n"
    "1. 携带完整检查报告前往正规医院对应专科就诊；\n"
    "2. 本系统仅提供健康科普与辅助参考，任何诊疗决策请以执业医师意见为准。\n\n"
    "您也可以换一种问法，例如询问具体症状、诊断方法、治疗手段或预防筛查等话题。"
)

_DISEASE_LABEL = {"breast": "乳腺癌", "heart": "心脏病"}


def _out_of_scope_answer(disease: str, foreign: list[str]) -> str:
    """Refusal tailored to a question that belongs to another module."""
    label = _DISEASE_LABEL.get(disease, disease)
    return (
        f"您的问题涉及{'、'.join(foreign[:3])}，超出了当前「{label}」知识库的检索范围。\n\n"
        f"本系统的不同病种知识库严格隔离，以避免概念混淆、保证每条引用都可核查。\n\n"
        f"如需查询该内容，请在左侧「病种模块」切换到对应模块后重新提问；\n"
        f"也欢迎继续询问关于{label}的具体问题，例如症状、诊断方法或筛查建议。"
    )


def _token_coverage(question: str, chunk: Chunk) -> float:
    """Fraction of the question's content tokens present in the passage.

    A pure embedding score cannot tell "今天天气怎么样" apart from medical text
    when the corpus is small; requiring lexical overlap as well closes that gap.
    """
    q_tokens = {t for t in tokenize(question) if len(t) >= 2}
    if not q_tokens:
        return 1.0
    body = set(tokenize(lexical_text(chunk)))
    return len(q_tokens & body) / len(q_tokens)


# Disease-defining terms. If a question names a disease that is *not* the
# scope it was asked under, the question is out of scope regardless of how
# high the embedding similarity is — Chinese medical vocabulary overlaps
# heavily, so "冠心病如何诊断" scores 0.47 against breast-cancer text.
_DISEASE_TERMS: dict[str, tuple[str, ...]] = {
    "breast": (
        "乳腺", "乳房", "乳癌", "乳头", "钼靶", "birads", "bi-rads",
        "乳腺导管", "前哨淋巴结",
    ),
    "heart": (
        "心脏", "冠心病", "心肌", "心梗", "心血管", "心律", "心电图",
        "冠脉", "冠状动脉", "心绞痛", "心衰", "血压", "胸痛", "房颤",
        "心脏骤停", "心功能",
    ),
}


def _foreign_disease_terms(question: str, disease: str | None) -> list[str]:
    """Terms from *other* disease modules that appear in the question."""
    if not disease:
        return []
    normalized = normalize_zh(question)
    foreign: list[str] = []
    for other, terms in _DISEASE_TERMS.items():
        if other == disease:
            continue
        foreign.extend(t for t in terms if t in normalized)
    return foreign


def is_greeting(text: str) -> bool:
    """True when the whole input is just a greeting.

    Exported so callers can label the answer honestly: a greeting comes from
    neither the knowledge base nor a refusal, and reporting it as
    `source="knowledge_base"` would be a small lie that callers might branch on.
    """
    return bool(_GREETING.match(text.strip()))


def compose_local_answer(
    question: str,
    hits: list[tuple[Chunk, float]],
    disease: str | None = None,
    passages: list[Passage] | None = None,
) -> tuple[str, bool]:
    """Build an answer from retrieved passages. Returns (answer, refused)."""
    if is_greeting(question):
        return GREETING_REPLY, False

    if not hits:
        return REFUSAL_TEXT, True

    # Measured against `hits[0]` only — deliberately *not* the best hit, unlike
    # the cosine below. On the real corpus, taking the best hit here would turn
    # four honest refusals into four confident answers cited to the wrong
    # section (see the comment at `top_score`).
    top_chunk = hits[0][0]
    coverage = _token_coverage(question, top_chunk)

    # Gate 0: the question names a *different* disease than the active scope.
    # This is the only reliable signal when vocabulary overlaps.
    foreign = _foreign_disease_terms(question, disease)
    if foreign:
        logger.info(
            f"RAG refusing: question mentions out-of-scope disease terms "
            f"{foreign} while scope={disease}"
        )
        return _out_of_scope_answer(disease, foreign), True

    # Two independent gates: semantic similarity AND lexical grounding.
    # Neither alone is reliable on a small curated corpus.
    #
    # `search()` orders hits by the hybrid ranking but reports each passage's
    # **raw cosine**, precisely so this gate can keep reading a cosine: the
    # threshold below was calibrated in that space and fusing a BM25 score into
    # it would move the threshold silently.
    #
    # It takes the best cosine among the returned hits rather than `hits[0]`'s.
    # A lexical promotion legitimately puts a lower-cosine passage first — that
    # is the entire point of adding BM25 — and refusing a well-grounded question
    # because the lexical retriever did its job would invert the intent.
    #
    # `coverage` above is deliberately the opposite: it reads `hits[0]` only.
    # The two are not meant to be unified. On the real corpus the four questions
    # dense retrieval gets wrong have max cosines of 0.43-0.61 (so this gate
    # stays quiet) and a coverage of 0.000 against the passage dense put first;
    # a best-over-hits coverage would have scored 0.125-0.333, clearing the 0.12
    # threshold, and all four would have been answered from a section sharing no
    # content word with the question. The refusal is this gate reporting the
    # truth about the passage it was handed.
    top_score = max(score for _, score in hits)
    weak_semantic = top_score < settings.rag_min_similarity
    weak_lexical = coverage < settings.rag_min_token_coverage
    if weak_semantic or weak_lexical:
        logger.info(
            f"RAG refusing: top_score={top_score:.3f} "
            f"(min {settings.rag_min_similarity}), coverage={coverage:.3f} "
            f"(min {settings.rag_min_token_coverage})"
        )
        return REFUSAL_TEXT, True

    blocks: list[str] = []
    for i, passage in enumerate(passages or group_passages(hits), start=1):
        body = re.sub(r"\s*\n\s*", "\n", passage.text.strip())
        # Lead with the section heading on its own line. Plain text, no markup:
        # the answer is rendered as pre-wrapped text in the UI, so any markdown
        # syntax here would be shown to the user verbatim.
        blocks.append(f"{passage.title.split(' > ')[-1]}\n{body} [^c{i}]")

    answer = "\n\n".join(blocks)
    answer += (
        "\n\n---\n"
        "以上内容整理自本地知识库，仅供健康科普参考，"
        "不能替代执业医师的诊断与治疗建议。"
    )
    return answer, False


# --------------------------------------------------------------------------- #
# Optional LLM synthesis
# --------------------------------------------------------------------------- #

SYNTH_SYSTEM = (
    "你是一位严谨的医学科普助手。请**仅依据**下方提供的参考资料回答用户问题。"
    "要求：\n"
    "1. 用简体中文，条理清晰，可用小标题或编号列表；\n"
    "2. 每条关键结论后用 [^c1] 形式标注对应的参考资料编号；\n"
    "3. 参考资料没有提到的内容，明确说明「资料中未提及」，严禁编造；\n"
    "4. 不给出具体药物剂量，不做出「一定」「保证」等绝对化判断；\n"
    "5. 结尾用一句话提醒用户以医师意见为准。"
)


def synthesize_with_llm(
    question: str,
    hits: list[tuple[Chunk, float]],
    embed_fn,
    *,
    model: str | None = None,
) -> tuple[str | None, dict]:
    """LLM-rewritten answer. Skipped for short retrievals; cached on repeat.

    `model` overrides the configured model for this call only, so one
    comparison can ask several models the same contextualised question.
    """
    context = "\n\n".join(
        f"[^c{i}] 《{c.title}》\n{c.text}" for i, (c, _) in enumerate(hits, start=1)
    )
    total_chars = len(context)
    if total_chars < settings.llm_min_chars_for_call:
        logger.info(f"LLM synthesis skipped (context too short: {total_chars} chars)")
        return None, {"llm_used": False, "cache_hit": False, "skipped": "short_context"}

    user = (
        f"参考资料：\n{context}\n\n"
        f"用户问题：{question}\n\n"
        "请基于以上资料作答，并保留 [^cN] 引用标记。"
    )
    gateway = get_gateway()
    return gateway.complete(
        purpose="rag",
        system=SYNTH_SYSTEM,
        user=user,
        cache_payload=question,     # paraphrase of the same question reuses the answer
        embed_fn=embed_fn,
        temperature=0.2,
        model=model,
    )
