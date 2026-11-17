import { useEffect, useMemo, useState } from "react";
import { type DocRepoDocument } from "../../api/documents";
import { ChevronIcon, DownloadIcon, FileIcon, FolderIcon, MoreIcon, SearchIcon, UploadIcon } from "../../components/Icons";
import { Menu, type MenuItem } from "../../components/Menu";
import { Pager, usePagination } from "../../components/Pager";
import { SortHeader, useSort } from "../../components/Sort";
import { timeAgo } from "../../lib/time";
import { DocName, folderLabel, matchesQuery, plural, within } from "./docs-common";

interface Props {
  docs: DocRepoDocument[] | null; // each document's latest approved version
  inProgress: Set<string>; // documents with a newer version being worked on (shown to makers)
  canUpload: boolean;
  folder: string; // the folder being browsed (shared with the upload window's default)
  onFolder: (folder: string) => void;
  onOpen: (d: DocRepoDocument) => void;
  onDownload: (d: DocRepoDocument) => void;
  onNewVersion: (d: DocRepoDocument) => void;
}

const MAX_FACETS = 4; // metadata fields offered as filters (the first ones the repository defines)

/**
 * Published documents, the library: browse by folder; a search or a filter lists the matches with
 * where each one is kept (Location), filtered by folder and by metadata, each choice with its count.
 */
export function PublishedList({ docs, inProgress, canUpload, folder, onFolder, onOpen, onDownload, onNewVersion }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState(""); // the Folder filter while searching ("" = all folders)
  const [meta, setMeta] = useState<Record<string, string>>({}); // label -> value
  const filtering = query.trim() !== "" || Object.keys(meta).length > 0;
  const all = useMemo(() => docs ?? [], [docs]);

  // A search starts in the folder being browsed; the Folder filter can widen it.
  const [wasFiltering, setWasFiltering] = useState(false);
  useEffect(() => {
    if (filtering && !wasFiltering) setScope(folder);
    setWasFiltering(filtering);
  }, [filtering, wasFiltering, folder]);

  // ---------------------------------------------------------------- filter mode
  const byQuery = useMemo(() => all.filter((d) => matchesQuery(d, query)), [all, query]);
  const metaMatch = (d: DocRepoDocument, except?: string) =>
    Object.entries(meta).every(([label, value]) => label === except || d.metadata.some((m) => m.label === label && m.value === value));
  const matches = useMemo(
    () => byQuery.filter((d) => within(d.folder, scope) && metaMatch(d)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [byQuery, scope, meta],
  );

  // Facet counts: each counts the matches of every other filter, as library catalogues do.
  const folderFacet = useMemo(() => {
    const pool = byQuery.filter((d) => metaMatch(d));
    const counts = new Map<string, number>();
    for (const d of pool) {
      const parts = d.folder ? d.folder.split("/") : [];
      for (let i = 1; i <= parts.length; i++) {
        const p = parts.slice(0, i).join("/");
        counts.set(p, (counts.get(p) ?? 0) + 1);
      }
    }
    return { total: pool.length, folders: [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byQuery, meta]);

  const labels = useMemo(() => {
    const seen: string[] = [];
    for (const d of all) for (const m of d.metadata) if (m.value && !seen.includes(m.label)) seen.push(m.label);
    return seen.slice(0, MAX_FACETS);
  }, [all]);

  const metaFacets = useMemo(
    () =>
      labels.map((label) => {
        const counts = new Map<string, number>();
        for (const d of byQuery) {
          if (!within(d.folder, scope) || !metaMatch(d, label)) continue;
          const v = d.metadata.find((m) => m.label === label)?.value;
          if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
        }
        return { label, values: [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)) };
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [labels, byQuery, scope, meta],
  );

  // ---------------------------------------------------------------- browse mode
  const { subfolders, here } = useMemo(() => {
    const prefix = folder ? `${folder}/` : "";
    const names = new Set<string>();
    for (const d of all) {
      if (!d.folder.startsWith(prefix) || d.folder === folder) continue;
      names.add(d.folder.slice(prefix.length).split("/")[0]);
    }
    return { subfolders: [...names].sort((a, b) => a.localeCompare(b)), here: all.filter((d) => d.folder === folder) };
  }, [all, folder]);

  const files = filtering ? matches : here;
  const { sorted, sort, toggle } = useSort(files, {
    name: { value: (d) => d.filename },
    location: { value: (d) => d.folder },
    maker: { value: (d) => d.maker?.display_name },
    approved: { value: (d) => d.last_decision?.decided_at, desc: true },
  });
  const { rows, ...pager } = usePagination(sorted);

  function clear() {
    setQuery("");
    setMeta({});
  }

  function goTo(path: string) {
    clear();
    onFolder(path);
  }

  const rowMenu = (d: DocRepoDocument): MenuItem[] => [
    { label: "Open", icon: <FileIcon />, onSelect: () => onOpen(d) },
    { label: "Download", icon: <DownloadIcon />, onSelect: () => onDownload(d) },
    ...(canUpload
      ? [{ label: "Upload new version", icon: <UploadIcon />, onSelect: () => onNewVersion(d) }]
      : []),
  ];

  const crumbs = folder ? folder.split("/") : [];
  const filters = [
    query.trim() && `matching “${query.trim()}”`,
    ...Object.entries(meta).map(([l, v]) => `${l}: ${v}`),
  ].filter(Boolean);

  return (
    <>
      <div className="toolbar toolbar--wrap">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" placeholder="Search published documents" value={query}
              onChange={(e) => setQuery(e.target.value)} aria-label="Search published documents" />
          </label>
          {filtering && (
            <label className="filter">
              <span className="sr-only">Folder</span>
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="">All folders ({folderFacet.total})</option>
                {folderFacet.folders.map(([f, n]) => (
                  <option key={f} value={f}>
                    {folderLabel(f)} ({n})
                  </option>
                ))}
              </select>
              <ChevronIcon dir="down" />
            </label>
          )}
          {metaFacets.map((f) => (
            <label key={f.label} className="filter">
              <span className="sr-only">{f.label}</span>
              <select value={meta[f.label] ?? ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setMeta(({ [f.label]: _, ...rest }) => (v ? { ...rest, [f.label]: v } : rest));
                }}>
                <option value="">Any {f.label.toLowerCase()}</option>
                {f.values.map(([v, n]) => (
                  <option key={v} value={v}>
                    {v} ({n})
                  </option>
                ))}
              </select>
              <ChevronIcon dir="down" />
            </label>
          ))}
        </div>
      </div>

      {filtering ? (
        <p className="filter-summary" aria-live="polite">
          {plural(matches.length, "published document", "published documents")} in{" "}
          {scope ? folderLabel(scope) : "all folders"}
          {filters.length ? `, ${filters.join(", ")}` : ""}.
          <button type="button" className="btn-link" onClick={clear}>
            Clear filters
          </button>
        </p>
      ) : (
        <nav className="crumbs" aria-label="Folder">
          <button type="button" className="crumbs__item" aria-current={folder === "" ? "page" : undefined}
            onClick={() => onFolder("")}>
            All files
          </button>
          {crumbs.map((c, i) => {
            const path = crumbs.slice(0, i + 1).join("/");
            return (
              <span key={path} className="crumbs__part">
                <ChevronIcon dir="right" />
                <button type="button" className="crumbs__item" aria-current={path === folder ? "page" : undefined}
                  onClick={() => onFolder(path)}>
                  {c}
                </button>
              </span>
            );
          })}
        </nav>
      )}

      <div className="kb-table-panel">
        {docs === null ? (
          <p className="kb-message">Loading documents…</p>
        ) : !filtering && subfolders.length === 0 && here.length === 0 ? (
          <p className="kb-message">
            {all.length === 0
              ? canUpload
                ? "Nothing is published yet. Documents appear here once they're approved."
                : "No documents to show yet."
              : "This folder is empty."}
          </p>
        ) : filtering && matches.length === 0 ? (
          <p className="kb-message">No published documents match.</p>
        ) : (
          <>
            <table className="data-table docs-table">
              <colgroup>
                <col />
                {filtering && <col style={{ width: "22%" }} />}
                <col style={{ width: "18%" }} />
                <col style={{ width: "130px" }} />
                <col style={{ width: "56px" }} />
              </colgroup>
              <thead>
                <tr>
                  <SortHeader label="Name" sortKey="name" sort={sort} onSort={toggle} />
                  {filtering && <SortHeader label="Location" sortKey="location" sort={sort} onSort={toggle} />}
                  <SortHeader label="Uploaded by" sortKey="maker" sort={sort} onSort={toggle} />
                  <SortHeader label="Approved" sortKey="approved" sort={sort} onSort={toggle} />
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {!filtering &&
                  subfolders.map((name) => (
                    <tr key={`folder:${name}`} className="docs-table__folder">
                      <td>
                        <button type="button" className="doc-name doc-name--button"
                          onClick={() => onFolder(folder ? `${folder}/${name}` : name)}>
                          <span className="doc-name__icon doc-name__icon--folder">
                            <FolderIcon />
                          </span>
                          <span className="truncate">{name}</span>
                        </button>
                      </td>
                      <td colSpan={3} />
                    </tr>
                  ))}
                {rows.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <DocName d={d} onOpen={() => onOpen(d)} note={inProgress.has(d.id) ? "newer version in progress" : undefined} />
                    </td>
                    {filtering && (
                      <td className="truncate">
                        <button type="button" className="link-button" title={`Open ${folderLabel(d.folder)}`}
                          onClick={() => goTo(d.folder)}>
                          {folderLabel(d.folder)}
                        </button>
                      </td>
                    )}
                    <td className="truncate">{d.maker?.display_name ?? "—"}</td>
                    <td title={d.last_decision ? new Date(d.last_decision.decided_at).toLocaleString() : undefined}>
                      {d.last_decision ? timeAgo(d.last_decision.decided_at) : "—"}
                    </td>
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
