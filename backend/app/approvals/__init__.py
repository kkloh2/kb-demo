"""Approvals (CAMS), first version: one queue for every module's approvals.

    models.py   approval_type, resource (with its node), approval_request, approval_task,
                approval_task_assignment, approval_task_assignee, approval_decision, approval_event
    hooks.py    ApprovalKind: how a module registers what it gets approved (and reacts to decisions)
    service.py  request_approval, inbox, decide, cancel, history
    router.py   /api/approvals: the inbox and decisions

Depends on access (who may decide); never on the modules that use it.
"""
