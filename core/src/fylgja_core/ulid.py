"""ULIDs, made in the core (D-040): run ids are ULIDs by twin record 1, and a dependency
for thirty lines is not worth keeping (D-039).

A ULID is 48 bits of milliseconds since the epoch and 80 random bits, written as 26
characters of Crockford base32 (10 of time, 16 of randomness), so that ids sort by creation.
Within a process they are monotonic: a second id in the same millisecond is the first's
random part plus one.
"""

from __future__ import annotations

import re
import secrets
import threading
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

_RANDOM_BITS = 80
_lock = threading.RLock()
_last_ms = -1
_last_random = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_at(ms: int, random: int) -> str:
    """The ULID for `ms` and `random`; in the millisecond of the last one made in this
    process it is the last one plus one."""
    global _last_ms, _last_random
    with _lock:
        if ms == _last_ms:
            ms, random = _last_ms, _last_random + 1
            if random >> _RANDOM_BITS:
                raise OverflowError("2**80 ULIDs in one millisecond")
        _last_ms, _last_random = ms, random
    return _encode(ms, 10) + _encode(random, 16)


def new() -> str:
    """A new ULID for now; should the clock step back, the time of the last one made is kept,
    so that ids never sort backwards within a process."""
    with _lock:
        return new_at(max(time.time_ns() // 1_000_000, _last_ms), secrets.randbits(_RANDOM_BITS))


def timestamp_ms(value: str) -> int:
    """The milliseconds since the epoch that `value` carries."""
    ms = 0
    for c in value[:10]:
        ms = ms << 5 | ALPHABET.index(c)
    return ms
