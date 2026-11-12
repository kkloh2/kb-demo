import { useCallback, useEffect, useState } from "react";
import {
  downloadDocument,
  formatSize,
  getDocument,
  reviewDocuments,
  STATUS_LABEL,
  submitDocuments,
  updateMetadata,
  type MetadataPair,
  type DocRepoDocument,
} from "../../api/documents";
import { DEPARTMENT_METADATA_KEYS, DEPARTMENT_METADATA_LABELS, type DepartmentMetadata } from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { CheckIcon, DownloadIcon, PlusIcon, TrashIcon, UploadIcon } from "../../components/Icons";

interface Props {
  token: string;
  docRepoId: number;
  documentId: number;
  repoPairs: MetadataPair[]; // the doc-repo's repository metadata
  repoDefaults: DepartmentMetadata; // the doc-repo's department metadata
  onClose: () => void;
  onChanged: (message?: string) => void;
  onSessionEnded: (message: string) => void;
}

/**
 * One document: its file details and its metadata in three parts: department metadata (from the doc-repo, which
 * the maker may override), repository metadata (likewise), and the maker's own fields.
 * Makers edit drafts and rejected documents and submit them; checkers approve or reject pending ones.
 */
export function DocumentPanel({ token, docRepoId, documentId, repoPairs, repoDefaults, onClose, onChanged, onSessionEnded }: Props) {
  const [doc, setDoc] = useState<DocRepoDocument | null>(null);
  const [dept, setDept] = useState<DepartmentMetadata>(repoDefaults);
  const [values, setValues] = useState<Record<string, string>>({});
  const [extra, setExtra] = useState<{ key: string; value: string }[]>([]);
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else setError(e instanceof Error ? e.message : "Something went wrong.");
    },
    [onSessionEnded],
  );

  const show = useCallback((d: DocRepoDocument) => {
    setDoc(d);
    setDept(d.department_metadata);
    setValues(d.repository_metadata);
    setExtra(Object.entries(d.extra).map(([key, value]) => ({ key, value })));
  }, []);

  useEffect(() => {
    getDocument(token, docRepoId, documentId).then(show).catch(fail);
  }, [token, docRepoId, documentId, show, fail]);

  if (!doc) {
    return <div className="modal__body">{error ? <p className="alert" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  }

  const editable = doc.actions.edit;
  const payload = () => ({
    department_metadata: dept,
    repository_metadata: Object.fromEntries(repoPairs.map((p) => [p.key, (values[p.key] ?? "").trim()])),
    extra: Object.fromEntries(extra.filter((e) => e.key.trim() && e.value.trim()).map((e) => [e.key.trim(), e.value.trim()])),
  });

  async function act(label: string, work: () => Promise<string | undefined>) {
    setBusy(label);
    setError(null);
    try {
      const message = await work();
      onChanged(message);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  const save = () =>
    act("save", async () => {
      show(await updateMetadata(token, docRepoId, doc.id, payload()));
      return `Saved metadata for ${doc.filename}.`;
    });

  const saveAndSubmit = () =>
    act("submit", async () => {
      await updateMetadata(token, docRepoId, doc.id, payload());
      const r = await submitDocuments(token, docRepoId, [doc.id]);
      if (r.skipped.length) {
        show(await getDocument(token, docRepoId, doc.id));
        throw new Error(r.skipped[0].reason);
      }
      onClose();
      return `Submitted ${doc.filename} for review.`;
    });

  const decide = (decision: "approve" | "reject") =>
    act(decision, async () => {
      const r = await reviewDocuments(token, docRepoId, [doc.id], decision, reason);
      if (r.skipped.length) throw new Error(r.skipped[0].reason);
      onClose();
      return `${decision === "approve" ? "Approved" : "Rejected"} ${doc.filename}.`;
    });

  const sameAsDocRepo = (k: keyof DepartmentMetadata) => (dept[k] ?? "") === (repoDefaults[k] ?? "");

  return (
    <>
      <div className="modal__body doc-panel">
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}

        <header className="doc-panel__head">
          <div>
            <h3 className="doc-panel__name">{doc.filename}</h3>
            <p className="doc-panel__meta">
              <span className={`status status--${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
              <span>{doc.folder || "Top level"}</span>
              <span>{formatSize(doc.size_bytes)}</span>
              <span>
                Uploaded by {doc.maker?.display_name ?? "—"} · {new Date(doc.created_at).toLocaleString()}
              </span>
            </p>
            {doc.checker && (
              <p className="doc-panel__meta">
                <span>
                  {doc.status === "approved" ? "Approved" : "Rejected"} by {doc.checker.display_name}
                  {doc.decided_at ? ` · ${new Date(doc.decided_at).toLocaleString()}` : ""}
                </span>
              </p>
            )}
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={() => downloadDocument(token, doc).catch(fail)}>
            <DownloadIcon />
            Download
          </button>
        </header>

        {doc.status === "rejected" && doc.rejection_reason && (
          <p className="notice notice--error">
            <strong>Rejected:</strong> {doc.rejection_reason}
          </p>
        )}

        {/* ---------------------------------------------------------------- department */}
        <section className="meta-section">
          <h4 className="meta-section__title">Department metadata</h4>
          <p className="meta-section__desc">Set by the department admin for every document in this repository.{" "}
            {editable ? "Change a value to override it for this document." : ""}</p>
          <div className="form-grid">
            {DEPARTMENT_METADATA_KEYS.map((k) => (
              <label key={k} className="form-field">
                <span>
                  {DEPARTMENT_METADATA_LABELS[k]}
                  {!sameAsDocRepo(k) && <span className="tag">Overridden</span>}
                </span>
                <input
                  type="text"
                  value={dept[k] ?? ""}
                  readOnly={!editable}
                  onChange={(e) => setDept((d) => ({ ...d, [k]: e.target.value }))}
                />
                {!sameAsDocRepo(k) && <small>Repository: {repoDefaults[k] || "not set"}</small>}
              </label>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------------- repository */}
        <section className="meta-section">
          <h4 className="meta-section__title">Repository metadata</h4>
          {repoPairs.length === 0 ? (
            <p className="meta-section__desc">This repository has no metadata of its own yet.</p>
          ) : (
            <>
              <p className="meta-section__desc">
                Set by the department admin for this repository.{" "}
                {editable ? "Change a value to override it for this document." : ""}
              </p>
              <div className="form-grid">
                {repoPairs.map((p) => {
                  const value = values[p.key] ?? "";
                  const overridden = value !== p.value;
                  return (
                    <label key={p.key} className="form-field">
                      <span>
                        {p.key}
                        {overridden && <span className="tag">Overridden</span>}
                      </span>
                      <input value={value} readOnly={!editable}
                        onChange={(e) => setValues((v) => ({ ...v, [p.key]: e.target.value }))} />
                      {overridden && <small>Repository: {p.value || "not set"}</small>}
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </section>

        {/* ---------------------------------------------------------------- extra */}
        <section className="meta-section">
          <h4 className="meta-section__title">Additional fields</h4>
          <p className="meta-section__desc">Anything else worth recording about this document.</p>
          {extra.length === 0 && !editable && <p className="muted">None.</p>}
          {extra.map((e, i) => (
            <div key={i} className="extra-row">
              <input aria-label="Field name" placeholder="Name" value={e.key} readOnly={!editable}
                onChange={(ev) => setExtra((x) => x.map((r, j) => (j === i ? { ...r, key: ev.target.value } : r)))} />
              <input aria-label="Value" placeholder="Value" value={e.value} readOnly={!editable}
                onChange={(ev) => setExtra((x) => x.map((r, j) => (j === i ? { ...r, value: ev.target.value } : r)))} />
              {editable && (
                <button type="button" className="kb-icon-btn" aria-label="Remove field"
                  onClick={() => setExtra((x) => x.filter((_, j) => j !== i))}>
                  <TrashIcon />
                </button>
              )}
            </div>
          ))}
          {editable && (
            <button type="button" className="btn-link" onClick={() => setExtra((x) => [...x, { key: "", value: "" }])}>
              <PlusIcon /> Add a field
            </button>
          )}
        </section>

        {doc.actions.review && rejecting && (
          <label className="form-field">
            <span>Reason for rejecting</span>
            <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus
              placeholder="What the maker needs to fix" />
          </label>
        )}
      </div>

      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onClose}>
          Close
        </button>
        {editable && (
          <>
            <button type="button" className="btn-outline" disabled={busy !== null} onClick={save}>
              {busy === "save" ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={saveAndSubmit}>
              <UploadIcon />
              {busy === "submit" ? "Submitting…" : "Save and submit"}
            </button>
          </>
        )}
        {doc.actions.review && !rejecting && (
          <>
            <button type="button" className="btn-outline" onClick={() => setRejecting(true)}>
              Reject…
            </button>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => decide("approve")}>
              <CheckIcon />
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
          </>
        )}
        {doc.actions.review && rejecting && (
          <button type="button" className="btn-danger" disabled={busy !== null || !reason.trim()} onClick={() => decide("reject")}>
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
        )}
      </div>
    </>
  );
}
