import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/http";
import {
  createProject,
  creatableDepartments,
  updateProject,
  type DepartmentRef,
  type Project,
  type ProjectFields,
} from "../../api/projects";

interface Props {
  token: string;
  existing: Project | null; // null: create
  onCancel: () => void;
  onSaved: (project: Project, created: boolean) => void;
  onSessionEnded: (message: string) => void;
}

/** Create a project (department admins) or edit its name, description and base metadata. */
export function ProjectForm({ token, existing, onCancel, onSaved, onSessionEnded }: Props) {
  const [departments, setDepartments] = useState<DepartmentRef[] | null>(existing ? [existing.department] : null);
  const [department, setDepartment] = useState(existing?.department.code ?? "");
  const [form, setForm] = useState<ProjectFields>({
    name: existing?.name ?? "",
    description: existing?.description ?? "",
    country: existing?.country ?? "",
    business_unit: existing?.business_unit ?? "",
    purpose: existing?.purpose ?? "",
    valid_till: existing?.valid_till ?? null,
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

  const set = (k: keyof ProjectFields) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: k === "valid_till" ? e.target.value || null : e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const saved = existing
        ? await updateProject(token, existing.id, form)
        : await createProject(token, department, form);
      onSaved(saved, existing === null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save the project.");
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
            <span>Project name</span>
            <input value={form.name} onChange={set("name")} placeholder="e.g. Card Policies" required autoFocus />
          </label>
          <label className="form-field form-field--wide">
            <span>Description</span>
            <textarea rows={2} value={form.description} onChange={set("description")}
              placeholder="What this project's documents are for" />
          </label>

          <p className="form-section form-field--wide">
            <span>Base metadata</span>
            <small>Every document in the project starts with these. A maker can override them per document.</small>
          </p>
          <label className="form-field">
            <span>Country</span>
            <input value={form.country} onChange={set("country")} placeholder="e.g. Singapore" />
          </label>
          <label className="form-field">
            <span>Business unit</span>
            <input value={form.business_unit} onChange={set("business_unit")} placeholder="e.g. Consumer Banking" />
          </label>
          <label className="form-field">
            <span>Purpose</span>
            <input value={form.purpose} onChange={set("purpose")} placeholder="e.g. Credit card, Loan" />
          </label>
          <label className="form-field">
            <span>Valid till</span>
            <input type="date" value={form.valid_till ?? ""} onChange={set("valid_till")} />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || (!existing && !department)}>
          {saving ? "Saving…" : existing ? "Save" : "Create project"}
        </button>
      </div>
    </form>
  );
}
