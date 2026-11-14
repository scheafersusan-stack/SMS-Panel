"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api";
import { errorText, fieldPath } from "@/lib/errors";
import { jalaliDateTime } from "@/lib/format";
import { faNumber } from "@/lib/format";
import { latinDigits } from "@/lib/phone";
import { qrDataUrl } from "@/lib/qr";
import { Button, IconButton } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Alert, Badge, Skeleton } from "@/ui/Feedback";
import { TextField } from "@/ui/TextField";
import { useToasts } from "./useToasts";

const V1 = "/panel/web/v1";

interface Me {
  mfa_method: "none" | "totp" | "sms";
}
interface Security {
  login_notice: boolean;
  allowed_ips: string[];
  login_hours: { days: number[]; from: string; to: string }[];
}
interface SessionRow {
  id: string;
  ip: string | null;
  user_agent: string | null;
  last_seen_at: string;
  current: boolean;
  impersonated: boolean;
}

type Toaster = (message: string, tone?: "ok" | "bad") => void;

export function ProfileSecurity() {
  const { toast, host } = useToasts();
  return (
    <>
      <div className="ph">
        <div className="ph-text">
          <h1>حساب و امنیت</h1>
          <p>رمز عبور، ورود دومرحله‌ای، محدودیت‌های ورود و نشست‌های فعال حساب شما.</p>
        </div>
      </div>
      <PasswordCard toast={toast} />
      <MfaCard toast={toast} />
      <RestrictionsCard toast={toast} />
      <SessionsCard toast={toast} />
      {host}
    </>
  );
}

// --- change password -----------------------------------------------------------------------

function PasswordCard({ toast }: { toast: Toaster }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [errors, setErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErrors({});
    setFormError(null);
    if (!current || !next) {
      setErrors({ ...(current ? {} : { current_password: "این فیلد الزامی است." }), ...(next ? {} : { new_password: "این فیلد الزامی است." }) });
      return;
    }
    setBusy(true);
    try {
      await api("POST", `${V1}/account/password`, { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      toast("رمز عبور تغییر کرد.");
    } catch (err) {
      const path = fieldPath(err);
      if (path === "current_password" || path === "new_password") setErrors({ [path]: errorText(err) });
      else setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="تغییر رمز عبور">
      <form className="stack" noValidate onSubmit={(e) => void submit(e)}>
        {formError ? <Alert tone="danger">{formError}</Alert> : null}
        <div className="form-grid">
          <TextField label="رمز عبور فعلی" type="password" ltr autoComplete="current-password" value={current} error={errors.current_password} onChange={(e) => setCurrent(e.target.value)} />
          <TextField
            label="رمز عبور جدید"
            type="password"
            ltr
            autoComplete="new-password"
            help="دست‌کم ۸ نویسه با حرف بزرگ و کوچک لاتین، رقم و یک نویسهٔ ویژه"
            value={next}
            error={errors.new_password}
            onChange={(e) => setNext(e.target.value)}
          />
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          با تغییر رمز عبور، نشست‌های دیگر شما بسته می‌شوند.
        </p>
        <div>
          <Button type="submit" variant="primary" loading={busy}>
            تغییر رمز عبور
          </Button>
        </div>
      </form>
    </Card>
  );
}

// --- second factor -------------------------------------------------------------------------

type Panel = "totp" | "sms" | "disable" | null;
const MFA_LABEL: Record<Me["mfa_method"], string> = { none: "غیرفعال", totp: "فعال: برنامهٔ احراز هویت", sms: "فعال: کد پیامکی" };

function MfaCard({ toast }: { toast: Toaster }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["account", "me"], queryFn: () => api<Me>("GET", `${V1}/account/me`) });
  const [panel, setPanel] = useState<Panel>(null);
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function close() {
    setPanel(null);
    setSetup(null);
    setCode("");
    setPassword("");
    setErrors({});
    setFormError(null);
  }

  async function openTotp() {
    close();
    setBusy(true);
    try {
      const r = await api<{ secret: string; otpauth_uri: string }>("POST", `${V1}/account/mfa/totp/setup`);
      setSetup({ secret: r.secret, uri: r.otpauth_uri });
      setPanel("totp");
    } catch (err) {
      setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function openPanel(p: Panel) {
    close();
    setPanel(p);
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setErrors({});
    setFormError(null);
    if (!password || (panel === "totp" && !code.trim())) {
      setErrors({ ...(password ? {} : { password: "رمز عبور حساب را وارد کنید." }), ...(panel === "totp" && !code.trim() ? { code: "کد برنامه را وارد کنید." } : {}) });
      return;
    }
    setBusy(true);
    try {
      let done: string;
      if (panel === "totp") {
        await api("POST", `${V1}/account/mfa/totp/enable`, { code: latinDigits(code.trim()), password });
        done = "ورود دومرحله‌ای با برنامهٔ احراز هویت فعال شد.";
      } else if (panel === "sms") {
        await api("POST", `${V1}/account/mfa/sms/enable`, { password });
        done = "ورود دومرحله‌ای با پیامک فعال شد.";
      } else {
        await api("POST", `${V1}/account/mfa/disable`, { password });
        done = "ورود دومرحله‌ای غیرفعال شد.";
      }
      close();
      toast(done);
      await qc.invalidateQueries({ queryKey: ["account", "me"] });
    } catch (err) {
      const path = fieldPath(err);
      const wrongPassword = err instanceof ApiError && err.code === "CURRENT_PASSWORD_INVALID";
      if (path === "password" || path === "code") setErrors({ [path]: wrongPassword ? "رمز عبور درست نیست." : errorText(err) });
      else setFormError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const method = me.data?.mfa_method;
  return (
    <Card title="ورود دومرحله‌ای" action={method ? <Badge tone={method === "none" ? "neutral" : "success"}>{MFA_LABEL[method]}</Badge> : undefined}>
      <div className="stack">
        <p className="small muted" style={{ margin: 0 }}>
          با فعال بودن، هر ورود به یک کد دوم نیاز دارد. برای هر تغییر، رمز عبور حساب را دوباره وارد می‌کنید.
        </p>
        {me.isError ? <Alert tone="danger">{errorText(me.error)}</Alert> : null}
        {formError && panel === null ? <Alert tone="danger">{formError}</Alert> : null}
        {method ? (
          <div className="ns-row">
            {method !== "totp" ? (
              <Button variant="secondary" disabled={busy} onClick={() => void openTotp()}>
                فعال‌سازی با برنامهٔ احراز هویت
              </Button>
            ) : null}
            {method !== "sms" ? (
              <Button variant="secondary" disabled={busy} onClick={() => openPanel("sms")}>
                فعال‌سازی با پیامک
              </Button>
            ) : null}
            {method !== "none" ? (
              <Button variant="danger" disabled={busy} onClick={() => openPanel("disable")}>
                غیرفعال‌سازی
              </Button>
            ) : null}
          </div>
        ) : me.isPending ? (
          <Skeleton height={40} />
        ) : null}
        {panel ? (
          <form className="stack" noValidate onSubmit={(e) => void confirm(e)}>
            {formError ? <Alert tone="danger">{formError}</Alert> : null}
            {panel === "totp" && setup ? (
              <>
                <p style={{ margin: 0 }}>این کد QR را با برنامهٔ احراز هویت (مانند Google Authenticator) اسکن کنید، سپس کد ۶ رقمی را وارد کنید.</p>
                <div className="qr-box">
                  {/* eslint-disable-next-line @next/next/no-img-element -- a generated data URL, not a network image */}
                  <img src={qrDataUrl(setup.uri)} alt="کد QR برنامهٔ احراز هویت" width={180} height={180} />
                  <div className="stack-sm">
                    <span className="small muted">اگر اسکن ممکن نیست، این کلید را وارد کنید:</span>
                    <code dir="ltr" className="ns-ltr">
                      {setup.secret}
                    </code>
                  </div>
                </div>
                <TextField label="کد برنامه" ltr inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code} error={errors.code} onChange={(e) => setCode(e.target.value)} />
              </>
            ) : null}
            <TextField label="رمز عبور حساب" type="password" ltr autoComplete="current-password" value={password} error={errors.password} onChange={(e) => setPassword(e.target.value)} />
            <div className="ns-row">
              <Button type="submit" variant={panel === "disable" ? "danger" : "primary"} loading={busy}>
                {panel === "totp" ? "تأیید و فعال‌سازی" : panel === "sms" ? "فعال‌سازی" : "تأیید غیرفعال‌سازی"}
              </Button>
              <Button variant="ghost" onClick={close}>
                انصراف
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </Card>
  );
}

// --- sign-in restrictions ------------------------------------------------------------------

const DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"];

interface HoursWindow {
  days: number[];
  from: string;
  to: string;
}

function RestrictionsCard({ toast }: { toast: Toaster }) {
  const sec = useQuery({ queryKey: ["account", "security"], queryFn: () => api<Security>("GET", `${V1}/account/security`) });
  return (
    <Card title="محدودیت‌های ورود">
      {sec.data ? <RestrictionsForm initial={sec.data} toast={toast} /> : sec.isError ? <Alert tone="danger">{errorText(sec.error)}</Alert> : <Skeleton height={120} />}
    </Card>
  );
}

function RestrictionsForm({ initial, toast }: { initial: Security; toast: Toaster }) {
  const qc = useQueryClient();
  const [notice, setNotice] = useState(initial.login_notice);
  const [ips, setIps] = useState(initial.allowed_ips);
  const [ipInput, setIpInput] = useState("");
  const [windows, setWindows] = useState<HoursWindow[]>(initial.login_hours.map((w) => ({ ...w })));
  const [errors, setErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<{ title: string; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);

  function addIp() {
    const v = latinDigits(ipInput).trim();
    if (!v) return;
    if (!ips.includes(v)) setIps([...ips, v]);
    setIpInput("");
  }

  const patch = (i: number, p: Partial<HoursWindow>) => setWindows((l) => l.map((w, k) => (k === i ? { ...w, ...p } : w)));
  const toggleDay = (i: number, d: number) => {
    const w = windows[i];
    if (w) patch(i, { days: w.days.includes(d) ? w.days.filter((x) => x !== d) : [...w.days, d].sort() });
  };

  async function save() {
    setErrors({});
    setFormError(null);
    const body: Security = {
      login_notice: notice,
      allowed_ips: ips,
      login_hours: windows.map((w) => ({ days: [...w.days].sort(), from: latinDigits(w.from.trim()), to: latinDigits(w.to.trim()) })),
    };
    const missing: Record<string, ReactNode> = {};
    body.login_hours.forEach((w, i) => {
      if (w.days.length === 0) missing[`login_hours/${i}/days`] = "دست‌کم یک روز را انتخاب کنید.";
    });
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    setBusy(true);
    try {
      const saved = await api<Security>("PUT", `${V1}/account/security`, body);
      qc.setQueryData(["account", "security"], saved);
      toast("محدودیت‌های ورود ذخیره شد.");
    } catch (err) {
      const path = fieldPath(err);
      if (err instanceof ApiError && err.code === "WOULD_LOCK_YOU_OUT") {
        setFormError({ title: "این تنظیم دسترسی خود شما را می‌بندد", detail: err.detail });
      } else if (path && /^(allowed_ips|login_hours)\//.test(path)) {
        setErrors({ [path]: errorText(err) });
      } else {
        setFormError({ title: errorText(err), detail: "" });
      }
    } finally {
      setBusy(false);
    }
  }

  const ipError = Object.entries(errors).find(([k]) => k.startsWith("allowed_ips/"))?.[1];
  return (
    <form className="stack" noValidate onSubmit={(e) => (e.preventDefault(), void save())}>
      {formError ? (
        <Alert tone="danger" title={formError.title}>
          {formError.detail}
        </Alert>
      ) : null}
      <label className="ns-switch">
        <input type="checkbox" role="switch" checked={notice} onChange={(e) => setNotice(e.target.checked)} />
        <span>اطلاع‌رسانی پیامکی هر ورود</span>
      </label>

      <div className="stack-sm">
        <div className="ns-row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <TextField
              label="نشانی IP یا محدوده (CIDR)"
              ltr
              placeholder="203.0.113.0/24"
              help="اگر خالی بماند، ورود از هر نشانی مجاز است."
              value={ipInput}
              error={ipError}
              onChange={(e) => setIpInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addIp();
                }
              }}
            />
          </div>
          <Button variant="secondary" onClick={addIp}>
            افزودن نشانی
          </Button>
        </div>
        {ips.length ? (
          <ul className="list" aria-label="نشانی‌های مجاز">
            {ips.map((ip) => (
              <li key={ip} className="list-row">
                <span className="grow ns-ltr" dir="ltr">
                  {ip}
                </span>
                <IconButton icon="trash" label={`حذف ${ip}`} onClick={() => setIps(ips.filter((x) => x !== ip))} />
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="stack-sm">
        <div className="between">
          <b>ساعت‌های مجاز ورود (به وقت تهران)</b>
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setWindows([...windows, { days: [], from: "08:00", to: "18:00" }])}>
            افزودن بازه
          </Button>
        </div>
        {windows.length === 0 ? <span className="ns-help">بدون محدودیت: ورود در همهٔ ساعت‌ها مجاز است.</span> : null}
        {windows.map((w, i) => (
          <div key={i} className="stack-sm" style={{ paddingBlock: 8, borderBottom: "1px solid var(--border)" }}>
            <div className="ns-row" role="group" aria-label={`روزهای بازهٔ ${faNumber(i + 1)}`}>
              {DAYS.map((name, d) => (
                <Button key={name} size="sm" variant={w.days.includes(d) ? "primary" : "secondary"} aria-pressed={w.days.includes(d)} onClick={() => toggleDay(i, d)}>
                  {name}
                </Button>
              ))}
            </div>
            {errors[`login_hours/${i}/days`] ? <span className="ns-help is-error">{errors[`login_hours/${i}/days`]}</span> : null}
            <div className="form-grid">
              <TextField label={`ساعت شروع بازهٔ ${faNumber(i + 1)}`} ltr maxLength={5} placeholder="08:00" value={w.from} error={errors[`login_hours/${i}/from`]} onChange={(e) => patch(i, { from: e.target.value })} />
              <TextField label={`ساعت پایان بازهٔ ${faNumber(i + 1)}`} ltr maxLength={5} placeholder="18:00" value={w.to} error={errors[`login_hours/${i}/to`]} onChange={(e) => patch(i, { to: e.target.value })} />
            </div>
            <div>
              <Button variant="ghost" size="sm" icon="trash" onClick={() => setWindows(windows.filter((_, k) => k !== i))}>
                حذف بازه
              </Button>
            </div>
          </div>
        ))}
      </div>

      <div>
        <Button type="submit" variant="primary" loading={busy}>
          ذخیرهٔ محدودیت‌ها
        </Button>
      </div>
    </form>
  );
}

// --- sessions ------------------------------------------------------------------------------

function SessionsCard({ toast }: { toast: Toaster }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["account", "sessions"], queryFn: () => api<{ sessions: SessionRow[] }>("GET", `${V1}/account/sessions`) });
  const [busyId, setBusyId] = useState<string | null>(null);

  async function revoke(row: SessionRow) {
    setBusyId(row.id);
    try {
      await api("DELETE", `${V1}/account/sessions/${row.id}`);
      toast("نشست بسته شد.");
    } catch (err) {
      // An already-closed session just disappears from the list.
      if (!(err instanceof ApiError && err.code === "SESSION_NOT_FOUND")) toast(errorText(err), "bad");
    } finally {
      setBusyId(null);
      await qc.invalidateQueries({ queryKey: ["account", "sessions"] });
    }
  }

  return (
    <Card title="نشست‌های فعال">
      {list.isError ? (
        <Alert tone="danger">{errorText(list.error)}</Alert>
      ) : !list.data ? (
        <Skeleton height={80} />
      ) : (
        <ul className="list" aria-label="نشست‌های فعال">
          {list.data.sessions.map((s) => (
            <li key={s.id} className="list-row">
              <div className="grow">
                <b>{s.user_agent ?? "دستگاه ناشناس"}</b>
                <div className="small muted">
                  <span dir="ltr">{s.ip ?? "—"}</span> · آخرین فعالیت {jalaliDateTime(s.last_seen_at)}
                </div>
              </div>
              {s.impersonated ? <Badge tone="warning">ورود مدیر</Badge> : null}
              {s.current ? (
                <Badge tone="success">فعلی</Badge>
              ) : (
                <Button variant="ghost" size="sm" aria-label={`بستن نشست ${s.ip ?? ""}`} loading={busyId === s.id} onClick={() => void revoke(s)}>
                  خروج
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
