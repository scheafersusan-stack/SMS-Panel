import { useQuery } from "@tanstack/react-query";
import { api, V1 } from "./api";

export interface Me {
  id: string;
  username: string;
  mfa_method: "none" | "totp" | "sms";
  roles: string[];
  permissions: string[];
}

export const ME_KEY = ["account", "me"] as const;

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: () => api<Me>("GET", `${V1}/account/me`) });
}

/** Permissions of the customer side; anything else is a staff permission. */
const CUSTOMER_SIDE = new Set([
  "send.single",
  "send.bulk",
  "send.pattern",
  "contacts.manage",
  "templates.manage",
  "inbox.view",
  "rules.manage",
  "api.manage",
  "wallet.pay",
  "tickets.create",
  "resellers.subusers",
]);

export function isStaff(me: Me): boolean {
  return me.permissions.some((p) => !CUSTOMER_SIDE.has(p));
}

/** The route a guarded screen redirected from, so login can send the user back. */
let returnTo: string | null = null;
export const rememberReturn = (route: string): void => {
  returnTo = route;
};
export const clearReturn = (): void => {
  returnTo = null;
};

/** Where to go after signing in: the remembered route, else the dashboard. */
export function afterLoginRoute(): string {
  const r = returnTo ?? "u-dashboard";
  returnTo = null;
  return r;
}
