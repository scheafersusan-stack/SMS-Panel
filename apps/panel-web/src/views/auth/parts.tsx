import type { ReactNode } from "react";
import { clock } from "@/lib/countdown";
import { afterLoginRoute } from "@/lib/session";
import { Alert } from "@/ui/Feedback";
import { Button } from "@/ui/Button";
import { Icon } from "@/ui/Icon";
import { TextField } from "@/ui/TextField";

export function BrandMark() {
  return (
    <span className="ns-brand-mark">
      <Icon name="send" size={18} />
    </span>
  );
}

/** Single-column auth card (registration, recovery). */
export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="ns-card auth-card">
      <div className="ns-card-body stack">
        <div className="ns-brand" style={{ padding: 0 }}>
          <BrandMark />
          پیامک‌یار
        </div>
        <h1 className="auth-title">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function FormAlert({ message }: { message: string | null }) {
  return message ? <Alert tone="danger">{message}</Alert> : null;
}

export function CodeField({ value, onChange, error, label = "کد تأیید", help }: { value: string; onChange: (v: string) => void; error?: ReactNode; label?: string; help?: ReactNode }) {
  return (
    <TextField
      label={label}
      ltr
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={8}
      className="otp-input"
      value={value}
      error={error}
      help={help}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** «ارسال دوباره کد» button that stays disabled until the countdown reaches zero. */
export function ResendRow({ left, busy, onResend }: { left: number; busy?: boolean; onResend: () => void }) {
  return (
    <div className="between">
      <Button size="sm" variant="secondary" disabled={left > 0 || busy} onClick={onResend}>
        ارسال دوباره کد
      </Button>
      {left > 0 ? <span className="ns-help">ارسال دوباره کد تا {clock(left)} دیگر</span> : null}
    </div>
  );
}

export function goTo(route: string): void {
  window.location.hash = `#${route}`;
}

/** Signed in: back to the route the guard sent us away from, else the dashboard. */
export function goAfterLogin(): void {
  goTo(afterLoginRoute());
}

export const PASSWORD_HELP = "دست‌کم ۸ نویسه با حرف بزرگ و کوچک لاتین، رقم و یک نویسهٔ ویژه";
