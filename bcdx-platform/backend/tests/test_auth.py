"""Authentication: registration, login, tokens, and account isolation.

Two properties beyond "it works":

* **No account enumeration.** A wrong password and an unknown email return the
  same status and the same message, so the login endpoint cannot be used to
  discover which addresses are registered.
* **Token-gated surface.** Every non-public route rejects a missing, malformed
  or disabled-account token, and a user cannot reach another user's data.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"auth-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str | None = None, password: str = "testpass123",
              display_name: str = "Tester"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email or _email(), "display_name": display_name,
              "password": password},
    )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

class TestRegister:
    def test_returns_a_token_and_the_profile(self, client):
        email = _email()
        res = _register(client, email)
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["access_token"]
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        assert data["user"]["email"] == email
        assert data["user"]["role"] in {"admin", "user"}
        # The password hash must never be serialised.
        assert "hashed_password" not in data["user"]
        assert "password" not in data["user"]

    def test_email_is_normalised_to_lowercase(self, client):
        email = _email()
        res = _register(client, email.upper())
        assert res.status_code == 200
        assert res.json()["data"]["user"]["email"] == email.lower()

    def test_duplicate_email_is_rejected(self, client):
        email = _email()
        assert _register(client, email).status_code == 200
        res = _register(client, email)
        assert res.status_code == 409
        assert res.json()["code"] == 2003  # EMAIL_TAKEN

    def test_duplicate_email_is_case_insensitive(self, client):
        email = _email()
        assert _register(client, email).status_code == 200
        assert _register(client, email.upper()).status_code == 409

    @pytest.mark.parametrize("password", ["12345678", "abcdefgh"])
    def test_password_must_mix_letters_and_digits(self, client, password):
        assert _register(client, password=password).status_code == 422

    def test_password_must_be_long_enough(self, client):
        assert _register(client, password="a1b2").status_code == 422

    @pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", ""])
    def test_malformed_email_is_rejected(self, client, email):
        # Posted directly: the `_register` helper substitutes a random address
        # for falsy input, which would hide the empty-string case.
        res = client.post("/api/v1/auth/register",
                          json={"email": email, "display_name": "Tester",
                                "password": "testpass123"})
        assert res.status_code == 422, res.text

    def test_blank_display_name_is_rejected(self, client):
        res = client.post("/api/v1/auth/register",
                          json={"email": _email(), "display_name": "   ",
                                "password": "testpass123"})
        assert res.status_code == 422

    def test_first_account_becomes_an_admin(self, client):
        """A fresh deployment must be manageable without touching the database.

        Asserted on the lowest user id rather than on "my" user, so the test does
        not depend on which test module ran first.
        """
        from sqlalchemy import select

        from app.db.models import User
        from app.db.session import SessionLocal

        _register(client)  # make sure at least two accounts exist

        with SessionLocal() as db:
            users = db.scalars(select(User).order_by(User.id)).all()
        assert len(users) >= 2
        assert users[0].role == "admin", "the bootstrap account was not an admin"
        assert any(u.role == "user" for u in users[1:]), \
            "every account is an admin; the bootstrap rule is not scoped"

    def test_registration_is_audited(self, client):
        from sqlalchemy import select

        from app.db.models import AuditLog
        from app.db.session import SessionLocal

        email = _email()
        _register(client, email)
        with SessionLocal() as db:
            actions = db.scalars(
                select(AuditLog.action).where(AuditLog.resource == email)
            ).all()
        assert "register" in actions


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #

class TestLogin:
    def test_correct_credentials_return_a_token(self, client):
        email = _email()
        _register(client, email)
        res = client.post("/api/v1/auth/login",
                          json={"email": email, "password": "testpass123"})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["access_token"]

    def test_login_is_case_insensitive_on_email(self, client):
        email = _email()
        _register(client, email)
        res = client.post("/api/v1/auth/login",
                          json={"email": email.upper(), "password": "testpass123"})
        assert res.status_code == 200

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, client):
        """No account enumeration: identical status, code and message."""
        email = _email()
        _register(client, email)

        wrong_password = client.post("/api/v1/auth/login",
                                     json={"email": email, "password": "wrongpass1"})
        unknown_email = client.post("/api/v1/auth/login",
                                    json={"email": _email(), "password": "wrongpass1"})

        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json()["code"] == unknown_email.json()["code"] == 2002
        assert wrong_password.json()["message"] == unknown_email.json()["message"]

    def test_login_is_audited(self, client):
        from sqlalchemy import select

        from app.db.models import AuditLog
        from app.db.session import SessionLocal

        email = _email()
        _register(client, email)
        client.post("/api/v1/auth/login",
                    json={"email": email, "password": "testpass123"})
        with SessionLocal() as db:
            actions = db.scalars(
                select(AuditLog.action).where(AuditLog.resource == email)
            ).all()
        assert "login" in actions


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #

class TestTokenGate:
    def test_me_returns_the_profile(self, client, auth_headers):
        res = client.get("/api/v1/auth/me", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["data"]["display_name"] == "Pytest"

    def test_me_without_a_token_is_unauthorised(self, client):
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 401
        assert res.json()["code"] == 2001

    @pytest.mark.parametrize("token", ["garbage", "a.b.c", ""])
    def test_malformed_tokens_are_rejected(self, client, token):
        res = client.get("/api/v1/auth/me",
                         headers={"Authorization": f"Bearer {token}"})
        assert res.status_code in {401, 403}

    def test_a_token_for_a_deleted_account_is_rejected(self, client):
        from sqlalchemy import select

        from app.core.security import create_access_token
        from app.db.models import User
        from app.db.session import SessionLocal

        email = _email()
        _register(client, email)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            user_id = user.id
            db.delete(user)
            db.commit()

        token = create_access_token(user_id)
        res = client.get("/api/v1/auth/me",
                         headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401
        assert "no longer exists" in res.json()["message"]

    def test_a_disabled_account_is_forbidden(self, client):
        from sqlalchemy import select

        from app.db.models import User
        from app.db.session import SessionLocal

        email = _email()
        token = _register(client, email).json()["data"]["access_token"]

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            user.is_active = False
            db.commit()

        res = client.get("/api/v1/auth/me",
                         headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403
        assert res.json()["code"] == 2006  # FORBIDDEN

    def test_tokens_are_isolated_between_users(self, client):
        a = _register(client).json()["data"]
        b = _register(client).json()["data"]
        assert a["user"]["id"] != b["user"]["id"]

        me_a = client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {a['access_token']}"}).json()["data"]
        me_b = client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {b['access_token']}"}).json()["data"]
        assert me_a["email"] != me_b["email"]


# --------------------------------------------------------------------------- #
# Protected surface
# --------------------------------------------------------------------------- #

class TestProtectedSurface:
    @pytest.mark.parametrize("method,path", [
        ("get", "/api/v1/rag/conversations"),
        ("get", "/api/v1/rag/usage"),
        ("get", "/api/v1/rag/comparisons"),
        ("get", "/api/v1/models/registry"),
        ("get", "/api/v1/records"),
        ("get", "/api/v1/predict/samples"),
    ])
    def test_every_private_get_route_requires_auth(self, client, method, path):
        res = getattr(client, method)(path)
        assert res.status_code == 401, f"{path} answered without a token"

    @pytest.mark.parametrize("method,path", [
        ("post", "/api/v1/predict"),
        ("post", "/api/v1/predict/batch"),
        ("post", "/api/v1/rag/ask"),
        ("post", "/api/v1/rag/compare"),
    ])
    def test_every_private_post_route_requires_auth(self, client, method, path):
        res = getattr(client, method)(path, json={})
        assert res.status_code == 401, f"{path} answered without a token"

    @pytest.mark.parametrize("path", [
        "/", "/health", "/api/v1/models", "/api/v1/meta/limits",
        "/api/v1/rag/sources",
    ])
    def test_documented_public_routes_need_no_token(self, client, path):
        assert client.get(path).status_code == 200, f"{path} should be public"
