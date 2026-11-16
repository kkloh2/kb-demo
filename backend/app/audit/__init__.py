"""Audit: who did what, where, when and from where, for every area of Data Hub.

    models.py    audit_action (the registered kinds of event) and audit_event (the trail)
    catalog.py   register_actions(...): each area declares its events (code, area, category, label)
    context.py   the request's id and client address, set by middleware in app.main
    service.py   record(...) (in the caller's transaction), query(...), diff(...)
    router.py    GET /api/audit (platform admins, with filters)

Standalone: it knows nothing about the areas that use it. Events are written in the same
transaction as the change they describe and are never updated or deleted.
"""
