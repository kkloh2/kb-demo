/** Source systems, their hierarchies and their roots' groups (platform admins). */

import type { Member } from "./access";
import { api } from "./http";

export interface RootGroup {
  type: "ADMINS" | "USERS" | string;
  name: string;
  roles: string[]; // roles its members may hold
  auto_join_role: string | null; // everyone joins with this role
  members: (Member & { added_at: string | null; updated_at: string | null })[];
}

export interface SourceSystem {
  code: string;
  name: string;
  status: string;
  created_at: string;
  last_updated: string; // the latest change to the system, its hierarchy, or who is in its root groups
  hierarchy: {
    name: string;
    levels: string[]; // root first, e.g. ["ROOT", "DOC_REPO"]
    root_node_id: string;
    child_count: number;
    groups: RootGroup[];
  } | null;
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const listSources = (t: string) => api<SourceSystem[]>(t, "/sources");
export const createSource = (t: string, code: string, name: string) =>
  api<SourceSystem>(t, "/sources", { method: "POST", body: json({ code, name }) });
export const createHierarchy = (t: string, code: string, name = "", levels?: string[]) =>
  api<SourceSystem>(t, `/sources/${seg(code)}/hierarchy`, { method: "POST", body: json({ name, levels }) });
export const setGroupRoles = (t: string, code: string, group: string, lanId: string, roles: string[]) =>
  api<SourceSystem>(t, `/sources/${seg(code)}/groups/${seg(group)}/members/${seg(lanId)}`, {
    method: "PUT",
    body: json({ roles }),
  });
export const removeFromGroup = (t: string, code: string, group: string, lanId: string) =>
  api<void>(t, `/sources/${seg(code)}/groups/${seg(group)}/members/${seg(lanId)}`, { method: "DELETE" });
