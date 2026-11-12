import { useEffect, useState } from "react";
import type { User } from "../api/auth";
import { FolderIcon } from "../components/Icons";
import { Sidebar, type NavItem } from "../components/Sidebar";
import { isSystemAdmin } from "../lib/token";
import { AdminPage } from "../pages/AdminPage";
import { ProjectDetailPage } from "../pages/projects/ProjectDetailPage";
import { ProjectsPage } from "../pages/projects/ProjectsPage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** Navigation entries. Projects (document & metadata management) is the landing page. */
const NAV_ITEMS: NavItem[] = [{ key: "projects", label: "Projects", icon: <FolderIcon /> }];

/** The open project, from a "#project/<id>" URL (so back/forward and bookmarks work). */
function projectFromHash(): number | null {
  const m = window.location.hash.match(/^#project\/(\d+)$/);
  return m ? Number(m[1]) : null;
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
  /** The session ended while in use (e.g. the user's roles changed): back to sign-in with this message. */
  onSessionEnded: (message: string) => void;
}

/** The signed-in app: navigation panel on the left, the current page on the right. */
export function AppShell({ token, user, onSignOut, onSessionEnded }: Props) {
  const [active, setActive] = useState("projects");
  const [projectId, setProjectId] = useState(projectFromHash);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const systemAdmin = isSystemAdmin(token);

  useEffect(() => {
    const onHash = () => {
      const id = projectFromHash();
      setProjectId(id);
      if (id !== null) setActive("projects");
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function closeProject() {
    history.pushState(null, "", window.location.pathname + window.location.search);
    setProjectId(null);
  }

  function navigate(key: string) {
    if (projectId !== null) closeProject();
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

  let page;
  if (active === "admin" && systemAdmin) {
    page = <AdminPage token={token} user={user} onSessionEnded={onSessionEnded} />;
  } else if (projectId !== null) {
    page = (
      <ProjectDetailPage key={projectId} token={token} projectId={projectId} onBack={closeProject}
        onSessionEnded={onSessionEnded} />
    );
  } else {
    page = <ProjectsPage token={token} onSessionEnded={onSessionEnded} />;
  }

  return (
    <div className="shell">
      <Sidebar
        user={user}
        items={NAV_ITEMS}
        active={active === "admin" ? "admin" : "projects"}
        collapsed={collapsed}
        onToggle={toggle}
        onNavigate={navigate}
        onSignOut={onSignOut}
        showAdmin={systemAdmin}
      />
      <main className="shell__main">{page}</main>
    </div>
  );
}
