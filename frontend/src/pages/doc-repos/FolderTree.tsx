import { useMemo, useState } from "react";
import { ChevronIcon, FolderIcon, PlusIcon, SearchIcon } from "../../components/Icons";
import { folderLabel } from "./docs-common";

interface Props {
  folders: string[]; // every folder path ("A", "A/B", ...)
  value: string; // the chosen folder ("" = top level)
  onChange: (folder: string) => void;
  onNewFolder: (path: string) => void; // a folder to create (on upload) inside the chosen one
}

/** The parents of a path: "A/B/C" -> ["A", "A/B"]. */
const parentsOf = (path: string) => {
  const parts = path ? path.split("/") : [];
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
};

/**
 * Choose a folder from a tree: expand and collapse folders, click one to choose it. A filter finds a
 * folder by name however deep it is; New folder makes one inside the chosen folder.
 */
export function FolderTree({ folders, value, onChange, onNewFolder }: Props) {
  const [open, setOpen] = useState<Set<string>>(() => new Set(parentsOf(value).concat(value ? [value] : [])));
  const [query, setQuery] = useState("");
  const [naming, setNaming] = useState<string | null>(null);
  const q = query.trim().toLowerCase();

  const childrenOf = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const f of folders) {
      const parent = f.includes("/") ? f.slice(0, f.lastIndexOf("/")) : "";
      map.set(parent, [...(map.get(parent) ?? []), f]);
    }
    for (const list of map.values()) list.sort((a, b) => a.localeCompare(b));
    return map;
  }, [folders]);
  const found = useMemo(() => (q ? folders.filter((f) => f.split("/").pop()!.toLowerCase().includes(q)) : []), [folders, q]);

  function choose(f: string) {
    onChange(f);
    setOpen((o) => new Set([...o, ...parentsOf(f)]));
  }

  function toggle(f: string) {
    setOpen((o) => {
      const next = new Set(o);
      if (!next.delete(f)) next.add(f);
      return next;
    });
  }

  const name = (naming ?? "").replace(/[/\\]/g, " ").trim();
  function create() {
    if (!name) return;
    const path = value ? `${value}/${name}` : name;
    onNewFolder(path);
    setOpen((o) => new Set([...o, value]));
    choose(path);
    setNaming(null);
  }

  function row(f: string, depth: number) {
    const kids = childrenOf.get(f) ?? [];
    const expanded = open.has(f) || f === "";
    return (
      <li key={f || "(top)"} role="treeitem" aria-expanded={kids.length ? expanded : undefined} aria-selected={f === value}>
        <div className={`folder-tree__row${f === value ? " folder-tree__row--chosen" : ""}`}
          style={{ paddingLeft: `${8 + depth * 18}px` }}>
          {kids.length > 0 && f !== "" ? (
            <button type="button" className="folder-tree__toggle" aria-label={`${expanded ? "Collapse" : "Expand"} ${f.split("/").pop()}`}
              onClick={() => toggle(f)}>
              <ChevronIcon dir={expanded ? "down" : "right"} />
            </button>
          ) : (
            <span className="folder-tree__toggle" aria-hidden="true" />
          )}
          <button type="button" className="folder-tree__name" onClick={() => choose(f)}>
            <FolderIcon />
            <span className="truncate">{f === "" ? "Top level" : f.split("/").pop()}</span>
          </button>
        </div>
        {expanded && kids.length > 0 && <ul role="group">{kids.map((k) => row(k, depth + 1))}</ul>}
      </li>
    );
  }

  return (
    <div className="folder-tree">
      {folders.length > 0 && (
        <label className="folder-tree__search">
          <SearchIcon />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a folder"
            aria-label="Find a folder" />
        </label>
      )}

      <div className="folder-tree__body">
        {q ? (
          found.length === 0 ? (
            <p className="folder-tree__empty">No folder matches “{query.trim()}”.</p>
          ) : (
            <ul className="folder-tree__list" aria-label="Matching folders">
              {found.map((f) => (
                <li key={f}>
                  <button type="button" className={`folder-tree__found${f === value ? " folder-tree__row--chosen" : ""}`}
                    onClick={() => { choose(f); setQuery(""); }}>
                    <FolderIcon />
                    <span className="folder-tree__found-text">
                      <span className="truncate">{f.split("/").pop()}</span>
                      <small className="truncate">{folderLabel(f)}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <ul className="folder-tree__list" role="tree" aria-label="Folders">
            {row("", 0)}
          </ul>
        )}
      </div>

      <div className="folder-tree__foot">
        {naming === null ? (
          <button type="button" className="btn-link folder-tree__new" onClick={() => setNaming("")}>
            <PlusIcon /> New folder
          </button>
        ) : (
          <form className="folder-tree__naming" onSubmit={(e) => { e.preventDefault(); create(); }}>
            <input type="text" value={naming} onChange={(e) => setNaming(e.target.value)} maxLength={100} autoFocus
              placeholder="Folder name" aria-label={`New folder in ${folderLabel(value)}`} />
            <div className="folder-tree__naming-actions">
              <small className="truncate">In {folderLabel(value)}</small>
              <button type="button" className="btn-link" onClick={() => setNaming(null)}>
                Cancel
              </button>
              <button type="submit" className="btn-link folder-tree__create" disabled={!name}>
                Create
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
