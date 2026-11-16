import { useCallback, useEffect, useState } from "react";
import { getDocRepo, type DocRepo } from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { ChevronIcon, FolderIcon } from "../../components/Icons";
import { timeAgo } from "../../lib/time";
import { DocumentsTab } from "./DocumentsTab";
import { ActivityTab } from "./ActivityTab";
import { GroupsTab } from "./GroupsTab";
import { WorkflowTab } from "./WorkflowTab";
import { MembersTab } from "./MembersTab";
import { RepositoryMetadataPanel } from "./RepositoryMetadataPanel";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css";
import "../../styles/kb-detail.css";
import "../../styles/doc-repos.css";
import { MessageBar } from "../../components/MessageBar";

type Tab = "documents" | "metadata" | "members" | "groups" | "workflow" | "activity";

interface Props {
  token: string;
  docRepoId: string;
  onBack: () => void;
  onSessionEnded: (message: string) => void;
}

/** One repository: its documents, its metadata fields, and (owner and admins) its members and user groups. */
export function DocRepoDetailPage({ token, docRepoId, onBack, onSessionEnded }: Props) {
  const [docRepo, setDocRepo] = useState<DocRepo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("documents");
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
    ...(access.manage_members
      ? [{ key: "members" as Tab, label: "Users" }, { key: "groups" as Tab, label: "User groups" }]
      : []),
    ...(access.edit ? [{ key: "workflow" as Tab, label: "Workflow" }] : []),
    ...(access.activity ? [{ key: "activity" as Tab, label: "Activity" }] : []),
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
          <span className="muted">Updated {timeAgo(docRepo.updated_at)}</span>
        </p>
      </header>

      {notice && (
        <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>
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
          <RepositoryMetadataPanel token={token} docRepoId={docRepo.id} pairs={docRepo.metadata} canEdit={access.edit}
            onSessionEnded={onSessionEnded} onSaved={(pairs) => setDocRepo((r) => r && { ...r, metadata: pairs })} />
        )}
        {tab === "members" && access.manage_members && (
          <MembersTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} />
        )}
        {tab === "groups" && access.manage_members && (
          <GroupsTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} />
        )}
        {tab === "workflow" && access.edit && (
          <WorkflowTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} />
        )}
        {tab === "activity" && access.activity && (
          <ActivityTab token={token} docRepo={docRepo} onSessionEnded={onSessionEnded} />
        )}
      </div>
    </div>
  );
}
