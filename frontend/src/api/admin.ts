import type { Department } from "./auth";
import { api } from "./http";

export interface AdminUser {
  username: string;
  display_name: string;
  title: string;
  email: string;
  department: Department | null;
  roles: string[]; // assigned roles; [] means an implicit viewer
  is_active: boolean;
}

export interface DepartmentRow extends Department {
  members: number;
  knowledge_bases: number;
  admins: string[];
}

export interface RoleRow {
  code: string;
  name: string;
  description: string;
  scope: "global" | "department";
  assignable: boolean;
  permissions: string[];
}

export interface PermissionRow {
  code: string;
  description: string;
  roles: string[];
}

export interface NewUser {
  lan_id: string;
  display_name: string;
  email: string;
  title: string;
  password: string;
  department_code?: string;
  role?: string;
}

export const listUsers = (t: string) => api<AdminUser[]>(t, "/users");
export const createUser = (t: string, body: NewUser) =>
  api<AdminUser>(t, "/users", { method: "POST", body: JSON.stringify(body) });

export const listDepartments = (t: string) => api<DepartmentRow[]>(t, "/departments");
export const createDepartment = (t: string, body: { code: string; name: string }) =>
  api<DepartmentRow>(t, "/departments", { method: "POST", body: JSON.stringify(body) });

export const listRoles = (t: string) => api<RoleRow[]>(t, "/roles");
export const listPermissions = (t: string) => api<PermissionRow[]>(t, "/permissions");

export const ROLE_NAMES: Record<string, string> = {
  system_admin: "System admin",
  department_admin: "Department admin",
  maker: "Maker",
  checker: "Checker",
  viewer: "Viewer",
};
