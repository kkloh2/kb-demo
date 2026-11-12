import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../api/http";
import { DEPARTMENT_METADATA_KEYS, DEPARTMENT_METADATA_LABELS, DOC_REPO_ROLE_NAMES, getDocRepo, type DocRepo } from "../../api/doc-repos";
import { ChevronIcon, EditIcon, FolderIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { timeAgo } from "../../lib/time";
import { DocumentsTab } from "./DocumentsTab";
import { RepositoryMetadataPanel } from "./RepositoryMetadataPanel";
import { MembersTab } from "./MembersTab";
import { DocRepoForm } from "./DocRepoForm";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css";
import "../../styles/kb-detail.css";
import "../../styles/doc-repos.css";

type Tab = "documents" | "metadata" | "members";

interface Props {
  token: string;
  docRepoId: number;
  onBack: () => void;
  onSessionEnded: (message: string) => void;
}

/** One doc-repo: its documents, department metadata, and members (department admins). */
export function DocRepoDetailPage({ token, docRepoId, onBack, onSessionEnded }: Props) {
  const [docRepo, setDocRepo] = useState<DocRepo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("documents");
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);

  const load = useCallback(() => {
    getDocRepo(token, docRepoId)
      .then(setDocRepo)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load the repository.");
      });
  }, [token, docRepoId, onSessionEnded]);
  useEffect(load, [load]);

  const back = (
    <button type="button" className="back-link" onClick={onBack}>
      <ChevronIcon dir="left" />
      All repositories
    </button>
  );

  if (!docRepo) {
    return (
      <div className="page">
        {back}
        {error ? (
          <p className="kb-message kb-message--error" role="alert">
            {error}
          </p>
        ) : (
          <p className="kb-message">Loading…</p>
        )}
      </div>
    );
  }

  const { access } = docRepo;
  const tabs: { key: Tab; label: string }[] = [
    { key: "documents", label: docCount === null ? "Documents" : `Documents (${docCount})` },
    { key: "metadata", label: "Metadata" },
    ...(access.manage ? [{ key: "members" as Tab, label: "Members" }] : []),
  ];

  return (
    <div className="page">
      {back}

      <header className="kb-head">
        <div className="kb-head__title-row">
          <span className="kb-head__icon">
            <FolderIcon />
          </span>
          <h1 className="kb-head__title">{docRepo.name}</h1>
        </div>
        {docRepo.description && <p className="kb-head__desc">{docRepo.description}</p>}
        <p className="kb-head__meta">
          <span className="badge">{docRepo.department.name}</span>
          {access.manage && <span className="badge badge--neutral">Department admin</span>}
          {access.doc_repo_roles.map((r) => (
            <span key={r} className="badge badge--neutral">
              {DOC_REPO_ROLE_NAMES[r]}
            </span>
          ))}
          <span className="muted">Updated {timeAgo(docRepo.updated_at)}</span>
        </p>
      </header>

      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}

      <div className="tabs" role="tablist" aria-label="Repository">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" id={`docRepo-tab-${t.key}`} aria-selected={tab === t.key}
            aria-controls={`docRepo-panel-${t.key}`} className="tab" onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`docRepo-panel-${tab}`} aria-labelledby={`docRepo-tab-${tab}`}>
        {tab === "documents" && (
          <DocumentsTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} onCountChange={setDocCount} />
        )}

        {tab === "metadata" && (
          <section className="panel" aria-labelledby="metadata-title">
            <div className="panel__head">
              <div>
                <h2 id="metadata-title" className="panel__title">
                  Department metadata
                </h2>
                <p className="panel__desc">
                  Every document in this repository starts with these values. A maker can override them per document.
                </p>
              </div>
              {access.manage && (
                <button type="button" className="btn-secondary" onClick={() => setEditing(true)}>
                  <EditIcon />
                  Edit
                </button>
              )}
            </div>
            <dl className="meta-list">
              {DEPARTMENT_METADATA_KEYS.map((k) => (
                <div key={k} className="meta-list__row">
                  <dt>{DEPARTMENT_METADATA_LABELS[k]}</dt>
                  <dd>{docRepo.department_metadata[k] || <span className="muted">Not set</span>}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {tab === "metadata" && (
          <RepositoryMetadataPanel token={token} docRepoId={docRepo.id} pairs={docRepo.repository_metadata}
            canEdit={access.manage} onSessionEnded={onSessionEnded}
            onSaved={(pairs) => setDocRepo((r) => r && { ...r, repository_metadata: pairs })} />
        )}

        {tab === "members" && access.manage && (
          <MembersTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} />
        )}
      </div>

      <Modal open={editing} title={`Edit ${docRepo.name}`} onClose={() => setEditing(false)}>
        {editing && (
          <DocRepoForm
            token={token}
            existing={docRepo}
            onCancel={() => setEditing(false)}
            onSaved={(p) => {
              setEditing(false);
              setDocRepo(p);
              setNotice(`Saved ${p.name}.`);
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </div>
  );
}
