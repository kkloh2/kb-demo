"""Doc Hub: document repositories, their documents, and metadata.

A repository is a DOC_REPO node in the DOC_HUB tree (app.access): its name, members (OWNER,
ADMIN, MAKER, CHECKER, VIEWER), team grants and soft deletion live there. Documents go through
Approvals (app.approvals) as DOCUMENT_UPLOAD requests: makers submit here, checkers decide on the
Approvals page.

    models.py      doc_repo, document, metadata_field, metadata_value
    metadata.py    fields and values at a node or on a document; inheritance, overrides, freezing
    service.py     repositories: create, edit, delete/restore, who may do what
    documents.py   upload, metadata, submit, delete; the approvals hook (KIND, on_decided)
    routers/       /api/doc-repos...

Depends on access and approvals; neither imports this module.
"""
