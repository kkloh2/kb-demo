import base64
import json
from datetime import timedelta

from app.auth.models import AuthSession, User
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
    assert body["user"] == {"username": "analyst", "display_name": "Alex Tan", "email": "alex.tan@datahub.local"}


def test_token_identifies_the_user_only(client):
    token = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"}).json()["access_token"]
    claims = _claims(token)
    assert set(claims) == {"sub", "uid", "jti", "name", "iss", "aud", "iat", "exp"}
    assert claims["sub"] == "analyst"
    assert claims["iss"] == "data-hub" and claims["aud"] == "data-hub-api"
    assert claims["exp"] - claims["iat"] == 3600


def test_lan_id_is_case_insensitive(client):
    assert client.post("/api/auth/login", json={"username": " Analyst ", "password": "datahub123"}).status_code == 200


def test_wrong_password_and_unknown_user_get_the_same_answer(client):
    a = client.post("/api/auth/login", json={"username": "analyst", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Incorrect LAN ID or password."}


def test_unknown_user_still_runs_a_password_check(client, monkeypatch):
    """Guards against LAN ID enumeration by timing."""
    import app.auth.service as auth_service

    calls = []
    monkeypatch.setattr(auth_service, "burn_password_check", lambda pw: calls.append(pw))
    client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert calls == ["x"]


def test_inactive_user_cannot_sign_in(client):
    with new_session() as db:
        db.query(User).filter_by(lan_id="analyst").one().is_active = False
        db.commit()
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect LAN ID or password."


def test_empty_fields_are_rejected(client):
    assert client.post("/api/auth/login", json={"username": "", "password": "x"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "analyst", "password": ""}).status_code == 422


def test_lockout_after_five_failures(client):
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "analyst", "password": "bad"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    assert r.status_code == 423
    # Even the right password is refused while locked.
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 423
    assert "Try again in 15 minutes" in r.json()["detail"]


def test_lock_expires(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    with new_session() as db:
        db.query(User).filter_by(lan_id="analyst").one().locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"}).status_code == 200


def test_successful_login_resets_failed_count(client):
    client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    with new_session() as db:
        user = db.query(User).filter_by(lan_id="analyst").one()
        assert user.failed_login_count == 0
        assert user.last_login_at is not None


def test_me_returns_the_signed_in_user(client, login):
    r = client.get("/api/auth/me", headers=login("admin"))
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


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
