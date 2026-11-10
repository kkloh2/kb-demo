"""Users: Data Hub's own record of each person, keyed by LAN ID, and their roles.

    models.py   users, departments (org units), roles, user_system_roles, user_org_unit_roles
    hooks.py    the auth sign-in hooks: record_sign_in (create or refresh the user, give PUBLIC)
                and add_roles_claim (put system_roles and org_unit_roles in the token)
    service.py  lookups; creating departments; granting and revoking roles (who may grant what);
                reading a caller's roles from their token (system_roles_of, org_unit_roles_of)
    seed.py     demo departments (RISK, HR)

Token claims added at sign-in:
    "system_roles":   ["PUBLIC", "SYSTEM_ADMIN"]
    "org_unit_roles": {"RISK": ["CHECKER", "VIEWER"], "HR": ["VIEWER"]}

Depends on auth (Identity, and later CurrentUser for its endpoints); auth never imports users.
Planned here: deactivating users (refuse sign-in from hooks.record_sign_in).
"""
