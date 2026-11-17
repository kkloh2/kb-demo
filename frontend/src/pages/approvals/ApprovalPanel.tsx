import { useEffect, useState } from "react";
import { decide, downloadFor, getApproval, type Approval, type ApprovalListItem, type DecisionKind } from "../../api/approvals";
import { ApiError } from "../../api/http";
import { ApproveIcon, DownloadIcon, RejectIcon, RequestChangesIcon } from "../../components/Icons";

const DECISION_ICON = { approve: <ApproveIcon />, reject: <RejectIcon />, request_changes: <RequestChangesIcon /> };
import { MessageBar } from "../../components/MessageBar";

interface Props {
  token: string;
  approval: ApprovalListItem; // as listed; the full approval is fetched when it opens
  onClose: () => void;
  onDecided: (message: string) => void;
  /** It can't be decided any more (another checker got there first, or it was withdrawn). */
  onGone: (message: string) => void;
  onSessionEnded: (message: string) => void;
}

const WRITING: Record<Exclude<DecisionKind, "approve">, { label: string; button: string; busy: string; placeholder: string }> = {
  request_changes: {
    label: "What needs changing",
    button: "Request changes",
    busy: "Sending…",
    placeholder: "e.g. Add the effective date",
  },
  reject: { label: "Reason for rejecting", button: "Reject", busy: "Rejecting…", placeholder: "Why it can't be approved" },
};

/** One item waiting for a decision: fetched in full when opened, then Approve, Request changes or Reject. */
export function ApprovalPanel({ token, approval: listed, onClose, onDecided, onGone, onSessionEnded }: Props) {
  const [a, setFull] = useState<Approval | null>(null);
  const [writing, setWriting] = useState<Exclude<DecisionKind, "approve"> | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<DecisionKind | null>(null);
  const [error, setError] = useState<string | null>(null);

  function fail(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onSessionEnded(e.message);
    else if (e instanceof ApiError && (e.status === 404 || e.status === 409)) onGone(`${listed.title}: ${e.message}`);
    else setError(e instanceof Error ? e.message : "Something went wrong.");
  }

  useEffect(() => {
    getApproval(token, listed.id).then(setFull).catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, listed.id]);

  if (!a) {
    return (
      <>
        <div className="modal__body doc-panel">
          {error ? (
            <MessageBar className="alert" role="alert" onClose={() => setError(null)}>{error}</MessageBar>
          ) : (
            <p className="muted">Loading {listed.title}…</p>
          )}
        </div>
        <div className="modal__footer">
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </>
    );
  }
  const s = a.summary;

  async function submit(decision: DecisionKind) {
    if (!a) return;
    setBusy(decision);
    setError(null);
    try {
      await decide(token, a.id, decision, comment.trim());
      const verb = { approve: "Approved", reject: "Rejected", request_changes: "Requested changes to" }[decision];
      onDecided(`${verb} ${a.title}.`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="modal__body doc-panel">
        {error && (
          <MessageBar className="alert" role="alert" onClose={() => setError(null)}>
            {error}
          </MessageBar>
        )}

        <header className="doc-panel__head">
          <div>
            <h3 className="doc-panel__name">{a.title}</h3>
            <p className="doc-panel__meta">
              <span className="status status--pending_approval">Pending approval</span>
              {a.round > 1 && <span className="badge badge--neutral">Round {a.round}</span>}
              {s.subtitle && <span>{s.subtitle}</span>}
            </p>
            <p className="doc-panel__meta">
              <span>
                Submitted by {a.requested_by?.display_name ?? "—"} · {new Date(a.requested_at).toLocaleString()}
              </span>
              {s.link && (
                <a className="btn-link" href={s.link.href} onClick={onClose}>
                  {s.link.label}
                </a>
              )}
            </p>
          </div>
          {s.download && (
            <button type="button" className="btn-secondary btn-sm" onClick={() => downloadFor(token, a).catch(fail)}>
              <DownloadIcon />
              Download
            </button>
          )}
        </header>

        {a.round > 1 && (
          <MessageBar className="notice notice--info">
            Changes were requested before; this is the maker's resubmission (round {a.round}).
          </MessageBar>
        )}

        {(s.facts ?? []).length > 0 && (
          <section className="meta-section">
            <h4 className="meta-section__title">Details</h4>
            <dl className="meta-list">
              {(s.facts ?? []).map((f) => (
                <div key={f.label} className="meta-list__row">
                  <dt>{f.label}</dt>
                  <dd>{f.value || <span className="muted">Not set</span>}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {(s.sections ?? []).map((sec) => (
          <section key={sec.title} className="meta-section">
            <h4 className="meta-section__title">{sec.title}</h4>
            {sec.items.length === 0 ? (
              <p className="meta-section__desc">None.</p>
            ) : (
              <dl className="meta-list">
                {sec.items.map((f) => (
                  <div key={f.label} className="meta-list__row">
                    <dt>{f.label}</dt>
                    <dd>
                      {f.value || <span className="muted">{f.note === "removed by the maker" ? "Removed" : "Not set"}</span>}
                      {f.note && <span className="tag">{f.note}</span>}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}

        {writing && (
          <label className="form-field">
            <span>{WRITING[writing].label}</span>
            <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} autoFocus
              placeholder={WRITING[writing].placeholder} />
            <small>It goes back to {a.requested_by?.display_name ?? "the maker"} with this note.</small>
          </label>
        )}
      </div>

      <div className="modal__footer">
        {!writing ? (
          <>
            <button type="button" className="btn-secondary" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn-secondary" disabled={busy !== null} onClick={() => setWriting("reject")}>
              {DECISION_ICON.reject}
              Reject
            </button>
            <button type="button" className="btn-secondary" disabled={busy !== null}
              onClick={() => setWriting("request_changes")}>
              {DECISION_ICON.request_changes}
              Request changes
            </button>
            <button type="button" className="btn-primary" disabled={busy !== null} onClick={() => submit("approve")}>
              {DECISION_ICON.approve}
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn-secondary" onClick={() => { setWriting(null); setComment(""); }}>
              Cancel
            </button>
            <button type="button" className={writing === "reject" ? "btn-danger" : "btn-primary"}
              disabled={busy !== null || !comment.trim()} onClick={() => submit(writing)}>
              {DECISION_ICON[writing]}
              {busy === writing ? WRITING[writing].busy : WRITING[writing].button}
            </button>
          </>
        )}
      </div>
    </>
  );
}
