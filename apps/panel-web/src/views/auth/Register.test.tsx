import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HttpResponse, V1, apiError, http, server } from "@/test/msw";
import { Register } from "./Register";

async function toCodeStep(user: ReturnType<typeof userEvent.setup>, mobile = "09123456789") {
  await user.type(screen.getByLabelText("شماره موبایل"), mobile);
  await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
  return screen.findByLabelText("کد تأیید");
}

describe("Register", () => {
  it("walks the three steps for an individual and lands on the dashboard", async () => {
    let start: unknown;
    let complete: unknown;
    server.use(
      http.post(`${V1}/auth/register/start`, async ({ request }) => {
        start = await request.json();
        return HttpResponse.json({ challenge_id: "c-1", resend_after: 60 }, { status: 202 });
      }),
      http.post(`${V1}/auth/register/complete`, async ({ request }) => {
        complete = await request.json();
        return HttpResponse.json({ user_id: "u-1" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    render(<Register />);
    expect(screen.getByRole("button", { name: "حقیقی" })).toHaveAttribute("aria-pressed", "true");
    const code = await toCodeStep(user, "۰۹۱۲۳۴۵۶۷۸۹");
    expect(start).toEqual({ mobile: "09123456789", kind: "individual" });
    await user.type(code, "۱۲۳۴۵۶");
    await user.click(screen.getByRole("button", { name: "ادامه" }));
    await user.type(await screen.findByLabelText("نام"), "مریم");
    await user.type(screen.getByLabelText("نام خانوادگی"), "رضایی");
    await user.type(screen.getByLabelText("نام کاربری"), "maryam");
    await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    await waitFor(() => expect(window.location.hash).toBe("#u-dashboard"));
    expect(complete).toEqual({
      challenge_id: "c-1",
      code: "123456",
      username: "maryam",
      password: "Abcdef1!",
      first_name: "مریم",
      last_name: "رضایی",
    });
  });

  it("asks for the company name when the account is a company", async () => {
    let start: { kind?: string } = {};
    let complete: Record<string, unknown> = {};
    server.use(
      http.post(`${V1}/auth/register/start`, async ({ request }) => {
        start = (await request.json()) as { kind?: string };
        return HttpResponse.json({ challenge_id: "c-2", resend_after: 60 }, { status: 202 });
      }),
      http.post(`${V1}/auth/register/complete`, async ({ request }) => {
        complete = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ user_id: "u-2" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    render(<Register />);
    await user.click(screen.getByRole("button", { name: "حقوقی" }));
    const code = await toCodeStep(user);
    expect(start.kind).toBe("company");
    await user.type(code, "123456");
    await user.click(screen.getByRole("button", { name: "ادامه" }));
    await user.type(await screen.findByLabelText("نام شرکت"), "فروشگاه آبان");
    expect(screen.queryByLabelText("نام خانوادگی")).toBeNull();
    await user.type(screen.getByLabelText("نام نماینده"), "مریم");
    await user.type(screen.getByLabelText("نام کاربری"), "aban");
    await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    await waitFor(() => expect(window.location.hash).toBe("#u-dashboard"));
    expect(complete.company_name).toBe("فروشگاه آبان");
    expect(complete.last_name).toBeUndefined();
  });

  it("disables resend until the countdown ends, then requests a new code", async () => {
    let starts = 0;
    server.use(
      http.post(`${V1}/auth/register/start`, () => {
        starts += 1;
        return HttpResponse.json({ challenge_id: `c-${starts}`, resend_after: 1 }, { status: 202 });
      }),
    );
    const user = userEvent.setup();
    render(<Register />);
    await toCodeStep(user);
    const resend = screen.getByRole("button", { name: "ارسال دوباره کد" });
    expect(resend).toBeDisabled();
    expect(screen.getByText(/ارسال دوباره کد تا ۰۰:۰۱ دیگر/)).toBeInTheDocument();
    await waitFor(() => expect(resend).toBeEnabled(), { timeout: 4000 });
    await user.click(resend);
    await waitFor(() => expect(starts).toBe(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "ارسال دوباره کد" })).toBeDisabled());
  });

  it("shows taken mobile numbers on the mobile field", async () => {
    server.use(http.post(`${V1}/auth/register/start`, () => apiError(409, "MOBILE_TAKEN", "با این شماره وارد شوید.", "/mobile")));
    const user = userEvent.setup();
    render(<Register />);
    await user.type(screen.getByLabelText("شماره موبایل"), "09123456789");
    await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
    expect(await screen.findByText(/این شماره قبلاً ثبت شده است/)).toBeInTheDocument();
    expect(screen.getByLabelText("شماره موبایل")).toHaveAttribute("aria-invalid", "true");
  });

  it("rejects a malformed mobile without calling the server", async () => {
    const user = userEvent.setup();
    render(<Register />);
    await user.type(screen.getByLabelText("شماره موبایل"), "123");
    await user.click(screen.getByRole("button", { name: "ارسال کد تأیید" }));
    expect(await screen.findByText("شمارهٔ موبایل معتبر نیست.")).toBeInTheDocument();
  });

  async function toDetailsStep(user: ReturnType<typeof userEvent.setup>) {
    server.use(http.post(`${V1}/auth/register/start`, () => HttpResponse.json({ challenge_id: "c-9", resend_after: 60 }, { status: 202 })));
    const code = await toCodeStep(user);
    await user.type(code, "123456");
    await user.click(screen.getByRole("button", { name: "ادامه" }));
    await user.type(await screen.findByLabelText("نام"), "مریم");
    await user.type(screen.getByLabelText("نام خانوادگی"), "رضایی");
    await user.type(screen.getByLabelText("نام کاربری"), "maryam");
  }

  it("lists every password problem in Persian", async () => {
    server.use(http.post(`${V1}/auth/register/complete`, () => apiError(422, "PASSWORD_WEAK", "TOO_SHORT,NO_UPPER,NO_DIGIT,NO_SPECIAL", "/password")));
    const user = userEvent.setup();
    render(<Register />);
    await toDetailsStep(user);
    await user.type(screen.getByLabelText("رمز عبور"), "abc");
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    const msg = await screen.findByText(/رمز عبور باید شامل این موارد باشد/);
    for (const part of ["دست‌کم ۸ نویسه", "یک حرف بزرگ لاتین", "یک رقم", "یک نویسهٔ ویژه مانند ! یا @"]) expect(msg).toHaveTextContent(part);
    expect(msg).not.toHaveTextContent("یک حرف کوچک لاتین");
    expect(screen.getByLabelText("رمز عبور")).toHaveAttribute("aria-invalid", "true");
  });

  it("explains PASSWORD_TOO_LONG and USERNAME_TAKEN on their fields", async () => {
    server.use(http.post(`${V1}/auth/register/complete`, () => apiError(409, "USERNAME_TAKEN", "نام کاربری دیگری انتخاب کنید.", "/username")));
    const user = userEvent.setup();
    render(<Register />);
    await toDetailsStep(user);
    await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    expect(await screen.findByText(/نام کاربری قبلاً گرفته شده است/)).toBeInTheDocument();
    expect(screen.getByLabelText("نام کاربری")).toHaveAttribute("aria-invalid", "true");
    server.use(http.post(`${V1}/auth/register/complete`, () => apiError(422, "PASSWORD_TOO_LONG", "x", "/password")));
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    expect(await screen.findByText(/بیش از ۱۲۸ نویسه/)).toBeInTheDocument();
  });

  it("sends the user back to the code step when the code is wrong", async () => {
    server.use(http.post(`${V1}/auth/register/complete`, () => apiError(400, "OTP_INVALID", "کد واردشده درست نیست.", "/code")));
    const user = userEvent.setup();
    render(<Register />);
    await toDetailsStep(user);
    await user.type(screen.getByLabelText("رمز عبور"), "Abcdef1!");
    await user.click(screen.getByRole("button", { name: "ساخت حساب" }));
    expect(await screen.findByLabelText("کد تأیید")).toBeInTheDocument();
    expect(screen.getByText("کد واردشده درست نیست.")).toBeInTheDocument();
  });
});
