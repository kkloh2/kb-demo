import { useState, type FormEvent } from "react";
import { createDocRepo, updateDocRepo, type DocRepo } from "../../api/doc-repos";
import { ApiError } from "../../api/http";
import { MessageBar } from "../../components/MessageBar";

interface Props {
  token: string;
  existing: DocRepo | null; // null: create
  onCancel: () => void;
  onSaved: (docRepo: DocRepo, created: boolean) => void;
  onSessionEnded: (message: string) => void;
}

/** Create a repository (Doc Hub admins; the creator becomes its owner) or edit its name and description. */
export function DocRepoForm({ token, existing, onCancel, onSaved, onSessionEnded }: Props) {
  const [form, setForm] = useState({ name: existing?.name ?? "", description: existing?.description ?? "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (k: "name" | "description") => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const saved = existing ? await updateDocRepo(token, existing.id, form) : await createDocRepo(token, form);
      onSaved(saved, existing === null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save the repository.");
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
          <label className="form-field form-field--wide">
            <span>Repository name</span>
            <input value={form.name} onChange={set("name")} placeholder="e.g. Card Policies" required autoFocus />
          </label>
          <label className="form-field form-field--wide">
            <span>Description</span>
            <textarea rows={2} value={form.description} onChange={set("description")}
              placeholder="What this repository's documents are for" />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : existing ? "Save" : "Create repository"}
        </button>
      </div>
    </form>
  );
}
