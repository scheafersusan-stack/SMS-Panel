"""Foundation schema: users, sessions, OTP, RBAC, audit, settings, messages, jobs.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default="ready", nullable=False),
        sa.Column(
            "run_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("lease_until", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('ready', 'running', 'done', 'dead')", name=op.f("ck_jobs_state")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_jobs_dedupe_key")),
    )
    op.create_index("ix_jobs_state_run_at", "jobs", ["state", "run_at"], unique=False)
    op.create_table(
        "permissions",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title_fa", sa.Text(), nullable=False),
        sa.Column("group", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_permissions")),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("title_fa", sa.Text(), nullable=False),
        sa.Column("is_staff", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_sale_package", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=0), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("name", name=op.f("uq_roles_name")),
    )
    op.create_table(
        "system_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("to_mobile", sa.Text(), nullable=False),
        sa.Column("template_key", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')", name=op.f("ck_system_messages_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_messages")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), server_default="person", nullable=False),
        sa.Column("username", postgresql.CITEXT(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("send_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "document_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("identity_state", sa.Text(), server_default="none", nullable=False),
        sa.Column("documents_state", sa.Text(), server_default="none", nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("national_code", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("company_name", sa.Text(), nullable=True),
        sa.Column("company_national_id", sa.Text(), nullable=True),
        sa.Column("economic_code", sa.Text(), nullable=True),
        sa.Column("ceo_name", sa.Text(), nullable=True),
        sa.Column("ceo_national_code", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("mfa_method", sa.Text(), server_default="none", nullable=False),
        sa.Column("totp_secret_sealed", sa.Text(), nullable=True),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column("login_notice", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allowed_ips", postgresql.ARRAY(postgresql.CIDR()), nullable=True),
        sa.Column("login_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_login_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "documents_state IN ('none', 'pending', 'approved', 'rejected')",
            name=op.f("ck_users_documents_state"),
        ),
        sa.CheckConstraint(
            "identity_state IN ('none', 'pending', 'matched', 'mismatch', 'manual_review')",
            name=op.f("ck_users_identity_state"),
        ),
        sa.CheckConstraint("kind IN ('person', 'company')", name=op.f("ck_users_kind")),
        sa.CheckConstraint(
            "mfa_method IN ('none', 'totp', 'sms')", name=op.f("ck_users_mfa_method")
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name=op.f("ck_users_status")),
        sa.ForeignKeyConstraint(["parent_id"], ["users.id"], name=op.f("fk_users_parent_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("mobile", name=op.f("uq_users_mobile")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_ip", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=True),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"], unique=False)
    op.create_table(
        "login_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("username_tried", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column(
            "at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_login_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_events")),
    )
    op.create_index(op.f("ix_login_events_user_id"), "login_events", ["user_id"], unique=False)
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("mobile", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("consumed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('register', 'login', 'reset', 'mobile_change')",
            name=op.f("ck_otp_challenges_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_otp_challenges_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenges")),
    )
    op.create_index(op.f("ix_otp_challenges_mobile"), "otp_challenges", ["mobile"], unique=False)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["permissions.code"],
            name=op.f("fk_role_permissions_permission_code_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_hash", sa.Text(), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("impersonator_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["impersonator_id"], ["users.id"], name=op.f("fk_sessions_impersonator_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_user_roles_role_id_roles"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("settings")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("role_permissions")
    op.drop_index(op.f("ix_otp_challenges_mobile"), table_name="otp_challenges")
    op.drop_table("otp_challenges")
    op.drop_index(op.f("ix_login_events_user_id"), table_name="login_events")
    op.drop_table("login_events")
    op.drop_index(op.f("ix_audit_events_action"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("users")
    op.drop_table("system_messages")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_index("ix_jobs_state_run_at", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DROP EXTENSION IF EXISTS citext")
