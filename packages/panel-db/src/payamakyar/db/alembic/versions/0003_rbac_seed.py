"""Seed the permission catalog and the system roles.

The data below is a frozen copy: later catalog changes need their own migration.

Revision ID: 0003
Revises: 0002
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PERMISSIONS = [
    ("users.view", "مشاهده کاربران", "users"),
    ("users.edit", "ویرایش کاربران", "users"),
    ("users.impersonate", "ورود به\u200cجای کاربر", "users"),
    ("users.credit.adjust", "تعدیل اعتبار کاربر", "users"),
    ("kyc.review", "بررسی احراز هویت", "verification"),
    ("documents.catalog", "مدیریت فهرست مدارک", "verification"),
    ("patterns.review", "بررسی الگوهای پیام", "moderation"),
    ("moderation.review", "بررسی محتوای پیام\u200cها", "moderation"),
    ("line_orders.review", "بررسی سفارش خط", "lines"),
    ("lines.manage", "مدیریت خطوط", "lines"),
    ("upstreams.manage", "مدیریت اپراتورهای بالادستی", "lines"),
    ("routes.manage", "مدیریت مسیرهای ارسال", "lines"),
    ("pricing.manage", "مدیریت تعرفه\u200cها", "finance"),
    ("finance.view", "مشاهده امور مالی", "finance"),
    ("finance.receipts.approve", "تأیید فیش\u200cهای واریزی", "finance"),
    ("finance.refund", "بازپرداخت وجه", "finance"),
    ("tickets.view", "مشاهده تیکت\u200cها", "support"),
    ("tickets.reply", "پاسخ به تیکت\u200cها", "support"),
    ("system_sms.manage", "مدیریت پیامک\u200cهای سامانه", "support"),
    ("announcements.manage", "مدیریت اطلاعیه\u200cها", "support"),
    ("roles.manage", "مدیریت نقش\u200cها و دسترسی\u200cها", "system"),
    ("audit.view", "مشاهده گزارش حسابرسی", "system"),
    ("settings.manage", "مدیریت تنظیمات سامانه", "system"),
    ("guard_policy.manage", "مدیریت سیاست\u200cهای نگهبان", "system"),
    ("traffic.view", "مشاهده ترافیک", "traffic"),
    ("traffic.kill_switch", "قطع اضطراری ترافیک", "traffic"),
    ("resellers.manage", "مدیریت نمایندگان", "resellers"),
    ("content_filter.manage", "مدیریت فیلتر محتوا", "moderation"),
    ("number_bank.manage", "مدیریت بانک شماره", "lines"),
    ("send.single", "ارسال تکی", "customer"),
    ("send.bulk", "ارسال انبوه", "customer"),
    ("send.pattern", "ارسال الگویی", "customer"),
    ("contacts.manage", "مدیریت مخاطبان", "customer"),
    ("templates.manage", "مدیریت قالب\u200cهای پیام", "customer"),
    ("inbox.view", "مشاهده صندوق دریافت", "customer"),
    ("rules.manage", "مدیریت قوانین خودکار", "customer"),
    ("api.manage", "مدیریت وب\u200cسرویس و کلیدها", "customer"),
    ("wallet.pay", "پرداخت از کیف پول", "customer"),
    ("tickets.create", "ثبت تیکت", "customer"),
    ("resellers.subusers", "مدیریت کاربران زیرمجموعه", "customer"),
]

ROLES = {
    "customer": (
        "مشتری",
        False,
        [
            "send.single",
            "send.bulk",
            "send.pattern",
            "contacts.manage",
            "templates.manage",
            "inbox.view",
            "rules.manage",
            "api.manage",
            "wallet.pay",
            "tickets.create",
        ],
    ),
    "reseller": (
        "نماینده",
        False,
        [
            "send.single",
            "send.bulk",
            "send.pattern",
            "contacts.manage",
            "templates.manage",
            "inbox.view",
            "rules.manage",
            "api.manage",
            "wallet.pay",
            "tickets.create",
            "resellers.subusers",
        ],
    ),
    "staff_moderation": (
        "کارشناس نظارت",
        True,
        [
            "users.view",
            "kyc.review",
            "documents.catalog",
            "patterns.review",
            "moderation.review",
            "line_orders.review",
            "traffic.view",
            "content_filter.manage",
            "audit.view",
        ],
    ),
    "staff_finance": (
        "کارشناس مالی",
        True,
        [
            "users.view",
            "users.credit.adjust",
            "finance.view",
            "finance.receipts.approve",
            "finance.refund",
            "pricing.manage",
            "audit.view",
        ],
    ),
    "staff_support": (
        "کارشناس پشتیبانی",
        True,
        [
            "users.view",
            "tickets.view",
            "tickets.reply",
            "announcements.manage",
            "system_sms.manage",
        ],
    ),
    "admin": (
        "مدیر کل",
        True,
        [
            "users.view",
            "users.edit",
            "users.impersonate",
            "users.credit.adjust",
            "kyc.review",
            "documents.catalog",
            "patterns.review",
            "moderation.review",
            "line_orders.review",
            "lines.manage",
            "upstreams.manage",
            "routes.manage",
            "pricing.manage",
            "finance.view",
            "finance.receipts.approve",
            "finance.refund",
            "tickets.view",
            "tickets.reply",
            "system_sms.manage",
            "announcements.manage",
            "roles.manage",
            "audit.view",
            "settings.manage",
            "guard_policy.manage",
            "traffic.view",
            "traffic.kill_switch",
            "resellers.manage",
            "content_filter.manage",
            "number_bank.manage",
            "send.single",
            "send.bulk",
            "send.pattern",
            "contacts.manage",
            "templates.manage",
            "inbox.view",
            "rules.manage",
            "api.manage",
            "wallet.pay",
            "tickets.create",
            "resellers.subusers",
        ],
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, title, group in PERMISSIONS:
        conn.execute(
            sa.text(
                'INSERT INTO permissions (code, title_fa, "group") VALUES (:c, :t, :g) '
                "ON CONFLICT (code) DO UPDATE SET title_fa = EXCLUDED.title_fa, "
                '"group" = EXCLUDED."group"'
            ),
            {"c": code, "t": title, "g": group},
        )
    for name, (title, is_staff, codes) in ROLES.items():
        role_id = conn.execute(
            sa.text(
                "INSERT INTO roles (id, name, title_fa, is_staff) VALUES (:i, :n, :t, :s) "
                "ON CONFLICT (name) DO UPDATE SET title_fa = EXCLUDED.title_fa, "
                "is_staff = EXCLUDED.is_staff RETURNING id"
            ),
            {"i": uuid.uuid4(), "n": name, "t": title, "s": is_staff},
        ).scalar_one()
        for code in codes:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_code) VALUES (:r, :c) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"r": role_id, "c": code},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for name in ROLES:
        if name == "customer":
            # Created by registration before this migration: keep the row and its assignments.
            conn.execute(
                sa.text(
                    "DELETE FROM role_permissions WHERE role_id IN "
                    "(SELECT id FROM roles WHERE name = :n)"
                ),
                {"n": name},
            )
            continue
        used = conn.execute(
            sa.text(
                "SELECT count(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE r.name = :n"
            ),
            {"n": name},
        ).scalar_one()
        if used:
            raise RuntimeError(
                f"cannot downgrade 0003: role {name!r} is still assigned to {used} user(s); "
                "unassign it first"
            )
        conn.execute(sa.text("DELETE FROM roles WHERE name = :n"), {"n": name})
    for code, _, _ in PERMISSIONS:
        conn.execute(sa.text("DELETE FROM permissions WHERE code = :c"), {"c": code})
