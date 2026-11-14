import type { ReactNode } from "react";
import { faNumber } from "@/lib/format";
import { Icon } from "./Icon";

export interface TabDef {
  id: string;
  label: string;
  count?: number;
}

export function Tabs({ tabs, value, onChange }: { tabs: TabDef[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="ns-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} type="button" role="tab" className="ns-tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>
          {t.label}
          {t.count !== undefined ? <span className="ns-badge ns-badge-neutral no-dot">{faNumber(t.count)}</span> : null}
        </button>
      ))}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="ns-row" style={{ justifyContent: "space-between" }}>
      <span className="ns-help">
        نمایش {faNumber(from)} تا {faNumber(to)} از {faNumber(total)} ردیف
      </span>
      <nav className="ns-pager" aria-label="صفحه‌بندی">
        <button type="button" aria-label="قبلی" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <Icon name="chev-right" />
        </button>
        <button type="button" aria-current="page">
          {faNumber(page)}
        </button>
        <span className="gap">از {faNumber(pages)}</span>
        <button type="button" aria-label="بعدی" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <Icon name="chev-left" />
        </button>
      </nav>
    </div>
  );
}

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="ns-steps">
      {steps.map((s, i) => (
        <li key={s} className={`ns-step${i < current ? " is-done" : i === current ? " is-current" : ""}`} aria-current={i === current ? "step" : undefined}>
          <span className="ns-step-bar" />
          <span className="ns-step-text">
            <span className="ns-step-num">{i < current ? <Icon name="check" size={14} /> : faNumber(i + 1)}</span>
            {s}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="ns-row">{children}</div>;
}
