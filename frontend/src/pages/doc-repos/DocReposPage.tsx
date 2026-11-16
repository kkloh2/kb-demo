import { useCallback, useEffect, useMemo, useState } from "react";
import { canCreateRepos, type MyAccess } from "../../api/access";
import { ApiError } from "../../api/http";
import { deleteDocRepo, listDocRepos, type DocRepo } from "../../api/doc-repos";
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
import { timeAgo } from "../../lib/time";
import { ConfirmDelete } from "../admin/common";
import { DocRepoForm } from "./DocRepoForm";
import { DocRepoTable } from "./DocRepoTable";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css"; // modal and form styles
import "../../styles/kb-detail.css"; // menu styles
import { MessageBar } from "../../components/MessageBar";

type View = "grid" | "list";
const VIEW_KEY = "dh.docRepoView";

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

interface Props {
  token: string;
  access: MyAccess;
  onSessionEnded: (message: string) => void;
}

/** Landing page: every repository; the ones the caller holds a role in can be opened. */
export function DocReposPage({ token, access, onSessionEnded }: Props) {
  const [items, setItems] = useState<DocRepo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>(readView);
  const [editing, setEditing] = useState<{ docRepo: DocRepo | null } | null>(null);
  const [deleting, setDeleting] = useState<DocRepo | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Doc Hub admins create repositories (for the button only; the server checks).
  const canCreate = canCreateRepos(access);

  const load = useCallback(() => {
    listDocRepos(token)
      .then(setItems)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load document repositories.");
      });
  }, [token, onSessionEnded]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items || !q) return items ?? [];
    return items.filter((p) =>
      [p.name, p.description, p.created_by?.display_name ?? "", ...p.metadata.map((m) => m.value)]
        .some((v) => v.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const stats = useMemo(() => {
    if (!items) return null;
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    return {
      documents: items.reduce((n, p) => n + p.document_count, 0),
      repositories: items.length,
      mine: items.filter((p) => p.access.roles.length > 0).length,
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

  const menuItems = (p: DocRepo): MenuItem[] =>
    [
      ...(p.access.edit ? [{ label: "Edit", icon: <EditIcon />, onSelect: () => setEditing({ docRepo: p }) }] : []),
      ...(p.access.delete
        ? [{ label: "Delete", icon: <TrashIcon />, danger: true, onSelect: () => setDeleting(p) }]
        : []),
    ];

  return (
    <div className="page">
      <h1 className="page__title">Document repositories</h1>

      <ul className="stats" aria-label="Summary">
        {[
          { label: "Total documents", value: stats?.documents },
          { label: "Repositories", value: stats?.repositories },
          { label: "With a role for me", value: stats?.mine },
          { label: "Updated this week", value: stats?.recent },
        ].map((s) => (
          <li key={s.label} className="stat">
            <span className="stat__value">{s.value ?? "–"}</span>
            <span className="stat__label">{s.label}</span>
          </li>
        ))}
      </ul>

      <section aria-labelledby="all-docRepos">
        <div className="section-head">
          <h2 id="all-docRepos" className="section-head__title">
            All repositories
          </h2>
          {canCreate && (
            <button type="button" className="btn-primary" onClick={() => setEditing({ docRepo: null })}>
              <PlusIcon />
              Create repository
            </button>
          )}
        </div>

        {notice && (
          <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>
        )}

        <div className="toolbar">
          <label className="search">
            <SearchIcon />
            <input
              type="search"
              placeholder="Search repositories"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search repositories"
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
          <p className="kb-message">Loading repositories…</p>
        ) : filtered.length === 0 ? (
          <p className="kb-message">
            {query
              ? `No repositories match “${query}”.`
              : canCreate
                ? "No repositories yet. Use Create repository to add the first one."
                : "No repositories yet."}
          </p>
        ) : view === "grid" ? (
          <ul className="kb-grid">
            {filtered.map((p) => (
              <li key={p.id} className="kb-card">
                <div className="kb-card__head">
                  <span className="kb-card__icon">
                    <FolderIcon />
                  </span>
                  {p.access.view ? (
                    <a className="kb-card__name" href={`#doc-repo/${p.id}`}>
                      {p.name}
                    </a>
                  ) : (
                    <span className="kb-card__name kb-card__name--locked" title={`Listed for everyone. To open it, ask its owner${p.owner ? ` (${p.owner.display_name})` : ""} for a role.`}>
                      {p.name}
                    </span>
                  )}
                  {!p.access.view && <span className="kb-badge">No access</span>}
                  {menuItems(p).length > 0 && (
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
                  {p.created_by && (
                    <span className="kb-card__dept" title={`Created by ${p.created_by.display_name}`}>
                      <span className="kb-card__dept-name">{p.created_by.display_name}</span>
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <DocRepoTable items={filtered} menuItems={menuItems} />
        )}
      </section>

      <Modal
        open={editing !== null}
        title={editing?.docRepo ? `Edit ${editing.docRepo.name}` : "Create repository"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <DocRepoForm
            token={token}
            existing={editing.docRepo}
            onCancel={() => setEditing(null)}
            onSaved={(p, created) => {
              setEditing(null);
              setNotice(created
                ? `Created ${p.name}.`
                : `Saved ${p.name}.`);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete repository" onClose={() => setDeleting(null)}>
        {deleting && (
          <ConfirmDelete
            message={<>Delete <strong>{deleting.name}</strong>? It disappears for everyone and its pending approvals
              are withdrawn. Its documents are kept; a platform admin can restore it.</>}
            confirmLabel="Delete repository"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              await deleteDocRepo(token, deleting.id);
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
