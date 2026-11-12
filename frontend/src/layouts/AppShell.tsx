import { useEffect, useState } from "react";
import type { User } from "../api/auth";
import { FolderIcon } from "../components/Icons";
import { Sidebar, type NavItem } from "../components/Sidebar";
import { isSystemAdmin } from "../lib/token";
import { AdminPage } from "../pages/AdminPage";
import { DocRepoDetailPage } from "../pages/doc-repos/DocRepoDetailPage";
import { DocReposPage } from "../pages/doc-repos/DocReposPage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** Navigation entries. Doc-repos (document & metadata management) is the landing page. */
const NAV_ITEMS: NavItem[] = [{ key: "docRepos", label: "Document repositories", icon: <FolderIcon /> }];

/** The open doc-repo, from a "#doc-repo/<id>" URL (so back/forward and bookmarks work). */
function docRepoFromHash(): number | null {
  const m = window.location.hash.match(/^#doc-repo\/(\d+)$/);
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
  const [active, setActive] = useState("docRepos");
  const [docRepoId, setDocRepoId] = useState(docRepoFromHash);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const systemAdmin = isSystemAdmin(token);

  useEffect(() => {
    const onHash = () => {
      const id = docRepoFromHash();
      setDocRepoId(id);
      if (id !== null) setActive("docRepos");
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  function closeDocRepo() {
    history.pushState(null, "", window.location.pathname + window.location.search);
    setDocRepoId(null);
  }

  function navigate(key: string) {
    if (docRepoId !== null) closeDocRepo();
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
  } else if (docRepoId !== null) {
    page = (
      <DocRepoDetailPage key={docRepoId} token={token} docRepoId={docRepoId} onBack={closeDocRepo}
        onSessionEnded={onSessionEnded} />
    );
  } else {
    page = <DocReposPage token={token} onSessionEnded={onSessionEnded} />;
  }

  return (
    <div className="shell">
      <Sidebar
        user={user}
        items={NAV_ITEMS}
        active={active === "admin" ? "admin" : "docRepos"}
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
