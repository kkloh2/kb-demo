# Data Hub: Approval workflow module

This document is the technical reference for the approval workflow module. It covers how the module is built, how documents use it, its API, and the plan for running approval flows from uploaded BPMN files with [SpiffWorkflow](https://github.com/sartography/SpiffWorkflow).

- **Code:** `backend/app/workflow/` (the module) and `backend/app/services/document_approval.py` (documents as its first subject)
- **Tests:** `backend/tests/test_workflow.py`; the document tests in `test_documents.py` also run through it
- **Status:** one built-in engine (`builtin.single_review`) runs today's maker-checker flow. A SpiffWorkflow engine is the planned next step (section 6).

---

## 1. Why a separate module

Approval used to be a status column on `documents` that the documents service changed directly. To let approval flows be changed by uploading a workflow file, approval is now its own module:

- **It knows nothing about documents.** Documents plug in through a *subject handler*, so other subjects (knowledge bases, access requests) can use the same module later.
- **The flow itself is data.** Each subject type is governed by a *workflow definition* (key + version) that names an *engine*. Changing the flow means activating a new definition version, not changing code.
- **It's shaped like BPMN.** A flow is user tasks in lanes, completed with data, with engine state serialised as JSON. That's how SpiffWorkflow works, so a Spiff engine is another implementation of the same interface, with no further refactor.

It runs inside the backend process for now. Its API (section 5) and tables (section 4) form a clean boundary, so it can later move to its own service by replacing the in-process calls in `document_approval.py` with HTTP calls.

---

## 2. Architecture

```
            ┌──────────────────────── app/workflow (generic) ─────────────────────────┐
 API  ───▶  │ service.py   start · complete_task · inbox · history                     │
            │     │                                     │                             │
            │     ▼                                     ▼                             │
            │ engine.py  WorkflowEngine contract   handlers.py  SubjectHandler contract│
            │     ▲  registry                           ▲  registry                   │
            │     │                                     │                             │
            │ builtin.py  builtin.single_review    models.py  definitions · instances  │
            │ (future) spiff.py  spiff.bpmn                   · tasks                  │
            └─────────────────────────────────────────┬───────────────────────────────┘
                                                      │ registers "document" handler
                     app/services/document_approval.py ┘  (document rules; sets status)
                     app/services/documents.py  upload → start · approve/reject → complete
```

| Piece | Responsibility |
|---|---|
| **Engine** (`engine.py`) | Runs a flow. `start(source, context)` and `complete(state, task_id, data)` return a snapshot: new state, ready tasks, finished or not, outcome. Engines are registered by name. |
| **Definition** (`workflow_definitions`) | Which engine runs a flow and, for file-based engines, the file itself (BPMN XML). Versioned per key; one active version per key. |
| **Instance** (`workflow_instances`) | One run for one subject, e.g. `document:42`, pinned to the definition version it started with. Holds the engine's JSON state and, at the end, the outcome. |
| **Task** (`workflow_tasks`) | A step waiting for a person, copied from the engine's ready tasks so inboxes are a plain SQL query. The **lane** is the role allowed to do it. |
| **Subject handler** (`handlers.py`) | The domain rules for one subject type: who may complete a task, what data is valid, what the inbox shows, who may see history, and what to do with the outcome. |

### The engine contract

```python
class WorkflowEngine(Protocol):
    name: str                                              # e.g. "builtin.single_review", "spiff.bpmn"
    def validate_definition(self, source: str | None) -> None: ...         # on upload; raise ValueError
    def start(self, source: str | None, context: dict) -> EngineSnapshot: ...
    def complete(self, state: dict, task_id: str, data: dict) -> EngineSnapshot: ...

@dataclass
class EngineSnapshot:
    state: dict                 # opaque; stored as JSON in workflow_instances.state
    ready: list[EngineTask]     # EngineTask(id, name, title, lane)
    completed: bool
    outcome: dict               # final workflow data when completed
```

### The built-in engine

`builtin.single_review` is today's flow:

```
start ──▶ [review] lane: checker ──▶ end      outcome = {"decision": "approve"|"reject", "reason": ...}
```

---

## 3. Documents as a subject

`app/services/document_approval.py` registers the `document` handler and keeps every document rule that existed before the refactor:

| Rule | Where |
|---|---|
| A task's lane must be one of the user's roles | `authorize` |
| A checker must be in the knowledge base's department **and** the maker's department, and must not be the maker | `authorize` → `authz.can_review` |
| Users who can't see the knowledge base get 404 | `authorize` |
| The `review` task needs `decision` = `approve`/`reject`, and a reason to reject | `validate` |
| On completion, the outcome sets `documents.status`, `checker_id`, `decided_at` and `rejection_reason` | `on_completed` |

**Lifecycle**

1. **Upload:** `documents.upload` saves the file and calls `document_approval.start_for(...)` **in the same transaction**. If the workflow can't start, the upload is rolled back (tested).
2. **Decide**, in either of two ways:
   - **Approve / Reject**: `POST /api/documents/{id}/approve|reject`, which the UI uses. These are shortcuts that complete the document's open `checker` task.
   - **Generic**: `POST /api/workflow/tasks/{task_id}/complete` with `{"data": {...}}`.
3. **Finish:** when the engine finishes, the handler applies the outcome to the document.

`documents.status` is kept as a **projection** of the workflow outcome, so listing and visibility queries stay simple and fast.

**Existing data:** on start-up, `document_approval.backfill()` starts a workflow for any pending document that doesn't have one. It's idempotent, and tested. Demo documents are seeded through the real workflow, so decided ones have history.

---

## 4. Tables

**`workflow_definitions`**

| Column | Notes |
|---|---|
| `key`, `version` | unique together, e.g. `document_approval` v1 |
| `engine` | registered engine name |
| `name`, `description` | |
| `source`, `source_filename` | BPMN XML for file-based engines; NULL for built-in |
| `is_active` | **at most one active version per key** (partial unique index) |
| `created_by_id`, `created_at` | |

**`workflow_instances`**

| Column | Notes |
|---|---|
| `definition_id` | pinned at start |
| `subject_type`, `subject_id` | e.g. `document`, `42` (indexed together) |
| `status` | `running` / `completed` / `cancelled` |
| `state` | engine JSON |
| `outcome` | JSON, when completed |
| `started_by_id`, `started_at`, `completed_at` | |

**`workflow_tasks`**

| Column | Notes |
|---|---|
| `instance_id` | |
| `engine_task_id` | the engine's id for the task |
| `name`, `title` | e.g. `review`, "Review document" |
| `lane` | role allowed to complete it |
| `status` | `ready` / `completed` / `cancelled`; inbox index on (`status`, `lane`) |
| `data` | JSON submitted on completion |
| `completed_by_id`, `completed_at`, `created_at` | |

**Audit events:** `workflow.start`, `workflow.task.complete` (with the submitted data) and `workflow.complete` (with the outcome), alongside the existing `document.approve` / `document.reject`.

---

## 5. API

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/api/workflow/tasks` | signed in | **Inbox:** ready tasks in your roles' lanes that you're allowed to complete, with a summary of the subject (file, knowledge base, uploader, link) |
| POST | `/api/workflow/tasks/{id}/complete` | per the subject's rules | Complete a task with `{"data": {...}}`; returns the instance |
| GET | `/api/workflow/subjects/{type}/{id}/instances` | anyone who can see the subject | History: every run with its tasks, who completed them and with what data |
| GET | `/api/workflow/definitions` | system admin (`workflows:view`) | Definitions and versions |

`POST /api/documents/{id}/approve` and `/reject` remain as shortcuts.

---

## 6. Plan: flows from uploaded BPMN files (SpiffWorkflow)

The goal: a system admin uploads a `.bpmn` file (drawn in a BPMN modeller), it becomes a new version of `document_approval`, and new uploads follow it. For example: checker, then department admin sign-off for documents over a size, then compliance review for certain knowledge bases.

### What to build

1. **A `spiff.bpmn` engine** (`app/workflow/spiff.py`) implementing `WorkflowEngine`:

   | Method | SpiffWorkflow mapping |
   |---|---|
   | `validate_definition(source)` | Parse the XML with Spiff's BPMN parser and check it against the contract below. Raise `ValueError` with a readable message. |
   | `start(source, context)` | Parse, create a workflow, put `context` into its data, run engine steps, then **serialise** the workflow to JSON (Spiff provides a serializer). Return its ready manual (user) tasks as `EngineTask(id=<task uuid>, name=<task spec name>, title=<task spec label>, lane=<task spec lane>)`. |
   | `complete(state, task_id, data)` | Deserialise, find the task by id, merge `data` into it, run it, run engine steps, then serialise. If the workflow is finished, return its data as the `outcome`. |

   Register it in `app/workflow/__init__.py`, and add `SpiffWorkflow` to `requirements.txt`. Pin the version, because Spiff's API and serialised format have changed between major versions. Check the parser, serializer and task-state names against that release's documentation.

2. **Definition upload endpoints** (system admin, new permission `workflows:manage`):

   | Endpoint | Purpose |
   |---|---|
   | `POST /api/workflow/definitions` | multipart `.bpmn`, plus `key`. Validates with the engine and stores it as the next version, **inactive**. |
   | `POST /api/workflow/definitions/{id}/activate` | Makes this version the active one for its key. Running instances keep their version. |
   | `GET /api/workflow/definitions/{id}/source` | Download the BPMN. |

3. **A Workflows tab** in Administration listing definitions, with **Upload** and **Activate** actions.

Nothing else changes. The handler, tables, inbox and the document UI already work with any engine that follows the contract.

### Contract an uploaded BPMN must follow (for `document_approval`)

- **Lanes:** every user task is in a lane named after a Data Hub role: `checker`, `department_admin` or `maker`. The inbox and permissions use the lane.
- **Start data:** the workflow starts with `document_id`, `kb_id`, `filename` and `maker` in its data, for gateways to branch on.
- **Review tasks:** a task named `review` collects `decision` (`approve`/`reject`) and `reason`, with the same validation as today. Tasks with other names pass their data through; add rules for them in `DocumentApprovalHandler.validate` as needed.
- **End data:** the process must end with `decision` in its data. `approve` publishes the document; anything else rejects it, using `reason`.

`validate_definition` should reject files that break the contract: unknown lanes, missing start event, or more than one process.

### Security: uploaded BPMN can run code

BPMN **script tasks** and gateway **conditions** are evaluated as Python by SpiffWorkflow's script engine. An uploaded file is therefore code, and must be treated that way:

- only system admins can upload, and every upload and activation is audited;
- run Spiff with a **restricted script environment** (no imports, no file or network access, only whitelisted functions), or reject definitions that contain script tasks;
- new versions are **inactive until activated**, so they can be reviewed first;
- add a time limit on engine steps so a looping definition can't hang a request.

---

## 7. Extending to other subjects

To put something else under approval, for example the cross-department access requests:

1. Write a handler with `subject_type = "access_request"` and its own `definition_key`, implementing `authorize`, `validate`, `describe`, `can_view` and `on_completed`.
2. Add a built-in definition for its key to `BUILTIN_DEFINITIONS` in `app/workflow/service.py`.
3. Call `workflow.start(db, "access_request", request.id, context, actor)` where the subject is created.

The inbox, task completion, history and audit work without changes.
