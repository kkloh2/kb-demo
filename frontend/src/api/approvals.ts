/** Approvals: what waits for the signed-in person's decision, and their decisions. */

import type { PersonRef } from "./doc-repos";
import { downloadPath } from "./documents";
import { api } from "./http";

export interface SummaryItem {
  label: string;
  value: string;
  note?: string; // e.g. "changed by the maker"
}

/** What the module that asked shows the checker. Every part is optional. */
export interface ApprovalSummary {
  subtitle?: string;
  facts?: SummaryItem[];
  sections?: { title: string; items: SummaryItem[] }[];
  download?: { href: string; filename: string } | null; // API path to the file
  link?: { label: string; href: string } | null;
}

/** A task as listed: everything comes from the task's stored metadata. */
export interface ApprovalListItem {
  id: string; // the task
  kind: string; // e.g. "DOCUMENT_UPLOAD"
  kind_label: string; // e.g. "Document"
  title: string;
  round: number; // 2, 3 ... after changes were requested
  resource_name: string;
  requested_by: PersonRef | null; // who submitted this round
  requested_at: string;
  metadata: Record<string, unknown>; // the task's metadata as stored
}

/** A task opened in full (GET /api/approvals/{id}): with the summary the asking module shows. */
export interface Approval {
  id: string; // the task
  request_id: string;
  kind: string; // e.g. "DOCUMENT_UPLOAD"
  kind_label: string; // e.g. "Document"
  title: string;
  round: number; // 2, 3 ... after changes were requested
  resource_name: string;
  summary: ApprovalSummary;
  requested_by: PersonRef | null;
  requested_at: string;
}

export type DecisionKind = "approve" | "reject" | "request_changes";

export const listApprovals = (t: string) => api<ApprovalListItem[]>(t, "/approvals");
export const getApproval = (t: string, id: string) => api<Approval>(t, `/approvals/${id}`);

export const decide = (t: string, id: string, decision: DecisionKind, comment = "") =>
  api<void>(t, `/approvals/${id}/decision`, { method: "POST", body: JSON.stringify({ decision, comment }) });

/** Download the file an approval points to. */
export const downloadFor = (t: string, a: Approval) =>
  a.summary.download ? downloadPath(t, a.summary.download.href, a.summary.download.filename) : Promise.resolve();
