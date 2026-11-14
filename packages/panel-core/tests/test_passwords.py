from payamakyar.core.passwords import (
    hash_password,
    needs_rehash,
    password_problems,
    verify_password,
)


def test_password_policy() -> None:
    assert password_problems("Ab1!xyzw") == []
    assert set(password_problems("abc")) == {"TOO_SHORT", "NO_UPPER", "NO_DIGIT", "NO_SPECIAL"}


def test_persian_letters_are_not_letters_or_specials() -> None:
    assert set(password_problems("سلامسلام")) == {"NO_UPPER", "NO_LOWER", "NO_DIGIT", "NO_SPECIAL"}
    assert "NO_SPECIAL" in password_problems("Ab1 xyzw")


def test_min_length_is_a_parameter() -> None:
    assert "TOO_SHORT" in password_problems("Ab1!xyzw", min_length=12)
    assert password_problems("Ab1!", min_length=4) == []


def test_hash_verify_rehash() -> None:
    h = hash_password("Ab1!xyzw")
    assert h.startswith("$argon2id$") and "m=19456,t=2,p=1" in h
    assert verify_password(h, "Ab1!xyzw")
    assert not verify_password(h, "wrong")
    assert not verify_password("not-a-hash", "x")
    assert not needs_rehash(h)
    from argon2 import PasswordHasher

    assert needs_rehash(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("x"))
