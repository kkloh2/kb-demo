import { useState } from "react";
import type { User } from "../api/auth";
import { HomeIcon } from "../components/Icons";
import { Sidebar, type NavItem } from "../components/Sidebar";
import { isSystemAdmin } from "../lib/token";
import { AdminPage } from "../pages/AdminPage";
import { HomePage } from "../pages/HomePage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** Navigation entries. Each feature (e.g. knowledge bases) adds its page here. */
const NAV_ITEMS: NavItem[] = [{ key: "home", label: "Home", icon: <HomeIcon /> }];

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

interface Props {
  token: string;
  user: User;
  onSignOut: () => void;
  /** The session ended while in use (e.g. the user's roles changed): back to sign-in with this message. */
  onSessionEnded: (message: string) => void;
}

/** The signed-in app: navigation panel on the left, the current page on the right. */
export function AppShell({ token, user, onSignOut, onSessionEnded }: Props) {
  const [active, setActive] = useState("home");
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const systemAdmin = isSystemAdmin(token);

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
        showAdmin={systemAdmin}
      />
      <main className="shell__main">
        {active === "admin" && systemAdmin ? (
          <AdminPage token={token} user={user} onSessionEnded={onSessionEnded} />
        ) : (
          <HomePage user={user} />
        )}
      </main>
    </div>
  );
}
