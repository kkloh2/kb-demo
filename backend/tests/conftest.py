import os
import tempfile
from pathlib import Path

# Must be set before the app (and its cached settings) is imported.
_tmp = Path(tempfile.mkdtemp(prefix="datahub-test-"))
DIRECTORY_FILE = _tmp / "ldap-directory.yaml"
os.environ["DATAHUB_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATAHUB_ENVIRONMENT"] = "test"
os.environ["DATAHUB_LDAP_DIRECTORY_FILE"] = str(DIRECTORY_FILE)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import reset_database  # noqa: E402
from app.main import app  # noqa: E402

# The test directory (a stand-in for LDAP / Active Directory), rewritten before every test.
DIRECTORY_YAML = """\
users:
  admin:
    password: admin123
    display_name: Data Hub Admin
    email: admin@datahub.local
    department: Technology
    title: Platform Administrator
  analyst:
    password: datahub123
    display_name: Alex Tan
    email: alex.tan@datahub.local
    department: Risk Management
    title: Data Analyst
"""
PASSWORDS = {"admin": "admin123", "analyst": "datahub123"}


@pytest.fixture
def directory() -> Path:
    """The test directory file. Tests may rewrite it; it is restored before the next test."""
    DIRECTORY_FILE.write_text(DIRECTORY_YAML, encoding="utf-8")
    return DIRECTORY_FILE


@pytest.fixture
def client(directory):
    reset_database()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    """login("analyst") -> auth headers for that directory user."""

    def _login(lan_id: str, password: str | None = None) -> dict[str, str]:
        r = client.post("/api/auth/login", json={"username": lan_id, "password": password or PASSWORDS[lan_id]})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login
