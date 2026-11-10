import { api, ApiError } from "./http";
import type { KnowledgeBase } from "./knowledgeBases";

export type DocumentStatus = "pending_approval" | "approved" | "rejected";

export interface PersonRef {
  username: string;
  display_name: string;
}

export interface KbDocument {
  id: number;
  kb_id: string;
  title: string;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  has_file: boolean;
  status: DocumentStatus;
  maker: PersonRef;
  checker: PersonRef | null;
  submitted_at: string;
  decided_at: string | null;
  rejection_reason: string | null;
}

export interface KbCapabilities {
  view_documents: boolean;
  view_unapproved: boolean;
  upload: boolean;
  review: boolean;
  edit: boolean;
}

export interface KnowledgeBaseDetail extends KnowledgeBase {
  capabilities: KbCapabilities;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const kbPath = (id: string) => `/knowledge-bases/${encodeURIComponent(id)}`;

export const getKnowledgeBase = (t: string, id: string) => api<KnowledgeBaseDetail>(t, kbPath(id));

export const listDocuments = (t: string, kbId: string) => api<KbDocument[]>(t, `${kbPath(kbId)}/documents`);

export function uploadDocuments(t: string, kbId: string, files: File[]) {
  const body = new FormData();
  files.forEach((f) => body.append("files", f, f.name));
  return api<KbDocument[]>(t, `${kbPath(kbId)}/documents`, { method: "POST", body });
}

export const approveDocument = (t: string, id: number) =>
  api<KbDocument>(t, `/documents/${id}/approve`, { method: "POST", body: JSON.stringify({}) });

export const rejectDocument = (t: string, id: number, reason: string) =>
  api<KbDocument>(t, `/documents/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });

/** Fetch with the auth header, then hand the file to the browser as a download. */
export async function downloadDocument(t: string, doc: KbDocument): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${doc.id}/download`, {
    headers: { Authorization: `Bearer ${t}` },
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new ApiError(res.status, detail ?? `Download failed (${res.status})`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: doc.filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type ActivityType = "uploaded" | "approved" | "rejected";

export interface ActivityEvent {
  id: string;
  type: ActivityType;
  at: string;
  document: { id: number; filename: string; status: DocumentStatus };
  actor: PersonRef | null;
  reason: string | null;
}

export const listActivity = (t: string, kbId: string) => api<ActivityEvent[]>(t, `${kbPath(kbId)}/activity`);
