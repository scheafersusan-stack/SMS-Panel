"""Structured JSON logging to stderr with redaction."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from payamakyar.core.masking import redact

_STD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}
_HANDLER_NAME = "payamakyar-json"


class RedactFilter(logging.Filter):
    """Apply ``redact`` to the message, its args and any extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = redact(record.args)
        for key in set(record.__dict__) - _STD:
            record.__dict__[key] = (
                "****" if redact({key: 0}).get(key) == "****" else redact(record.__dict__[key])
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
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
