import { useCallback, useEffect, useMemo, useState } from "react";
import { decideMany, listApprovals, type ApprovalListItem, type DecisionKind } from "../../api/approvals";
import { ApiError } from "../../api/http";
import { ApproveIcon, EyeIcon, FileIcon, RejectIcon, RequestChangesIcon, SearchIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";
import { extKind } from "../doc-repos/docs-common";
import { ApprovalPanel } from "./ApprovalPanel";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css"; // modal and form styles
import "../../styles/kb-detail.css"; // table, notices
import "../../styles/doc-repos.css"; // metadata lists
import "../../styles/approvals.css";
import { MessageBar } from "../../components/MessageBar";
import { SelectAll } from "../../components/SelectAll";
import { SortHeader, useSort } from "../../components/Sort";

const BULK: Record<DecisionKind, { title: string; button: string; busy: string; done: string; label: string; placeholder: string }> = {
  approve: {
    title: "Approve", button: "Approve", busy: "Approving…", done: "Approved",
    label: "Comment (optional)", placeholder: "Recorded on each decision",
  },
  request_changes: {
    title: "Request changes", button: "Request changes", busy: "Sending…", done: "Requested changes to",
    label: "What needs changing", placeholder: "e.g. Add the effective date",
  },
  reject: {
    title: "Reject", button: "Reject", busy: "Rejecting…", done: "Rejected",
    label: "Reason for rejecting", placeholder: "Why they can't be approved",
  },
};

interface Props {
  token: string;
  onSessionEnded: (message: string) => void;
}

/** A document's version, from what the task's metadata says about it. */
const versionOf = (a: ApprovalListItem) =>
  Number((a.metadata.document as { version?: number } | undefined)?.version ?? 1);

/**
 * Approvals: everything waiting for the signed-in person's decision, oldest first. Each item comes
 * from a group where they hold the deciding role (for documents: CHECKER of that repository).
 * Ticked items (from any repository) can be decided together with one comment, all or none.
 */
export function ApprovalsPage({ token, onSessionEnded }: Props) {
  const [items, setItems] = useState<ApprovalListItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<ApprovalListItem | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState<DecisionKind | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listApprovals(token)
      .then((a) => {
        setItems(a);
        const ids = new Set(a.map((i) => i.id)); // ticks on items that have gone are dropped
        setSelected((sel) => (sel.size && [...sel].some((id) => !ids.has(id)) ? new Set([...sel].filter((id) => ids.has(id))) : sel));
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
  const { sorted, sort, toggle: sortBy } = useSort(filtered, {
    title: { value: (a) => a.title },
    kind: { value: (a) => a.kind_label },
    by: { value: (a) => a.requested_by?.display_name },
    at: { value: (a) => a.requested_at, desc: true },
  }, { key: "at", dir: "asc" });
  const { rows, ...pager } = usePagination(sorted);

  // A new search starts a new selection; "select all" covers everything it matches.
  useEffect(() => setSelected(new Set()), [query]);
  const tickedHere = filtered.filter((a) => selected.has(a.id)).length;
  const chosen = (items ?? []).filter((a) => selected.has(a.id));

  function toggle(id: string) {
    setSelected((sel) => {
      const next = new Set(sel);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function startBulk(kind: DecisionKind) {
    setComment("");
    setBulk(kind);
  }

  async function decideSelected() {
    if (!bulk) return;
    const kind = bulk;
    const n = selected.size;
    setBusy(true);
    setError(null);
    try {
      await decideMany(token, [...selected], kind, comment.trim());
      setNotice(`${BULK[kind].done} ${n} item${n === 1 ? "" : "s"}.`);
      setSelected(new Set());
      setBulk(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
      else {
        setError(e instanceof Error ? e.message : "Something went wrong.");
        setBulk(null);
        if (e instanceof ApiError && e.status === 409) setSelected(new Set());
      }
    } finally {
      setBusy(false);
      load();
    }
  }

  const needsComment = bulk !== null && bulk !== "approve";

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
          <div className="toolbar__right bulk-actions">
            <span className="selection-count" aria-live="polite">
              {selected.size === 0 ? (
                "Select items to decide on them together"
              ) : (
                <>
                  <strong>{selected.size} selected</strong>
                  <button type="button" className="btn-link" onClick={() => setSelected(new Set())}>
                    Clear
                  </button>
                </>
              )}
            </span>
            <button type="button" className="btn-secondary" disabled={selected.size === 0 || busy}
              onClick={() => startBulk("reject")}>
              <RejectIcon />
              Reject
            </button>
            <button type="button" className="btn-secondary" disabled={selected.size === 0 || busy}
              onClick={() => startBulk("request_changes")}>
              <RequestChangesIcon />
              Request changes
            </button>
            <button type="button" className="btn-primary" disabled={selected.size === 0 || busy}
              onClick={() => startBulk("approve")}>
              <ApproveIcon />
              Approve
            </button>
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
                <col style={{ width: "44px" }} />
                <col />
                <col style={{ width: "120px" }} />
                <col style={{ width: "18%" }} />
                <col style={{ width: "140px" }} />
                <col style={{ width: "48px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col" className="check-cell">
                    <SelectAll selected={tickedHere} total={filtered.length} label="Select all"
                      onChange={(all) => setSelected(all ? new Set(filtered.map((a) => a.id)) : new Set())} />
                  </th>
                  <SortHeader label="Item" sortKey="title" sort={sort} onSort={sortBy} />
                  <SortHeader label="Type" sortKey="kind" sort={sort} onSort={sortBy} />
                  <SortHeader label="Submitted by" sortKey="by" sort={sort} onSort={sortBy} />
                  <SortHeader label="Submitted" sortKey="at" sort={sort} onSort={sortBy} />
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td className="check-cell">
                      <input type="checkbox" className="row-check" aria-label={`Select ${a.title}`}
                        checked={selected.has(a.id)} onChange={() => toggle(a.id)} />
                    </td>
                    <td>
                      <button type="button" className="doc-name doc-name--button" onClick={() => setOpen(a)}>
                        <span className={`doc-name__icon doc-name__icon--${extKind(a.title)}`}>
                          <FileIcon />
                        </span>
                        <span className="doc-name__text">
                          <span className="truncate">{a.title}</span>
                          <span className="doc-name__sub truncate">
                            {a.resource_name}
                            {versionOf(a) > 1 ? ` · version ${versionOf(a)}` : ""}
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

      <Modal open={bulk !== null} title={bulk ? `${BULK[bulk].title}: ${chosen.length} item${chosen.length === 1 ? "" : "s"}` : ""}
        onClose={() => !busy && setBulk(null)}>
        {bulk && (
          <>
            <div className="modal__body bulk-confirm">
              <p className="modal__text">
                The same decision and comment are recorded on each item. If any was decided or withdrawn after you
                selected it, none is decided.
              </p>
              <ul className="selection-list">
                {chosen.map((a) => (
                  <li key={a.id}>
                    <span className={`doc-name__icon doc-name__icon--${extKind(a.title)}`}>
                      <FileIcon />
                    </span>
                    <span className="selection-list__name" title={a.title}>{a.title}</span>
                    <span className="selection-list__meta" title={a.resource_name}>{a.resource_name}</span>
                  </li>
                ))}
              </ul>
              <label className="form-field">
                <span>{BULK[bulk].label}</span>
                <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} autoFocus
                  placeholder={BULK[bulk].placeholder} maxLength={4000} />
                {needsComment && <small>Each maker sees this note.</small>}
              </label>
            </div>
            <div className="modal__footer">
              <button type="button" className="btn-secondary" disabled={busy} onClick={() => setBulk(null)}>
                Cancel
              </button>
              <button type="button" className={bulk === "reject" ? "btn-danger" : "btn-primary"}
                disabled={busy || chosen.length === 0 || (needsComment && !comment.trim())} onClick={decideSelected}>
                {bulk === "approve" ? <ApproveIcon /> : bulk === "reject" ? <RejectIcon /> : <RequestChangesIcon />}
                {busy ? BULK[bulk].busy : `${BULK[bulk].button} ${chosen.length}`}
              </button>
            </div>
          </>
        )}
      </Modal>

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
