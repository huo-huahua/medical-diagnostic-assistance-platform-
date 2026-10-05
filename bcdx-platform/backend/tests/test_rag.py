"""RAG: retrieval, scope isolation, refusal gating, citation assembly.

The behavioural guarantees this file pins down:

* a question outside the active disease module is **refused with a tailored
  message** rather than answered from a neighbouring module's text;
* retrieval never silently returns nothing because of over-fetching;
* citations are one entry per *section*, not one per retrieved fragment;
* the assistant endpoint requires authentication.
"""

from __future__ import annotations

import pytest

from app.services.rag_service import (
    GREETING_REPLY,
    REFUSAL_TEXT,
    Chunk,
    compose_local_answer,
    group_passages,
    is_greeting,
    tokenize,
)

pytestmark = pytest.mark.integration


def _chunk(index: int, path: tuple[str, ...], part: int, parts: int,
           text: str, source: str = "breast_cancer_zh") -> Chunk:
    return Chunk(index=index, source=source, title=path[-1], text=text,
                 disease="breast", path=path, part=part, parts=parts)


# --------------------------------------------------------------------------- #
# Tokenizer
# --------------------------------------------------------------------------- #

class TestTokenizer:
    def test_chinese_becomes_bigrams(self):
        assert "乳腺" in tokenize("乳腺癌")

    def test_latin_becomes_words(self):
        assert "bi" in tokenize("BI-RADS 分级")

    def test_punctuation_and_case_are_folded(self):
        assert tokenize("乳腺癌，如何筛查？") == tokenize("乳腺癌如何筛查")

    def test_empty_text_yields_no_tokens(self):
        assert tokenize("") == []


# --------------------------------------------------------------------------- #
# Passage grouping — small-to-big retrieval
# --------------------------------------------------------------------------- #

class TestGroupPassages:
    def test_sibling_parts_merge_into_one_passage(self):
        hits = [
            (_chunk(0, ("知识库", "乳腺超声"), 1, 2, "第一段"), 0.71),
            (_chunk(1, ("知识库", "乳腺超声"), 2, 2, "第二段"), 0.65),
        ]
        passages = group_passages(hits)
        assert len(passages) == 1
        assert passages[0].parts == 2
        # Parts are reassembled in reading order, not score order.
        assert passages[0].text.index("第一段") < passages[0].text.index("第二段")
        # The passage keeps the best score of its members.
        assert passages[0].score == pytest.approx(0.71)

    def test_distinct_sections_stay_separate(self):
        hits = [
            (_chunk(0, ("知识库", "甲"), 1, 1, "A"), 0.9),
            (_chunk(1, ("知识库", "乙"), 1, 1, "B"), 0.8),
        ]
        assert [p.title for p in group_passages(hits)] == ["知识库 > 甲", "知识库 > 乙"]

    def test_ranking_follows_the_best_hit_of_each_section(self):
        """Grouping must not reshuffle the retrieval ranking."""
        hits = [
            (_chunk(0, ("知识库", "甲"), 1, 3, "A1"), 0.55),
            (_chunk(1, ("知识库", "乙"), 1, 1, "B"), 0.80),
            (_chunk(2, ("知识库", "甲"), 2, 3, "A2"), 0.62),
        ]
        titles = [p.title for p in group_passages(hits)]
        assert titles == ["知识库 > 甲", "知识库 > 乙"]

    def test_split_sections_are_labelled_as_merged(self):
        hits = [
            (_chunk(0, ("知识库", "甲"), 1, 2, "A1"), 0.5),
            (_chunk(1, ("知识库", "甲"), 2, 2, "A2"), 0.5),
        ]
        assert "合并 2 段" in group_passages(hits)[0].citation_title

    def test_unsplit_sections_are_not_labelled(self):
        hits = [(_chunk(0, ("知识库", "甲"), 1, 1, "A"), 0.5)]
        assert group_passages(hits)[0].citation_title == "知识库 > 甲"

    def test_empty_input_is_safe(self):
        assert group_passages([]) == []


# --------------------------------------------------------------------------- #
# Refusal gating — the safety property
# --------------------------------------------------------------------------- #

class TestRefusalGating:
    def test_no_hits_refuses_instead_of_guessing(self):
        answer, refused = compose_local_answer("乳腺癌怎么筛查", [], disease="breast")
        assert refused is True
        assert answer == REFUSAL_TEXT

    def test_cross_disease_question_gets_a_tailored_refusal(self):
        """Out-of-scope questions must be told *why*, not given a generic shrug."""
        strong = (_chunk(0, ("知识库", "乳腺超声"), 1, 1,
                         "乳腺超声检查用于评估乳腺结节。"), 0.95)
        answer, refused = compose_local_answer(
            "冠心病应该如何治疗？", [strong], disease="breast"
        )
        assert refused is True
        assert "冠心病" in answer
        assert "超出" in answer and "范围" in answer
        assert "切换" in answer
        # It must not be the generic refusal — that would hide the real reason.
        assert answer != REFUSAL_TEXT

    def test_weak_semantic_match_is_refused(self):
        weak = (_chunk(0, ("知识库", "乳腺超声"), 1, 1,
                       "乳腺超声检查用于评估乳腺结节。"), 0.01)
        _, refused = compose_local_answer(
            "乳腺癌的筛查建议是什么", [weak], disease="breast"
        )
        assert refused is True

    def test_weak_lexical_overlap_is_refused(self):
        """High similarity but no shared vocabulary must still refuse.

        A small corpus makes unrelated medical questions look similar to each
        other, so the lexical gate is the second, independent check.
        """
        lexical_dud = (_chunk(0, ("知识库", "无关条目"), 1, 1,
                              "今天天气很好适合出门散步散步。"), 0.99)
        _, refused = compose_local_answer(
            "乳腺癌的化疗方案有哪些", [lexical_dud], disease="breast"
        )
        assert refused is True

    def test_grounded_question_is_answered_with_citations(self):
        chunk = _chunk(
            0, ("知识库", "乳腺癌筛查"), 1, 1,
            "乳腺癌筛查主要包括乳腺超声与钼靶检查，推荐适龄女性定期筛查。",
        )
        answer, refused = compose_local_answer(
            "乳腺癌筛查包括哪些检查", [(chunk, 0.82)], disease="breast"
        )
        assert refused is False
        assert "[^c1]" in answer
        # Plain text only: the UI renders pre-wrapped text, so markdown would
        # be shown verbatim.
        assert "**" not in answer
        assert "以上内容整理自本地知识库" in answer

    def test_greeting_is_answered_without_a_refusal(self):
        """A greeting is not an unanswerable question.

        Meeting "你好" with "没有检索到相关内容，请前往医院就诊" reads as a
        failure and tells the user nothing.
        """
        answer, refused = compose_local_answer("你好", [], disease="breast")
        assert refused is False
        assert "[^c1]" not in answer
        assert "【" not in answer
        assert "医学科普助手" in answer

    @pytest.mark.parametrize("text", ["你好", "您好！", "hi", "Hello.", "在吗？"])
    def test_greeting_variants_are_recognised(self, text):
        answer, refused = compose_local_answer(text, [], disease="breast")
        assert refused is False
        assert answer == GREETING_REPLY

    def test_a_greeting_plus_a_question_is_not_treated_as_a_greeting(self):
        """Anchored on purpose: "你好，乳腺癌怎么筛查" is a real question."""
        chunk = _chunk(
            0, ("知识库", "乳腺癌筛查"), 1, 1,
            "乳腺癌筛查主要包括乳腺超声与钼靶检查，推荐适龄女性定期筛查。",
        )
        answer, refused = compose_local_answer(
            "你好，乳腺癌筛查包括哪些检查", [(chunk, 0.82)], disease="breast"
        )
        assert refused is False
        assert answer != GREETING_REPLY
        assert "[^c1]" in answer

    @pytest.mark.parametrize("text,expected", [
        ("你好", True), ("您好！", True), ("在吗？", True), ("hi", True),
        ("", False), ("你好吗，我最近乳房有肿块", False), ("乳腺癌怎么筛查", False),
    ])
    def test_is_greeting(self, text, expected):
        assert is_greeting(text) is expected


# --------------------------------------------------------------------------- #
# Retrieval scope (needs the real index)
# --------------------------------------------------------------------------- #

class TestRetrievalScope:
    """Regression for the over-fetch starvation bug.

    `fetch_k` used to be capped at 20. Because every medical chunk is lexically
    similar to any medical question, a cross-disease question could fill all 20
    slots with the *other* module's chunks; the disease filter then removed
    every one of them, `search()` returned `[]`, and the tailored
    out-of-scope answer became unreachable — the user got a generic refusal
    instead of being told to switch modules.
    """

    def test_scoped_search_never_returns_another_disease_modules_chunks(self):
        """*Another disease* is the thing that must never leak in.

        Careful with the assertion here. An earlier version asserted
        `c.disease == "breast"` for every hit, which reads like the same
        guarantee but is stricter than the design: `general` chunks — the
        disclaimer and the system notes — are eligible for every query on
        purpose, as `Chunk.disease` and the scope filter both say. That version
        passed only because no general chunk had ever reached the top 5 for this
        query, and it broke the moment BM25 and the reranker changed the ranking.
        A test that passes by luck is worse than no test, so it now asserts the
        property that is actually intended.
        """
        from app.core.config import settings
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        hits = index.search("冠心病应该如何治疗？", top_k=settings.rag_top_k,
                            disease="breast")
        assert hits, "scoped search starved itself and returned nothing"
        assert all(c.disease in ("breast", "general") for c, _ in hits)
        assert all(c.disease != "heart" for c, _ in hits), (
            "cardiology text reached a breast-scoped query"
        )

    def test_cross_disease_question_reaches_the_tailored_refusal(self):
        from app.core.config import settings
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        hits = index.search("冠心病应该如何治疗？", top_k=settings.rag_top_k,
                            disease="breast")
        answer, refused = compose_local_answer(
            "冠心病应该如何治疗？", hits, disease="breast"
        )
        assert refused is True
        assert "超出" in answer, "fell back to the generic refusal"

    def test_unscoped_search_can_reach_other_modules(self):
        from app.core.config import settings
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        hits = index.search("心电图能查出什么问题？", top_k=settings.rag_top_k,
                            disease=None)
        assert hits
        assert any(c.disease == "heart" for c, _ in hits)

    def test_every_indexed_chunk_has_provenance(self):
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        assert index.chunks
        for chunk in index.chunks:
            assert chunk.source, "a chunk without a source cannot be cited"
            assert chunk.citation_title


# --------------------------------------------------------------------------- #
# Retrieval must be observable
# --------------------------------------------------------------------------- #

class TestRetrievalIsObservable:
    """`/health` has to say what retrieval is *actually* doing.

    "We added hybrid retrieval and a reranker" cannot be checked by reading the
    diff — and a silent degradation to dense-only (a reranker model that could not
    be fetched on an offline host) would otherwise look exactly like the feature
    working. These assertions are what make the difference visible.

    `mode` is deliberately checked against the whole legitimate set rather than
    pinned to `hybrid+rerank`: whether the cross-encoder is present depends on the
    machine, and a test that demanded it would fail in CI for the honest reason
    that CI has no reason to download a 1 GB model.
    """

    def test_health_reports_the_retrieval_stack(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        info = res.json()["rag_retrieval"]
        assert info["mode"] in {"dense", "hybrid", "hybrid+rerank"}
        assert info["bm25"] == "okapi"
        assert info["rrf_k"] > 0
        assert info["candidates"] >= 5
        assert isinstance(info["rerank_unavailable"], bool)

    def test_a_query_updates_the_reported_counts(self, client, auth_headers):
        """A per-query record, so a reader can see the two retrievers disagree.

        Retrieval that returns the right passage is not by itself evidence that
        fusion did anything — `dense` and `lexical` both being non-zero is, and it
        is only visible here.
        """
        res = client.post(
            "/api/v1/rag/ask",
            json={"question": "乳腺癌的早期症状有哪些？", "disease": "breast",
                  "use_llm": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text

        info = client.get("/health").json()["rag_retrieval"]
        last = info["last_query"]
        assert last is not None, "a search must publish what it did"
        assert last["mode"] in {"hybrid", "hybrid+rerank"}
        assert last["dense"] >= 1
        assert last["lexical"] >= 1, "BM25 found no candidate for an in-corpus question"
        assert last["fused"] >= 1

    def test_limits_expose_the_retrieval_switches(self, client):
        """So the UI can tell a reader which stack is live.

        `rag_rerank` is asserted as False on purpose: reranking is off by
        default, and the reason is in `core/config.py` — it cost ~2.2s per query
        and improved no top-1 result. Pinning the default here means flipping it
        has to be a deliberate act with an updated measurement, not a quiet
        config edit.
        """
        data = client.get("/api/v1/meta/limits").json()["data"]
        assert data["rag_hybrid"] is True
        assert data["rag_rerank"] is False


# --------------------------------------------------------------------------- #
# Hybrid retrieval, measured on the real corpus
# --------------------------------------------------------------------------- #

#: Questions that dense-only retrieval gets wrong on this knowledge base, with
#: the section a reader would want. Taken from `_tools/eval_retrieval.py`, which
#: derives every expectation from the corpus instead of from memory.
#:
#: All four end in a refusal rather than merely a worse answer, which is why they
#: are worth a regression test: a wrong-but-related answer is a quality problem,
#: "the knowledge base has nothing" on a question it plainly answers is a broken
#: product.
#:
#: The gate that fires is the *lexical* one, not the cosine one. Measured on this
#: corpus: these four score 0.43-0.61 on the best cosine among their hits, all
#: comfortably clear of `rag_min_similarity` (0.30), while `coverage` against the
#: section dense ranked first is exactly 0.000 — because dense answered a question
#: about "Youden" with 概率校准与布里尔分数. The gate was therefore doing its job:
#: refusing to answer from a passage that shares no content word with the
#: question. What was broken was the ranking; the refusal was honest.
#:
#: BM25 ranks the section that actually contains the term first, so the lexical
#: gate is satisfied as well — which is why the assertions below pin both halves.
HYBRID_RECOVERS: list[tuple[str, str, str]] = [
    ("Youden 指数是怎么用的？", "breast", "判定阈值的作用"),
    ("约登指数是什么意思？", "breast", "判定阈值的作用"),
    ("数据泄漏为什么会让评估失真？", "breast", "数据泄漏与评估可信度"),
    ("房颤是怎么回事？", "heart", "心律失常基本概念"),
]


class TestHybridRetrievalOnTheRealCorpus:
    @pytest.mark.parametrize("question,disease,expected", HYBRID_RECOVERS)
    def test_the_expected_section_ranks_first(self, question, disease, expected):
        from app.core.config import settings
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        hits = index.search(question, top_k=settings.rag_top_k, disease=disease)
        assert hits
        assert hits[0][0].title == expected, (
            f"{question!r} ranked {hits[0][0].title!r} first"
        )

    @pytest.mark.parametrize("question,disease,expected", HYBRID_RECOVERS)
    def test_the_question_is_no_longer_refused(self, question, disease, expected):
        """The user-visible half of the fix, and the reason BM25 is on by default.

        A wrong-but-related answer is a quality problem; a refusal on a question
        the corpus answers is a broken product.
        """
        from app.core.config import settings
        from app.services.rag_service import compose_local_answer, get_index

        index = get_index()
        if not index.ready:
            index.build()

        hits = index.search(question, top_k=settings.rag_top_k, disease=disease)
        _, refused = compose_local_answer(question, hits, disease=disease)
        assert refused is False

    def test_the_hybrid_stack_is_the_one_that_is_live(self):
        """Guards the other three tests: they only mean something in hybrid mode."""
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        info = index.retrieval_info()
        assert info["bm25"] == "okapi"
        assert "hybrid" in info["mode"]


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #

class TestRagApi:
    def test_sources_endpoint_is_public(self, client):
        res = client.get("/api/v1/rag/sources")
        assert res.status_code == 200
        sources = res.json()["data"]
        assert {s["source"] for s in sources} >= {
            "breast_cancer_zh", "heart_disease_zh"
        }
        assert sum(s["count"] for s in sources) > 50

    def test_ask_requires_authentication(self, client):
        res = client.post("/api/v1/rag/ask", json={"question": "乳腺癌怎么筛查"})
        assert res.status_code == 401

    def test_ask_returns_a_grounded_answer(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/ask",
            json={"question": "乳腺癌的筛查方法有哪些？", "disease": "breast",
                  "use_llm": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["answer"]
        assert isinstance(data["refused"], bool)
        assert data["source"] in {"knowledge_base", "refusal", "llm_enhanced"}
        # No key is configured in the test environment, so nothing may be billed.
        assert data["llm_used"] is False
        for c in data["citations"]:
            assert c["title"] and c["source"]

    def test_ask_refuses_a_cross_disease_question(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/ask",
            json={"question": "冠心病应该如何治疗？", "disease": "breast",
                  "use_llm": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["refused"] is True
        assert data["source"] == "refusal"
        assert "超出" in data["answer"]

    def test_a_greeting_is_labelled_as_such(self, client, auth_headers):
        """Not `knowledge_base`: a greeting comes from neither the KB nor a
        refusal, and a caller branching on `source` must not be misled."""
        res = client.post(
            "/api/v1/rag/ask",
            json={"question": "你好", "disease": "breast", "use_llm": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["source"] == "greeting"
        assert data["refused"] is False
        assert data["citations"] == []

    def test_usage_reports_the_llm_as_disabled(self, client, auth_headers):
        res = client.get("/api/v1/rag/usage", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["available"] is False
        assert data["api_calls_this_process"] == 0

    def test_conversations_are_created_and_listed(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/ask",
            json={"question": "乳腺癌早期有什么表现？", "disease": "breast",
                  "use_llm": False},
            headers=auth_headers,
        )
        assert res.status_code == 200
        convo_id = res.json()["data"]["conversation_id"]

        listed = client.get("/api/v1/rag/conversations", headers=auth_headers)
        assert listed.status_code == 200
        assert any(c["id"] == convo_id for c in listed.json()["data"])

        detail = client.get(f"/api/v1/rag/conversations/{convo_id}",
                            headers=auth_headers)
        assert detail.status_code == 200
        messages = detail.json()["data"]["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
