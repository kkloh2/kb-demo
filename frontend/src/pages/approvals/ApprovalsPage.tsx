import { useCallback, useEffect, useMemo, useState } from "react";
import { listApprovals, type ApprovalListItem } from "../../api/approvals";
import { ApiError } from "../../api/http";
import { EyeIcon, FileIcon, SearchIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import { extKind } from "../doc-repos/DocumentsTab";
import { ApprovalPanel } from "./ApprovalPanel";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css"; // modal and form styles
import "../../styles/kb-detail.css"; // table, notices
import "../../styles/doc-repos.css"; // metadata lists
import "../../styles/approvals.css";
import { MessageBar } from "../../components/MessageBar";

interface Props {
  token: string;
  onSessionEnded: (message: string) => void;
}

/**
 * Approvals: everything waiting for the signed-in person's decision, oldest first. Each item comes
 * from a group where they hold the deciding role (for documents: CHECKER of that repository).
 */
export function ApprovalsPage({ token, onSessionEnded }: Props) {
  const [items, setItems] = useState<ApprovalListItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ApprovalListItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listApprovals(token)
      .then((a) => {
        setItems(a);
        setError(null);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
        else setError(e instanceof Error ? e.message : "Couldn't load your approvals.");
      });
  }, [token, onSessionEnded]);
  useEffect(load, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!items || !q) return items ?? [];
    return items.filter((a) =>
      [a.title, a.resource_name, a.kind_label, a.requested_by?.display_name ?? ""].some((v) => v.toLowerCase().includes(q)),
    );
  }, [items, query]);
  const { rows, ...pager } = usePagination(filtered);

  return (
    <div className="page">
      <h1 className="page__title">Approvals</h1>

      <section aria-label="Waiting for your decision">

        {notice && <MessageBar onClose={() => setNotice(null)}>{notice}</MessageBar>}
        {error && <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>}

        <div className="toolbar">
          <div className="toolbar__left">
            <label className="search">
              <SearchIcon />
              <input type="search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Search approvals" aria-label="Search approvals" />
            </label>
          </div>
        </div>

        {items === null && !error ? (
          <p className="kb-message">Loading approvals…</p>
        ) : filtered.length === 0 ? (
          <p className="kb-message">
            {query ? `No approvals match “${query}”.` : "Nothing is waiting for your decision."}
          </p>
        ) : (
          <div className="kb-table-panel">
            <table className="data-table approvals-table">
              <colgroup>
                <col />
                <col style={{ width: "120px" }} />
                <col style={{ width: "18%" }} />
                <col style={{ width: "140px" }} />
                <col style={{ width: "48px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Type</th>
                  <th scope="col">Submitted by</th>
                  <th scope="col">Submitted</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <button type="button" className="doc-name doc-name--button" onClick={() => setOpen(a)}>
                        <span className={`doc-name__icon doc-name__icon--${extKind(a.title)}`}>
                          <FileIcon />
                        </span>
                        <span className="doc-name__text">
                          <span className="truncate">{a.title}</span>
                          <span className="doc-name__sub truncate">
                            {a.resource_name}
                            {a.round > 1 ? ` · round ${a.round}` : ""}
                          </span>
                        </span>
                      </button>
                    </td>
                    <td>
                      <span className="kb-badge kb-badge--cell">{a.kind_label}</span>
                    </td>
                    <td className="truncate">{a.requested_by?.display_name ?? "—"}</td>
                    <td title={new Date(a.requested_at).toLocaleString()}>{timeAgo(a.requested_at)}</td>
                    <td className="kb-table__actions">
                      <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Review ${a.title}`}
                        title="Review" onClick={() => setOpen(a)}>
                        <EyeIcon />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager {...pager} />
          </div>
        )}
      </section>

      <Modal open={open !== null} wide title={open?.kind_label ?? "Approval"} onClose={() => setOpen(null)}>
        {open && (
          <ApprovalPanel
            token={token}
            approval={open}
            onClose={() => setOpen(null)}
            onDecided={(message) => {
              setOpen(null);
              setNotice(message);
              load();
            }}
            onGone={(message) => {
              setOpen(null);
              setError(message);
              load();
            }}
            onSessionEnded={onSessionEnded}
          />
        )}
      </Modal>
    </div>
  );
}
