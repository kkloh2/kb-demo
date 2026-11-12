"""Documents: upload (files and folders), metadata, submit, review (bulk), visibility, delete."""

import pytest

from app.core.config import get_settings
from app.db.session import new_session
from app.users import service as users

EXTRA_DIRECTORY_USERS = """
  risk.admin:
    password: demo123
    display_name: Rita Lim
    email: rita.lim@datahub.local
    department: Risk Management
    title: Risk Lead
  maker:
    password: demo123
    display_name: Marcus Lee
    email: marcus.lee@datahub.local
    department: Risk Management
    title: Analyst
  maker2:
    password: demo123
    display_name: Mia Tan
    email: mia.tan@datahub.local
    department: Risk Management
    title: Analyst
  checker:
    password: demo123
    display_name: Chloe Wong
    email: chloe.wong@datahub.local
    department: Risk Management
    title: Manager
  viewer:
    password: demo123
    display_name: Victor Ng
    email: victor.ng@datahub.local
    department: Risk Management
    title: Associate
  dept.viewer:
    password: demo123
    display_name: Dee Viewer
    email: dee.viewer@datahub.local
    department: Risk Management
    title: Associate
"""

DOC_REPO = {"name": "Card Policies",
            "department_metadata": {"business_unit": "Consumer Banking", "country": "Singapore"}}
PDF = b"%PDF-1.4 demo"


@pytest.fixture
def ctx(client, directory, login):
    """A RISK doc-repo with a maker, a second maker, a checker and a viewer; a department viewer
    with no doc-repo role. Returns {name: headers, "pid": doc-repo id}."""
    directory.write_text(directory.read_text() + EXTRA_DIRECTORY_USERS)
    names = ["risk.admin", "maker", "maker2", "checker", "viewer", "dept.viewer"]
    login("admin")
    for n in names:
        login(n, "demo123")
    with new_session() as db:
        for n, org in {"risk.admin": {"RISK": ["DEPARTMENT_ADMIN"]}, "dept.viewer": {"RISK": ["VIEWER"]}}.items():
            u = users.get_by_lan_id(db, n)
            users.upsert_user(db, "admin", n, display_name=u.display_name, email=u.email,
                              system_roles=["PUBLIC"], org_unit_roles=org)
    h = {n: login(n, "demo123") for n in names}
    pid = client.post("/api/departments/RISK/doc-repos", json=DOC_REPO, headers=h["risk.admin"]).json()["id"]
    for n, roles in {"maker": ["MAKER"], "maker2": ["MAKER"], "checker": ["CHECKER"], "viewer": ["VIEWER"]}.items():
        assert client.put(f"/api/doc-repos/{pid}/members/{n}", json={"roles": roles},
                          headers=h["risk.admin"]).status_code == 200
    return {**h, "pid": pid}


def _upload(client, ctx, files, paths=None, who="maker"):
    data = {"paths": paths} if paths is not None else None
    return client.post(f"/api/doc-repos/{ctx['pid']}/documents", headers=ctx[who],
                       files=[("files", (name, body, "application/pdf")) for name, body in files], data=data)


def _ids(r):
    return [d["id"] for d in r.json()]


def _list(client, ctx, who):
    r = client.get(f"/api/doc-repos/{ctx['pid']}/documents", headers=ctx[who])
    assert r.status_code == 200, r.text
    return r.json()["documents"]


def _post(client, ctx, action, body, who):
    return client.post(f"/api/doc-repos/{ctx['pid']}/documents/{action}", json=body, headers=ctx[who])


# --------------------------------------------------------------------------- upload


def test_maker_uploads_files_as_drafts_with_the_doc_repos_base_metadata(client, ctx):
    r = _upload(client, ctx, [("policy.pdf", PDF), ("terms.docx", b"docx")])
    assert r.status_code == 201
    docs = r.json()
    assert [(d["filename"], d["status"], d["folder"]) for d in docs] == [
        ("policy.pdf", "draft", ""), ("terms.docx", "draft", "")]
    # an empty department became the department's name
    assert docs[0]["department_metadata"] == {"department": "Risk Management", "business_unit": "Consumer Banking",
                                              "country": "Singapore"}
    assert docs[0]["department_overrides"] == []
    assert docs[0]["maker"] == {"lan_id": "maker", "display_name": "Marcus Lee"}
    assert docs[0]["actions"] == {"edit": True, "submit": True, "review": False, "delete": True}


def test_folder_upload_keeps_the_structure(client, ctx):
    r = _upload(client, ctx, [("a.pdf", PDF), ("b.pdf", PDF), ("c.pdf", PDF)],
                paths=["Policies/2026/a.pdf", "Policies/b.pdf", "../../etc/c.pdf"])
    assert [(d["folder"], d["filename"]) for d in r.json()] == [
        ("Policies/2026", "a.pdf"), ("Policies", "b.pdf"), ("etc", "c.pdf")]  # ".." is dropped


def test_files_are_stored_by_document_id_under_the_doc_repo(client, ctx):
    doc = _upload(client, ctx, [("policy.pdf", PDF)], paths=["Deep/Folder/policy.pdf"]).json()[0]
    stored = get_settings().upload_dir / "doc-repos" / str(ctx["pid"]) / str(doc["id"]) / "policy.pdf"
    assert stored.read_bytes() == PDF
    r = client.get(f"/api/doc-repos/{ctx['pid']}/documents/{doc['id']}/download", headers=ctx["maker"])
    assert (r.status_code, r.content) == (200, PDF)
    assert "policy.pdf" in r.headers["content-disposition"]


def test_same_name_in_the_same_folder_is_renamed(client, ctx):
    _upload(client, ctx, [("policy.pdf", PDF)])
    assert _upload(client, ctx, [("policy.pdf", PDF)]).json()[0]["filename"] == "policy (2).pdf"


@pytest.mark.parametrize("files, message", [
    ([("virus.exe", b"MZ")], ".exe"),
    ([("empty.pdf", b"")], "empty"),
    ([("big.pdf", b"x" * (1024 * 1024 + 1))], "larger than 1 MB"),
])
def test_bad_files_are_refused_and_nothing_is_stored(client, ctx, files, message):
    r = _upload(client, ctx, [("ok.pdf", PDF), *files])
    assert r.status_code == 422
    assert message in r.json()["detail"]
    assert _list(client, ctx, "maker") == []


@pytest.mark.parametrize("who", ["checker", "viewer", "risk.admin", "dept.viewer"])
def test_only_doc_repo_makers_upload(client, ctx, who):
    assert _upload(client, ctx, [("policy.pdf", PDF)], who=who).status_code == 403


# --------------------------------------------------------------------------- who sees what


def test_visibility_by_role_and_status(client, ctx):
    ids = _ids(_upload(client, ctx, [("draft.pdf", PDF), ("pending.pdf", PDF), ("approved.pdf", PDF)]))
    _post(client, ctx, "submit", {"ids": ids[1:]}, "maker")
    _post(client, ctx, "review", {"ids": [ids[2]], "decision": "approve"}, "checker")
    seen = lambda who: sorted(d["filename"] for d in _list(client, ctx, who))  # noqa: E731
    assert seen("maker") == ["approved.pdf", "draft.pdf", "pending.pdf"]
    assert seen("maker2") == ["approved.pdf", "draft.pdf", "pending.pdf"]  # makers share the doc-repo
    assert seen("checker") == ["approved.pdf", "pending.pdf"]  # no drafts
    assert seen("viewer") == ["approved.pdf"]
    assert seen("risk.admin") == ["approved.pdf"]  # the department admin is a viewer
    assert client.get(f"/api/doc-repos/{ctx['pid']}/documents", headers=ctx["dept.viewer"]).status_code == 403
    # hidden documents answer 404, not 403, so drafts don't leak
    assert client.get(f"/api/doc-repos/{ctx['pid']}/documents/{ids[0]}", headers=ctx["viewer"]).status_code == 404


def test_document_count_follows_what_the_caller_may_see(client, ctx):
    ids = _ids(_upload(client, ctx, [("draft.pdf", PDF), ("pending.pdf", PDF), ("approved.pdf", PDF)]))
    _post(client, ctx, "submit", {"ids": ids[1:]}, "maker")
    _post(client, ctx, "review", {"ids": [ids[2]], "decision": "approve"}, "checker")

    def count(who):
        listed = client.get("/api/doc-repos", headers=ctx[who]).json()
        one = client.get(f"/api/doc-repos/{ctx['pid']}", headers=ctx[who]).json()
        assert [p["document_count"] for p in listed] == [one["document_count"]]
        return one["document_count"]

    assert count("maker") == 3
    assert count("checker") == 2  # no drafts
    assert count("viewer") == 1
    assert count("risk.admin") == 1
    assert count("dept.viewer") == 0  # sees the doc-repo, not its documents


# --------------------------------------------------------------------------- metadata


REPO_META = [
    {"key": "Product code", "value": ""},
    {"key": "Card tier", "value": "Classic"},
]


def _set_repo_meta(client, ctx, pairs=REPO_META, who="risk.admin"):
    return client.put(f"/api/doc-repos/{ctx['pid']}/repository-metadata", json=pairs, headers=ctx[who])


def _meta(client, ctx, doc_id, dept=None, repo=None, extra=None, who="maker"):
    body = {"department_metadata": dept or DEPT_META, "repository_metadata": repo or {}, "extra": extra or {}}
    return client.put(f"/api/doc-repos/{ctx['pid']}/documents/{doc_id}/metadata", json=body, headers=ctx[who])


DEPT_META = {"department": "Risk Management", **DOC_REPO["department_metadata"]}


def test_department_admin_sets_repository_metadata_as_key_value_pairs(client, ctx):
    r = _set_repo_meta(client, ctx, [{"key": "  Product   code ", "value": " VISA "}, {"key": "Card tier"}])
    assert r.status_code == 200
    assert r.json() == [{"key": "Product code", "value": "VISA"}, {"key": "Card tier", "value": ""}]
    shown = client.get(f"/api/doc-repos/{ctx['pid']}", headers=ctx["dept.viewer"]).json()
    assert shown["repository_metadata"] == r.json()
    assert _set_repo_meta(client, ctx, []).json() == []
    assert _set_repo_meta(client, ctx, who="maker").status_code == 403


@pytest.mark.parametrize("pairs", [
    [{"key": "Tier"}, {"key": "tier"}],  # the same key twice
    [{"key": "Country"}],  # department metadata has it
    [{"key": "business unit"}],
    [{"key": ""}],
])
def test_bad_repository_metadata(client, ctx, pairs):
    assert _set_repo_meta(client, ctx, pairs).status_code == 422


def test_documents_start_with_the_repository_values_and_makers_change_them(client, ctx):
    _set_repo_meta(client, ctx)
    doc_id = _ids(_upload(client, ctx, [("policy.pdf", PDF)]))[0]
    doc = client.get(f"/api/doc-repos/{ctx['pid']}/documents/{doc_id}", headers=ctx["maker"]).json()
    assert (doc["repository_metadata"], doc["repository_overrides"]) == ({"Card tier": "Classic"}, [])
    r = _meta(client, ctx, doc_id, dept={**DEPT_META, "business_unit": "Premier Banking"},
              repo={"Product code": "VISA-PLAT", "Card tier": "Platinum"}, extra={"Reviewed by legal": "Yes"})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["department_metadata"]["business_unit"] == "Premier Banking"
    assert doc["department_overrides"] == ["business_unit"]
    assert doc["repository_metadata"] == {"Card tier": "Platinum", "Product code": "VISA-PLAT"}
    assert doc["repository_overrides"] == ["Product code", "Card tier"]
    assert doc["extra"] == {"Reviewed by legal": "Yes"}
    listed = client.get(f"/api/doc-repos/{ctx['pid']}/documents", headers=ctx["maker"]).json()
    assert listed["repository_metadata"] == REPO_META


@pytest.mark.parametrize("repo, extra", [
    ({"Unknown": "x"}, {}),  # not one of the repository's keys
    ({}, {"product CODE": "x"}),  # an extra field can't shadow a repository key
])
def test_metadata_is_validated(client, ctx, repo, extra):
    _set_repo_meta(client, ctx)
    doc_id = _ids(_upload(client, ctx, [("policy.pdf", PDF)]))[0]
    assert _meta(client, ctx, doc_id, repo=repo, extra=extra).status_code == 422


def test_removed_repository_keys_are_kept_as_extra(client, ctx):
    _set_repo_meta(client, ctx)
    doc_id = _ids(_upload(client, ctx, [("policy.pdf", PDF)]))[0]
    _meta(client, ctx, doc_id, repo={"Product code": "VISA-PLAT", "Card tier": "Gold"})
    _set_repo_meta(client, ctx, REPO_META[1:])
    doc = client.get(f"/api/doc-repos/{ctx['pid']}/documents/{doc_id}", headers=ctx["maker"]).json()
    assert (doc["repository_metadata"], doc["extra"]) == ({"Card tier": "Gold"}, {"Product code": "VISA-PLAT"})


# --------------------------------------------------------------------------- submit & review


def test_submit_reports_skipped_documents(client, ctx):
    ids = _ids(_upload(client, ctx, [("draft.pdf", PDF), ("sent.pdf", PDF)]))
    _post(client, ctx, "submit", {"ids": [ids[1]]}, "maker")
    r = _post(client, ctx, "submit", {"ids": ids}, "maker")
    assert r.status_code == 200
    assert [d["filename"] for d in r.json()["done"]] == ["draft.pdf"]
    assert r.json()["skipped"] == [{"id": ids[1], "filename": "sent.pdf", "reason": "It's pending approval."}]


def test_bulk_approve_and_reject(client, ctx):
    ids = _ids(_upload(client, ctx, [("a.pdf", PDF), ("b.pdf", PDF), ("c.pdf", PDF)]))
    _post(client, ctx, "submit", {"ids": ids}, "maker")
    r = _post(client, ctx, "review", {"ids": ids[:2], "decision": "approve"}, "checker")
    assert [(d["status"], d["checker"]["lan_id"]) for d in r.json()["done"]] == [("approved", "checker")] * 2
    assert _post(client, ctx, "review", {"ids": [ids[2]], "decision": "reject"}, "checker").status_code == 422
    r = _post(client, ctx, "review", {"ids": [ids[2]], "decision": "reject", "reason": "Wrong version"}, "checker")
    assert (r.json()["done"][0]["status"], r.json()["done"][0]["rejection_reason"]) == ("rejected", "Wrong version")


def test_rejected_documents_go_back_to_the_maker(client, ctx):
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)]))[0]
    _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    _post(client, ctx, "review", {"ids": [doc_id], "decision": "reject", "reason": "Fix the purpose"}, "checker")
    assert _meta(client, ctx, doc_id, dept={**DEPT_META, "country": "Malaysia"}).status_code == 200
    r = _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    assert r.json()["done"][0]["status"] == "pending_approval"
    assert r.json()["done"][0]["rejection_reason"] is None


def test_pending_and_approved_documents_are_locked(client, ctx):
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)]))[0]
    _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    assert _meta(client, ctx, doc_id).status_code == 409
    r = _post(client, ctx, "delete", {"ids": [doc_id]}, "maker")
    assert r.json()["skipped"][0]["reason"] == "It's pending approval."
    r = _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    assert r.json()["skipped"][0]["reason"] == "It's pending approval."


def test_only_pending_documents_can_be_reviewed(client, ctx):
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)]))[0]
    _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    _post(client, ctx, "review", {"ids": [doc_id], "decision": "approve"}, "checker")
    r = _post(client, ctx, "review", {"ids": [doc_id], "decision": "reject", "reason": "x"}, "checker")
    assert r.json()["skipped"][0]["reason"] == "It's approved, not pending approval."


@pytest.mark.parametrize("who", ["maker", "viewer", "risk.admin"])
def test_only_doc_repo_checkers_review(client, ctx, who):
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)]))[0]
    _post(client, ctx, "submit", {"ids": [doc_id]}, "maker")
    assert _post(client, ctx, "review", {"ids": [doc_id], "decision": "approve"}, who).status_code == 403


def test_checker_never_decides_on_their_own_upload(client, ctx):
    """Someone who uploaded as a maker and later became a checker can't approve that upload."""
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)], who="maker2"))[0]
    _post(client, ctx, "submit", {"ids": [doc_id]}, "maker2")
    client.put(f"/api/doc-repos/{ctx['pid']}/members/maker2", json={"roles": ["CHECKER"]}, headers=ctx["risk.admin"])
    r = _post(client, ctx, "review", {"ids": [doc_id], "decision": "approve"}, "maker2")
    assert r.json()["skipped"][0]["reason"] == "You uploaded it; another checker has to decide."


def test_ids_from_another_doc_repo_or_hidden_are_refused(client, ctx):
    doc_id = _ids(_upload(client, ctx, [("a.pdf", PDF)]))[0]
    assert _post(client, ctx, "review", {"ids": [doc_id], "decision": "approve"}, "checker").status_code == 404
    assert _post(client, ctx, "submit", {"ids": [doc_id, 9999]}, "maker").status_code == 404


# --------------------------------------------------------------------------- delete


def test_maker_deletes_drafts_and_their_files(client, ctx):
    doc = _upload(client, ctx, [("a.pdf", PDF)]).json()[0]
    stored = get_settings().upload_dir / "doc-repos" / str(ctx["pid"]) / str(doc["id"])
    assert stored.exists()
    r = _post(client, ctx, "delete", {"ids": [doc["id"]]}, "maker")
    assert (r.status_code, r.json()["skipped"]) == (200, [])
    assert not stored.exists()
    assert _list(client, ctx, "maker") == []


def test_deleting_a_doc_repo_removes_its_documents_and_files(client, ctx):
    _upload(client, ctx, [("a.pdf", PDF)])
    folder = get_settings().upload_dir / "doc-repos" / str(ctx["pid"])
    assert folder.exists()
    assert client.delete(f"/api/doc-repos/{ctx['pid']}", headers=ctx["risk.admin"]).status_code == 204
    assert not folder.exists()
