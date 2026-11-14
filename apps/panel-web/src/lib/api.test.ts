import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function mockFetch(res: Response) {
  const fn = vi.fn().mockResolvedValue(res);
  vi.stubGlobal("fetch", fn);
  return fn;
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "pk_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

describe("api", () => {
  it("sends same-origin GET without CSRF header", async () => {
    const fn = mockFetch(Response.json({ ok: 1 }));
    await expect(api<{ ok: number }>("GET", "/panel/web/v1/me")).resolves.toEqual({ ok: 1 });
    const [url, init] = fn.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/panel/web/v1/me");
    expect(init.credentials).toBe("same-origin");
    expect(new Headers(init.headers).has("X-CSRF-Token")).toBe(false);
  });
  it("sends CSRF token and JSON body on unsafe methods", async () => {
    document.cookie = "pk_csrf=tok%20123; path=/";
    const fn = mockFetch(Response.json({}));
    await api("POST", "/panel/admin/v1/users", { a: 1 });
    const [, init] = fn.mock.calls[0] as [string, RequestInit];
    const h = new Headers(init.headers);
    expect(h.get("X-CSRF-Token")).toBe("tok 123");
    expect(h.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });
  it("returns undefined on 204", async () => {
    mockFetch(new Response(null, { status: 204 }));
    await expect(api("DELETE", "/panel/web/v1/x")).resolves.toBeUndefined();
  });
  it("parses the error envelope", async () => {
    mockFetch(
      Response.json(
        { error: { code: "VALIDATION", title: "t", detail: "d", source: { pointer: "/mobile" } } },
        { status: 422 },
      ),
    );
    const err = await api("POST", "/panel/web/v1/x", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 422, code: "VALIDATION", title: "t", detail: "d", pointer: "/mobile" });
  });
  it("uses a null pointer when source is null", async () => {
    mockFetch(Response.json({ error: { code: "X", title: "t", detail: "d", source: null } }, { status: 400 }));
    await expect(api("GET", "/panel/web/v1/x")).rejects.toMatchObject({ pointer: null });
  });
  it("maps non-JSON errors to HTTP_<status>", async () => {
    mockFetch(new Response("<html>bad</html>", { status: 502 }));
    await expect(api("GET", "/panel/web/v1/x")).rejects.toMatchObject({ status: 502, code: "HTTP_502" });
  });
  it("maps network failure to NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    await expect(api("GET", "/panel/web/v1/x")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });
});
