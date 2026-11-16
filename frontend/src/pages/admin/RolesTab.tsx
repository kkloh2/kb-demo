import { useEffect, useState } from "react";
import { listRoles, type RoleInfo } from "../../api/access";
import type { AdminTabProps } from "../AdminPage";
import { ErrorMessage, useErrors } from "./common";

/** The roles and the permissions each carries (defined in code). */
export function RolesTab({ token, onSessionEnded }: AdminTabProps) {
  const [roles, setRoles] = useState<RoleInfo[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const { error, setError, fail } = useErrors(onSessionEnded);

  useEffect(() => {
    listRoles(token)
      .then((r) => {
        setRoles(r.roles);
        setNames(Object.fromEntries(r.permissions.map((p) => [p.code, p.name])));
      })
      .catch(fail);
  }, [token, fail]);

  return (
    <section className="panel" aria-labelledby="roles-title">
      <div className="panel__head">
        <div>
          <h2 id="roles-title" className="panel__title">
            Roles
          </h2>
          <p className="panel__desc">
            A role applies only where it's given: at a system's root or in one repository, never below it. What it lets
            someone do there is its permissions. Roles are defined by the platform and can't be edited here.
          </p>
        </div>
      </div>

      {error ? (
        <ErrorMessage onClose={() => setError(null)}>{error}</ErrorMessage>
      ) : roles === null ? (
        <p className="admin-message">Loading roles…</p>
      ) : (
        <table className="data-table data-table--wrap">
          <colgroup>
            <col style={{ width: "20%" }} />
            <col style={{ width: "34%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Description</th>
              <th scope="col">Permissions</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.code}>
                <td>
                  <div className="person">
                    <span className="person__name">{r.name}</span>
                    <span className="person__id">{r.code}</span>
                  </div>
                </td>
                <td className="muted">{r.description}</td>
                <td>
                  <ul className="plain-list plain-list--tight">
                    {r.permissions.map((p) => (
                      <li key={p} title={p}>
                        {names[p] ?? p}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
