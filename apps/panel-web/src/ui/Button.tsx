import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "accent";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  icon?: string;
  loading?: boolean;
  children?: ReactNode;
}

export function buttonClass(variant: ButtonVariant = "secondary", size: Props["size"] = "md", extra = ""): string {
  return ["ns-btn", `ns-btn-${variant}`, size === "md" ? "" : `ns-btn-${size}`, extra].filter(Boolean).join(" ");
}

export function Button({ variant = "secondary", size = "md", icon, loading, className, children, disabled, type, ...rest }: Props) {
  return (
    <button type={type ?? "button"} className={buttonClass(variant, size, className)} disabled={disabled || loading} {...rest}>
      {loading ? <span className="ns-spinner" aria-hidden="true" /> : icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
}

export function IconButton({ icon, label, variant = "ghost", ...rest }: Omit<Props, "children"> & { icon: string; label: string }) {
  return (
    <button type="button" className={buttonClass(variant, "md", "ns-btn-icon")} aria-label={label} {...rest}>
      <Icon name={icon} />
    </button>
  );
}
