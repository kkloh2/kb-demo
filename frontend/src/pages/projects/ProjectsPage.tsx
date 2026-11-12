import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api/http";
import { deleteProject, listProjects, PROJECT_ROLE_NAMES, type Project } from "../../api/projects";
import {
  EditIcon,
  FolderIcon,
  GridIcon,
  ListIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
} from "../../components/Icons";
import { Menu, type MenuItem } from "../../components/Menu";
import { Modal } from "../../components/Modal";
import { tokenClaims } from "../../lib/token";
import { timeAgo } from "../../lib/time";
import { ConfirmDelete } from "../admin/common";
import { ProjectForm } from "./ProjectForm";
import { ProjectTable } from "./ProjectTable";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css"; // modal and form styles
import "../../styles/kb-detail.css"; // menu styles

type View = "grid" | "list";
const VIEW_KEY = "dh.projectView";

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

interface Props {
  token: string;
  onSessionEnded: (message: string) => void;
}

/** Landing page: the projects of the caller's departments, and any project they hold a role in. */
export function ProjectsPage({ token, onSessionEnded }: Props) {
  const [items, setItems] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>(readView);
  const [editing, setEditing] = useState<{ project: Project | null } | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Department admins can create projects: from the token, for the button only.
  const orgRoles = tokenClaims(token).org_unit_roles ?? {};
  const canCreate = Object.values(orgRoles).some((roles) => roles.includes("DEPARTMENT_ADMIN"));

  const load = useCallback(() => {
    listProjects(token)
      .then(setItems)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load projects.");
      });
  }, [token, onSessionEnded]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items || !q) return items ?? [];
    return items.filter((p) =>
      [p.name, p.description, p.department.name, p.department.code, p.purpose, p.business_unit, p.country]
        .some((v) => v.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const stats = useMemo(() => {
    if (!items) return null;
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    return {
      total: items.length,
      departments: new Set(items.map((p) => p.department.code)).size,
      mine: items.filter((p) => p.access.project_roles.length > 0).length,
      recent: items.filter((p) => new Date(p.updated_at).getTime() >= weekAgo).length,
    };
  }, [items]);

  function changeView(v: View) {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* preference just won't be remembered */
    }
  }

  const menuItems = (p: Project): MenuItem[] =>
    p.access.manage
      ? [
          { label: "Edit", icon: <EditIcon />, onSelect: () => setEditing({ project: p }) },
          { label: "Delete", icon: <TrashIcon />, danger: true, onSelect: () => setDeleting(p) },
        ]
      : [];

  return (
    <div className="page">
      <h1 className="page__title">Projects</h1>

      <ul className="stats" aria-label="Summary">
        {[
          { label: "Projects", value: stats?.total },
          { label: "Departments", value: stats?.departments },
          { label: "With a role for me", value: stats?.mine },
          { label: "Updated this week", value: stats?.recent },
        ].map((s) => (
          <li key={s.label} className="stat">
            <span className="stat__value">{s.value ?? "–"}</span>
            <span className="stat__label">{s.label}</span>
          </li>
        ))}
      </ul>

      <section aria-labelledby="all-projects">
        <div className="section-head">
          <h2 id="all-projects" className="section-head__title">
            All projects
          </h2>
          {canCreate && (
            <button type="button" className="btn-primary" onClick={() => setEditing({ project: null })}>
              <PlusIcon />
              Create project
            </button>
          )}
        </div>

        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}

        <div className="toolbar">
          <label className="search">
            <SearchIcon />
            <input
              type="search"
              placeholder="Search projects"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search projects"
            />
          </label>

          <div className="view-toggle" role="group" aria-label="View">
            <button type="button" aria-pressed={view === "list"} aria-label="List view" title="List view"
              onClick={() => changeView("list")}>
              <ListIcon />
            </button>
            <button type="button" aria-pressed={view === "grid"} aria-label="Grid view" title="Grid view"
              onClick={() => changeView("grid")}>
              <GridIcon />
            </button>
          </div>
        </div>

        {error ? (
          <p className="kb-message kb-message--error" role="alert">
            {error}
          </p>
        ) : items === null ? (
          <p className="kb-message">Loading projects…</p>
        ) : filtered.length === 0 ? (
          <p className="kb-message">
            {query
              ? `No projects match “${query}”.`
              : canCreate
                ? "No projects yet. Use Create project to add the first one."
                : "No projects to show. Projects appear here once you're a viewer in a department, or a department admin gives you a role in one."}
          </p>
        ) : view === "grid" ? (
          <ul className="kb-grid">
            {filtered.map((p) => (
              <li key={p.id} className="kb-card">
                <div className="kb-card__head">
                  <span className="kb-card__icon">
                    <FolderIcon />
                  </span>
                  <a className="kb-card__name" href={`#project/${p.id}`}>
                    {p.name}
                  </a>
                  {p.access.manage && (
                    <div className="kb-card__actions">
                      <Menu
                        trigger={(props) => (
                          <button type="button" className="kb-icon-btn" aria-label={`More actions for ${p.name}`}
                            title="More actions" {...props}>
                            <MoreIcon />
                          </button>
                        )}
                        items={menuItems(p)}
                      />
                    </div>
                  )}
                </div>
                <p className="kb-card__desc">{p.description || <span className="muted">No description</span>}</p>
                <div className="kb-card__foot">
                  <span className="kb-card__updated">Updated {timeAgo(p.updated_at)}</span>
                  <span className="kb-card__dept" title={p.department.name}>
                    <span className="kb-card__dept-name">{p.department.name}</span>
                    {p.access.project_roles.map((r) => (
                      <span key={r} className="kb-badge">
                        {PROJECT_ROLE_NAMES[r]}
                      </span>
                    ))}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <ProjectTable items={filtered} menuItems={menuItems} />
        )}
      </section>

      <Modal
        open={editing !== null}
        title={editing?.project ? `Edit ${editing.project.name}` : "Create project"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <ProjectForm
            token={token}
            existing={editing.project}
            onCancel={() => setEditing(null)}
            onSaved={(p, created) => {
              setEditing(null);
              setNotice(created
                ? `Created ${p.name} in ${p.department.name}. Open it to add members.`
                : `Saved ${p.name}.`);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete project" onClose={() => setDeleting(null)}>
        {deleting && (
          <ConfirmDelete
            message={<>Delete <strong>{deleting.name}</strong> and its members? This can't be undone.</>}
            confirmLabel="Delete project"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              await deleteProject(token, deleting.id);
              setDeleting(null);
              setNotice(`Deleted ${deleting.name}.`);
              load();
            }}
          />
        )}
      </Modal>
    </div>
  );
}
