/** Pieces the Documents tab's lists share. */

import { formatSize, type DocRepoDocument } from "../../api/documents";
import { FileIcon } from "../../components/Icons";

// Must match the server's allowed_upload_extensions; anything else in a folder is left out.
export const ALLOWED = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".txt", ".md"];

export const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

/** A file's kind from its name, for the coloured file icon (doc-name__icon--<kind>). */
export function extKind(name: string): string {
  const ext = name.slice(name.lastIndexOf(".") + 1).toLowerCase();
  if (ext === "pdf") return "pdf";
  if (ext === "doc" || ext === "docx") return "doc";
  if (ext === "xls" || ext === "xlsx") return "xls";
  if (ext === "csv") return "csv";
  if (ext === "ppt" || ext === "pptx") return "ppt";
  return "other";
}

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "Policies / 2026", or "Top level". */
export const folderLabel = (folder: string) => (folder ? folder.split("/").join(" / ") : "Top level");

/** Every folder path, with each one's parents ("A", "A/B", ...), sorted. */
export function allFolders(docs: DocRepoDocument[]): string[] {
  const out = new Set<string>();
  for (const d of docs) {
    const parts = d.folder ? d.folder.split("/") : [];
    for (let i = 1; i <= parts.length; i++) out.add(parts.slice(0, i).join("/"));
  }
  return [...out].sort((a, b) => a.localeCompare(b));
}

/** Is `folder` the scope or below it? ("" is everything.) */
export const within = (folder: string, scope: string) => !scope || folder === scope || folder.startsWith(`${scope}/`);

/** Matches a search: name, folder or any metadata value. */
export function matchesQuery(d: DocRepoDocument, q: string): boolean {
  q = q.trim().toLowerCase();
  return (
    !q ||
    d.filename.toLowerCase().includes(q) ||
    d.folder.toLowerCase().includes(q) ||
    d.metadata.some((m) => (m.value ?? "").toLowerCase().includes(q))
  );
}

/** The name cell: icon, file name, and "Version n · size" underneath. */
export function DocName({ d, onOpen, note }: { d: DocRepoDocument; onOpen: () => void; note?: string }) {
  return (
    <button type="button" className="doc-name doc-name--button" onClick={onOpen}
      title={`${d.folder ? `${d.folder}/` : ""}${d.filename}`}>
      <span className={`doc-name__icon doc-name__icon--${extKind(d.filename)}`}>
        <FileIcon />
      </span>
      <span className="doc-name__text">
        <span className="truncate">{d.filename}</span>
        <span className="doc-name__sub">
          Version {d.version} · {formatSize(d.size_bytes)}
          {note ? ` · ${note}` : ""}
        </span>
      </span>
    </button>
  );
}
