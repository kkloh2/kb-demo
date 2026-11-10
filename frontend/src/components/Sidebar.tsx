import type { ReactNode } from "react";
import type { User } from "../api/auth";
import { KnowledgeBaseIcon, PanelIcon, SettingsIcon } from "./Icons";
import { UserMenu } from "./UserMenu";

export type NavKey = "knowledge-bases" | "admin";

const NAV_ITEMS: { key: Exclude<NavKey, "admin">; label: string; icon: ReactNode }[] = [
  { key: "knowledge-bases", label: "Knowledge Bases", icon: <KnowledgeBaseIcon /> },
];

/** System admins and department admins get the Administration page. */
export function canAdminister(user: User): boolean {
  return user.roles.includes("system_admin") || user.roles.includes("department_admin");
}

interface Props {
  user: User;
  active: NavKey;
  collapsed: boolean;
  onToggle: () => void;
  onNavigate: (key: NavKey) => void;
  onSignOut: () => void;
}

export function Sidebar({
  user,
  active,
  collapsed,
  onToggle,
  onNavigate,
  onSignOut,
}: Props) {
  return (
    <aside className={`sidebar${collapsed ? " sidebar--collapsed" : ""}`}>
      <div className="sidebar__brand">
        {collapsed ? (
          // Collapsed: the logo doubles as the expand button (shows the
          // expand icon on hover/focus).
          <button
            type="button"
            className="brand-toggle"
            onClick={onToggle}
            aria-label="Expand navigation"
            title="Expand navigation"
          >
            <img src="/ocbc-symbol.svg" alt="" />
            <PanelIcon expand />
          </button>
        ) : (
          <>
            <img src="/ocbc-symbol.svg" alt="" />
            <span className="sidebar__product">Data Hub</span>
            <button
              type="button"
              className="icon-btn sidebar__collapse"
              onClick={onToggle}
              aria-label="Collapse navigation"
              title="Collapse navigation"
            >
              <PanelIcon />
            </button>
          </>
        )}
      </div>

      <nav className="sidebar__nav" aria-label="Main">
        <ul className="nav-list">
          {NAV_ITEMS.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                className="nav-item"
                aria-current={item.key === active ? "page" : undefined}
                onClick={() => onNavigate(item.key)}
                title={collapsed ? item.label : undefined}
              >
                {item.icon}
                <span className="nav-item__label">{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar__user">
        {canAdminister(user) && (
          <button
            type="button"
            className="nav-item sidebar__admin"
            aria-current={active === "admin" ? "page" : undefined}
            onClick={() => onNavigate("admin")}
            title={collapsed ? "Administration" : undefined}
          >
            <SettingsIcon />
            <span className="nav-item__label">Administration</span>
          </button>
        )}
        <UserMenu user={user} collapsed={collapsed} onSignOut={onSignOut} />
      </div>
    </aside>
  );
}
