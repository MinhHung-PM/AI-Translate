// Thin fetch wrapper. All calls are same-origin (/api/v1 is proxied by Next.js),
// cookies are HttpOnly, and the CSRF token lives only in memory — never in
// localStorage/sessionStorage.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(`/api/v1${path}${buildQuery(query)}`, {
    method,
    headers,
    body: payload,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data: unknown = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (isJson && typeof data === "object" && data && "error" in data
      ? (data as { error: { code: string; message: string; details?: Record<string, unknown> } }).error
      : { code: "http_error", message: res.statusText }) as { code: string; message: string; details?: Record<string, unknown> };
    throw new ApiError(res.status, err.code, err.message, err.details ?? {});
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** Download a file from an authenticated GET endpoint without exposing tokens in URLs. */
export async function downloadFile(path: string, query?: Query): Promise<void> {
  const res = await fetch(`/api/v1${path}${buildQuery(query)}`, { credentials: "same-origin" });
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = ((await res.json()) as { error: { message: string } }).error.message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, "download_failed", message);
  }
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
