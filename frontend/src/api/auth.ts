export interface LoginRequest {
  username: string; // LAN ID
  password: string;
}

export interface User {
  username: string; // LAN ID
  display_name: string;
  email: string;
  department: string; // from the directory, e.g. "Risk Management"
  title: string; // job title, e.g. "Data Analyst"
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number; // seconds
  user: User;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function errorDetail(res: Response): Promise<string | null> {
  return res
    .json()
    .then((d) => (typeof d.detail === "string" ? d.detail : null))
    .catch(() => null);
}

export async function login(body: LoginRequest): Promise<LoginResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach Data Hub. Check your connection and try again.");
  }
  if (!res.ok) throw new Error((await errorDetail(res)) ?? `Sign-in failed (${res.status})`);
  return res.json();
}

/** The signed-in user. Throws with the server's message if the session is no longer valid. */
export async function me(token: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error((await errorDetail(res)) ?? "Session ended. Please sign in again.");
  return res.json();
}

/** End the session on the server. Best effort: the UI signs out either way. */
export async function logout(token: string): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => undefined);
}
