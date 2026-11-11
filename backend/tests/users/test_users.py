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


def test_seeding_is_idempotent_and_restores_system_admin(client):
    from app.users.models import UserSystemRole
    from app.users.seed import seed_system_admins

    with new_session() as db:
        admin = db.query(User).filter_by(lan_id="admin").one()
        db.query(UserSystemRole).filter_by(user_id=admin.id, role_code="SYSTEM_ADMIN").delete()
        db.commit()
    with new_session() as db:
        assert seed_system_admins(db) == []  # nobody new
        db.commit()
    with new_session() as db:
        assert db.query(User).filter_by(lan_id="admin").count() == 1
    assert {r.value for r in _system_roles("admin")} == {"PUBLIC", "SYSTEM_ADMIN"}  # restored


def test_every_bootstrap_lan_id_is_seeded(client, monkeypatch):
    from app.core.config import get_settings
    from app.users import seed

    settings = get_settings().model_copy(update={"bootstrap_system_admins": ["admin", " Ops.Lead "]})
    monkeypatch.setattr(seed, "get_settings", lambda: settings)
    with new_session() as db:
        assert seed.seed_system_admins(db) == ["ops.lead"]
        db.commit()
    assert {r.value for r in _system_roles("ops.lead")} == {"PUBLIC", "SYSTEM_ADMIN"}
