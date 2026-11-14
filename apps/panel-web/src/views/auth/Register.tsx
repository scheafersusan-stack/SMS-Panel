"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { V1, api } from "@/lib/api";
import { useCountdown } from "@/lib/countdown";
import { errorText, fieldPath, resendWait } from "@/lib/errors";
import { formatMobile, latinDigits, normalizeMobile } from "@/lib/phone";
import { Button } from "@/ui/Button";
import { Stepper } from "@/ui/Nav";
import { TextField } from "@/ui/TextField";
import { AuthCard, CodeField, FormAlert, PASSWORD_HELP, ResendRow, goAfterLogin } from "./parts";

type Kind = "person" | "company";
type Errors = Record<string, ReactNode>;

const STEPS = ["موبایل", "کد تأیید", "اطلاعات حساب"];
/** The step that owns a server field. */
const FIELD_STEP: Record<string, number> = { mobile: 0, code: 1 };
/** Fields rendered on each step; an error for any other field is a form-level message. */
const RENDERED: string[][] = [["mobile"], ["code"], ["first_name", "last_name", "company_name", "username", "password", "email"]];

export function Register() {
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<Kind>("person");
  const [mobile, setMobile] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [form, setForm] = useState({ first_name: "", last_name: "", company_name: "", username: "", password: "", email: "" });
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const countdown = useCountdown();

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function fail(err: unknown, own: number) {
    const path = fieldPath(err);
    const msg = errorText(err);
    const wait = resendWait(err);
    if (wait) countdown.start(wait);
    if (path && RENDERED[own]?.includes(path)) {
      setErrors({ [path]: msg });
    } else if (path && own === 2 && path in FIELD_STEP) {
      // The final submit can be refused for the mobile or the code; go back to that step.
      setStep(FIELD_STEP[path] ?? own);
      setErrors({ [path]: msg });
    } else {
      setFormError(msg);
    }
  }

  async function start() {
    const normalized = normalizeMobile(mobile);
    if (!normalized) {
      setErrors({ mobile: "شمارهٔ موبایل معتبر نیست." });
      return false;
    }
    const r = await api<{ challenge_id: string; resend_after: number }>("POST", `${V1}/auth/register/start`, { mobile: normalized, kind });
    setChallenge(r.challenge_id);
    countdown.start(r.resend_after);
    return true;
  }

  async function run(own: number, work: () => Promise<void>) {
    setErrors({});
    setFormError(null);
    setBusy(true);
    try {
      await work();
    } catch (err) {
      fail(err, own);
    } finally {
      setBusy(false);
    }
  }

  const sendCode = (e: FormEvent) => {
    e.preventDefault();
    void run(0, async () => {
      if (await start()) {
        setCode("");
        setStep(1);
      }
    });
  };

  const resend = () =>
    void run(1, async () => {
      await start();
      setCode("");
    });

  const toDetails = (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) {
      setErrors({ code: "کد تأیید را وارد کنید." });
      return;
    }
    setErrors({});
    setFormError(null);
    setStep(2);
  };

  const complete = (e: FormEvent) => {
    e.preventDefault();
    const missing: Errors = {};
    if (!form.first_name.trim()) missing.first_name = "این فیلد الزامی است.";
    if (kind === "person" && !form.last_name.trim()) missing.last_name = "این فیلد الزامی است.";
    if (kind === "company" && !form.company_name.trim()) missing.company_name = "این فیلد الزامی است.";
    if (!form.username.trim()) missing.username = "این فیلد الزامی است.";
    if (!form.password) missing.password = "این فیلد الزامی است.";
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    void run(2, async () => {
      const body: Record<string, string> = {
        challenge_id: challenge,
        code: latinDigits(code.trim()),
        username: form.username.trim(),
        password: form.password,
        first_name: form.first_name.trim(),
      };
      if (kind === "person") body.last_name = form.last_name.trim();
      else body.company_name = form.company_name.trim();
      if (form.email.trim()) body.email = form.email.trim();
      await api("POST", `${V1}/auth/register/complete`, body);
      goAfterLogin();
    });
  };

  return (
    <AuthCard title="ثبت‌نام">
      <Stepper steps={STEPS} current={step} />
      <FormAlert message={formError} />
      {step === 0 ? (
        <form className="stack" noValidate onSubmit={sendCode}>
          <div className="ns-field">
            <span className="ns-label" id="kind-label">
              نوع حساب
            </span>
            <div className="ns-seg" role="group" aria-labelledby="kind-label">
              <button type="button" aria-pressed={kind === "person"} onClick={() => setKind("person")}>
                حقیقی
              </button>
              <button type="button" aria-pressed={kind === "company"} onClick={() => setKind("company")}>
                حقوقی
              </button>
            </div>
          </div>
          <TextField label="شماره موبایل" ltr inputMode="tel" autoComplete="tel" placeholder="0912 345 6789" value={mobile} error={errors.mobile} onChange={(e) => setMobile(e.target.value)} />
          <Button type="submit" variant="primary" size="lg" className="ns-btn-block" loading={busy}>
            ارسال کد تأیید
          </Button>
          <p className="small" style={{ margin: 0 }}>
            حساب دارید؟ <a href="#auth-login">ورود</a>
          </p>
        </form>
      ) : step === 1 ? (
        <form className="stack" noValidate onSubmit={toDetails}>
          <CodeField value={code} onChange={setCode} error={errors.code} help={<>کد به شمارهٔ <span dir="ltr">{formatMobile(mobile)}</span> پیامک شد.</>} />
          <ResendRow left={countdown.left} busy={busy} onResend={resend} />
          <div className="between">
            <Button variant="secondary" onClick={() => setStep(0)}>
              ویرایش شماره
            </Button>
            <Button type="submit" variant="primary">
              ادامه
            </Button>
          </div>
        </form>
      ) : (
        <form className="stack" noValidate onSubmit={complete}>
          <div className="form-grid">
            <TextField label={kind === "company" ? "نام نماینده" : "نام"} autoComplete="given-name" value={form.first_name} error={errors.first_name} onChange={set("first_name")} />
            {kind === "person" ? (
              <TextField label="نام خانوادگی" autoComplete="family-name" value={form.last_name} error={errors.last_name} onChange={set("last_name")} />
            ) : (
              <TextField label="نام شرکت" autoComplete="organization" value={form.company_name} error={errors.company_name} onChange={set("company_name")} />
            )}
          </div>
          <TextField label="نام کاربری" ltr autoComplete="username" help="۳ تا ۳۲ نویسهٔ انگلیسی، رقم، _ یا ." value={form.username} error={errors.username} onChange={set("username")} />
          <TextField label="رمز عبور" type="password" ltr autoComplete="new-password" help={PASSWORD_HELP} value={form.password} error={errors.password} onChange={set("password")} />
          <TextField label="ایمیل (اختیاری)" type="email" ltr autoComplete="email" placeholder="name@example.com" value={form.email} error={errors.email} onChange={set("email")} />
          <div className="between">
            <Button variant="secondary" onClick={() => setStep(1)}>
              مرحلهٔ قبل
            </Button>
            <Button type="submit" variant="primary" loading={busy}>
              ساخت حساب
            </Button>
          </div>
        </form>
      )}
    </AuthCard>
  );
}

