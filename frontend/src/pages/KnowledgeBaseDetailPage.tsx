import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { User } from "../api/auth";
import {
  approveDocument,
  downloadDocument,
  getKnowledgeBase,
  listDocuments,
  rejectDocument,
  uploadDocuments,
  type DocumentStatus,
  type KbDocument,
  type KnowledgeBaseDetail,
} from "../api/documents";
import { setFavorite } from "../api/knowledgeBases";
import {
  CheckIcon,
  ChevronIcon,
  CloseIcon,
  DownloadIcon,
  FileIcon,
  KnowledgeBaseIcon,
  MoreIcon,
  PlusIcon,
  SearchIcon,
  StarIcon,
  UploadIcon,
} from "../components/Icons";
import { Menu } from "../components/Menu";
import { Modal } from "../components/Modal";
import { Pager, usePagination } from "../components/Pager";
import { timeAgo } from "../lib/time";
import { ActivityTab } from "./kb/ActivityTab";
import "../styles/knowledge-bases.css";
import "../styles/admin.css";
import "../styles/kb-detail.css";

const ACCEPT = ".pdf,.docx,.doc,.xlsx,.xls,.pptx,.csv,.txt,.md";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  approved: "Approved",
  pending_approval: "Pending approval",
  rejected: "Rejected",
};

type StatusFilter = "all" | DocumentStatus;

interface Props {
  token: string;
  user: User;
  kbId: string;
  onBack: () => void;
}

export function KnowledgeBaseDetailPage({ token, kbId, onBack }: Props) {
  const [kb, setKb] = useState<KnowledgeBaseDetail | null>(null);
  const [docs, setDocs] = useState<KbDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [uploading, setUploading] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<KbDocument | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<"documents" | "activity">("documents");
  const [activityVersion, setActivityVersion] = useState(0); // refresh Activity after changes

  const loadDocs = useCallback(
    () =>
      listDocuments(token, kbId)
        .then(setDocs)
        .catch((e: Error) => setError(e.message)),
    [token, kbId],
  );

  useEffect(() => {
    setKb(null);
    setDocs(null);
    setError(null);
    getKnowledgeBase(token, kbId)
      .then((k) => {
        setKb(k);
        if (k.capabilities.view_documents) loadDocs();
      })
      .catch((e: Error) => setError(e.message));
  }, [token, kbId, loadDocs]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (docs ?? []).filter(
      (d) => (status === "all" || d.status === status) && (!q || d.filename.toLowerCase().includes(q)),
    );
  }, [docs, query, status]);
  const { rows, ...pager } = usePagination(filtered);

  async function onFilesChosen(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (fileInput.current) fileInput.current.value = ""; // allow choosing the same file again
    if (!files.length) return;
    setUploading(files.length);
    setNotice(null);
    try {
      const created = await uploadDocuments(token, kbId, files);
      setNotice({
        kind: "ok",
        text: `Uploaded ${created.length} file${created.length === 1 ? "" : "s"}. ${
          created.length === 1 ? "It's" : "They're"
        } pending approval by a checker.`,
      });
      await loadDocs();
      setActivityVersion((v) => v + 1);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : "Upload failed." });
    } finally {
      setUploading(null);
    }
  }

  async function act(fn: () => Promise<unknown>, success: string) {
    setNotice(null);
    try {
      await fn();
      setNotice({ kind: "ok", text: success });
      await loadDocs();
      setActivityVersion((v) => v + 1);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : "Something went wrong." });
    }
  }

  function toggleFavorite() {
    if (!kb) return;
    const next = !kb.favorite;
    setKb({ ...kb, favorite: next });
    setFavorite(token, kb.id, next).catch(() => setKb((k) => (k ? { ...k, favorite: !next } : k)));
  }

  const back = (
    <button type="button" className="back-link" onClick={onBack}>
      <ChevronIcon dir="left" />
      All knowledge bases
    </button>
  );

  if (error && !kb) {
    return (
      <div className="page">
        {back}
        <p className="kb-message kb-message--error" role="alert">
          {error}
        </p>
      </div>
    );
  }
  if (!kb) {
    return (
      <div className="page">
        {back}
        <p className="kb-message">Loading…</p>
      </div>
    );
  }

  const caps = kb.capabilities;

  return (
    <div className="page">
      {back}

      <header className="kb-head">
        <div className="kb-head__title-row">
          <span className="kb-head__icon">
            <KnowledgeBaseIcon />
          </span>
          <h1 className="kb-head__title">{kb.name}</h1>
          <button
            type="button"
            className="kb-icon-btn kb-icon-btn--star kb-head__star"
            aria-pressed={kb.favorite}
            aria-label={kb.favorite ? "Remove from favourites" : "Add to favourites"}
            title={kb.favorite ? "Remove from favourites" : "Add to favourites"}
            onClick={toggleFavorite}
          >
            <StarIcon filled={kb.favorite} />
          </button>
        </div>
        {kb.description && <p className="kb-head__desc">{kb.description}</p>}
        <p className="kb-head__meta">
          <span className="badge">{kb.department.name}</span>
          {kb.access === "granted" && <span className="badge badge--neutral">Shared with me · view only</span>}
          {kb.admin && (
            <span className="muted" title={kb.admin.username}>
              Admin: {kb.admin.display_name}
            </span>
          )}
          <span className="muted">Updated {timeAgo(kb.updated_at)}</span>
        </p>
      </header>

      {!caps.view_documents ? (
        <p className="kb-message">
          Admins manage knowledge bases and people; documents aren't shown to admins.
        </p>
      ) : (
        <>
          <div className="tabs" role="tablist" aria-label="Knowledge base">
            {(["documents", "activity"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                id={`kb-tab-${t}`}
                aria-selected={tab === t}
                aria-controls={`kb-panel-${t}`}
                className="tab"
                onClick={() => setTab(t)}
              >
                {t === "documents" ? `Documents${docs ? ` (${docs.length})` : ""}` : "Activity"}
              </button>
            ))}
          </div>

          {tab === "activity" ? (
            <div role="tabpanel" id="kb-panel-activity" aria-labelledby="kb-tab-activity">
              <ActivityTab token={token} kbId={kbId} version={activityVersion} />
            </div>
          ) : (
            <div role="tabpanel" id="kb-panel-documents" aria-labelledby="kb-tab-documents">
            <div className="toolbar">
              <div className="toolbar__left">
                <label className="search">
                  <SearchIcon />
                  <input
                    type="search"
                    placeholder="Search by name…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    aria-label="Search documents by name"
                  />
                </label>
                {caps.view_unapproved && (
                  <label className="filter">
                    <span className="sr-only">Status</span>
                    <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
                      <option value="all">All statuses</option>
                      <option value="approved">Approved</option>
                      <option value="pending_approval">Pending approval</option>
                      <option value="rejected">Rejected</option>
                    </select>
                    <ChevronIcon dir="down" />
                  </label>
                )}
              </div>

              {caps.upload && (
                <>
                  <Menu
                    trigger={(props) => (
                      <button type="button" className="btn-outline" disabled={uploading !== null} {...props}>
                        <PlusIcon />
                        {uploading !== null ? `Uploading ${uploading}…` : "Add"}
                        <ChevronIcon dir="down" />
                      </button>
                    )}
                    items={[
                      { label: "Upload files", icon: <UploadIcon />, onSelect: () => fileInput.current?.click() },
                    ]}
                  />
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    accept={ACCEPT}
                    hidden
                    onChange={(e) => onFilesChosen(e.target.files)}
                  />
                </>
              )}
            </div>

            {notice && (
              <p className={notice.kind === "ok" ? "notice" : "notice notice--error"} role="status">
                {notice.text}
              </p>
            )}

            <div className="kb-table-panel">
              {docs === null ? (
                <p className="kb-message">Loading documents…</p>
              ) : filtered.length === 0 ? (
                <p className="kb-message">
                  {docs.length === 0
                    ? caps.upload
                      ? "No documents yet. Use Add → Upload files to add the first one."
                      : "No documents yet."
                    : "No documents match your search."}
                </p>
              ) : (
                <>
                  <table className="data-table">
                    <colgroup>
                      <col style={{ width: "36%" }} />
                      <col style={{ width: "18%" }} />
                      <col style={{ width: "16%" }} />
                      <col style={{ width: "20%" }} />
                      <col />
                    </colgroup>
                    <thead>
                      <tr>
                        <th scope="col">Name</th>
                        <th scope="col">Status</th>
                        <th scope="col">Added on</th>
                        <th scope="col">Added by</th>
                        <th scope="col">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((d) => (
                        <tr key={d.id}>
                          <td>
                            <span className="doc-name">
                              <span className={`doc-name__icon doc-name__icon--${ext(d.filename)}`}>
                                <FileIcon />
                              </span>
                              {d.has_file ? (
                                <button
                                  type="button"
                                  className="link-button truncate"
                                  title={`Download ${d.filename}`}
                                  onClick={() =>
                                    downloadDocument(token, d).catch((e: Error) =>
                                      setNotice({ kind: "error", text: e.message }),
                                    )
                                  }
                                >
                                  {d.filename}
                                </button>
                              ) : (
                                <span className="truncate">{d.filename}</span>
                              )}
                            </span>
                          </td>
                          <td>
                            <span
                              className={`status status--${d.status}`}
                              title={d.rejection_reason ? `Reason: ${d.rejection_reason}` : undefined}
                            >
                              {d.status === "approved" && <CheckIcon />}
                              {STATUS_LABEL[d.status]}
                            </span>
                          </td>
                          <td title={new Date(d.submitted_at).toLocaleString()}>{timeAgo(d.submitted_at)}</td>
                          <td className="truncate" title={d.maker.username}>
                            {d.maker.display_name}
                          </td>
                          <td>
                            <Menu
                              trigger={(props) => (
                                <button
                                  type="button"
                                  className="kb-icon-btn kb-icon-btn--brand"
                                  aria-label={`Actions for ${d.filename}`}
                                  {...props}
                                >
                                  <MoreIcon />
                                </button>
                              )}
                              items={[
                                ...(d.has_file
                                  ? [
                                      {
                                        label: "Download",
                                        icon: <DownloadIcon />,
                                        onSelect: () =>
                                          downloadDocument(token, d).catch((e: Error) =>
                                            setNotice({ kind: "error", text: e.message }),
                                          ),
                                      },
                                    ]
                                  : []),
                                ...(caps.review && d.status === "pending_approval"
                                  ? [
                                      {
                                        label: "Approve",
                                        icon: <CheckIcon />,
                                        onSelect: () =>
                                          act(() => approveDocument(token, d.id), `Approved ${d.filename}.`),
                                      },
                                      {
                                        label: "Reject…",
                                        icon: <CloseIcon />,
                                        danger: true,
                                        onSelect: () => setRejecting(d),
                                      },
                                    ]
                                  : []),
                              ]}
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
            </div>
          )}
        </>
      )}

      <Modal open={rejecting !== null} title="Reject document" onClose={() => setRejecting(null)}>
        {rejecting && (
          <RejectForm
            doc={rejecting}
            onCancel={() => setRejecting(null)}
            onReject={async (reason) => {
              const d = rejecting;
              setRejecting(null);
              await act(() => rejectDocument(token, d.id, reason), `Rejected ${d.filename}.`);
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function ext(filename: string): string {
  const e = filename.split(".").pop()?.toLowerCase() ?? "";
  return ["pdf", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx"].includes(e) ? e.replace(/x$/, "") : "other";
}

function RejectForm({
  doc,
  onCancel,
  onReject,
}: {
  doc: KbDocument;
  onCancel: () => void;
  onReject: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (reason.trim()) onReject(reason.trim());
      }}
    >
      <div className="modal__body">
        <p className="panel__desc" style={{ marginBottom: 16 }}>
          {doc.maker.display_name} will see your reason on <strong>{doc.filename}</strong>.
        </p>
        <label className="form-field">
          <span>Reason</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            maxLength={1000}
            required
            autoFocus
          />
        </label>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={!reason.trim()}>
          Reject
        </button>
      </div>
    </form>
  );
}
