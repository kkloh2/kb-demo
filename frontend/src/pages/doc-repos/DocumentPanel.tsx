import { useCallback, useEffect, useState } from "react";
import {
  DECISION_LABEL,
  documentHistory,
  downloadDocument,
  formatSize,
  getDocument,
  STATUS_LABEL,
  submitDocuments,
  updateMetadata,
  type DocRepoDocument,
  type MetadataEntry,
  type RequestHistory,
} from "../../api/documents";
import { ApiError } from "../../api/http";
import { DownloadIcon, PlusIcon, TrashIcon, UploadIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";

interface Props {
  token: string;
  docRepoId: string;
  documentId: string;
  onClose: () => void;
  onChanged: (message?: string) => void;
  onSessionEnded: (message: string) => void;
}

type FieldState = { state: "inherit" | "override" | "remove"; value: string };

const REQUEST_STATUS: Record<RequestHistory["status"], string> = {
  PENDING: "Waiting for a decision",
  CHANGES_REQUESTED: "Changes requested",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CANCELLED: "Withdrawn",
};

/**
 * One document: its file, its metadata (the repository's fields, which a maker keeps, changes or
 * removes, plus the document's own fields) and its approval history. Makers edit and submit; the
 * decision happens on the Approvals page.
 */
export function DocumentPanel({ token, docRepoId, documentId, onClose, onChanged, onSessionEnded }: Props) {
  const [doc, setDoc] = useState<DocRepoDocument | null>(null);
  const [fields, setFields] = useState<Record<string, FieldState>>({});
  const [own, setOwn] = useState<{ label: string; value: string }[]>([]);
  const [history, setHistory] = useState<RequestHistory[] | null>(null);
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
    setFields(
      Object.fromEntries(
        d.metadata
          .filter((m) => m.state !== "own")
          .map((m) => [
            m.field_id,
            {
              state: m.state === "removed" ? "remove" : m.state === "overridden" ? "override" : "inherit",
              value: m.value ?? "",
            },
          ]),
      ),
    );
    setOwn(d.metadata.filter((m) => m.state === "own").map((m) => ({ label: m.label, value: m.value ?? "" })));
  }, []);

  useEffect(() => {
    getDocument(token, docRepoId, documentId).then(show).catch(fail);
    documentHistory(token, docRepoId, documentId).then(setHistory).catch(() => setHistory([]));
  }, [token, docRepoId, documentId, show, fail]);

  if (!doc) {
    return <div className="modal__body">{error ? <MessageBar className="alert" role="alert" onClose={onClose}>{error}</MessageBar> : <p className="muted">Loading…</p>}</div>;
  }

  const editable = doc.actions.edit;
  const repoFields = doc.metadata.filter((m) => m.state !== "own");
  const repoValue = (m: MetadataEntry) => (m.state === "inherited" ? m.value ?? "" : m.inherited_value ?? "");

  function setValue(m: MetadataEntry, value: string) {
    setFields((f) => ({ ...f, [m.field_id]: { state: value === repoValue(m) ? "inherit" : "override", value } }));
  }

  const payload = () => ({
    inherited: repoFields.map((m) => {
      const f = fields[m.field_id];
      return { field_id: m.field_id, state: f.state, value: f.state === "override" ? f.value.trim() : null };
    }),
    own: own.filter((e) => e.label.trim()).map((e) => ({ label: e.label.trim(), value: e.value.trim() })),
  });

  async function act(label: string, work: () => Promise<string | undefined>) {
    setBusy(label);
    setError(null);
    try {
      onChanged(await work());
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
      const r = await submitDocuments(token, docRepoId, { [doc.id]: doc.status });
      if (r.skipped.length) {
        show(await getDocument(token, docRepoId, doc.id));
        throw new Error(r.skipped[0].reason);
      }
      onClose();
      return `Submitted ${doc.filename} for approval.`;
    });

  const d = doc.last_decision;

  return (
    <>
      <div className="modal__body doc-panel">
        {error && (
          <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
            {error}
          </MessageBar>
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
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={() => downloadDocument(token, doc).catch(fail)}>
            <DownloadIcon />
            Download
          </button>
        </header>

        {doc.status === "pending_approval" && (
          <MessageBar className="notice notice--info">Waiting for a checker of this repository to decide, on the Approvals page.</MessageBar>
        )}
        {doc.status === "changes_requested" && d && (
          <MessageBar className="notice notice--info">
            <strong>Changes requested by {d.decided_by?.display_name ?? "a checker"}:</strong> {d.comment}{" "}
            {editable ? "Make the changes, then submit it again." : ""}
          </MessageBar>
        )}
        {doc.status === "rejected" && d && (
          <MessageBar className="notice notice--error">
            <strong>Rejected by {d.decided_by?.display_name ?? "a checker"}:</strong> {d.comment}
          </MessageBar>
        )}
        {doc.status === "approved" && d && (
          <MessageBar className="notice">
            Approved by {d.decided_by?.display_name ?? "a checker"} · {new Date(d.decided_at).toLocaleString()}. Its
            metadata is locked.
          </MessageBar>
        )}

        {/* ---------------------------------------------------------------- repository fields */}
        <section className="meta-section">
          <h4 className="meta-section__title">Repository metadata</h4>
          {repoFields.length === 0 ? (
            <p className="meta-section__desc">This repository has no metadata fields.</p>
          ) : (
            <>
              <p className="meta-section__desc">
                From the repository.{editable ? " Change a value for this document, or remove a field that doesn't apply." : ""}
              </p>
              <div className="form-grid">
                {repoFields.map((m) => {
                  const f = fields[m.field_id] ?? { state: "inherit", value: m.value ?? "" };
                  const removed = f.state === "remove";
                  const changed = f.state === "override";
                  return (
                    <div key={m.field_id} className={`meta-row${removed ? " meta-row--removed" : ""}`}>
                      <label className="form-field">
                        <span>
                          {m.label}
                          {changed && <span className="tag">Changed</span>}
                          {removed && <span className="tag">Removed</span>}
                        </span>
                        <input
                          type="text"
                          value={removed ? repoValue(m) : f.value}
                          readOnly={!editable || removed || !m.overridable}
                          onChange={(e) => setValue(m, e.target.value)}
                        />
                        {(changed || removed) && <small>Repository: {repoValue(m) || "not set"}</small>}
                      </label>
                      {editable && m.overridable && (
                        <div className="meta-row__actions">
                          {(changed || removed) && (
                            <button type="button" className="btn-link"
                              onClick={() => setFields((x) => ({ ...x, [m.field_id]: { state: "inherit", value: repoValue(m) } }))}>
                              Use repository value
                            </button>
                          )}
                          {!removed && (
                            <button type="button" className="kb-icon-btn" aria-label={`Remove ${m.label} from this document`}
                              title="Remove from this document"
                              onClick={() => setFields((x) => ({ ...x, [m.field_id]: { state: "remove", value: "" } }))}>
                              <TrashIcon />
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </section>

        {/* ---------------------------------------------------------------- own fields */}
        <section className="meta-section">
          <h4 className="meta-section__title">Additional metadata</h4>
          <p className="meta-section__desc">Metadata specific to this document, beyond what the repository defines.</p>
          {own.length === 0 && !editable && <p className="muted">None.</p>}
          {own.map((e, i) => (
            <div key={i} className="extra-row">
              <input aria-label="Field name" placeholder="Name" value={e.label} readOnly={!editable}
                onChange={(ev) => setOwn((x) => x.map((r, j) => (j === i ? { ...r, label: ev.target.value } : r)))} />
              <input aria-label="Value" placeholder="Value" value={e.value} readOnly={!editable}
                onChange={(ev) => setOwn((x) => x.map((r, j) => (j === i ? { ...r, value: ev.target.value } : r)))} />
              {editable && (
                <button type="button" className="kb-icon-btn" aria-label="Remove field"
                  onClick={() => setOwn((x) => x.filter((_, j) => j !== i))}>
                  <TrashIcon />
                </button>
              )}
            </div>
          ))}
          {editable && (
            <button type="button" className="btn-link" onClick={() => setOwn((x) => [...x, { label: "", value: "" }])}>
              <PlusIcon /> Add a field
            </button>
          )}
        </section>

        {/* ---------------------------------------------------------------- history */}
        {history && history.length > 0 && (
          <section className="meta-section">
            <h4 className="meta-section__title">Approval history</h4>
            <ul className="history">
              {history.flatMap((h) =>
                [...h.rounds].reverse().map((r) => {
                  const dec = r.decisions[r.decisions.length - 1];
                  const key = dec?.decision ?? (h.status === "CANCELLED" ? "CANCELLED" : "PENDING");
                  return (
                    <li key={r.id} className={`history__item history__item--${key}`}>
                      <strong>
                        {dec ? DECISION_LABEL[dec.decision] : REQUEST_STATUS[h.status === "CANCELLED" ? "CANCELLED" : "PENDING"]}
                      </strong>
                      {r.step && <span className="muted"> · {r.step}</span>}
                      <span className="muted">
                        {" "}· submitted {new Date(r.created_at).toLocaleString()}
                        {r.round > 1 ? ` (round ${r.round})` : ""}
                        {dec ? ` · ${dec.decided_by?.display_name ?? "—"}, ${new Date(dec.decided_at).toLocaleString()}` : ""}
                      </span>
                      {dec?.comment && <p className="history__comment">“{dec.comment}”</p>}
                    </li>
                  );
                }),
              )}
            </ul>
          </section>
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
      </div>
    </>
  );
}
