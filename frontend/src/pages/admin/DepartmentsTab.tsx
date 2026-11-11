import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  listUsers,
  updateDepartment,
  type AdminUser,
  type DepartmentRow,
} from "../../api/admin";
import { ApiError } from "../../api/http";
import { PlusIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";
import type { AdminTabProps } from "../AdminPage";
import { ConfirmDelete, ErrorMessage, Notice, useErrors } from "./common";

type Editing = { mode: "add" } | { mode: "edit"; department: DepartmentRow } | null;

export function DepartmentsTab({ token, onSessionEnded }: AdminTabProps) {
  const [departments, setDepartments] = useState<DepartmentRow[] | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [editing, setEditing] = useState<Editing>(null);
  const [deleting, setDeleting] = useState<DepartmentRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { error, fail } = useErrors(onSessionEnded);

  const load = useCallback(() => {
    Promise.all([listDepartments(token), listUsers(token)])
      .then(([d, u]) => {
        setDepartments(d);
        setUsers(u);
      })
      .catch(fail);
  }, [token, fail]);
  useEffect(load, [load]);

  // Per department: its admins and how many people hold any role there.
  const stats = useMemo(() => {
    const byCode = new Map<string, { admins: string[]; people: number }>();
    for (const u of users) {
      for (const [code, roles] of Object.entries(u.org_unit_roles)) {
        const s = byCode.get(code) ?? { admins: [], people: 0 };
        s.people += 1;
        if (roles.includes("DEPARTMENT_ADMIN")) s.admins.push(u.display_name);
        byCode.set(code, s);
      }
    }
    return byCode;
  }, [users]);

  const { rows, ...pager } = usePagination(departments ?? []);

  return (
    <section className="panel" aria-labelledby="departments-title">
      <div className="panel__head">
        <div>
          <h2 id="departments-title" className="panel__title">
            Manage departments
          </h2>
          <p className="panel__desc">
            Departments are the org units roles are held in. Give people roles in a department from the Users tab.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setEditing({ mode: "add" })}>
          <PlusIcon />
          Add department
        </button>
      </div>

      <Notice>{notice}</Notice>

      {error ? (
        <ErrorMessage>{error}</ErrorMessage>
      ) : departments === null ? (
        <p className="admin-message">Loading departments…</p>
      ) : (
        <>
          <table className="data-table">
            <colgroup>
              <col style={{ width: "14%" }} />
              <col style={{ width: "28%" }} />
              <col style={{ width: "16%" }} />
              <col />
              <col style={{ width: "128px" }} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Code</th>
                <th scope="col">Name</th>
                <th scope="col">People with roles</th>
                <th scope="col">Department admins</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const s = stats.get(d.code);
                return (
                  <tr key={d.code}>
                    <td>
                      <code className="code">{d.code}</code>
                    </td>
                    <td className="truncate">{d.name}</td>
                    <td>{s?.people ?? 0}</td>
                    <td className="truncate">
                      {s?.admins.length ? s.admins.join(", ") : <span className="muted">None yet</span>}
                    </td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="btn-link"
                        onClick={() => setEditing({ mode: "edit", department: d })}
                      >
                        Edit
                      </button>
                      <button type="button" className="btn-link btn-link--danger" onClick={() => setDeleting(d)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal
        open={editing !== null}
        title={editing?.mode === "edit" ? `Edit ${editing.department.name}` : "Add department"}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <DepartmentForm
            token={token}
            existing={editing.mode === "edit" ? editing.department : null}
            onCancel={() => setEditing(null)}
            onSaved={(d, created) => {
              setEditing(null);
              setNotice(
                created
                  ? `Added ${d.name} (${d.code}). Give people roles in it from the Users tab.`
                  : `Saved ${d.name} (${d.code}).`,
              );
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>

      <Modal open={deleting !== null} title="Delete department" onClose={() => setDeleting(null)}>
        {deleting && (
          <ConfirmDelete
            message={
              <>
                Delete <strong>{deleting.name}</strong> ({deleting.code})?{" "}
                {stats.get(deleting.code)?.people
                  ? `${stats.get(deleting.code)!.people} people lose the roles they hold in it, and are signed out.`
                  : "Nobody holds a role in it."}
              </>
            }
            confirmLabel="Delete department"
            onCancel={() => setDeleting(null)}
            onConfirm={async () => {
              await deleteDepartment(token, deleting.code);
              setDeleting(null);
              setNotice(`Deleted ${deleting.name} (${deleting.code}).`);
              load();
            }}
          />
        )}
      </Modal>
    </section>
  );
}

function DepartmentForm({
  token,
  existing,
  onCancel,
  onSaved,
  onSessionEnded,
}: {
  token: string;
  existing: DepartmentRow | null;
  onCancel: () => void;
  onSaved: (d: DepartmentRow, created: boolean) => void;
  onSessionEnded: (message: string) => void;
}) {
  const [code, setCode] = useState(existing?.code ?? "");
  const [name, setName] = useState(existing?.name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const renaming = existing !== null && code.trim().toUpperCase() !== existing.code;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const body = { code, name };
      const saved = existing ? await updateDepartment(token, existing.code, body) : await createDepartment(token, body);
      onSaved(saved, existing === null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : "Couldn't save the department.");
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
            <span>Code</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="e.g. TREASURY"
              maxLength={32}
              required
              autoFocus
            />
            <small>Short and stable: it's how tokens and URLs name the department.</small>
          </label>
          <label className="form-field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Treasury" required />
          </label>
          {renaming && (
            <p className="form-field form-field--wide">
              <small className="form-hint--warn">
                Changing the code keeps everyone's roles, but signs out everyone who holds one here.
              </small>
            </p>
          )}
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Saving…" : existing ? "Save" : "Add department"}
        </button>
      </div>
    </form>
  );
}
