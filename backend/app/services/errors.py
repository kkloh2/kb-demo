"""Domain errors. app.main maps each to an HTTP response of the same status code."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Unauthenticated(DomainError):
    status_code = 401


class AccountLocked(DomainError):
    status_code = 423


class Forbidden(DomainError):
    status_code = 403


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class InvalidRequest(DomainError):
    status_code = 422
