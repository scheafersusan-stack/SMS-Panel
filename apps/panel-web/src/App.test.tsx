import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { HttpResponse, V1, apiError, http, server } from "@/test/msw";

const CUSTOMER = { id: "u1", username: "maryam", mfa_method: "none", roles: ["customer"], permissions: ["send.single", "wallet.pay"] };
const STAFF = { ...CUSTOMER, roles: ["staff_moderation"], permissions: ["kyc.review"] };
const notAuthenticated = () => apiError(401, "NOT_AUTHENTICATED", "دوباره وارد حساب شوید.");

describe("auth guard", () => {
  it("sends an unauthenticated visitor of a user route to the login screen", async () => {
    server.use(http.get(`${V1}/account/me`, notAuthenticated));
    window.location.hash = "#u-profile";
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe("#auth-login"));
    expect(await screen.findByRole("heading", { level: 1, name: "ورود به پنل" })).toBeInTheDocument();
  });

  it("returns to the intended route after login", async () => {
    let signedIn = false;
    server.use(
      http.get(`${V1}/account/me`, () => (signedIn ? HttpResponse.json(CUSTOMER) : notAuthenticated())),
      http.get(`${V1}/account/security`, () => HttpResponse.json({ login_notice: false, allowed_ips: [], login_hours: [] })),
      http.get(`${V1}/account/sessions`, () => HttpResponse.json({ sessions: [] })),
      http.post(`${V1}/auth/login`, () => {
        signedIn = true;
        return HttpResponse.json({ status: "ok", user: CUSTOMER });
      }),
    );
    window.location.hash = "#u-profile";
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("نام کاربری یا شماره موبایل"), "maryam");
    await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
    await user.click(screen.getByRole("button", { name: "ورود" }));
    await waitFor(() => expect(window.location.hash).toBe("#u-profile"));
    expect(await screen.findByRole("heading", { level: 1, name: "حساب و امنیت" })).toBeInTheDocument();
  });

  it("keeps the auth screens public but moves a signed-in user off login", async () => {
    server.use(http.get(`${V1}/account/me`, () => HttpResponse.json(CUSTOMER)));
    window.location.hash = "#auth-login";
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe("#u-dashboard"));
  });

  it("shows no-access for admin routes without a staff permission", async () => {
    server.use(http.get(`${V1}/account/me`, () => HttpResponse.json(CUSTOMER)));
    window.location.hash = "#a-kyc";
    render(<App />);
    expect(await screen.findByText("دسترسی ندارید")).toBeInTheDocument();
  });

  it("opens admin routes for staff", async () => {
    server.use(http.get(`${V1}/account/me`, () => HttpResponse.json(STAFF)));
    window.location.hash = "#a-kyc";
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "احراز هویت" })).toBeInTheDocument();
    expect(screen.queryByText("دسترسی ندارید")).toBeNull();
  });

  it("signs out: POSTs logout, drops the cached user and stays on login", async () => {
    let signedIn = true;
    let logouts = 0;
    server.use(
      http.get(`${V1}/account/me`, () => (signedIn ? HttpResponse.json(CUSTOMER) : notAuthenticated())),
      http.post(`${V1}/auth/logout`, () => {
        logouts += 1;
        signedIn = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    window.location.hash = "#u-dashboard";
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "منوی اصلی" });
    await user.click(within(nav).getByRole("button", { name: "خروج" }));
    await waitFor(() => expect(window.location.hash).toBe("#auth-login"));
    expect(logouts).toBe(1);
    expect(await screen.findByRole("heading", { level: 1, name: "ورود به پنل" })).toBeInTheDocument();
    // The stale signed-in user must not bounce the login screen back to the dashboard.
    await new Promise((r) => setTimeout(r, 50));
    expect(window.location.hash).toBe("#auth-login");
  });

  it("sends you to login when a screen's call answers 401 NOT_AUTHENTICATED", async () => {
    let expired = false;
    server.use(
      http.get(`${V1}/account/me`, () => (expired ? notAuthenticated() : HttpResponse.json(CUSTOMER))),
      http.get(`${V1}/account/security`, () => {
        expired = true; // the session ended after the guard's check
        return notAuthenticated();
      }),
      http.get(`${V1}/account/sessions`, () => notAuthenticated()),
    );
    window.location.hash = "#u-profile";
    render(<App />);
    await waitFor(() => expect(window.location.hash).toBe("#auth-login"));
    expect(await screen.findByRole("heading", { level: 1, name: "ورود به پنل" })).toBeInTheDocument();
  });
});
