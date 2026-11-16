import { useCallback, useEffect, useState } from "react";
import { myAccess, type MyAccess } from "../api/access";
import type { User } from "../api/auth";
import { ApiError } from "../api/http";
import { ApprovalsIcon, AuditIcon, FolderIcon, WorkflowIcon } from "../components/Icons";
import { Sidebar, type NavItem } from "../components/Sidebar";
import { AdminPage } from "../pages/AdminPage";
import { AuditPage } from "../pages/audit/AuditPage";
import { ApprovalsPage } from "../pages/approvals/ApprovalsPage";
import { ApprovalWorkflowsPage } from "../pages/approvals/ApprovalWorkflowsPage";
import { DocRepoDetailPage } from "../pages/doc-repos/DocRepoDetailPage";
import { DocReposPage } from "../pages/doc-repos/DocReposPage";
import "../styles/shell.css";

const COLLAPSED_KEY = "dh.sidebarCollapsed";

/** The open repository, from a "#doc-repo/<id>" URL (so back/forward and bookmarks work). */
function docRepoFromHash(): string | null {
  const m = window.location.hash.match(/^#doc-repo\/([0-9a-f-]{36})$/i);
  return m ? m[1] : null;
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
  /** The session ended while in use (e.g. a root role changed): back to sign-in with this message. */
  onSessionEnded: (message: string) => void;
}

/**
 * The signed-in app: navigation on the left, the current page on the right. What the navigation
 * offers comes from GET /api/me/access, reloaded on every page change (roles take effect at once).
 */
export function AppShell({ token, user, onSignOut, onSessionEnded }: Props) {
  const [access, setAccess] = useState<MyAccess | null>(null);
  const [active, setActive] = useState("docRepos");
  const [docRepoId, setDocRepoId] = useState(docRepoFromHash);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const reloadAccess = useCallback(() => {
    myAccess(token)
      .then(setAccess)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      });
  }, [token, onSessionEnded]);
  useEffect(reloadAccess, [reloadAccess]);

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
    reloadAccess();
  }

  function navigate(key: string) {
    if (docRepoId !== null) closeDocRepo();
    setActive(key);
    reloadAccess();
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

  const docHub = !!access && ("DOC_HUB" in access.system_roles || access.nodes.some((n) => n.system === "DOC_HUB"));
  const admin = !!access?.platform_admin;
  const approvals = !!access?.can_decide;
  const items: NavItem[] = [
    ...(docHub ? [{ key: "docRepos", label: "Document repositories", icon: <FolderIcon /> }] : []),
    ...(approvals ? [{ key: "approvals", label: "Approvals", icon: <ApprovalsIcon /> }] : []),
    ...(admin ? [{ key: "approvalWorkflows", label: "Workflows", icon: <WorkflowIcon /> }] : []), // platform admins
    ...(admin ? [{ key: "audit", label: "Audit", icon: <AuditIcon /> }] : []), // platform admins
  ];

  let page;
  if (access === null) {
    page = null;
  } else if (active === "admin" && admin) {
    page = <AdminPage token={token} user={user} onSessionEnded={onSessionEnded} />;
  } else if (active === "approvals" && approvals) {
    page = <ApprovalsPage token={token} onSessionEnded={onSessionEnded} />;
  } else if (active === "audit" && admin) {
    page = <AuditPage token={token} onSessionEnded={onSessionEnded} />;
  } else if (active === "approvalWorkflows" && admin) {
    page = <ApprovalWorkflowsPage token={token} onSessionEnded={onSessionEnded} />;
  } else if (docHub && docRepoId !== null) {
    page = (
      <DocRepoDetailPage key={docRepoId} token={token} docRepoId={docRepoId} onBack={closeDocRepo}
        onSessionEnded={onSessionEnded} />
    );
  } else if (docHub) {
    page = <DocReposPage token={token} access={access} onSessionEnded={onSessionEnded} />;
  } else {
    page = (
      <div className="page">
        <h1 className="page__title">Welcome, {user.display_name}</h1>
        <p className="muted">You don't have access to any module yet. Ask a platform admin.</p>
      </div>
    );
  }

  const current =
    active === "admin" && admin ? "admin"
      : active === "approvals" && approvals ? "approvals"
        : active === "approvalWorkflows" && admin ? "approvalWorkflows"
          : active === "audit" && admin ? "audit"
          : "docRepos";
  return (
    <div className="shell">
      <Sidebar
        user={user}
        items={items}
        active={current}
        collapsed={collapsed}
        onToggle={toggle}
        onNavigate={navigate}
        onSignOut={onSignOut}
        showAdmin={admin}
      />
      <main className="shell__main">{page}</main>
    </div>
  );
}
