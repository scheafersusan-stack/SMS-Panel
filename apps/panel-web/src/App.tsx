"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { errorText } from "@/lib/errors";
import { ME_KEY, afterLoginRoute, isStaff, rememberReturn, useMe } from "@/lib/session";
import { Alert, EmptyState, Skeleton } from "@/ui/Feedback";
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

/** Routes whose screen needs a signed-in user (everything but the auth screens). */
function Guarded({ route, role, children }: { route: string; role: "user" | "admin"; children: ReactNode }) {
  const client = useQueryClient();
  const me = useMe();
  const unauthenticated = me.isError && !me.isFetching && me.error instanceof ApiError && me.error.status === 401;

  // A stale 401 (from before a sign-in) is re-checked whenever the route changes.
  useEffect(() => {
    if (client.getQueryState(ME_KEY)?.status === "error") void client.invalidateQueries({ queryKey: ME_KEY });
  }, [route, client]);
  useEffect(() => {
    if (unauthenticated) {
      rememberReturn(route);
      window.location.hash = "#auth-login";
    }
  }, [unauthenticated, route]);

  let body: ReactNode;
  if (me.data) {
    body = role === "admin" && !isStaff(me.data) ? <EmptyState title="دسترسی ندارید" icon="alert">شما به این بخش دسترسی ندارید.</EmptyState> : children;
  } else if (me.isError && !me.isFetching && !unauthenticated) {
    body = <Alert tone="danger">{errorText(me.error)}</Alert>;
  } else {
    body = <Skeleton height={160} />;
  }
  return (
    <Shell role={role} route={route}>
      {body}
    </Shell>
  );
}

/** On the auth screens a signed-in visitor is sent on to the dashboard. */
function AuthRoute({ route, children }: { route: string; children: ReactNode }) {
  const me = useMe();
  const signedIn = Boolean(me.data);
  useEffect(() => {
    if (signedIn && (route === "auth-login" || route === "auth-register")) window.location.hash = `#${afterLoginRoute()}`;
  }, [signedIn, route]);
  return (
    <div className="auth-wrap">
      <main className="content">{children}</main>
    </div>
  );
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
        <AuthRoute route={route}>{view}</AuthRoute>
      ) : (
        <Guarded route={route} role={role}>
          {view}
        </Guarded>
      )}
    </QueryClientProvider>
  );
}
