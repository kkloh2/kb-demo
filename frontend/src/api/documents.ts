/** Documents in a doc-repo: upload, metadata, submit, review. */

import type { DepartmentMetadata } from "./doc-repos";
import { ApiError, api } from "./http";

export type DocumentStatus = "draft" | "pending_approval" | "approved" | "rejected";

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
};

/** One repository metadata entry: plain text. */
export interface MetadataPair {
  key: string;
  value: string;
}

export interface PersonRef {
  lan_id: string;
  display_name: string;
}

export interface DocRepoDocument {
  id: number;
  doc_repo_id: number;
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
  department_metadata: DepartmentMetadata;
  department_overrides: (keyof DepartmentMetadata)[];
  repository_metadata: Record<string, string>; // repository key -> this document's value
  repository_overrides: string[]; // keys whose value differs from the repository's
  extra: Record<string, string>;
  ai_metadata: Record<string, unknown>;
  actions: { edit: boolean; submit: boolean; review: boolean; delete: boolean };
}

export interface BulkResult {
  done: DocRepoDocument[];
  skipped: { id: number; filename: string; reason: string }[];
}

const base = (docRepoId: number) => `/doc-repos/${docRepoId}`;
const json = (body: unknown) => JSON.stringify(body);

export const listDocuments = (t: string, docRepoId: number) =>
  api<{ documents: DocRepoDocument[]; repository_metadata: MetadataPair[] }>(t, `${base(docRepoId)}/documents`);

export const getDocument = (t: string, docRepoId: number, id: number) =>
  api<DocRepoDocument>(t, `${base(docRepoId)}/documents/${id}`);

/** Upload files; for a folder upload, each file's relative path keeps the folder structure. */
export function uploadDocuments(t: string, docRepoId: number, files: { file: File; path: string }[]) {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f.file, f.file.name);
    form.append("paths", f.path);
  }
  return api<DocRepoDocument[]>(t, `${base(docRepoId)}/documents`, { method: "POST", body: form });
}

export const updateMetadata = (
  t: string,
  docRepoId: number,
  id: number,
  body: { department_metadata: DepartmentMetadata; repository_metadata: Record<string, string>; extra: Record<string, string> },
) => api<DocRepoDocument>(t, `${base(docRepoId)}/documents/${id}/metadata`, { method: "PUT", body: json(body) });

export const submitDocuments = (t: string, docRepoId: number, ids: number[]) =>
  api<BulkResult>(t, `${base(docRepoId)}/documents/submit`, { method: "POST", body: json({ ids }) });

export const reviewDocuments = (t: string, docRepoId: number, ids: number[], decision: "approve" | "reject", reason = "") =>
  api<BulkResult>(t, `${base(docRepoId)}/documents/review`, { method: "POST", body: json({ ids, decision, reason }) });

export const deleteDocuments = (t: string, docRepoId: number, ids: number[]) =>
  api<BulkResult>(t, `${base(docRepoId)}/documents/delete`, { method: "POST", body: json({ ids }) });

export const replaceRepositoryMetadata = (t: string, docRepoId: number, pairs: MetadataPair[]) =>
  api<MetadataPair[]>(t, `${base(docRepoId)}/repository-metadata`, { method: "PUT", body: json(pairs) });

/** Download with the access token (a plain link can't send it), then save the file. */
export async function downloadDocument(t: string, doc: DocRepoDocument): Promise<void> {
  const apiBase = import.meta.env.VITE_API_BASE ?? "/api";
  const res = await fetch(`${apiBase}${base(doc.doc_repo_id)}/documents/${doc.id}/download`, {
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
