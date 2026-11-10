"""Documents as a workflow subject: the bridge between documents and app.workflow.

The workflow module runs the flow; this handler supplies the document rules:
- a task's lane is the role that may do it ("checker");
- a checker must also pass the department and maker-checker rules in app.services.authz;
- the "review" task needs decision approve|reject, and a reason to reject;
- when the workflow ends, its outcome sets the document's status.
"""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Document, DocumentStatus, KnowledgeBase, User, utcnow
from app.services import audit, authz
from app.services.errors import Forbidden, InvalidRequest, NotFound
from app.workflow import service as workflow
from app.workflow.handlers import Actor, register_handler
from app.workflow.models import WorkflowInstance, WorkflowTask

SUBJECT = "document"


def _doc(db: Session, subject_id: str) -> Document:
    doc = db.scalar(
        select(Document)
        .where(Document.id == int(subject_id))
        .options(
            selectinload(Document.kb).selectinload(KnowledgeBase.department),
            selectinload(Document.maker),
        )
    )
    if doc is None:
        raise NotFound("Document not found.")
    return doc


class DocumentApprovalHandler:
    subject_type = SUBJECT
    definition_key = "document_approval"

    def authorize(self, db: Session, actor: Actor, task: WorkflowTask, instance: WorkflowInstance) -> None:
        doc = _doc(db, instance.subject_id)
        if authz.kb_access(db, actor, doc.kb) is None:
            raise NotFound("Document not found.")
        if task.lane and task.lane not in {str(r) for r in actor.roles}:
            raise Forbidden(f"Only a {task.lane} can do this.")
        if task.lane == "checker" and not authz.can_review(actor, doc, doc.maker):
            raise Forbidden("Only a checker from the maker's department can approve or reject this document.")

    def validate(self, task: WorkflowTask, data: dict[str, Any]) -> dict[str, Any]:
        if task.name != "review":
            return data  # tasks from uploaded definitions: passed through as-is
        decision = data.get("decision")
        if decision not in ("approve", "reject"):
            raise InvalidRequest("decision must be 'approve' or 'reject'.")
        reason = (data.get("reason") or "").strip() or None
        if decision == "reject" and not reason:
            raise InvalidRequest("Give a reason for rejecting the document.")
        return {"decision": decision, "reason": reason}

    def describe(self, db: Session, subject_id: str) -> dict[str, Any]:
        doc = _doc(db, subject_id)
        return {
            "title": doc.filename,
            "knowledge_base": {"id": doc.kb_id, "name": doc.kb.name},
            "submitted_by": doc.maker.display_name,
            "link": f"#kb/{doc.kb_id}",
        }

    def can_view(self, db: Session, actor: Actor, subject_id: str) -> bool:
        try:
            doc = _doc(db, subject_id)
        except NotFound:
            return False
        statuses = authz.visible_document_statuses(db, actor, doc.kb)
        return statuses is not None and doc.status in statuses

    def on_completed(
        self, db: Session, instance: WorkflowInstance, outcome: dict[str, Any], actor: Actor | None
    ) -> None:
        doc = _doc(db, instance.subject_id)
        approved = outcome.get("decision") == "approve"
        doc.status = DocumentStatus.APPROVED if approved else DocumentStatus.REJECTED
        doc.checker_id = actor.user_id if actor else None
        doc.decided_at = utcnow()
        doc.rejection_reason = None if approved else outcome.get("reason")
        audit.record(db, "document.approve" if approved else "document.reject",
                     actor_id=actor.user_id if actor else None, actor_lan_id=actor.lan_id if actor else None,
                     target_type="document", target_id=doc.id,
                     detail={"kb": doc.kb_id, "workflow_instance": instance.id})


register_handler(DocumentApprovalHandler())


def start_for(db: Session, doc: Document, actor: Actor | None) -> WorkflowInstance:
    """Start the approval workflow for a newly uploaded document."""
    return workflow.start(
        db, SUBJECT, doc.id,
        context={"document_id": doc.id, "kb_id": doc.kb_id, "filename": doc.filename,
                 "maker": doc.maker.lan_id if doc.maker else None},
        actor=actor,
    )


def backfill(db: Session) -> int:
    """Give every pending document without a workflow one (e.g. data from before this module)."""
    started = 0
    pending = db.scalars(
        select(Document).where(Document.status == DocumentStatus.PENDING).options(selectinload(Document.maker))
    ).all()
    for doc in pending:
        if not workflow.has_instance(db, SUBJECT, doc.id):
            start_for(db, doc, None)
            started += 1
    return started


def kb_activity(db: Session, actor: Actor, kb: KnowledgeBase) -> list[dict[str, Any]]:
    """Approval activity for a knowledge base's documents, newest first.

    Built from the workflow history: each run gives an "uploaded" event (when it started) and,
    once its review task is done, an "approved" or "rejected" event. Only documents the actor
    may see are included, so viewers get approved documents' activity only.
    """
    statuses = authz.visible_document_statuses(db, actor, kb)
    if statuses is None:
        raise Forbidden("Admins manage knowledge bases and people; they can't view document activity.")
    docs = {
        str(d.id): d
        for d in db.scalars(
            select(Document)
            .where(Document.kb_id == kb.id, Document.status.in_(statuses))
            .options(selectinload(Document.maker))
        )
    }
    if not docs:
        return []
    instances = db.scalars(
        select(WorkflowInstance)
        .where(WorkflowInstance.subject_type == SUBJECT, WorkflowInstance.subject_id.in_(docs))
        .options(selectinload(WorkflowInstance.tasks))
    ).all()
    user_ids = {i.started_by_id for i in instances} | {t.completed_by_id for i in instances for t in i.tasks}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({x for x in user_ids if x})))}

    def person(user_id: int | None) -> dict[str, str] | None:
        u = users.get(user_id) if user_id else None
        return {"username": u.lan_id, "display_name": u.display_name} if u else None

    events: list[dict[str, Any]] = []
    for inst in instances:
        doc = docs[inst.subject_id]
        ref = {"id": doc.id, "filename": doc.filename, "status": doc.status}
        events.append({
            "id": f"{inst.id}-start", "type": "uploaded", "at": inst.started_at,
            "document": ref, "actor": person(inst.started_by_id) or person(doc.maker_id), "reason": None,
        })
        for t in inst.tasks:
            if t.status != "completed" or not t.data:
                continue
            decision = json.loads(t.data).get("decision")
            if decision not in ("approve", "reject"):
                continue
            events.append({
                "id": f"{inst.id}-task-{t.id}",
                "type": "approved" if decision == "approve" else "rejected",
                "at": t.completed_at, "document": ref, "actor": person(t.completed_by_id),
                "reason": json.loads(t.data).get("reason"),
            })
    events.sort(key=lambda e: (e["at"], e["type"] != "uploaded"), reverse=True)
    return events
