"""The one clock: every `date-time` the core writes comes from `now()`, so that records,
runs and events agree on the form (RFC 3339, UTC, microseconds, a `Z` suffix)."""

from __future__ import annotations

import datetime


def now() -> str:
    """The current time, such as `2026-11-03T18:02:56.123456Z`."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
