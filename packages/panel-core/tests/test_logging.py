import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from payamakyar.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    level = root.level
    yield
    for h in list(root.handlers):
        if h.get_name() == "payamakyar-json":
            root.removeHandler(h)
    root.setLevel(level)


def _rows(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().err.strip().splitlines()]


def test_logging_json_redacts(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    log = logging.getLogger("t")
    log.info("sent to %s", "09123456789", extra={"password": "hunter2", "ctx": {"otp": "1"}})
    log.info("map %(m)s", {"m": "09123456789"})
    rows = _rows(capsys)
    assert rows[0]["message"] == "sent to 0912***6789"
    assert rows[0]["level"] == "INFO"
    assert rows[0]["password"] == "****" and rows[0]["ctx"] == {"otp": "****"}
    assert rows[1]["message"] == "map 0912***6789"
    assert "09123456789" not in json.dumps(rows) and "hunter2" not in json.dumps(rows)
    configure_logging("INFO")  # idempotent: no duplicate handlers
    assert [h.get_name() for h in logging.getLogger().handlers].count("payamakyar-json") == 1


def test_non_str_msg_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("t").info({"password": "hunter2"})
    out = json.dumps(_rows(capsys))
    assert "hunter2" not in out


def test_object_arg_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    logging.getLogger("t").info("e %s", ValueError("09123456789"))
    rows = _rows(capsys)
    assert rows[0]["message"] == "e 0912***6789"


def test_cyclic_structures_do_not_raise(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    cyc: dict[str, Any] = {}
    cyc["self"] = cyc
    logging.getLogger("t").info("x %s", cyc, extra={"ctx": cyc})
    logging.getLogger("t").info(cyc)
    rows = _rows(capsys)
    assert rows[0]["message"] == "[unredactable]" and rows[0]["ctx"] == "[unredactable]"
    assert rows[1]["message"] == "[unredactable]"
