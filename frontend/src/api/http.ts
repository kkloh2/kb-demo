const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Authenticated JSON request. Throws ApiError with the server's message on failure. */
export async function api<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      // JSON bodies are strings; FormData sets its own multipart boundary.
      ...(typeof init.body === "string" ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((d) => (typeof d.detail === "string" ? d.detail : d.detail?.[0]?.msg))
      .catch(() => null);
    throw new ApiError(res.status, detail ?? `Request failed (${res.status})`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}
