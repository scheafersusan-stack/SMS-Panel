import pyotp

from payamakyar.core.totp import new_totp_secret, totp_uri, verify_totp


def test_totp_roundtrip() -> None:
    s = new_totp_secret()
    assert verify_totp(s, pyotp.TOTP(s).now())
    assert not verify_totp(s, "abcdef")
    assert not verify_totp(s, "")


def test_totp_accepts_persian_digits_and_spaces() -> None:
    s = new_totp_secret()
    code = pyotp.TOTP(s).now()
    fa = code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert verify_totp(s, f" {fa[:3]} {fa[3:]} ")


def test_totp_uri() -> None:
    uri = totp_uri("JBSWY3DPEHPK3PXP", "a@b.ir")
    assert uri.startswith("otpauth://totp/Payamakyar:") and "issuer=Payamakyar" in uri


def test_totp_matching_step_returns_counter_within_window() -> None:
    from datetime import UTC, datetime

    from payamakyar.core.totp import totp_matching_step

    s = new_totp_secret()
    at = datetime(2026, 11, 13, 16, 30, 10, tzinfo=UTC)
    step = int(at.timestamp()) // 30
    t = pyotp.TOTP(s)
    assert totp_matching_step(s, t.at(at), at=at) == step
    assert totp_matching_step(s, t.at(at, -1), at=at) == step - 1
    assert totp_matching_step(s, t.at(at, 1), at=at) == step + 1
    assert totp_matching_step(s, t.at(at, 3), at=at) is None
    assert totp_matching_step(s, "abcdef", at=at) is None
    fa = t.at(at).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert totp_matching_step(s, fa, at=at) == step
