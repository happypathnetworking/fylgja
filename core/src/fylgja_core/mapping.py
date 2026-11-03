"""Interface mapping: how a platform package's interface rules decide a production name
(formats/platform-package-1.schema.json, D-015).

The compiler decides every blueprint interface with `decide`, and a driver's plan renders
endpoint names from a decision's captures through the package's rename templates. A rule's
`match` is a naming template: `{name}` captures one path segment, everything else is
literal, and the whole name must fit. Pure: no I/O, clock or environment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Literal

from fylgja_core.platform_package import PlatformPackage

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_INTEGER = re.compile(r"[0-9]+")


@dataclass(frozen=True, kw_only=True)
class Mapped:
    """A production name the platform has: the rule that decided it, what the node's OS
    calls the port, and the values the match captured."""

    rule: str
    node_name: str
    captures: Mapping[str, str]


@dataclass(frozen=True, kw_only=True)
class Unmappable:
    """A production name the platform has no port for: a rule matched with a value outside
    its range, or no rule matched. `detail` says which, for a finding or a fidelity row."""

    omission: Literal["out_of_range", "no_rule"]
    rule: str | None
    detail: str


@cache
def _compiled(pattern: str) -> re.Pattern[str]:
    parts, last = [], 0
    for found in _PLACEHOLDER.finditer(pattern):
        parts.append(re.escape(pattern[last:found.start()]))
        parts.append(f"(?P<{found.group(1)}>[^/]+)")
        last = found.end()
    parts.append(re.escape(pattern[last:]))
    return re.compile("".join(parts))


def match(pattern: str, name: str) -> dict[str, str] | None:
    """The values `pattern`'s placeholders capture from `name`, or None when it does not fit."""
    found = _compiled(pattern).fullmatch(name)
    return None if found is None else found.groupdict()


def render(template: str, captures: Mapping[str, str]) -> str:
    """`template` with each placeholder replaced by its captured value."""
    return _PLACEHOLDER.sub(lambda found: captures[found.group(1)], template)


def decide(package: PlatformPackage, name: str, mgmt_only: bool) -> Mapped | Unmappable:
    """What `package` makes of the production interface `name`: the management rule for a
    mgmt_only interface, else the first data rule whose match fits, in range or not."""
    rules = package.interfaces.rules
    if mgmt_only:
        management = next(rule for rule in rules if rule.management)
        return Mapped(rule=management.name, node_name=management.node_name or name, captures={})
    tried = []
    for rule in rules:
        if rule.match is None:
            continue
        tried.append(rule.name)
        captures = match(rule.match, name)
        if captures is None:
            continue
        for placeholder, (low, high) in (rule.ranges or {}).items():
            value = captures[placeholder]
            if not _INTEGER.fullmatch(value) or not low <= int(value) <= high:
                detail = f"rule {rule.name!r} matched, but {{{placeholder}}} is {value}, outside {low}..{high}"
                return Unmappable(omission="out_of_range", rule=rule.name, detail=detail)
        node_name = render(rule.node_name, captures) if rule.node_name else name
        return Mapped(rule=rule.name, node_name=node_name, captures=captures)
    return Unmappable(omission="no_rule", rule=None, detail=f"no rule matches; tried {', '.join(tried)}")
