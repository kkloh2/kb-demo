"""Directory sign-in (LDAP / Active Directory).

For now the directory is a YAML file (settings.ldap_directory_file, default
backend/ldap-directory.yaml) and the password is compared as written. Replacing this with a real
LDAP bind only changes this module: the rest of auth relies on `authenticate` alone.
"""

import hmac
import logging
from pathlib import Path
from typing import NamedTuple

import yaml

from app.auth.errors import DirectoryUnavailable
from app.core.config import get_settings

log = logging.getLogger("datahub.auth.ldap")

_FIELDS = ("department", "display_name", "email", "title")
_UNAVAILABLE = "Sign-in is unavailable right now. Please try again later."


class LdapUser(NamedTuple):
    """The user's details from their directory entry."""

    department: str
    display_name: str
    email: str
    title: str


def authenticate(lan_id: str, password: str) -> LdapUser | None:
    """Check the LAN ID and password against the directory.

    Returns the user's (department, display_name, email, title), or None when the LAN ID is
    unknown or the password is wrong. The two cases deliberately look the same to the caller.
    Raises DirectoryUnavailable when the directory can't answer.
    """
    entry = _read_directory(get_settings().ldap_directory_file).get(lan_id.strip().lower())
    if not isinstance(entry, dict):
        return None
    if not hmac.compare_digest(str(entry.get("password", "")).encode(), password.encode()):
        return None
    missing = [f for f in _FIELDS if not entry.get(f)]
    if missing:
        log.error("Directory entry %r is missing %s", lan_id, ", ".join(missing))
        raise DirectoryUnavailable(_UNAVAILABLE)
    return LdapUser(*(str(entry[f]) for f in _FIELDS))


def _read_directory(path: Path) -> dict:
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
