import { useMemo, useState } from "react";
import type { KnowledgeBase } from "../api/knowledgeBases";
import { timeAgo } from "../lib/time";
import { MoreIcon, SortIcon, StarIcon } from "./Icons";
import { Pager, usePagination } from "./Pager";

type SortKey = "name" | "department" | "updated_at";
type SortDir = "asc" | "desc";

interface Props {
  items: KnowledgeBase[];
  accessLabel: (kb: KnowledgeBase) => string;
  onToggleFavorite: (id: string) => void;
}

/** List view, modelled on Amazon Quick's table: sortable columns + pagination. */
export function KnowledgeBaseTable({ items, accessLabel, onToggleFavorite }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "updated_at",
    dir: "desc",
  });

  const sorted = useMemo(() => {
    const value = (kb: KnowledgeBase) =>
      sort.key === "department" ? kb.department.name.toLowerCase()
      : sort.key === "name" ? kb.name.toLowerCase()
      : kb.updated_at;
    const out = [...items].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0));
    return sort.dir === "asc" ? out : out.reverse();
  }, [items, sort]);

  const { rows, ...pager } = usePagination(sorted);

  function sortBy(key: SortKey) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "updated_at" ? "desc" : "asc" },
    );
  }

  function header(label: string, key?: SortKey) {
    const active = key !== undefined && sort.key === key;
    return (
      <th
        scope="col"
        aria-sort={key ? (active ? (sort.dir === "asc" ? "ascending" : "descending") : "none") : undefined}
      >
        <div className="kb-table__th">
          <span className="kb-table__th-label" title={label}>
            {label}
          </span>
          {key && (
            <button
              type="button"
              className="kb-table__sort"
              aria-label={`Sort by ${label}`}
              title={`Sort by ${label}`}
              onClick={() => sortBy(key)}
            >
              <SortIcon dir={active ? sort.dir : "none"} />
            </button>
          )}
        </div>
      </th>
    );
  }

  return (
    <div className="kb-table-panel">
      <table className="kb-table">
        <colgroup>
          <col className="kb-table__col-name" />
          <col />
          <col className="kb-table__col-department" />
          <col className="kb-table__col-updated" />
          <col className="kb-table__col-actions" />
        </colgroup>
        <thead>
          <tr>
            {header("Knowledge base name", "name")}
            {header("Description")}
            {header("Department", "department")}
            {header("Last updated", "updated_at")}
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((kb) => (
            <tr key={kb.id}>
              <td>
                <div className="kb-table__name">
                  <button
                    type="button"
                    className="kb-icon-btn kb-icon-btn--star"
                    aria-pressed={kb.favorite}
                    aria-label={kb.favorite ? "Remove from favourites" : "Add to favourites"}
                    title={kb.favorite ? "Remove from favourites" : "Add to favourites"}
                    onClick={() => onToggleFavorite(kb.id)}
                  >
                    <StarIcon filled={kb.favorite} />
                  </button>
                  <a className="kb-table__link" href={`#kb/${encodeURIComponent(kb.id)}`}>
                    {kb.name}
                  </a>
                </div>
              </td>
              <td className="kb-table__truncate">{kb.description}</td>
              <td className="kb-table__truncate" title={accessLabel(kb)}>
                {kb.department.name}
                {kb.access === "granted" && <span className="kb-badge">Shared</span>}
              </td>
              <td title={new Date(kb.updated_at).toLocaleString()}>{timeAgo(kb.updated_at)}</td>
              <td className="kb-table__actions">
                <button
                  type="button"
                  className="kb-icon-btn kb-icon-btn--brand"
                  aria-label={`More actions for ${kb.name}`}
                  title="More actions"
                >
                  <MoreIcon />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Pager {...pager} />
    </div>
  );
}
