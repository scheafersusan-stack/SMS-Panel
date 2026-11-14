import type { ReactNode } from "react";
import { Icon } from "./Icon";

export type AlertTone = "success" | "info" | "warning" | "danger";
const ALERT_ICON: Record<AlertTone, string> = {
  success: "check-circle",
  info: "info",
  warning: "alert",
  danger: "x-circle",
};

export function Alert({ tone, title, children }: { tone: AlertTone; title?: string; children?: ReactNode }) {
  return (
    <div className={`ns-alert ns-alert-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon name={ALERT_ICON[tone]} />
      <div className="ns-alert-body">
        {title ? <p className="ns-alert-title">{title}</p> : null}
        {children ? <p>{children}</p> : null}
      </div>
    </div>
  );
}

export type BadgeTone = "success" | "info" | "warning" | "danger" | "primary" | "neutral";

export function Badge({ tone = "neutral", dot = true, children }: { tone?: BadgeTone; dot?: boolean; children: ReactNode }) {
  return <span className={`ns-badge ns-badge-${tone}${dot ? "" : " no-dot"}`}>{children}</span>;
}

export function Toast({ message, tone = "ok", onClose }: { message: string; tone?: "ok" | "bad"; onClose?: () => void }) {
  return (
    <div className="ns-toast" role="status">
      <span className={tone}>
        <Icon name={tone === "ok" ? "check-circle" : "x-circle"} />
      </span>
      <span className="ns-toast-msg">{message}</span>
      {onClose ? (
        <button type="button" aria-label="بستن" onClick={onClose}>
          <Icon name="x" size={16} />
        </button>
      ) : null}
    </div>
  );
}

/** The single fixed container all toasts stack in. */
export function ToastHost({ children }: { children?: ReactNode }) {
  return <div className="toast-host">{children}</div>;
}

export function Skeleton({ width = "100%", height = 14 }: { width?: string; height?: number }) {
  return <span className="ns-skel" style={{ width, height, display: "block" }} aria-hidden="true" />;
}

export function EmptyState({ title, children, action, icon = "inbox" }: { title: string; children?: ReactNode; action?: ReactNode; icon?: string }) {
  return (
    <div className="ns-empty">
      <span className="ns-empty-ico">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}
