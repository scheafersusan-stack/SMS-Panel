import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HttpResponse, V1, apiError, http, server } from "@/test/msw";
import { ForgotPassword } from "./ForgotPassword";

describe("ForgotPassword", () => {
  it("requests a code, then sets the new password", async () => {
    let complete: unknown;
    server.use(
      http.post(`${V1}/auth/reset/start`, () => HttpResponse.json({ challenge_id: "r-1", resend_after: 60 }, { status: 202 })),
      http.post(`${V1}/auth/reset/complete`, async ({ request }) => {
        complete = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    render(<ForgotPassword />);
    await user.type(screen.getByLabelText("شماره موبایل"), "۰۹۱۲۳۴۵۶۷۸۹");
    await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
    await user.type(await screen.findByLabelText("کد تأیید"), "123456");
    await user.type(screen.getByLabelText("رمز عبور جدید"), "Newpass1!");
    await user.click(screen.getByRole("button", { name: "تغییر رمز عبور" }));
    expect(await screen.findByText(/رمز عبور شما تغییر کرد/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ورود به حساب" })).toHaveAttribute("href", "#auth-login");
    expect(complete).toEqual({ challenge_id: "r-1", code: "123456", new_password: "Newpass1!" });
  });

  it("shows the single OTP_INVALID message on the code field", async () => {
    server.use(
      http.post(`${V1}/auth/reset/start`, () => HttpResponse.json({ challenge_id: "r-2", resend_after: 60 }, { status: 202 })),
      http.post(`${V1}/auth/reset/complete`, () => apiError(400, "OTP_INVALID", "کد نامعتبر یا منقضی است؛ کد جدید بگیرید.", "/code")),
    );
    const user = userEvent.setup();
    render(<ForgotPassword />);
    await user.type(screen.getByLabelText("شماره موبایل"), "09123456789");
    await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
    await user.type(await screen.findByLabelText("کد تأیید"), "000000");
    await user.type(screen.getByLabelText("رمز عبور جدید"), "Newpass1!");
    await user.click(screen.getByRole("button", { name: "تغییر رمز عبور" }));
    expect(await screen.findByText("کد نامعتبر یا منقضی است؛ کد جدید بگیرید.")).toBeInTheDocument();
    expect(screen.getByLabelText("کد تأیید")).toHaveAttribute("aria-invalid", "true");
  });

  it("lists password problems on the new password field", async () => {
    server.use(
      http.post(`${V1}/auth/reset/start`, () => HttpResponse.json({ challenge_id: "r-3", resend_after: 60 }, { status: 202 })),
      http.post(`${V1}/auth/reset/complete`, () => apiError(422, "PASSWORD_WEAK", "NO_LOWER,NO_DIGIT", "/new_password")),
    );
    const user = userEvent.setup();
    render(<ForgotPassword />);
    await user.type(screen.getByLabelText("شماره موبایل"), "09123456789");
    await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
    await user.type(await screen.findByLabelText("کد تأیید"), "123456");
    await user.type(screen.getByLabelText("رمز عبور جدید"), "ABC!!!!!");
    await user.click(screen.getByRole("button", { name: "تغییر رمز عبور" }));
    const msg = await screen.findByText(/رمز عبور باید شامل این موارد باشد/);
    expect(msg).toHaveTextContent("یک حرف کوچک لاتین");
    expect(msg).toHaveTextContent("یک رقم");
  });
});
