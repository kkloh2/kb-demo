"""Repositories: creating (owner), listing, members, ownership, soft delete and restore, team grants."""

import pytest
from tests.helpers import set_roles


def _repo(client, hub, who="ben", name="Card Policies", **extra):
    r = client.post("/api/doc-repos", json={"name": name, **extra}, headers=hub[who])
    assert r.status_code == 201, r.text
    return r.json()


def test_the_creator_becomes_the_owner(client, hub):
    body = client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["ben"]).json()
    assert body["owner"]["lan_id"] == "ben" and body["access"]["roles"] == ["OWNER"]
    assert body["access"]["delete"] is True and body["access"]["upload"] is False  # owners don't upload
    assert body["metadata"] == [{"label": "Department", "value": "Risk Management"},
                                {"label": "Country", "value": "Singapore"}]


def test_new_repositories_start_with_no_metadata_fields(client, hub):
    assert _repo(client, hub)["metadata"] == []


@pytest.mark.parametrize("who", ["dana", "marcus", "cara", "eve", "analyst"])
def test_only_doc_hub_admins_create_repositories(client, hub, who):
    assert client.post("/api/doc-repos", json={"name": "Mine"}, headers=hub[who]).status_code == 403


def test_names_are_unique(client, hub):
    r = client.post("/api/doc-repos", json={"name": "loan risks"}, headers=hub["andy"])
    assert r.status_code == 409


def test_everyone_sees_the_list_but_opens_only_their_repositories(client, hub):
    items = {r["name"]: r for r in client.get("/api/doc-repos", headers=hub["analyst"]).json()}
    assert items["Loan Risks"]["access"]["view"] is False and items["Loan Risks"]["document_count"] == 0
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["analyst"]).status_code == 403
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["eve"]).status_code == 200


def test_doc_hub_admins_do_not_reach_into_repositories(client, hub):
    """Root ADMIN is node scope: Andy can create repositories but not manage Ben's."""
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["andy"]).status_code == 403
    assert client.delete(f"/api/doc-repos/{hub['repo']}", headers=hub["andy"]).status_code == 403
    assert client.put(f"/api/doc-repos/{hub['repo']}/members/andy", json={"groups": []},
                      headers=hub["andy"]).status_code == 403
    assert client.get(f"/api/doc-repos/{hub['repo']}/groups", headers=hub["andy"]).status_code == 403


def test_repository_admins_manage_members_but_cannot_delete_or_create(client, hub):
    r = set_roles(client, hub['repo'], "outsider", ["VIEWER"], hub["dana"])
    assert r.status_code == 200
    assert client.delete(f"/api/doc-repos/{hub['repo']}", headers=hub["dana"]).status_code == 403
    assert client.post("/api/doc-repos", json={"name": "Dana's"}, headers=hub["dana"]).status_code == 403


def test_members_and_their_roles(client, hub):
    body = client.get(f"/api/doc-repos/{hub['repo']}/members", headers=hub["dana"]).json()
    assert {m["lan_id"]: m["roles"] for m in body["members"]} == {
        "ben": ["OWNER"], "dana": ["ADMIN"], "marcus": ["MAKER"], "mia": ["MAKER"], "cara": ["CHECKER"],
        "chris": ["CHECKER"], "eve": ["VIEWER"]}
    assert [(g["name"], g["member_count"], g["default"]) for g in body["groups"]] == [
        ("Users", 2, True), ("Admins", 1, False), ("Checkers", 2, False), ("Makers", 2, False)]
    assert body["grantable_roles"] == ["ADMIN", "MAKER", "CHECKER", "VIEWER"] and body["team_grants"] == []


@pytest.mark.parametrize("roles", [["OWNER"], ["AUDITOR"], ["NOPE"]])
def test_roles_a_person_can_be_given_in_a_group(client, hub, roles):
    url = f"/api/doc-repos/{hub['repo']}"
    group = client.post(f"{url}/groups", json={"name": "Reviewers"}, headers=hub["ben"]).json()["id"]
    r = client.put(f"{url}/members/outsider", json={"groups": [{"id": group, "roles": roles}]}, headers=hub["ben"])
    assert r.status_code == 422


def test_group_names_are_unique_per_repository(client, hub):
    url = f"/api/doc-repos/{hub['repo']}/groups"
    assert client.post(url, json={"name": "makers"}, headers=hub["ben"]).status_code == 409
    other = client.post("/api/doc-repos", json={"name": "Other"}, headers=hub["andy"]).json()
    assert client.post(f"/api/doc-repos/{other['id']}/groups", json={"name": "Makers"}, headers=hub["andy"]).status_code == 201


def test_each_person_holds_their_own_roles_in_a_group(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    r = client.post(f"{url}/groups", json={"name": "default"}, headers=hub["dana"])
    assert r.status_code == 201 and r.json()["member_count"] == 0 and "roles" not in r.json()
    group = r.json()["id"]
    assert client.get(url, headers=hub["outsider"]).status_code == 403
    r = client.put(f"{url}/members/outsider", json={"groups": [{"id": group, "roles": ["VIEWER"]}]}, headers=hub["dana"])
    assert r.status_code == 200 and r.json()["groups"] == [{"id": group, "name": "default", "roles": ["VIEWER"]}]
    assert client.get(url, headers=hub["outsider"]).json()["access"]["roles"] == ["VIEWER"]
    r = client.put(f"{url}/members/eve", json={"groups": [{"id": group, "roles": ["CHECKER"]}]}, headers=hub["dana"])
    roles = {m["lan_id"]: m["groups"] for m in client.get(f"{url}/members", headers=hub["dana"]).json()["members"]}
    assert roles["outsider"] == [{"id": group, "name": "default", "roles": ["VIEWER"]}]  # same group, own roles
    assert roles["eve"] == [{"id": group, "name": "default", "roles": ["CHECKER"]}]  # (eve left "Users")
    r = client.put(f"{url}/groups/{group}", json={"name": "Credit reviewers"}, headers=hub["dana"])
    assert r.status_code == 200 and r.json()["name"] == "Credit reviewers" and r.json()["member_count"] == 2
    actions = [e["action"] for e in client.get("/api/audit", headers=hub["admin"]).json()["items"]]
    assert {"GROUP_CREATED", "GROUP_RENAMED", "MEMBER_GROUPS_SET"} <= set(actions)


def test_a_person_can_be_both_maker_and_checker_in_a_group(client, hub):
    """Separation of duties is per document: nobody decides their own submission (test_approvals)."""
    url = f"/api/doc-repos/{hub['repo']}"
    group = client.post(f"{url}/groups", json={"name": "Policy team"}, headers=hub["ben"]).json()["id"]
    r = client.put(f"{url}/members/outsider", json={"groups": [{"id": group, "roles": ["MAKER", "CHECKER"]}]},
                   headers=hub["ben"])
    assert r.status_code == 200
    assert set(client.get(url, headers=hub["outsider"]).json()["access"]["roles"]) == {"MAKER", "CHECKER"}


def test_groups_of_another_repository_are_refused(client, hub):
    other = client.post("/api/doc-repos", json={"name": "Other"}, headers=hub["andy"]).json()
    theirs = client.get(f"/api/doc-repos/{other['id']}/groups", headers=hub["andy"]).json()["groups"][0]["id"]
    r = client.put(f"/api/doc-repos/{hub['repo']}/members/eve", json={"groups": [{"id": theirs, "roles": ["VIEWER"]}]},
                   headers=hub["ben"])
    assert r.status_code == 422
    assert client.put(f"/api/doc-repos/{hub['repo']}/groups/{theirs}", json={"name": "X"},
                      headers=hub["ben"]).status_code == 404


def test_roles_take_effect_without_signing_in_again(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    assert client.get(url, headers=hub["outsider"]).status_code == 403
    set_roles(client, hub["repo"], "outsider", ["VIEWER"], hub["ben"])
    assert client.get(url, headers=hub["outsider"]).status_code == 200
    client.delete(f"{url}/members/outsider", headers=hub["ben"])
    assert client.get(url, headers=hub["outsider"]).status_code == 403


def test_the_owner_cannot_be_removed(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    assert client.delete(f"{url}/members/ben", headers=hub["dana"]).status_code == 204
    assert client.get(url, headers=hub["ben"]).json()["access"]["roles"] == ["OWNER"]


def test_owner_hands_ownership_over_and_stays_admin(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    assert client.put(f"{url}/owner", json={"lan_id": "dana"}, headers=hub["dana"]).status_code == 403
    assert client.put(f"{url}/owner", json={"lan_id": "dana"}, headers=hub["ben"]).status_code == 204
    roles = {m["lan_id"]: m["roles"] for m in client.get(f"{url}/members", headers=hub["dana"]).json()["members"]}
    assert roles["dana"] == ["OWNER", "ADMIN"] and roles["ben"] == ["ADMIN"]
    assert client.delete(url, headers=hub["ben"]).status_code == 403  # only the owner deletes


def test_platform_admin_reassigns_an_owner(client, hub):
    node = client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["ben"]).json()["node_id"]
    assert client.put(f"/api/nodes/{node}/owner", json={"lan_id": "dana"}, headers=hub["ben"]).status_code == 403
    assert client.put(f"/api/nodes/{node}/owner", json={"lan_id": "dana"}, headers=hub["admin"]).status_code == 204
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["dana"]).json()["owner"]["lan_id"] == "dana"
    actions = [e["action"] for e in client.get("/api/audit", headers=hub["admin"]).json()["items"]]
    assert "OWNER_REASSIGNED" in actions


def test_soft_delete_and_restore(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    assert client.delete(url, headers=hub["ben"]).status_code == 204
    assert client.get(url, headers=hub["ben"]).status_code == 404
    assert "Loan Risks" not in {r["name"] for r in client.get("/api/doc-repos", headers=hub["eve"]).json()}
    deleted = client.get("/api/doc-repos/deleted", headers=hub["admin"]).json()
    assert [d["name"] for d in deleted] == ["Loan Risks"] and deleted[0]["deleted_at"]
    assert client.post(f"{url}/restore", headers=hub["ben"]).status_code == 403
    assert client.post(f"{url}/restore", headers=hub["admin"]).status_code == 200
    assert client.get(url, headers=hub["eve"]).status_code == 200  # members came back with it


def test_owner_and_admins_edit_name_description_and_metadata(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    r = client.put(url, json={"name": "Loan Risk Policies", "description": "x"}, headers=hub["dana"])
    assert r.status_code == 200 and r.json()["name"] == "Loan Risk Policies"
    r = client.put(f"{url}/metadata", json=[{"label": "Country", "value": "SG"}], headers=hub["ben"])
    assert r.json() == [{"label": "Country", "value": "SG"}]
    assert client.put(url, json={"name": "Nope"}, headers=hub["marcus"]).status_code == 403


@pytest.mark.parametrize("pairs", [[{"label": "A", "value": "1"}, {"label": "a", "value": "2"}],
                                   [{"label": " ", "value": "1"}]])
def test_bad_repository_metadata(client, hub, pairs):
    assert client.put(f"/api/doc-repos/{hub['repo']}/metadata", json=pairs, headers=hub["ben"]).status_code == 422


def test_default_grants_give_teams_read_only_access_to_new_and_existing_repositories(client, hub):
    admin = hub["admin"]
    url = f"/api/doc-repos/{hub['repo']}"
    assert client.get(url, headers=hub["ivan"]).status_code == 403
    grant = client.post("/api/default-grants", json={"team": "AUDIT", "role": "AUDITOR"}, headers=admin).json()
    assert client.get(url, headers=hub["ivan"]).json()["access"]["roles"] == ["AUDITOR"]  # existing repository
    new = _repo(client, hub, who="andy")
    assert client.get(f"/api/doc-repos/{new['id']}", headers=hub["ivan"]).status_code == 200  # new repository
    teams = client.get(f"{url}/members", headers=hub["ben"]).json()["team_grants"]
    assert teams == [{"team": "AUDIT", "team_name": "Audit", "role": "AUDITOR", "from_default": True}]
    # repository admins can't remove it; the platform admin can
    assert client.delete(f"/api/default-grants/{grant['id']}", headers=hub["ben"]).status_code == 403
    assert client.delete(f"/api/default-grants/{grant['id']}", headers=admin).status_code == 204
    assert client.get(url, headers=hub["ivan"]).status_code == 403


def test_team_membership_changes_apply_everywhere_at_once(client, hub):
    admin = hub["admin"]
    client.post("/api/default-grants", json={"team": "COMPLIANCE", "role": "VIEWER"}, headers=admin)
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["grace"]).status_code == 200
    client.put("/api/teams/COMPLIANCE/members", json={"lan_ids": []}, headers=admin)
    assert client.get(f"/api/doc-repos/{hub['repo']}", headers=hub["grace"]).status_code == 403


def test_missing_repository(client, hub):
    assert client.get("/api/doc-repos/01900000-0000-7000-8000-000000000000", headers=hub["ben"]).status_code == 404


def test_members_list_their_user_groups_and_dates(client, hub):
    body = client.get(f"/api/doc-repos/{hub['repo']}/members", headers=hub["ben"]).json()
    ben = next(m for m in body["members"] if m["lan_id"] == "ben")
    assert [(g["name"], g["roles"]) for g in ben["groups"]] == [("Users", ["OWNER"])]
    assert ben["added_at"] and ben["updated_at"]


def test_deleting_a_user_group_takes_away_the_roles_held_in_it(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    groups = {g["name"]: g["id"] for g in client.get(f"{url}/groups", headers=hub["ben"]).json()["groups"]}
    assert client.delete(f"{url}/groups/{groups['Makers']}", headers=hub["marcus"]).status_code == 403
    assert client.delete(f"{url}/groups/{groups['Users']}", headers=hub["ben"]).status_code == 409  # the default
    assert client.delete(f"{url}/groups/{groups['Makers']}", headers=hub["dana"]).status_code == 204
    assert client.get(url, headers=hub["marcus"]).status_code == 403  # marcus was only a maker there
    names = [g["name"] for g in client.get(f"{url}/groups", headers=hub["ben"]).json()["groups"]]
    assert "Makers" not in names
    assert client.post(f"{url}/groups", json={"name": "Makers"}, headers=hub["ben"]).status_code == 201  # name free again
    assert "GROUP_DELETED" in [e["action"] for e in client.get("/api/audit", headers=hub["admin"]).json()["items"]]


def test_deleting_the_checkers_group_empties_their_inboxes(client, hub):
    from tests.approvals.test_approvals import inbox, submit
    submit(client, hub)
    url = f"/api/doc-repos/{hub['repo']}"
    groups = {g["name"]: g["id"] for g in client.get(f"{url}/groups", headers=hub["ben"]).json()["groups"]}
    assert len(inbox(client, hub, "cara")) == 1
    client.delete(f"{url}/groups/{groups['Checkers']}", headers=hub["ben"])
    assert inbox(client, hub, "cara") == [] and inbox(client, hub, "chris") == []


def test_an_admin_cannot_remove_their_own_right_to_manage(client, hub):
    url = f"/api/doc-repos/{hub['repo']}"
    groups = {g["name"]: g["id"] for g in client.get(f"{url}/groups", headers=hub["ben"]).json()["groups"]}
    r = client.delete(f"{url}/groups/{groups['Admins']}", headers=hub["dana"])  # dana's only admin role is there
    assert r.status_code == 409 and "your own right to manage" in r.text
    assert client.get(f"{url}/groups", headers=hub["dana"]).status_code == 200  # nothing changed
    r = client.put(f"{url}/members/dana", json={"groups": [{"id": groups["Admins"], "roles": ["VIEWER"]}]},
                   headers=hub["dana"])
    assert r.status_code == 409
    assert client.delete(f"{url}/groups/{groups['Admins']}", headers=hub["ben"]).status_code == 204  # the owner may
