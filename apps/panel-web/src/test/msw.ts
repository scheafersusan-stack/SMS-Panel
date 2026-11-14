import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { V1 } from "@/lib/api";

export { http, HttpResponse, V1 };

/** The shared MSW server; tests install per-case handlers with `server.use(...)`. */
export const server = setupServer();

/** An API error response in the server's envelope. */
export function apiError(status: number, code: string, detail = "", pointer: string | null = null, title = "خطا") {
  return HttpResponse.json({ error: { code, title, detail, source: pointer ? { pointer } : null } }, { status });
}
