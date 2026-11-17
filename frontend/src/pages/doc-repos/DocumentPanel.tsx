import { useCallback, useEffect, useState } from "react";
import {
  DECISION_LABEL,
  discardVersion,
  documentHistory,
  downloadDocument,
  downloadVersion,
  formatSize,
  getDocument,
  listVersions,
  restoreVersion,
  STATUS_LABEL,
  submitDocuments,
  updateMetadata,
  type DocRepoDocument,
  type DocumentVersion,
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

/** The status chip colour for a decision. */
const DECISION_STATUS: Record<"APPROVED" | "REJECTED" | "CHANGES_REQUESTED", DocRepoDocument["status"]> = {
  APPROVED: "approved",
  REJECTED: "rejected",
  CHANGES_REQUESTED: "changes_requested",
};

/**
 * One document: its file, its metadata (the repository's fields, which a maker keeps, changes or
 * removes, plus the document's own fields), its versions and its approval history. Makers edit and
 * submit, discard the latest version or restore an earlier one; the decision happens on the
 * Approvals page.
 */
export function DocumentPanel({ token, docRepoId, documentId, onClose, onChanged, onSessionEnded }: Props) {
  const [doc, setDoc] = useState<DocRepoDocument | null>(null);
  const [fields, setFields] = useState<Record<string, FieldState>>({});
  const [own, setOwn] = useState<{ label: string; value: string }[]>([]);
  const [history, setHistory] = useState<RequestHistory[] | null>(null);
  const [versions, setVersions] = useState<DocumentVersion[] | null>(null);
  const [discarding, setDiscarding] = useState(false);
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

  const loadHistory = useCallback(
    (d: DocRepoDocument) => {
      documentHistory(token, docRepoId, d.id).then(setHistory).catch(() => setHistory([]));
      if (d.actions.versions) listVersions(token, docRepoId, d.id).then(setVersions).catch(() => setVersions([]));
    },
    [token, docRepoId],
  );

  useEffect(() => {
    getDocument(token, docRepoId, documentId)
      .then((d) => {
        show(d);
        loadHistory(d);
      })
      .catch(fail);
  }, [token, docRepoId, documentId, show, loadHistory, fail]);

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

  const restore = (v: DocumentVersion) =>
    act(`restore-${v.number}`, async () => {
      const r = await restoreVersion(token, docRepoId, doc.id, v.number);
      show(r);
      loadHistory(r);
      return r.version === doc.version
        ? `Version ${r.version} of ${doc.filename} now has version ${v.number}'s file and metadata. Submit it when ready.`
        : `Restored version ${v.number} of ${doc.filename} as version ${r.version}, a draft. Submit it for approval.`;
    });

  const discard = () =>
    act("discard", async () => {
      const gone = doc.version;
      const r = await discardVersion(token, docRepoId, doc.id);
      setDiscarding(false);
      show(r);
      loadHistory(r);
      return `Discarded version ${gone} of ${doc.filename}; version ${r.version} is the latest again.`;
    });

  const d = doc.last_decision;
  // which version each approval request was for (makers, checkers and auditors see the versions)
  const versionOfRequest: Record<string, number> = Object.fromEntries(
    (versions ?? []).filter((v) => v.approval_request_id).map((v) => [v.approval_request_id as string, v.number]),
  );

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
              <span className="badge badge--neutral">Version {doc.version}</span>
              <span>{doc.folder || "Top level"}</span>
              <span>{formatSize(doc.size_bytes)}</span>
              <span>
                Uploaded by {doc.maker?.display_name ?? "—"} · {new Date(doc.uploaded_at).toLocaleString()}
              </span>
            </p>
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={() => downloadDocument(token, doc).catch(fail)}>
            <DownloadIcon />
            Download
          </button>
        </header>

        {doc.latest && doc.approved_version !== null && doc.approved_version !== doc.version && (
          <MessageBar className="notice notice--info">
            Version {doc.approved_version} is the approved one. Viewers see it until this version is approved.
          </MessageBar>
        )}
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

        {/* ---------------------------------------------------------------- versions */}
        {versions && versions.length > 1 && (
          <section className="meta-section">
            <h4 className="meta-section__title">Versions</h4>
            <ul className="versions">
              {versions.map((v) => (
                <li key={v.number} className={`versions__item${v.discarded_at ? " versions__item--discarded" : ""}`}>
                  <div className="versions__main">
                    <span className="versions__title">
                      <strong>Version {v.number}</strong>
                      {v.discarded_at ? (
                        <span className="badge badge--neutral">Discarded</span>
                      ) : (
                        <span className={`status status--${v.status}`}>{STATUS_LABEL[v.status]}</span>
                      )}
                      {v.latest && <span className="badge badge--neutral">Latest</span>}
                      {v.approved && !v.latest && <span className="badge badge--neutral">What viewers see</span>}
                    </span>
                    <span className="muted versions__sub">
                      {v.uploaded_by?.display_name ?? "—"} · {new Date(v.created_at).toLocaleString()} ·{" "}
                      {formatSize(v.size_bytes)}
                      {v.restored_from ? ` · restored from version ${v.restored_from}` : ""}
                      {v.last_decision
                        ? ` · ${DECISION_LABEL[v.last_decision.decision].toLowerCase()} by ${v.last_decision.decided_by?.display_name ?? "—"}`
                        : ""}
                    </span>
                  </div>
                  <div className="versions__actions">
                    {v.can_restore && (
                      <button type="button" className="btn-link" disabled={busy !== null} onClick={() => restore(v)}>
                        {busy === `restore-${v.number}` ? "Restoring…" : "Restore"}
                      </button>
                    )}
                    <button type="button" className="kb-icon-btn" aria-label={`Download version ${v.number}`}
                      title="Download" onClick={() => downloadVersion(token, doc, v).catch(fail)}>
                      <DownloadIcon />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ---------------------------------------------------------------- history */}
        {history && history.length > 0 && (
          <section className="meta-section">
            <h4 className="meta-section__title">Approval history</h4>
            <ul className="versions">
              {history.flatMap((h) =>
                [...h.rounds].reverse().map((r) => {
                  const dec = r.decisions[r.decisions.length - 1];
                  const withdrawn = !dec && h.status === "CANCELLED";
                  const number = versionOfRequest[h.id];
                  return (
                    <li key={r.id} className="versions__item">
                      <div className="versions__main">
                        <span className="versions__title">
                          <strong>{r.step ?? "Review"}</strong>
                          {dec ? (
                            <span className={`status status--${DECISION_STATUS[dec.decision]}`}>{DECISION_LABEL[dec.decision]}</span>
                          ) : withdrawn ? (
                            <span className="badge badge--neutral">Withdrawn</span>
                          ) : (
                            <span className="status status--pending_approval">Waiting for a decision</span>
                          )}
                          {number !== undefined && <span className="badge badge--neutral">Version {number}</span>}
                          {r.round > 1 && <span className="badge badge--neutral">Round {r.round}</span>}
                        </span>
                        <span className="muted versions__sub">
                          Submitted {new Date(r.created_at).toLocaleString()}
                          {dec ? ` · decided by ${dec.decided_by?.display_name ?? "—"}, ${new Date(dec.decided_at).toLocaleString()}` : ""}
                        </span>
                        {dec?.comment && <p className="history__comment">“{dec.comment}”</p>}
                      </div>
                    </li>
                  );
                }),
              )}
            </ul>
          </section>
        )}
      </div>

      <div className="modal__footer">
        {discarding ? (
          <>
            <span className="modal__footer-note">
              Discard version {doc.version}? Its file and metadata are kept on record, and the document goes back to the
              version before it.
            </span>
            <button type="button" className="btn-secondary" disabled={busy !== null} onClick={() => setDiscarding(false)}>
              Cancel
            </button>
            <button type="button" className="btn-danger" disabled={busy !== null} onClick={discard}>
              <TrashIcon />
              {busy === "discard" ? "Discarding…" : "Discard version"}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            {doc.actions.discard && (
              <button type="button" className="btn-secondary" disabled={busy !== null} onClick={() => setDiscarding(true)}>
                <TrashIcon />
                Discard this version
              </button>
            )}
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
          </>
        )}
      </div>
    </>
  );
}
