import { useMemo, useState } from "react";
import { type DocRepo } from "../../api/doc-repos";
import { MoreIcon, SortIcon } from "../../components/Icons";
import { Menu, type MenuItem } from "../../components/Menu";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";

type SortKey = "name" | "department" | "updated_at";
type SortDir = "asc" | "desc";

interface Props {
  items: DocRepo[];
  menuItems: (p: DocRepo) => MenuItem[];
}

/** List view of doc-repos, like main's knowledge base table: sortable columns and pagination. */
export function DocRepoTable({ items, menuItems }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "updated_at", dir: "desc" });

  const sorted = useMemo(() => {
    const value = (p: DocRepo) =>
      sort.key === "department" ? p.department.name.toLowerCase()
      : sort.key === "name" ? p.name.toLowerCase()
      : p.updated_at;
    const out = [...items].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0));
    return sort.dir === "asc" ? out : out.reverse();
  }, [items, sort]);

  const { rows, ...pager } = usePagination(sorted);

  function sortBy(key: SortKey) {
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "updated_at" ? "desc" : "asc" },
    );
  }

  function header(label: string, key?: SortKey) {
    const active = key !== undefined && sort.key === key;
    return (
      <th scope="col" aria-sort={key ? (active ? (sort.dir === "asc" ? "ascending" : "descending") : "none") : undefined}>
        <div className="kb-table__th">
          <span className="kb-table__th-label" title={label}>
            {label}
          </span>
          {key && (
            <button type="button" className="kb-table__sort" aria-label={`Sort by ${label}`} title={`Sort by ${label}`}
              onClick={() => sortBy(key)}>
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
            {header("Repository name", "name")}
            {header("Description")}
            {header("Department", "department")}
            {header("Last updated", "updated_at")}
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id}>
              <td>
                <div className="kb-table__name">
                  {p.access.view_details ? (
                    <a className="kb-table__link" href={`#doc-repo/${p.id}`}>
                      {p.name}
                    </a>
                  ) : (
                    <span className="kb-table__locked" title={`Listed for everyone. To open it, ask a department admin of ${p.department.name} for a role.`}>
                      {p.name}
                      <span className="kb-badge">No access</span>
                    </span>
                  )}
                </div>
              </td>
              <td className="kb-table__truncate">{p.description}</td>
              <td className="kb-table__truncate">{p.department.name}</td>
              <td title={new Date(p.updated_at).toLocaleString()}>{timeAgo(p.updated_at)}</td>
              <td className="kb-table__actions">
                {p.access.manage && (
                  <Menu
                    trigger={(props) => (
                      <button type="button" className="kb-icon-btn kb-icon-btn--brand"
                        aria-label={`More actions for ${p.name}`} title="More actions" {...props}>
                        <MoreIcon />
                      </button>
                    )}
                    items={menuItems(p)}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager {...pager} />
    </div>
  );
}
