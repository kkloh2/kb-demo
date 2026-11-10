from app.core.errors import DomainError


class Unauthenticated(DomainError):
    status_code = 401


class AccountLocked(DomainError):
    status_code = 423
