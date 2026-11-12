/** Document & metadata management: doc-repos (a department's logical group of documents). */

import type { MetadataPair } from "./documents";
import { api } from "./http";

export type DocRepoRole = "MAKER" | "CHECKER" | "VIEWER";
export const DOC_REPO_ROLES: DocRepoRole[] = ["MAKER", "CHECKER", "VIEWER"];
export const DOC_REPO_ROLE_NAMES: Record<DocRepoRole, string> = { MAKER: "Maker", CHECKER: "Checker", VIEWER: "Viewer" };

export interface DepartmentRef {
  code: string;
  name: string;
}

/** Department metadata: copied onto each of the doc-repo's documents (a maker can override it per document). */
export interface DepartmentMetadata {
  department: string;
  business_unit: string;
  country: string;
}

export const DEPARTMENT_METADATA_LABELS: Record<keyof DepartmentMetadata, string> = {
  department: "Department",
  business_unit: "Business unit",
  country: "Country",
};

export const DEPARTMENT_METADATA_KEYS = Object.keys(DEPARTMENT_METADATA_LABELS) as (keyof DepartmentMetadata)[];

export interface DocRepoFields {
  name: string;
  description: string;
  department_metadata: DepartmentMetadata; // an empty department becomes the department's name
}

export interface DocRepo extends DocRepoFields {
  id: number;
  repository_metadata: MetadataPair[]; // set on the Metadata tab
  department: DepartmentRef;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  document_count: number; // documents in it the caller may see
  /** What the caller can do (for the UI; the server checks again on every request). */
  access: {
    manage: boolean; // department admin: edit, delete, members
    view_details: boolean; // can open its page (a doc-repo role, or department viewer / admin)
    view_documents: boolean;
    upload: boolean; // doc-repo maker
    review: boolean; // doc-repo checker
    doc_repo_roles: DocRepoRole[];
  };
}

export interface Member {
  lan_id: string;
  display_name: string;
  email: string;
  title: string;
  roles: DocRepoRole[];
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const listDocRepos = (t: string) => api<DocRepo[]>(t, "/doc-repos");
export const creatableDepartments = (t: string) => api<DepartmentRef[]>(t, "/doc-repos/departments");
export const getDocRepo = (t: string, id: number) => api<DocRepo>(t, `/doc-repos/${id}`);
export const createDocRepo = (t: string, departmentCode: string, body: DocRepoFields) =>
  api<DocRepo>(t, `/departments/${seg(departmentCode)}/doc-repos`, { method: "POST", body: json(body) });
export const updateDocRepo = (t: string, id: number, body: DocRepoFields) =>
  api<DocRepo>(t, `/doc-repos/${id}`, { method: "PUT", body: json(body) });
export const deleteDocRepo = (t: string, id: number) => api<void>(t, `/doc-repos/${id}`, { method: "DELETE" });

export const listMembers = (t: string, id: number) => api<Member[]>(t, `/doc-repos/${id}/members`);
export const setMemberRoles = (t: string, id: number, lanId: string, roles: DocRepoRole[]) =>
  api<Member>(t, `/doc-repos/${id}/members/${seg(lanId)}`, { method: "PUT", body: json({ roles }) });
export const removeMember = (t: string, id: number, lanId: string) =>
  api<void>(t, `/doc-repos/${id}/members/${seg(lanId)}`, { method: "DELETE" });
