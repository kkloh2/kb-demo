/**
 * Reads the claims in the access token. Never a security check: the server verifies the token and
 * checks permissions on every request. Pages use GET /api/me/access for what to show.
 */

export interface TokenClaims {
  sub?: string;
  system_roles?: Record<string, string[]>; // roles at each system's root, e.g. {"DOC_HUB": ["VIEWER"]}
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
