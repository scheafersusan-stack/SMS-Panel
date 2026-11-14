"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api";
import { useCountdown } from "@/lib/countdown";
import { errorText, fieldPath } from "@/lib/errors";
import { formatMobile, latinDigits, normalizeMobile } from "@/lib/phone";
import { Alert } from "@/ui/Feedback";
import { Button, buttonClass } from "@/ui/Button";
import { Stepper } from "@/ui/Nav";
import { TextField } from "@/ui/TextField";
import { AuthCard, CodeField, FormAlert, PASSWORD_HELP, ResendRow } from "./parts";

const V1 = "/panel/web/v1";
const RESET_CODE_INVALID = "کد نامعتبر یا منقضی است؛ کد جدید بگیرید.";

export function ForgotPassword() {
  const [step, setStep] = useState(0);
  const [mobile, setMobile] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const countdown = useCountdown();

  async function run(work: () => Promise<void>) {
    setErrors({});
    setFormError(null);
    setBusy(true);
    try {
      await work();
    } catch (err) {
      const path = fieldPath(err);
      // Every failed code (wrong, expired, used up) is the same answer by design.
      const msg = err instanceof ApiError && err.code === "OTP_INVALID" ? RESET_CODE_INVALID : errorText(err);
      if (path === "mobile" || path === "code" || path === "new_password") setErrors({ [path]: msg });
      else setFormError(msg);
    } finally {
      setBusy(false);
    }
  }

  async function requestCode(): Promise<boolean> {
    const normalized = normalizeMobile(mobile);
    if (!normalized) {
      setErrors({ mobile: "شمارهٔ موبایل معتبر نیست." });
      return false;
    }
    const r = await api<{ challenge_id: string; resend_after: number }>("POST", `${V1}/auth/reset/start`, { mobile: normalized });
    setChallenge(r.challenge_id);
    countdown.start(r.resend_after);
    return true;
  }

  const sendCode = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      if (await requestCode()) setStep(1);
    });
  };

  const complete = (e: FormEvent) => {
    e.preventDefault();
    const missing: Record<string, ReactNode> = {};
    if (!code.trim()) missing.code = "کد تأیید را وارد کنید.";
    if (!password) missing.new_password = "رمز عبور جدید را وارد کنید.";
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    void run(async () => {
      await api("POST", `${V1}/auth/reset/complete`, { challenge_id: challenge, code: latinDigits(code.trim()), new_password: password });
      setStep(2);
    });
  };

  return (
    <AuthCard title="بازیابی رمز عبور">
      <Stepper steps={["موبایل", "رمز عبور جدید"]} current={step} />
      <FormAlert message={formError} />
      {step === 0 ? (
        <form className="stack" noValidate onSubmit={sendCode}>
          <TextField label="شماره موبایل" ltr inputMode="tel" autoComplete="tel" placeholder="0912 345 6789" value={mobile} error={errors.mobile} onChange={(e) => setMobile(e.target.value)} />
          <Button type="submit" variant="primary" size="lg" className="ns-btn-block" loading={busy}>
            ارسال کد تأیید
          </Button>
          <p className="small" style={{ margin: 0 }}>
            <a href="#auth-login">بازگشت به ورود</a>
          </p>
        </form>
      ) : step === 1 ? (
        <form className="stack" noValidate onSubmit={complete}>
          <CodeField value={code} onChange={setCode} error={errors.code} help={<>اگر حسابی با شمارهٔ <span dir="ltr">{formatMobile(mobile)}</span> وجود داشته باشد، کد پیامک می‌شود.</>} />
          <ResendRow
            left={countdown.left}
            busy={busy}
            onResend={() =>
              void run(async () => {
                await requestCode();
                setCode("");
              })
            }
          />
          <TextField label="رمز عبور جدید" type="password" ltr autoComplete="new-password" help={PASSWORD_HELP} value={password} error={errors.new_password} onChange={(e) => setPassword(e.target.value)} />
          <div className="between">
            <Button variant="secondary" onClick={() => setStep(0)}>
              ویرایش شماره
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              تغییر رمز عبور
            </Button>
          </div>
        </form>
      ) : (
        <div className="stack">
          <Alert tone="success" title="رمز عبور شما تغییر کرد.">
            نشست‌های قبلی بسته شدند. با رمز عبور جدید وارد شوید.
          </Alert>
          <a className={buttonClass("primary", "lg", "ns-btn-block")} href="#auth-login" style={{ textDecoration: "none" }}>
            ورود به حساب
          </a>
        </div>
      )}
    </AuthCard>
  );
}
