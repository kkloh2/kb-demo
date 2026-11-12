"""Document & metadata management: departments group their documents into doc-repos.

A doc-repo (document repository) belongs to one department and holds:
  - department metadata for its documents (one JSON value): department, business unit, country
    (department and created-by come from the doc-repo itself); documents copy it and makers may
    override it per document
  - its own members: MAKER (uploads), CHECKER (approves or rejects), VIEWER (sees approved)
    given by the department's admin (resource-based access control)

Who can do what with a doc-repo:
    see it in the list      VIEWER or DEPARTMENT_ADMIN of its department, or any doc-repo role
    see its documents       a doc-repo role, or DEPARTMENT_ADMIN of its department (a viewer by default)
    create / edit / delete  DEPARTMENT_ADMIN of its department; also manages its members

    models.py         doc_repos, doc_repo_members, doc_repo_fields, documents, document_values
    service.py        the rules above, doc-repo and member operations
    authorization.py  @DocRepoRoles(...): endpoint guard for one doc-repo
    schemas.py        request and response bodies
    routers/          HTTP endpoints

Depends on auth and users; neither imports this module.
"""
