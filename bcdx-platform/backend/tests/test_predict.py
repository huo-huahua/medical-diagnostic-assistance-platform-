"""Prediction: label semantics, the champion threshold, and the batch path.

The two traps this file exists to prevent
-----------------------------------------
1. **Label inversion.** The project is globally fixed at `0 = negative`,
   `1 = positive`, and every response is rendered from that convention. It is
   easy to get backwards: `sklearn.datasets.load_breast_cancer` uses the
   *opposite* encoding (`0 = malignant`, `1 = benign`), so code or analysis
   ported from it can look correct while printing the wrong verdict. The
   invariants below are stated in terms of the *displayed* labels, which is what
   a user actually reads.

2. **The threshold is not 0.5.** Breast uses a screening-oriented Youden's J
   cut-off of **0.1701**, so a probability of 0.30 is a *positive* call. Any
   summary that tallies at 0.5 contradicts the per-row verdicts shown beside it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

BREAST = "breast"
HEART = "heart"


def _feature_keys(client, disease: str) -> list[str]:
    res = client.get(f"/api/v1/models/{disease}")
    assert res.status_code == 200
    return [f["key"] for f in res.json()["data"]["feature_schema"]]


def _defaults(client, disease: str) -> list[float]:
    res = client.get(f"/api/v1/models/{disease}")
    return res.json()["data"]["default_values"]


def _threshold(client, disease: str) -> float:
    data = client.get(f"/api/v1/models/{disease}").json()["data"]
    champion = next(m for m in data["models"] if m["id"] == data["champion_id"])
    return champion["threshold"]


# --------------------------------------------------------------------------- #
# Schema metadata — the source of every label the UI shows
# --------------------------------------------------------------------------- #

class TestSchemaSemantics:
    def test_disease_metadata_is_public(self, client):
        res = client.get("/api/v1/models")
        assert res.status_code == 200
        assert {d["disease"] for d in res.json()["data"]} == {BREAST, HEART}

    @pytest.mark.parametrize(
        "disease,positive_zh,negative_zh",
        [(BREAST, "恶性", "良性"), (HEART, "患病", "健康")],
    )
    def test_positive_and_negative_labels(self, client, disease,
                                          positive_zh, negative_zh):
        """Pin the documented convention; a swap here silently inverts every
        verdict the product displays."""
        data = client.get(f"/api/v1/models/{disease}").json()["data"]
        assert data["positive_label_zh"] == positive_zh
        assert data["negative_label_zh"] == negative_zh

    def test_breast_feature_schema_matches_its_defaults(self, client):
        keys = _feature_keys(client, BREAST)
        assert len(keys) == 30
        # Native model names, not display names.
        assert keys[0] == "radius1"
        assert len(_defaults(client, BREAST)) == len(keys)

    def test_heart_feature_schema_matches_its_defaults(self, client):
        keys = _feature_keys(client, HEART)
        assert len(keys) == 13
        assert len(_defaults(client, HEART)) == len(keys)

    def test_every_feature_has_a_chinese_display_name(self, client):
        for disease in (BREAST, HEART):
            for f in client.get(f"/api/v1/models/{disease}").json()["data"]["feature_schema"]:
                assert f["name_zh"], f"{disease}/{f['key']} has no Chinese name"

    def test_champion_thresholds_are_not_one_half(self, client):
        """The whole reason `threshold` is echoed in every response."""
        assert _threshold(client, BREAST) == pytest.approx(0.1701, abs=1e-3)
        assert _threshold(client, HEART) == pytest.approx(0.6321, abs=1e-3)


# --------------------------------------------------------------------------- #
# Single prediction
# --------------------------------------------------------------------------- #

class TestPredict:
    def test_requires_authentication(self, client):
        res = client.post("/api/v1/predict", json={"features": [1.0]})
        assert res.status_code == 401

    def test_verdict_agrees_with_the_threshold_and_the_label(self, client,
                                                            auth_headers):
        keys = _feature_keys(client, BREAST)
        payload = {
            "disease": BREAST,
            "features": _defaults(client, BREAST),
            "with_explanation": False,
            "persist": False,
        }
        res = client.post("/api/v1/predict", json=payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()["data"]

        threshold = data["threshold"]
        positive = data["positive_prob"] >= threshold

        assert data["verdict"] == ("positive" if positive else "negative")
        assert data["verdict_label"] == ("恶性" if positive else "良性")
        assert data["positive_prob"] + data["negative_prob"] == pytest.approx(1.0, abs=1e-4)
        assert data["threshold"] == pytest.approx(_threshold(client, BREAST), abs=1e-6)
        assert len(keys) == 30

    def test_mean_filled_vector_is_a_positive_call_at_this_threshold(self, client,
                                                                    auth_headers):
        """Documented behaviour, not a bug.

        The breast champion's threshold is a screening-oriented 0.1701, so a
        mean-filled vector (probability ~0.44) is classified positive. Anyone
        finding this surprising is reading the 0.5 rule of thumb into a model
        that deliberately does not use it.
        """
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": _defaults(client, BREAST),
                  "with_explanation": False, "persist": False},
            headers=auth_headers,
        )
        data = res.json()["data"]
        assert data["positive_prob"] > data["threshold"]
        assert data["verdict"] == "positive"
        assert data["verdict_label"] == "恶性"

    def test_an_extreme_benign_vector_is_a_negative_call(self, client, auth_headers):
        """The complementary case — proves the verdict is not stuck positive."""
        data = client.get(f"/api/v1/models/{BREAST}").json()["data"]
        lo = [f["min"] for f in data["feature_schema"]]
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": lo,
                  "with_explanation": False, "persist": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        out = res.json()["data"]
        assert out["verdict"] == "negative"
        assert out["verdict_label"] == "良性"

    def test_heart_verdict_uses_the_heart_labels(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": HEART, "features": _defaults(client, HEART),
                  "with_explanation": False, "persist": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        out = res.json()["data"]
        assert out["verdict_label"] in {"患病", "健康"}
        assert out["threshold"] == pytest.approx(_threshold(client, HEART), abs=1e-6)

    def test_wrong_feature_count_is_rejected(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": [1.0, 2.0, 3.0]},
            headers=auth_headers,
        )
        assert res.status_code == 422
        assert res.json()["code"] == 1002  # FEATURE_COUNT_MISMATCH

    def test_unknown_disease_is_rejected(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": "flu", "features": [1.0]},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_explanation_is_returned_when_requested(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": _defaults(client, BREAST),
                  "with_explanation": True, "persist": False},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        explanation = res.json()["data"]["explanation"]
        assert explanation is not None
        assert explanation["contributions"]
        for c in explanation["contributions"]:
            assert c["name_zh"], "a contribution without a Chinese label is unreadable"
            assert c["direction"] in {"positive", "negative", "neutral"}

    def test_persist_creates_a_retrievable_record(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": _defaults(client, BREAST),
                  "with_explanation": False, "persist": True,
                  "case_label": "pytest-record"},
            headers=auth_headers,
        )
        record_id = res.json()["data"]["record_id"]
        assert record_id is not None

        fetched = client.get(f"/api/v1/records/{record_id}", headers=auth_headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["case_label"] == "pytest-record"

    def test_persist_false_writes_nothing(self, client, auth_headers):
        res = client.post(
            "/api/v1/predict",
            json={"disease": BREAST, "features": _defaults(client, BREAST),
                  "with_explanation": False, "persist": False},
            headers=auth_headers,
        )
        assert res.json()["data"]["record_id"] is None


# --------------------------------------------------------------------------- #
# Real dataset samples — replaces the biased synthetic generator
# --------------------------------------------------------------------------- #

class TestSamples:
    def test_requires_authentication(self, client):
        assert client.get("/api/v1/predict/samples").status_code == 401

    @pytest.mark.parametrize("disease", [BREAST, HEART])
    def test_samples_are_real_rows_with_labels(self, client, auth_headers, disease):
        res = client.get("/api/v1/predict/samples",
                         params={"disease": disease, "n": 12},
                         headers=auth_headers)
        assert res.status_code == 200, res.text
        data = res.json()["data"]

        assert data["disease"] == disease
        assert data["source"], "the sample source must be named for provenance"
        assert len(data["rows"]) == 12
        keys = _feature_keys(client, disease)
        for row in data["rows"]:
            assert row["case_label"], "a sample without an id cannot be traced back"
            # Dataset-native encoding: 0 = negative, 1 = positive.
            assert row["true_label"] in {0, 1}
            assert set(row["features"]) == set(keys)

    @pytest.mark.parametrize("disease", [BREAST, HEART])
    def test_samples_are_balanced_across_labels(self, client, auth_headers, disease):
        """Regression: uniform sampling over [min, max] centred on the positive
        class (its maximum *is* the upper tail), so all 12 demo rows came back
        'malignant at 100%'. Real rows, sampled evenly, give both classes."""
        res = client.get("/api/v1/predict/samples",
                         params={"disease": disease, "n": 12, "balanced": True},
                         headers=auth_headers)
        rows = res.json()["data"]["rows"]
        positives = sum(1 for r in rows if r["true_label"] == 1)
        assert positives == 6, f"{disease}: {positives}/12 positive, expected 6"

    def test_sampling_is_deterministic_for_a_seed(self, client, auth_headers):
        params = {"disease": BREAST, "n": 12, "seed": 12345}
        a = client.get("/api/v1/predict/samples", params=params,
                       headers=auth_headers).json()["data"]["rows"]
        b = client.get("/api/v1/predict/samples", params=params,
                       headers=auth_headers).json()["data"]["rows"]
        assert [r["case_label"] for r in a] == [r["case_label"] for r in b]

    def test_different_seeds_give_different_batches(self, client, auth_headers):
        a = client.get("/api/v1/predict/samples",
                       params={"disease": BREAST, "n": 12, "seed": 1},
                       headers=auth_headers).json()["data"]["rows"]
        b = client.get("/api/v1/predict/samples",
                       params={"disease": BREAST, "n": 12, "seed": 2},
                       headers=auth_headers).json()["data"]["rows"]
        assert [r["case_label"] for r in a] != [r["case_label"] for r in b]


# --------------------------------------------------------------------------- #
# Batch prediction
# --------------------------------------------------------------------------- #

def _sample_set(client, auth_headers, disease: str, n: int = 12) -> list[dict]:
    """Raw sample rows: `{case_label, features, true_label}`."""
    res = client.get("/api/v1/predict/samples",
                     params={"disease": disease, "n": n}, headers=auth_headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]["rows"]


def _batch_rows(samples: list[dict]) -> list[dict]:
    """What the batch endpoint expects — the frontend flattens `features`."""
    return [s["features"] for s in samples]


def _truth(sample: dict) -> str:
    return "positive" if sample["true_label"] == 1 else "negative"


class TestBatchPredict:
    def test_requires_authentication(self, client):
        res = client.post("/api/v1/predict/batch",
                          json={"rows": [{"radius1": 1.0}]})
        assert res.status_code == 401

    def test_summary_tallies_from_each_rows_verdict(self, client, auth_headers):
        """The regression that matters.

        The summary used to count `probs >= 0.5` while every row was labelled
        with the champion threshold (0.1701). A probability of 0.30 was shown as
        "恶性" but tallied as a negative.
        """
        rows = _batch_rows(_sample_set(client, auth_headers, BREAST))
        res = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": rows},
            headers=auth_headers,
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        threshold = data["threshold"]

        assert threshold == pytest.approx(_threshold(client, BREAST), abs=1e-6)
        assert threshold < 0.5, "this regression is only meaningful below 0.5"

        by_verdict = sum(1 for r in data["results"] if r["verdict"] == "positive")
        assert data["positives"] == by_verdict
        assert data["negatives"] == data["count"] - by_verdict
        assert data["positives"] + data["negatives"] == data["count"] == len(rows)

        for r in data["results"]:
            assert r["verdict"] == ("positive" if r["positive_prob"] >= threshold
                                    else "negative")
            assert r["verdict_label"] in {"恶性", "良性"}

        # Had the old 0.5 rule been in force, these two would disagree.
        legacy_positive = sum(1 for r in data["results"] if r["positive_prob"] >= 0.5)
        assert legacy_positive <= data["positives"]

    def test_batch_labels_agree_with_the_true_dataset_labels(self, client,
                                                            auth_headers):
        samples = _sample_set(client, auth_headers, BREAST)
        data = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": _batch_rows(samples)},
            headers=auth_headers,
        ).json()["data"]
        agreed = sum(1 for r, s in zip(data["results"], samples)
                     if r["verdict"] == _truth(s))
        # Real data on a champion model with AUC 0.9959. The bound is loose on
        # purpose: this asserts the pipeline is sound, not that the model is
        # perfect on twelve arbitrary rows.
        assert agreed >= 9, f"only {agreed}/12 rows matched their true label"

    def test_batch_produces_both_classes(self, client, auth_headers):
        """A batch that is uniformly 'malignant at 100%' is the sampling bug."""
        samples = _sample_set(client, auth_headers, BREAST)
        data = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": _batch_rows(samples)},
            headers=auth_headers,
        ).json()["data"]
        assert data["positives"] > 0, "every row came back negative"
        assert data["negatives"] > 0, "every row came back positive"

    def test_mean_probability_is_reported(self, client, auth_headers):
        samples = _sample_set(client, auth_headers, BREAST)
        data = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": _batch_rows(samples)},
            headers=auth_headers,
        ).json()["data"]
        probs = [r["positive_prob"] for r in data["results"]]
        assert data["mean_positive_prob"] == pytest.approx(sum(probs) / len(probs),
                                                           abs=1e-5)

    def test_heart_batch_uses_the_heart_threshold(self, client, auth_headers):
        samples = _sample_set(client, auth_headers, HEART)
        data = client.post(
            "/api/v1/predict/batch",
            json={"disease": HEART, "rows": _batch_rows(samples)},
            headers=auth_headers,
        ).json()["data"]
        assert data["threshold"] == pytest.approx(0.6321, abs=1e-3)
        for r in data["results"]:
            assert r["verdict"] == ("positive" if r["positive_prob"] >= 0.6321
                                    else "negative")

    def test_rows_keep_their_input_order(self, client, auth_headers):
        samples = _sample_set(client, auth_headers, BREAST, n=4)
        data = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": _batch_rows(samples)},
            headers=auth_headers,
        ).json()["data"]
        assert [r["row"] for r in data["results"]] == [0, 1, 2, 3]

    def test_missing_feature_names_the_offending_row(self, client, auth_headers):
        samples = _sample_set(client, auth_headers, BREAST, n=2)
        broken = dict(samples[0]["features"])
        broken.pop("radius1")
        res = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST,
                  "rows": [samples[1]["features"], broken]},
            headers=auth_headers,
        )
        assert res.status_code == 422
        body = res.json()
        assert "Row 1" in body["message"], body

    def test_non_finite_values_are_rejected(self, client, auth_headers):
        samples = _sample_set(client, auth_headers, BREAST, n=1)
        features = dict(samples[0]["features"])
        features["radius1"] = float("inf")
        res = client.post(
            "/api/v1/predict/batch",
            json={"disease": BREAST, "rows": [features]},
            headers=auth_headers,
        )
        assert res.status_code == 422

    def test_empty_batch_is_rejected(self, client, auth_headers):
        res = client.post("/api/v1/predict/batch",
                          json={"disease": BREAST, "rows": []},
                          headers=auth_headers)
        assert res.status_code == 422
