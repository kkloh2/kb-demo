import { useCallback, useState, type ReactNode } from "react";
import { ApiError } from "../../api/http";
import type { RoleRow } from "../../api/admin";

/** Error state for a tab: a 401 ends the session (back to sign-in); anything else is shown. */
export function useErrors(onSessionEnded: (message: string) => void) {
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback(
    (err: unknown, fallback = "Something went wrong.") => {
      if (err instanceof ApiError && err.status === 401) onSessionEnded(err.message);
      else setError(err instanceof Error ? err.message : fallback);
    },
    [onSessionEnded],
  );
  return { error, setError, fail };
}

/** Role code -> display name, from the roles list (falls back to the code). */
export function roleNamer(roles: RoleRow[] | null) {
  const names = new Map((roles ?? []).map((r) => [r.code, r.name]));
  return (code: string) => names.get(code) ?? code;
}

export function Notice({ children }: { children: ReactNode }) {
  return children ? (
    <p className="notice" role="status">
      {children}
    </p>
  ) : null;
}

export function ErrorMessage({ children }: { children: ReactNode }) {
  return (
    <p className="admin-message admin-message--error" role="alert">
      {children}
    </p>
  );
}

/** A modal body asking to confirm a destructive action. */
export function ConfirmDelete({
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setError(null);
    setBusy(true);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete.");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="modal__body">
        {error && (
          <p className="alert" role="alert">
            {error}
          </p>
        )}
        <p className="modal__text">{message}</p>
      </div>
      <div className="modal__footer">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn-danger" onClick={confirm} disabled={busy}>
          {busy ? "Deleting…" : confirmLabel}
        </button>
      </div>
    </>
  );
}
