import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../api/http";
import { getProject, PROJECT_ROLE_NAMES, type Project } from "../../api/projects";
import { ChevronIcon, EditIcon, FolderIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { timeAgo } from "../../lib/time";
import { DocumentsTab } from "./DocumentsTab";
import { FieldsEditor } from "./FieldsEditor";
import { MembersTab } from "./MembersTab";
import { ProjectForm } from "./ProjectForm";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css";
import "../../styles/kb-detail.css";
import "../../styles/projects.css";

type Tab = "documents" | "metadata" | "members" | "activity";

interface Props {
  token: string;
  projectId: number;
  onBack: () => void;
  onSessionEnded: (message: string) => void;
}

/** One project: its documents, base metadata, members (department admins) and activity. */
export function ProjectDetailPage({ token, projectId, onBack, onSessionEnded }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("documents");
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);

  const load = useCallback(() => {
    getProject(token, projectId)
      .then(setProject)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load the project.");
      });
  }, [token, projectId, onSessionEnded]);
  useEffect(load, [load]);

  const back = (
    <button type="button" className="back-link" onClick={onBack}>
      <ChevronIcon dir="left" />
      All projects
    </button>
  );

  if (!project) {
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

  const { access } = project;
  const tabs: { key: Tab; label: string }[] = [
    { key: "documents", label: docCount === null ? "Documents" : `Documents (${docCount})` },
    { key: "metadata", label: "Metadata" },
    ...(access.manage ? [{ key: "members" as Tab, label: "Members" }] : []),
    { key: "activity", label: "Activity" },
  ];

  return (
    <div className="page">
      {back}

      <header className="kb-head">
        <div className="kb-head__title-row">
          <span className="kb-head__icon">
            <FolderIcon />
          </span>
          <h1 className="kb-head__title">{project.name}</h1>
        </div>
        {project.description && <p className="kb-head__desc">{project.description}</p>}
        <p className="kb-head__meta">
          <span className="badge">{project.department.name}</span>
          {access.manage && <span className="badge badge--neutral">Department admin</span>}
          {access.project_roles.map((r) => (
            <span key={r} className="badge badge--neutral">
              {PROJECT_ROLE_NAMES[r]}
            </span>
          ))}
          <span className="muted">Updated {timeAgo(project.updated_at)}</span>
        </p>
      </header>

      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}

      <div className="tabs" role="tablist" aria-label="Project">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" id={`project-tab-${t.key}`} aria-selected={tab === t.key}
            aria-controls={`project-panel-${t.key}`} className="tab" onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`project-panel-${tab}`} aria-labelledby={`project-tab-${tab}`}>
        {tab === "documents" && (
          <DocumentsTab token={token} project={project} onSessionEnded={onSessionEnded} onCountChange={setDocCount} />
        )}

        {tab === "metadata" && (
          <section className="panel" aria-labelledby="metadata-title">
            <div className="panel__head">
              <div>
                <h2 id="metadata-title" className="panel__title">
                  Base metadata
                </h2>
                <p className="panel__desc">
                  Every document in this project starts with these values. A maker can override them per document.
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
              {[
                ["Department", `${project.department.name} (${project.department.code})`],
                ["Country", project.country],
                ["Business unit", project.business_unit],
                ["Purpose", project.purpose],
                ["Valid till", project.valid_till ? new Date(`${project.valid_till}T00:00:00`).toLocaleDateString() : ""],
                ["Created by", project.created_by ?? ""],
                ["Created", new Date(project.created_at).toLocaleString()],
              ].map(([label, value]) => (
                <div key={label} className="meta-list__row">
                  <dt>{label}</dt>
                  <dd>{value || <span className="muted">Not set</span>}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {tab === "metadata" && (
          <FieldsEditor token={token} projectId={project.id} canEdit={access.manage} onSessionEnded={onSessionEnded} />
        )}

        {tab === "members" && access.manage && (
          <MembersTab token={token} project={project} onSessionEnded={onSessionEnded} />
        )}

        {tab === "activity" && (
          <div className="kb-table-panel">
            <p className="kb-message">
              The project's history (uploads, metadata changes, approvals) appears here once the platform's audit
              module is in place.
            </p>
          </div>
        )}
      </div>

      <Modal open={editing} title={`Edit ${project.name}`} onClose={() => setEditing(false)}>
        {editing && (
          <ProjectForm
            token={token}
            existing={project}
            onCancel={() => setEditing(false)}
            onSaved={(p) => {
              setEditing(false);
              setProject(p);
              setNotice(`Saved ${p.name}.`);
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </div>
  );
}
