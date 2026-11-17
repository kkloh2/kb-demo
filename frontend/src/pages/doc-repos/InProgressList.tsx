import { useEffect, useMemo, useState } from "react";
import { STATUS_LABEL, type DocRepoDocument, type DocumentStatus } from "../../api/documents";
import { ChevronIcon, DownloadIcon, FileIcon, MoreIcon, SearchIcon, TrashIcon, UploadIcon } from "../../components/Icons";
import { Menu, type MenuItem } from "../../components/Menu";
import { Pager, usePagination } from "../../components/Pager";
import { SelectAll } from "../../components/SelectAll";
import { SortHeader, useSort } from "../../components/Sort";
import { timeAgo } from "../../lib/time";
import { DocName, folderLabel, matchesQuery, plural, within } from "./docs-common";

/** Documents a maker can tick for bulk submission: drafts and those sent back for changes. */
const BULK_STATUSES: DocumentStatus[] = ["draft", "changes_requested"];
const bulkable = (d: DocRepoDocument) => d.actions.submit && BULK_STATUSES.includes(d.status);
const STATUSES: DocumentStatus[] = ["draft", "pending_approval", "changes_requested", "rejected"];

interface Props {
  docs: DocRepoDocument[] | null; // latest versions not yet approved
  canUpload: boolean;
  selected: Map<string, DocumentStatus>; // ticked, with the status each had when ticked
  onSelected: (next: Map<string, DocumentStatus>) => void;
  onOpen: (d: DocRepoDocument) => void;
  onDownload: (d: DocRepoDocument) => void;
  onSubmit: (d: DocRepoDocument) => void;
  onDelete: (d: DocRepoDocument) => void;
}

/**
 * Work in progress: the latest version of every document that isn't approved yet, as a task list
 * (status, who, when, where it's kept). Makers tick drafts and changes-requested documents to
 * submit them together.
 */
export function InProgressList({ docs, canUpload, selected, onSelected, onOpen, onDownload, onSubmit, onDelete }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"" | DocumentStatus>("");
  const [scope, setScope] = useState("");
  const all = useMemo(() => docs ?? [], [docs]);

  const byQuery = useMemo(() => all.filter((d) => matchesQuery(d, query)), [all, query]);
  const matches = useMemo(
    () => byQuery.filter((d) => (!status || d.status === status) && within(d.folder, scope)),
    [byQuery, status, scope],
  );
  const statusCounts = useMemo(() => {
    const pool = byQuery.filter((d) => within(d.folder, scope));
    return { total: pool.length, by: Object.fromEntries(STATUSES.map((s) => [s, pool.filter((d) => d.status === s).length])) };
  }, [byQuery, scope]);
  const folderCounts = useMemo(() => {
    const pool = byQuery.filter((d) => !status || d.status === status);
    const counts = new Map<string, number>();
    for (const d of pool) {
      const parts = d.folder ? d.folder.split("/") : [];
      for (let i = 1; i <= parts.length; i++) {
        const p = parts.slice(0, i).join("/");
        counts.set(p, (counts.get(p) ?? 0) + 1);
      }
    }
    return { total: pool.length, folders: [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)) };
  }, [byQuery, status]);

  const { sorted, sort, toggle: sortBy } = useSort(matches, {
    name: { value: (d) => d.filename },
    location: { value: (d) => d.folder },
    status: { value: (d) => STATUS_LABEL[d.status] },
    maker: { value: (d) => d.maker?.display_name },
    updated: { value: (d) => d.updated_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  // A different search or filter starts a new selection; "select all" covers what it shows.
  useEffect(() => onSelected(new Map()), [query, status, scope]); // eslint-disable-line react-hooks/exhaustive-deps
  const tickable = useMemo(() => matches.filter(bulkable), [matches]);
  const tickedHere = tickable.filter((d) => selected.has(d.id)).length;

  function toggle(d: DocRepoDocument) {
    const next = new Map(selected);
    if (next.has(d.id)) next.delete(d.id);
    else next.set(d.id, d.status);
    onSelected(next);
  }

  const rowMenu = (d: DocRepoDocument): MenuItem[] => [
    { label: "Open", icon: <FileIcon />, onSelect: () => onOpen(d) },
    { label: "Download", icon: <DownloadIcon />, onSelect: () => onDownload(d) },
    ...(d.actions.submit ? [{ label: "Submit for approval", icon: <UploadIcon />, onSelect: () => onSubmit(d) }] : []),
    ...(d.actions.delete ? [{ label: "Delete…", icon: <TrashIcon />, danger: true, onSelect: () => onDelete(d) }] : []),
  ];

  const filtered = query.trim() !== "" || status !== "" || scope !== "";

  return (
    <>
      <div className="toolbar toolbar--wrap">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" placeholder="Search documents in progress" value={query}
              onChange={(e) => setQuery(e.target.value)} aria-label="Search documents in progress" />
          </label>
          <label className="filter">
            <span className="sr-only">Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as "" | DocumentStatus)}>
              <option value="">All statuses ({statusCounts.total})</option>
              {STATUSES.filter((s) => statusCounts.by[s] > 0 || s === status).map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL[s]} ({statusCounts.by[s]})
                </option>
              ))}
            </select>
            <ChevronIcon dir="down" />
          </label>
          <label className="filter">
            <span className="sr-only">Folder</span>
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="">All folders ({folderCounts.total})</option>
              {folderCounts.folders.map(([f, n]) => (
                <option key={f} value={f}>
                  {folderLabel(f)} ({n})
                </option>
              ))}
            </select>
            <ChevronIcon dir="down" />
          </label>
        </div>
      </div>

      {filtered && (
        <p className="filter-summary" aria-live="polite">
          {plural(matches.length, "document", "documents")} in progress
          {status ? `, ${STATUS_LABEL[status].toLowerCase()}` : ""}
          {scope ? ` in ${folderLabel(scope)}` : ""}
          {query.trim() ? `, matching “${query.trim()}”` : ""}.
          <button type="button" className="btn-link" onClick={() => { setQuery(""); setStatus(""); setScope(""); }}>
            Clear filters
          </button>
        </p>
      )}

      <div className="kb-table-panel">
        {docs === null ? (
          <p className="kb-message">Loading documents…</p>
        ) : all.length === 0 ? (
          <p className="kb-message">
            {canUpload ? "Nothing in progress. Use Add to upload documents." : "Nothing in progress."}
          </p>
        ) : matches.length === 0 ? (
          <p className="kb-message">No documents in progress match.</p>
        ) : (
          <>
            <table className="data-table docs-table">
              <colgroup>
                {canUpload && <col style={{ width: "44px" }} />}
                <col />
                <col style={{ width: "20%" }} />
                <col style={{ width: "150px" }} />
                <col style={{ width: "15%" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "56px" }} />
              </colgroup>
              <thead>
                <tr>
                  {canUpload && (
                    <th scope="col" className="check-cell">
                      <SelectAll selected={tickedHere} total={tickable.length}
                        onChange={(on) => onSelected(on ? new Map(tickable.map((d) => [d.id, d.status])) : new Map())}
                        label="Select all drafts and documents sent back for changes" />
                    </th>
                  )}
                  <SortHeader label="Name" sortKey="name" sort={sort} onSort={sortBy} />
                  <SortHeader label="Location" sortKey="location" sort={sort} onSort={sortBy} />
                  <SortHeader label="Status" sortKey="status" sort={sort} onSort={sortBy} />
                  <SortHeader label="Uploaded by" sortKey="maker" sort={sort} onSort={sortBy} />
                  <SortHeader label="Updated" sortKey="updated" sort={sort} onSort={sortBy} />
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id}>
                    {canUpload && (
                      <td className="check-cell">
                        {bulkable(d) && (
                          <input type="checkbox" className="row-check" aria-label={`Select ${d.filename}`}
                            checked={selected.has(d.id)} onChange={() => toggle(d)} />
                        )}
                      </td>
                    )}
                    <td>
                      <DocName d={d} onOpen={() => onOpen(d)} />
                    </td>
                    <td className="truncate" title={folderLabel(d.folder)}>
                      <button type="button" className="link-button" onClick={() => setScope(d.folder)}
                        title={`Only show ${folderLabel(d.folder)}`}>
                        {folderLabel(d.folder)}
                      </button>
                    </td>
                    <td>
                      <span className={`status status--${d.status}`} title={d.last_decision?.comment ?? undefined}>
                        {STATUS_LABEL[d.status]}
                      </span>
                    </td>
                    <td className="truncate">{d.maker?.display_name ?? "—"}</td>
                    <td title={new Date(d.updated_at).toLocaleString()}>{timeAgo(d.updated_at)}</td>
                    <td className="kb-table__actions">
                      <Menu
                        trigger={(props) => (
                          <button type="button" className="kb-icon-btn kb-icon-btn--brand"
                            aria-label={`More actions for ${d.filename}`} title="More actions" {...props}>
                            <MoreIcon />
                          </button>
                        )}
                        items={rowMenu(d)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...pager} />
          </>
        )}
      </div>
    </>
  );
}
