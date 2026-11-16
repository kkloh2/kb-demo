"""Access: people, the source systems' trees, groups, roles and permissions (the audit trail is app.audit).

    catalog.py        roles, permissions, which roles carry which, tree levels, root and repository
                      group roles (defined in code, synced at start-up)
    models.py         app_user, role, permission, role_permission, user_group, user_group_member,
                      user_group_member_role, node_team_grant, default_grant (source
                      systems and their trees are in app.sources)
    service.py        the access check (can), sign-in hooks, user groups and people's roles in them,
                      nodes, teams, users, record() (adds an app.audit event), and on_roles_changed (other features, e.g.
                      approvals, react when roles change)
    authorization.py  @Can(permission, at=Root(...) | Param(...)) endpoint guards; PlatformAdmin
    router.py         /api/me/access and the platform admin endpoints

Token claim added at sign-in: "system_roles": {"PLATFORM": ["ADMIN"], "DOC_HUB": ["VIEWER"]},
the roles held at each system's root. Everything else is read from the database per request.
"""
