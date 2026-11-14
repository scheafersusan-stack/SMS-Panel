// The navigation tree, copied from the prototype's NAV object: [section label, items].
// An item is { id (hash route), label, icon, count? } where count is a placeholder unread badge.
export interface NavItem {
  id: string;
  label: string;
  icon: string;
  count?: string;
}
export interface NavSection {
  label: string;
  items: NavItem[];
}

const item = (id: string, label: string, icon: string, count?: string): NavItem =>
  count ? { id, label, icon, count } : { id, label, icon };

export const NAV: { user: NavSection[]; admin: NavSection[] } = {
  user: [
    { label: "", items: [item("u-dashboard", "داشبورد", "home")] },
    {
      label: "ارسال",
      items: [
        item("u-send", "ارسال سریع", "send"),
        item("u-bulk", "ارسال گروهی", "users"),
        item("u-otp", "ارسال با الگو (OTP)", "key"),
        item("u-numberbank", "بانک شماره", "filter"),
        item("u-scheduled", "زمان‌بندی‌شده‌ها", "calendar"),
      ],
    },
    {
      label: "پیام‌ها",
      items: [
        item("u-outbox", "گزارش ارسال‌ها", "chart"),
        item("u-inbox", "صندوق دریافت", "inbox", "۱۲"),
        item("u-rules", "پاسخ خودکار و قواعد", "settings"),
      ],
    },
    {
      label: "مخاطبان",
      items: [
        item("u-contacts", "دفترچه تلفن", "users"),
        item("u-import", "ورود از اکسل", "upload"),
        item("u-stoplist", "لیست توقف", "x-circle"),
      ],
    },
    {
      label: "ابزارها",
      items: [
        item("u-templates", "متن‌ها و الگوها", "template"),
        item("u-lines", "خطوط من", "phone"),
        item("u-api", "وب‌سرویس و وب‌هوک", "key"),
        item("u-resellers", "نمایندگی", "users"),
      ],
    },
    {
      label: "حساب",
      items: [
        item("u-wallet", "کیف پول", "wallet"),
        item("u-transactions", "تراکنش‌ها و فاکتور", "file"),
        item("u-tariffs", "تعرفه‌ها", "chart"),
        item("u-tickets", "پشتیبانی", "ticket"),
        item("u-notifications", "اعلان‌ها", "bell"),
        item("u-profile", "حساب و امنیت", "settings"),
      ],
    },
  ],
  admin: [
    { label: "", items: [item("a-dashboard", "داشبورد مدیریت", "home")] },
    {
      label: "صف‌های بررسی",
      items: [
        item("a-kyc", "احراز هویت", "file", "۷"),
        item("a-patterns", "بررسی الگوها", "template", "۴"),
        item("a-moderation", "پایش ارسال", "alert", "۳"),
        item("a-line-orders", "سفارش خط", "phone", "۲"),
      ],
    },
    {
      label: "کاربران",
      items: [
        item("a-users", "کاربران", "users"),
        item("a-resellers", "نمایندگان", "users"),
        item("a-tickets", "تیکت‌ها", "ticket", "۵"),
      ],
    },
    {
      label: "ارسال",
      items: [
        item("a-traffic", "ترافیک و صف", "chart"),
        item("a-upstreams", "بالادست‌ها و مسیریابی", "send"),
        item("a-lines", "خطوط و سرشماره‌ها", "phone"),
      ],
    },
    {
      label: "مالی",
      items: [
        item("a-finance", "تراکنش‌ها و بازگشت وجه", "wallet"),
        item("a-pricing", "تعرفه و قیمت‌گذاری", "chart"),
      ],
    },
    {
      label: "سیستم",
      items: [
        item("a-system-sms", "پیامک‌های سیستمی و اطلاعیه", "bell"),
        item("a-roles", "نقش‌ها و دسترسی", "key"),
        item("a-audit", "گزارش رویدادها", "file"),
        item("a-settings", "تنظیمات سامانه", "settings"),
      ],
    },
  ],
};
