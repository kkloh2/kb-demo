import type { Department } from "./auth";
import { api } from "./http";

/** admin: you manage it · department: your department's · granted: shared with you */
export type KbAccess = "admin" | "department" | "granted";

export interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  department: Department;
  admin: { username: string; display_name: string } | null; // department admin named at creation
  access: KbAccess;
  updated_at: string; // ISO 8601
  favorite: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export async function listKnowledgeBases(token: string): Promise<KnowledgeBase[]> {
  const res = await fetch(`${API_BASE}/knowledge-bases`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Couldn't load knowledge bases (${res.status})`);
  return res.json();
}

export async function setFavorite(token: string, id: string, favorite: boolean): Promise<void> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${encodeURIComponent(id)}/favorite`, {
    method: favorite ? "PUT" : "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Couldn't update favourite (${res.status})`);
}

export interface NewKnowledgeBase {
  name: string;
  description: string;
  department_code: string;
  admin_lan_id: string;
}

export function createKnowledgeBase(token: string, body: NewKnowledgeBase): Promise<KnowledgeBase> {
  return api<KnowledgeBase>(token, "/knowledge-bases", { method: "POST", body: JSON.stringify(body) });
}
