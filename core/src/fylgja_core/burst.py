"""Verify's burst, per probe format (D-051, D-014): the command a burst runs, how its output
is judged held, and the exec budget it gets.

The package holds the command and its counts; the format keys how the output is read, so
`MECHANISMS` maps each format this build runs to its judging function. Pure: no I/O, clock
or environment.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from fylgja_core import mapping
from fylgja_core.driver import Exec
from fylgja_core.probe_package import ProbePackage

# BusyBox ping's summary: "5 packets transmitted, 5 packets received, 0% packet loss".
_PING_SUMMARY = re.compile(r"(\d+) packets transmitted, (\d+) packets received")

# The slack a burst's exec gets beyond its own packets and wait.
_MARGIN_S = 5.0


def command(package: ProbePackage, far_address: str) -> list[str]:
    """The package's burst command, rendered for `far_address` (no prefix length)."""
    values = {
        "count": str(package.burst.count),
        "interval": f"{package.flow.interval_s:g}",
        "wait": str(package.burst.wait_s),
        "far_address": far_address,
    }
    return [mapping.render(word, values) for word in package.burst.command]


def timeout_s(package: ProbePackage) -> float:
    """The exec budget for a burst: its packets' spacing, its wait, and a margin."""
    return package.burst.count * package.flow.interval_s + package.burst.wait_s + _MARGIN_S


def _ping_held(package: ProbePackage, result: Exec) -> tuple[bool, str]:
    found = _PING_SUMMARY.search(result.stdout)
    if found is None:
        if result.returncode != 0:
            return False, f"exit status {result.returncode} and no summary"
        return False, "no summary line in the output"
    sent, received = int(found.group(1)), int(found.group(2))
    count = package.burst.count
    if sent != count:
        return False, f"{sent} echoes sent, not {count}; {received} answered"
    held = received == sent == count
    return held, f"{received} of {sent} echoes answered"


# The judging function for each probe format this build runs; a format absent here is refused at load.
MECHANISMS: Mapping[str, Callable[[ProbePackage, Exec], tuple[bool, str]]] = {"ping": _ping_held}


def held(package: ProbePackage, result: Exec) -> tuple[bool, str]:
    """Whether the burst's output holds, and one sentence of facts for the finding."""
    return MECHANISMS[package.format](package, result)
