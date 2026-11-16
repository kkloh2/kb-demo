import type { ReactNode } from "react";
import type { User } from "../api/auth";
import { PanelIcon, SettingsIcon } from "./Icons";
import { UserMenu } from "./UserMenu";

/** A page reachable from the navigation panel. Features add their own entries. */
export interface NavItem {
  key: string;
  label: string;
  icon: ReactNode;
  /** Pages under this one, shown indented beneath it (e.g. Approvals > Workflows). */
  children?: NavItem[];
}

interface Props {
  user: User;
  items: NavItem[];
  active: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onNavigate: (key: string) => void;
  onSignOut: () => void;
  /** Show the Administration entry (system admins). Navigates with the key "admin". */
  showAdmin?: boolean;
}

export function Sidebar({ user, items, active, collapsed, onToggle, onNavigate, onSignOut, showAdmin }: Props) {
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
          {items.map((item) => (
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
              {item.children && item.children.length > 0 && (
                <ul className="nav-list nav-list--sub">
                  {item.children.map((child) => (
                    <li key={child.key}>
                      <button
                        type="button"
                        className="nav-item nav-item--sub"
                        aria-current={child.key === active ? "page" : undefined}
                        onClick={() => onNavigate(child.key)}
                        title={collapsed ? child.label : undefined}
                      >
                        {child.icon}
                        <span className="nav-item__label">{child.label}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar__user">
        {showAdmin && (
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
