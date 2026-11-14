import uuid

from pydantic import SecretStr

from payamakyar.core.ids import new_id
from payamakyar.core.masking import mask_mobile, mask_secret, redact
from payamakyar.core.phone import InvalidMobile


def test_mask_mobile_variants() -> None:
    assert mask_mobile("09123456789") == "0912***6789"
    assert mask_mobile("+989123456789") == "0912***6789"
    assert mask_mobile("۰۹۱۲۳۴۵۶۷۸۹") == "0912***6789"


def test_mask_mobile_non_mobile_unchanged() -> None:
    assert mask_mobile("hello") == "hello"


def test_mask_secret() -> None:
    assert mask_secret("abcdefgh1234") == "****1234"
    assert mask_secret("ab") == "****"
    assert mask_secret("") == "****"


def test_redact_masks_nested() -> None:
    out = redact({"password": "x", "user": {"mobile": "09123456789", "otp": "1234"}})
    assert out == {"password": "****", "user": {"mobile": "0912***6789", "otp": "****"}}


def test_redact_any_value_type_and_case() -> None:
    out = redact(
        {
            "API_KEY": 123,
            "Authorization": None,
            "x_token": ["a"],
            "s": SecretStr("z"),
            "name": "ok",
        }
    )
    assert out == {
        "API_KEY": "****",
        "Authorization": "****",
        "x_token": "****",
        "s": "****",
        "name": "ok",
    }


def test_code_keys() -> None:
    assert redact({"status_code": 200, "error": {"code": "INVALID_CREDENTIALS"}}) == {
        "status_code": 200,
        "error": {"code": "INVALID_CREDENTIALS"},
    }
    assert redact({"code": "123456"}) == {"code": "****"}
    assert redact({"code": 5}) == {"code": 5}
    for k in [
        "otp_code",
        "verification_code",
        "mfa_code",
        "otpCode",
        "apiKey",
        "api-key",
        "X_Token",
        "accessToken",
        "client_secret",
    ]:
        assert redact({k: "x"}) == {k: "****"}, k
    assert redact({"keyboard": "x", "tokenizer_name": "x"}) == {
        "keyboard": "x",
        "tokenizer_name": "x",
    }


def test_redact_containers_and_text() -> None:
    out = redact([("09123456789", 1), {"a": "call +989123456789 now"}])
    assert out == [("0912***6789", 1), {"a": "call 0912***6789 now"}]
    assert redact(5) == 5
    assert redact("uuid 12345678901234 here") == "uuid 12345678901234 here"


def test_new_id_v7_time_ordered() -> None:
    ids = [new_id() for _ in range(2000)]
    assert all(
        isinstance(i, uuid.UUID) and i.version == 7 and i.variant == uuid.RFC_4122 for i in ids
    )
    assert len(set(ids)) == 2000
    assert ids == sorted(ids)


def test_invalid_mobile_is_value_error() -> None:
    assert issubclass(InvalidMobile, ValueError)
