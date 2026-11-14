import { NAV } from "./nav";

export type Role = "user" | "admin" | "auth";

export interface RouteDef {
  id: string;
  title: string;
  role: Role;
  /** Nav item that stays highlighted while this (detail) route is open. */
  navParent?: string;
}

export const DEFAULT_ROUTE = "u-dashboard";

export function roleOf(id: string): Role {
  if (id.startsWith("auth-")) return "auth";
  return id.startsWith("a-") ? "admin" : "user";
}

const list: RouteDef[] = [];
for (const r of ["user", "admin"] as const)
  for (const s of NAV[r]) for (const i of s.items) list.push({ id: i.id, title: i.label, role: r });

// Detail screens that live under a nav item, plus the auth screens (prototype S[...] keys).
list.push(
  { id: "u-batch", title: "جزئیات یک ارسال", role: "user", navParent: "u-outbox" },
  { id: "u-ticket", title: "جزئیات تیکت", role: "user", navParent: "u-tickets" },
  { id: "a-user", title: "جزئیات کاربر", role: "admin", navParent: "a-users" },
  { id: "auth-login", title: "ورود به پنل", role: "auth" },
  { id: "auth-register", title: "ثبت‌نام", role: "auth" },
  { id: "auth-forgot", title: "بازیابی رمز عبور", role: "auth" },
);

export const ROUTES: Record<string, RouteDef> = Object.fromEntries(list.map((r) => [r.id, r]));

/** Resolves a location hash such as "#u-send" to a known route id, else the dashboard. */
export function routeFromHash(hash: string): string {
  const id = hash.replace(/^#/, "");
  return id in ROUTES ? id : DEFAULT_ROUTE;
}
