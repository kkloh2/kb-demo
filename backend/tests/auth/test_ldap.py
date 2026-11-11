"""The directory module on its own: LAN ID + password -> (department, display_name, email, title)."""

import pytest

from app.auth import ldap
from app.auth.errors import DirectoryUnavailable


def test_returns_the_directory_tuple(directory):
    user = ldap.authenticate("analyst", "datahub123")
    assert user == ("Risk Management", "Alex Tan", "alex.tan@datahub.local", "Data Analyst")
    department, display_name, email, title = user
    assert (user.department, user.title) == (department, title)


def test_lan_id_is_case_insensitive(directory):
    assert ldap.authenticate(" ANALYST ", "datahub123") is not None


def test_password_is_compared_as_is(directory):
    assert ldap.authenticate("analyst", "DATAHUB123") is None
    assert ldap.authenticate("analyst", "datahub123 ") is None


def test_wrong_password_and_unknown_user_both_return_none(directory):
    assert ldap.authenticate("analyst", "nope") is None
    assert ldap.authenticate("nobody", "nope") is None


def test_missing_file_means_directory_unavailable(directory):
    directory.unlink()
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "datahub123")


@pytest.mark.parametrize("content", ["users: [", "- just a list", "people: {}"])
def test_unreadable_file_means_directory_unavailable(directory, content):
    directory.write_text(content)
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "datahub123")


def test_entry_missing_a_field_means_directory_unavailable(directory):
    directory.write_text("users:\n  analyst:\n    password: x\n    display_name: Alex Tan\n")
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "x")


def test_edits_apply_without_restart(directory):
    directory.write_text(directory.read_text().replace("datahub123", "changed"))
    assert ldap.authenticate("analyst", "datahub123") is None
    assert ldap.authenticate("analyst", "changed") is not None


# --------------------------------------------------------------------------- real LDAP (ldap3)
#
# These run ldap3's real client code against its in-memory mock server (MOCK_SYNC), which checks
# simple binds against each entry's userPassword.

from ldap3 import MOCK_SYNC, Connection, Server  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402

PEOPLE = "ou=people,dc=example,dc=com"


@pytest.fixture
def ldap_dir(monkeypatch):
    """Switch the directory to "ldap" against a mock server; returns add(lan_id, **attributes)."""
    settings = get_settings().model_copy(update={
        "directory": "ldap",
        "ldap_server_url": "ldap://mock.example.com",
        "ldap_search_base": PEOPLE,
        "ldap_bind_format": "cn={lan_id}," + PEOPLE,
        "ldap_search_filter": "(uid={lan_id})",
    })
    server = Server("mock.example.com")
    monkeypatch.setattr(ldap, "get_settings", lambda: settings)
    monkeypatch.setattr(ldap, "_server", lambda: server)
    monkeypatch.setattr(ldap, "_CLIENT_STRATEGY", MOCK_SYNC)
    admin = Connection(server, client_strategy=MOCK_SYNC)

    def add(lan_id: str, password: str = "s3cret", **attributes):
        admin.strategy.add_entry(f"cn={lan_id},{PEOPLE}", {
            "objectClass": ["person"], "uid": lan_id, "userPassword": password, **attributes,
        })

    add.settings = settings
    return add


ALEX = {"displayName": "Alex Tan", "mail": "Alex.Tan@example.com", "department": "Risk Management",
        "title": "Data Analyst"}


def test_ldap_returns_the_tuple_from_the_entry(ldap_dir):
    ldap_dir("analyst", **ALEX)
    assert ldap.authenticate(" Analyst ", "s3cret") == (
        "Risk Management", "Alex Tan", "alex.tan@example.com", "Data Analyst",
    )


@pytest.mark.parametrize("lan_id, password", [("analyst", "wrong"), ("nobody", "s3cret")])
def test_ldap_wrong_password_and_unknown_user_return_none(ldap_dir, lan_id, password):
    ldap_dir("analyst", **ALEX)
    assert ldap.authenticate(lan_id, password) is None


def test_ldap_empty_password_never_binds(ldap_dir, monkeypatch):
    """LDAP accepts a name with no password as an unauthenticated bind; we must never send one."""
    ldap_dir("analyst", **ALEX)
    monkeypatch.setattr(ldap, "Connection", lambda *a, **k: pytest.fail("connected with an empty password"))
    assert ldap.authenticate("analyst", "") is None


@pytest.mark.parametrize("lan_id", ["analyst)(uid=*", "*", "cn=admin,dc=x", "a b", "x" * 65])
def test_ldap_odd_lan_ids_never_reach_the_directory(ldap_dir, monkeypatch, lan_id):
    monkeypatch.setattr(ldap, "Connection", lambda *a, **k: pytest.fail(f"connected for {lan_id!r}"))
    assert ldap.authenticate(lan_id, "s3cret") is None


def test_ldap_optional_attributes_may_be_missing(ldap_dir):
    ldap_dir("analyst", mail="alex@example.com")
    assert ldap.authenticate("analyst", "s3cret") == ("", "analyst", "alex@example.com", "")


def test_ldap_email_falls_back_to_user_principal_name(ldap_dir):
    ldap_dir("analyst", displayName="Alex Tan", userPrincipalName="analyst@corp.example.com")
    assert ldap.authenticate("analyst", "s3cret").email == "analyst@corp.example.com"


def test_ldap_entry_without_any_email_is_a_directory_problem(ldap_dir):
    ldap_dir("analyst", displayName="Alex Tan")
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "s3cret")


def test_ldap_entry_not_found_after_bind_is_a_directory_problem(ldap_dir, monkeypatch):
    """The password was right but the search settings can't find the person: misconfiguration."""
    ldap_dir("analyst", **ALEX)
    wrong_base = ldap_dir.settings.model_copy(update={"ldap_search_base": "ou=elsewhere,dc=example,dc=com"})
    monkeypatch.setattr(ldap, "get_settings", lambda: wrong_base)
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "s3cret")


def test_ldap_server_down_is_directory_unavailable(monkeypatch):
    settings = get_settings().model_copy(update={
        "directory": "ldap", "ldap_server_url": "ldap://127.0.0.1:1", "ldap_search_base": PEOPLE,
        "ldap_timeout_seconds": 1,
    })
    monkeypatch.setattr(ldap, "get_settings", lambda: settings)
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "s3cret")


def test_sign_in_through_ldap_end_to_end(client, ldap_dir):
    ldap_dir("analyst", **ALEX)
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "s3cret"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["display_name"] == "Alex Tan"
    r = client.post("/api/auth/login", json={"username": "analyst", "password": "wrong"})
    assert (r.status_code, r.json()["detail"]) == (401, "Incorrect LAN ID or password.")


# --------------------------------------------------------------------------- settings checks


def test_ldap_settings_must_be_complete():
    with pytest.raises(ValueError, match="DATAHUB_LDAP_SERVER_URL"):
        Settings(directory="ldap", ldap_search_base=PEOPLE)
    with pytest.raises(ValueError, match="DATAHUB_LDAP_SEARCH_BASE"):
        Settings(directory="ldap", ldap_server_url="ldaps://ad.example.com")
    with pytest.raises(ValueError, match="lan_id"):
        Settings(directory="ldap", ldap_server_url="ldaps://ad.example.com", ldap_search_base=PEOPLE,
                 ldap_bind_format="CORP\\someone")


def test_plain_ldap_is_refused_in_production():
    production = {"environment": "production", "jwt_secret": "x" * 40, "directory": "ldap",
                  "ldap_search_base": PEOPLE}
    with pytest.raises(ValueError, match="unencrypted"):
        Settings(**production, ldap_server_url="ldap://ad.example.com")
    Settings(**production, ldap_server_url="ldaps://ad.example.com")
    Settings(**production, ldap_server_url="ldap://ad.example.com", ldap_start_tls=True)
