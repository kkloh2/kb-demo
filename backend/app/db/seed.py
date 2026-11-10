"""Demo data. Every account's password is listed in docs/auth-module.md."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSION_DESCRIPTIONS, ROLES, RoleCode
from app.core.security import hash_password
from app.services import storage
from app.db.models import (
    AccessRequest,
    AccessRequestStatus,
    Department,
    Document,
    KbFavorite,
    KbViewGrant,
    KnowledgeBase,
    Permission,
    Role,
    User,
    UserRole,
    utcnow,
)


def sync_roles_and_permissions(db: Session) -> dict[RoleCode, Role]:
    """Make the roles / permissions / role_permissions tables match app.core.permissions.

    Idempotent; runs on every start-up so new permissions reach existing databases.
    """
    perms = {p.code: p for p in db.scalars(select(Permission))}
    for code, desc in PERMISSION_DESCRIPTIONS.items():
        if code.value in perms:
            perms[code.value].description = desc
        else:
            perms[code.value] = Permission(code=code.value, description=desc)
            db.add(perms[code.value])
    existing = {r.code: r for r in db.scalars(select(Role))}
    roles: dict[RoleCode, Role] = {}
    for code, d in ROLES.items():
        role = existing.get(code.value) or Role(code=code.value)
        role.name, role.description, role.scope, role.assignable = d.name, d.description, d.scope, d.assignable
        role.permissions = [perms[p.value] for p in sorted(d.permissions)]
        if code.value not in existing:
            db.add(role)
        roles[code] = role
    db.flush()
    return roles


DEPARTMENTS = [
    ("RISK", "Risk Management"),
    ("HR", "Human Resources"),
    ("COMP", "Compliance"),
    ("DATA", "Data Office"),
]

# lan_id, display name, title, department code (None = system admin), password, assigned roles
USERS: list[tuple[str, str, str, str | None, str, list[RoleCode]]] = [
    ("admin", "Demo Admin", "Data Platform Engineer", None, "admin123", [RoleCode.SYSTEM_ADMIN]),
    ("analyst", "Demo Analyst", "Data Analyst", "RISK", "datahub123", []),
    ("risk.admin", "Risk Admin", "Head of Risk Analytics", "RISK", "demo123", [RoleCode.DEPARTMENT_ADMIN]),
    ("risk.maker", "Risk Maker", "Risk Analyst", "RISK", "demo123", [RoleCode.MAKER]),
    ("risk.checker", "Risk Checker", "Senior Risk Manager", "RISK", "demo123", [RoleCode.CHECKER]),
    ("hr.admin", "HR Admin", "HR Business Partner", "HR", "demo123", [RoleCode.DEPARTMENT_ADMIN]),
    ("hr.maker", "HR Maker", "HR Executive", "HR", "demo123", [RoleCode.MAKER]),
    ("hr.checker", "HR Checker", "HR Manager", "HR", "demo123", [RoleCode.CHECKER]),
    ("comp.admin", "Compliance Admin", "Compliance Lead", "COMP", "demo123", [RoleCode.DEPARTMENT_ADMIN]),
    ("comp.officer", "Compliance Officer", "Compliance Officer", "COMP", "demo123", []),
    ("data.admin", "Data Admin", "Data Governance Lead", "DATA", "demo123", [RoleCode.DEPARTMENT_ADMIN]),
]

KNOWLEDGE_BASES = [
    ("credit-risk", "Credit Risk", "Credit policies, risk appetite statements and model documentation", "RISK", timedelta(hours=5)),
    ("hr-policies", "HR Policies", "Everything HR related should come here", "HR", timedelta(days=3)),
    ("aml-compliance", "AML & Compliance", "AML procedures, sanctions guidance and regulatory notices", "COMP", timedelta(days=12)),
    ("data-governance", "Data Governance", "Data standards, glossary and data ownership register", "DATA", timedelta(days=30)),
]


def sample_pdf(title: str) -> bytes:
    """A minimal one-page PDF with the title on it, so demo documents can be downloaded."""
    text = title.replace("\\", "").replace("(", "").replace(")", "")
    stream = f"BT /F1 20 Tf 72 720 Td ({text}) Tj ET\nBT /F1 11 Tf 72 690 Td (Data Hub demo document) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


KB_ADMINS = {"RISK": "risk.admin", "HR": "hr.admin", "COMP": "comp.admin", "DATA": "data.admin"}


def seed(db: Session) -> None:
    now = utcnow()
    roles = sync_roles_and_permissions(db)

    depts = {code: Department(code=code, name=name) for code, name in DEPARTMENTS}
    db.add_all(depts.values())
    db.flush()

    users: dict[str, User] = {}
    for lan_id, name, title, dept, password, assigned in USERS:
        u = User(
            lan_id=lan_id,
            display_name=name,
            title=title,
            email=f"{lan_id}@example.com",
            password_hash=hash_password(password),
            department_id=depts[dept].id if dept else None,
        )
        u.role_links = [UserRole(role=roles[r]) for r in assigned]
        users[lan_id] = u
    db.add_all(users.values())
    db.flush()

    kbs: dict[str, KnowledgeBase] = {}
    for kb_id, name, desc, dept, age in KNOWLEDGE_BASES:
        kbs[kb_id] = KnowledgeBase(
            id=kb_id,
            name=name,
            description=desc,
            department_id=depts[dept].id,
            admin_id=users[KB_ADMINS[dept]].id,
            created_by_id=users["admin"].id,
            created_at=now - age - timedelta(days=60),
            updated_at=now - age,
        )
    db.add_all(kbs.values())
    db.flush()

    # analyst (Risk) asked for HR Policies and HR's admin approved it ...
    approved = AccessRequest(
        kb_id="hr-policies",
        requester_id=users["analyst"].id,
        reason="Need HR policies for headcount risk analysis",
        status=AccessRequestStatus.APPROVED,
        decided_by_id=users["hr.admin"].id,
        decided_at=now - timedelta(days=2),
        created_at=now - timedelta(days=3),
    )
    # ... and is still waiting on AML & Compliance.
    pending = AccessRequest(
        kb_id="aml-compliance",
        requester_id=users["analyst"].id,
        reason="Cross-checking sanctions guidance for a credit review",
        created_at=now - timedelta(hours=6),
    )
    db.add_all([approved, pending])
    db.flush()
    db.add(KbViewGrant(
        kb_id="hr-policies",
        user_id=users["analyst"].id,
        request_id=approved.id,
        granted_by_id=users["hr.admin"].id,
        granted_at=now - timedelta(days=2),
    ))

    # Every demo document goes through the real approval workflow, so decided ones have history.
    from types import SimpleNamespace

    from app.services import document_approval
    from app.workflow import service as workflow

    workflow.ensure_builtin_definitions(db)

    def actor(lan_id: str, role: str):
        return SimpleNamespace(user_id=users[lan_id].id, lan_id=lan_id, roles={role})

    demo_docs = [
        # kb, title, filename, maker, age, (checker, decision, reason) or None
        ("credit-risk", "Credit Policy 2026", "credit-policy-2026.pdf", "risk.maker", timedelta(days=10),
         ("risk.checker", "approve", None)),
        ("credit-risk", "Risk Appetite Statement Q3", "risk-appetite-q3.pdf", "risk.maker", timedelta(hours=5), None),
        ("credit-risk", "Model Validation Report", "model-validation.pdf", "risk.maker", timedelta(days=4),
         ("risk.checker", "reject", "Missing sign-off page; please re-upload.")),
        ("hr-policies", "Employee Handbook", "employee-handbook.pdf", "hr.maker", timedelta(days=20),
         ("hr.checker", "approve", None)),
        ("hr-policies", "Leave Policy (draft revision)", "leave-policy-v2.pdf", "hr.maker", timedelta(days=3), None),
    ]
    for kb_id, title, filename, maker, age, decision in demo_docs:
        data = sample_pdf(title)
        d = Document(kb_id=kb_id, title=title, filename=filename, content_type="application/pdf",
                     size_bytes=len(data), maker_id=users[maker].id, submitted_at=now - age)
        db.add(d)
        db.flush()
        d.storage_path = storage.save(kb_id, d.id, filename, data)
        db.refresh(d, ["maker"])
        instance = document_approval.start_for(db, d, actor(maker, "maker"))
        instance.started_at = now - age
        if decision:
            checker, verdict, reason = decision
            task = workflow.open_task_for(db, document_approval.SUBJECT, d.id)
            workflow.complete_task(db, task.id, actor(checker, "checker"),
                                   {"decision": verdict, "reason": reason}, check_permission=False)
            decided = now - age + timedelta(hours=4)
            d.decided_at = instance.completed_at = task.completed_at = decided
        for t in instance.tasks:
            t.created_at = now - age

    db.add(KbFavorite(user_id=users["analyst"].id, kb_id="hr-policies"))
    db.commit()


def role_by_code(db: Session, code: RoleCode) -> Role:
    role = db.scalar(select(Role).where(Role.code == code.value))
    if role is None:
        raise LookupError(f"Role {code} is not seeded")
    return role
