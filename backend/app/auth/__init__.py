"""Authentication: sign-in with LAN ID and password, JWT access tokens, sessions, sign-out.

    router.py        HTTP endpoints under /api/auth (login, logout, me)
    dependencies.py  CurrentUser: the FastAPI dependency other modules use to require sign-in
    service.py       sign-in, lockout, token -> Principal, sign-out
    security.py      password hashing and JWT encoding/decoding
    models.py        users and auth_sessions tables
    schemas.py       request and response bodies
    errors.py        Unauthenticated (401), AccountLocked (423)
    seed.py          demo users

Settings (JWT, password hashing, lockout) live in app.core.config with the rest.
"""
