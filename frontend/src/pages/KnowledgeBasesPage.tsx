import { useCallback, useEffect, useMemo, useState } from "react";
import type { User } from "../api/auth";
import { listKnowledgeBases, setFavorite, type KnowledgeBase } from "../api/knowledgeBases";
import {
  GridIcon,
  KnowledgeBaseIcon,
  ListIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
  StarIcon,
} from "../components/Icons";
import { KnowledgeBaseTable } from "../components/KnowledgeBaseTable";
import { Modal } from "../components/Modal";
import { CreateKnowledgeBaseForm } from "./CreateKnowledgeBaseForm";
import { timeAgo } from "../lib/time";
import "../styles/knowledge-bases.css";
import "../styles/admin.css"; // modal and form styles

type View = "grid" | "list";
const VIEW_KEY = "dh.kbView";

function readView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

interface Props {
  token: string;
  user: User;
}

export function KnowledgeBasesPage({ token, user }: Props) {
  const [items, setItems] = useState<KnowledgeBase[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>(readView);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    listKnowledgeBases(token)
      .then(setItems)
      .catch((e: Error) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items || !q) return items ?? [];
    return items.filter(
      (kb) =>
        kb.name.toLowerCase().includes(q) ||
        kb.description.toLowerCase().includes(q),
    );
  }, [items, query]);

  function changeView(v: View) {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* preference just won't be remembered */
    }
  }

  // Optimistic: flip the star now, put it back if the save fails.
  function toggleFavorite(id: string) {
    const kb = items?.find((k) => k.id === id);
    if (!kb) return;
    const flip = (fav: boolean) =>
      setItems((prev) => prev?.map((k) => (k.id === id ? { ...k, favorite: fav } : k)) ?? prev);
    flip(!kb.favorite);
    setFavorite(token, id, !kb.favorite).catch(() => flip(kb.favorite));
  }

  const stats = useMemo(() => {
    if (!items) return null;
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    return {
      total: items.length,
      department: items.filter((kb) => kb.access !== "granted").length,
      shared: items.filter((kb) => kb.access === "granted").length,
      recent: items.filter((kb) => new Date(kb.updated_at).getTime() >= weekAgo).length,
    };
  }, [items]);

  const accessLabel = (kb: KnowledgeBase) =>
    kb.access === "granted" ? "Shared with me" : kb.access === "admin" ? "Managed by me" : "My department";

  return (
    <div className="page">
      <h1 className="page__title">Knowledge Bases</h1>

      <ul className="stats" aria-label="Summary">
        {[
          { label: "Total knowledge bases", value: stats?.total },
          {
            label: user.department ? `${user.department.name}` : "Managed by me",
            value: stats?.department,
          },
          { label: "Shared with me", value: stats?.shared },
          { label: "Updated this week", value: stats?.recent },
        ].map((s) => (
          <li key={s.label} className="stat">
            <span className="stat__value">{s.value ?? "–"}</span>
            <span className="stat__label">{s.label}</span>
          </li>
        ))}
      </ul>

      <section aria-labelledby="all-kb">
        <div className="section-head">
          <h2 id="all-kb" className="section-head__title">
            All knowledge bases
          </h2>
          {user.permissions.includes("kb:create") && (
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              <PlusIcon />
              Create knowledge base
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
              placeholder="Search knowledge bases"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search knowledge bases"
            />
          </label>

          <div className="view-toggle" role="group" aria-label="View">
            <button
              type="button"
              aria-pressed={view === "list"}
              aria-label="List view"
              title="List view"
              onClick={() => changeView("list")}
            >
              <ListIcon />
            </button>
            <button
              type="button"
              aria-pressed={view === "grid"}
              aria-label="Grid view"
              title="Grid view"
              onClick={() => changeView("grid")}
            >
              <GridIcon />
            </button>
          </div>
        </div>

        {error ? (
          <p className="kb-message kb-message--error" role="alert">
            {error}
          </p>
        ) : items === null ? (
          <p className="kb-message">Loading knowledge bases…</p>
        ) : filtered.length === 0 ? (
          <p className="kb-message">
            {query ? `No knowledge bases match “${query}”.` : "No knowledge bases yet."}
          </p>
        ) : (
          view === "grid" ? (
            <ul className="kb-grid">
              {filtered.map((kb) => (
                <li key={kb.id} className="kb-card">
                  <div className="kb-card__head">
                    <span className="kb-card__icon">
                      <KnowledgeBaseIcon />
                    </span>
                    <a className="kb-card__name" href={`#kb/${encodeURIComponent(kb.id)}`}>
                      {kb.name}
                    </a>
                    <div className="kb-card__actions">
                      <button
                        type="button"
                        className="kb-icon-btn kb-icon-btn--star"
                        aria-pressed={kb.favorite}
                        aria-label={kb.favorite ? "Remove from favourites" : "Add to favourites"}
                        title={kb.favorite ? "Remove from favourites" : "Add to favourites"}
                        onClick={() => toggleFavorite(kb.id)}
                      >
                        <StarIcon filled={kb.favorite} />
                      </button>
                      <button
                        type="button"
                        className="kb-icon-btn"
                        aria-label={`More actions for ${kb.name}`}
                        title="More actions"
                      >
                        <MoreIcon />
                      </button>
                    </div>
                  </div>
                  <p className="kb-card__desc">{kb.description}</p>
                  <div className="kb-card__foot">
                    <span className="kb-card__updated">Updated {timeAgo(kb.updated_at)}</span>
                    <span className="kb-card__dept" title={`${kb.department.name} · ${accessLabel(kb)}`}>
                      <span className="kb-card__dept-name">{kb.department.name}</span>
                      {kb.access === "granted" && <span className="kb-badge">Shared</span>}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <KnowledgeBaseTable
              items={filtered}
              accessLabel={accessLabel}
              onToggleFavorite={toggleFavorite}
            />
          )
        )}
      </section>

      <Modal open={creating} title="Create knowledge base" onClose={() => setCreating(false)}>
        <CreateKnowledgeBaseForm
          token={token}
          onCancel={() => setCreating(false)}
          onCreated={(kb, promoted) => {
            setCreating(false);
            setNotice(
              `Created ${kb.name} for ${kb.department.name}, with ${kb.admin?.display_name} as department admin.` +
                (promoted ? ` ${promoted.display_name} is now a department admin.` : ""),
            );
            load();
          }}
        />
      </Modal>
    </div>
  );
}
