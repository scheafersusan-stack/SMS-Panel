"""The permission catalog and the seeded (system) roles.

Migration 0003 seeds exactly this data (as a frozen copy); tests keep both in step.
Staff permissions gate ``/panel/admin/v1``; customer-side permissions are the capabilities of
panel users and never open an admin route on their own.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    code: str
    title_fa: str
    group: str


@dataclass(frozen=True)
class RoleSpec:
    title_fa: str
    is_staff: bool
    permissions: tuple[str, ...]


CUSTOMER_GROUP = "customer"

_STAFF: tuple[Permission, ...] = (
    Permission("users.view", "مشاهده کاربران", "users"),
    Permission("users.edit", "ویرایش کاربران", "users"),
    Permission("users.impersonate", "ورود به‌جای کاربر", "users"),
    Permission("users.credit.adjust", "تعدیل اعتبار کاربر", "users"),
    Permission("kyc.review", "بررسی احراز هویت", "verification"),
    Permission("documents.catalog", "مدیریت فهرست مدارک", "verification"),
    Permission("patterns.review", "بررسی الگوهای پیام", "moderation"),
    Permission("moderation.review", "بررسی محتوای پیام‌ها", "moderation"),
    Permission("line_orders.review", "بررسی سفارش خط", "lines"),
    Permission("lines.manage", "مدیریت خطوط", "lines"),
    Permission("upstreams.manage", "مدیریت اپراتورهای بالادستی", "lines"),
    Permission("routes.manage", "مدیریت مسیرهای ارسال", "lines"),
    Permission("pricing.manage", "مدیریت تعرفه‌ها", "finance"),
    Permission("finance.view", "مشاهده امور مالی", "finance"),
    Permission("finance.receipts.approve", "تأیید فیش‌های واریزی", "finance"),
    Permission("finance.refund", "بازپرداخت وجه", "finance"),
    Permission("tickets.view", "مشاهده تیکت‌ها", "support"),
    Permission("tickets.reply", "پاسخ به تیکت‌ها", "support"),
    Permission("system_sms.manage", "مدیریت پیامک‌های سامانه", "support"),
    Permission("announcements.manage", "مدیریت اطلاعیه‌ها", "support"),
    Permission("roles.manage", "مدیریت نقش‌ها و دسترسی‌ها", "system"),
    Permission("audit.view", "مشاهده گزارش حسابرسی", "system"),
    Permission("settings.manage", "مدیریت تنظیمات سامانه", "system"),
    Permission("guard_policy.manage", "مدیریت سیاست‌های نگهبان", "system"),
    Permission("traffic.view", "مشاهده ترافیک", "traffic"),
    Permission("traffic.kill_switch", "قطع اضطراری ترافیک", "traffic"),
    Permission("resellers.manage", "مدیریت نمایندگان", "resellers"),
    Permission("content_filter.manage", "مدیریت فیلتر محتوا", "moderation"),
    Permission("number_bank.manage", "مدیریت بانک شماره", "lines"),
)

_CUSTOMER: tuple[Permission, ...] = (
    Permission("send.single", "ارسال تکی", CUSTOMER_GROUP),
    Permission("send.bulk", "ارسال انبوه", CUSTOMER_GROUP),
    Permission("send.pattern", "ارسال الگویی", CUSTOMER_GROUP),
    Permission("contacts.manage", "مدیریت مخاطبان", CUSTOMER_GROUP),
    Permission("templates.manage", "مدیریت قالب‌های پیام", CUSTOMER_GROUP),
    Permission("inbox.view", "مشاهده صندوق دریافت", CUSTOMER_GROUP),
    Permission("rules.manage", "مدیریت قوانین خودکار", CUSTOMER_GROUP),
    Permission("api.manage", "مدیریت وب‌سرویس و کلیدها", CUSTOMER_GROUP),
    Permission("wallet.pay", "پرداخت از کیف پول", CUSTOMER_GROUP),
    Permission("tickets.create", "ثبت تیکت", CUSTOMER_GROUP),
    Permission("resellers.subusers", "مدیریت کاربران زیرمجموعه", CUSTOMER_GROUP),
)

PERMISSIONS: tuple[Permission, ...] = _STAFF + _CUSTOMER
CUSTOMER_SIDE_CODES: frozenset[str] = frozenset(p.code for p in _CUSTOMER)
STAFF_CODES: frozenset[str] = frozenset(p.code for p in _STAFF)

_CUSTOMER_ORDER = tuple(p.code for p in _CUSTOMER)

SYSTEM_ROLES: dict[str, RoleSpec] = {
    "customer": RoleSpec(
        "مشتری", False, tuple(c for c in _CUSTOMER_ORDER if c != "resellers.subusers")
    ),
    "reseller": RoleSpec("نماینده", False, _CUSTOMER_ORDER),
    "staff_moderation": RoleSpec(
        "کارشناس نظارت",
        True,
        (
            "users.view",
            "kyc.review",
            "documents.catalog",
            "patterns.review",
            "moderation.review",
            "line_orders.review",
            "traffic.view",
            "content_filter.manage",
            "audit.view",
        ),
    ),
    "staff_finance": RoleSpec(
        "کارشناس مالی",
        True,
        (
            "users.view",
            "users.credit.adjust",
            "finance.view",
            "finance.receipts.approve",
            "finance.refund",
            "pricing.manage",
            "audit.view",
        ),
    ),
    "staff_support": RoleSpec(
        "کارشناس پشتیبانی",
        True,
        (
            "users.view",
            "tickets.view",
            "tickets.reply",
            "announcements.manage",
            "system_sms.manage",
        ),
    ),
    "admin": RoleSpec("مدیر کل", True, tuple(p.code for p in PERMISSIONS)),
}

ADMIN_ROLE = "admin"


def permission_codes() -> frozenset[str]:
    return frozenset(p.code for p in PERMISSIONS)
