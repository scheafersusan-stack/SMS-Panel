import type { ReactNode } from "react";

export function Card({ title, action, foot, level = 2, children }: { title?: string; action?: ReactNode; foot?: ReactNode; level?: 2 | 3 | 4; children?: ReactNode }) {
  const Heading = `h${level}` as const;
  return (
    <section className="ns-card">
      {title || action ? (
        <div className="ns-card-head">
          {title ? <Heading>{title}</Heading> : <span />}
          {action}
        </div>
      ) : null}
      <div className="ns-card-body">{children}</div>
      {foot ? <div className="ns-card-foot">{foot}</div> : null}
    </section>
  );
}
