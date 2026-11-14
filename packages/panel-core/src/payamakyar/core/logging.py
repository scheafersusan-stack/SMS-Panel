"""Structured JSON logging to stderr with redaction."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from payamakyar.core.masking import redact

_STD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
_HANDLER_NAME = "payamakyar-json"


_UNREDACTABLE = "[unredactable]"
_PLAIN = (str, int, float, bool, bytes, type(None), dict, list, tuple, set, frozenset)


def _safe(value: Any) -> Any:
    """Redact ``value``; objects of other types are rendered with ``str`` first."""
    if not isinstance(value, _PLAIN):
        value = str(value)
    return redact(value)


class RedactFilter(logging.Filter):
    """Apply ``redact`` to the message, its args and any extras; never raises."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _safe(record.msg)
            if record.args:
                record.args = _safe(record.args)
        except Exception:
            record.msg, record.args = _UNREDACTABLE, None
        for key in set(record.__dict__) - _STD:
            try:
                record.__dict__[key] = redact({key: record.__dict__[key]})[key]
            except Exception:
                record.__dict__[key] = _UNREDACTABLE
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in set(record.__dict__) - _STD:
            data[key] = record.__dict__[key]
        if record.exc_info:
            data["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(data, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Install a single JSON-lines stderr handler on the root logger (idempotent)."""
    root = logging.getLogger()
    for h in list(root.handlers):
        if h.get_name() == _HANDLER_NAME:
            root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
