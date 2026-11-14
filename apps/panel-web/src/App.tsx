"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";
import { DEFAULT_ROUTE, ROUTES, routeFromHash } from "@/routes";
import { Shell } from "@/shell/Shell";
import { Placeholder } from "@/views/Placeholder";

function subscribe(cb: () => void): () => void {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

/** Current hash route id; the server snapshot is the dashboard so the static export is stable. */
export function useRoute(): string {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash, () => `#${DEFAULT_ROUTE}`);
  return routeFromHash(hash);
}

export function App() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  const route = useRoute();
  const role = ROUTES[route]?.role ?? "user";
  useEffect(() => window.scrollTo?.(0, 0), [route]);

  // Later tasks swap Placeholder for the real screen of each route.
  const view = <Placeholder route={route} />;
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
