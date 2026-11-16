"""Documents: upload, visibility, metadata (inherited, overridden, removed, own; frozen at approval)."""

import pytest

from app.core.config import get_settings
from tests.helpers import set_roles

PDF = b"%PDF-1.4 demo"


def upload(client, hub, files=(("policy.pdf", PDF),), paths=None, who="marcus"):
    data = {"paths": paths} if paths is not None else None
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents", headers=hub[who],
                    files=[("files", (n, b, "application/pdf")) for n, b in files], data=data)
    return r


def docs(client, hub, who):
    return {d["filename"]: d for d in client.get(f"/api/doc-repos/{hub['repo']}/documents", headers=hub[who]).json()}


def meta(doc):
    return {m["label"]: (m["value"], m["state"]) for m in doc["metadata"]}


def test_maker_uploads_drafts_carrying_the_repositorys_metadata(client, hub):
    r = upload(client, hub)
    assert r.status_code == 201
    d = r.json()[0]
    assert d["status"] == "draft" and d["maker"]["lan_id"] == "marcus"
    assert meta(d) == {"Department": ("Risk Management", "inherited"), "Country": ("Singapore", "inherited")}
    assert d["metadata"][0]["from_node"] == "Loan Risks"
    assert d["actions"] == {"edit": True, "submit": True, "delete": True}


def test_folder_upload_keeps_the_structure_and_renames_duplicates(client, hub):
    upload(client, hub, [("a.pdf", PDF), ("a.pdf", PDF)], paths=["Policies/2026/a.pdf", "Policies/2026/a.pdf"])
    names = sorted((d["folder"], d["filename"]) for d in docs(client, hub, "marcus").values())
    assert names == [("Policies/2026", "a (2).pdf"), ("Policies/2026", "a.pdf")]


@pytest.mark.parametrize("files, message", [
    ([("x.exe", PDF)], "can't be uploaded"),
    ([("empty.pdf", b"")], "is empty"),
    ([("big.pdf", b"x" * (1024 * 1024 + 1))], "larger than"),
])
def test_bad_files_are_refused(client, hub, files, message):
    r = upload(client, hub, files)
    assert r.status_code == 422 and message in r.json()["detail"]
    assert docs(client, hub, "marcus") == {}


@pytest.mark.parametrize("who", ["cara", "eve", "dana", "ben", "outsider"])
def test_only_makers_upload(client, hub, who):
    assert upload(client, hub, who=who).status_code == 403


def test_files_are_stored_by_document_id(client, hub):
    d = upload(client, hub).json()[0]
    assert (get_settings().upload_dir / "doc-repos" / hub["repo"] / d["id"] / "policy.pdf").read_bytes() == PDF
    r = client.get(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}/download", headers=hub["marcus"])
    assert r.content == PDF


def test_who_sees_which_documents(client, hub):
    d = upload(client, hub).json()[0]
    assert "policy.pdf" in docs(client, hub, "mia")  # makers: every status
    for who in ("cara", "eve", "ben"):
        assert docs(client, hub, who) == {}
    assert client.get(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}", headers=hub["eve"]).status_code == 404
    client.post(f"/api/doc-repos/{hub['repo']}/documents/submit", json={"ids": [d["id"]]}, headers=hub["marcus"])
    assert docs(client, hub, "cara")["policy.pdf"]["status"] == "pending_approval"  # checkers: submitted
    assert docs(client, hub, "eve") == {}  # viewers: approved only


def test_maker_overrides_removes_and_adds_metadata(client, hub):
    d = upload(client, hub).json()[0]
    fields = {m["label"]: m["field_id"] for m in d["metadata"]}
    body = {"inherited": [{"field_id": fields["Country"], "state": "override", "value": "Malaysia"},
                          {"field_id": fields["Department"], "state": "remove"}],
            "own": [{"label": "Reviewed by legal", "value": "Yes"}]}
    r = client.put(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}/metadata", json=body, headers=hub["marcus"])
    assert r.status_code == 200, r.text
    m = {x["label"]: x for x in r.json()["metadata"]}
    assert (m["Country"]["value"], m["Country"]["state"], m["Country"]["inherited_value"]) == ("Malaysia", "overridden", "Singapore")
    assert (m["Department"]["value"], m["Department"]["state"]) == (None, "removed")
    assert (m["Reviewed by legal"]["value"], m["Reviewed by legal"]["state"]) == ("Yes", "own")
    # back to the repository's value
    body = {"inherited": [{"field_id": fields["Country"], "state": "inherit"}], "own": []}
    r = client.put(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}/metadata", json=body, headers=hub["marcus"])
    assert meta(r.json()) == {"Department": (None, "removed"), "Country": ("Singapore", "inherited")}


@pytest.mark.parametrize("own", [[{"label": "Country", "value": "x"}],
                                 [{"label": "A", "value": "1"}, {"label": "a", "value": "2"}]])
def test_own_fields_cannot_clash(client, hub, own):
    d = upload(client, hub).json()[0]
    r = client.put(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}/metadata", json={"own": own},
                   headers=hub["marcus"])
    assert r.status_code == 422


def test_repository_changes_reach_unapproved_documents_but_not_overrides(client, hub):
    a, b = upload(client, hub, [("a.pdf", PDF), ("b.pdf", PDF)]).json()
    country = next(m["field_id"] for m in b["metadata"] if m["label"] == "Country")
    client.put(f"/api/doc-repos/{hub['repo']}/documents/{b['id']}/metadata",
               json={"inherited": [{"field_id": country, "state": "override", "value": "Japan"}]}, headers=hub["marcus"])
    client.put(f"/api/doc-repos/{hub['repo']}/metadata", headers=hub["ben"], json=[
        {"label": "Department", "value": "Risk Management"}, {"label": "Country", "value": "SG"},
        {"label": "Product", "value": "Loans"}])
    now = docs(client, hub, "marcus")
    assert meta(now["a.pdf"]) == {"Department": ("Risk Management", "inherited"), "Country": ("SG", "inherited"),
                                  "Product": ("Loans", "inherited")}
    assert meta(now["b.pdf"])["Country"] == ("Japan", "overridden")


def test_a_removed_repository_field_stays_on_documents_that_changed_it(client, hub):
    d = upload(client, hub).json()[0]
    country = next(m["field_id"] for m in d["metadata"] if m["label"] == "Country")
    client.put(f"/api/doc-repos/{hub['repo']}/documents/{d['id']}/metadata",
               json={"inherited": [{"field_id": country, "state": "override", "value": "Japan"}]}, headers=hub["marcus"])
    client.put(f"/api/doc-repos/{hub['repo']}/metadata", json=[{"label": "Department", "value": "Risk"}], headers=hub["ben"])
    assert meta(docs(client, hub, "marcus")["policy.pdf"]) == {"Department": ("Risk", "inherited"), "Country": ("Japan", "own")}


def test_soft_delete_hides_documents(client, hub):
    d = upload(client, hub).json()[0]
    r = client.post(f"/api/doc-repos/{hub['repo']}/documents/delete", json={"ids": [d["id"]]}, headers=hub["marcus"])
    assert r.status_code == 200 and r.json()["skipped"] == []
    assert docs(client, hub, "marcus") == {}
    assert (get_settings().upload_dir / "doc-repos" / hub["repo"] / d["id"] / "policy.pdf").exists()  # kept


def test_ids_from_elsewhere_are_refused(client, hub):
    d = upload(client, hub).json()[0]
    other = client.post("/api/doc-repos", json={"name": "Other"}, headers=hub["andy"]).json()
    set_roles(client, other['id'], "marcus", ["MAKER"], hub["andy"])
    r = client.post(f"/api/doc-repos/{other['id']}/documents/submit", json={"ids": [d["id"]]}, headers=hub["marcus"])
    assert r.status_code == 404
