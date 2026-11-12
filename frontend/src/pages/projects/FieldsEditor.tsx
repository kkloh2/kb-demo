import { useEffect, useState } from "react";
import { listFields, replaceFields, type FieldDef, type FieldType } from "../../api/documents";
import { ApiError } from "../../api/http";
import { PlusIcon, TrashIcon } from "../../components/Icons";

interface Row {
  label: string;
  key: string;
  type: FieldType;
  options: string; // comma-separated in the form
  required: boolean;
}

const toRow = (f: FieldDef): Row => ({ label: f.label, key: f.key, type: f.type, options: f.options.join(", "), required: f.required });

interface Props {
  token: string;
  projectId: number;
  canEdit: boolean; // the department admin
  onSessionEnded: (message: string) => void;
}

/** The project's own metadata fields, which every document fills in. Department admins edit them. */
export function FieldsEditor({ token, projectId, canEdit, onSessionEnded }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const fail = (e: unknown) => {
    if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
    else setError(e instanceof Error ? e.message : "Something went wrong.");
  };

  const load = () => listFields(token, projectId).then((f) => setRows(f.map(toRow))).catch(fail);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void load(), [token, projectId]);

  const set = (i: number, patch: Partial<Row>) => setRows((r) => r && r.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  async function save() {
    if (!rows) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await replaceFields(token, projectId, rows.map((r) => ({
        label: r.label,
        key: r.key,
        type: r.type,
        options: r.type === "select" ? r.options.split(",").map((o) => o.trim()).filter(Boolean) : [],
        required: r.required,
      })));
      setRows(saved.map(toRow));
      setEditing(false);
      setNotice("Saved the project's fields.");
    } catch (e) {
      fail(e);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="fields-title">
      <div className="panel__head">
        <div>
          <h2 id="fields-title" className="panel__title">
            Document fields
          </h2>
          <p className="panel__desc">
            Fields every document in this project fills in, so metadata stays consistent and searchable. Makers can
            add their own fields on top.
          </p>
        </div>
        {canEdit && !editing && (
          <button type="button" className="btn-secondary" onClick={() => { setEditing(true); setNotice(null); }}>
            Edit fields
          </button>
        )}
      </div>

      {notice && <p className="notice" role="status">{notice}</p>}
      {error && <p className="alert" role="alert">{error}</p>}

      {rows === null ? (
        <p className="admin-message">Loading fields…</p>
      ) : !editing ? (
        rows.length === 0 ? (
          <p className="admin-message">No fields yet.{canEdit ? " Use Edit fields to add some." : ""}</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Type</th>
                <th scope="col">Options</th>
                <th scope="col">Required</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td>
                    <div className="person">
                      <span className="person__name">{r.label}</span>
                      <span className="person__id">{r.key}</span>
                    </div>
                  </td>
                  <td>{r.type === "text" ? "Text" : r.type === "date" ? "Date" : "Choice"}</td>
                  <td className="truncate">{r.options || <span className="muted">—</span>}</td>
                  <td>{r.required ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : (
        <div className="fields-edit">
          {rows.map((r, i) => (
            <div key={i} className="fields-edit__row">
              <label className="form-field">
                <span>Label</span>
                <input value={r.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="e.g. Product code" />
              </label>
              <label className="form-field">
                <span>Type</span>
                <select value={r.type} onChange={(e) => set(i, { type: e.target.value as FieldType })}>
                  <option value="text">Text</option>
                  <option value="date">Date</option>
                  <option value="select">Choice</option>
                </select>
              </label>
              <label className="form-field">
                <span>Options</span>
                <input value={r.options} disabled={r.type !== "select"} onChange={(e) => set(i, { options: e.target.value })}
                  placeholder={r.type === "select" ? "Gold, Platinum" : "For choices only"} />
              </label>
              <label className="check fields-edit__required">
                <input type="checkbox" checked={r.required} onChange={(e) => set(i, { required: e.target.checked })} />
                Required
              </label>
              <button type="button" className="kb-icon-btn" aria-label={`Remove ${r.label || "field"}`}
                onClick={() => setRows((x) => x && x.filter((_, j) => j !== i))}>
                <TrashIcon />
              </button>
            </div>
          ))}
          <button type="button" className="btn-link"
            onClick={() => setRows((x) => [...(x ?? []), { label: "", key: "", type: "text", options: "", required: false }])}>
            <PlusIcon /> Add a field
          </button>
          <div className="fields-edit__actions">
            <button type="button" className="btn-secondary" onClick={() => { setEditing(false); setError(null); void load(); }}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={saving} onClick={save}>
              {saving ? "Saving…" : "Save fields"}
            </button>
          </div>
          <small className="muted">Removing a field keeps what makers typed, as one of their own fields.</small>
        </div>
      )}
    </section>
  );
}
