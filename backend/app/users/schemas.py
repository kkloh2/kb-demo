from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- departments


class DepartmentIn(BaseModel):
    """POST: the new department. PUT: its full replacement (a different code renames it)."""

    code: str = Field(min_length=1, max_length=32, description='e.g. "RISK" (stored upper-case)')
    name: str = Field(min_length=1, max_length=128, description='e.g. "Risk Management"')


class DepartmentOut(BaseModel):
    id: int
    code: str = Field(description='e.g. "RISK"')
    name: str


# --------------------------------------------------------------------------- users


class UserUpsert(BaseModel):
    """System admins: the user's profile, system roles and the departments they administer."""

    display_name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=256)
    department: str = Field(default="", max_length=128, description="Directory department text, not an org unit")
    title: str = Field(default="", max_length=128)
    system_roles: list[str] = Field(description='Complete list, e.g. ["PUBLIC"]. Others are removed.')
    department_admin_of: list[str] = Field(
        description='Department codes where the user is DEPARTMENT_ADMIN, e.g. ["RISK"]. Complete list.'
    )


class DepartmentRolesIn(BaseModel):
    """Department admins: the user's roles in this department."""

    roles: list[str] = Field(description='Complete list from MAKER, CHECKER, VIEWER, e.g. ["CHECKER", "VIEWER"]. [] for none.')


class UserOut(BaseModel):
    lan_id: str
    display_name: str
    email: str
    department: str
    title: str
    system_roles: list[str]
    org_unit_roles: dict[str, list[str]] = Field(description='e.g. {"RISK": ["CHECKER", "VIEWER"]}')
