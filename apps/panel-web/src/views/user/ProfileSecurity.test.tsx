import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithClient } from "@/test/render";
import { HttpResponse, V1, apiError, http, server } from "@/test/msw";
import { ProfileSecurity } from "./ProfileSecurity";

const ME = { id: "u1", username: "maryam", mobile: "09123456789", kind: "person", mfa_method: "none", roles: ["customer"], permissions: [] };
const SECURITY = { login_notice: false, allowed_ips: [], login_hours: [] };
const SESSIONS = {
  sessions: [
    { id: "s-1", ip: "10.0.0.1", user_agent: "Chrome", created_at: "2026-11-14T08:00:00Z", last_seen_at: "2026-11-14T09:00:00Z", expires_at: "2026-12-14T08:00:00Z", current: true, impersonated: false },
    { id: "s-2", ip: "10.0.0.2", user_agent: "Firefox", created_at: "2026-11-10T08:00:00Z", last_seen_at: "2026-11-12T09:00:00Z", expires_at: "2026-12-10T08:00:00Z", current: false, impersonated: false },
  ],
};

function base(me: Partial<typeof ME> = {}) {
  server.use(
    http.get(`${V1}/account/me`, () => HttpResponse.json({ ...ME, ...me })),
    http.get(`${V1}/account/security`, () => HttpResponse.json(SECURITY)),
    http.get(`${V1}/account/sessions`, () => HttpResponse.json(SESSIONS)),
  );
}

describe("ProfileSecurity", () => {
  it("changes the password and reports success", async () => {
    base();
    let body: unknown;
    server.use(
      http.post(`${V1}/account/password`, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.type(await screen.findByLabelText("رمز عبور فعلی"), "Oldpass1!");
    await user.type(screen.getByLabelText("رمز عبور جدید"), "Newpass1!");
    await user.click(screen.getByRole("button", { name: "تغییر رمز عبور" }));
    expect(await screen.findByText("رمز عبور تغییر کرد.")).toBeInTheDocument();
    expect(body).toEqual({ current_password: "Oldpass1!", new_password: "Newpass1!" });
  });

  it("shows a wrong current password on its field", async () => {
    base();
    server.use(http.post(`${V1}/account/password`, () => apiError(400, "CURRENT_PASSWORD_INVALID", "x", "/current_password")));
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.type(await screen.findByLabelText("رمز عبور فعلی"), "bad");
    await user.type(screen.getByLabelText("رمز عبور جدید"), "Newpass1!");
    await user.click(screen.getByRole("button", { name: "تغییر رمز عبور" }));
    expect(await screen.findByText("رمز عبور فعلی درست نیست.")).toBeInTheDocument();
    expect(screen.getByLabelText("رمز عبور فعلی")).toHaveAttribute("aria-invalid", "true");
  });

  it("enables TOTP with a QR, the secret in LTR, the code and the account password", async () => {
    base();
    let enable: unknown;
    server.use(
      http.post(`${V1}/account/mfa/totp/setup`, () => HttpResponse.json({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/Payamakyar:maryam?secret=JBSWY3DPEHPK3PXP&issuer=Payamakyar" })),
      http.post(`${V1}/account/mfa/totp/enable`, async ({ request }) => {
        enable = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.click(await screen.findByRole("button", { name: "فعال‌سازی با برنامهٔ احراز هویت" }));
    const qr = await screen.findByRole("img", { name: "کد QR برنامهٔ احراز هویت" });
    expect(qr.getAttribute("src")).toMatch(/^data:image\/gif;base64,/);
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toHaveAttribute("dir", "ltr");
    await user.type(screen.getByLabelText("کد برنامه"), "۱۲۳۴۵۶");
    await user.type(screen.getByLabelText("رمز عبور حساب"), "Mypass1!");
    await user.click(screen.getByRole("button", { name: "تأیید و فعال‌سازی" }));
    expect(await screen.findByText("ورود دومرحله‌ای با برنامهٔ احراز هویت فعال شد.")).toBeInTheDocument();
    expect(enable).toEqual({ code: "123456", password: "Mypass1!" });
  });

  it("enables SMS 2FA with the account password", async () => {
    base();
    let body: unknown;
    server.use(
      http.post(`${V1}/account/mfa/sms/enable`, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.click(await screen.findByRole("button", { name: "فعال‌سازی با پیامک" }));
    await user.type(screen.getByLabelText("رمز عبور حساب"), "Mypass1!");
    await user.click(screen.getByRole("button", { name: "فعال‌سازی" }));
    expect(await screen.findByText("ورود دومرحله‌ای با پیامک فعال شد.")).toBeInTheDocument();
    expect(body).toEqual({ password: "Mypass1!" });
  });

  it("disables an active second factor with the password", async () => {
    base({ mfa_method: "sms" });
    let body: unknown;
    server.use(
      http.post(`${V1}/account/mfa/disable`, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    expect(await screen.findByText("فعال: کد پیامکی")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "غیرفعال‌سازی" }));
    await user.type(screen.getByLabelText("رمز عبور حساب"), "Mypass1!");
    await user.click(screen.getByRole("button", { name: "تأیید غیرفعال‌سازی" }));
    expect(await screen.findByText("ورود دومرحله‌ای غیرفعال شد.")).toBeInTheDocument();
    expect(body).toEqual({ password: "Mypass1!" });
  });

  it("saves notice, IPs and login hours (0 = Saturday)", async () => {
    base();
    let body: { login_notice: boolean } | undefined;
    server.use(
      http.put(`${V1}/account/security`, async ({ request }) => {
        body = (await request.json()) as { login_notice: boolean };
        return HttpResponse.json(body);
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.click(await screen.findByLabelText("اطلاع‌رسانی پیامکی هر ورود"));
    await user.type(screen.getByLabelText("نشانی IP یا محدوده (CIDR)"), "۱۹۲.۱۶۸.۱.۰/۲۴");
    await user.click(screen.getByRole("button", { name: "افزودن نشانی" }));
    await user.click(screen.getByRole("button", { name: "افزودن بازه" }));
    await user.click(screen.getByRole("button", { name: "شنبه" }));
    await user.click(screen.getByRole("button", { name: "جمعه" }));
    await user.clear(screen.getByLabelText("ساعت شروع بازهٔ ۱"));
    await user.type(screen.getByLabelText("ساعت شروع بازهٔ ۱"), "۰۸:۰۰");
    await user.clear(screen.getByLabelText("ساعت پایان بازهٔ ۱"));
    await user.type(screen.getByLabelText("ساعت پایان بازهٔ ۱"), "18:30");
    await user.click(screen.getByRole("button", { name: "ذخیرهٔ محدودیت‌ها" }));
    expect(await screen.findByText("محدودیت‌های ورود ذخیره شد.")).toBeInTheDocument();
    expect(body).toEqual({ login_notice: true, allowed_ips: ["192.168.1.0/24"], login_hours: [{ days: [0, 6], from: "08:00", to: "18:30" }] });
  });

  it("shows WOULD_LOCK_YOU_OUT with its explanation", async () => {
    base();
    server.use(http.put(`${V1}/account/security`, () => apiError(422, "WOULD_LOCK_YOU_OUT", "نشانی فعلی شما در فهرست مجاز نیست.", "/allowed_ips")));
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    await user.type(await screen.findByLabelText("نشانی IP یا محدوده (CIDR)"), "203.0.113.5");
    await user.click(screen.getByRole("button", { name: "افزودن نشانی" }));
    await user.click(screen.getByRole("button", { name: "ذخیرهٔ محدودیت‌ها" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("این تنظیم دسترسی خود شما را می‌بندد");
    expect(alert).toHaveTextContent("نشانی فعلی شما در فهرست مجاز نیست.");
  });

  it("lists sessions and removes a revoked one", async () => {
    base();
    let revoked = false;
    server.use(
      http.get(`${V1}/account/sessions`, () => HttpResponse.json({ sessions: revoked ? SESSIONS.sessions.slice(0, 1) : SESSIONS.sessions })),
      http.delete(`${V1}/account/sessions/s-2`, () => {
        revoked = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithClient(<ProfileSecurity />);
    const list = await screen.findByRole("list", { name: "نشست‌های فعال" });
    expect(within(list).getByText("فعلی")).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /بستن نشست 10\.0\.0\.1/ })).toBeNull();
    await user.click(within(list).getByRole("button", { name: /بستن نشست 10\.0\.0\.2/ }));
    await waitFor(() => expect(screen.queryByText("10.0.0.2")).toBeNull());
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
  });
});
