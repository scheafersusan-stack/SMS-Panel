import pytest
from cryptography.fernet import Fernet

from payamakyar.core.crypto import SecretBox, SecretBoxError


def test_roundtrip() -> None:
    box = SecretBox(Fernet.generate_key())
    token = box.seal("راز")
    assert token != "راز" and box.open(token) == "راز"


def test_wrong_key_and_tamper() -> None:
    a, b = SecretBox(Fernet.generate_key()), SecretBox(Fernet.generate_key())
    t = a.seal("x")
    with pytest.raises(SecretBoxError):
        b.open(t)
    with pytest.raises(SecretBoxError):
        a.open(t[:-2] + "AA")
    with pytest.raises(SecretBoxError):
        a.open("garbage")


def test_bad_key() -> None:
    with pytest.raises(SecretBoxError):
        SecretBox(b"short")
