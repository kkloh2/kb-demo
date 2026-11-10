import { useEffect, useState } from "react";
import type { User } from "../api/auth";
import { Sidebar, canAdminister, type NavKey } from "../components/Sidebar";
import { AdminPage } from "../pages/AdminPage";
import { KnowledgeBaseDetailPage } from "../pages/KnowledgeBaseDetailPage";
import { KnowledgeBasesPage } from "../pages/KnowledgeBasesPage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** The open knowledge base, from a "#kb/<id>" URL (so back/forward and bookmarks work). */
function kbFromHash(): string | null {
  const m = window.location.hash.match(/^#kb\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

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
}

export function AppShell({ token, user, onSignOut }: Props) {
  const [active, setActive] = useState<NavKey>("knowledge-bases");
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [kbId, setKbId] = useState(kbFromHash);

  useEffect(() => {
    const onHash = () => setKbId(kbFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function closeKb() {
    history.pushState(null, "", window.location.pathname + window.location.search);
    setKbId(null);
  }

  function navigate(key: NavKey) {
    if (kbId) closeKb();
    setActive(key);
  }

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
        active={active}
        collapsed={collapsed}
        onToggle={toggle}
        onNavigate={navigate}
        onSignOut={onSignOut}
      />
      <main className="shell__main">
        {active === "knowledge-bases" &&
          (kbId ? (
            <KnowledgeBaseDetailPage token={token} user={user} kbId={kbId} onBack={closeKb} />
          ) : (
            <KnowledgeBasesPage token={token} user={user} />
          ))}
        {active === "admin" && canAdminister(user) && <AdminPage token={token} user={user} />}
      </main>
    </div>
  );
}
