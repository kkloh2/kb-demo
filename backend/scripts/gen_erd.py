"""Write docs/erd.html (a Mermaid ER diagram) from the app's SQLAlchemy models.

Run from backend/: .venv/bin/python scripts/gen_erd.py ../docs/erd.html
Then render docs/erd.png from it (a headless browser screenshot of the #d element).
Foreign keys become solid lines. Approvals refers to the access model by plain UUIDs ("logical",
so it can become a separate service): those are listed below and drawn dotted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/, so `app` imports

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.types import JSON

import app.main  # noqa: F401  (registers every model)
from app.db.base import Base

LOGICAL = {  # table.column -> table it refers to without a foreign key
    "approval_type.source_system_id": "source_system",
    "resource.source_system_id": "source_system",
    "resource.hierarchy_node_id": "hierarchy_node",
    "approval_request.source_system_id": "source_system",
    "approval_request.requested_by": "app_user",
    "approval_request.maker_id": "app_user",
    "approval_request.subject_id": "document",
    "approval_task_assignment.group_id": "user_group",
    "approval_task_assignment.hierarchy_node_id": "hierarchy_node",
    "approval_task_assignment.required_role_id": "role",
    "approval_task_assignee.user_id": "app_user",
    "approval_decision.decided_by": "app_user",
    "approval_event.actor_id": "app_user",
    "workflow_binding.hierarchy_node_id": "hierarchy_node",
    "workflow_binding.bound_by_id": "app_user",
    "workflow_instance.hierarchy_node_id": "hierarchy_node",
    "workflow_instance.subject_id": "approval_request",
    "audit_event.hierarchy_node_id": "hierarchy_node",
}


def type_name(col) -> str:
    t = col.type
    for cls, name in ((Uuid, "uuid"), (BigInteger, "bigint"), (Integer, "int"), (Boolean, "bool"),
                      (JSON, "json"), (Text, "text"), (String, "string"), (DateTime, "timestamptz")):
        if isinstance(t, cls):
            return name
    return "timestamptz" if "DateTime" in type(t).__name__ else type(t).__name__.lower()


def main(out: str) -> None:
    tables = Base.metadata.tables
    lines = ["erDiagram"]
    for name in sorted(tables):
        table = tables[name]
        for col in table.columns:
            for fk in col.foreign_keys:
                parent = fk.column.table.name
                optional = "o|" if col.nullable else "||"
                lines.append(f'    {parent} {optional}--o{{ {name} : "{col.name}"')
    for ref, parent in LOGICAL.items():
        child, col = ref.split(".")
        lines.append(f'    {parent} ||..o{{ {child} : "{col} (logical)"')
    for name in sorted(tables):
        table = tables[name]
        single_unique = {next(iter(c.columns)).name for c in table.constraints
                         if c.__class__.__name__ == "UniqueConstraint" and len(c.columns) == 1}
        single_unique |= {c.name for c in table.columns if c.unique}
        lines.append(f"    {name} {{")
        for col in table.columns:
            keys = []
            if col.primary_key:
                keys.append("PK")
            if col.foreign_keys:
                keys.append("FK")
            if col.name in single_unique and not col.primary_key:
                keys.append("UK")
            note = f' "logical: {LOGICAL[f"{name}.{col.name}"]}"' if f"{name}.{col.name}" in LOGICAL else ""
            key = f" {', '.join(keys)}" if keys else ""
            lines.append(f"        {type_name(col)} {col.name}{key}{note}")
        lines.append("    }")
    diagram = "\n".join(lines)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Data Hub ERD</title>
<style>body{{margin:0;background:#fff;font-family:'Open Sans',Arial,sans-serif}} #d{{padding:24px;display:inline-block}}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
</head><body><div id="d"><pre class="mermaid">
{diagram}
</pre></div>
<script>mermaid.initialize({{startOnLoad: true, theme: "neutral", er: {{useMaxWidth: false}}, maxTextSize: 200000}});</script>
</body></html>
"""
    with open(out, "w") as f:
        f.write(html)
    print(f"{len(tables)} tables, {sum(1 for l in lines if '--' in l or '..' in l)} relationships -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
