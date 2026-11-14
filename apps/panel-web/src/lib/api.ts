export interface ErrorEnvelope {
  error: { code: string; title: string; detail: string; source: { pointer: string } | null };
}

/** Every user-panel API path starts here. */
export const V1 = "/panel/web/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly pointer: string | null;
  /** Seconds from the Retry-After header, when the server sent one. */
  readonly retryAfter: number | null;

  constructor(status: number, code: string, title: string, detail: string, pointer: string | null = null, retryAfter: number | null = null) {
    super(`${code}: ${title}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.title = title;
    this.detail = detail;
    this.pointer = pointer;
    this.retryAfter = retryAfter;
  }
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export function csrfToken(): string | null {
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith("pk_csrf=")) return decodeURIComponent(part.slice("pk_csrf=".length));
  }
  return null;
}

function isEnvelope(v: unknown): v is ErrorEnvelope {
  if (typeof v !== "object" || v === null || !("error" in v)) return false;
  const e = v.error;
  return typeof e === "object" && e !== null && typeof (e as { code?: unknown }).code === "string";
}

/** Same-origin JSON call. Paths start with /panel/web/v1/ (user) or /panel/admin/v1/ (admin). */
export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const verb = method.toUpperCase();
  const headers = new Headers({ Accept: "application/json" });
  const init: RequestInit = { method: verb, headers, credentials: "same-origin" };
  if (!SAFE.has(verb)) {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "اتصال برقرار نشد", "اتصال اینترنت خود را بررسی و دوباره تلاش کنید.");
  }
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let parsed: unknown;
    try {
      parsed = await res.json();
    } catch {
      parsed = undefined;
    }
    if (isEnvelope(parsed)) {
      const e = parsed.error;
      const wait = Number(res.headers.get("Retry-After"));
      throw new ApiError(res.status, e.code, e.title, e.detail, e.source?.pointer ?? null, Number.isInteger(wait) && wait > 0 ? wait : null);
    }
    throw new ApiError(res.status, `HTTP_${res.status}`, "پاسخ نامعتبر از سرور", "لطفاً دوباره تلاش کنید.");
  }
  return await (res.json() as Promise<T>);
}
