from app.core.errors import DomainError


class Unauthenticated(DomainError):
    status_code = 401


class DirectoryUnavailable(DomainError):
    """The directory (LDAP) could not be reached or answered with an error (not a wrong password)."""

    status_code = 503
