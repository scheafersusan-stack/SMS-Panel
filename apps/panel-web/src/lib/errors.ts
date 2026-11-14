import { ApiError } from "./api";
import { jalaliDateTime } from "./format";

export const GENERIC_ERROR = "خطایی رخ داد؛ دوباره تلاش کنید.";

const PASSWORD_PROBLEMS: Record<string, string> = {
  TOO_SHORT: "دست‌کم ۸ نویسه",
  NO_UPPER: "یک حرف بزرگ لاتین",
  NO_LOWER: "یک حرف کوچک لاتین",
  NO_DIGIT: "یک رقم",
  NO_SPECIAL: "یک نویسهٔ ویژه مانند ! یا @",
};

/** Persian labels for the comma-joined problem codes of a PASSWORD_WEAK detail. */
export function passwordProblemLabels(detail: string): string[] {
  return detail
    .split(",")
    .map((c) => PASSWORD_PROBLEMS[c.trim()])
    .filter((x): x is string => x !== undefined);
}

const COPY: Record<string, string> = {
  INVALID_CREDENTIALS: "نام کاربری یا رمز عبور درست نیست.",
  LOGIN_IP_NOT_ALLOWED: "ورود از این نشانی IP مجاز نیست؛ از نشانی مجاز وارد شوید.",
  LOGIN_OUTSIDE_HOURS: "ورود در این ساعت مجاز نیست؛ در ساعت‌های مجاز وارد شوید.",
  ACCOUNT_INACTIVE: "حساب شما غیرفعال است؛ با پشتیبانی تماس بگیرید.",
  ACCOUNT_EXPIRED: "اعتبار حساب شما به پایان رسیده است؛ با پشتیبانی تماس بگیرید.",
  MFA_TOKEN_INVALID: "مرحلهٔ ورود منقضی شد؛ دوباره وارد حساب شوید.",
  OTP_INVALID: "کد واردشده درست نیست.",
  OTP_EXPIRED: "کد منقضی شده است؛ کد جدید بگیرید.",
  OTP_TOO_MANY_ATTEMPTS: "تعداد تلاش‌ها از حد مجاز گذشت؛ کد جدید بگیرید.",
  RATE_LIMITED: "تعداد تلاش‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید.",
  MOBILE_TAKEN: "این شماره قبلاً ثبت شده است؛ با آن وارد شوید.",
  USERNAME_TAKEN: "این نام کاربری قبلاً گرفته شده است؛ نام دیگری انتخاب کنید.",
  PASSWORD_TOO_LONG: "رمز عبور نباید بیش از ۱۲۸ نویسه باشد.",
  CURRENT_PASSWORD_INVALID: "رمز عبور فعلی درست نیست.",
  WOULD_LOCK_YOU_OUT: "این تنظیم دسترسی خود شما را می‌بندد.",
  TOTP_SETUP_REQUIRED: "راه‌اندازی منقضی شد؛ کد QR تازه بگیرید.",
};

/** Persian message for any thrown value: fixed copy per code, else the server detail, else a generic line. */
export function errorText(e: unknown): string {
  if (!(e instanceof ApiError)) return GENERIC_ERROR;
  if (e.code === "ACCOUNT_LOCKED") {
    const when = jalaliDateTime(e.detail);
    return when ? `حساب شما تا ${when} قفل است؛ پس از آن دوباره تلاش کنید.` : "حساب شما موقتاً قفل است؛ بعداً دوباره تلاش کنید.";
  }
  if (e.code === "PASSWORD_WEAK") {
    const labels = passwordProblemLabels(e.detail);
    return labels.length ? `رمز عبور باید شامل این موارد باشد: ${labels.join("، ")}.` : "رمز عبور به‌اندازهٔ کافی قوی نیست.";
  }
  return COPY[e.code] ?? (e.detail || GENERIC_ERROR);
}

/** The JSON pointer of a field error without its leading slash («login_hours/0/from»), or null. */
export function fieldPath(e: unknown): string | null {
  return e instanceof ApiError && e.pointer ? e.pointer.replace(/^\//, "") : null;
}
