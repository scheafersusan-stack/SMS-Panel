import { describe, expect, it } from "vitest";
import { jalaliDateTime } from "./format";
import { ApiError } from "./api";
import { GENERIC_ERROR, errorText, fieldPath, passwordProblemLabels, resendWait } from "./errors";

const err = (code: string, detail = "", pointer: string | null = null) => new ApiError(400, code, "t", detail, pointer);

describe("errorText", () => {
  it("has fixed copy for the auth codes", () => {
    expect(errorText(err("INVALID_CREDENTIALS"))).toBe("نام کاربری یا رمز عبور درست نیست.");
    expect(errorText(err("OTP_INVALID"))).toBe("کد واردشده درست نیست.");
    expect(errorText(err("LOGIN_IP_NOT_ALLOWED"))).toContain("نشانی");
    expect(errorText(err("LOGIN_OUTSIDE_HOURS"))).toContain("ساعت");
    expect(errorText(err("ACCOUNT_INACTIVE"))).toContain("غیرفعال");
    expect(errorText(err("ACCOUNT_EXPIRED"))).toContain("اعتبار");
  });
  it("formats the lock time in Jalali", () => {
    const iso = "2026-11-14T10:30:00+00:00";
    expect(errorText(err("ACCOUNT_LOCKED", iso))).toBe(`حساب شما تا ${jalaliDateTime(iso)} قفل است؛ پس از آن دوباره تلاش کنید.`);
  });
  it("lists each password problem", () => {
    const text = errorText(err("PASSWORD_WEAK", "TOO_SHORT,NO_UPPER,NO_SPECIAL"));
    expect(text).toContain("دست‌کم ۸ نویسه");
    expect(text).toContain("یک حرف بزرگ لاتین");
    expect(text).toContain("یک نویسهٔ ویژه مانند ! یا @");
    expect(text).not.toContain("یک رقم");
  });
  it("explains a too-early resend with Persian digits", () => {
    const e = new ApiError(429, "OTP_RESEND_TOO_SOON", "t", "x", "/mobile", 7);
    expect(errorText(e)).toBe("ارسال مجدد کد هنوز ممکن نیست؛ ۷ ثانیهٔ دیگر دوباره تلاش کنید.");
    expect(resendWait(e)).toBe(7);
    expect(resendWait(err("OTP_INVALID"))).toBeNull();
  });
  it("falls back to the server detail, then a generic line", () => {
    expect(errorText(err("SOMETHING_NEW", "جزئیات سرور"))).toBe("جزئیات سرور");
    expect(errorText(err("SOMETHING_NEW", ""))).toBe(GENERIC_ERROR);
    expect(errorText(new Error("boom"))).toBe(GENERIC_ERROR);
  });
});

describe("helpers", () => {
  it("maps problem codes and ignores unknown ones", () => {
    expect(passwordProblemLabels("NO_DIGIT,WHAT")).toEqual(["یک رقم"]);
  });
  it("reads the field path from a pointer", () => {
    expect(fieldPath(err("X", "", "/login_hours/0/from"))).toBe("login_hours/0/from");
    expect(fieldPath(err("X"))).toBeNull();
  });
});
