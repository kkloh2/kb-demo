import { useEffect, useMemo, useState, type FormEvent } from "react";
import { listDepartments, listUsers, type AdminUser, type DepartmentRow } from "../api/admin";
import { createKnowledgeBase, type KnowledgeBase } from "../api/knowledgeBases";

interface Props {
  token: string;
  onCancel: () => void;
  onCreated: (kb: KnowledgeBase, promoted: AdminUser | null) => void;
}

const isAdmin = (u: AdminUser) => u.roles.includes("department_admin");
const blocksAdmin = (u: AdminUser) => u.roles.some((r) => r === "maker" || r === "checker");

/** System admin: create a knowledge base for a department and name its department admin. */
export function CreateKnowledgeBaseForm({ token, onCancel, onCreated }: Props) {
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [description, setDescription] = useState("");
  const [adminLanId, setAdminLanId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([listDepartments(token), listUsers(token)])
      .then(([d, u]) => {
        setDepartments(d);
        setUsers(u);
      })
      .catch((e: Error) => setError(e.message));
  }, [token]);

  // Users of the chosen department: current admins first, then people who can be made admin.
  const { admins, eligible, blocked } = useMemo(() => {
    const inDept = (users ?? [])
      .filter((u) => u.department?.code === department && u.is_active)
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
    return {
      admins: inDept.filter(isAdmin),
      eligible: inDept.filter((u) => !isAdmin(u) && !blocksAdmin(u)),
      blocked: inDept.filter(blocksAdmin),
    };
  }, [users, department]);

  // Pick the department's admin by default when there's exactly one.
  useEffect(() => {
    setAdminLanId(admins.length === 1 ? admins[0].username : "");
  }, [department, admins]);

  const chosen = (users ?? []).find((u) => u.username === adminLanId) ?? null;
  const willPromote = chosen !== null && !isAdmin(chosen);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const kb = await createKnowledgeBase(token, {
        name,
        description,
        department_code: department,
        admin_lan_id: adminLanId,
      });
      onCreated(kb, willPromote ? chosen : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the knowledge base.");
    } finally {
      setSaving(false);
    }
  }

  const label = (u: AdminUser) => `${u.display_name} (${u.username})`;

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <div className="form-grid">
          <label className="form-field form-field--wide">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={128} required autoFocus />
          </label>

          <label className="form-field form-field--wide">
            <span>Department</span>
            <select value={department} onChange={(e) => setDepartment(e.target.value)} required>
              <option value="" disabled>
                Choose a department
              </option>
              {departments.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>

          <label className="form-field form-field--wide">
            <span>Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="What this knowledge base is for"
            />
          </label>

          <label className="form-field form-field--wide">
            <span>Department admin</span>
            <select
              value={adminLanId}
              onChange={(e) => setAdminLanId(e.target.value)}
              disabled={!department || users === null}
              required
            >
              <option value="" disabled>
                {!department
                  ? "Choose a department first"
                  : admins.length + eligible.length === 0
                    ? "No one in this department can be admin"
                    : "Choose a user"}
              </option>
              {admins.length > 0 && (
                <optgroup label="Department admins">
                  {admins.map((u) => (
                    <option key={u.username} value={u.username}>
                      {label(u)}
                    </option>
                  ))}
                </optgroup>
              )}
              {eligible.length > 0 && (
                <optgroup label="Will be made department admin">
                  {eligible.map((u) => (
                    <option key={u.username} value={u.username}>
                      {label(u)}
                    </option>
                  ))}
                </optgroup>
              )}
              {blocked.length > 0 && (
                <optgroup label="Can't be admin (maker or checker)">
                  {blocked.map((u) => (
                    <option key={u.username} value={u.username} disabled>
                      {label(u)}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            {willPromote ? (
              <small className="form-hint form-hint--warn">
                {chosen.display_name} isn't a department admin yet. Creating this knowledge base makes them
                one, and signs them out so their next sign-in carries the new role.
              </small>
            ) : (
              <small>Shown on the knowledge base as its admin.</small>
            )}
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving || !name.trim() || !department || !adminLanId}>
          {saving ? "Creating…" : "Create knowledge base"}
        </button>
      </div>
    </form>
  );
}
