"""Document & metadata management: departments group their documents into projects.

A project ("project" is a working name) belongs to one department and holds:
  - base metadata for its documents: country, business unit, purpose, valid till
    (department and created-by come from the project itself); documents copy it and makers may
    override it per document
  - its own members: MAKER (uploads), CHECKER (approves or rejects), VIEWER (sees approved)
    given by the department's admin (resource-based access control)

Who can do what with a project:
    see it in the list      VIEWER or DEPARTMENT_ADMIN of its department, or any project role
    see its documents       a project role, or DEPARTMENT_ADMIN of its department (a viewer by default)
    create / edit / delete  DEPARTMENT_ADMIN of its department; also manages its members

    models.py         projects, project_members
    service.py        the rules above, project and member operations
    authorization.py  @ProjectRoles(...): endpoint guard for one project
    schemas.py        request and response bodies
    routers/          HTTP endpoints

Depends on auth and users; neither imports this module.
"""
