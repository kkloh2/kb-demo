"""Directory sign-in: LAN ID + password -> (department, display_name, email, title).

Two directories, chosen by settings.directory:

    "ldap"  a real LDAP / Active Directory server, through ldap3. Sign-in binds as the person with
            their own LAN ID and password (settings.ldap_bind_format), then reads their own entry
            (settings.ldap_search_base / ldap_search_filter). No service account is needed.
    "yaml"  a local file stands in for the directory (settings.ldap_directory_file); passwords are
            compared as written. For the demo and tests only.

Either way, `authenticate` returns None for a wrong password, an unknown LAN ID, or an account the
directory refuses (locked, disabled, expired), and raises DirectoryUnavailable when the directory
can't answer. The rest of auth relies on `authenticate` alone.
"""

import hmac
import logging
import re
import ssl
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from ldap3 import NONE, SUBTREE, SYNC, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.core.results import RESULT_INVALID_CREDENTIALS
from ldap3.utils.conv import escape_filter_chars

from app.auth.errors import DirectoryUnavailable
from app.core.config import get_settings

log = logging.getLogger("datahub.auth.ldap")

_UNAVAILABLE = "Sign-in is unavailable right now. Please try again later."

# LAN IDs are plain account names. Anything else never reaches the directory, so a crafted
# "LAN ID" can't change the meaning of the bind name or the search filter.
_LAN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class LdapUser(NamedTuple):
    """The user's details from their directory entry."""

    department: str
    display_name: str
    email: str
    title: str


def authenticate(lan_id: str, password: str) -> LdapUser | None:
    """Check the LAN ID and password against the directory.

    Returns the user's (department, display_name, email, title), or None when the LAN ID is
    unknown, the password is wrong, or the directory refuses the account. These cases
    deliberately look the same to the caller. Raises DirectoryUnavailable when the directory
    can't answer.
    """
    lan_id = lan_id.strip().lower()
    if not password or not _LAN_ID.match(lan_id):
        # An empty password would be an "unauthenticated bind", which LDAP servers accept.
        return None
    if get_settings().directory == "ldap":
        return _ldap_authenticate(lan_id, password)
    return _yaml_authenticate(lan_id, password)


# --------------------------------------------------------------------------- LDAP (ldap3)

_CLIENT_STRATEGY = SYNC  # tests swap in ldap3's MOCK_SYNC


def _server() -> Server:
    s = get_settings()
    tls = Tls(
        validate=ssl.CERT_REQUIRED,
        ca_certs_file=str(s.ldap_ca_certs_file) if s.ldap_ca_certs_file else None,
    )
    return Server(s.ldap_server_url, connect_timeout=s.ldap_timeout_seconds, tls=tls, get_info=NONE)


def _ldap_authenticate(lan_id: str, password: str) -> LdapUser | None:
    s = get_settings()
    attributes = {
        "display_name": s.ldap_attribute_display_name,
        "email": s.ldap_attribute_email,
        "department": s.ldap_attribute_department,
        "title": s.ldap_attribute_title,
    }
    connection = Connection(
        _server(),
        user=s.ldap_bind_format.format(lan_id=lan_id),
        password=password,
        client_strategy=_CLIENT_STRATEGY,
        receive_timeout=s.ldap_timeout_seconds,
        read_only=True,
        raise_exceptions=False,
    )
    try:
        if s.ldap_start_tls:
            connection.open()
            connection.start_tls()
        if not connection.bind():
            if connection.result.get("result") == RESULT_INVALID_CREDENTIALS:
                # Wrong password, unknown LAN ID, or a locked / disabled / expired account.
                return None
            log.error("LDAP bind for %r failed: %s", lan_id, connection.result)
            raise DirectoryUnavailable(_UNAVAILABLE)

        found = connection.search(
            s.ldap_search_base,
            s.ldap_search_filter.format(lan_id=escape_filter_chars(lan_id)),
            search_scope=SUBTREE,
            attributes=[*attributes.values(), "userPrincipalName"],
            size_limit=2,
        )
        if not found or len(connection.entries) != 1:
            # The person proved their password but their own entry can't be read: a setting
            # (search base, filter) is wrong, not the password.
            log.error("LDAP search for %r found %d entries: %s", lan_id, len(connection.entries), connection.result)
            raise DirectoryUnavailable(_UNAVAILABLE)
        values = connection.entries[0].entry_attributes_as_dict
    except LDAPException as exc:  # can't connect, timeout, TLS failure, ...
        log.error("LDAP server %s unavailable: %s", s.ldap_server_url, exc)
        raise DirectoryUnavailable(_UNAVAILABLE) from None
    finally:
        connection.unbind()

    def first(attribute: str) -> str:
        found = values.get(attribute) or []
        return str(found[0]).strip() if found else ""

    email = first(attributes["email"]) or first("userPrincipalName")
    if not email:
        log.error("LDAP entry for %r has no %s or userPrincipalName", lan_id, attributes["email"])
        raise DirectoryUnavailable(_UNAVAILABLE)
    return LdapUser(
        department=first(attributes["department"]),
        display_name=first(attributes["display_name"]) or lan_id,
        email=email.lower(),
        title=first(attributes["title"]),
    )


# --------------------------------------------------------------------------- YAML stand-in

_YAML_FIELDS = ("department", "display_name", "email", "title")


def _yaml_authenticate(lan_id: str, password: str) -> LdapUser | None:
    entry = _read_directory(get_settings().ldap_directory_file).get(lan_id)
    if not isinstance(entry, dict):
        return None
    if not hmac.compare_digest(str(entry.get("password", "")).encode(), password.encode()):
        return None
    missing = [f for f in _YAML_FIELDS if not entry.get(f)]
    if missing:
        log.error("Directory entry %r is missing %s", lan_id, ", ".join(missing))
        raise DirectoryUnavailable(_UNAVAILABLE)
    return LdapUser(*(str(entry[f]) for f in _YAML_FIELDS))


def _read_directory(path: Path) -> dict[str, Any]:
    """The directory's users, keyed by lower-case LAN ID."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.error("Can't read the directory file %s: %s", path, exc)
        raise DirectoryUnavailable(_UNAVAILABLE) from None
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, dict):
        log.error("Directory file %s has no 'users' mapping", path)
        raise DirectoryUnavailable(_UNAVAILABLE)
    return {str(k).strip().lower(): v for k, v in users.items()}
