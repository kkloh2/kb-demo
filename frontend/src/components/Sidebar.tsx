import type { ReactNode } from "react";
import type { User } from "../api/auth";
import { PanelIcon } from "./Icons";
import { UserMenu } from "./UserMenu";

/** A page reachable from the navigation panel. None yet: features add their own entries. */
export interface NavItem {
  key: string;
  label: string;
  icon: ReactNode;
}

interface Props {
  user: User;
  items: NavItem[];
  active: string | null;
  collapsed: boolean;
  onToggle: () => void;
  onNavigate: (key: string) => void;
  onSignOut: () => void;
}

export function Sidebar({ user, items, active, collapsed, onToggle, onNavigate, onSignOut }: Props) {
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
            </li>
          ))}
        </ul>
      </nav>

      <div className="sidebar__user">
        <UserMenu user={user} collapsed={collapsed} onSignOut={onSignOut} />
      </div>
    </aside>
  );
}
