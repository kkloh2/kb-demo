import { useEffect, useState } from "react";
import { listRoles, type RoleRow } from "../../api/admin";

export function RolesTab({ token }: { token: string }) {
  const [rows, setRows] = useState<RoleRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRoles(token).then(setRows).catch((e: Error) => setError(e.message));
  }, [token]);

  return (
    <section className="panel" aria-labelledby="roles-title">
      <div className="panel__head">
        <div>
          <h2 id="roles-title" className="panel__title">
            Roles
          </h2>
          <p className="panel__desc">
            What each role can do. Roles are defined by the platform and can't be edited here.
          </p>
        </div>
      </div>

      {error ? (
        <p className="kb-message kb-message--error" role="alert">
          {error}
        </p>
      ) : rows === null ? (
        <p className="kb-message">Loading roles…</p>
      ) : (
        <table className="data-table data-table--wrap">
          <colgroup>
            <col style={{ width: "18%" }} />
            <col style={{ width: "15%" }} />
            <col style={{ width: "32%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Scope</th>
              <th scope="col">Description</th>
              <th scope="col">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code}>
                <td>
                  <div className="person">
                    <span className="person__name">{r.name}</span>
                    <span className="person__id">{r.code}</span>
                  </div>
                </td>
                <td>{r.scope === "global" ? "All departments" : "Own department"}</td>
                <td className="muted">{r.description}</td>
                <td>
                  {r.permissions.map((p) => (
                    <code key={p} className="code code--chip">
                      {p}
                    </code>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
