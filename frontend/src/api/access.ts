/** Access: what the signed-in person may do, and the platform admin pages. */

import { api } from "./http";

export interface Person {
  lan_id: string;
  display_name: string;
  email: string;
  title: string;
}

export interface NodeAccess {
  system: string; // "PLATFORM", "DOC_HUB", "APPROVALS"
  node_id: string;
  node_code: string;
  node_name: string;
  node_type: string; // "ROOT", "DOC_REPO"
  path: string;
  roles: string[];
  permissions: string[];
}

/** For the UI only; the server checks every request. */
export interface MyAccess {
  system_roles: Record<string, string[]>; // roles at each system's root; [] = roles only below it
  platform_admin: boolean;
  can_decide: boolean; // show the Approvals page
  nodes: NodeAccess[];
}

export interface AdminUser extends Person {
  directory_department: string;
  status: "ACTIVE" | "INACTIVE";
  platform_admin: boolean;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Member extends Person {
  roles: string[];
}

export interface Team {
  code: string;
  name: string;
  members: Person[];
}

export interface DefaultGrant {
  id: string;
  system: string;
  child_node_type: string;
  team: string;
  team_name: string;
  role: string;
}

export interface RoleInfo {
  code: string;
  name: string;
  description: string;
  permissions: string[];
}

export interface AuditEvent {
  id: string;
  at: string;
  actor: string | null;
  action: string;
  target_type: string;
  target_id: string;
  node_id: string | null;
  details: Record<string, unknown>;
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const myAccess = (t: string) => api<MyAccess>(t, "/me/access");

/** Can the person create document repositories (ADMIN at the Doc Hub root)? */
export const canCreateRepos = (a: MyAccess | null) =>
  !!a?.nodes.some((n) => n.system === "DOC_HUB" && n.node_type === "ROOT" && n.permissions.includes("docs.repository.create"));

export const listUsers = (t: string) => api<AdminUser[]>(t, "/users");
export const upsertUser = (
  t: string,
  lanId: string,
  // Every field optional: a new user with none gets placeholder details until their first sign-in.
  body: { display_name?: string; email?: string; title?: string; directory_department?: string; platform_admin?: boolean },
) => api<AdminUser>(t, `/users/${seg(lanId)}`, { method: "PUT", body: json(body) });
export const setUserActive = (t: string, lanId: string, active: boolean) =>
  api<AdminUser>(t, `/users/${seg(lanId)}/active`, { method: "POST", body: json({ active }) });

export const listRoles = (t: string) =>
  api<{ roles: RoleInfo[]; permissions: { code: string; name: string }[] }>(t, "/roles");

export const listTeams = (t: string) => api<Team[]>(t, "/teams");
export const setTeamMembers = (t: string, team: string, lanIds: string[]) =>
  api<Team>(t, `/teams/${seg(team)}/members`, { method: "PUT", body: json({ lan_ids: lanIds }) });

export const listDefaultGrants = (t: string) => api<DefaultGrant[]>(t, "/default-grants");
export const addDefaultGrant = (t: string, team: string, role: string) =>
  api<DefaultGrant>(t, "/default-grants", { method: "POST", body: json({ team, role }) });
export const removeDefaultGrant = (t: string, id: string) => api<void>(t, `/default-grants/${id}`, { method: "DELETE" });

export const reassignOwner = (t: string, nodeId: string, lanId: string) =>
  api<void>(t, `/nodes/${nodeId}/owner`, { method: "PUT", body: json({ lan_id: lanId }) });

export const auditTrail = (t: string) => api<AuditEvent[]>(t, "/audit");

export const ROLE_NAMES: Record<string, string> = {
  OWNER: "Owner",
  ADMIN: "Admin",
  MAKER: "Maker",
  CHECKER: "Checker",
  VIEWER: "Viewer",
  APPROVER: "Approver",
  AUDITOR: "Auditor",
};
export const roleName = (code: string) => ROLE_NAMES[code] ?? code;
