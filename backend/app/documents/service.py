"""Document repositories: create, edit, (soft) delete and restore, and what each person may do.

A repository is a DOC_REPO node under the DOC_HUB root. Creating one makes the creator its OWNER,
applies the default team grants (e.g. AUDIT as AUDITOR), adds the usual metadata fields, and
registers it with Approvals so its documents can be submitted.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.access import service as access
from app.access.catalog import NodeType, P, SystemCode
from app.access.models import AppUser, HierarchyNode, NodeStatus
from app.approvals import service as approvals
from app.audit import service as audit
from app.audit.catalog import register_actions
from app.documents import workflow_steps
from app.core.errors import Conflict, InvalidRequest, NotFound
from app.documents import metadata
from app.documents.models import DocRepo, Document, DocumentStatus

RESOURCE_TYPE = "DOC_REPO"
S = DocumentStatus


# --------------------------------------------------------------------------- lookups

register_actions("DOC_HUB", {
    "REPOSITORY_METADATA_SET": ("configuration", "Default metadata changed"),
    "DOCUMENTS_UPLOADED": ("content", "Documents uploaded"),
    "DOCUMENT_METADATA_SET": ("content", "Document metadata changed"),
    "DOCUMENTS_DELETED": ("content", "Documents deleted"),
    "DOCUMENT_DOWNLOADED": ("content", "Document downloaded"),
    "DOCUMENT_VERSION_DISCARDED": ("content", "Document version discarded"),
    "DOCUMENT_VERSION_RESTORED": ("content", "Earlier document version restored"),
})


def get_repo(db: Session, doc_repo_id: uuid.UUID, *, include_deleted: bool = False) -> DocRepo:
    repo = db.scalar(select(DocRepo).where(DocRepo.id == doc_repo_id).options(
        selectinload(DocRepo.node), selectinload(DocRepo.created_by)))
    if repo is None or (repo.node.status == NodeStatus.DELETED.value and not include_deleted):
        raise NotFound("No such document repository.")
    return repo


def repo_node(db: Session, doc_repo_id: uuid.UUID) -> uuid.UUID:
    """For endpoint guards: the repository's node (404 when there's no such active repository)."""
    return get_repo(db, doc_repo_id).hierarchy_node_id


def any_repo_node(db: Session, doc_repo_id: uuid.UUID) -> uuid.UUID:
    return get_repo(db, doc_repo_id, include_deleted=True).hierarchy_node_id


# --------------------------------------------------------------------------- what the caller may do


@dataclass(frozen=True)
class RepoAccess:
    roles: frozenset[str]
    permissions: frozenset[str]

    def has(self, p: P) -> bool:
        return p.value in self.permissions

    def visible_statuses(self) -> set[str]:
        statuses: set[str] = set()
        if self.has(P.DOC_VIEW_ALL):
            statuses |= {s.value for s in S}
        if self.has(P.DOC_VIEW_SUBMITTED):
            statuses |= {S.PENDING.value, S.CHANGES_REQUESTED.value, S.APPROVED.value, S.REJECTED.value}
        if self.has(P.DOC_VIEW_APPROVED):
            statuses.add(S.APPROVED.value)
        return statuses


def access_to(db: Session, user: AppUser, repo: DocRepo) -> RepoAccess:
    roles = access.roles_at(db, user.id, repo.hierarchy_node_id)
    return RepoAccess(frozenset(roles), frozenset(access.permissions_for(roles)))


@dataclass(frozen=True)
class RepoWithAccess:
    repo: DocRepo
    access: RepoAccess
    document_count: int  # documents the caller may see


def _counts(db: Session, items: list[tuple[DocRepo, RepoAccess]]) -> dict[uuid.UUID, int]:
    by_status: dict[uuid.UUID, dict[tuple[str, bool], int]] = {}
    ids = [r.id for r, _ in items]
    if ids:
        has_approved = Document.approved_version.is_not(None)
        for repo_id, status, approved, n in db.execute(
            select(Document.doc_repo_id, Document.status, has_approved, func.count())
            .where(Document.doc_repo_id.in_(ids), Document.deleted_at.is_(None))
            .group_by(Document.doc_repo_id, Document.status, has_approved)
        ):
            by_status.setdefault(repo_id, {})[(status, bool(approved))] = n

    def seen(a: RepoAccess, status: str, approved: bool) -> bool:  # see versions.views
        statuses = a.visible_statuses()
        return status in statuses or (approved and S.APPROVED.value in statuses)

    return {r.id: sum(n for (s, ap), n in by_status.get(r.id, {}).items() if seen(a, s, ap)) for r, a in items}


def list_repos(db: Session, user: AppUser) -> list[RepoWithAccess]:
    """Every active repository, most recently updated first, with what the caller may do in each."""
    repos = db.scalars(
        select(DocRepo).join(HierarchyNode, HierarchyNode.id == DocRepo.hierarchy_node_id)
        .where(HierarchyNode.status == NodeStatus.ACTIVE.value)
        .options(selectinload(DocRepo.node), selectinload(DocRepo.created_by))
        .order_by(DocRepo.updated_at.desc(), DocRepo.id.desc())
    ).all()
    held = access.roles_by_node(db, user.id, [r.hierarchy_node_id for r in repos])
    items = [(r, RepoAccess(frozenset(held.get(r.hierarchy_node_id, ())),
                            frozenset(access.permissions_for(held.get(r.hierarchy_node_id, ()))))) for r in repos]
    counts = _counts(db, items)
    return [RepoWithAccess(r, a, counts[r.id]) for r, a in items]


def with_access(db: Session, user: AppUser, repo: DocRepo) -> RepoWithAccess:
    a = access_to(db, user, repo)
    return RepoWithAccess(repo, a, _counts(db, [(repo, a)])[repo.id])


def list_deleted(db: Session) -> list[DocRepo]:
    return list(db.scalars(
        select(DocRepo).join(HierarchyNode, HierarchyNode.id == DocRepo.hierarchy_node_id)
        .where(HierarchyNode.status == NodeStatus.DELETED.value)
        .options(selectinload(DocRepo.node), selectinload(DocRepo.created_by))
        .order_by(HierarchyNode.deleted_at.desc())
    ))


# --------------------------------------------------------------------------- changes


def _require_unique_name(db: Session, name: str, other_than: uuid.UUID | None = None) -> None:
    root = access.root_node(db, SystemCode.DOC_HUB)
    for node in access.children(db, root):
        if node.name.casefold() == name.casefold() and node.id != other_than:
            raise Conflict(f"There's already a repository called {node.name!r}.")


def create_repo(db: Session, actor: AppUser, name: str, description: str,
                fields: list[tuple[str, str]] | None) -> DocRepo:
    """Create a repository; the creator becomes its owner. Commits."""
    name = " ".join(name.split())
    if not name:
        raise InvalidRequest("Enter a repository name.")
    _require_unique_name(db, name)
    root = access.root_node(db, SystemCode.DOC_HUB)
    node = access.create_child(db, actor, root, NodeType.DOC_REPO, name)
    repo = DocRepo(hierarchy_node_id=node.id, description=description.strip(), created_by_id=actor.id)
    db.add(repo)
    db.flush()
    pairs = fields if fields is not None else [(label, "") for label in metadata.DEFAULT_REPOSITORY_FIELDS]
    metadata.set_node_metadata(db, actor, node, pairs)
    approvals.register_resource(db, SystemCode.DOC_HUB.value, RESOURCE_TYPE, str(repo.id), name, node.id)
    workflow_steps.bind_default(db, node.id, actor.id)  # its owner or admins can choose another
    db.commit()
    return get_repo(db, repo.id)


def update_repo(db: Session, actor: AppUser, repo: DocRepo, name: str, description: str) -> DocRepo:
    name = " ".join(name.split())
    if not name:
        raise InvalidRequest("Enter a repository name.")
    before = {"name": repo.node.name, "description": repo.description}
    if name != repo.node.name:
        _require_unique_name(db, name, other_than=repo.node.id)
        repo.node.name = name
        approvals.rename_resource(db, SystemCode.DOC_HUB.value, RESOURCE_TYPE, str(repo.id), name)
    repo.description = description.strip()
    after = {"name": repo.node.name, "description": repo.description}
    if before != after:
        access.record(db, actor, "NODE_UPDATED", "node", str(repo.node.id), repo.node.id, audit.diff(before, after))
    db.commit()
    return get_repo(db, repo.id)


def set_repo_metadata(db: Session, actor: AppUser, repo: DocRepo, pairs: list[tuple[str, str]]) -> None:
    before = {e.field.label: e.value for e in metadata.node_entries(db, repo.node.id)}
    metadata.set_node_metadata(db, actor, repo.node, pairs)
    after = {e.field.label: e.value for e in metadata.node_entries(db, repo.node.id)}
    if before != after:
        access.record(db, actor, "REPOSITORY_METADATA_SET", "node", str(repo.node.id), repo.node.id,
                      audit.diff(before, after))
    db.commit()


def delete_repo(db: Session, actor: AppUser, repo: DocRepo) -> None:
    """Soft delete: hidden everywhere, everything kept; its pending approvals are cancelled. Commits."""
    access.soft_delete(db, actor, repo.node)
    approvals.set_resource_active(db, SystemCode.DOC_HUB.value, RESOURCE_TYPE, str(repo.id), False, actor)
    for doc in db.scalars(select(Document).where(Document.doc_repo_id == repo.id,
                                                  Document.status == S.PENDING.value)):
        doc.status = S.DRAFT.value  # its request was cancelled; the maker can submit again after a restore
    db.commit()


def restore_repo(db: Session, actor: AppUser, repo: DocRepo) -> DocRepo:
    """Platform admins: bring a deleted repository back. Commits."""
    _require_unique_name(db, repo.node.name, other_than=repo.node.id)
    access.restore(db, actor, repo.node)
    approvals.register_resource(db, SystemCode.DOC_HUB.value, RESOURCE_TYPE, str(repo.id), repo.node.name, repo.node.id)
    db.commit()
    return get_repo(db, repo.id)
