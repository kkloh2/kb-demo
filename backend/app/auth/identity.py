"""Who someone is, as far as auth knows: their LAN ID and the details the directory returned."""

from dataclasses import dataclass


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
