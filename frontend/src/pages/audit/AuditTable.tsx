import { useState } from "react";
import { AREAS, CATEGORIES, type AuditEvent } from "../../api/audit";
import { EyeIcon } from "../../components/Icons";
import { Modal } from "../../components/Modal";
import { timeAgo } from "../../lib/time";

/** One line about what changed, from an event's details. */
export function summary(e: AuditEvent): string {
  const d = e.details as Record<string, any>;
  if (d.before !== undefined && d.after !== undefined && typeof d.before === "object" && d.before && !Array.isArray(d.before)) {
    const keys = Object.keys({ ...d.before, ...d.after });
    return keys.slice(0, 2).map((k) => `${k}: ${d.before[k] ?? "—"} → ${d.after[k] ?? "—"}`).join("; ")
      + (keys.length > 2 ? ` (+${keys.length - 2} more)` : "");
  }
  if (d.before !== undefined && d.after !== undefined) return `${fmt(d.before)} → ${fmt(d.after)}`;
  if (Array.isArray(d.files)) {
    const names = d.files.map((f: any) => (typeof f === "string" ? f : f.name));
    return names.length === 1 ? names[0] : `${names.length} files`;
  }
  if (d.team && d.role) return `${String(d.team).replace(/^TEAM:/, "")} · ${d.role}`;
  if (d.decision) return `${String(d.decision).replace(/_/g, " ").toLowerCase()}${d.title ? ` · ${d.title}` : ""}`;
  if (d.outcome) return `${String(d.outcome).toLowerCase()}${d.title ? ` · ${d.title}` : ""}`;
  if (d.reason) return String(d.reason);
  if (d.title) return String(d.title);
  if (d.filename) return String(d.filename);
  if (d.name) return String(d.name);
  if (d.version) return `version ${d.version}`;
  return e.target_id && e.target_type !== "node" ? e.target_id : "";
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** What a node is called in each area; access records node events generically ("Created"). */
const NODE_NOUN: Record<string, string> = { DOC_HUB: "Repository" };

/** The event's label, naming the kind of node for generic node events ("Repository created"). */
export function label(e: AuditEvent): string {
  const noun = NODE_NOUN[e.source_system];
  return e.action.startsWith("NODE_") && noun ? `${noun} ${e.label.charAt(0).toLowerCase()}${e.label.slice(1)}` : e.label;
}

/** A refused or failed attempt (shown in red); ordinary sign-ins aren't alarming. */
const alarming = (e: AuditEvent) => /_(FAILED|REFUSED)$/.test(e.action);

/** "/DOC_HUB/RISK_POLICIES" -> "RISK_POLICIES"; nothing for events not at a node. */
const place = (e: AuditEvent) => (e.node_path ? e.node_path.split("/").filter(Boolean).slice(-1)[0] : "—");

/** "17 Nov 2026, 01:28:33" in the viewer's time zone. */
const stamp = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** The audit trail as a table; the eye opens an event's full details. */
export function AuditTable({
  events,
  showPlace = true,
}: {
  events: AuditEvent[];
  showPlace?: boolean;
}) {
  const [open, setOpen] = useState<AuditEvent | null>(null);

  return (
    <>
      <table className="data-table members-table audit-table">
        <colgroup>
          <col style={{ width: "190px" }} />
          <col />
          <col style={{ width: "200px" }} />
          {showPlace && <col style={{ width: "160px" }} />}
          <col style={{ width: "48px" }} />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Timestamp</th>
            <th scope="col">Event</th>
            <th scope="col">Originated from</th>
            {showPlace && <th scope="col">Where</th>}
            <th scope="col">
              <span className="visually-hidden">Details</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td title={timeAgo(e.at)}>{stamp(e.at)}</td>
              <td className="cell-wrap">
                <div className="audit-what">
                  <span className={alarming(e) ? "audit-what__label audit-what__label--security" : "audit-what__label"}>
                    {label(e)}
                  </span>
                  {summary(e) && <span className="audit-what__summary">{summary(e)}</span>}
                </div>
              </td>
              <td className="truncate" title={e.actor ?? undefined}>
                {e.actor_name ?? e.actor ?? <span className="muted">Data Hub</span>}
              </td>
              {showPlace && <td className="truncate" title={e.node_path ?? undefined}>{place(e)}</td>}
              <td className="kb-table__actions">
                <button type="button" className="kb-icon-btn kb-icon-btn--brand" aria-label={`Details of ${label(e)}`}
                  title="Details" onClick={() => setOpen(e)}>
                  <EyeIcon />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Modal open={open !== null} title={open ? label(open) : ""} onClose={() => setOpen(null)} wide>
        {open && (
          <>
            <div className="modal__body">
              <dl className="meta-list">
                {[
                  ["Timestamp", stamp(open.at)],
                  ["Originated from", open.actor ? `${open.actor_name ?? open.actor} (${open.actor})` : "Data Hub"],
                  ["Area", AREAS[open.source_system] ?? open.source_system],
                  ["Kind", `${CATEGORIES[open.category] ?? open.category} · ${open.action}`],
                  ["About", `${open.target_type} ${open.target_id}`],
                  ["Where", open.node_path ?? "—"],
                  ["From", open.client_ip ?? "—"],
                  ["Request", open.request_id ?? "—"],
                ].map(([k, v]) => (
                  <div key={k} className="meta-list__row">
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <section className="meta-section">
                <h4 className="meta-section__title">Details</h4>
                <pre className="audit-details">{JSON.stringify(open.details, null, 2)}</pre>
              </section>
            </div>
            <div className="modal__footer">
              <button type="button" className="btn-secondary" onClick={() => setOpen(null)}>
                Close
              </button>
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
