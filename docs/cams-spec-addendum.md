# CAMS specification: addendum for Data Hub

**Status:** agreed 2026-11-13.
**Applies to:** *Centralized Approval Management System (CAMS): Claude Handoff, Technical Architecture and Implementation Specification* (design baseline 2026-11-13).

Data Hub builds CAMS on a shared access model: users, groups, roles and permissions for every source system. That model changes three things in the specification:

- **A. Renamed tables.** It overrides §2.7 and §11.
- **B. First version without workflow tables.** It relaxes §2.11 for the first version only.
- **C. Additions.** These go beyond the 23 entities in §4.

Everything else in the specification stands.

---

## A. Group tables use access-model names

Groups now hold every role, not only approval roles: platform admin, repository admin, maker, checker and viewer. Their names say so.

| Specification name | Data Hub name |
|---|---|
| `approval_group` | `user_group` |
| `approval_group_member` | `user_group_member` |
| `approval_group_member_role` | `user_group_member_role` |

- **Replaces** §2.7 ("The role association table is named `approval_group_member_role`") and the §11 checklist entries for these names.
- **Unchanged:**
  - Each member still has their own roles, so membership alone never grants authority.
  - `group_type` is still how groups are looked up.
  - Approval decisions still require an active membership with the required role, checked when deciding.

---

## B. First version: approval type and resource without workflow tables

The first version has one approval type with one step. It keeps the specification's approval type and resource records but does not yet build the workflow tables.

### Built now
- **`approval_type`:** seeded as `DOC_HUB` / `DOCUMENT_UPLOAD`.
- **`resource` and `resource_hierarchy_binding`:** creating a document repository, in the same transaction:
  - creates a `resource` row (`resource_type = DOC_REPO`, `resource_id` = the repository's id);
  - binds it to the repository's hierarchy node.

  Deleting the repository makes both inactive and cancels its pending requests.
- **Requests:** every approval request records its `approval_type_id` and `resource_pk`, as the specification requires.

### Deferred
These tables come when a second step, a second approval type or a second source system needs them:
- `workflow_definition`, `workflow_version`, `workflow_binding`
- `workflow_instance`, `step_instance`
- `workflow_configuration_audit`, `outbox_event`

### The rule for now
`DOCUMENT_UPLOAD` has one step, defined in code under the approval type's code:
- **Assignment:** `RESOURCE_NODE`, `group_type = MEMBERS`, `required_role = CHECKER`;
- **Completion:** `ANY`.

`approval_task` points at `approval_request` directly. When `step_instance` arrives, the task points at the step instead.

### Departures, accepted for this version only
- **§2.11 (no default binding):** the rule in code acts as the binding for `DOCUMENT_UPLOAD`. An approval type without a rule in code is still an error.
- **§2.12 (pinned published versions):** there are no versions yet. Changing the rule changes it for requests already pending. That is acceptable while the rule is fixed.

---

## C. Additions to the 23 entities

### C1. Permissions
| Table | Columns | Purpose |
|---|---|---|
| `permission` | id, code (UK), name, description | What a role can do. Codes are `<system>.<object>.<action>`, e.g. `docs.document.approve`. Defined and seeded from code. |
| `role_permission` | role_id, permission_id (PK both) | Which permissions each role has |

Access checks ask "may this person do permission P at node N?", never just "does this person have role R?". This answers §9.10 for Data Hub.

### C2. Platform admins create source systems and their hierarchies
- **`PLATFORM`** (Data Hub itself) is the only source system seeded. Its root's admins group holds the platform admins, which replaces system-wide roles.
- **Every other source system is created by a platform admin** in Administration (`/api/sources`, package `app/sources`), for example `DOC_HUB`, and later `APPROVALS` for CAMS's own administrators.
- **Creating its hierarchy** creates:
  - the levels, root first: `hierarchy.levels`, e.g. `["ROOT", "DOC_REPO"]` for Doc Hub's two levels. They replace a fixed list of allowed child types; a node can only be created at the level below its parent.
  - the root node;
  - the root's two groups:
    - **admins**: every platform admin is added, as ADMIN;
    - **users**: every active user is added, as VIEWER, and everyone who signs in later joins too.
- Each source system has exactly one hierarchy with one root. A role held at a system's root is that system's "system role".

Groups are containers; each member holds their own roles. `user_group.group_type` is `ADMINS` or `USERS` at a root, `MEMBERS` at a node below it (e.g. a repository), or `TEAM`. A node has at most one active group of each type.

### C3. New columns
| Table | Column | Purpose |
|---|---|---|
| `hierarchy_node` | `path` (UK, indexed) | Full path, e.g. `/DOC_HUB/DOC_REPO_A`, so finding a node's ancestors (for inherited metadata) needs no recursive query. A node's `code` can't change once created. |
| `user_group` | `auto_join_role_id` (FK role, nullable) | The role given to every user at first sign-in, e.g. VIEWER at the PLATFORM and DOC_HUB roots |
| `user_group_member`, `user_group_member_role` | `added_by`/`granted_by`, `status` | Rows become INACTIVE and are never deleted |
| `app_user` | `access_version` | Goes up on every change to the user's memberships, so stale sign-in tokens are refused |
| `approval_request` | `subject_type`, `subject_id` (indexed together) | What is being approved, e.g. `DOCUMENT` and the document's id. `resource_pk` stays the repository. |
| `approval_request` | `current_round`, `last_event_sequence` | Round counter, and how `event_sequence` is allocated (§9.15): incremented in the same transaction |
| `approval_task` | `round`, `subject_snapshot` | One task per round; the snapshot records exactly what was reviewed |

### C4. Decision value CHANGES_REQUESTED
- **`approval_decision.decision`:** `APPROVED | REJECTED | CHANGES_REQUESTED`. A comment is required unless the decision is APPROVED.
- **`approval_request.status`:** gains `CHANGES_REQUESTED`, meaning the request is back with the maker.
- **Rounds:**
  - Resubmitting continues the **same** request with a new round: a new task and a new snapshot.
  - REJECTED stays final, and a later resubmission is a new request.
  - `external_reference_id` is therefore made per request, e.g. `document:<id>:<n>`.
- **Later, with workflows:** sending back to an earlier checker step is the same decision, with a step id as its transition target. `maker` is a reserved target.

### C5. Compliance and audit teams
Some teams must see every repository without being added to each one.

| Table or value | Purpose |
|---|---|
| `user_group.group_type = TEAM` | Teams such as COMPLIANCE and AUDIT, held at the `PLATFORM` root |
| `node_team_grant` (node, team, role, default_grant_id, status, granted_by) | "Team X has role R at this node". The team's current members hold the role. |
| `default_grant` (parent node, child node type, team, role, status) | "Every DOC_REPO under the DOC_HUB root gets these team grants." Applied to new nodes when they're created, and to existing nodes when the default is added. Both are audited. |
| `role` AUDITOR | Sees documents in every status, their approval history and the audit trail. Can't act. |

**Rules:**
- **Who manages them:** only platform admins manage teams, team grants and default grants. Repository admins and system root admins can't change or remove them.
- **Which roles:** team grants carry read-only roles only (VIEWER, AUDITOR). A team never holds MAKER, CHECKER, APPROVER or ADMIN, so approval assignment (§2.15, §7.3) is unaffected.
- **No inheritance:** grants still apply only at the node they're attached to.

### C6. Audit of access changes
`audit_event`:
- **Columns:** id, actor_id, action, target_type, target_id, hierarchy_node_id, details (before/after), created_at.
- **Covers** membership and role changes, setting up system roots, and recovery.
- **Is** the separate Auth Service audit store recommended in §9.14.

---

## The approvals inbox
The Approvals page (the inbox) is shown to anyone who holds a role with an approve permission (CHECKER, APPROVER) at any node. It lists only the tasks that person may decide: tasks assigned to a group where they hold the required role, excluding their own requests. No separate permission is needed to open the page.

## Rules the model relies on
- **Every role applies only at the node where it is granted.** No role reaches the nodes below, so §2.15 (no inherited authority) holds for every role, not just approval roles.
- **Platform admins** (ADMIN at the `PLATFORM` root):
  - set up each source system's root and its first admins;
  - reassign the admins of any node when none are left (recovery).

  Both are audited.
- **System root admins** (e.g. ADMIN at the `DOC_HUB` root):
  - have NODE scope: they create child nodes such as repositories and manage the root's members;
  - don't reach into existing children.
- **The creator of a node** becomes its **OWNER**. OWNER has everything ADMIN has, and can also delete the node and hand ownership to someone else. A node has at most one active OWNER.
- **Deleting a node** needs OWNER at the node itself. Other ADMINs can manage members but can't delete.
- **If the owner leaves,** a platform admin reassigns ownership (recovery, audited).
- **The OWNER can't be removed** except by handing ownership to someone else or through recovery.
- **Deletes are soft.**
  - A deleted node is marked `DELETED` with `deleted_by` and `deleted_at`. Its documents, metadata, memberships and approval history are kept.
  - Its `resource` and binding become INACTIVE, and its pending approval requests are CANCELLED.
  - It disappears from every list and access check.
  - A platform admin can restore it (audited). Pending requests stay cancelled; makers resubmit.
  - Its code stays reserved.
- **Child node types** allowed under each node type are defined in code. A document repository has no children.
