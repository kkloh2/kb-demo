import { useState } from "react";
import type { User } from "../api/auth";
import "../styles/admin.css";
import { RolesTab } from "./admin/RolesTab";
import { SourcesTab } from "./admin/SourcesTab";
import { TeamsTab } from "./admin/TeamsTab";
import { UsersTab } from "./admin/UsersTab";

type Tab = "users" | "teams" | "sources" | "roles";

const TABS: { key: Tab; label: string }[] = [
  { key: "users", label: "Users" },
  { key: "teams", label: "Teams" },
  { key: "sources", label: "Source systems" },
  { key: "roles", label: "Roles" },
];

export interface AdminTabProps {
  token: string;
  user: User;
  /** The server ended the session (401), e.g. after the admin changed their own root roles. */
  onSessionEnded: (message: string) => void;
}

/** Administration (platform admins): users, source systems and the role catalogue. */
export function AdminPage(props: AdminTabProps) {
  const [tab, setTab] = useState<Tab>("users");

  return (
    <div className="page page--admin">
      <h1 className="page__title">Administration</h1>

      <div className="tabs" role="tablist" aria-label="Administration">
        {TABS.map((t) => (
          <button key={t.key} type="button" role="tab" id={`tab-${t.key}`} aria-selected={tab === t.key}
            aria-controls={`panel-${t.key}`} className="tab" onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "users" && <UsersTab {...props} />}
        {tab === "teams" && <TeamsTab {...props} />}
        {tab === "sources" && <SourcesTab {...props} />}
        {tab === "roles" && <RolesTab {...props} />}
      </div>
    </div>
  );
}
