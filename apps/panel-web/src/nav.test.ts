import { describe, expect, it } from "vitest";
import { NAV } from "./nav";
import { ROUTES, roleOf } from "./routes";

const ids = (r: string) => Object.keys(ROUTES).filter((k) => k.startsWith(r));

describe("NAV and ROUTES", () => {
  it("has 24 user and 18 admin routes plus 3 auth routes", () => {
    expect(ids("u-")).toHaveLength(24);
    expect(ids("a-")).toHaveLength(18);
    expect(ids("auth-").sort()).toEqual(["auth-forgot", "auth-login", "auth-register"]);
  });
  it("NAV lists the prototype sections", () => {
    const count = (r: "user" | "admin") => NAV[r].reduce((n, s) => n + s.items.length, 0);
    expect(count("user")).toBe(22);
    expect(count("admin")).toBe(17);
    expect(NAV.user.map((s) => s.label)).toEqual(["", "ارسال", "پیام‌ها", "مخاطبان", "ابزارها", "حساب"]);
    expect(NAV.admin[1]?.items[0]).toEqual({ id: "a-kyc", label: "احراز هویت", icon: "file", count: "۷" });
  });
  it("every nav item is a route with the same title", () => {
    for (const r of ["user", "admin"] as const)
      for (const s of NAV[r])
        for (const it of s.items) expect(ROUTES[it.id]?.title).toBe(it.label);
  });
  it("derives the role from the id", () => {
    expect(roleOf("a-users")).toBe("admin");
    expect(roleOf("u-send")).toBe("user");
    expect(roleOf("auth-login")).toBe("auth");
  });
});
