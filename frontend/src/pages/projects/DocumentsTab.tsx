import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDocuments,
  downloadDocument,
  formatSize,
  listDocuments,
  reviewDocuments,
  STATUS_LABEL,
  submitDocuments,
  uploadDocuments,
  type BulkResult,
  type DocumentStatus,
  type FieldDef,
  type ProjectDocument,
} from "../../api/documents";
import { ApiError } from "../../api/http";
import type { Project } from "../../api/projects";
import {
  CheckIcon,
  ChevronIcon,
  CloseIcon,
  DownloadIcon,
  FileIcon,
  FolderIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
  UploadIcon,
} from "../../components/Icons";
import { Menu, type MenuItem } from "../../components/Menu";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import { DocumentPanel } from "./DocumentPanel";

// Must match the server's allowed_upload_extensions; anything else in a folder is left out.
const ALLOWED = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".txt", ".md"];

type StatusFilter = "all" | DocumentStatus;
type Notice = { kind: "ok" | "error"; text: string } | null;

interface Props {
  token: string;
  project: Project;
  onSessionEnded: (message: string) => void;
  onCountChange?: (count: number) => void;
}

/** The project's documents, browsable by folder, with upload, bulk submit / review / delete. */
export function DocumentsTab({ token, project, onSessionEnded, onCountChange }: Props) {
  const { access } = project;
  const [docs, setDocs] = useState<ProjectDocument[] | null>(null);
  const [fields, setFields] = useState<FieldDef[]>([]);
  const [folder, setFolder] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [openId, setOpenId] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<number[] | null>(null);
  const [deleting, setDeleting] = useState<number[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else setNotice({ kind: "error", text: e instanceof Error ? e.message : "Something went wrong." });
    },
    [onSessionEnded],
  );

  const load = useCallback(() => {
    listDocuments(token, project.id)
      .then((r) => {
        setDocs(r.documents);
        setFields(r.fields);
        onCountChange?.(r.documents.length);
        setSelected((s) => new Set([...s].filter((id) => r.documents.some((d) => d.id === id))));
      })
      .catch(fail);
  }, [token, project.id, fail, onCountChange]);
  useEffect(load, [load]);

  // Folder pickers need the non-standard webkitdirectory attribute.
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  // ---------------------------------------------------------------- what to show
  const searching = query.trim() !== "" || status !== "all";
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (docs ?? []).filter(
      (d) =>
        (status === "all" || d.status === status) &&
        (!q ||
          d.filename.toLowerCase().includes(q) ||
          d.folder.toLowerCase().includes(q) ||
          Object.values({ ...d.fields, ...d.extra, ...d.base }).some((v) => String(v ?? "").toLowerCase().includes(q))),
    );
  }, [docs, query, status]);

  const { subfolders, files } = useMemo(() => {
    if (searching) return { subfolders: [] as { name: string; count: number }[], files: matches };
    const prefix = folder ? `${folder}/` : "";
    const counts = new Map<string, number>();
    for (const d of docs ?? []) {
      if (folder && d.folder !== folder && !d.folder.startsWith(prefix)) continue;
      const rest = folder ? d.folder.slice(prefix.length) : d.folder;
      if (d.folder === folder || !rest) continue;
      const name = rest.split("/")[0];
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return {
      subfolders: [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([name, count]) => ({ name, count })),
      files: (docs ?? []).filter((d) => d.folder === folder),
    };
  }, [docs, folder, matches, searching]);

  const { rows, ...pager } = usePagination(files);
  const selectedDocs = (docs ?? []).filter((d) => selected.has(d.id));
  const can = {
    submit: selectedDocs.some((d) => d.actions.submit),
    review: selectedDocs.some((d) => d.actions.review),
    delete: selectedDocs.some((d) => d.actions.delete),
  };

  // ---------------------------------------------------------------- actions
  function report(verb: string, r: BulkResult) {
    const parts = [`${verb} ${r.done.length} document${r.done.length === 1 ? "" : "s"}.`];
    if (r.skipped.length)
      parts.push(`Skipped ${r.skipped.length}: ${r.skipped.map((s) => `${s.filename} (${s.reason})`).join("; ")}`);
    setNotice({ kind: r.skipped.length && !r.done.length ? "error" : "ok", text: parts.join(" ") });
  }

  async function run(label: string, action: () => Promise<BulkResult>, verb: string) {
    setBusy(label);
    setNotice(null);
    try {
      report(verb, await action());
      setSelected(new Set());
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function onPicked(list: FileList | null, fromFolder: boolean) {
    if (!list?.length) return;
    const prefix = folder ? `${folder}/` : "";
    const all = [...list].map((file) => ({
      file,
      path: prefix + (fromFolder && file.webkitRelativePath ? file.webkitRelativePath : file.name),
    }));
    const usable = all.filter(({ file }) => {
      const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
      return !file.name.startsWith(".") && ALLOWED.includes(ext) && file.size > 0;
    });
    const left = all.length - usable.length;
    if (filesInput.current) filesInput.current.value = "";
    if (folderInput.current) folderInput.current.value = "";
    if (!usable.length) {
      setNotice({ kind: "error", text: `None of the ${all.length} files can be uploaded (allowed: ${ALLOWED.join(", ")}).` });
      return;
    }
    setBusy(`Uploading ${usable.length}…`);
    setNotice(null);
    try {
      const created = await uploadDocuments(token, project.id, usable);
      setNotice({
        kind: "ok",
        text:
          `Uploaded ${created.length} file${created.length === 1 ? "" : "s"} as drafts. ` +
          (left ? `Left out ${left} (hidden, empty or not an allowed type). ` : "") +
          "Open each to check its metadata, then submit for review.",
      });
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allOnPageSelected = rows.length > 0 && rows.every((d) => selected.has(d.id));
  function toggleAll() {
    setSelected((s) => {
      const next = new Set(s);
      for (const d of rows) {
        if (allOnPageSelected) next.delete(d.id);
        else next.add(d.id);
      }
      return next;
    });
  }

  const rowMenu = (d: ProjectDocument): MenuItem[] => [
    { label: "Open", icon: <FileIcon />, onSelect: () => setOpenId(d.id) },
    { label: "Download", icon: <DownloadIcon />, onSelect: () => downloadDocument(token, d).catch(fail) },
    ...(d.actions.submit
      ? [{ label: "Submit for review", icon: <UploadIcon />, onSelect: () => run("submit", () => submitDocuments(token, project.id, [d.id]), "Submitted") }]
      : []),
    ...(d.actions.review
      ? [
          { label: "Approve", icon: <CheckIcon />, onSelect: () => run("approve", () => reviewDocuments(token, project.id, [d.id], "approve"), "Approved") },
          { label: "Reject…", icon: <CloseIcon />, danger: true, onSelect: () => setRejecting([d.id]) },
        ]
      : []),
    ...(d.actions.delete ? [{ label: "Delete…", icon: <TrashIcon />, danger: true, onSelect: () => setDeleting([d.id]) }] : []),
  ];

  // ---------------------------------------------------------------- render
  if (!access.view_documents) {
    return (
      <div className="kb-table-panel">
        <p className="kb-message">
          You can see this project, but not its documents. Ask a department admin of {project.department.name} for a
          role in it.
        </p>
      </div>
    );
  }

  const crumbs = folder ? folder.split("/") : [];
  const statusOptions: StatusFilter[] = access.upload
    ? ["all", "draft", "pending_approval", "approved", "rejected"]
    : access.review
      ? ["all", "pending_approval", "approved", "rejected"]
      : [];

  return (
    <div>
      <div className="toolbar">
        <div className="toolbar__left">
          <label className="search">
            <SearchIcon />
            <input type="search" placeholder="Search names and metadata…" value={query}
              onChange={(e) => setQuery(e.target.value)} aria-label="Search documents" />
          </label>
          {statusOptions.length > 0 && (
            <label className="filter">
              <span className="sr-only">Status</span>
              <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
                {statusOptions.map((s) => (
                  <option key={s} value={s}>
                    {s === "all" ? "All statuses" : STATUS_LABEL[s]}
                  </option>
                ))}
              </select>
              <ChevronIcon dir="down" />
            </label>
          )}
        </div>

        {access.upload && (
          <>
            <Menu
              trigger={(props) => (
                <button type="button" className="btn-outline" disabled={busy !== null} {...props}>
                  <PlusIcon />
                  {busy?.startsWith("Uploading") ? busy : "Add"}
                  <ChevronIcon dir="down" />
                </button>
              )}
              items={[
                { label: "Upload files", icon: <UploadIcon />, onSelect: () => filesInput.current?.click() },
                { label: "Upload folder", icon: <FolderIcon />, onSelect: () => folderInput.current?.click() },
              ]}
            />
            <input ref={filesInput} type="file" multiple accept={ALLOWED.join(",")} hidden
              onChange={(e) => onPicked(e.target.files, false)} data-testid="upload-files" />
            <input ref={folderInput} type="file" multiple hidden
              onChange={(e) => onPicked(e.target.files, true)} data-testid="upload-folder" />
          </>
        )}
      </div>

      {notice && (
        <p className={notice.kind === "ok" ? "notice" : "notice notice--error"} role="status">
          {notice.text}
        </p>
      )}

      {selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected documents">
          <span className="bulk-bar__count">{selected.size} selected</span>
          {can.submit && (
            <button type="button" className="btn-primary btn-sm" disabled={busy !== null}
              onClick={() => run("submit", () => submitDocuments(token, project.id, [...selected]), "Submitted")}>
              <UploadIcon />
              Submit for review
            </button>
          )}
          {can.review && (
            <>
              <button type="button" className="btn-primary btn-sm" disabled={busy !== null}
                onClick={() => run("approve", () => reviewDocuments(token, project.id, [...selected], "approve"), "Approved")}>
                <CheckIcon />
                Approve
              </button>
              <button type="button" className="btn-outline btn-sm" disabled={busy !== null}
                onClick={() => setRejecting([...selected])}>
                Reject…
              </button>
            </>
          )}
          {can.delete && (
            <button type="button" className="btn-link btn-link--danger" disabled={busy !== null}
              onClick={() => setDeleting([...selected])}>
              Delete…
            </button>
          )}
          <button type="button" className="btn-link" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      )}

      {!searching && (
        <nav className="crumbs" aria-label="Folder">
          <button type="button" className="crumbs__item" aria-current={folder === "" ? "page" : undefined}
            onClick={() => setFolder("")}>
            All files
          </button>
          {crumbs.map((c, i) => {
            const path = crumbs.slice(0, i + 1).join("/");
            return (
              <span key={path} className="crumbs__part">
                <ChevronIcon dir="right" />
                <button type="button" className="crumbs__item" aria-current={path === folder ? "page" : undefined}
                  onClick={() => setFolder(path)}>
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
        ) : subfolders.length === 0 && files.length === 0 ? (
          <p className="kb-message">
            {searching
              ? "No documents match."
              : docs.length === 0
                ? access.upload
                  ? "No documents yet. Use Add → Upload files or Upload folder."
                  : "No documents to show yet."
                : "This folder is empty."}
          </p>
        ) : (
          <>
            <table className="data-table docs-table">
              <colgroup>
                <col style={{ width: "44px" }} />
                <col />
                <col style={{ width: "150px" }} />
                <col style={{ width: "18%" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "56px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">
                    <input type="checkbox" aria-label="Select all on this page" checked={allOnPageSelected}
                      onChange={toggleAll} disabled={rows.length === 0} />
                  </th>
                  <th scope="col">Name</th>
                  <th scope="col">Status</th>
                  <th scope="col">Uploaded by</th>
                  <th scope="col">Updated</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {subfolders.map((f) => (
                  <tr key={`folder:${f.name}`} className="docs-table__folder">
                    <td />
                    <td>
                      <button type="button" className="doc-name doc-name--button"
                        onClick={() => setFolder(folder ? `${folder}/${f.name}` : f.name)}>
                        <span className="doc-name__icon doc-name__icon--folder">
                          <FolderIcon />
                        </span>
                        <span className="truncate">{f.name}</span>
                      </button>
                    </td>
                    <td className="muted" colSpan={4}>
                      {f.count} document{f.count === 1 ? "" : "s"}
                    </td>
                  </tr>
                ))}
                {rows.map((d) => (
                  <tr key={d.id} aria-selected={selected.has(d.id)}>
                    <td>
                      <input type="checkbox" aria-label={`Select ${d.filename}`} checked={selected.has(d.id)}
                        onChange={() => toggle(d.id)} />
                    </td>
                    <td>
                      <button type="button" className="doc-name doc-name--button" onClick={() => setOpenId(d.id)}
                        title={`${d.folder ? `${d.folder}/` : ""}${d.filename}`}>
                        <span className={`doc-name__icon doc-name__icon--${extKind(d.filename)}`}>
                          <FileIcon />
                        </span>
                        <span className="doc-name__text">
                          <span className="truncate">{d.filename}</span>
                          <span className="doc-name__sub">
                            {searching && d.folder ? `${d.folder} · ` : ""}
                            {formatSize(d.size_bytes)}
                          </span>
                        </span>
                      </button>
                    </td>
                    <td>
                      <span className={`status status--${d.status}`} title={d.rejection_reason ?? undefined}>
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

      <Modal open={openId !== null} wide title="Document" onClose={() => setOpenId(null)}>
        {openId !== null && (
          <DocumentPanel
            token={token}
            projectId={project.id}
            documentId={openId}
            fields={fields}
            projectBase={{ country: project.country, business_unit: project.business_unit, purpose: project.purpose,
              valid_till: project.valid_till }}
            onClose={() => setOpenId(null)}
            onChanged={(message) => {
              if (message) setNotice({ kind: "ok", text: message });
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={rejecting !== null} title="Reject" onClose={() => setRejecting(null)}>
        {rejecting && (
          <RejectForm
            count={rejecting.length}
            onCancel={() => setRejecting(null)}
            onReject={(reason) => {
              const ids = rejecting;
              setRejecting(null);
              return run("reject", () => reviewDocuments(token, project.id, ids, "reject", reason), "Rejected");
            }}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete documents" onClose={() => setDeleting(null)}>
        {deleting && (
          <>
            <div className="modal__body">
              <p className="modal__text">
                Delete {deleting.length === 1 ? "this document" : `${deleting.length} documents`} and the stored
                file{deleting.length === 1 ? "" : "s"}? Only drafts and rejected documents are deleted; others are
                skipped.
              </p>
            </div>
            <div className="modal__footer">
              <button type="button" className="btn-secondary" onClick={() => setDeleting(null)}>
                Cancel
              </button>
              <button type="button" className="btn-danger" onClick={() => {
                const ids = deleting;
                setDeleting(null);
                run("delete", () => deleteDocuments(token, project.id, ids), "Deleted");
              }}>
                Delete
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

function RejectForm({ count, onCancel, onReject }: { count: number; onCancel: () => void; onReject: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (reason.trim()) onReject(reason.trim()); }}>
      <div className="modal__body">
        <label className="form-field">
          <span>Reason</span>
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} required autoFocus
            placeholder="What the maker needs to fix" />
          <small>
            {count === 1 ? "The document goes" : `The ${count} documents go`} back to the maker with this reason.
          </small>
        </label>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-danger" disabled={!reason.trim()}>
          Reject
        </button>
      </div>
    </form>
  );
}

function extKind(name: string): string {
  const ext = name.slice(name.lastIndexOf(".") + 1).toLowerCase();
  if (ext === "pdf") return "pdf";
  if (ext === "doc" || ext === "docx") return "doc";
  if (ext === "xls" || ext === "xlsx") return "xls";
  if (ext === "csv") return "csv";
  if (ext === "ppt" || ext === "pptx") return "ppt";
  return "other";
}
