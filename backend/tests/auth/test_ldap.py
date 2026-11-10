"""The directory module on its own: LAN ID + password -> (department, display_name, email, title)."""

import pytest

from app.auth import ldap
from app.auth.errors import DirectoryUnavailable


def test_returns_the_directory_tuple(directory):
    user = ldap.authenticate("analyst", "datahub123")
    assert user == ("Risk Management", "Alex Tan", "alex.tan@datahub.local", "Data Analyst")
    department, display_name, email, title = user
    assert (user.department, user.title) == (department, title)


def test_lan_id_is_case_insensitive(directory):
    assert ldap.authenticate(" ANALYST ", "datahub123") is not None


def test_password_is_compared_as_is(directory):
    assert ldap.authenticate("analyst", "DATAHUB123") is None
    assert ldap.authenticate("analyst", "datahub123 ") is None


def test_wrong_password_and_unknown_user_both_return_none(directory):
    assert ldap.authenticate("analyst", "nope") is None
    assert ldap.authenticate("nobody", "nope") is None


def test_missing_file_means_directory_unavailable(directory):
    directory.unlink()
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "datahub123")


@pytest.mark.parametrize("content", ["users: [", "- just a list", "people: {}"])
def test_unreadable_file_means_directory_unavailable(directory, content):
    directory.write_text(content)
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "datahub123")


def test_entry_missing_a_field_means_directory_unavailable(directory):
    directory.write_text("users:\n  analyst:\n    password: x\n    display_name: Alex Tan\n")
    with pytest.raises(DirectoryUnavailable):
        ldap.authenticate("analyst", "x")


def test_edits_apply_without_restart(directory):
    directory.write_text(directory.read_text().replace("datahub123", "changed"))
    assert ldap.authenticate("analyst", "datahub123") is None
    assert ldap.authenticate("analyst", "changed") is not None
