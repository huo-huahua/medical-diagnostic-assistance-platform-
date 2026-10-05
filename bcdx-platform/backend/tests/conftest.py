"""Shared test fixtures.

The database URL is set **before** `app.core.config` is imported, because
`settings` is built once at import time and cached. Pointing the tests at a
throwaway SQLite file keeps them from touching the developer's `bcdx.db`.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# The throwaway database lives in the OS temp directory, not next to the tests.
# A path inside the repo works until the cleanup `unlink()` is blocked (some
# sandboxes interpose on file deletion), at which point a ~100 KB `.db` is left
# sitting in the source tree. Nothing depends on the file being there, so the
# temp directory is strictly better. The pid keeps concurrent runs from sharing
# a file. `tempfile.gettempdir()` returns a native Windows path — unlike the
# literal "/tmp", which SQLite cannot open on Windows.
_TEST_DB = Path(tempfile.gettempdir()) / f"bcdx_pytest_{os.getpid()}.db"

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TEST_DB.as_posix()}"
# Guarantee the suite can never make a real, billed API call.
os.environ["LLM_ENABLED"] = "false"
os.environ["LLM_API_KEY"] = ""
os.environ["ENVIRONMENT"] = "test"
# The limiters are module-level singletons shared across the whole session, so
# the production defaults (12/minute for RAG) would be tripped by the suite
# merely doing its job. The limiter itself is unit-tested in test_gateway.py.
os.environ["RATE_LIMIT_PREDICT"] = "100000/minute"
os.environ["RATE_LIMIT_LLM"] = "100000/minute"
os.environ["RATE_LIMIT_AUTH"] = "100000/minute"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """One app instance for the whole session.

    Session-scoped on purpose: spinning up the app loads six model artifacts and
    builds the embedding index, which is ~40s of work that must not repeat per
    test.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def fresh_llm_gateway(monkeypatch):
    """Give every test its own LLM gateway.

    The gateway is a process-wide singleton that carries mutable state: call
    counters, token totals, the last error, and a response cache. Sharing it
    makes any assertion about those numbers depend on execution order — a test
    asserting "no external calls were made" would fail merely because a test
    that exercised the external path ran first.

    Swapping in a fresh instance per test removes that coupling, and is also
    what makes the cache assertions deterministic: a previous test's cached
    answer can no longer satisfy a later test's request.
    """
    from app.services import llm_gateway

    monkeypatch.setattr(llm_gateway, "_gateway", llm_gateway.LlmGateway())


@pytest.fixture(scope="session")
def auth_headers(client) -> dict[str, str]:
    """A registered user's bearer token."""
    # `example.com` rather than a `.test` TLD: email-validator rejects
    # special-use/reserved domains outright, and RFC 2606 reserves
    # example.com for exactly this purpose.
    email = f"pytest-{uuid.uuid4().hex[:8]}@example.com"
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": "Pytest", "password": "testpass123"},
    )
    assert res.status_code == 200, res.text
    token = res.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    """Remove the throwaway database (plus SQLite's journal, if any)."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(str(_TEST_DB) + suffix)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
