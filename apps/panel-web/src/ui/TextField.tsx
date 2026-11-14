import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

interface FieldProps {
  label: string;
  help?: ReactNode;
  error?: ReactNode;
  required?: boolean;
}

function Field({ label, help, error, required, id, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="ns-field">
      <label className="ns-label" htmlFor={id}>
        {label}
        {required ? <span className="req">*</span> : null}
      </label>
      {children}
      {error ? (
        <span className="ns-help is-error" id={`${id}-msg`}>
          {error}
        </span>
      ) : help ? (
        <span className="ns-help" id={`${id}-msg`}>
          {help}
        </span>
      ) : null}
    </div>
  );
}

export function TextField({
  label,
  help,
  error,
  required,
  ltr,
  className,
  ...rest
}: FieldProps & { ltr?: boolean } & InputHTMLAttributes<HTMLInputElement>) {
  const auto = useId();
  const id = rest.id ?? auto;
  return (
    <Field label={label} help={help} error={error} required={required} id={id}>
      <input
        {...rest}
        id={id}
        required={required}
        dir={ltr ? "ltr" : rest.dir}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || help ? `${id}-msg` : undefined}
        className={["ns-input", error ? "is-error" : "", className ?? ""].filter(Boolean).join(" ")}
      />
    </Field>
  );
}

export function Select({
  label,
  help,
  error,
  required,
  className,
  children,
  ...rest
}: FieldProps & SelectHTMLAttributes<HTMLSelectElement>) {
  const auto = useId();
  const id = rest.id ?? auto;
  return (
    <Field label={label} help={help} error={error} required={required} id={id}>
      <select
        {...rest}
        id={id}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || help ? `${id}-msg` : undefined}
        className={["ns-select", error ? "is-error" : "", className ?? ""].filter(Boolean).join(" ")}
      >
        {children}
      </select>
    </Field>
  );
}
