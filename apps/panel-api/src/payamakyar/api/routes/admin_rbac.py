"""RBAC admin API: the permission catalog, roles and user role assignment."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payamakyar.api.deps import CurrentUser, Permissions, SessionDep, client_ip, forbidden, require
from payamakyar.api.errors import ApiError, validation_failed
from payamakyar.core.permissions import ADMIN_ROLE, STAFF_CODES, SYSTEM_ROLES, permission_codes
from payamakyar.db import audit
from payamakyar.db.models import Permission, Role, RolePermission, User, UserRole

router = APIRouter(tags=["admin-rbac"], dependencies=[require("roles.manage")])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PermissionOut(BaseModel):
    code: str
    title_fa: str
    group: str


class PermissionList(BaseModel):
    items: list[PermissionOut]


class RoleOut(BaseModel):
    id: uuid.UUID
    code: str
    title_fa: str
    is_staff: bool
    is_system: bool
    permissions: list[str]


class RoleList(BaseModel):
    items: list[RoleOut]


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,31}$")]
    title_fa: Title
    permissions: list[str] = Field(default_factory=list, max_length=200)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_fa: Title
    permissions: list[str] = Field(default_factory=list, max_length=200)


class UserRolesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[str] = Field(max_length=50)


class UserRolesOut(BaseModel):
    user_id: uuid.UUID
    roles: list[str]


def _not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} یافت نشد", f"{what} مورد نظر وجود ندارد.")


def _is_staff(codes: list[str]) -> bool:
    return any(c in STAFF_CODES for c in codes)


def _is_full(perms: frozenset[str]) -> bool:
    """Admin-equivalent: holds every permission, so no delegation bound applies."""
    return permission_codes() <= perms


def _outside(actor_perms: frozenset[str], codes: list[str], pointer: str) -> ApiError:
    return forbidden("شما نمی‌توانید دسترسی‌ای را مدیریت کنید که خودتان ندارید.", pointer=pointer)


def _bound_new(actor_perms: frozenset[str], codes: list[str]) -> None:
    """Every permission in ``codes`` must be one the actor holds (admin: no bound)."""
    if _is_full(actor_perms):
        return
    for i, code in enumerate(codes):
        if code not in actor_perms:
            raise _outside(actor_perms, codes, f"/permissions/{i}")


def _check_permissions(codes: list[str]) -> list[str]:
    known = permission_codes()
    for i, code in enumerate(codes):
        if code not in known:
            raise validation_failed("کد دسترسی ناشناخته است.", f"/permissions/{i}")
    return sorted(set(codes))


async def _role_permissions(s: AsyncSession, role_id: uuid.UUID) -> list[str]:
    rows = await s.execute(
        select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
    )
    return sorted(rows.scalars())


def _snapshot(role: Role, permissions: list[str]) -> dict[str, Any]:
    return {
        "code": role.name,
        "title_fa": role.title_fa,
        "is_staff": role.is_staff,
        "permissions": permissions,
    }


async def _out(s: AsyncSession, role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        code=role.name,
        title_fa=role.title_fa,
        is_staff=role.is_staff,
        is_system=role.name in SYSTEM_ROLES,
        permissions=await _role_permissions(s, role.id),
    )


async def _lock_admin_role(s: AsyncSession) -> uuid.UUID:
    """Serialise role changes (last-admin and lock-out checks) on the admin role row."""
    return (
        await s.execute(select(Role.id).where(Role.name == ADMIN_ROLE).with_for_update())
    ).scalar_one()


def _lockout(pointer: str) -> ApiError:
    return ApiError(
        409,
        "WOULD_LOCK_YOU_OUT",
        "این تغییر دسترسی مدیریت نقش‌ها را از شما می‌گیرد",
        "شما نمی‌توانید دسترسی خودتان به مدیریت نقش‌ها را حذف کنید.",
        pointer,
    )


async def _get_role(s: AsyncSession, role_id: uuid.UUID, *, lock: bool = False) -> Role:
    stmt = select(Role).where(Role.id == role_id)
    if lock:
        stmt = stmt.with_for_update()
    role = (await s.execute(stmt)).scalar_one_or_none()
    if role is None:
        raise _not_found("نقش")
    return role


@router.get("/permissions")
async def list_permissions(s: SessionDep) -> PermissionList:
    rows = await s.execute(select(Permission).order_by(Permission.group, Permission.code))
    return PermissionList(
        items=[
            PermissionOut(code=p.code, title_fa=p.title_fa, group=p.group) for p in rows.scalars()
        ]
    )


@router.get("/roles")
async def list_roles(s: SessionDep) -> RoleList:
    roles = (await s.execute(select(Role).order_by(Role.name))).scalars().all()
    grants: dict[uuid.UUID, list[str]] = {}
    for rid, code in (
        await s.execute(
            select(RolePermission.role_id, RolePermission.permission_code).order_by(
                RolePermission.permission_code
            )
        )
    ).all():
        grants.setdefault(rid, []).append(code)
    return RoleList(
        items=[
            RoleOut(
                id=r.id,
                code=r.name,
                title_fa=r.title_fa,
                is_staff=r.is_staff,
                is_system=r.name in SYSTEM_ROLES,
                permissions=grants.get(r.id, []),
            )
            for r in roles
        ]
    )


@router.post("/roles", status_code=201)
async def create_role(
    body: RoleCreate,
    request: Request,
    s: SessionDep,
    actor: CurrentUser,
    actor_perms: Permissions,
) -> RoleOut:
    codes = _check_permissions(body.permissions)
    _bound_new(actor_perms, body.permissions)
    role = Role(name=body.code, title_fa=body.title_fa, is_staff=_is_staff(codes))
    taken = ApiError(
        409, "ROLE_CODE_TAKEN", "این کد نقش قبلاً گرفته شده است", "کد دیگری انتخاب کنید.", "/code"
    )
    if (await s.execute(select(Role.id).where(Role.name == body.code))).first() is not None:
        raise taken
    try:
        async with s.begin_nested():
            s.add(role)
            await s.flush()
    except IntegrityError:
        raise taken from None
    s.add_all(RolePermission(role_id=role.id, permission_code=c) for c in codes)
    await s.flush()
    await audit.record(
        s,
        actor_id=actor.id,
        actor_ip=client_ip(request) or None,
        action="role.create",
        target_type="role",
        target_id=str(role.id),
        after=_snapshot(role, codes),
    )
    return await _out(s, role)


@router.put("/roles/{role_id}")
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    request: Request,
    s: SessionDep,
    actor: CurrentUser,
    actor_perms: Permissions,
) -> RoleOut:
    await _lock_admin_role(s)
    role = await _get_role(s, role_id, lock=True)
    codes = _check_permissions(body.permissions)
    old_codes = await _role_permissions(s, role.id)
    _bound_new(actor_perms, body.permissions)
    if not _is_full(actor_perms) and not set(old_codes) <= actor_perms:
        raise _outside(actor_perms, old_codes, "/permissions")
    if role.name == ADMIN_ROLE and set(codes) != permission_codes():
        raise ApiError(
            409,
            "ADMIN_ROLE_PROTECTED",
            "مجوزهای نقش مدیر کل قابل کاهش نیست",
            "نقش مدیر کل باید همه دسترسی‌ها را داشته باشد.",
            "/permissions",
        )
    held = (
        await s.execute(
            select(UserRole.role_id).where(
                UserRole.user_id == actor.id, UserRole.role_id != role.id
            )
        )
    ).scalars()
    kept = (
        set(codes)
        if (
            await s.execute(
                select(UserRole).where(UserRole.user_id == actor.id, UserRole.role_id == role.id)
            )
        ).first()
        else set()
    )
    other = set(
        (
            await s.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id.in_(list(held)))
            )
        ).scalars()
    )
    if "roles.manage" in actor_perms and "roles.manage" not in kept | other:
        raise _lockout("/permissions")
    before = _snapshot(role, old_codes)
    role.title_fa = body.title_fa
    role.is_staff = _is_staff(codes)
    await s.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    s.add_all(RolePermission(role_id=role.id, permission_code=c) for c in codes)
    await s.flush()
    await audit.record(
        s,
        actor_id=actor.id,
        actor_ip=client_ip(request) or None,
        action="role.update",
        target_type="role",
        target_id=str(role.id),
        before=before,
        after=_snapshot(role, codes),
    )
    return await _out(s, role)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: uuid.UUID, request: Request, s: SessionDep, actor: CurrentUser
) -> Response:
    role = await _get_role(s, role_id, lock=True)
    if role.name in SYSTEM_ROLES:
        raise ApiError(
            409,
            "ROLE_IS_SYSTEM",
            "نقش‌های پیش‌فرض قابل حذف نیستند",
            "این نقش جزو نقش‌های سامانه است.",
        )
    used = (
        await s.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        )
    ).scalar_one()
    if used:
        raise ApiError(
            409,
            "ROLE_IN_USE",
            "این نقش به کاربرانی داده شده است",
            "ابتدا نقش را از کاربران بردارید.",
        )
    before = _snapshot(role, await _role_permissions(s, role.id))
    await s.delete(role)
    await s.flush()
    await audit.record(
        s,
        actor_id=actor.id,
        actor_ip=client_ip(request) or None,
        action="role.delete",
        target_type="role",
        target_id=str(role_id),
        before=before,
    )
    return Response(status_code=204)


async def _user_role_names(s: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await s.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return sorted(rows.scalars())


@router.put("/users/{user_id}/roles")
async def set_user_roles(
    user_id: uuid.UUID,
    body: UserRolesBody,
    request: Request,
    s: SessionDep,
    actor: CurrentUser,
    actor_perms: Permissions,
) -> UserRolesOut:
    target = await s.get(User, user_id)
    if target is None:
        raise _not_found("کاربر")
    wanted = sorted(set(body.roles))
    found = {
        r.name: r for r in (await s.execute(select(Role).where(Role.name.in_(wanted)))).scalars()
    }
    for i, code in enumerate(body.roles):
        if code not in found:
            raise validation_failed("نقش ناشناخته است.", f"/roles/{i}")
    # Serialise role changes so the last-admin check cannot race.
    admin_role_id = await _lock_admin_role(s)
    before = await _user_role_names(s, user_id)
    if not _is_full(actor_perms):
        # Adding or removing a role is allowed only if its permissions are within the actor's.
        changed = set(before) ^ set(wanted)
        grants: dict[str, set[str]] = {}
        for name, code in (
            await s.execute(
                select(Role.name, RolePermission.permission_code)
                .join(RolePermission, RolePermission.role_id == Role.id)
                .where(Role.name.in_(changed))
            )
        ).all():
            grants.setdefault(name, set()).add(code)
        for name in sorted(changed):
            if not grants.get(name, set()) <= actor_perms:
                index = body.roles.index(name) if name in body.roles else None
                raise forbidden(
                    "شما نمی‌توانید نقشی را که دسترسی‌های بیشتری از شما دارد تخصیص دهید یا بردارید.",
                    pointer=f"/roles/{index}" if index is not None else "/roles",
                )
    if actor.id == user_id:
        new_perms = set(
            (
                await s.execute(
                    select(RolePermission.permission_code).where(
                        RolePermission.role_id.in_([r.id for r in found.values()])
                    )
                )
            ).scalars()
        )
        if "roles.manage" not in new_perms:
            raise _lockout("/roles")
    if ADMIN_ROLE in before and ADMIN_ROLE not in found:
        others = (
            await s.execute(
                select(func.count())
                .select_from(UserRole)
                .join(User, User.id == UserRole.user_id)
                .where(
                    UserRole.role_id == admin_role_id,
                    UserRole.user_id != user_id,
                    User.status == "active",
                )
            )
        ).scalar_one()
        if not others:
            raise ApiError(
                409,
                "LAST_ADMIN_REQUIRED",
                "آخرین مدیر کل نمی‌تواند این نقش را از دست بدهد",
                "ابتدا مدیر کل دیگری تعیین کنید.",
                "/roles",
            )
    await s.execute(delete(UserRole).where(UserRole.user_id == user_id))
    s.add_all(UserRole(user_id=user_id, role_id=r.id) for r in found.values())
    await s.flush()
    await audit.record(
        s,
        actor_id=actor.id,
        actor_ip=client_ip(request) or None,
        action="user.roles.update",
        target_type="user",
        target_id=str(user_id),
        before={"roles": before},
        after={"roles": wanted},
    )
    return UserRolesOut(user_id=user_id, roles=wanted)
