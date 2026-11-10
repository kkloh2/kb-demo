import base64
import json

from app.db.models import AuditEvent, User
from app.db.session import new_session


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_token_carries_department_roles_and_permissions(client):
    r = client.post("/api/auth/login", json={"username": "risk.maker", "password": "demo123"})
    assert r.status_code == 200
    claims = _claims(r.json()["access_token"])
    assert claims["sub"] == "risk.maker"
    assert claims["dept"]["code"] == "RISK"
    assert claims["roles"] == ["maker", "viewer"]
    assert "documents:upload" in claims["perms"]
    assert "documents:approve" not in claims["perms"]
    assert claims["iss"] == "data-hub" and claims["aud"] == "data-hub-api"


def test_system_admin_has_no_department_and_no_document_permissions(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    user = r.json()["user"]
    assert user["department"] is None
    assert user["roles"] == ["system_admin"]
    assert "kb:create" in user["permissions"]
    assert not [p for p in user["permissions"] if p.startswith("documents:")]


def test_department_admin_is_not_a_viewer(client):
    user = client.post("/api/auth/login", json={"username": "hr.admin", "password": "demo123"}).json()["user"]
    assert user["roles"] == ["department_admin"]
    assert not [p for p in user["permissions"] if p.startswith("documents:")]


def test_lan_id_is_case_insensitive(client):
    assert client.post("/api/auth/login", json={"username": " Analyst ", "password": "datahub123"}).status_code == 200


def test_wrong_password_and_unknown_user_get_the_same_answer(client):
    a = client.post("/api/auth/login", json={"username": "analyst", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Incorrect LAN ID or password."}


def test_unknown_user_still_runs_a_password_check(client, monkeypatch):
    """Guards against LAN ID enumeration by timing."""
    import app.services.auth as auth_service

    calls = []
    monkeypatch.setattr(auth_service, "burn_password_check", lambda pw: calls.append(pw))
    client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert calls == ["x"]


def test_lockout_after_five_failures(client):
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "analyst", "password": "bad"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    assert r.status_code == 423
    # Even the right password is refused while locked.
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 423
    assert "Try again in 15 minutes" in r.json()["detail"]


def test_successful_login_resets_failed_count(client):
    client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    with new_session() as db:
        assert db.query(User).filter_by(lan_id="analyst").one().failed_login_count == 0


def test_logout_revokes_the_token(client, login):
    h = login("analyst")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 204
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 401
    assert r.json()["detail"] == "Session ended. Please sign in again."


def test_tampered_token_is_rejected(client, login):
    h = login("analyst")
    token = h["Authorization"].split()[1]
    header, payload, sig = token.split(".")
    claims = _claims(token)
    claims["roles"] = ["system_admin"]
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {header}.{forged}.{sig}"})
    assert r.status_code == 401


def test_missing_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_sign_ins_are_audited(client, login):
    client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    login("analyst")
    with new_session() as db:
        events = [(e.action, e.outcome) for e in db.query(AuditEvent).filter(AuditEvent.action.like("auth.%")).order_by(AuditEvent.id)]
    assert events == [("auth.login", "failure"), ("auth.login", "success")]
