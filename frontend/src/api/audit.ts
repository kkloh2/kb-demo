/** The audit trail: everything (platform admins), or one node's activity (audit.trail.view there). */

import { api } from "./http";

export interface AuditEvent {
  id: string;
  at: string;
  actor: string | null; // LAN ID; null: Data Hub itself
  actor_name: string | null;
  action: string; // e.g. "DOCUMENTS_UPLOADED"
  label: string; // e.g. "Documents uploaded"
  source_system: string; // PLATFORM, WORKFLOWS, DOC_HUB, APPROVALS ...
  category: string; // access, configuration, content, approval, security
  target_type: string;
  target_id: string;
  node_id: string | null;
  node_path: string | null;
  details: Record<string, unknown>;
  request_id: string | null;
  client_ip: string | null;
}

export interface AuditFilters {
  source_system?: string;
  category?: string;
  actor?: string;
  offset?: number;
  limit?: number;
}

/** One page of the trail and how many events match in all. */
export interface AuditPage {
  items: AuditEvent[];
  total: number;
}

function query(f: AuditFilters): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const listAudit = (t: string, f: AuditFilters) => api<AuditPage>(t, `/audit${query(f)}`);
export const nodeActivity = (t: string, nodeId: string, f: AuditFilters) =>
  api<AuditPage>(t, `/audit/nodes/${nodeId}${query(f)}`);

export const AREAS: Record<string, string> = {
  PLATFORM: "Administration",
  WORKFLOWS: "Workflows",
  DOC_HUB: "Document repositories",
  APPROVALS: "Approvals",
};
export const CATEGORIES: Record<string, string> = {
  access: "Access",
  configuration: "Configuration",
  content: "Content",
  approval: "Approval",
  security: "Security",
};
