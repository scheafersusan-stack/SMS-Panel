import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { jalaliDateTime } from "@/lib/format";
import { HttpResponse, V1, apiError, http, server } from "@/test/msw";
import { Login } from "./Login";

const USER = { id: "u1", username: "maryam", kind: "individual", first_name: "مریم", last_name: "رضایی", company_name: null, mfa_method: "none" };

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("نام کاربری یا شماره موبایل"), "maryam");
  await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
  await user.click(screen.getByRole("button", { name: "ورود" }));
  return user;
}

describe("Login", () => {
  it("goes to the dashboard after a plain login", async () => {
    let body: unknown;
    server.use(
      http.post(`${V1}/auth/login`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ status: "ok", user: USER });
      }),
    );
    render(<Login />);
    await fillAndSubmit();
    await waitFor(() => expect(window.location.hash).toBe("#u-dashboard"));
    expect(body).toEqual({ username: "maryam", password: "Abcdef1!" });
  });

  it("asks for the TOTP code and confirms with the sealed token", async () => {
    let confirm: unknown;
    server.use(
      http.post(`${V1}/auth/login`, () => HttpResponse.json({ status: "mfa_required", method: "totp", mfa_token: "tok-1" })),
      http.post(`${V1}/auth/mfa/confirm`, async ({ request }) => {
        confirm = await request.json();
        return HttpResponse.json({ status: "ok", user: USER });
      }),
    );
    render(<Login />);
    const user = await fillAndSubmit();
    const code = await screen.findByLabelText("کد تأیید");
    expect(code).toHaveAttribute("dir", "ltr");
    await user.type(code, "۱۲۳۴۵۶");
    await user.click(screen.getByRole("button", { name: "تأیید و ورود" }));
    await waitFor(() => expect(window.location.hash).toBe("#u-dashboard"));
    expect(confirm).toEqual({ mfa_token: "tok-1", code: "123456" });
  });

  it("sends the SMS code on entering the SMS step and gates the resend button", async () => {
    let sent = 0;
    server.use(
      http.post(`${V1}/auth/login`, () => HttpResponse.json({ status: "mfa_required", method: "sms", mfa_token: "tok-2" })),
      http.post(`${V1}/auth/mfa/sms/send`, async ({ request }) => {
        sent += 1;
        expect(await request.json()).toEqual({ mfa_token: "tok-2" });
        return HttpResponse.json({ resend_after: 60 }, { status: 202 });
      }),
    );
    render(<Login />);
    await fillAndSubmit();
    await screen.findByLabelText("کد تأیید");
    await waitFor(() => expect(sent).toBe(1));
    expect(await screen.findByRole("button", { name: "ارسال دوباره کد" })).toBeDisabled();
    expect(screen.getByText(/۰۱:۰۰|۰۰:۵۹/)).toBeInTheDocument();
  });

  it("returns to the credentials step when the mfa token expired", async () => {
    server.use(
      http.post(`${V1}/auth/login`, () => HttpResponse.json({ status: "mfa_required", method: "totp", mfa_token: "tok-3" })),
      http.post(`${V1}/auth/mfa/confirm`, () => apiError(401, "MFA_TOKEN_INVALID", "دوباره وارد حساب شوید.")),
    );
    render(<Login />);
    const user = await fillAndSubmit();
    await user.type(await screen.findByLabelText("کد تأیید"), "123456");
    await user.click(screen.getByRole("button", { name: "تأیید و ورود" }));
    expect(await screen.findByLabelText("رمز عبور")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("مرحلهٔ ورود منقضی شد");
  });

  it("shows OTP_INVALID on the code step without leaving it", async () => {
    server.use(
      http.post(`${V1}/auth/login`, () => HttpResponse.json({ status: "mfa_required", method: "totp", mfa_token: "tok-4" })),
      http.post(`${V1}/auth/mfa/confirm`, () => apiError(400, "OTP_INVALID", "کد واردشده درست نیست.", "/code")),
    );
    render(<Login />);
    const user = await fillAndSubmit();
    await user.type(await screen.findByLabelText("کد تأیید"), "000000");
    await user.click(screen.getByRole("button", { name: "تأیید و ورود" }));
    expect(await screen.findByText("کد واردشده درست نیست.")).toBeInTheDocument();
    expect(screen.getByLabelText("کد تأیید")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the lock time in Jalali", async () => {
    const until = "2026-11-14T10:30:00+00:00";
    server.use(http.post(`${V1}/auth/login`, () => apiError(423, "ACCOUNT_LOCKED", until)));
    render(<Login />);
    await fillAndSubmit();
    expect(await screen.findByText(`حساب شما تا ${jalaliDateTime(until)} قفل است؛ پس از آن دوباره تلاش کنید.`)).toBeInTheDocument();
  });

  it.each([
    [401, "INVALID_CREDENTIALS", "نام کاربری یا رمز عبور درست نیست."],
    [403, "LOGIN_IP_NOT_ALLOWED", "از این نشانی IP"],
    [403, "LOGIN_OUTSIDE_HOURS", "در این ساعت"],
    [403, "ACCOUNT_INACTIVE", "غیرفعال"],
    [403, "ACCOUNT_EXPIRED", "پایان رسیده"],
    [429, "RATE_LIMITED", "تعداد تلاش‌ها"],
  ])("explains %i %s", async (status, code, fragment) => {
    server.use(http.post(`${V1}/auth/login`, () => apiError(status, code, "x")));
    render(<Login />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent(fragment);
  });

  it("falls back to the server detail for unknown codes", async () => {
    server.use(http.post(`${V1}/auth/login`, () => apiError(500, "WEIRD", "مشکل ناشناخته")));
    render(<Login />);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("مشکل ناشناخته");
  });

  it("links to registration and password recovery", () => {
    render(<Login />);
    expect(screen.getByRole("link", { name: /ثبت‌نام/ })).toHaveAttribute("href", "#auth-register");
    expect(screen.getByRole("link", { name: /فراموش/ })).toHaveAttribute("href", "#auth-forgot");
  });
});
