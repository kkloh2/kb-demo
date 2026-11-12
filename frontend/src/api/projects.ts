/** Document & metadata management: projects (a department's logical group of documents). */

import { api } from "./http";

export type ProjectRole = "MAKER" | "CHECKER" | "VIEWER";
export const PROJECT_ROLES: ProjectRole[] = ["MAKER", "CHECKER", "VIEWER"];
export const PROJECT_ROLE_NAMES: Record<ProjectRole, string> = { MAKER: "Maker", CHECKER: "Checker", VIEWER: "Viewer" };

export interface DepartmentRef {
  code: string;
  name: string;
}

/** Base metadata shared by the project's documents (a maker can override it per document). */
export interface ProjectFields {
  name: string;
  description: string;
  country: string;
  business_unit: string;
  purpose: string;
  valid_till: string | null; // YYYY-MM-DD
}

export interface Project extends ProjectFields {
  id: number;
  department: DepartmentRef;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** What the caller can do (for the UI; the server checks again on every request). */
  access: {
    manage: boolean; // department admin: edit, delete, members
    view_documents: boolean;
    upload: boolean; // project maker
    review: boolean; // project checker
    project_roles: ProjectRole[];
  };
}

export interface Member {
  lan_id: string;
  display_name: string;
  email: string;
  title: string;
  roles: ProjectRole[];
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const listProjects = (t: string) => api<Project[]>(t, "/projects");
export const creatableDepartments = (t: string) => api<DepartmentRef[]>(t, "/projects/departments");
export const getProject = (t: string, id: number) => api<Project>(t, `/projects/${id}`);
export const createProject = (t: string, departmentCode: string, body: ProjectFields) =>
  api<Project>(t, `/departments/${seg(departmentCode)}/projects`, { method: "POST", body: json(body) });
export const updateProject = (t: string, id: number, body: ProjectFields) =>
  api<Project>(t, `/projects/${id}`, { method: "PUT", body: json(body) });
export const deleteProject = (t: string, id: number) => api<void>(t, `/projects/${id}`, { method: "DELETE" });

export const listMembers = (t: string, id: number) => api<Member[]>(t, `/projects/${id}/members`);
export const setMemberRoles = (t: string, id: number, lanId: string, roles: ProjectRole[]) =>
  api<Member>(t, `/projects/${id}/members/${seg(lanId)}`, { method: "PUT", body: json({ roles }) });
export const removeMember = (t: string, id: number, lanId: string) =>
  api<void>(t, `/projects/${id}/members/${seg(lanId)}`, { method: "DELETE" });
