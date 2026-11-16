"""Shared test helpers."""

ROLE_GROUPS = {"ADMIN": "Admins", "MAKER": "Makers", "CHECKER": "Checkers", "VIEWER": "Users"}


def set_roles(client, repo: str, lan_id: str, roles: list[str], headers: dict):
    """Give the person these roles in the repository, each in its own user group ("Admins", "Makers",
    "Checkers"; VIEWER in the default "Users" group), made as needed. Returns the PUT response."""
    groups = client.get(f"/api/doc-repos/{repo}/groups", headers=headers).json()["groups"]
    assignments = []
    for role in roles:
        group = next((g for g in groups if g["name"] == ROLE_GROUPS[role]), None)
        if group is None:
            r = client.post(f"/api/doc-repos/{repo}/groups", json={"name": ROLE_GROUPS[role]}, headers=headers)
            assert r.status_code == 201, r.text
            group = r.json()
            groups.append(group)
        assignments.append({"id": group["id"], "roles": [role]})
    return client.put(f"/api/doc-repos/{repo}/members/{lan_id}", json={"groups": assignments}, headers=headers)


# The test repositories keep makers and checkers in "Makers" and "Checkers" (set_roles), so they use
# this workflow rather than Doc Hub's default (which names a group called "default").
GROUPS_FLOW = {
    "code": "TEST.MAKERS_AND_CHECKERS", "name": "Makers and checkers", "start": "maker_upload",
    "steps": [
        {"id": "maker_upload", "type": "DOCUMENT_UPLOAD", "name": "Raised by a maker",
         "role": {"user_group": "Makers", "role": "MAKER"},
         "on": {"PASSED": "checker_review", "FAILED": "END:UNAUTHORIZED"}},
        {"id": "checker_review", "type": "DOCUMENT_REVIEW", "name": "Checker review",
         "role": {"user_group": "Checkers", "role": "CHECKER"}, "completion": {"rule": "ANY"},
         "on": {"APPROVED": "END:APPROVED", "REJECTED": "END:REJECTED", "CHANGES_REQUESTED": "maker_upload"}},
    ],
}


def use_workflow(client, repo: str, flow: dict, admin: dict, owner: dict) -> str:
    """Create the workflow (as a platform admin) if it isn't there, and make the repository use it."""
    r = client.post("/api/approval-workflows", json={"definition": flow}, headers=admin)
    assert r.status_code in (201, 409), r.text
    wf = next(w for w in client.get("/api/approval-workflows", headers=admin).json() if w["code"] == flow["code"])
    r = client.put(f"/api/doc-repos/{repo}/workflow", json={"workflow_id": wf["id"]}, headers=owner)
    assert r.status_code == 200, r.text
    return wf["id"]
