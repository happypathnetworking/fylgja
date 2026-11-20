"""Each device's configuration: Golden Config's render of it at the read, `intended_config` taken verbatim (D-118,
Constitution IV: Golden Config renders, Fylgja does not).

Nautobot stores no configuration Fylgja reads, and core Nautobot renders no device, so the read asks Golden Config's
`generate-intended-config` of every scoped device, which renders it under the setting that applies to it, that
setting's template repository and query, and `judge` takes what Golden Config answered, by its status, then by its
words (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8", "Golden Config's render"). A 200 is the
configuration where its `intended_config` is text holding a character other than whitespace, taken whole, its last
newline as Golden Config answered it: a template of whitespace alone answered 200 all the same, so it is refused, never
defaulted. Golden Config answers every refusal 400 `{"detail": …}`, and its words tell them apart:

- `NO_SETTING`: the device is in no setting's dynamic group, whose members are stored, so a device tagged since the
  group was last refreshed is not among them;
- `TEMPLATE_MISSING`: the setting's template file is not in the repository;
- any other words beginning `FAILED`: the template raised, the cause in Nautobot's log alone;
- `NOT_FOUND`: no device of the id within what the account may view, a device deleted under the read and one the
  account may not view being answered alike; the read weighs it at its close (read.py).

A 400 in other words, and any other status, is `render.unavailable`: Golden Config's words are quoted for a 400 alone,
their runs of whitespace made one space and cut at `QUOTED` characters. A 401 or a 403 is the transport's
`NautobotError`, never an answer judged here. No finding holds a byte of a configuration, and each names the device.
"""

from __future__ import annotations

import re

from fylgja_core.findings import Finding

from fylgja_nautobot.rows import Device, Rendered

# Rule ids. Callers and tests match on them (rules.md).
RULE_SETTING_ABSENT = "render.setting.absent"
RULE_TEMPLATE_MISSING = "render.template.missing"
RULE_FAILED = "render.failed"
RULE_EMPTY = "render.empty"
RULE_INVALID = "render.invalid"
RULE_DEVICE_UNKNOWN = "render.device.unknown"
RULE_UNAVAILABLE = "render.unavailable"

RENDERED = 200
"""The one status of a configuration rendered."""

REFUSED = 400
"""Golden Config's status for every render it refuses, its words in `detail`."""

NO_SETTING = "No Golden Config settings found for this device"
"""Golden Config's words for a device in no setting's dynamic group (design/verified-facts.md)."""

TEMPLATE_MISSING = re.compile(r"Error rendering Jinja template: Jinja template .+ not found in git repository .+")
"""Golden Config's words for a template file the repository lacks (design/verified-facts.md)."""

FAILED = "Error rendering Jinja template:"
"""What begins Golden Config's words for a template that raised (design/verified-facts.md)."""

NOT_FOUND = re.compile(r"Device with id '[^']*' not found")
"""Golden Config's words for a device of an id it cannot find among those the account may view
(design/verified-facts.md)."""

QUOTED = 300
"""How many characters of Golden Config's own words a finding quotes."""


def called(device: Device) -> str:
    """A device as findings name it: its name in Nautobot, or `dcim.device <id>` where it has none."""
    return device.name if device.name else f"dcim.device {device.id}"


def judge(device: Device, rendered: Rendered) -> str | Finding:
    """The configuration Golden Config rendered for `device`, its `intended_config`, verbatim; or the finding that
    names the device: `render.setting.absent`, `render.template.missing`, `render.failed` and `render.device.unknown`
    for a 400 in each one's words; `render.empty` for a 200 of whitespace alone; `render.invalid` for a 200 that is no
    JSON object with a text `intended_config`; and `render.unavailable` for a 400 in other words, whose words it
    quotes, or any other status."""
    name = called(device)
    status = rendered.status
    if status == RENDERED:
        if rendered.text is None:
            message = (
                f"Golden Config answered the render of device {name} HTTP 200 with no JSON object holding a text "
                "intended_config, so it has no configuration."
            )
            return _finding(RULE_INVALID, name, message)
        if not rendered.text.strip():
            message = (
                f"Golden Config rendered device {name} to no character but whitespace, {len(rendered.text)} "
                "characters, so it has no configuration: correct the template."
            )
            return _finding(RULE_EMPTY, name, message)
        return rendered.text
    if status != REFUSED:
        said = f"Golden Config answered HTTP {status} to the render of device {name}, so it has no configuration."
        return _finding(RULE_UNAVAILABLE, name, said)
    words = " ".join((rendered.detail or "").split())
    quoted = words[:QUOTED] if words else "no words"
    answered = f"Golden Config answering its render HTTP 400 ({quoted})"
    if words == NO_SETTING:
        message = (
            f"Device {name} is in no Golden Config setting's dynamic group, {answered}: the group's members are "
            "stored, so refresh the stored members of the dynamic group of the setting meant to apply to it (save the "
            "group, or run the job RefreshDynamicGroupCaches)."
        )
        return _finding(RULE_SETTING_ABSENT, name, message)
    if TEMPLATE_MISSING.fullmatch(words):
        message = (
            f"The template of device {name} is not in its Golden Config setting's template repository, {answered}: "
            "add the template, or correct the setting's path to it."
        )
        return _finding(RULE_TEMPLATE_MISSING, name, message)
    if words.startswith(FAILED):
        message = (
            f"The template of device {name} failed, {answered}, and the cause is in Nautobot's log alone: correct "
            "the template or the setting's query."
        )
        return _finding(RULE_FAILED, name, message)
    if NOT_FOUND.fullmatch(words):
        message = (
            f"Golden Config found no device {name}, {answered}: it was deleted during the read, or the reader's "
            "account may not view it, so grant the account view on dcim.device."
        )
        return _finding(RULE_DEVICE_UNKNOWN, name, message)
    message = f"Golden Config answered HTTP 400 to the render of device {name} ({quoted}), so it has no configuration."
    return _finding(RULE_UNAVAILABLE, name, message)


def _finding(rule: str, name: str, message: str) -> Finding:
    return Finding(rule=rule, severity="error", object=name, message=message)
