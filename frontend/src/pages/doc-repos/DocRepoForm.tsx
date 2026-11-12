import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/http";
import {
  createDocRepo,
  creatableDepartments,
  updateDocRepo,
  type DepartmentMetadata,
  type DepartmentRef,
  type DocRepo,
  type DocRepoFields,
} from "../../api/doc-repos";

interface Props {
  token: string;
  existing: DocRepo | null; // null: create
  onCancel: () => void;
  onSaved: (docRepo: DocRepo, created: boolean) => void;
  onSessionEnded: (message: string) => void;
}

/** Create a doc-repo (department admins) or edit its name, description and department metadata. */
export function DocRepoForm({ token, existing, onCancel, onSaved, onSessionEnded }: Props) {
  const [departments, setDepartments] = useState<DepartmentRef[] | null>(existing ? [existing.department] : null);
  const [department, setDepartment] = useState(existing?.department.code ?? "");
  const [form, setForm] = useState<DocRepoFields>({
    name: existing?.name ?? "",
    description: existing?.description ?? "",
    department_metadata: existing?.department_metadata ?? { department: "", business_unit: "", country: "" },
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (existing) return;
    creatableDepartments(token)
      .then((d) => {
        setDepartments(d);
        if (d.length === 1) setDepartment(d[0].code);
      })
      .catch((e: Error) => setError(e.message));
  }, [existing, token]);

  const set = (k: "name" | "description") => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  const setMeta = (k: keyof DepartmentMetadata) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, department_metadata: { ...f.department_metadata, [k]: e.target.value } }));
  const departmentName = existing?.department.name ?? departments?.find((d) => d.code === department)?.name;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const saved = existing
        ? await updateDocRepo(token, existing.id, form)
        : await createDocRepo(token, department, form);
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
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="form-grid">
          <label className="form-field">
            <span>Department</span>
            {existing ? (
              <input value={existing.department.name} readOnly />
            ) : (
              <select value={department} onChange={(e) => setDepartment(e.target.value)} required>
                <option value="" disabled>
                  {departments === null ? "Loading…" : "Choose a department"}
                </option>
                {(departments ?? []).map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name} ({d.code})
                  </option>
                ))}
              </select>
            )}
          </label>
          <label className="form-field">
            <span>Repository name</span>
            <input value={form.name} onChange={set("name")} placeholder="e.g. Card Policies" required autoFocus />
          </label>
          <label className="form-field form-field--wide">
            <span>Description</span>
            <textarea rows={2} value={form.description} onChange={set("description")}
              placeholder="What this repository's documents are for" />
          </label>

          <p className="form-section form-field--wide">
            <span>Department metadata</span>
            <small>Every document in the repository starts with these. A maker can override them per document.</small>
          </p>
          <label className="form-field">
            <span>Department</span>
            <input value={form.department_metadata.department} onChange={setMeta("department")}
              placeholder={departmentName ? `Defaults to ${departmentName}` : "Defaults to the department's name"} />
          </label>
          <label className="form-field">
            <span>Business unit</span>
            <input value={form.department_metadata.business_unit} onChange={setMeta("business_unit")}
              placeholder="e.g. Consumer Banking" />
          </label>
          <label className="form-field">
            <span>Country</span>
            <input value={form.department_metadata.country} onChange={setMeta("country")} placeholder="e.g. Singapore" />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || (!existing && !department)}>
          {saving ? "Saving…" : existing ? "Save" : "Create repository"}
        </button>
      </div>
    </form>
  );
}
