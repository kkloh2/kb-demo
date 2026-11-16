/** Document repositories: DOC_REPO nodes under the Doc Hub root. */

import type { Member } from "./access";
import { api } from "./http";

export interface MetadataPair {
  label: string;
  value: string;
}

export interface PersonRef {
  lan_id: string;
  display_name: string;
}

export interface DocRepo {
  id: string;
  node_id: string;
  name: string;
  description: string;
  metadata: MetadataPair[]; // every document here inherits these
  owner: PersonRef | null;
  created_by: PersonRef | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  document_count: number; // documents the caller may see
  /** What the caller can do here (for the UI; the server checks again). */
  access: {
    roles: string[];
    view: boolean;
    edit: boolean;
    manage_members: boolean;
    delete: boolean; // owner only
    transfer: boolean; // owner only
    upload: boolean; // maker
    activity: boolean; // see the repository's activity (audit.trail.view)
  };
}

export interface TeamGrant {
  team: string;
  team_name: string;
  role: string;
  from_default: boolean;
}

/** One of a repository's user groups: a name; each person in it holds their own roles there. */
export interface RepoGroup {
  id: string;
  name: string;
  default: boolean; // the default group ("Users"): holds the owner
  member_count: number;
  created_at: string;
  updated_at: string;
}

/** A repository member, with the user groups they're in and their roles in each. */
export interface RepoMember extends Member {
  groups: { id: string; name: string; roles: string[] }[];
  added_at: string | null;
  updated_at: string | null;
}

export interface Members {
  members: RepoMember[];
  team_grants: TeamGrant[];
  groups: RepoGroup[];
  grantable_roles: string[]; // roles a person can be given in a user group
}

export interface Groups {
  groups: RepoGroup[];
  grantable_roles: string[];
}

const seg = encodeURIComponent;
const json = (body: unknown) => JSON.stringify(body);

export const listDocRepos = (t: string) => api<DocRepo[]>(t, "/doc-repos");
export const listDeletedDocRepos = (t: string) => api<DocRepo[]>(t, "/doc-repos/deleted");
export const getDocRepo = (t: string, id: string) => api<DocRepo>(t, `/doc-repos/${id}`);
export const createDocRepo = (t: string, body: { name: string; description: string }) =>
  api<DocRepo>(t, "/doc-repos", { method: "POST", body: json(body) });
export const updateDocRepo = (t: string, id: string, body: { name: string; description: string }) =>
  api<DocRepo>(t, `/doc-repos/${id}`, { method: "PUT", body: json(body) });
export const setRepoMetadata = (t: string, id: string, pairs: MetadataPair[]) =>
  api<MetadataPair[]>(t, `/doc-repos/${id}/metadata`, { method: "PUT", body: json(pairs) });
export const deleteDocRepo = (t: string, id: string) => api<void>(t, `/doc-repos/${id}`, { method: "DELETE" });
export const restoreDocRepo = (t: string, id: string) => api<DocRepo>(t, `/doc-repos/${id}/restore`, { method: "POST" });

export const listMembers = (t: string, id: string) => api<Members>(t, `/doc-repos/${id}/members`);
/** Their user groups and roles here, exactly these ([] for a group takes them out of it). */
export const setMemberGroups = (t: string, id: string, lanId: string, groups: { id: string; roles: string[] }[]) =>
  api<RepoMember>(t, `/doc-repos/${id}/members/${seg(lanId)}`, { method: "PUT", body: json({ groups }) });
export const removeMember = (t: string, id: string, lanId: string) =>
  api<void>(t, `/doc-repos/${id}/members/${seg(lanId)}`, { method: "DELETE" });

export const listGroups = (t: string, id: string) => api<Groups>(t, `/doc-repos/${id}/groups`);
export const createGroup = (t: string, id: string, body: { name: string }) =>
  api<RepoGroup>(t, `/doc-repos/${id}/groups`, { method: "POST", body: json(body) });
export const updateGroup = (t: string, id: string, groupId: string, body: { name: string }) =>
  api<RepoGroup>(t, `/doc-repos/${id}/groups/${groupId}`, { method: "PUT", body: json(body) });
export const deleteGroup = (t: string, id: string, groupId: string) =>
  api<void>(t, `/doc-repos/${id}/groups/${groupId}`, { method: "DELETE" });
