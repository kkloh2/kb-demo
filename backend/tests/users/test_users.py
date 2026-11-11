"""The users module's part in sign-in: it records each person the directory verifies."""

from app.db.session import new_session
from app.users.models import User


def _user(lan_id: str) -> User:
    with new_session() as db:
        return db.query(User).filter_by(lan_id=lan_id).one()


def test_first_sign_in_creates_the_user_from_the_directory(client):
    with new_session() as db:
        assert db.query(User).filter(User.lan_id != "admin").count() == 0  # admin is seeded
    client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    user = _user("analyst")
    assert (user.department, user.display_name, user.email, user.title) == (
        "Risk Management", "Alex Tan", "alex.tan@datahub.local", "Data Analyst",
    )
    assert user.last_login_at is not None


def test_details_are_refreshed_from_the_directory_at_sign_in(client, login, directory):
    login("analyst")
    directory.write_text(directory.read_text().replace("title: Data Analyst", "title: Senior Data Analyst"))
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "datahub123"})
    assert r.json()["user"]["title"] == "Senior Data Analyst"
    assert _user("analyst").title == "Senior Data Analyst"


def test_signing_in_again_keeps_one_record(client, login):
    login("analyst")
    login(" Analyst ", "datahub123")
    with new_session() as db:
        assert db.query(User).filter_by(lan_id="analyst").count() == 1


def test_failed_sign_ins_create_nothing(client):
    client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    client.post("/api/auth/login", json={"username": "analyst", "password": "bad"})
    with new_session() as db:
        assert db.query(User).filter(User.lan_id != "admin").count() == 0  # admin is seeded


# --------------------------------------------------------------------------- seeded system admins


def _system_roles(lan_id):
    from app.users import service

    with new_session() as db:
        return service.system_roles(db, service.get_by_lan_id(db, lan_id))


def test_bootstrap_admin_is_seeded_before_anyone_signs_in(client):
    with new_session() as db:
        admin = db.query(User).filter_by(lan_id="admin").one()
        assert (admin.display_name, admin.email, admin.last_login_at) == ("admin", "admin@pending.invalid", None)
    assert {r.value for r in _system_roles("admin")} == {"PUBLIC", "SYSTEM_ADMIN"}


def test_first_sign_in_fills_in_the_seeded_admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.json()["user"]["email"] == "admin@datahub.local"
    with new_session() as db:
        assert db.query(User).filter_by(lan_id="admin").one().display_name == "Data Hub Admin"


def _seed():
    from app.users.seed import seed_system_admins

    with new_session() as db:
        created = seed_system_admins(db)
        db.commit()
    return created


def test_seeding_is_idempotent(client):
    assert _seed() == []
    with new_session() as db:
        assert db.query(User).filter_by(lan_id="admin").count() == 1


def test_removed_system_admin_stays_removed_while_another_exists(client, login):
    """A system admin takes SYSTEM_ADMIN away from the bootstrap admin: a restart must not undo it."""
    from app.users import service

    login("analyst")
    with new_session() as db:  # analyst becomes a system admin, then removes admin's role
        user = service.get_by_lan_id(db, "analyst")
        service.upsert_user(db, "admin", "analyst", display_name=user.display_name, email=user.email,
                            system_roles=["PUBLIC", "SYSTEM_ADMIN"], org_unit_roles={})
    with new_session() as db:
        admin = service.get_by_lan_id(db, "admin")
        service.upsert_user(db, "analyst", "admin", display_name=admin.display_name, email=admin.email,
                            system_roles=["PUBLIC"], org_unit_roles={})
    assert _seed() == []
    assert {r.value for r in _system_roles("admin")} == {"PUBLIC"}
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.json()["access_token"] and "SYSTEM_ADMIN" not in _system_roles("admin")


def test_deleted_bootstrap_admin_stays_deleted_while_another_exists(client, login):
    from app.users import service

    login("analyst")
    with new_session() as db:
        user = service.get_by_lan_id(db, "analyst")
        service.upsert_user(db, "admin", "analyst", display_name=user.display_name, email=user.email,
                            system_roles=["PUBLIC", "SYSTEM_ADMIN"], org_unit_roles={})
    with new_session() as db:
        service.delete_user(db, "analyst", "admin")
    assert _seed() == []
    with new_session() as db:
        assert service.get_by_lan_id(db, "admin") is None


def test_system_admin_is_restored_when_nobody_has_it(client):
    """Nobody can sign in to manage roles any more: seeding brings the bootstrap admin back."""
    from app.users.models import UserSystemRole

    with new_session() as db:
        db.query(UserSystemRole).filter_by(role_code="SYSTEM_ADMIN").delete()
        db.commit()
    assert _seed() == []  # admin already existed; only the role comes back
    assert {r.value for r in _system_roles("admin")} == {"PUBLIC", "SYSTEM_ADMIN"}


def test_every_bootstrap_lan_id_is_seeded(client, monkeypatch):
    from app.core.config import get_settings
    from app.users import seed
    from app.users.models import UserSystemRole

    with new_session() as db:  # nobody is a system admin, so seeding acts
        db.query(UserSystemRole).filter_by(role_code="SYSTEM_ADMIN").delete()
        db.commit()
    settings = get_settings().model_copy(update={"bootstrap_system_admins": ["admin", " Ops.Lead "]})
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    with new_session() as db:
        assert seed.seed_system_admins(db) == ["ops.lead"]
        db.commit()
    assert {r.value for r in _system_roles("ops.lead")} == {"PUBLIC", "SYSTEM_ADMIN"}


def test_deleted_bootstrap_admin_signs_back_in_without_system_admin(client, login):
    """Regression: DELETE /api/users/admin (by another system admin), a server restart, then admin
    signs in again. They come back as a new user with PUBLIC only, not SYSTEM_ADMIN."""
    import base64
    import json

    from app.db.session import init_db

    admin = login("admin")
    login("analyst")
    r = client.put("/api/users/analyst", headers=admin, json={
        "display_name": "Alex Tan", "email": "alex.tan@datahub.local",
        "system_roles": ["PUBLIC", "SYSTEM_ADMIN"], "org_unit_roles": {}})
    assert r.status_code == 200
    analyst = login("analyst")  # new token with SYSTEM_ADMIN
    assert client.delete("/api/users/admin", headers=analyst).status_code == 204

    init_db()  # a server restart (uvicorn --reload restarts on every code change)
    token = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
    payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["system_roles"] == ["PUBLIC"]
