"""Users: Data Hub's own record of each person, keyed by LAN ID.

    models.py   users table
    service.py  lookups, and record_sign_in: the auth sign-in hook that creates or refreshes
                a user from the directory details

Depends on auth (Identity, and later CurrentUser for its endpoints); auth never imports users.
Planned here: deactivating users (refuse sign-in from record_sign_in).
"""
