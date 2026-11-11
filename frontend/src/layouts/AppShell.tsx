import { useState } from "react";
import type { User } from "../api/auth";
import { Sidebar, type NavItem } from "../components/Sidebar";
import { HomePage } from "../pages/HomePage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** Navigation entries. Empty for now: each feature (e.g. knowledge bases) adds its page here. */
const NAV_ITEMS: NavItem[] = [];

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

interface Props {
  user: User;
  onSignOut: () => void;
}

/** The signed-in app: navigation panel on the left, the current page on the right. */
export function AppShell({ user, onSignOut }: Props) {
  const [active, setActive] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  function toggle() {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, c ? "0" : "1");
      } catch {
        /* preference just won't be remembered */
      }
      return !c;
    });
  }

  return (
    <div className="shell">
      <Sidebar
        user={user}
        items={NAV_ITEMS}
        active={active}
        collapsed={collapsed}
        onToggle={toggle}
        onNavigate={setActive}
        onSignOut={onSignOut}
      />
      <main className="shell__main">
        <HomePage user={user} />
      </main>
    </div>
  );
}
