import { useState } from "react";
import { replaceRepositoryMetadata, type MetadataPair } from "../../api/documents";
import { ApiError } from "../../api/http";
import { EditIcon, PlusIcon, TrashIcon } from "../../components/Icons";

interface Props {
  token: string;
  docRepoId: number;
  pairs: MetadataPair[];
  canEdit: boolean; // the department admin
  onSaved: (pairs: MetadataPair[]) => void;
  onSessionEnded: (message: string) => void;
}

/**
 * The doc-repo's repository metadata: plain text key/value pairs. Every new document starts with
 * these values and a maker can change them per document. Department admins edit them.
 */
export function RepositoryMetadataPanel({ token, docRepoId, pairs, canEdit, onSaved, onSessionEnded }: Props) {
  const [rows, setRows] = useState<MetadataPair[] | null>(null); // null: not editing
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (i: number, patch: Partial<MetadataPair>) =>
    setRows((r) => r && r.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  async function save() {
    if (!rows) return;
    setSaving(true);
    setError(null);
    try {
      // Rows left completely empty are dropped; a key without a value is fine.
      const saved = await replaceRepositoryMetadata(token, docRepoId, rows.filter((r) => r.key.trim() || r.value.trim()));
      onSaved(saved);
      setRows(null);
      setNotice("Saved the repository metadata.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="repo-meta-title">
      <div className="panel__head">
        <div>
          <h2 id="repo-meta-title" className="panel__title">
            Repository metadata
          </h2>
          <p className="panel__desc">
            Every document in this repository starts with these values. A maker can change them per document and add
            their own fields on top.
          </p>
        </div>
        {canEdit && rows === null && (
          <button type="button" className="btn-secondary"
            onClick={() => { setRows(pairs.length ? pairs : [{ key: "", value: "" }]); setNotice(null); }}>
            <EditIcon />
            Edit
          </button>
        )}
      </div>

      {notice && <p className="notice" role="status">{notice}</p>}
      {error && <p className="alert" role="alert">{error}</p>}

      {rows === null ? (
        pairs.length === 0 ? (
          <p className="admin-message">None yet.{canEdit ? " Use Edit to add some." : ""}</p>
        ) : (
          <dl className="meta-list">
            {pairs.map((p) => (
              <div key={p.key} className="meta-list__row">
                <dt>{p.key}</dt>
                <dd>{p.value || <span className="muted">Not set</span>}</dd>
              </div>
            ))}
          </dl>
        )
      ) : (
        <div className="fields-edit">
          {rows.map((r, i) => (
            <div key={i} className="fields-edit__row">
              <label className="form-field">
                <span>Key</span>
                <input value={r.key} onChange={(e) => set(i, { key: e.target.value })} placeholder="e.g. Product code" />
              </label>
              <label className="form-field">
                <span>Value</span>
                <input value={r.value} onChange={(e) => set(i, { value: e.target.value })} placeholder="e.g. VISA-PLAT" />
              </label>
              <button type="button" className="kb-icon-btn" aria-label={`Remove ${r.key || "entry"}`}
                onClick={() => setRows((x) => x && x.filter((_, j) => j !== i))}>
                <TrashIcon />
              </button>
            </div>
          ))}
          <button type="button" className="btn-link" onClick={() => setRows((x) => [...(x ?? []), { key: "", value: "" }])}>
            <PlusIcon /> Add a key
          </button>
          <div className="fields-edit__actions">
            <button type="button" className="btn-secondary" onClick={() => { setRows(null); setError(null); }}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={saving} onClick={save}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
          <small className="muted">
            Changes apply to documents uploaded from now on. Removing a key keeps what makers typed, as one of their own
            fields.
          </small>
        </div>
      )}
    </section>
  );
}
