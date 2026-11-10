"""Base domain error. app.main maps each subclass to an HTTP response with its status code."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
