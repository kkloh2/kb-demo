import { useState, type FormEvent } from "react";
import { setRepoMetadata, type MetadataPair } from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { EditIcon, PlusIcon, TrashIcon } from "../../components/Icons";
import { MessageBar } from "../../components/MessageBar";
import { Modal } from "../../components/Modal";
import { ConfirmDelete } from "../admin/common";

interface Props {
  token: string;
  docRepoId: string;
  pairs: MetadataPair[];
  canEdit: boolean; // owner and admins
  onSaved: (pairs: MetadataPair[]) => void;
  onSessionEnded: (message: string) => void;
}

/**
 * The repository's metadata fields as a list: every document here inherits them (a maker can change
 * or remove them per document and add their own). The owner and admins add, edit and delete them.
 */
export function RepositoryMetadataPanel({ token, docRepoId, pairs, canEdit, onSaved, onSessionEnded }: Props) {
  const [editing, setEditing] = useState<{ index: number | null } | null>(null); // index null: add
  const [deleting, setDeleting] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  /** Save the whole list (the API replaces it), then report. */
  async function save(next: MetadataPair[], message: string) {
    const saved = await setRepoMetadata(token, docRepoId, next);
    onSaved(saved);
    setNotice(message);
  }

  return (
    <section className="panel" aria-labelledby="repo-meta-title">
      <div className="panel__head">
        <div>
          <h2 id="repo-meta-title" className="panel__title">
            Repository metadata
          </h2>
          <p className="panel__desc">Default metadata for documents in this repository.</p>
        </div>
        {canEdit && (
          <button type="button" className="btn-primary" onClick={() => { setEditing({ index: null }); setNotice(null); }}>
            <PlusIcon />
            Add field
          </button>
        )}
      </div>

      {notice && <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>}

      {pairs.length === 0 ? (
        <p className="admin-message">No metadata fields yet.</p>
      ) : (
        <table className="data-table">
          <colgroup>
            <col style={{ width: "34%" }} />
            <col />
            {canEdit && <col style={{ width: "96px" }} />}
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Value</th>
              {canEdit && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {pairs.map((p, i) => (
              <tr key={p.label}>
                <td className="truncate">{p.label}</td>
                <td className="truncate">{p.value || <span className="muted">Not set</span>}</td>
                {canEdit && (
                  <td className="row-actions">
                      <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Edit ${p.label}`}
                        title="Edit" onClick={() => { setEditing({ index: i }); setNotice(null); }}>
                        <EditIcon />
                      </button>
                      <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Delete ${p.label}`}
                        title="Delete" onClick={() => { setDeleting(i); setNotice(null); }}>
                        <TrashIcon />
                      </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Modal open={editing !== null} title={editing?.index == null ? "Add field" : "Edit field"} onClose={() => setEditing(null)}>
        {editing && (
          <FieldForm
            existing={editing.index == null ? null : pairs[editing.index]}
            onCancel={() => setEditing(null)}
            onSave={async (field) => {
              const next = editing.index == null
                ? [...pairs, field]
                : pairs.map((p, j) => (j === editing.index ? field : p));
              await save(next, editing.index == null ? `Added ${field.label}.` : `Saved ${field.label}.`);
              setEditing(null);
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete field" onClose={() => setDeleting(null)}>
        {deleting !== null && pairs[deleting] && (
          <ConfirmDelete
            message={<>Delete <strong>{pairs[deleting].label}</strong> from this repository's metadata?</>}
            confirmLabel="Delete field"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              const label = pairs[deleting].label;
              try {
                await save(pairs.filter((_, j) => j !== deleting), `Deleted ${label}.`);
                setDeleting(null);
              } catch (e) {
                if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
                else throw e;
              }
            }}
          />
        )}
      </Modal>
    </section>
  );
}

function FieldForm({
  existing,
  onCancel,
  onSave,
  onSessionEnded,
}: {
  existing: MetadataPair | null;
  onCancel: () => void;
  onSave: (field: MetadataPair) => Promise<void>;
  onSessionEnded: (message: string) => void;
}) {
  const [label, setLabel] = useState(existing?.label ?? "");
  const [value, setValue] = useState(existing?.value ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave({ label: label.trim(), value: value.trim() });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save.");
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        {error && (
          <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
            {error}
          </MessageBar>
        )}
        <div className="form-grid">
          <label className="form-field">
            <span>Field</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} required autoFocus={existing === null} />
          </label>
          <label className="form-field">
            <span>Value</span>
            <input value={value} onChange={(e) => setValue(e.target.value)} autoFocus={existing !== null} />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || !label.trim()}>
          {saving ? "Saving…" : existing ? "Save" : "Add field"}
        </button>
      </div>
    </form>
  );
}
