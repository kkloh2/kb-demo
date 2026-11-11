import { useEffect, useRef, useState } from "react";
import type { User } from "../api/auth";
import { SignOutIcon } from "./Icons";

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

interface Props {
  user: User;
  collapsed: boolean;
  onSignOut: () => void;
}

/**
 * Account control at the bottom of the sidebar: avatar, name and job title.
 * Clicking it opens a popover with the user's name, email and Sign out.
 */
export function UserMenu({ user, collapsed, onSignOut }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="user-menu" ref={rootRef}>
      <button
        type="button"
        className="user-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={collapsed ? `Account: ${user.display_name}` : undefined}
        title={collapsed ? user.display_name : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="avatar" aria-hidden>
          {initials(user.display_name)}
        </span>
        <span className="user__info">
          <span className="user__name">{user.display_name}</span>
          <span className="user__meta">{user.title}</span>
        </span>
      </button>

      {open && (
        <div className="popover" role="menu" aria-label="Account">
          <div className="popover__header">
            <p className="popover__name">{user.display_name}</p>
            <p className="popover__email">{user.email}</p>
          </div>
          <div className="popover__section">
            <button
              type="button"
              role="menuitem"
              className="popover__item"
              onClick={onSignOut}
            >
              <SignOutIcon />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
