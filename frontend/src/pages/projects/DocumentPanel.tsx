import { useCallback, useEffect, useState } from "react";
import {
  BASE_LABELS,
  downloadDocument,
  formatSize,
  getDocument,
  reviewDocuments,
  STATUS_LABEL,
  submitDocuments,
  updateMetadata,
  type BaseMetadata,
  type FieldDef,
  type ProjectDocument,
} from "../../api/documents";
import { ApiError } from "../../api/http";
import { CheckIcon, DownloadIcon, PlusIcon, TrashIcon, UploadIcon } from "../../components/Icons";

const BASE_KEYS = Object.keys(BASE_LABELS) as (keyof BaseMetadata)[];

interface Props {
  token: string;
  projectId: number;
  documentId: number;
  fields: FieldDef[];
  projectBase: BaseMetadata;
  onClose: () => void;
  onChanged: (message?: string) => void;
  onSessionEnded: (message: string) => void;
}

/**
 * One document: its file details and its metadata in three parts: base (from the project, which
 * the maker may override), the project's fields, and the maker's own fields. AI metadata is phase 2.
 * Makers edit drafts and rejected documents and submit them; checkers approve or reject pending ones.
 */
export function DocumentPanel({ token, projectId, documentId, fields, projectBase, onClose, onChanged, onSessionEnded }: Props) {
  const [doc, setDoc] = useState<ProjectDocument | null>(null);
  const [base, setBase] = useState<BaseMetadata>(projectBase);
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

  const show = useCallback((d: ProjectDocument) => {
    setDoc(d);
    setBase(d.base);
    setValues(d.fields);
    setExtra(Object.entries(d.extra).map(([key, value]) => ({ key, value })));
  }, []);

  useEffect(() => {
    getDocument(token, projectId, documentId).then(show).catch(fail);
  }, [token, projectId, documentId, show, fail]);

  if (!doc) {
    return <div className="modal__body">{error ? <p className="alert" role="alert">{error}</p> : <p className="muted">Loading…</p>}</div>;
  }

  const editable = doc.actions.edit;
  const payload = () => ({
    base,
    fields: Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim())),
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
      show(await updateMetadata(token, projectId, doc.id, payload()));
      return `Saved metadata for ${doc.filename}.`;
    });

  const saveAndSubmit = () =>
    act("submit", async () => {
      await updateMetadata(token, projectId, doc.id, payload());
      const r = await submitDocuments(token, projectId, [doc.id]);
      if (r.skipped.length) {
        show(await getDocument(token, projectId, doc.id));
        throw new Error(r.skipped[0].reason);
      }
      onClose();
      return `Submitted ${doc.filename} for review.`;
    });

  const decide = (decision: "approve" | "reject") =>
    act(decision, async () => {
      const r = await reviewDocuments(token, projectId, [doc.id], decision, reason);
      if (r.skipped.length) throw new Error(r.skipped[0].reason);
      onClose();
      return `${decision === "approve" ? "Approved" : "Rejected"} ${doc.filename}.`;
    });

  const sameAsProject = (k: keyof BaseMetadata) => (base[k] ?? "") === (projectBase[k] ?? "");
  // Required fields still empty in the form (not just at the last save).
  const missing = fields.filter((f) => f.required && !(values[f.key] ?? "").trim()).map((f) => f.label);

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

        {/* ---------------------------------------------------------------- base */}
        <section className="meta-section">
          <h4 className="meta-section__title">Base metadata</h4>
          <p className="meta-section__desc">From the project. {editable ? "Change a value to override it for this document." : ""}</p>
          <div className="form-grid">
            {BASE_KEYS.map((k) => (
              <label key={k} className="form-field">
                <span>
                  {BASE_LABELS[k]}
                  {!sameAsProject(k) && <span className="tag">Overridden</span>}
                </span>
                <input
                  type={k === "valid_till" ? "date" : "text"}
                  value={base[k] ?? ""}
                  readOnly={!editable}
                  onChange={(e) => setBase((b) => ({ ...b, [k]: k === "valid_till" ? e.target.value || null : e.target.value }))}
                />
                {!sameAsProject(k) && <small>Project: {projectBase[k] || "not set"}</small>}
              </label>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------------- project fields */}
        <section className="meta-section">
          <h4 className="meta-section__title">Project fields</h4>
          {fields.length === 0 ? (
            <p className="meta-section__desc">This project has no fields of its own yet.</p>
          ) : (
            <div className="form-grid">
              {fields.map((f) => (
                <label key={f.key} className="form-field">
                  <span>
                    {f.label}
                    {f.required && <span className="required" aria-label="required"> *</span>}
                  </span>
                  {f.type === "select" ? (
                    <select value={values[f.key] ?? ""} disabled={!editable}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                      <option value="">—</option>
                      {f.options.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input type={f.type === "date" ? "date" : "text"} value={values[f.key] ?? ""} readOnly={!editable}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} />
                  )}
                </label>
              ))}
            </div>
          )}
          {missing.length > 0 && editable && (
            <p className="meta-section__warn">Fill in {missing.join(", ")} before submitting.</p>
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

        {/* ---------------------------------------------------------------- AI */}
        <section className="meta-section meta-section--muted">
          <h4 className="meta-section__title">AI-generated metadata</h4>
          <p className="meta-section__desc">
            Coming in phase 2: extracted from the file automatically, in the background.
          </p>
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
