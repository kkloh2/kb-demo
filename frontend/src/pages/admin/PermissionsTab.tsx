import { useEffect, useState } from "react";
import { listPermissions, ROLE_NAMES, type PermissionRow } from "../../api/admin";

export function PermissionsTab({ token }: { token: string }) {
  const [rows, setRows] = useState<PermissionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPermissions(token).then(setRows).catch((e: Error) => setError(e.message));
  }, [token]);

  return (
    <section className="panel" aria-labelledby="permissions-title">
      <div className="panel__head">
        <div>
          <h2 id="permissions-title" className="panel__title">
            Permissions
          </h2>
          <p className="panel__desc">
            Every permission a sign-in token can carry, and the roles that grant it.
          </p>
        </div>
      </div>

      {error ? (
        <p className="kb-message kb-message--error" role="alert">
          {error}
        </p>
      ) : rows === null ? (
        <p className="kb-message">Loading permissions…</p>
      ) : (
        <table className="data-table data-table--wrap">
          <colgroup>
            <col style={{ width: "26%" }} />
            <col style={{ width: "44%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Permission</th>
              <th scope="col">Description</th>
              <th scope="col">Granted to</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.code}>
                <td>
                  <code className="code">{p.code}</code>
                </td>
                <td className="muted">{p.description}</td>
                <td>
                  {p.roles.map((r) => (
                    <span key={r} className="badge">
                      {ROLE_NAMES[r] ?? r}
                    </span>
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
