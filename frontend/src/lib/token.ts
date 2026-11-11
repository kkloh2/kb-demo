/**
 * Reads the claims in the access token, to decide what the UI shows (e.g. the Administration
 * entry). Never a security check: the server verifies the token and the roles on every request.
 */

export interface TokenClaims {
  sub?: string;
  system_roles?: string[];
  org_unit_roles?: Record<string, string[]>; // department code -> roles
}

export function tokenClaims(token: string): TokenClaims {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "="));
    const json = new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
    return JSON.parse(json) as TokenClaims;
  } catch {
    return {};
  }
}

export const isSystemAdmin = (token: string) => (tokenClaims(token).system_roles ?? []).includes("SYSTEM_ADMIN");
