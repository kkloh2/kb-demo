"""Who someone is, as far as auth knows: their LAN ID and the details the directory returned."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Identity:
    """A person the directory has just verified."""

    lan_id: str
    display_name: str
    email: str
    department: str
    title: str


@dataclass(frozen=True)
class Principal(Identity):
    """The signed-in caller of a request, read from their access token."""

    session_id: str
    # Claims added by sign-in hooks (e.g. "system_roles"), read-only. Auth doesn't interpret them;
    # the module that added a claim reads it back (e.g. app.users.service.org_unit_roles_of).
    claims: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
