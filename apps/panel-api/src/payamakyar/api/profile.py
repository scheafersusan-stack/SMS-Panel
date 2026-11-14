"""Profile validation, completeness and the ``/account/me`` view."""

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel

from payamakyar.api.errors import ApiError, validation_failed
from payamakyar.core.gates import Capabilities, Gates, capabilities
from payamakyar.core.masking import mask_secret
from payamakyar.core.national_id import is_valid_company_id, is_valid_national_code
from payamakyar.core.phone import to_ascii_digits
from payamakyar.db.models import User

PERSON_FIELDS = (
    "first_name",
    "last_name",
    "national_code",
    "birth_date",
    "email",
    "phone",
    "postal_code",
    "address",
)
COMPANY_FIELDS = (
    "company_name",
    "company_national_id",
    "economic_code",
    "ceo_name",
    "ceo_national_code",
    "postal_code",
    "address",
)
ALL_FIELDS = tuple(dict.fromkeys(PERSON_FIELDS + COMPANY_FIELDS))
# email and phone are optional contact details; everything else is needed for a complete profile.
REQUIRED = {
    "person": (
        "first_name",
        "last_name",
        "national_code",
        "birth_date",
        "postal_code",
        "address",
    ),
    "company": COMPANY_FIELDS,
}
IDENTITY_FIELDS = frozenset({"national_code", "birth_date"})
_MASKED = frozenset({"national_code", "company_national_id", "ceo_national_code"})
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]+")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def fields_for(kind: str) -> tuple[str, ...]:
    return COMPANY_FIELDS if kind == "company" else PERSON_FIELDS


def _bad(field: str, detail: str) -> ApiError:
    return validation_failed(detail, f"/{field}")


def _text(field: str, value: str, label: str, max_len: int) -> str:
    if len(value) > max_len:
        raise _bad(field, f"{label} بیش از حد طولانی است.")
    return value


def _digits(field: str, value: str, label: str, pattern: str) -> str:
    d = to_ascii_digits(value).replace(" ", "")
    if not re.fullmatch(pattern, d):
        raise _bad(field, f"{label} نامعتبر است.")
    return d


def normalise(field: str, value: str, today: date) -> Any:
    """Validate one non-empty string and return its stored form (date for birth_date)."""
    v = value.strip()
    if field in ("first_name", "last_name", "ceo_name"):
        return _text(field, v, "نام", 100)
    if field == "company_name":
        return _text(field, v, "نام شرکت", 200)
    if field == "address":
        return _text(field, v, "نشانی", 500)
    if field in ("national_code", "ceo_national_code"):
        d = to_ascii_digits(v)
        if not is_valid_national_code(d):
            raise _bad(field, "کد ملی نامعتبر است.")
        return d
    if field == "company_national_id":
        d = to_ascii_digits(v)
        if not is_valid_company_id(d):
            raise _bad(field, "شناسه ملی شرکت نامعتبر است.")
        return d
    if field == "economic_code":
        return _digits(field, v, "کد اقتصادی", r"[0-9]{10,14}")
    if field == "postal_code":
        return _digits(field, v, "کد پستی", r"[0-9]{10}")
    if field == "phone":
        return _digits(field, v, "شماره تلفن", r"0[0-9]{8,10}")
    if field == "email":
        e = v.lower()
        if len(e) > 254 or not _EMAIL.fullmatch(e):
            raise _bad(field, "نشانی ایمیل نامعتبر است.")
        return e
    if field == "birth_date":
        d = to_ascii_digits(v)
        if not _DATE.fullmatch(d):
            raise _bad(field, "تاریخ تولد باید به شکل YYYY-MM-DD باشد.")
        try:
            born = date.fromisoformat(d)
        except ValueError:
            raise _bad(field, "تاریخ تولد نامعتبر است.") from None
        if born > today or born.year < 1900:
            raise _bad(field, "تاریخ تولد نامعتبر است.")
        return born
    raise _bad(field, "فیلد ناشناخته است.")


def today_utc(now: datetime) -> date:
    return now.astimezone(UTC).date()


def display(field: str, value: Any) -> Any:
    """Audit-safe form of a field value: national ids and birth date are masked."""
    if value is None:
        return None
    if field in _MASKED:
        return mask_secret(str(value))
    if field == "birth_date":
        return "****"
    return value.isoformat() if isinstance(value, date) else value


def is_complete(user: User) -> bool:
    return all(getattr(user, f) not in (None, "") for f in REQUIRED.get(user.kind, ()))


class GatesOut(BaseModel):
    registered: bool
    profile_complete: bool
    identity_matched: bool
    documents_approved: bool


class CapabilitiesOut(BaseModel):
    can_send: bool
    can_buy_line: bool
    can_use_service_line_and_links: bool


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    mobile: str
    kind: str
    status: str
    identity_state: str
    documents_state: str
    first_name: str | None
    last_name: str | None
    national_code: str | None
    birth_date: date | None
    email: str | None
    phone: str | None
    postal_code: str | None
    address: str | None
    company_name: str | None
    company_national_id: str | None
    economic_code: str | None
    ceo_name: str | None
    ceo_national_code: str | None
    mfa_method: str
    roles: list[str]
    permissions: list[str]
    gates: GatesOut
    capabilities: CapabilitiesOut


def build_me(user: User, roles: list[str], perms: frozenset[str]) -> MeOut:
    g = Gates(
        registered=True,
        profile_complete=is_complete(user),
        identity_matched=user.identity_state == "matched",
        documents_approved=user.documents_state == "approved",
    )
    caps: Capabilities = capabilities(g)
    return MeOut(
        id=user.id,
        username=user.username,
        mobile=user.mobile,
        kind=user.kind,
        status=user.status,
        identity_state=user.identity_state,
        documents_state=user.documents_state,
        mfa_method=user.mfa_method,
        roles=roles,
        permissions=sorted(perms),
        gates=GatesOut(**vars(g)),
        capabilities=CapabilitiesOut(**vars(caps)),
        **{f: getattr(user, f) for f in ALL_FIELDS},
    )
