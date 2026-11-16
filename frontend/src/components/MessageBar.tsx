import { useState, type ReactNode } from "react";
import { CloseIcon } from "./Icons";

interface Props {
  /** The bar's look: "notice" (success), "notice notice--error", "notice notice--info", "alert", ... */
  className?: string;
  role?: "status" | "alert";
  /** Called when the X is clicked (e.g. clear the message). Without it, the bar just hides itself;
   * give it a `key` (e.g. the message text) so a new message shows again. */
  onClose?: () => void;
  children: ReactNode;
}

/** A message bar with an X to close it. */
export function MessageBar({ className = "notice", role = "status", onClose, children }: Props) {
  const [hidden, setHidden] = useState(false);
  if (hidden || children === null || children === undefined || children === false || children === "") return null;
  return (
    <div className={`${className} message-bar`} role={role}>
      <div className="message-bar__text">{children}</div>
      <button type="button" className="message-bar__close" aria-label="Close message" title="Close"
        onClick={() => (onClose ? onClose() : setHidden(true))}>
        <CloseIcon />
      </button>
    </div>
  );
}
