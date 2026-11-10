"""The users module puts a "roles" claim in the token through an auth sign-in hook."""

import base64
import json

from app.auth.service import principal_from_token
from app.db.session import new_session
from app.users import service as users_service
from app.users.service import roles_of


def _sign_in(client) -> str:
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_token_has_an_empty_roles_claim_until_roles_are_designed(client):
    assert _claims(_sign_in(client))["roles"] == []


def test_roles_from_the_lookup_go_into_the_token(client, monkeypatch):
    monkeypatch.setattr(users_service, "lookup_roles", lambda db, lan_id: ["VIEWER", "CHECKER", "VIEWER"])
    assert _claims(_sign_in(client))["roles"] == ["CHECKER", "VIEWER"]


def test_roles_are_read_back_from_the_token(client, monkeypatch):
    monkeypatch.setattr(users_service, "lookup_roles", lambda db, lan_id: ["CHECKER"])
    token = _sign_in(client)
    with new_session() as db:
        principal = principal_from_token(db, token)
    assert roles_of(principal) == {"CHECKER"}
    assert principal.claims == {"roles": ["CHECKER"]}


def test_roles_are_a_snapshot_taken_at_sign_in(client, monkeypatch):
    monkeypatch.setattr(users_service, "lookup_roles", lambda db, lan_id: ["CHECKER"])
    token = _sign_in(client)
    monkeypatch.setattr(users_service, "lookup_roles", lambda db, lan_id: [])
    with new_session() as db:
        assert roles_of(principal_from_token(db, token)) == {"CHECKER"}
