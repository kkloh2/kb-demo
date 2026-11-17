/** Documents in a repository: upload, metadata, submit. Decisions happen on the Approvals page. */

import type { PersonRef } from "./doc-repos";
import { ApiError, api } from "./http";

export type DocumentStatus = "draft" | "pending_approval" | "changes_requested" | "approved" | "rejected";

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending approval",
  changes_requested: "Changes requested",
  approved: "Approved",
  rejected: "Rejected",
};

export type MetadataState = "inherited" | "overridden" | "removed" | "own" | "suggested";

export interface MetadataEntry {
  field_id: string;
  label: string;
  value: string | null; // null: removed by the maker
  state: MetadataState;
  inherited_value: string | null; // for overridden / removed: the repository's current value
  from_node: string | null;
  overridable: boolean;
}

export interface Decision {
  decision: "APPROVED" | "REJECTED" | "CHANGES_REQUESTED";
  comment: string | null;
  decided_by: PersonRef | null;
  decided_at: string;
  round: number;
}

export interface DocRepoDocument {
  id: string;
  doc_repo_id: string;
  folder: string; // "Policies/2026"; "" for the top level
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: DocumentStatus;
  maker: PersonRef | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  last_decision: Decision | null;
  metadata: MetadataEntry[];
  actions: {
    edit: boolean;
    submit: boolean;
    delete: boolean;
    discard: boolean; // throw away the latest version, back to the one before
    versions: boolean; // may see every version (makers, checkers, auditors)
  };
  version: number; // the version shown: the latest, or for viewers the latest approved one
  uploaded_at: string; // when that version's file was uploaded
  latest: boolean; // false when an earlier, approved version is shown
  approved_version: number | null; // the latest approved version's number
  outcome?: "new" | "replaced" | "version" | null; // after an upload
}

/** One version of a document, from its history. */
export interface DocumentVersion {
  number: number;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  status: DocumentStatus;
  uploaded_by: PersonRef | null;
  created_at: string;
  submitted_at: string | null;
  superseded_at: string | null;
  discarded_at: string | null;
  restored_from: number | null;
  approval_request_id: string | null; // matches RequestHistory.id
  latest: boolean;
  approved: boolean; // the latest approved version: what viewers see
  last_decision: Decision | null;
  can_restore: boolean;
}

export interface BulkResult {
  done: DocRepoDocument[];
  skipped: { id: string; filename: string; reason: string }[];
}

export interface RequestHistory {
  id: string;
  reference: string;
  status: "PENDING" | "CHANGES_REQUESTED" | "APPROVED" | "REJECTED" | "CANCELLED";
  requested_by: PersonRef | null;
  submitted_at: string;
  completed_at: string | null;
  rounds: {
    id: string; // the task: one per review step per round
    round: number;
    step: string | null; // e.g. "Checker review"
    status: string;
    outcome: string | null;
    created_at: string;
    completed_at: string | null;
    decisions: Decision[];
  }[];
}

export interface MetadataUpdate {
  inherited: { field_id: string; state: "inherit" | "override" | "remove"; value?: string | null }[];
  own: { label: string; value: string }[];
}

const base = (repoId: string) => `/doc-repos/${repoId}`;
const json = (body: unknown) => JSON.stringify(body);

/** "published": each document's latest approved version; "in_progress": latest versions not yet
 * approved; "all": each document as the person sees it. */
export type DocumentsView = "all" | "published" | "in_progress";

export const listDocuments = (t: string, repoId: string, view: DocumentsView = "all") =>
  api<DocRepoDocument[]>(t, `${base(repoId)}/documents?view=${view}`);
/** `published`: its latest approved version rather than its latest. */
export const getDocument = (t: string, repoId: string, id: string, published = false) =>
  api<DocRepoDocument>(t, `${base(repoId)}/documents/${id}${published ? "?published=true" : ""}`);
export const documentHistory = (t: string, repoId: string, id: string) =>
  api<RequestHistory[]>(t, `${base(repoId)}/documents/${id}/history`);
export const listVersions = (t: string, repoId: string, id: string) =>
  api<DocumentVersion[]>(t, `${base(repoId)}/documents/${id}/versions`);
export const restoreVersion = (t: string, repoId: string, id: string, n: number) =>
  api<DocRepoDocument>(t, `${base(repoId)}/documents/${id}/versions/${n}/restore`, { method: "POST" });
export const discardVersion = (t: string, repoId: string, id: string) =>
  api<DocRepoDocument>(t, `${base(repoId)}/documents/${id}/discard-version`, { method: "POST" });

/** Upload files; for a folder upload, each file's relative path keeps the folder structure. */
export function uploadDocuments(t: string, repoId: string, files: { file: File; path: string }[]) {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f.file, f.file.name);
    form.append("paths", f.path);
  }
  return api<DocRepoDocument[]>(t, `${base(repoId)}/documents`, { method: "POST", body: form });
}

export const updateMetadata = (t: string, repoId: string, id: string, body: MetadataUpdate) =>
  api<DocRepoDocument>(t, `${base(repoId)}/documents/${id}/metadata`, { method: "PUT", body: json(body) });
/** Submit for approval, all or none. `statuses`: what each document's status was when chosen; if any
 * has changed since, nothing is submitted (409). */
export const submitDocuments = (t: string, repoId: string, statuses: Record<string, DocumentStatus>) =>
  api<BulkResult>(t, `${base(repoId)}/documents/submit`, {
    method: "POST",
    body: json({ ids: Object.keys(statuses), statuses }),
  });
export const deleteDocuments = (t: string, repoId: string, ids: string[]) =>
  api<BulkResult>(t, `${base(repoId)}/documents/delete`, { method: "POST", body: json({ ids }) });

/** Download with the access token (a plain link can't send it), then save the file. */
export async function downloadPath(t: string, path: string, filename: string): Promise<void> {
  const apiBase = import.meta.env.VITE_API_BASE ?? "/api";
  const res = await fetch(`${apiBase}${path}`, { headers: { Authorization: `Bearer ${t}` } });
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The version shown: `doc` as listed (a Published list's document downloads its approved version). */
export const downloadDocument = (t: string, doc: DocRepoDocument, published = false) =>
  downloadPath(t, `${base(doc.doc_repo_id)}/documents/${doc.id}/download${published ? "?published=true" : ""}`, doc.filename);
export const downloadVersion = (t: string, doc: DocRepoDocument, v: DocumentVersion) =>
  downloadPath(t, `${base(doc.doc_repo_id)}/documents/${doc.id}/versions/${v.number}/download`, v.filename);

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const DECISION_LABEL: Record<Decision["decision"], string> = {
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CHANGES_REQUESTED: "Changes requested",
};
