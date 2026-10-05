"""App-level surface: health, operational limits, and the response envelope.

Two things are worth pinning down here:

* **`/health` reports the chunking statistics.** That is the observable proof
  that the embedding window is respected — the original truncation bug was
  invisible precisely because nothing surfaced `oversize`.
* **Every response uses the same envelope.** The frontend unwraps `data`
  unconditionally, so a route that returns a bare body would break it silently.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestHealth:
    def test_health_is_public_and_ok(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["version"]

    def test_health_reports_chunking_statistics(self, client):
        """`oversize` is the number that has to stay at zero."""
        from app.services.rag_service import get_index

        index = get_index()
        if not index.ready:
            index.build()

        stats = client.get("/health").json()["rag_chunking"]
        assert stats["count"] > 0
        assert stats["oversize"] == 0, (
            f"{stats['oversize']} chunk(s) exceed the embedding window and are "
            f"being truncated silently"
        )
        assert stats["window"] > 0
        assert stats["max_tokens"] < stats["window"]
        assert stats["avg_chars"] > 0
        assert 0 <= stats["split_sections"] <= stats["count"]

    def test_health_reports_the_rag_index(self, client):
        body = client.get("/health").json()
        assert body["rag_ready"] is True
        assert body["rag_chunks"] > 100

    def test_health_reports_the_llm_gateway(self, client):
        llm = client.get("/health").json()["llm"]
        assert llm["available"] is False   # no key in the test environment
        assert llm["api_calls_this_process"] == 0
        assert "cache" in llm

    def test_index_is_built_once_and_reused(self, client):
        from app.services.rag_service import get_index

        assert get_index() is get_index()


class TestLimits:
    def test_limits_are_public(self, client):
        res = client.get("/api/v1/meta/limits")
        assert res.status_code == 200
        data = res.json()["data"]

        assert data["rag_top_k"] >= 1
        assert 0 <= data["rag_min_similarity"] <= 1
        assert data["rag_chunk_max_chars"] > 0
        assert data["rag_chunk_overlap_chars"] < data["rag_chunk_max_chars"]
        assert data["max_upload_mb"] > 0

    def test_limits_reflect_the_llm_being_off(self, client):
        data = client.get("/api/v1/meta/limits").json()["data"]
        assert data["llm_enabled"] is False

    def test_comparison_limits_are_exposed(self, client):
        data = client.get("/api/v1/meta/limits").json()["data"]
        assert data["qa_compare_max_question_chars"] > 0
        assert isinstance(data["qa_compare_allow_llm"], bool)


class TestRoot:
    def test_root_describes_the_service(self, client):
        body = client.get("/").json()
        assert body["name"]
        assert body["version"]
        assert body["docs"] == "/docs"
        # The disclaimer belongs on the front door of a medical-adjacent tool.
        assert "Not a medical device" in body["disclaimer"]


class TestEnvelope:
    def test_success_responses_share_the_envelope(self, client):
        for path in ("/api/v1/models", "/api/v1/meta/limits"):
            body = client.get(path).json()
            assert set(body) >= {"code", "message", "data", "request_id"}
            assert body["code"] == 0
            assert body["message"] == "ok"
            assert body["request_id"] != "-"

    def test_error_responses_use_the_same_envelope(self, client):
        body = client.get("/api/v1/auth/me").json()
        assert body["code"] == 2001
        assert body["data"] is None
        assert body["message"]
        assert body["request_id"] != "-"

    def test_a_validation_error_also_uses_the_envelope(self, client, auth_headers):
        """The error path that used to bypass the envelope entirely.

        FastAPI installs its own handler for `RequestValidationError`, and that
        built-in handler beats the generic `Exception` one — so a 422 came back
        as a bare `{"detail": [...]}` with no `message`. The frontend reads
        `message` and falls back to the literal string "请求失败", which meant
        every field-level rejection reached the user as "the request failed"
        with no indication of *what* was wrong, even though the server had
        worked out exactly which field it was.

        Kept separate from the test above because it exercises a different
        handler; the earlier one only ever reached `AppError`.
        """
        # Auth is required first: FastAPI resolves dependencies before it
        # validates the body, so without a token this comes back 401 and never
        # reaches the validation handler at all (see the ordering test below).
        res = client.post(
            "/api/v1/predict",
            json={"disease": "breast", "features": []},
            headers=auth_headers,
        )
        assert res.status_code == 422
        body = res.json()
        assert set(body) >= {"code", "message", "data", "details", "request_id"}
        assert body["code"] == 1001
        assert body["message"].startswith("Validation failed")
        assert "features" in body["message"], (
            "the message has to name the offending field — that is the whole "
            "point, since the generic fallback said nothing"
        )
        assert body["details"], "the structured errors must survive for clients"
        assert body["request_id"] != "-"

    def test_a_bad_body_without_a_token_is_401_not_422(self, client):
        """Auth is checked before the body, and that ordering is observable.

        Worth pinning because it decides which handler a caller hits: an
        unauthenticated request with a malformed body is a 401 (an `AppError`,
        which always had the envelope), so the validation handler only ever runs
        for *authorised* callers. It also cost me a debugging round-trip —
        writing the 422 test without a token produced a 401 and looked like the
        envelope fix had not worked.
        """
        res = client.post("/api/v1/predict", json={"disease": "breast", "features": []})
        assert res.status_code == 401
        assert res.json()["code"] == 2001

    def test_a_custom_validator_error_is_json_serialisable(self, client):
        """`ctx` can hold a live exception object, and that is not JSON.

        When a `field_validator` raises `ValueError`, pydantic stores the
        exception instance itself under `ctx.error`. Handing that straight to
        `JSONResponse` raises "Object of type ValueError is not JSON
        serializable" *inside the error handler* — a well-formed 422 degrades
        into an unhandled 500, i.e. the cure is worse than the disease. The
        password-strength rule is the real validator in this codebase that
        trips it, so this test goes through `/auth/register` (public, no token)
        rather than the predict route.
        """
        res = client.post(
            "/api/v1/auth/register",
            json={
                "email": "envelope-check@example.com",
                "display_name": "Envelope",
                "password": "abcdefgh",  # letters only — the validator rejects it
            },
        )
        assert res.status_code == 422
        body = res.json()
        assert body["code"] == 1001
        assert body["message"].startswith("Validation failed")
        # The point of the test: the response *is* JSON, and `details` survived.
        assert isinstance(body["details"], list) and body["details"]

    def test_the_validation_message_does_not_run_away_on_a_big_batch(self):
        """A 500-row batch can produce hundreds of field errors.

        The message summarises a few and counts the rest; dumping all of them
        would be a wall of text that is no easier to act on than the first one.
        """
        from app.core.errors import _describe

        errors = [
            {"loc": ["body", "rows", i, "radius1"], "msg": "Field required"}
            for i in range(9)
        ]
        text = _describe(errors)
        assert "rows.0.radius1" in text
        assert "(+6 more)" in text
        assert text.count("Field required") == 3

    def test_request_ids_are_unique_per_request(self, client):
        a = client.get("/api/v1/models").json()["request_id"]
        b = client.get("/api/v1/models").json()["request_id"]
        assert a != b

    def test_unknown_route_is_a_404(self, client):
        assert client.get("/api/v1/does-not-exist").status_code == 404

    def test_openapi_schema_is_served(self, client):
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        paths = schema.json()["paths"]
        assert "/api/v1/rag/compare" in paths
        assert "/api/v1/predict/batch" in paths
        assert "/api/v1/predict/samples" in paths


class TestSecretKeyGuard:
    """`SECRET_KEY` must not be a value anyone could have copied.

    The old `.env.example` shipped `dev-only-secret-...-2f8a91c4` — random
    enough to pass a glance, therefore copied and never changed. A deployment
    signing tokens with a public string lets anyone mint a login token for any
    account, so the check is deliberately blunt and runs at startup.
    """

    @pytest.mark.parametrize("value", [
        "",                                                 # unset
        "   ",
        "change-me-in-dotenv-this-default-is-insecure",     # Settings default
        "change-me-generate-with-openssl-rand-hex-32",      # .env.example today
        "dev-only-secret-please-change-me-in-production-2f8a91c4",  # .env.example before
        "prefix-change-me-suffix",                          # contains a marker
    ])
    def test_placeholders_are_detected(self, monkeypatch, value):
        from app.core.config import settings

        monkeypatch.setattr(settings, "secret_key", value)
        assert settings.secret_key_is_placeholder is True

    def test_a_generated_key_passes(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "secret_key", "9f2c" * 16)
        assert settings.secret_key_is_placeholder is False

    def test_the_shipped_example_key_is_flagged(self, monkeypatch):
        """Whatever `.env.example` ships today must be rejected by definition.

        Reading the file rather than hard-coding the string keeps this honest:
        editing the example to a different placeholder without teaching the
        detection list about it fails here instead of in production.
        """
        from app.core.config import REPO_ROOT, settings

        example = REPO_ROOT / ".env.example"
        if not example.exists():                # pragma: no cover - packaged installs
            pytest.skip(".env.example not present")

        line = next(
            (ln for ln in example.read_text(encoding="utf-8").splitlines()
             if ln.strip().startswith("SECRET_KEY=")),
            None,
        )
        assert line is not None, ".env.example no longer documents SECRET_KEY"
        monkeypatch.setattr(settings, "secret_key", line.split("=", 1)[1].strip())
        assert settings.secret_key_is_placeholder is True

    def test_local_development_only_warns(self, monkeypatch):
        """A loud warning, not a refusal — development must stay runnable."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "secret_key", "change-me")
        monkeypatch.setattr(settings, "environment", "development")
        assert settings.is_production is False
        assert settings.secret_key_is_placeholder is True

    @pytest.mark.parametrize("env", ["production", "prod", "PRODUCTION"])
    def test_production_is_recognised(self, monkeypatch, env):
        from app.core.config import settings

        monkeypatch.setattr(settings, "environment", env)
        assert settings.is_production is True
