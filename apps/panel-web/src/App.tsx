"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";
import { DEFAULT_ROUTE, ROUTES, routeFromHash } from "@/routes";
import { Shell } from "@/shell/Shell";
import { ForgotPassword } from "@/views/auth/ForgotPassword";
import { Login } from "@/views/auth/Login";
import { Register } from "@/views/auth/Register";
import { Placeholder } from "@/views/Placeholder";
import { ProfileSecurity } from "@/views/user/ProfileSecurity";

function subscribe(cb: () => void): () => void {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

/** Current hash route id; the server snapshot is the dashboard so the static export is stable. */
export function useRoute(): string {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash, () => `#${DEFAULT_ROUTE}`);
  return routeFromHash(hash);
}

/** The real screen of a route; routes whose task has not landed yet show the placeholder. */
function screenFor(route: string) {
  switch (route) {
    case "auth-login":
      return <Login />;
    case "auth-register":
      return <Register />;
    case "auth-forgot":
      return <ForgotPassword />;
    case "u-profile":
      return <ProfileSecurity />;
    default:
      return <Placeholder route={route} />;
  }
}

export function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const route = useRoute();
  const role = ROUTES[route]?.role ?? "user";
  useEffect(() => window.scrollTo?.(0, 0), [route]);

  const view = screenFor(route);
  return (
    <QueryClientProvider client={client}>
      {role === "auth" ? (
        <div className="auth-wrap">
          <main className="content">{view}</main>
        </div>
      ) : (
        <Shell role={role} route={route}>
          {view}
        </Shell>
      )}
    </QueryClientProvider>
  );
}
