"""A resource keeps its node itself: resource.hierarchy_node_id; resource_hierarchy_binding goes.

Each resource had exactly one binding (nothing moves a resource), so its node moves onto it: the
active binding's, or else the latest one's.

Revision ID: 0011
Revises: 0010
Created: 2026-11-16 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.base
from app.db.base import utcnow, uuid7

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

U, S, TS = sa.Uuid(), sa.String(), app.db.base.UTCDateTime()
resource = sa.table("resource", sa.column("id", U), sa.column("hierarchy_node_id", U), sa.column("status", S))
binding = sa.table("resource_hierarchy_binding", sa.column("id", U), sa.column("resource_pk", U),
                   sa.column("hierarchy_node_id", U), sa.column("status", S), sa.column("created_at", TS),
                   sa.column("updated_at", TS))
ONE_ACTIVE = "status = 'ACTIVE'"


def _sqlite_foreign_keys(on: bool) -> None:
    """Off while resource is rebuilt (approval_request references it); checked when back on."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if on else 'OFF'}")
    if on:
        problems = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Foreign key problems after the rebuild: {problems[:5]}")


def upgrade() -> None:
    _sqlite_foreign_keys(False)
    with op.batch_alter_table('resource', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hierarchy_node_id', U, nullable=True))
    bind = op.get_bind()
    for resource_id, in bind.execute(sa.select(resource.c.id)).all():
        node = bind.execute(sa.select(binding.c.hierarchy_node_id).where(binding.c.resource_pk == resource_id)
                            .order_by((binding.c.status == "ACTIVE").desc(), binding.c.created_at.desc())).scalar()
        if node is None:
            raise RuntimeError(f"Resource {resource_id} has no node.")
        bind.execute(resource.update().where(resource.c.id == resource_id).values(hierarchy_node_id=node))
    with op.batch_alter_table('resource', schema=None) as batch_op:
        batch_op.alter_column('hierarchy_node_id', existing_type=U, nullable=False)
    with op.batch_alter_table('resource_hierarchy_binding', schema=None) as batch_op:
        batch_op.drop_index('uq_resource_hierarchy_binding_one_active', sqlite_where=sa.text(ONE_ACTIVE),
                            postgresql_where=sa.text(ONE_ACTIVE))
    op.drop_table('resource_hierarchy_binding')
    _sqlite_foreign_keys(True)


def downgrade() -> None:
    _sqlite_foreign_keys(False)
    op.create_table(
        'resource_hierarchy_binding',
        sa.Column('id', U, nullable=False), sa.Column('resource_pk', U, nullable=False),
        sa.Column('hierarchy_node_id', U, nullable=False), sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', TS, nullable=False), sa.Column('updated_at', TS, nullable=False),
        sa.ForeignKeyConstraint(['resource_pk'], ['resource.id'], name='fk_resource_hierarchy_binding_resource_pk_resource'),
        sa.PrimaryKeyConstraint('id', name='pk_resource_hierarchy_binding'),
    )
    with op.batch_alter_table('resource_hierarchy_binding', schema=None) as batch_op:
        batch_op.create_index('uq_resource_hierarchy_binding_one_active', ['resource_pk'], unique=True,
                              sqlite_where=sa.text(ONE_ACTIVE), postgresql_where=sa.text(ONE_ACTIVE))
    bind = op.get_bind()
    now = utcnow()
    for resource_id, node, status in bind.execute(sa.select(resource.c.id, resource.c.hierarchy_node_id,
                                                            resource.c.status)).all():
        bind.execute(binding.insert().values(id=uuid7(), resource_pk=resource_id, hierarchy_node_id=node,
                                             status=status, created_at=now, updated_at=now))
    with op.batch_alter_table('resource', schema=None) as batch_op:
        batch_op.drop_column('hierarchy_node_id')
    _sqlite_foreign_keys(True)
