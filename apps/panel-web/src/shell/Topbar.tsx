import { Icon } from "@/ui/Icon";

export function Topbar({ role, onMenu, onTheme }: { role: "user" | "admin"; onMenu: () => void; onTheme: () => void }) {
  return (
    <header className="ns-topbar">
      <button type="button" className="ns-btn ns-btn-ghost ns-btn-icon menu-btn" aria-label="منو" onClick={onMenu}>
        <Icon name="menu" />
      </button>
      <div className="ns-seg role-switch" role="group" aria-label="پنل">
        <button type="button" aria-pressed={role === "user"} onClick={() => (window.location.hash = "#u-dashboard")}>
          کاربر
        </button>
        <button type="button" aria-pressed={role === "admin"} onClick={() => (window.location.hash = "#a-dashboard")}>
          مدیریت
        </button>
      </div>
      <div className="grow">
        <div className="ns-input-wrap top-search" style={{ maxWidth: 340 }}>
          <Icon name="search" />
          <input className="ns-input" aria-label="جستجو" placeholder={role === "admin" ? "جستجوی کاربر، شماره یا تراکنش" : "جستجو در پیام‌ها و مخاطبین"} />
        </div>
      </div>
      {role === "user" ? (
        // Placeholder until the wallet API is wired up (a later task).
        <a className="ns-credit" href="#u-wallet" aria-label="اعتبار حساب">
          <Icon name="wallet" />
          <span className="ns-num">
            — <span className="lbl">ریال</span>
          </span>
        </a>
      ) : null}
      <button type="button" className="ns-btn ns-btn-ghost ns-btn-icon" aria-label="تغییر تم" onClick={onTheme}>
        <Icon name="eye" />
      </button>
      <a className="ns-btn ns-btn-ghost ns-btn-icon" aria-label="اعلان‌ها" href="#u-notifications">
        <Icon name="bell" />
      </a>
      <span className="ns-avatar" aria-hidden="true">
        {role === "admin" ? "م" : "ک"}
      </span>
    </header>
  );
}
