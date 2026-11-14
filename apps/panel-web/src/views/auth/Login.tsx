"use client";

import { useState, type FormEvent } from "react";
import { ApiError, V1, api } from "@/lib/api";
import { useCountdown } from "@/lib/countdown";
import { errorText, fieldPath, resendWait } from "@/lib/errors";
import { latinDigits } from "@/lib/phone";
import { Button } from "@/ui/Button";
import { TextField } from "@/ui/TextField";
import { BrandMark, CodeField, FormAlert, ResendRow, goAfterLogin } from "./parts";

type LoginResult = { status: "ok" } | { status: "mfa_required"; method: "totp" | "sms"; mfa_token: string };
interface Mfa {
  method: "totp" | "sms";
  token: string;
}

export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState<Mfa | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const countdown = useCountdown();

  function backToCredentials(message: string) {
    setMfa(null);
    setCode("");
    setCodeError(null);
    setPassword("");
    setError(message);
  }

  async function sendSms(token: string) {
    try {
      const r = await api<{ resend_after: number }>("POST", `${V1}/auth/mfa/sms/send`, { mfa_token: token });
      countdown.start(r.resend_after);
    } catch (e) {
      if (e instanceof ApiError && e.code === "MFA_TOKEN_INVALID") backToCredentials(errorText(e));
      else setError(errorText(e));
      const wait = resendWait(e);
      if (wait) countdown.start(wait);
    }
  }

  async function submitCredentials(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const r = await api<LoginResult>("POST", `${V1}/auth/login`, { username: latinDigits(username.trim()), password });
      if (r.status === "ok") {
        goAfterLogin();
        return;
      }
      setPassword("");
      setMfa({ method: r.method, token: r.mfa_token });
      if (r.method === "sms") await sendSms(r.mfa_token);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: FormEvent) {
    e.preventDefault();
    if (!mfa) return;
    setError(null);
    setCodeError(null);
    setBusy(true);
    try {
      await api("POST", `${V1}/auth/mfa/confirm`, { mfa_token: mfa.token, code: latinDigits(code.trim()) });
      goAfterLogin();
    } catch (err) {
      if (err instanceof ApiError && err.code === "MFA_TOKEN_INVALID") backToCredentials(errorText(err));
      else if (fieldPath(err) === "code") setCodeError(errorText(err));
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ns-card ns-auth">
      <div className="ns-auth-side">
        <BrandMark />
        <div className="auth-side-copy">
          <h2>پیامک‌یار</h2>
          <p>ارسال تکی و گروهی، کد یک‌بارمصرف، گزارش لحظه‌ای تحویل و وب‌سرویس برای کسب‌وکار شما.</p>
        </div>
      </div>
      {mfa === null ? (
        <form className="ns-auth-form" noValidate onSubmit={(e) => void submitCredentials(e)}>
          <h1 className="auth-title">ورود به پنل</h1>
          <FormAlert message={error} />
          <TextField label="نام کاربری یا شماره موبایل" ltr autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <TextField label="رمز عبور" type="password" ltr autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <Button type="submit" variant="primary" size="lg" className="ns-btn-block" loading={busy} disabled={!username || !password}>
            ورود
          </Button>
          <div className="between small">
            <a href="#auth-forgot">رمز عبور را فراموش کرده‌اید؟</a>
            <a href="#auth-register">حساب ندارید؟ ثبت‌نام</a>
          </div>
        </form>
      ) : (
        <form className="ns-auth-form" noValidate onSubmit={(e) => void submitCode(e)}>
          <h1 className="auth-title">تأیید دومرحله‌ای</h1>
          <FormAlert message={error} />
          <CodeField
            value={code}
            onChange={setCode}
            error={codeError}
            help={mfa.method === "sms" ? "کد برای شمارهٔ موبایل شما پیامک شد." : "کد ۶ رقمی را از برنامهٔ احراز هویت وارد کنید."}
          />
          {mfa.method === "sms" ? <ResendRow left={countdown.left} onResend={() => void sendSms(mfa.token)} /> : null}
          <Button type="submit" variant="primary" size="lg" className="ns-btn-block" loading={busy} disabled={!code}>
            تأیید و ورود
          </Button>
          <div className="between small">
            <a href="#auth-login" onClick={() => backToCredentials("")}>
              بازگشت به ورود
            </a>
          </div>
        </form>
      )}
    </div>
  );
}
