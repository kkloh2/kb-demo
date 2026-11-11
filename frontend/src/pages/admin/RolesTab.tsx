import { useEffect, useState } from "react";
import { listRoles, type RoleRow } from "../../api/admin";
import type { AdminTabProps } from "../AdminPage";
import { ErrorMessage, useErrors } from "./common";

export function RolesTab({ token, onSessionEnded }: AdminTabProps) {
  const [rows, setRows] = useState<RoleRow[] | null>(null);
  const { error, fail } = useErrors(onSessionEnded);

  useEffect(() => {
    listRoles(token).then(setRows).catch(fail);
  }, [token, fail]);

  return (
    <section className="panel" aria-labelledby="roles-title">
      <div className="panel__head">
        <div>
          <h2 id="roles-title" className="panel__title">
            Roles
          </h2>
          <p className="panel__desc">
            What each role is for. Roles are defined by the platform and can't be edited here; give them to people
            from the Users tab.
          </p>
        </div>
      </div>

      {error ? (
        <ErrorMessage>{error}</ErrorMessage>
      ) : rows === null ? (
        <p className="admin-message">Loading roles…</p>
      ) : (
        <table className="data-table data-table--wrap">
          <colgroup>
            <col style={{ width: "24%" }} />
            <col style={{ width: "18%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Held</th>
              <th scope="col">Description</th>
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
                <td>{r.scope === "system" ? "System-wide" : "Per department"}</td>
                <td className="muted">{r.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
