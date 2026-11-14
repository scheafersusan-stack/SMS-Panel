"""Permissions, roles and their assignments."""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from payamakyar.core.ids import new_id
from payamakyar.db.base import Base


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    title_fa: Mapped[str] = mapped_column(Text)
    group: Mapped[str] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, unique=True)
    title_fa: Mapped[str] = mapped_column(Text)
    is_staff: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_sale_package: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 0))


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
