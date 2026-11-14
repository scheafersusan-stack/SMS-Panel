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
