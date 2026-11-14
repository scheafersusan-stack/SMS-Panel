from payamakyar.core.national_id import is_valid_company_id, is_valid_national_code


def test_national_code() -> None:
    assert is_valid_national_code("0499370899") and not is_valid_national_code("1111111111")
    assert not is_valid_national_code("0499370898")


def test_national_code_digits_and_shape() -> None:
    assert is_valid_national_code("۰۴۹۹۳۷۰۸۹۹")
    assert is_valid_national_code("٠٤٩٩٣٧٠٨٩٩")
    assert not is_valid_national_code("499370899")
    assert not is_valid_national_code("04993708990")
    assert not is_valid_national_code("04993708a9")
    assert not is_valid_national_code("")


def test_company_id() -> None:
    assert is_valid_company_id("10380284790") and not is_valid_company_id("10380284791")
    assert is_valid_company_id("۱۰۳۸۰۲۸۴۷۹۰")
    assert not is_valid_company_id("1038028479")
    assert not is_valid_company_id("1038028479x")
