import type { ReactNode } from "react";

export function Card({ title, action, foot, children }: { title?: string; action?: ReactNode; foot?: ReactNode; children?: ReactNode }) {
  return (
    <section className="ns-card">
      {title || action ? (
        <div className="ns-card-head">
          {title ? <h3>{title}</h3> : <span />}
          {action}
        </div>
      ) : null}
      <div className="ns-card-body">{children}</div>
      {foot ? <div className="ns-card-foot">{foot}</div> : null}
    </section>
  );
}
