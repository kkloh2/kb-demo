"""The users module's part in sign-in: it records each person the directory verifies."""

from app.db.session import new_session
from app.users.models import User


def _user(lan_id: str) -> User:
    with new_session() as db:
        return db.query(User).filter_by(lan_id=lan_id).one()


def test_first_sign_in_creates_the_user_from_the_directory(client):
    with new_session() as db:
        assert db.query(User).count() == 0
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
        assert db.query(User).count() == 0
