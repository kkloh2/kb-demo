import os
import tempfile
from pathlib import Path

# Must be set before the app (and its cached settings) is imported.
_tmp = Path(tempfile.mkdtemp(prefix="datahub-test-"))
DIRECTORY_FILE = _tmp / "ldap-directory.yaml"
os.environ["DATAHUB_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DATAHUB_ENVIRONMENT"] = "test"
os.environ["DATAHUB_LDAP_DIRECTORY_FILE"] = str(DIRECTORY_FILE)
os.environ["DATAHUB_UPLOAD_DIR"] = str(_tmp / "uploads")
os.environ["DATAHUB_MAX_UPLOAD_MB"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import reset_database  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import GROUPS_FLOW, set_roles, use_workflow

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
  ben:
    password: pw
    display_name: Ben Ong
    email: ben@datahub.local
    department: Risk Management
    title: Doc Hub Admin
  andy:
    password: pw
    display_name: Andy Koh
    email: andy@datahub.local
    department: Risk Management
    title: Doc Hub Admin
  dana:
    password: pw
    display_name: Dana Lim
    email: dana@datahub.local
    department: Risk Management
    title: Repository Admin
  marcus:
    password: pw
    display_name: Marcus Lee
    email: marcus@datahub.local
    department: Risk Management
    title: Credit Risk Analyst
  mia:
    password: pw
    display_name: Mia Tan
    email: mia@datahub.local
    department: Risk Management
    title: Credit Risk Analyst
  cara:
    password: pw
    display_name: Cara Wong
    email: cara@datahub.local
    department: Risk Management
    title: Credit Risk Manager
  chris:
    password: pw
    display_name: Chris Goh
    email: chris@datahub.local
    department: Risk Management
    title: Credit Risk Manager
  eve:
    password: pw
    display_name: Eve Ng
    email: eve@datahub.local
    department: Risk Management
    title: Risk Associate
  ivan:
    password: pw
    display_name: Ivan Teo
    email: ivan@datahub.local
    department: Risk Management
    title: Internal Auditor
  grace:
    password: pw
    display_name: Grace Chua
    email: grace@datahub.local
    department: Risk Management
    title: Compliance Officer
  outsider:
    password: pw
    display_name: Oscar Sim
    email: outsider@datahub.local
    department: Risk Management
    title: Associate
"""
PASSWORDS = {"admin": "admin123", "analyst": "datahub123"}  # everyone else: "pw"


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
        r = client.post("/api/auth/login", json={"username": lan_id, "password": password or PASSWORDS.get(lan_id, "pw")})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def doc_hub(client, login):
    """The platform admin creates the DOC_HUB source system and its two-level hierarchy
    (ROOT -> DOC_REPO). Returns the admin's headers."""
    admin = login("admin")
    assert client.post("/api/sources", json={"code": "DOC_HUB", "name": "Document repositories"},
                       headers=admin).status_code == 201
    r = client.post("/api/sources/DOC_HUB/hierarchy", json={"name": "Doc Hub", "levels": ["DOC_REPO"]}, headers=admin)
    assert r.status_code == 201, r.text
    return admin


@pytest.fixture
def hub(client, login, doc_hub):
    """Doc Hub set up the way the design walks through it:

        PLATFORM root   admins: admin (bootstrap); users: everyone (VIEWER, first sign-in)
        DOC_HUB root    created by the platform admin (doc_hub); admins: admin (a platform admin),
                        ben and andy; users: everyone (VIEWER)
        Loan Risks      created by ben (OWNER); dana ADMIN, marcus + mia MAKER, cara + chris CHECKER, eve VIEWER
        teams           ivan in AUDIT, grace in COMPLIANCE (no grants yet)

    Returns {lan id: auth headers, ..., "repo": Loan Risks' id}. Headers are fresh (taken after
    every root role was set)."""
    names = ["admin", "analyst", "ben", "andy", "dana", "marcus", "mia", "cara", "chris", "eve", "ivan", "grace", "outsider"]
    for n in names:
        login(n)
    h_admin = login("admin")
    for n in ("ben", "andy"):
        r = client.put(f"/api/sources/DOC_HUB/groups/ADMINS/members/{n}", json={"roles": ["ADMIN"]}, headers=h_admin)
        assert r.status_code == 200, r.text
    for team, people in {"AUDIT": ["ivan"], "COMPLIANCE": ["grace"]}.items():
        assert client.put(f"/api/teams/{team}/members", json={"lan_ids": people}, headers=h_admin).status_code == 200
    h = {n: login(n) for n in names}
    r = client.post("/api/doc-repos", json={"name": "Loan Risks", "description": "Credit risk policies",
                                            "metadata": [{"label": "Department", "value": "Risk Management"},
                                                         {"label": "Country", "value": "Singapore"}]},
                    headers=h["ben"])
    assert r.status_code == 201, r.text
    repo = r.json()["id"]
    for n, roles in {"dana": ["ADMIN"], "marcus": ["MAKER"], "mia": ["MAKER"], "cara": ["CHECKER"],
                     "chris": ["CHECKER"], "eve": ["VIEWER"]}.items():
        r = set_roles(client, repo, n, roles, h["ben"])
        assert r.status_code == 200, r.text
    use_workflow(client, repo, GROUPS_FLOW, h_admin, h["ben"])  # its groups are Makers and Checkers
    return {**h, "repo": repo}
