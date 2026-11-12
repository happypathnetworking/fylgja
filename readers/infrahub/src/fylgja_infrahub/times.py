"""Infrahub's time strings (D-082).

A time the reader is given or answers (`at`, `generated_since`, `head`'s answer) is a string as Infrahub returned it,
and `at` is sent verbatim. `parse` reads one to compare it, and nothing parsed is ever sent but `after`'s answer.

Infrahub answers its times to the microsecond, `+00:00` or `Z`, and reads an `at` with any number of fractional
digits, but cuts every digit past the sixth: a read at a time with a seventh digit, or nine, answers what a read at its
first six does, not what the next microsecond does (design/verified-facts.md, "Infrahub 1.11.11"). So `invalid`
refuses such an `at`, which would pin a read at another instant than the one given; `parse` still reads it, to
compare.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone

from fylgja_core.findings import Finding

# Rule ids. Callers and tests match on them (rules.md).
RULE_INVALID = "at.invalid"

HONOURED = 6
"""The fractional digits Infrahub reads an `at` to: the microsecond."""

_TIME = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _read(s: str) -> tuple[datetime, str, str]:
    """The instant `s` names to the second, in its own zone; its fractional digits; and its zone as written. A
    `ValueError` for anything but RFC 3339 with `T`, and `Z` or an offset."""
    found = _TIME.fullmatch(s)
    if found is None:
        raise ValueError(f"{s!r} is no RFC 3339 time with T, and Z or an offset")
    year, month, day, hour, minute, second = (int(found[i]) for i in range(1, 7))
    zone = found[8]
    try:
        offset = timedelta(0)
        if zone != "Z":
            hours, minutes = int(zone[1:3]), int(zone[4:6])
            if hours > 23 or minutes > 59:
                raise ValueError(zone)
            offset = (-1 if zone[0] == "-" else 1) * timedelta(hours=hours, minutes=minutes)
        moment = datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset))
    except ValueError:
        raise ValueError(f"{s!r} is no RFC 3339 time with T, and Z or an offset") from None
    return moment, found[7] or "", zone


def parse(s: str) -> int:
    """The instant `s` names, in nanoseconds since the epoch: RFC 3339 with `T`, a fraction of any length or none (a
    digit past the ninth is not counted), and `Z` or an offset; anything else is a `ValueError`."""
    moment, fraction, _ = _read(s)
    delta = moment - _EPOCH
    seconds = delta.days * 86_400 + delta.seconds
    return seconds * 1_000_000_000 + int(fraction[:9].ljust(9, "0"))


def later(a: str, b: str) -> bool:
    """Whether `a` names a later instant than `b`."""
    return parse(a) > parse(b)


def latest(times: Iterable[str]) -> str | None:
    """The first of `times` that names the latest instant among them, as it was given; None for none."""
    found: tuple[int, str] | None = None
    for time in times:
        instant = parse(time)
        if found is None or instant > found[0]:
            found = (instant, time)
    return found[1] if found is not None else None


def after(s: str) -> str:
    """The first instant after `s` that Infrahub reads: a microsecond after its first six fractional digits, written
    with six and in `s`'s zone as it is written (`Z` stays `Z`, `+00:00` stays `+00:00`). A read pinned there meets
    the write `s` is the time of, which a read pinned at `s` itself does not wholly: it answers the write's values with
    the earlier stamps (design/verified-facts.md, "Infrahub 1.11.11")."""
    moment, fraction, zone = _read(s)
    moment += timedelta(microseconds=int(fraction[:HONOURED].ljust(HONOURED, "0")) + 1)
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:{moment.minute:02d}:"
        f"{moment.second:02d}.{moment.microsecond:06d}{zone}"
    )


def invalid(value: str, *, branch: str | None = None) -> Finding | None:
    """`at.invalid` where `value`, an `at` or a `generated_since`, is no time Infrahub reads as given: no RFC 3339
    time with `T`, and `Z` or an offset; or one with more fractional digits than Infrahub honours. None where it is.
    The message names `branch`, the branch a read at `value` was asked of, where one is given."""
    of = f" of branch {branch}" if branch is not None else ""
    try:
        _, fraction, _ = _read(value)
    except ValueError:
        message = f"{value!r} is no RFC 3339 time with T, and Z or an offset, so no read{of} is made at it."
    else:
        if len(fraction) <= HONOURED:
            return None
        message = (
            f"{value!r} has {len(fraction)} fractional digits, and Infrahub honours six, cutting the rest, so a "
            f"read{of} at it would be pinned at another instant than the one given."
        )
    return Finding(rule=RULE_INVALID, severity="error", object=value, message=message)
