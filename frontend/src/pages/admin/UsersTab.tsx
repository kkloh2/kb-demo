import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  deleteUser,
  listDepartments,
  listRoles,
  listUsers,
  upsertUser,
  type AdminUser,
  type DepartmentRow,
  type OrgUnitRoles,
  type RoleRow,
} from "../../api/admin";
import { ApiError } from "../../api/http";
import { PlusIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";
import type { AdminTabProps } from "../AdminPage";
import { ConfirmDelete, ErrorMessage, Notice, roleNamer, useErrors } from "./common";

type Editing = { mode: "add" } | { mode: "edit"; user: AdminUser } | null;

export function UsersTab({ token, user: me, onSessionEnded }: AdminTabProps) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [departments, setDepartments] = useState<DepartmentRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[] | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    Promise.all([listUsers(token), listDepartments(token), listRoles(token)])
      .then(([u, d, r]) => {
        setUsers(u);
        setDepartments(d);
        setRoles(r);
      })
      .catch(fail);
  }, [token, fail]);
  useEffect(load, [load]);

  const roleName = roleNamer(roles);
  const { rows, ...pager } = usePagination(users ?? []);

  return (
    <section className="panel" aria-labelledby="users-title">
      <div className="panel__head">
        <div>
          <h2 id="users-title" className="panel__title">
            Manage users
          </h2>
          <p className="panel__desc">
            Everyone who has signed in, or been added here, with their system roles and their roles in each
            department. Changing someone's roles signs them out, so their next sign-in picks up the change.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setEditing({ mode: "add" })}>
          <PlusIcon />
          Add user
        </button>
      </div>

      <Notice>{notice}</Notice>

      {error ? (
        <ErrorMessage>{error}</ErrorMessage>
      ) : users === null ? (
        <p className="admin-message">Loading users…</p>
      ) : (
        <>
          <table className="data-table">
            <colgroup>
              <col style={{ width: "20%" }} />
              <col style={{ width: "20%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "14%" }} />
              <col />
              <col style={{ width: "128px" }} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Department</th>
                <th scope="col">System roles</th>
                <th scope="col">Department roles</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.lan_id}>
                  <td>
                    <div className="person">
                      <span className="person__name">{u.display_name}</span>
                      <span className="person__id">
                        {u.lan_id}
                        {u.title ? ` · ${u.title}` : ""}
                      </span>
                    </div>
                  </td>
                  <td className="truncate">{u.email}</td>
                  <td className="truncate">{u.department || <span className="muted">—</span>}</td>
                  <td>
                    {u.system_roles.length ? (
                      u.system_roles.map((r) => (
                        <span key={r} className="badge">
                          {roleName(r)}
                        </span>
                      ))
                    ) : (
                      <span className="muted">None</span>
                    )}
                  </td>
                  <td>
                    {Object.keys(u.org_unit_roles).length ? (
                      Object.entries(u.org_unit_roles).map(([code, rs]) => (
                        <span key={code} className="badge badge--neutral">
                          <strong>{code}</strong> {rs.map(roleName).join(", ")}
                        </span>
                      ))
                    ) : (
                      <span className="muted">None</span>
                    )}
                  </td>
                  <td className="row-actions">
                    <button type="button" className="btn-link" onClick={() => setEditing({ mode: "edit", user: u })}>
                      Edit
                    </button>
                    {u.lan_id !== me.username && (
                      <button type="button" className="btn-link btn-link--danger" onClick={() => setDeleting(u)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal
        open={editing !== null}
        title={editing?.mode === "edit" ? `Edit ${editing.user.display_name}` : "Add user"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <UserForm
            token={token}
            existing={editing.mode === "edit" ? editing.user : null}
            departments={departments}
            roles={roles ?? []}
            onCancel={() => setEditing(null)}
            onSaved={(u, created) => {
              setEditing(null);
              setNotice(`${created ? "Added" : "Saved"} ${u.display_name} (${u.lan_id}).`);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete user" onClose={() => setDeleting(null)}>
        {deleting && (
          <ConfirmDelete
            message={
              <>
                Delete <strong>{deleting.display_name}</strong> ({deleting.lan_id}) and all their roles? They're
                signed out now. If the directory still lets them in, they come back as a new user with Public only.
              </>
            }
            confirmLabel="Delete user"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              await deleteUser(token, deleting.lan_id);
              setDeleting(null);
              setNotice(`Deleted ${deleting.display_name} (${deleting.lan_id}).`);
              load();
            }}
          />
        )}
      </Modal>
    </section>
  );
}

// --------------------------------------------------------------------------- add / edit form

const EXCLUSIVE: Record<string, string> = { MAKER: "CHECKER", CHECKER: "MAKER" };

function UserForm({
  token,
  existing,
  departments,
  roles,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  existing: AdminUser | null;
  departments: DepartmentRow[];
  roles: RoleRow[];
  onCancel: () => void;
  onSaved: (u: AdminUser, created: boolean) => void;
  onSessionEnded: (message: string) => void;
}) {
  const systemRoles = roles.filter((r) => r.scope === "system");
  const orgRoles = roles.filter((r) => r.scope === "org_unit");
  const [form, setForm] = useState({
    lan_id: existing?.lan_id ?? "",
    display_name: existing?.display_name ?? "",
    email: existing?.email ?? "",
    title: existing?.title ?? "",
    department: existing?.department ?? "",
  });
  const [system, setSystem] = useState<Set<string>>(new Set(existing ? existing.system_roles : ["PUBLIC"]));
  const [org, setOrg] = useState<OrgUnitRoles>(existing?.org_unit_roles ?? {});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  function toggleSystem(code: string) {
    setSystem((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  function toggleOrg(dept: string, code: string) {
    setOrg((o) => {
      const held = new Set(o[dept] ?? []);
      if (held.has(code)) held.delete(code);
      else {
        held.add(code);
        if (EXCLUSIVE[code]) held.delete(EXCLUSIVE[code]); // one person can't be both maker and checker
      }
      const next = { ...o, [dept]: [...held].sort() };
      if (!held.size) delete next[dept];
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const saved = await upsertUser(token, form.lan_id.trim(), {
        display_name: form.display_name,
        email: form.email,
        department: form.department,
        title: form.title,
        system_roles: [...system].sort(),
        org_unit_roles: org,
      });
      onSaved(saved, existing === null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save the user.");
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
            <input
              value={form.lan_id}
              onChange={set("lan_id")}
              readOnly={existing !== null}
              required
              autoFocus={existing === null}
            />
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
          <label className="form-field form-field--wide">
            <span>Department (from the directory)</span>
            <input value={form.department} onChange={set("department")} placeholder="e.g. Risk Management" />
            <small>Name, email, department and job title are refreshed from the directory at each sign-in.</small>
          </label>

          <fieldset className="form-field form-field--wide role-group">
            <legend>System roles</legend>
            <div className="role-checks">
              {systemRoles.map((r) => (
                <label key={r.code} className="check" title={r.description}>
                  <input type="checkbox" checked={system.has(r.code)} onChange={() => toggleSystem(r.code)} />
                  {r.name}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="form-field form-field--wide role-group">
            <legend>Department roles</legend>
            {departments.length === 0 ? (
              <small>No departments yet. Add one in the Departments tab.</small>
            ) : (
              <table className="role-matrix">
                <thead>
                  <tr>
                    <th scope="col">Department</th>
                    {orgRoles.map((r) => (
                      <th key={r.code} scope="col" title={r.description}>
                        {r.name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {departments.map((d) => (
                    <tr key={d.code}>
                      <th scope="row">
                        <span className="code">{d.code}</span> <span className="muted">{d.name}</span>
                      </th>
                      {orgRoles.map((r) => (
                        <td key={r.code}>
                          <input
                            type="checkbox"
                            aria-label={`${r.name} in ${d.name}`}
                            checked={(org[d.code] ?? []).includes(r.code)}
                            onChange={() => toggleOrg(d.code, r.code)}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <small>Maker and checker can't both be held in one department.</small>
          </fieldset>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : existing ? "Save" : "Add user"}
        </button>
      </div>
    </form>
  );
}
