import base64
import json
from datetime import timedelta

import pytest

from app.auth import hooks
from app.auth.errors import Unauthenticated
from app.auth.models import AuthSession
from app.auth.service import principal_from_token
from app.db.base import utcnow
from app.db.session import new_session


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_login_returns_token_and_user(client):
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"] == {
        "username": "analyst",
        "display_name": "Alex Tan",
        "email": "alex.tan@datahub.local",
        "department": "Risk Management",
        "title": "Data Analyst",
    }


def test_token_carries_the_directory_identity(client):
    token = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"}).json()["access_token"]
    claims = _claims(token)
    assert set(claims) == {"sub", "jti", "name", "email", "department", "title", "iss", "aud", "iat", "exp", "system_roles", "org_unit_roles"}
    assert claims["sub"] == "analyst"
    assert (claims["name"], claims["department"], claims["title"]) == ("Alex Tan", "Risk Management", "Data Analyst")
    assert claims["iss"] == "data-hub" and claims["aud"] == "data-hub-api"
    assert claims["exp"] - claims["iat"] == 3600


def test_lan_id_is_case_insensitive(client):
    assert client.post("/api/auth/login", json={"username": " Analyst ", "password": "datahub123"}).status_code == 200


def test_wrong_password_and_unknown_user_get_the_same_answer(client):
    a = client.post("/api/auth/login", json={"username": "analyst", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Incorrect LAN ID or password."}


def test_empty_fields_are_rejected(client):
    assert client.post("/api/auth/login", json={"username": "", "password": "x"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "analyst", "password": ""}).status_code == 422


def test_repeated_failures_do_not_lock_the_account(client, login):
    """Lockout is the directory's job: Data Hub never blocks a correct password."""
    login("analyst")
    for _ in range(10):
        assert client.post("/api/auth/login", json={"username": "analyst", "password": "bad"}).status_code == 401
    login("analyst")


def test_directory_refusal_is_a_plain_sign_in_failure(client, monkeypatch):
    """A locked or disabled directory account comes back as None, like a wrong password."""
    import app.auth.service as auth_service

    monkeypatch.setattr(auth_service.ldap, "authenticate", lambda *a: None)
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect LAN ID or password."


def test_directory_down_is_not_a_wrong_password(client, directory):
    directory.unlink()
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 503
    assert r.json()["detail"] == "Sign-in is unavailable right now. Please try again later."


def test_me_returns_the_signed_in_user(client, login):
    r = client.get("/api/auth/me", headers=login("admin"))
    assert r.status_code == 200
    assert r.json() == {
        "username": "admin",
        "display_name": "Data Hub Admin",
        "email": "admin@datahub.local",
        "department": "Technology",
        "title": "Platform Administrator",
    }


def test_sign_in_hooks_get_the_identity(client, monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "_sign_in_hooks", [lambda db, who: seen.append(who)])
    client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert [(w.lan_id, w.department) for w in seen] == [("analyst", "Risk Management")]


def test_hooks_do_not_run_when_the_directory_refuses(client, monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "_sign_in_hooks", [lambda db, who: seen.append(who)])
    client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    assert seen == []


def test_a_hook_can_refuse_sign_in(client, monkeypatch):
    def refuse(db, who):
        raise Unauthenticated("Your Data Hub access has been removed.")

    monkeypatch.setattr(hooks, "_sign_in_hooks", [refuse])
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Your Data Hub access has been removed."
    with new_session() as db:
        assert db.query(AuthSession).count() == 0


def test_hooks_can_add_token_claims(client, monkeypatch):
    monkeypatch.setattr(hooks, "_sign_in_hooks", [lambda db, who: {"team": "alpha"}, lambda db, who: None])
    token = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"}).json()["access_token"]
    assert _claims(token)["team"] == "alpha"
    with new_session() as db:
        principal = principal_from_token(db, token)
    assert principal.claims == {"team": "alpha"}
    assert principal.lan_id == "analyst"


def test_hooks_cannot_overwrite_auth_claims(client, monkeypatch):
    monkeypatch.setattr(hooks, "_sign_in_hooks", [lambda db, who: {"sub": "admin"}])
    with pytest.raises(RuntimeError, match="sub"):
        client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    with new_session() as db:
        assert db.query(AuthSession).count() == 0


def test_two_hooks_cannot_add_the_same_claim(client, monkeypatch):
    monkeypatch.setattr(hooks, "_sign_in_hooks", [lambda db, who: {"team": "a"}, lambda db, who: {"team": "b"}])
    with pytest.raises(RuntimeError, match="team"):
        client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})


def test_auth_imports_no_other_feature():
    """Auth stays self-contained: only core and db, never users or later features."""
    import ast
    import pathlib

    import app.auth

    for path in pathlib.Path(app.auth.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                if name.startswith("app."):
                    assert name.split(".")[1] in {"auth", "core", "db"}, f"{path.name} imports {name}"


def test_logout_revokes_the_token(client, login):
    h = login("analyst")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 401
    assert r.json()["detail"] == "Session ended. Please sign in again."


def test_logout_ends_only_that_session(client, login):
    first, second = login("analyst"), login("analyst")
    client.post("/api/auth/logout", headers=first)
    assert client.get("/api/auth/me", headers=second).status_code == 200


def test_expired_session_is_rejected(client, login):
    h = login("analyst")
    with new_session() as db:
        for s in db.query(AuthSession):
            s.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_tampered_token_is_rejected(client, login):
    h = login("analyst")
    token = h["Authorization"].split()[1]
    header, _, sig = token.split(".")
    claims = _claims(token)
    claims["sub"] = "admin"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {header}.{forged}.{sig}"})
    assert r.status_code == 401


def test_missing_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
