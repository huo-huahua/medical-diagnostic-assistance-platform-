"""A/B harness for the retrieval stack: dense vs hybrid vs hybrid+rerank.

`docs/KNOWLEDGE_BASE.md` claims hybrid retrieval helps on abbreviations and
numbers. A claim like that is worth nothing unless it can be re-measured, and it
cannot be measured by reading the diff — so this runs the three configuration
states the shipped code can actually be in (`RAG_HYBRID_ENABLED` /
`RAG_RERANK_ENABLED`) and prints what each one retrieves.

Two design choices are deliberate:

* **The index is built once and the flags are flipped between passes.** The
  three modes therefore share one set of embeddings and one BM25 index, so a
  difference in the output can only come from the ranking stage — not from a
  different vector space. It also means this script doubles as a check that the
  two switches actually change behaviour, which is the one thing a config flag
  can silently fail to do.
* **Expectations are derived from the corpus, not typed in.** Each probe names an
  *anchor*, a term that must exist in the knowledge base, and the expected
  section is looked up from wherever that anchor lives. A probe whose anchor is
  missing, or lives in two sections, is reported as unusable rather than counted
  as a failure. (The first version of this script hard-coded section titles from
  memory; three of them named sections that do not exist, which made a working
  stack look broken.)

Usage, from the repository root:

    PYTHONPATH=backend python _tools/eval_retrieval.py
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

try:  # Windows consoles default to GBK and would mangle the Chinese output.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass

from app.core.config import settings  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    RagIndex,
    compose_local_answer,
    lexical_text,
)

# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #
#
# `anchor` is a term that exists verbatim in the knowledge base; the expected
# section is derived from it. The first group is what BM25 is *for*: an
# abbreviation or a number is a rare token carrying almost no semantic mass, so a
# sentence encoder drifts toward the surrounding prose. The second group is the
# control — ordinary paraphrase questions that dense retrieval already handles,
# and which this change must not break.

PROBES: list[tuple[str, str, str]] = [
    # -- rare token: abbreviation / number / proper noun ------------------- #
    ("BI-RADS 4A 是什么意思？", "breast", "4A"),
    ("TNM 分期怎么划分？", "breast", "TNM"),
    ("前哨淋巴结活检是做什么的？", "breast", "前哨淋巴结"),
    ("钼靶X线有什么作用？", "breast", "钼靶X线"),
    ("Youden 指数是怎么用的？", "breast", "Youden"),
    ("约登指数是什么意思？", "breast", "约登"),
    ("布里尔分数衡量什么？", "breast", "布里尔"),
    ("数据泄漏为什么会让评估失真？", "breast", "数据泄漏"),
    ("交叉验证的作用是什么？", "breast", "交叉验证"),
    ("房颤是怎么回事？", "heart", "房颤"),
    # -- control: ordinary paraphrase ------------------------------------- #
    #
    # Anchored on full section titles. A bare content word like "早期症状" also
    # occurs in the cardiology module, which makes the probe ambiguous and it is
    # reported as unusable rather than counted — the harness refuses to guess
    # which section you meant. A title only ever appears in its own breadcrumb.
    ("乳腺癌的早期症状有哪些？", "breast", "乳腺癌早期症状"),
    ("乳腺癌的筛查方法有哪些？", "breast", "乳腺癌预防与筛查"),
    ("冠心病应该如何治疗？", "heart", "冠心病治疗手段"),
    ("心电图能查出什么问题？", "heart", "心电图能查出什么"),
    ("心力衰竭有哪些典型表现？", "heart", "心力衰竭基本概念"),
]

# Questions the knowledge base must refuse. Better retrieval is worthless if the
# safety gate moved at the same time, so these are measured alongside — the
# refusal is a user-visible outcome too.
REFUSALS: list[tuple[str, str]] = [
    ("今天天气怎么样？", "breast"),
    ("怎么给股票开户？", "breast"),
    ("乳腺癌应该怎么治疗？", "heart"),
    ("冠心病应该如何治疗？", "breast"),
]

# (label, RAG_HYBRID_ENABLED, RAG_RERANK_ENABLED)
MODES: list[tuple[str, bool, bool]] = [
    ("dense", False, False),
    ("hybrid", True, False),
    ("hybrid+rerank", True, True),
]


@contextmanager
def _configured(hybrid: bool, rerank: bool):
    """Temporarily flip the two switches the shipped code reads."""
    before = (settings.rag_hybrid_enabled, settings.rag_rerank_enabled)
    settings.rag_hybrid_enabled, settings.rag_rerank_enabled = hybrid, rerank
    try:
        yield
    finally:
        settings.rag_hybrid_enabled, settings.rag_rerank_enabled = before


def _resolve(chunks, anchor: str) -> tuple[str | None, str]:
    """Section whose text contains `anchor`. Empty or ambiguous = unusable."""
    titles = sorted({
        c.title for c in chunks if anchor.lower() in lexical_text(c).lower()
    })
    if not titles:
        return None, "anchor not in corpus"
    if len(titles) > 1:
        return None, "anchor spans " + "/".join(titles[:3])
    return titles[0], ""


def _measure(index: RagIndex, chunks) -> dict:
    """One pass over every probe with the current flags."""
    rows, unusable = [], []
    for question, disease, anchor in PROBES:
        expected, why = _resolve(chunks, anchor)
        if expected is None:
            unusable.append((question, why))
            continue

        started = time.perf_counter()
        hits = index.search(question, top_k=settings.rag_top_k, disease=disease)
        elapsed_ms = (time.perf_counter() - started) * 1000
        _, refused = compose_local_answer(question, hits, disease=disease)
        top = hits[0][0].title if hits else "—"
        rows.append({
            "question": question,
            "expected": expected,
            "top": top,
            "hit1": top == expected,
            # Ranked second is still *found*, and with five passages retrieved it
            # may well be cited. Both numbers are reported because a reranker is
            # usually worth more at rank 1 than at rank 5.
            "in_topk": expected in [c.title for c, _ in hits],
            "cosine": hits[0][1] if hits else 0.0,
            "refused": refused,
            "ms": elapsed_ms,
        })

    negatives = []
    for question, disease in REFUSALS:
        hits = index.search(question, top_k=settings.rag_top_k, disease=disease)
        _, refused = compose_local_answer(question, hits, disease=disease)
        negatives.append({"question": question, "refused": refused})

    return {
        "info": index.retrieval_info(),
        "rows": rows,
        "negatives": negatives,
        "unusable": unusable,
    }


def _report(result: dict, width: int) -> None:
    info, rows = result["info"], result["rows"]
    print()
    print("=" * 104)
    print(f"  mode={info['mode']}  candidates={info['candidates']}  rrf_k={info['rrf_k']}"
          f"  rerank={info['rerank_model'] or '—'}"
          f"  rerank_unavailable={info['rerank_unavailable']}")
    print("=" * 104)
    print(f"  {'probe'.ljust(width)}{'hit@1':>6}{'top5':>6}{'cosine':>8}{'ms':>8}"
          f"{'refused':>9}  top-1 section")
    for row in rows:
        print(
            f"  {'OK ' if row['hit1'] else '·  '}{row['question'].ljust(width)}"
            f"{'Y' if row['hit1'] else 'n':>4}"
            f"{'Y' if row['in_topk'] else 'n':>6}"
            f"{row['cosine']:>8.4f}{row['ms']:>7.0f}ms"
            f"{'REFUSED' if row['refused'] else '-':>9}  {row['top']}"
            + ("" if row["hit1"] else f"   (want: {row['expected']})")
        )
    n = max(len(rows), 1)
    print("-" * 104)
    print(f"  hit@1 {sum(r['hit1'] for r in rows)}/{len(rows)}"
          f"   in top-5 {sum(r['in_topk'] for r in rows)}/{len(rows)}"
          f"   probes refused {sum(r['refused'] for r in rows)}/{len(rows)}"
          f"   mean {sum(r['ms'] for r in rows) / n:.0f}ms")
    for question, why in result["unusable"]:
        print(f"    ! unusable probe: {question} — {why}")


def main() -> int:
    print("building the index once; the three passes differ only in ranking")
    # Build with *everything* enabled, then flip flags per pass. Building takes
    # ~50s and the flags only affect the ranking stage, so the three passes share
    # one set of embeddings and one BM25 index — a difference in the output can
    # then only come from ranking. It also means both optional components are
    # loaded up front, which a default-config build would skip for the reranker.
    with _configured(hybrid=True, rerank=True):
        index = RagIndex()
        started = time.perf_counter()
        index.build()
    if not index.ready:
        print(f"index unavailable: {index._load_error}")
        return 1
    print(f"built in {time.perf_counter() - started:.1f}s, "
          f"{len(index.chunks)} chunks")
    chunks = index.chunks

    results = []
    for label, hybrid, rerank in MODES:
        with _configured(hybrid, rerank):
            result = _measure(index, chunks)
        result["label"] = label
        results.append(result)
        _report(result, width=max(len(q) for q, _, _ in PROBES) + 2)

    print()
    print("=" * 104)
    print("  summary")
    print("=" * 104)
    print(f"  {'mode':<16}{'hit@1':>8}{'top-5':>8}{'refusals ok':>13}{'mean ms':>10}")
    for result in results:
        rows, negs = result["rows"], result["negatives"]
        ok = sum(r["refused"] for r in negs)
        print(f"  {result['label']:<16}"
              f"{sum(r['hit1'] for r in rows)}/{len(rows):<6}"
              f"{sum(r['in_topk'] for r in rows)}/{len(rows):<6}"
              f"{ok}/{len(negs):<11}"
              f"{sum(r['ms'] for r in rows) / max(len(rows), 1):>8.0f}")

    print()
    print("  refusal gate — these must all be refused")
    for result in results:
        negs = result["negatives"]
        leaked = [r["question"] for r in negs if not r["refused"]]
        print(f"    {result['label']:<16} {sum(r['refused'] for r in negs)}/{len(negs)}"
              + (f"   LEAKED: {leaked}" if leaked else "   ok"))

    dense = {r["question"]: r for r in results[0]["rows"]}
    best = {r["question"]: r for r in results[-1]["rows"]}
    fixed = [q for q in dense if not dense[q]["hit1"] and best[q]["hit1"]]
    broke = [q for q in dense if dense[q]["hit1"] and not best[q]["hit1"]]
    print()
    print(f"  hybrid+rerank vs dense — newly correct: {len(fixed)}")
    for q in fixed:
        print(f"    + {q}   -> {best[q]['top']}")
    print(f"  hybrid+rerank vs dense — regressed: {len(broke)}")
    for q in broke:
        print(f"    - {q}   -> {best[q]['top']}  (dense had {dense[q]['top']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
