import { type DocRepo } from "../../api/doc-repos";
import { MoreIcon } from "../../components/Icons";
import { SortHeader, useSort } from "../../components/Sort";
import { Menu, type MenuItem } from "../../components/Menu";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";

interface Props {
  items: DocRepo[];
  menuItems: (p: DocRepo) => MenuItem[];
}

/** List view of doc-repos, like main's knowledge base table: sortable columns and pagination. */
export function DocRepoTable({ items, menuItems }: Props) {
  const { sorted, sort, toggle } = useSort(items, {
    name: { value: (p) => p.name },
    created_by: { value: (p) => p.created_by?.display_name },
    updated_at: { value: (p) => p.updated_at, desc: true },
  }, { key: "updated_at", dir: "desc" });
  const { rows, ...pager } = usePagination(sorted);
  const header = (label: string, key?: "name" | "created_by" | "updated_at") => (
    <SortHeader label={label} sortKey={key} sort={sort} onSort={toggle} />
  );

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
            {header("Created by", "created_by")}
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
                  {p.access.view ? (
                    <a className="kb-table__link" href={`#doc-repo/${p.id}`}>
                      {p.name}
                    </a>
                  ) : (
                    <span className="kb-table__locked" title={`Listed for everyone. To open it, ask its owner${p.owner ? ` (${p.owner.display_name})` : ""} for a role.`}>
                      {p.name}
                      <span className="kb-badge">No access</span>
                    </span>
                  )}
                </div>
              </td>
              <td className="kb-table__truncate">{p.description}</td>
              <td className="kb-table__truncate">{p.created_by?.display_name ?? "—"}</td>
              <td title={new Date(p.updated_at).toLocaleString()}>{timeAgo(p.updated_at)}</td>
              <td className="kb-table__actions">
                {menuItems(p).length > 0 && (
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
