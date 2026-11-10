"""Users: Data Hub's own record of each person, keyed by LAN ID, and their roles.

    models.py   users table
    hooks.py    the auth sign-in hooks: record_sign_in (create or refresh the user) and
                add_roles_claim (put {"roles": [...]} in the token)
    service.py  user lookups; roles: lookup_roles (placeholder) and roles_of (read a caller's
                roles from their token)

Depends on auth (Identity, and later CurrentUser for its endpoints); auth never imports users.
Planned here: deactivating users (refuse sign-in from hooks.record_sign_in).
"""
