import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { User } from "../../api/auth";
import {
  createUser,
  listDepartments,
  listUsers,
  ROLE_NAMES,
  type AdminUser,
  type DepartmentRow,
} from "../../api/admin";
import { PlusIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";

interface Props {
  token: string;
  user: User;
}

function roleLabels(u: AdminUser): string[] {
  if (u.roles.length) return u.roles.map((r) => ROLE_NAMES[r] ?? r);
  return u.department ? ["Viewer"] : [];
}

export function UsersTab({ token, user }: Props) {
  const isSystemAdmin = user.roles.includes("system_admin");
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    listUsers(token).then(setUsers).catch((e: Error) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);

  const { rows, ...pager } = usePagination(users ?? []);

  return (
    <section className="panel" aria-labelledby="users-title">
      <div className="panel__head">
        <div>
          <h2 id="users-title" className="panel__title">
            Manage users
          </h2>
          <p className="panel__desc">
            {isSystemAdmin
              ? "Users across all departments. Users you add become their department's admin."
              : `Users in ${user.department?.name}. Add users as viewers, makers or checkers.`}
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
          <PlusIcon />
          Add user
        </button>
      </div>

      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}

      {error ? (
        <p className="kb-message kb-message--error" role="alert">
          {error}
        </p>
      ) : users === null ? (
        <p className="kb-message">Loading users…</p>
      ) : (
        <>
          <table className="data-table">
            <colgroup>
              <col style={{ width: "24%" }} />
              <col style={{ width: "24%" }} />
              <col style={{ width: "18%" }} />
              <col style={{ width: "18%" }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Department</th>
                <th scope="col">Job title</th>
                <th scope="col">Role</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.username}>
                  <td>
                    <div className="person">
                      <span className="person__name">{u.display_name}</span>
                      <span className="person__id">{u.username}</span>
                    </div>
                  </td>
                  <td className="truncate">{u.email}</td>
                  <td className="truncate">{u.department?.name ?? "—"}</td>
                  <td className="truncate">{u.title || "—"}</td>
                  <td>
                    {roleLabels(u).map((r) => (
                      <span key={r} className="badge">
                        {r}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal open={adding} title="Add user" onClose={() => setAdding(false)}>
        <AddUserForm
          token={token}
          user={user}
          onCancel={() => setAdding(false)}
          onAdded={(u) => {
            setAdding(false);
            setNotice(`Added ${u.display_name} (${u.username}).`);
            load();
          }}
        />
      </Modal>
    </section>
  );
}

function AddUserForm({
  token,
  user,
  onCancel,
  onAdded,
}: Props & { onCancel: () => void; onAdded: (u: AdminUser) => void }) {
  const isSystemAdmin = user.roles.includes("system_admin");
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [form, setForm] = useState({
    lan_id: "",
    display_name: "",
    email: "",
    title: "",
    password: "",
    department_code: "",
    role: "viewer",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isSystemAdmin) listDepartments(token).then(setDepartments).catch(() => undefined);
  }, [isSystemAdmin, token]);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const created = await createUser(token, {
        lan_id: form.lan_id,
        display_name: form.display_name,
        email: form.email,
        title: form.title,
        password: form.password,
        ...(isSystemAdmin ? { department_code: form.department_code } : { role: form.role }),
      });
      onAdded(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add the user.");
    } finally {
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
            <span>LAN ID</span>
            <input value={form.lan_id} onChange={set("lan_id")} required autoFocus />
          </label>
          <label className="form-field">
            <span>Name</span>
            <input value={form.display_name} onChange={set("display_name")} required />
          </label>
          <label className="form-field">
            <span>Email</span>
            <input type="email" value={form.email} onChange={set("email")} required />
          </label>
          <label className="form-field">
            <span>Job title</span>
            <input value={form.title} onChange={set("title")} />
          </label>
          <label className="form-field">
            <span>Department</span>
            {isSystemAdmin ? (
              <select value={form.department_code} onChange={set("department_code")} required>
                <option value="" disabled>
                  Choose a department
                </option>
                {departments.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name}
                  </option>
                ))}
              </select>
            ) : (
              <input value={user.department?.name ?? ""} readOnly />
            )}
          </label>
          <label className="form-field">
            <span>Role</span>
            {isSystemAdmin ? (
              <input value="Department admin" readOnly />
            ) : (
              <select value={form.role} onChange={set("role")}>
                <option value="viewer">Viewer</option>
                <option value="maker">Maker</option>
                <option value="checker">Checker</option>
              </select>
            )}
          </label>
          <label className="form-field form-field--wide">
            <span>Initial password</span>
            <input
              type="password"
              value={form.password}
              onChange={set("password")}
              minLength={8}
              required
              autoComplete="new-password"
            />
            <small>At least 8 characters. Share it with the user securely.</small>
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Adding…" : "Add user"}
        </button>
      </div>
    </form>
  );
}
