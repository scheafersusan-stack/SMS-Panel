"""Time-ordered identifiers (UUIDv7, RFC 9562)."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_last_seq = 0


def new_id() -> uuid.UUID:
    """Return a UUIDv7; ids from one process are strictly increasing."""
    global _last_ms, _last_seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            _last_seq += 1
            if _last_seq > 0xFFF:  # 12-bit counter exhausted: borrow the next ms
                ms += 1
                _last_seq = 0
        else:
            _last_seq = int.from_bytes(os.urandom(2), "big") & 0x7FF  # headroom for the counter
        _last_ms = ms
        seq = _last_seq
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (seq << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
