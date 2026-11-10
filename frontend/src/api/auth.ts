export interface LoginRequest {
  username: string;
  password: string;
}

export interface Department {
  code: string;
  name: string;
}

export interface User {
  username: string; // LAN ID
  display_name: string;
  title: string; // job title, e.g. "Data Analyst"
  email: string;
  department: Department | null; // null for system admins
  roles: string[]; // e.g. ["checker", "viewer"]
  permissions: string[]; // e.g. ["documents:approve", ...]
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export async function login(body: LoginRequest): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d) => d.detail as string)
      .catch(() => null);
    throw new Error(detail ?? `Sign-in failed (${res.status})`);
  }
  return res.json();
}

export async function me(token: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Session expired");
  return res.json();
}

/** End the session on the server. Best effort: the UI signs out either way. */
export async function logout(token: string): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined);
}
