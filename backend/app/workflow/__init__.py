"""Approval workflows, as a standalone module.

    app/workflow/
    ├── engine.py     WorkflowEngine contract + engine registry (BPMN-shaped: tasks, lanes, data)
    ├── builtin.py    built-in engines (today: builtin.single_review)
    ├── handlers.py   SubjectHandler contract: how a subject type (e.g. document) plugs in
    ├── models.py     workflow_definitions, workflow_instances, workflow_tasks
    └── service.py    start / complete_task / inbox / history

The module knows nothing about documents; app.services.document_approval is the document
handler. A SpiffWorkflow engine ("spiff.bpmn") would be another WorkflowEngine that runs
uploaded BPMN definitions. See docs/approval-workflow.md.
"""

from app.workflow.builtin import SingleReviewEngine
from app.workflow.engine import register_engine

register_engine(SingleReviewEngine())
