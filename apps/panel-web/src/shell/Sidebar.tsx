import { NAV } from "@/nav";
import { ROUTES, type Role } from "@/routes";
import { Icon } from "@/ui/Icon";

export function Sidebar({ role, route, onNavigate }: { role: "user" | "admin"; route: string; onNavigate: () => void }) {
  const current = ROUTES[route]?.navParent ?? route;
  return (
    <nav className="ns-sidebar" id="main-nav" aria-label="منوی اصلی">
      <div className="ns-brand">
        <span className="ns-brand-mark">
          <Icon name="send" />
        </span>
        پیامک‌یار
        {role === "admin" ? (
          <span className="ns-badge ns-badge-accent no-dot" style={{ background: "var(--accent-soft)", color: "var(--on-accent)", marginInlineStart: "auto" }}>
            مدیریت
          </span>
        ) : null}
      </div>
      {NAV[role].map((section, i) => (
        <div className="side-sec" key={section.label || i}>
          {section.label ? <span className="ns-nav-label">{section.label}</span> : null}
          {section.items.map((it) => (
            <a key={it.id} className="ns-nav-item" href={`#${it.id}`} aria-current={it.id === current ? "page" : undefined} onClick={onNavigate}>
              <Icon name={it.icon} size={20} />
              {it.label}
              {it.count ? <span className="ns-count">{it.count}</span> : null}
            </a>
          ))}
        </div>
      ))}
      <div className="side-foot">
        <a className="ns-nav-item" href="#auth-login" onClick={onNavigate}>
          <Icon name="logout" size={20} />
          خروج
        </a>
      </div>
    </nav>
  );
}

export type { Role };
