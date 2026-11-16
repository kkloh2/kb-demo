"""The current request's id and client address, so every event records them without callers passing
them around. Set per request by the middleware in app.main; empty outside a request."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("audit_request_id", default=None)
client_ip: ContextVar[str | None] = ContextVar("audit_client_ip", default=None)
