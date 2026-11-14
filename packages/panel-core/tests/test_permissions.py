from payamakyar.core.permissions import (
    CUSTOMER_SIDE_CODES,
    PERMISSIONS,
    STAFF_CODES,
    SYSTEM_ROLES,
    permission_codes,
)


def test_staff_and_customer_partition_the_catalog() -> None:
    assert permission_codes() == STAFF_CODES | CUSTOMER_SIDE_CODES
    assert not STAFF_CODES & CUSTOMER_SIDE_CODES


def test_every_role_permission_is_in_the_catalog() -> None:
    for spec in SYSTEM_ROLES.values():
        assert set(spec.permissions) <= permission_codes()
        assert spec.title_fa


def test_persian_titles() -> None:
    assert all(p.title_fa and p.group for p in PERMISSIONS)
