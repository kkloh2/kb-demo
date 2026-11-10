import os
import tempfile

# Must be set before the app (and its cached settings) is imported.
_tmp = tempfile.mkdtemp(prefix="datahub-test-")
os.environ["DATAHUB_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATAHUB_ENVIRONMENT"] = "test"
os.environ["DATAHUB_PASSWORD_HASH_ITERATIONS"] = "1000"  # fast hashing in tests
os.environ["DATAHUB_UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["DATAHUB_MAX_UPLOAD_MB"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import reset_database  # noqa: E402
from app.main import app  # noqa: E402

PASSWORDS = {"admin": "admin123", "analyst": "datahub123"}


@pytest.fixture
def client():
    reset_database()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    """login("risk.maker") -> auth headers for that demo user."""

    def _login(lan_id: str, password: str | None = None) -> dict[str, str]:
        r = client.post(
            "/api/auth/login",
            json={"username": lan_id, "password": password or PASSWORDS.get(lan_id, "demo123")},
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login
