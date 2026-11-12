/** Documents in a project: upload, metadata, submit, review. */

import { ApiError, api } from "./http";

export type DocumentStatus = "draft" | "pending_approval" | "approved" | "rejected";

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
};

export type FieldType = "text" | "date" | "select";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  options: string[];
  required: boolean;
}

export interface BaseMetadata {
  country: string;
  business_unit: string;
  purpose: string;
  valid_till: string | null;
}

export const BASE_LABELS: Record<keyof BaseMetadata, string> = {
  country: "Country",
  business_unit: "Business unit",
  purpose: "Purpose",
  valid_till: "Valid till",
};

export interface PersonRef {
  lan_id: string;
  display_name: string;
}

export interface ProjectDocument {
  id: number;
  project_id: number;
  folder: string; // "Policies/2026"; "" for the top level
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: DocumentStatus;
  maker: PersonRef | null;
  checker: PersonRef | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  decided_at: string | null;
  rejection_reason: string | null;
  base: BaseMetadata;
  base_overrides: (keyof BaseMetadata)[];
  fields: Record<string, string>;
  extra: Record<string, string>;
  ai_metadata: Record<string, unknown>;
  missing_required: string[];
  actions: { edit: boolean; submit: boolean; review: boolean; delete: boolean };
}

export interface BulkResult {
  done: ProjectDocument[];
  skipped: { id: number; filename: string; reason: string }[];
}

const base = (projectId: number) => `/projects/${projectId}`;
const json = (body: unknown) => JSON.stringify(body);

export const listDocuments = (t: string, projectId: number) =>
  api<{ documents: ProjectDocument[]; fields: FieldDef[] }>(t, `${base(projectId)}/documents`);

export const getDocument = (t: string, projectId: number, id: number) =>
  api<ProjectDocument>(t, `${base(projectId)}/documents/${id}`);

/** Upload files; for a folder upload, each file's relative path keeps the folder structure. */
export function uploadDocuments(t: string, projectId: number, files: { file: File; path: string }[]) {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f.file, f.file.name);
    form.append("paths", f.path);
  }
  return api<ProjectDocument[]>(t, `${base(projectId)}/documents`, { method: "POST", body: form });
}

export const updateMetadata = (
  t: string,
  projectId: number,
  id: number,
  body: { base: BaseMetadata; fields: Record<string, string>; extra: Record<string, string> },
) => api<ProjectDocument>(t, `${base(projectId)}/documents/${id}/metadata`, { method: "PUT", body: json(body) });

export const submitDocuments = (t: string, projectId: number, ids: number[]) =>
  api<BulkResult>(t, `${base(projectId)}/documents/submit`, { method: "POST", body: json({ ids }) });

export const reviewDocuments = (t: string, projectId: number, ids: number[], decision: "approve" | "reject", reason = "") =>
  api<BulkResult>(t, `${base(projectId)}/documents/review`, { method: "POST", body: json({ ids, decision, reason }) });

export const deleteDocuments = (t: string, projectId: number, ids: number[]) =>
  api<BulkResult>(t, `${base(projectId)}/documents/delete`, { method: "POST", body: json({ ids }) });

export const listFields = (t: string, projectId: number) => api<FieldDef[]>(t, `${base(projectId)}/fields`);
export const replaceFields = (t: string, projectId: number, fields: FieldDef[]) =>
  api<FieldDef[]>(t, `${base(projectId)}/fields`, { method: "PUT", body: json(fields) });

/** Download with the access token (a plain link can't send it), then save the file. */
export async function downloadDocument(t: string, doc: ProjectDocument): Promise<void> {
  const apiBase = import.meta.env.VITE_API_BASE ?? "/api";
  const res = await fetch(`${apiBase}${base(doc.project_id)}/documents/${doc.id}/download`, {
    headers: { Authorization: `Bearer ${t}` },
  });
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: doc.filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
