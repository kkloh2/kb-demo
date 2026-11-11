"""Authentication: sign-in with LAN ID and password, JWT access tokens, sessions, sign-out.

The password is checked by the directory (ldap.py); Data Hub stores no passwords.
Auth is self-contained: it imports no other feature. People are identified by LAN ID; other
modules (users, ...) take part in sign-in through hooks.py and require sign-in with CurrentUser.

    router.py        HTTP endpoints under /api/auth (login, logout, me)
    dependencies.py  CurrentUser: the FastAPI dependency other modules use to require sign-in
    service.py       sign-in, token -> Principal, sign-out
    identity.py      Identity (who the directory verified) and Principal (the signed-in caller)
    hooks.py         on_sign_in: let other modules record a sign-in, add token claims, or refuse it
    ldap.py          the directory: LAN ID + password -> (department, display_name, email, title),
                     from a real LDAP / Active Directory server (ldap3) or, for the demo and tests,
                     a YAML stand-in (backend/ldap-directory.yaml); see settings.directory
    security.py      JWT encoding/decoding
    models.py        auth_sessions table
    schemas.py       request and response bodies
    errors.py        Unauthenticated (401), DirectoryUnavailable (503)

Account lockout and password policy are left to the directory.
Settings (JWT, directory file) live in app.core.config with the rest.
"""
