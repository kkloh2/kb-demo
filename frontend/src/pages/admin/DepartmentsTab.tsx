import { useCallback, useEffect, useState, type FormEvent } from "react";
import { createDepartment, listDepartments, type DepartmentRow } from "../../api/admin";
import { PlusIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";

export function DepartmentsTab({ token }: { token: string }) {
  const [rows, setRows] = useState<DepartmentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    listDepartments(token).then(setRows).catch((e: Error) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);

  const { rows: page, ...pager } = usePagination(rows ?? []);

  return (
    <section className="panel" aria-labelledby="departments-title">
      <div className="panel__head">
        <div>
          <h2 id="departments-title" className="panel__title">
            Manage departments
          </h2>
          <p className="panel__desc">
            Every user and knowledge base belongs to one department.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
          <PlusIcon />
          Add department
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
      ) : rows === null ? (
        <p className="kb-message">Loading departments…</p>
      ) : (
        <>
          <table className="data-table">
            <colgroup>
              <col style={{ width: "14%" }} />
              <col style={{ width: "28%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "16%" }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Code</th>
                <th scope="col">Name</th>
                <th scope="col">Members</th>
                <th scope="col">Knowledge bases</th>
                <th scope="col">Department admins</th>
              </tr>
            </thead>
            <tbody>
              {page.map((d) => (
                <tr key={d.code}>
                  <td>
                    <code className="code">{d.code}</code>
                  </td>
                  <td className="truncate">{d.name}</td>
                  <td>{d.members}</td>
                  <td>{d.knowledge_bases}</td>
                  <td className="truncate">
                    {d.admins.length ? d.admins.join(", ") : <span className="muted">None yet</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}

      <Modal open={adding} title="Add department" onClose={() => setAdding(false)}>
        <AddDepartmentForm
          token={token}
          onCancel={() => setAdding(false)}
          onAdded={(d) => {
            setAdding(false);
            setNotice(`Added ${d.name} (${d.code}). Add a department admin from the Users tab.`);
            load();
          }}
        />
      </Modal>
    </section>
  );
}

function AddDepartmentForm({
  token,
  onCancel,
  onAdded,
}: {
  token: string;
  onCancel: () => void;
  onAdded: (d: DepartmentRow) => void;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      onAdded(await createDepartment(token, { code, name }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add the department.");
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
            <span>Code</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="e.g. TREASURY"
              maxLength={16}
              required
              autoFocus
            />
            <small>2–16 letters, numbers or underscores.</small>
          </label>
          <label className="form-field">
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Treasury" required />
          </label>
        </div>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn-primary" disabled={saving}>
          {saving ? "Adding…" : "Add department"}
        </button>
      </div>
    </form>
  );
}
