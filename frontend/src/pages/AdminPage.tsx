import { useState } from "react";
import type { User } from "../api/auth";
import "../styles/knowledge-bases.css"; // shared page, button and pager styles
import "../styles/admin.css";
import { DepartmentsTab } from "./admin/DepartmentsTab";
import { PermissionsTab } from "./admin/PermissionsTab";
import { RolesTab } from "./admin/RolesTab";
import { UsersTab } from "./admin/UsersTab";

type Tab = "users" | "departments" | "roles" | "permissions";

const TAB_LABELS: Record<Tab, string> = {
  users: "Users",
  departments: "Departments",
  roles: "Roles",
  permissions: "Permissions",
};

interface Props {
  token: string;
  user: User;
}

/** System admins see every tab; department admins see Users only. */
export function AdminPage({ token, user }: Props) {
  const isSystemAdmin = user.roles.includes("system_admin");
  const tabs: Tab[] = isSystemAdmin ? ["users", "departments", "roles", "permissions"] : ["users"];
  const [tab, setTab] = useState<Tab>("users");

  return (
    <div className="page page--admin">
      <h1 className="page__title">Administration</h1>

      <div className="tabs" role="tablist" aria-label="Administration">
        {tabs.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            id={`tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            className="tab"
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "users" && <UsersTab token={token} user={user} />}
        {tab === "departments" && isSystemAdmin && <DepartmentsTab token={token} />}
        {tab === "roles" && isSystemAdmin && <RolesTab token={token} />}
        {tab === "permissions" && isSystemAdmin && <PermissionsTab token={token} />}
      </div>
    </div>
  );
}
