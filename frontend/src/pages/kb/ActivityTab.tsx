import { useEffect, useMemo, useState } from "react";
import { listActivity, type ActivityEvent, type ActivityType } from "../../api/documents";
import { CheckIcon, ChevronIcon, CloseIcon, UploadIcon } from "../../components/Icons";
import { Pager, usePagination } from "../../components/Pager";
import { timeAgo } from "../../lib/time";

const TYPE_LABEL: Record<ActivityType, string> = {
  uploaded: "Uploaded",
  approved: "Approved",
  rejected: "Rejected",
};

const ICON: Record<ActivityType, JSX.Element> = {
  uploaded: <UploadIcon />,
  approved: <CheckIcon />,
  rejected: <CloseIcon />,
};

type Filter = "all" | ActivityType;

const fmt = new Intl.DateTimeFormat("en-SG", { dateStyle: "medium", timeStyle: "short" });

interface Props {
  token: string;
  kbId: string;
  /** Bumped by the parent after uploads or decisions, so the list refreshes. */
  version: number;
}

/** Uploads and approval decisions for this knowledge base, newest first. */
export function ActivityTab({ token, kbId, version }: Props) {
  const [events, setEvents] = useState<ActivityEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    listActivity(token, kbId)
      .then(setEvents)
      .catch((e: Error) => setError(e.message));
  }, [token, kbId, version]);

  const pending = useMemo(() => {
    const ids = new Set(
      (events ?? []).filter((e) => e.document.status === "pending_approval").map((e) => e.document.id),
    );
    return ids.size;
  }, [events]);

  const shown = useMemo(
    () => (events ?? []).filter((e) => filter === "all" || e.type === filter),
    [events, filter],
  );
  const { rows, ...pager } = usePagination(shown);

  if (error) {
    return (
      <p className="kb-message kb-message--error" role="alert">
        {error}
      </p>
    );
  }

  return (
    <section className="panel" aria-labelledby="activity-title">
      <div className="panel__head">
        <div>
          <h2 id="activity-title" className="panel__title">
            Activity
          </h2>
          <p className="panel__desc">
            Files uploaded to this knowledge base, and when each was approved or rejected.
            {pending > 0 && (
              <>
                {" "}
                <strong>
                  {pending} file{pending === 1 ? " is" : "s are"} pending approval.
                </strong>
              </>
            )}
          </p>
        </div>
        <label className="filter">
          <span className="sr-only">Activity type</span>
          <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            <option value="all">All activity</option>
            <option value="uploaded">Uploaded</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <ChevronIcon dir="down" />
        </label>
      </div>

      {events === null ? (
        <p className="kb-message">Loading activity…</p>
      ) : shown.length === 0 ? (
        <p className="kb-message">{events.length === 0 ? "No activity yet." : "No activity of this type."}</p>
      ) : (
        <>
          <table className="data-table">
            <colgroup>
              <col style={{ width: "20%" }} />
              <col style={{ width: "16%" }} />
              <col style={{ width: "28%" }} />
              <col style={{ width: "16%" }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Activity</th>
                <th scope="col">File</th>
                <th scope="col">By</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td>
                    <div className="person">
                      <span>{fmt.format(new Date(e.at))}</span>
                      <span className="person__id">{timeAgo(e.at)}</span>
                    </div>
                  </td>
                  <td>
                    <span className={`activity activity--${e.type}`}>
                      {ICON[e.type]}
                      {TYPE_LABEL[e.type]}
                    </span>
                  </td>
                  <td className="truncate" title={e.document.filename}>
                    {e.document.filename}
                  </td>
                  <td className="truncate" title={e.actor?.username}>
                    {e.actor?.display_name ?? "—"}
                  </td>
                  <td className="truncate" title={e.reason ?? undefined}>
                    {e.type === "uploaded" && e.document.status === "pending_approval" ? (
                      <span className="status status--pending_approval">Pending approval</span>
                    ) : e.reason ? (
                      <span className="muted">Reason: {e.reason}</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager {...pager} />
        </>
      )}
    </section>
  );
}
