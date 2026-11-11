"""Users: Data Hub's own record of each person, keyed by LAN ID, and their roles.

    models.py   users, departments (org units), roles, user_system_roles, user_org_unit_roles
    hooks.py    the auth sign-in hooks: record_sign_in (create or refresh the user, give PUBLIC)
                and add_roles_claim (put system_roles and org_unit_roles in the token)
    service.py  lookups; create/update/delete departments; upsert/delete users; set a user's roles in a department;
                the rules about roles; reading a caller's roles from their token
    seed.py     demo departments (RISK, HR)
    routers/    endpoints, one router per resource (departments.py, users.py):
                  /api/departments                         POST; PUT, DELETE /{code}   system admin
                  /api/users/{lan_id}                      PUT, DELETE                 system admin
                  /api/departments/{code}/users/{lan_id}   PUT, DELETE                 system admin OR that
                                                                                       department's admin
    authorization.py  @SystemRoles(...) and @OrgUnitRoles(..., department="code"): endpoint guards
                reading the token's roles; stacked on one endpoint they combine with OR
    schemas.py  request and response bodies

Token claims added at sign-in:
    "system_roles":   ["PUBLIC", "SYSTEM_ADMIN"]
    "org_unit_roles": {"RISK": ["CHECKER", "VIEWER"], "HR": ["VIEWER"]}

Depends on auth (Identity, and later CurrentUser for its endpoints); auth never imports users.
Planned here: deactivating users (refuse sign-in from hooks.record_sign_in).
"""
