"""The three-path Q&A comparison.

What this feature has to guarantee:

* the three paths are always described consistently, so the table is comparable;
* a path that cannot run is marked `skipped` rather than `failed` — an
  unconfigured deployment is not a broken one;
* when no external model is configured, the comparison still works, costs
  exactly zero, and says so;
* every comparison is persisted and auditable, and is private to its owner.

The metric caveats (`lexical_overlap` is lexical, `risk_phrases` is a keyword
screen) are asserted too, so a later reader cannot mistake them for correctness
or safety measures.
"""

from __future__ import annotations

import pytest

from app.services.qa_compare import (
    ALL_PATHS,
    PATH_LABELS,
    _cost_cny,
    lexical_overlap,
    risk_phrases,
)

pytestmark = pytest.mark.integration

QUESTION = "乳腺癌的筛查方法有哪些？"


# --------------------------------------------------------------------------- #
# Pure metrics — no app, no index
# --------------------------------------------------------------------------- #

class TestPathCatalogue:
    def test_all_paths_are_described(self):
        for key in ALL_PATHS:
            meta = PATH_LABELS[key]
            assert meta["label"] and meta["short"] and meta["description"]

    def test_exactly_one_path_is_local_and_free(self):
        free = [k for k, m in PATH_LABELS.items() if not m["external_call"]]
        assert free == ["local_rag"]

    def test_retrieval_usage_is_consistent(self):
        assert PATH_LABELS["local_rag"]["uses_retrieval"] is True
        assert PATH_LABELS["llm_direct"]["uses_retrieval"] is False
        assert PATH_LABELS["llm_rag"]["uses_retrieval"] is True

    def test_the_direct_path_is_the_hallucination_baseline(self):
        """`llm_direct` must never gain retrieval — it is the control condition."""
        assert PATH_LABELS["llm_direct"]["uses_retrieval"] is False


class TestLexicalOverlap:
    def test_answer_drawn_from_the_context_scores_high(self):
        context = "乳腺癌筛查主要包括乳腺超声与钼靶检查，推荐适龄女性定期筛查。"
        assert lexical_overlap(context, context) == pytest.approx(1.0)

    def test_unrelated_answer_scores_low(self):
        context = "乳腺癌筛查主要包括乳腺超声与钼靶检查。"
        assert lexical_overlap("今天天气晴朗适合出门散步", context) < 0.2

    def test_paraphrase_scores_between_the_two_extremes(self):
        context = "乳腺癌筛查主要包括乳腺超声与钼靶检查。"
        copied = lexical_overlap(context, context)
        paraphrased = lexical_overlap("乳腺超声与钼靶是常用的乳腺癌筛查手段。", context)
        unrelated = lexical_overlap("今天天气晴朗适合出门散步", context)
        assert unrelated < paraphrased < copied

    def test_empty_answer_scores_zero(self):
        assert lexical_overlap("", "任意上下文") == 0.0

    def test_score_is_bounded(self):
        assert 0.0 <= lexical_overlap("乳腺癌", "乳腺癌筛查") <= 1.0


class TestRiskPhrases:
    @pytest.mark.parametrize("text", ["这个病一定能治好", "保证痊愈", "绝对安全",
                                      "100%有效", "无需就医", "肯定没问题"])
    def test_absolutist_wording_is_flagged(self, text):
        assert risk_phrases(text), f"{text!r} should have been flagged"

    def test_full_width_digits_are_still_caught(self):
        """NFKC folds １００％ to 100% before matching."""
        assert "100%" in risk_phrases("有效率１００％")

    def test_hedged_wording_is_not_flagged(self):
        assert risk_phrases("部分患者可能从中获益，具体请遵医嘱") == []

    def test_a_clean_answer_scores_no_phrases(self):
        assert risk_phrases("医生会结合影像与病理结果综合判断。") == []


class TestCostEstimate:
    def test_cost_is_the_sum_of_both_token_prices(self):
        # 1000 prompt tokens @ 0.002 + 1000 completion @ 0.008
        assert _cost_cny(1000, 1000) == pytest.approx(0.01)

    def test_no_tokens_costs_nothing(self):
        assert _cost_cny(0, 0) == 0.0

    def test_prompt_tokens_are_cheaper_than_completion(self):
        assert _cost_cny(1000, 0) < _cost_cny(0, 1000)


# --------------------------------------------------------------------------- #
# The orchestrator, without HTTP
# --------------------------------------------------------------------------- #

class TestCompareService:
    def test_runs_every_path_by_default(self):
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast")
        assert [p["key"] for p in outcome["paths"]] == list(ALL_PATHS)

    def test_local_path_is_always_ok(self):
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast")
        local = next(p for p in outcome["paths"] if p["key"] == "local_rag")
        assert local["status"] == "ok"
        assert local["answer"]
        assert local["external_call"] is False
        assert local["cost_cny"] == 0.0
        assert local["llm_used"] is False

    def test_unconfigured_external_paths_are_skipped_not_failed(self):
        """An unconfigured deployment is not a broken one."""
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast")
        external = [p for p in outcome["paths"] if p["external_call"]]
        assert external
        for path in external:
            assert path["status"] == "skipped"
            assert path["answer"] is None
            assert "未启用外部模型" in path["note"]

    def test_summary_reports_zero_cost_when_nothing_is_configured(self):
        from app.services.qa_compare import compare

        summary = compare(QUESTION, "breast")["summary"]
        assert summary["llm_available"] is False
        assert summary["external_calls"] == 0
        assert summary["cache_hits"] == 0
        assert summary["cost_cny"] == 0.0
        assert summary["prompt_tokens"] == 0

    def test_grounding_is_attributed_per_path(self):
        from app.services.qa_compare import compare

        summary = compare(QUESTION, "breast")["summary"]
        assert "local_rag" in summary["grounded_paths"]
        # Nothing else produced an answer, so nothing else may claim grounding.
        assert "llm_direct" not in summary["grounded_paths"]
        assert summary["ungrounded_paths"] == []

    def test_retrieval_is_shared_and_reported_once(self):
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast")
        assert outcome["hit_count"] >= outcome["passage_count"] > 0
        assert outcome["citations"]
        assert outcome["top_score"] > 0

    def test_an_out_of_scope_question_is_refused_everywhere(self):
        from app.services.qa_compare import compare

        outcome = compare("冠心病应该如何治疗？", "breast")
        assert outcome["refused"] is True
        local = next(p for p in outcome["paths"] if p["key"] == "local_rag")
        assert local["refused"] is True
        assert "超出" in local["answer"]

    def test_only_the_requested_paths_run(self):
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast", paths=["local_rag"])
        assert [p["key"] for p in outcome["paths"]] == ["local_rag"]

    def test_unknown_path_keys_fall_back_to_everything(self):
        from app.services.qa_compare import compare

        outcome = compare(QUESTION, "breast", paths=["nonsense"])
        assert [p["key"] for p in outcome["paths"]] == list(ALL_PATHS)

    def test_question_is_truncated_to_the_configured_cap(self, monkeypatch):
        from app.core.config import settings
        from app.services.qa_compare import compare

        monkeypatch.setattr(settings, "qa_compare_max_question_chars", 12)
        outcome = compare("乳腺癌的筛查方法有哪些？" * 20, "breast")
        assert outcome["truncated"] is True
        assert len(outcome["question"]) == 12

    def test_local_only_switch_drops_the_external_paths(self, monkeypatch):
        from app.core.config import settings
        from app.services.qa_compare import compare

        monkeypatch.setattr(settings, "qa_compare_allow_llm", False)
        outcome = compare(QUESTION, "breast")
        assert [p["key"] for p in outcome["paths"]] == ["local_rag"]

    def test_a_greeting_is_not_reported_as_ungrounded(self):
        """A greeting has no citations by design, which is not the same as an
        answer that makes claims without provenance. Flagging it as ungrounded
        would mark the safest possible reply as the riskiest."""
        from app.services.qa_compare import compare

        summary = compare("你好", "breast")["summary"]
        assert summary["ungrounded_paths"] == []
        assert summary["grounded_paths"] == []

        local = next(p for p in compare("你好", "breast")["paths"]
                     if p["key"] == "local_rag")
        assert local["status"] == "ok"
        assert local["citation_count"] == 0
        assert "问候" in local["note"]

    def test_metrics_are_present_on_every_path(self):
        """The table applies the same rows to every column, so no path may omit
        a metric."""
        from app.services.qa_compare import compare

        required = {
            "answer_chars", "lexical_overlap", "risk_phrases", "citation_count",
            "latency_ms", "cost_cny", "prompt_tokens", "completion_tokens",
            "llm_used", "cache_hit", "status", "note",
        }
        for path in compare(QUESTION, "breast")["paths"]:
            assert required <= set(path), f"{path['key']} is missing metrics"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #

class TestCompareApi:
    def test_requires_authentication(self, client):
        assert client.post("/api/v1/rag/compare",
                           json={"question": QUESTION}).status_code == 401

    def test_compare_returns_three_columns(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/compare",
            json={"question": QUESTION, "disease": "breast", "persist": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert [p["key"] for p in data["paths"]] == list(ALL_PATHS)
        assert data["summary"]["cost_cny"] == 0.0
        assert data["comparison_id"] is None

    def test_comparison_is_persisted_and_retrievable(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/compare",
            json={"question": QUESTION, "disease": "breast", "persist": True},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        comparison_id = res.json()["data"]["comparison_id"]
        assert comparison_id is not None

        listed = client.get("/api/v1/rag/comparisons", headers=auth_headers)
        assert listed.status_code == 200
        assert any(c["id"] == comparison_id for c in listed.json()["data"])

        detail = client.get(f"/api/v1/rag/comparisons/{comparison_id}",
                            headers=auth_headers)
        assert detail.status_code == 200
        row = detail.json()["data"]
        assert row["question"] == QUESTION
        assert row["answer_local"], "the local answer must survive persistence"
        assert row["cost_cny"] == 0.0
        assert isinstance(row["path_metrics"], list)

    def test_a_comparison_can_be_deleted(self, client, auth_headers):
        created = client.post(
            "/api/v1/rag/compare",
            json={"question": QUESTION, "disease": "breast", "persist": True},
            headers=auth_headers,
        ).json()["data"]["comparison_id"]

        deleted = client.delete(f"/api/v1/rag/comparisons/{created}",
                                headers=auth_headers)
        assert deleted.status_code == 200
        assert client.get(f"/api/v1/rag/comparisons/{created}",
                          headers=auth_headers).status_code == 403

    def test_history_and_detail_require_authentication(self, client):
        assert client.get("/api/v1/rag/comparisons").status_code == 401
        assert client.get("/api/v1/rag/comparisons/1").status_code == 401

    def test_one_users_comparison_is_not_visible_to_another(self, client,
                                                           auth_headers):
        import uuid

        created = client.post(
            "/api/v1/rag/compare",
            json={"question": QUESTION, "disease": "breast", "persist": True},
            headers=auth_headers,
        ).json()["data"]["comparison_id"]

        other = client.post(
            "/api/v1/auth/register",
            json={"email": f"other-{uuid.uuid4().hex[:8]}@example.com",
                  "display_name": "Other", "password": "testpass123"},
        )
        assert other.status_code == 200, other.text
        other_headers = {
            "Authorization": f"Bearer {other.json()['data']['access_token']}"
        }

        assert client.get(f"/api/v1/rag/comparisons/{created}",
                          headers=other_headers).status_code == 403
        assert client.delete(f"/api/v1/rag/comparisons/{created}",
                             headers=other_headers).status_code == 403

    def test_local_only_request_returns_one_column(self, client, auth_headers):
        res = client.post(
            "/api/v1/rag/compare",
            json={"question": QUESTION, "disease": "breast",
                  "paths": ["local_rag"], "persist": False},
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert [p["key"] for p in res.json()["data"]["paths"]] == ["local_rag"]

    def test_empty_question_is_rejected(self, client, auth_headers):
        res = client.post("/api/v1/rag/compare",
                          json={"question": "", "persist": False},
                          headers=auth_headers)
        assert res.status_code == 422
