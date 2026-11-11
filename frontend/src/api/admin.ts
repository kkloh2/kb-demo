/** Administration API (system admins): users, departments and roles. */

import { api } from "./http";

export type OrgUnitRoles = Record<string, string[]>; // department code -> roles, e.g. {"RISK": ["CHECKER"]}

export interface AdminUser {
  lan_id: string;
  display_name: string;
  email: string;
  department: string; // directory text, not an org unit
  title: string;
  system_roles: string[];
  org_unit_roles: OrgUnitRoles;
}

export interface UserUpsert {
  display_name: string;
  email: string;
  department: string;
  title: string;
  system_roles: string[]; // complete list
  org_unit_roles: OrgUnitRoles; // complete: a department left out loses all the user's roles there
}

export interface DepartmentRow {
  id: number;
  code: string;
  name: string;
}

export interface RoleRow {
  code: string;
  scope: "system" | "org_unit";
  name: string;
  description: string;
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const listUsers = (t: string) => api<AdminUser[]>(t, "/users");
export const upsertUser = (t: string, lanId: string, body: UserUpsert) =>
  api<AdminUser>(t, `/users/${seg(lanId)}`, { method: "PUT", body: json(body) });
export const deleteUser = (t: string, lanId: string) =>
  api<void>(t, `/users/${seg(lanId)}`, { method: "DELETE" });

export const listDepartments = (t: string) => api<DepartmentRow[]>(t, "/departments");
export const createDepartment = (t: string, body: { code: string; name: string }) =>
  api<DepartmentRow>(t, "/departments", { method: "POST", body: json(body) });
export const updateDepartment = (t: string, code: string, body: { code: string; name: string }) =>
  api<DepartmentRow>(t, `/departments/${seg(code)}`, { method: "PUT", body: json(body) });
export const deleteDepartment = (t: string, code: string) =>
  api<void>(t, `/departments/${seg(code)}`, { method: "DELETE" });

export const listRoles = (t: string) => api<RoleRow[]>(t, "/roles");
