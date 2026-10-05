"""Hybrid retrieval: BM25, rank fusion, reranking, and the cosine gate.

Deliberately unit-level. `test_rag.py` exercises retrieval through the real
corpus and the real embedding model, which makes it an integration test that
takes tens of seconds — and which, by construction, cannot reproduce the defect
this feature exists to fix, because on the real corpus dense retrieval is already
mostly right.

So the central test here builds a *synthetic* corpus with a stubbed encoder whose
vectors are arranged so that dense retrieval is guaranteed to pick the wrong
section for a question containing an abbreviation. That turns "BM25 helps with
rare tokens" from a claim into a regression test: the same query, same index,
only the ranking stage differs.

Private names (`_Bm25`, `_rrf_fuse`) are imported on purpose. They are the units
under test, and pulling them in beats re-implementing BM25 inside the test — a
test that computes its own expected value from its own copy of the formula
verifies nothing but the copy.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core.config import settings
from app.services.rag_service import (
    Chunk,
    RagIndex,
    _Bm25,
    _rrf_fuse,
    compose_local_answer,
    lexical_text,
    tokenize,
)


# --------------------------------------------------------------------------- #
# BM25
# --------------------------------------------------------------------------- #

class TestBm25:
    """Score-shape properties, on token lists so the arithmetic is explicit."""

    def test_a_document_containing_the_term_scores_above_one_that_does_not(self):
        bm25 = _Bm25([["bi", "rads", "分级"], ["乳腺", "筛查"], ["乳腺", "症状"]])
        scores = bm25.scores(["bi", "rads"])
        assert scores[0] > 0
        assert scores[1] == 0 and scores[2] == 0

    def test_a_term_present_in_every_document_contributes_nothing(self):
        """The IDF clamp, which is load-bearing rather than cosmetic.

        Without it the Robertson/Sparck-Jones formula goes negative for a term
        that appears everywhere, and a question built from ubiquitous words would
        then score chunks *lacking* the term above chunks containing it. Clamped
        to zero, such terms drop out of the lexical ranking entirely — which is
        what `search` relies on when it treats a zero score as "not a candidate".
        """
        docs = [["乳腺", "筛查"], ["乳腺", "症状"], ["乳腺", "治疗"]]
        bm25 = _Bm25(docs)
        assert bm25.idf["乳腺"] == 0.0
        assert list(bm25.scores(["乳腺"])) == [0.0, 0.0, 0.0]

    def test_a_rare_term_gets_more_idf_than_a_common_one(self):
        docs = [["bi", "rads"], ["bi", "其他"], ["bi", "再一"], ["别的", "内容"]]
        bm25 = _Bm25(docs)
        assert bm25.idf["rads"] > bm25.idf["bi"]

    def test_repeated_occurrences_score_higher_but_saturate(self):
        """`k1` must damp term frequency, or one keyword-stuffed chunk wins."""
        docs = [
            ["目标"], ["目标"] * 3, ["目标"] * 10,
            ["填充一"], ["填充二"], ["填充三"], ["填充四"], ["填充五"],
        ]
        scores = _Bm25(docs).scores(["目标"])
        assert scores[0] < scores[1] < scores[2]
        # Saturation: ten occurrences must not be worth ten times one.
        assert scores[2] < 10 * scores[0]

    def test_the_shorter_document_wins_on_an_equal_occurrence(self):
        """`b` must normalise by length, or a long chunk wins on sheer volume."""
        docs = [
            ["目标", "短"], ["目标"] + ["填充"] * 40,
            ["填充一"], ["填充二"], ["填充三"], ["填充四"], ["填充五"], ["填充六"],
        ]
        scores = _Bm25(docs).scores(["目标"])
        assert scores[0] > scores[1]

    def test_an_unknown_term_scores_zero_everywhere(self):
        bm25 = _Bm25([["乳腺", "筛查"], ["心脏", "检查"]])
        assert list(bm25.scores(["完全没出现过"])) == [0.0, 0.0]

    def test_an_empty_query_scores_zero_everywhere(self):
        bm25 = _Bm25([["乳腺", "筛查"]])
        assert list(bm25.scores([])) == [0.0]

    def test_an_empty_corpus_is_survivable(self):
        """A missing knowledge directory must not turn into a division by zero."""
        assert list(_Bm25([]).scores(["任何"])) == []

    def test_a_two_document_corpus_has_no_usable_idf(self):
        """A documented boundary of the clamped formula, not a bug to fix.

        With two documents a term in one of them gives idf exactly 0, because
        `(n - df + 0.5) / (df + 0.5)` lands on 1. One document out of two is not
        evidence of rarity, so refusing to score it is defensible — and the
        knowledge base is 190+ chunks, far past this. If a corpus ever did
        shrink this far, `/health`'s `rag_retrieval.last_query.lexical` would
        read 0 rather than the retrieval quietly changing behaviour.
        """
        assert list(_Bm25([["目标"], ["别的"]]).scores(["目标"])) == [0.0, 0.0]


# --------------------------------------------------------------------------- #
# Rank fusion
# --------------------------------------------------------------------------- #

class TestRrfFusion:
    def test_the_arithmetic_is_the_published_reciprocal_rank(self):
        fused = _rrf_fuse([[7, 8]], k=60)
        assert fused[7] == pytest.approx(1 / 61)
        assert fused[8] == pytest.approx(1 / 62)

    def test_agreement_between_retrievers_beats_a_single_first_place(self):
        """The property RRF exists for: two modest rankings outrank one strong."""
        fused = _rrf_fuse([[5, 9], [5, 9]])
        assert fused[5] > fused[9]

    def test_a_document_only_one_retriever_found_still_scores(self):
        fused = _rrf_fuse([[1, 2], [1, 3]])
        assert set(fused) == {1, 2, 3}
        # First in both lists is worth twice first in only one of them.
        assert fused[1] == pytest.approx(2 / 61)
        assert fused[2] == pytest.approx(1 / 62)
        assert fused[3] == pytest.approx(1 / 62)
        assert fused[1] > fused[2]

    def test_no_rankings_produces_no_candidates(self):
        assert _rrf_fuse([]) == {}

    def test_a_larger_k_flattens_the_difference_between_adjacent_ranks(self):
        small_k = _rrf_fuse([[0, 1]], k=1)
        large_k = _rrf_fuse([[0, 1]], k=60)
        assert small_k[0] / small_k[1] > large_k[0] / large_k[1]


# --------------------------------------------------------------------------- #
# The synthetic index: does hybrid actually fix the dense failure?
# --------------------------------------------------------------------------- #

class _StubTokenizer:
    """One token per character — enough for the chunker, no model needed.

    Deliberately not `len(text) // 2` or any other compression: the chunker merges
    sections shorter than `rag_chunk_min_chars` *measured in tokens*, and an
    artificially cheap counter silently collapses the test fixture's two breast
    sections into one chunk. When that happened, the corpus fell to two documents,
    BM25's IDF clamped to zero for every term, and the hybrid test failed for a
    reason that had nothing to do with what it was testing.
    """

    def __call__(self, text: str, add_special_tokens: bool = False) -> dict:
        return {"input_ids": list(range(len(text)))}


class _StubEncoder:
    """A deterministic stand-in for the sentence encoder.

    Vectors are three-dimensional and chosen so that dense retrieval is *bound*
    to fail on the query the test uses: the question mentions "BI-RADS", but the
    query vector is identical to the symptom chunk's and orthogonal to the
    BI-RADS chunk's. That is the real failure mode in miniature — an abbreviation
    contributes almost no semantic mass, so the encoder answers with the prose
    that surrounds the question rather than the section that defines the term.
    """

    max_seq_length = 128
    tokenizer = _StubTokenizer()

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        if "bi-rads" in lowered:
            return [0.0, 0.0, 1.0]
        if "症状" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        # A single-text call is a query; multi-text calls are corpus encoding.
        if len(texts) == 1:
            return np.array([[1.0, 0.0, 0.0]], dtype="float32")
        return np.array([self._vector(t) for t in texts], dtype="float32")


# Section bodies are written long enough that the chunker keeps them as separate
# entries — a short one gets merged into its predecessor, which would silently
# remove the very chunk under test.
BREAST_DOC = """\
# 乳腺癌知识库

## 早期症状
乳腺癌早期常表现为无痛性肿块、乳头溢液或皮肤凹陷等症状，多数患者是在常规体检或自我检查时才被发现。也有部分患者没有任何自觉症状，仅在影像检查中偶然发现可疑病灶，因此定期参加筛查对早期发现有实际意义。

## BI-RADS 分级含义
BI-RADS 是乳腺影像报告与数据系统的缩写，用于统一描述影像所见并给出分级建议。其中 BI-RADS 4A 属于低度可疑恶性，临床上通常建议进一步穿刺活检明确诊断，并由专科医师结合影像与病理结果综合判断。
"""

HEART_DOC = """\
# 心脏病知识库

## 冠心病治疗手段
冠心病的治疗方式主要包括药物治疗、经皮冠状动脉介入治疗与外科搭桥手术三类，具体选择需要结合冠状动脉病变的范围与程度、患者的心功能状态以及合并症情况，由心内科医师评估后个体化决定并长期随访。
"""

DISCLAIMER_DOC = """\
# 免责声明与使用须知

## 使用限制
本系统提供的所有判定结果与科普内容仅供健康教育与研究参考，不构成任何形式的医学诊断或治疗建议，也不能替代执业医师的面对面诊疗。任何临床决策都应当由具备资质的医疗专业人员结合完整病史与检查资料作出。
"""

QUESTION = "BI-RADS 4A 是什么意思？"
EXPECTED_SECTION = "BI-RADS 分级含义"
WRONG_SECTION = "早期症状"


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A three-file knowledge base, with the model and reranker stubbed out."""
    (tmp_path / "breast_cancer_zh.md").write_text(BREAST_DOC, encoding="utf-8")
    (tmp_path / "heart_disease_zh.md").write_text(HEART_DOC, encoding="utf-8")
    (tmp_path / "disclaimer_zh.md").write_text(DISCLAIMER_DOC, encoding="utf-8")
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path)
    # Reranking off unless a test asks for it: it needs a 1 GB model, and the
    # question here is what *fusion* buys.
    monkeypatch.setattr(settings, "rag_rerank_enabled", False)
    monkeypatch.setattr(RagIndex, "_ensure_model", lambda self: _StubEncoder())
    return tmp_path


def _built(monkeypatch, hybrid: bool, rerank: bool = False) -> RagIndex:
    monkeypatch.setattr(settings, "rag_hybrid_enabled", hybrid)
    monkeypatch.setattr(settings, "rag_rerank_enabled", rerank)
    index = RagIndex()
    index.build()
    assert index.ready, index._load_error
    return index


class TestHybridRetrieval:
    def test_the_fixture_kept_both_breast_sections_separate(self, corpus, monkeypatch):
        """Guards the fixture itself.

        If the chunker merges the two breast sections, the corpus drops to three
        documents and every IDF clamps to zero — at which point the hybrid test
        would fail while looking like a ranking bug.
        """
        index = _built(monkeypatch, hybrid=False)
        titles = [c.title for c in index.chunks]
        assert EXPECTED_SECTION in titles and WRONG_SECTION in titles
        assert len(index.chunks) >= 4

    def test_dense_alone_picks_the_wrong_section(self, corpus, monkeypatch):
        """The defect, pinned. If this ever passes, the premise of the feature
        changed and the test below stops proving anything."""
        index = _built(monkeypatch, hybrid=False)
        hits = index.search(QUESTION, disease="breast")
        assert hits[0][0].title == WRONG_SECTION
        assert index.retrieval_info()["mode"] == "dense"

    def test_hybrid_finds_the_section_dense_missed(self, corpus, monkeypatch):
        """Same index, same query, same vectors — only the ranking differs."""
        index = _built(monkeypatch, hybrid=True)
        hits = index.search(QUESTION, disease="breast")
        assert hits[0][0].title == EXPECTED_SECTION
        assert index.retrieval_info()["mode"] == "hybrid"

    def test_bm25_indexes_the_same_text_the_lexical_gate_reads(self, corpus, monkeypatch):
        """One definition of "what a chunk says", used by both lexical signals.

        If these diverged, BM25 could rank a chunk first that the refusal gate
        then judged ungrounded — a contradiction the user would see as a refusal
        of an answer the system had just decided was the best match.
        """
        index = _built(monkeypatch, hybrid=True)
        target = next(c for c in index.chunks if c.title == EXPECTED_SECTION)
        text = lexical_text(target)
        assert "BI-RADS" in text
        # Space-stripping is part of the shared normalisation, so "BI-RADS 4A"
        # reaches BM25 as the single latin run "bi-rads4a". Pinned because it is
        # surprising: the token is "rads4a", not "rads" and "4a".
        assert {"bi", "rads4a"} <= set(tokenize(text))

    def test_scope_filter_runs_before_fusion(self, corpus, monkeypatch):
        """BM25 must not be able to smuggle in another disease module.

        The heart chunk is the only one that mentions 冠心病, so BM25 ranks it
        first; the scope filter has to remove it *before* fusion or a breast
        question would be answered with cardiology text.
        """
        index = _built(monkeypatch, hybrid=True)
        hits = index.search("冠心病治疗手段有哪些？", disease="breast")
        assert hits
        assert all(c.disease in ("breast", "general") for c, _ in hits)
        assert all("冠心病" not in c.title for c, _ in hits)

    def test_a_hit_carries_its_raw_cosine_not_its_ranking_score(self, corpus, monkeypatch):
        """The two scales must stay separate.

        The fusion winner here is the BI-RADS chunk, whose cosine against the
        query stub is exactly 0 — so if the returned float were the ranking score
        (or a fused blend) the refusal gate, calibrated in cosine space, would be
        reading a number in the wrong units.
        """
        index = _built(monkeypatch, hybrid=True)
        hits = index.search(QUESTION, disease="breast")
        assert hits[0][0].title == EXPECTED_SECTION
        assert hits[0][1] == pytest.approx(0.0)
        # ...while the runner-up is the one the encoder actually liked.
        assert any(score > 0.9 for _, score in hits[1:])

    def test_last_retrieval_reports_what_the_query_did(self, corpus, monkeypatch):
        index = _built(monkeypatch, hybrid=True)
        index.search(QUESTION, disease="breast")
        last = index.retrieval_info()["last_query"]
        assert last["mode"] == "hybrid"
        assert last["dense"] >= 1 and last["lexical"] >= 1
        assert last["reranked"] == 0


# --------------------------------------------------------------------------- #
# Reranking: wired in, and allowed to fail
# --------------------------------------------------------------------------- #

class _FakeReranker:
    """Scores by whether a passage contains a chosen marker.

    Deliberately content-based rather than position-based. Inverting the list it
    is handed would make the assertion depend on what fusion produced — an
    implementation detail — so the test would break for reasons unrelated to
    reranking. Scoring on content lets the test state the property it cares
    about: whatever the reranker prefers wins, regardless of what ranking it was
    given.
    """

    def __init__(self, prefer: str) -> None:
        self.prefer = prefer
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs):
        self.calls.append(list(pairs))
        return np.array(
            [2.0 if self.prefer in text else 1.0 for _, text in pairs],
            dtype="float32",
        )


class TestReranking:
    def test_the_reranker_decides_the_final_order(self, corpus, monkeypatch):
        """Proves the stage is consulted, not decorative.

        Fusion alone puts the BI-RADS section first; the fake reranker prefers the
        symptom section instead, so a top-1 of 早期症状 can only come from the
        rerank call actually happening. The fake is installed *before* the index is
        built, so the shipped load path — `_ensure_reranker` included — is the code
        under test rather than something the test steps around.
        """
        reranker = _FakeReranker(prefer=WRONG_SECTION)
        monkeypatch.setattr(
            "sentence_transformers.CrossEncoder", lambda *a, **k: reranker
        )
        index = _built(monkeypatch, hybrid=True, rerank=True)
        assert index.retrieval_info()["mode"] == "hybrid+rerank"

        hits = index.search(QUESTION, disease="breast")
        assert reranker.calls, "the reranker was never asked"
        assert hits[0][0].title == WRONG_SECTION
        assert index.retrieval_info()["last_query"]["reranked"] > 1

    def test_without_the_rerank_stage_the_order_stays_as_fusion_left_it(
        self, corpus, monkeypatch
    ):
        """The counterfactual for the test above: same query, reranking off."""
        index = _built(monkeypatch, hybrid=True, rerank=False)
        hits = index.search(QUESTION, disease="breast")
        assert hits[0][0].title == EXPECTED_SECTION

    def test_the_reranker_sees_the_heading_trail_as_well_as_the_body(
        self, corpus, monkeypatch
    ):
        """The heading is often where the term lives, so the cross-encoder must
        get it too — the same reason `embed_text` includes it."""
        reranker = _FakeReranker(prefer="never matches")
        monkeypatch.setattr(
            "sentence_transformers.CrossEncoder", lambda *a, **k: reranker
        )
        index = _built(monkeypatch, hybrid=True, rerank=True)
        index.search(QUESTION, disease="breast")
        first_query, _ = reranker.calls[0][0]
        # `CrossEncoder.predict` takes (query, passage) pairs — that order is a
        # contract with the library, not a local convention.
        assert first_query == QUESTION
        assert any(
            "BI-RADS 分级含义" in text for _, text in reranker.calls[0]
        ), "the cross-encoder must be given the breadcrumb, not just the body"

    def test_a_missing_model_degrades_the_ranking_instead_of_the_feature(
        self, corpus, monkeypatch
    ):
        """The property that keeps a demo from going dark.

        A ~1 GB download can fail on an offline host; retrieval must keep working
        on the fused ranking rather than raise, and it must stop retrying — a
        per-query load attempt would add a failed network call to every question.
        """
        attempts: list[int] = []

        def unavailable(*args, **kwargs):
            attempts.append(1)
            raise OSError("model is not reachable")

        monkeypatch.setattr("sentence_transformers.CrossEncoder", unavailable)
        index = _built(monkeypatch, hybrid=True, rerank=True)

        info = index.retrieval_info()
        assert info["rerank_unavailable"] is True
        assert info["rerank_model"] is None
        assert info["mode"] == "hybrid"

        hits = index.search(QUESTION, disease="breast")
        assert hits, "retrieval must survive an unusable reranker"
        assert hits[0][0].title == EXPECTED_SECTION

        index.search(QUESTION, disease="breast")
        assert len(attempts) == 1, "the failure must be remembered, not retried"

    def test_disabling_the_reranker_does_not_even_try_to_load_it(
        self, corpus, monkeypatch
    ):
        attempts: list[int] = []

        def should_not_run(*args, **kwargs):
            attempts.append(1)
            raise AssertionError("the reranker was loaded while disabled")

        monkeypatch.setattr("sentence_transformers.CrossEncoder", should_not_run)
        index = _built(monkeypatch, hybrid=True, rerank=False)
        info = index.retrieval_info()
        assert info["mode"] == "hybrid"
        assert info["rerank_unavailable"] is False
        assert not attempts

    def test_a_query_time_failure_falls_back_for_good(self, corpus, monkeypatch):
        """A reranker that loads but then throws is just as survivable."""

        class Exploding:
            def predict(self, pairs):
                raise RuntimeError("inference blew up")

        monkeypatch.setattr(
            "sentence_transformers.CrossEncoder", lambda *a, **k: Exploding()
        )
        index = _built(monkeypatch, hybrid=True, rerank=True)
        # Loading succeeded, so the index believed reranking was available.
        assert index.retrieval_info()["mode"] == "hybrid+rerank"

        hits = index.search(QUESTION, disease="breast")
        assert hits, "a failing reranker must not take retrieval down with it"
        assert hits[0][0].title == EXPECTED_SECTION
        assert index.retrieval_info()["rerank_unavailable"] is True
        assert index.retrieval_info()["mode"] == "hybrid"


# --------------------------------------------------------------------------- #
# The refusal gate still reads a cosine
# --------------------------------------------------------------------------- #

def _chunk(title: str, text: str, index: int = 0, path: tuple[str, ...] | None = None):
    return Chunk(
        index=index, source="breast_cancer_zh", title=title, text=text,
        disease="breast", path=path or ("乳腺癌知识库", title), part=1, parts=1,
    )


class TestRefusalGateReadsCosine:
    """The one decision that made hybrid retrieval safe to ship.

    `search` orders by the fused score but reports each passage's cosine. The gate
    takes the best cosine among the hits rather than `hits[0]`'s, because a
    lexical promotion legitimately puts a lower-cosine passage first.
    """

    def test_a_lexical_promotion_does_not_cause_a_false_refusal(self):
        question = "乳腺癌的筛查方法有哪些"
        relevant = _chunk(
            "乳腺癌预防与筛查",
            "乳腺癌筛查方法包括乳腺超声与钼靶检查，建议适龄女性定期参加。",
        )
        # Lexically on-topic (so BM25 would rank it first) but semantically
        # distant — exactly the shape a lexical promotion produces.
        promoted = _chunk(
            "筛查相关条目", "筛查方法方法方法筛查筛查方法有哪些方法。", index=1,
        )
        hits = [(promoted, 0.05), (relevant, 0.82)]
        _, refused = compose_local_answer(question, hits, disease="breast")
        assert refused is False, (
            "reading hits[0]'s cosine here would refuse a well-grounded question "
            "merely because the lexical retriever did its job"
        )

    def test_a_genuinely_weak_retrieval_is_still_refused(self):
        """The gate must not have been loosened into uselessness."""
        question = "乳腺癌的筛查方法有哪些"
        hits = [
            (_chunk("无关条目", "今天天气不错适合出门散步。", index=0), 0.12),
            (_chunk("另一条目", "本节讨论其他话题。", index=1), 0.20),
        ]
        _, refused = compose_local_answer(question, hits, disease="breast")
        assert refused is True


class TestLexicalGateReadsTheTopHitOnly:
    """The asymmetry between the two gates, pinned before someone "tidies" it.

    `top_score` is the best cosine **among the hits**. `coverage` is measured
    against `hits[0]` alone. That looks like an inconsistency worth unifying, and
    unifying it would quietly turn honest refusals into confident wrong answers.

    Measured on the real corpus, for the four questions dense retrieval gets
    wrong: max cosine 0.43–0.61, so the semantic gate never fires; coverage
    against `hits[0]` exactly 0.000, so the lexical gate does. A best-over-hits
    coverage would have been 0.125–0.333 — every one of them above the 0.12
    threshold — and all four would have been *answered from the wrong section*:
    a question about Youden's index cited to 概率校准与布里尔分数.

    So the refusal is not the gate misfiring. It is the gate reporting the truth
    about the passage it was handed, which is exactly what a gate is for.
    """

    def test_coverage_is_measured_against_the_top_hit_not_the_best_hit(self):
        from app.services.rag_service import _token_coverage

        question = "Youden 指数是怎么用的？"
        # Ranked first on cosine, yet shares no content word with the question.
        top = _chunk(
            "概率校准与布里尔分数", "本节讨论概率校准曲线与布里尔分数的计算方式。"
        )
        # What the reader actually wanted: lexically on point, ranked second.
        wanted = _chunk(
            "判定阈值的作用", "Youden 指数常常用来选择判定阈值。", index=1
        )
        hits = [(top, 0.44), (wanted, 0.20)]

        assert _token_coverage(question, top) == 0.0
        assert _token_coverage(question, wanted) >= settings.rag_min_token_coverage

        _, refused = compose_local_answer(question, hits, disease="breast")
        assert refused is True, (
            "if coverage took the best hit, this would be answered from "
            f"{top.title!r} — the lower-cosine chunk is the one that is on topic"
        )
