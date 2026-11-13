"""Each device's configuration: what NetBox renders for it at the read, its text taken verbatim (D-095, D-007,
Constitution IV: NetBox renders, Fylgja does not).

NetBox stores no configuration, so the read asks a render of every scoped device under the branch's header, and
`judge` takes what NetBox answered, by its status, then by its content type and its bytes (design/verified-facts.md,
"A device's configuration, rendered"). A 200 is the configuration where NetBox calls it `text/plain` and it is UTF-8
text holding a character other than whitespace, taken whole, its last byte the template's and a trailing newline
kept: a 200 of another content type, NetBox's JSON envelope say, would otherwise be taken as a configuration, and a
template that renders nothing, or whitespace alone, answers 200 all the same, so each is refused, never defaulted. A
400 is a device with no configuration template only where NetBox says so, in the words `NO_TEMPLATE`: NetBox answered
a render 400 under the header of a branch deleted, `Invalid branch identifier` (the same facts, "A render under the
header of a branch that is gone"), and a list 400 under that of a branch deleted, syncing or merged, so any other 400
is `render.unavailable`, which the read weighs against its bracket
(read.py). A 500 is a template that fails. NetBox's words are quoted for a
400 and a 500 alone, as text and never parsed, since the no-template answer is single-quoted `text/plain`, cut at
`QUOTED` characters. Any other status is refused giving the status and no body; NetBox answers 404 to a render where
the token's account lacks `view` or `render_config` on `dcim.device`, though it has just listed the device, so a
404's finding says so. A 401 or a 403 is the transport's `NetBoxError`, never an answer judged here. No finding
holds a byte of a configuration, and each names the device and the branch read, or `main`.
"""

from __future__ import annotations

from fylgja_core.findings import Finding

from fylgja_netbox.rows import Device, Rendered

# Rule ids. Callers and tests match on them (rules.md).
RULE_TEMPLATE_MISSING = "render.template.missing"
RULE_FAILED = "render.failed"
RULE_EMPTY = "render.empty"
RULE_INVALID = "render.invalid"
RULE_UNAVAILABLE = "render.unavailable"

RENDERED = 200
"""The one status of a configuration rendered."""

TEXT = "text/plain"
"""The one content type of a configuration rendered, its parameters aside."""

REFUSED = 400
"""NetBox's status for a render of a device with no configuration template, and for one under the header of a branch
deleted."""

NO_TEMPLATE = "No config template found for this device."
"""NetBox's words in its 400 for a device with no configuration template (design/verified-facts.md)."""

FAILED = 500
"""NetBox's status for a render whose template fails."""

UNGRANTED = 404
"""NetBox's status for a render where the token's account lacks `view` or `render_config` on `dcim.device`."""

QUOTED = 300
"""How many characters of NetBox's own words a finding quotes."""


def judge(device: Device, rendered: Rendered, *, branch: str | None) -> str | Finding:
    """The configuration NetBox rendered for `device`, as text, verbatim; or `render.template.missing` where NetBox
    answered 400 in the words `NO_TEMPLATE`, `render.failed` where it answered 500, `render.empty` where it answered
    200 with no character but whitespace, `render.invalid` where it answered 200 of a content type but `text/plain` or
    with bytes that are no UTF-8 text, and `render.unavailable` for any other status, another 400 among them, whose
    words it quotes. `branch` is the name of the branch read, None for `main`."""
    called = device.name if device.name is not None else f"dcim.device {device.id}"
    where = f"branch {branch}" if branch is not None else "main"
    status = rendered.status
    if status == REFUSED and NO_TEMPLATE in rendered.body.decode("utf-8", errors="replace"):
        message = (
            f"Device {called} on {where} has no configuration template, NetBox answering its render HTTP 400 "
            f"({_words(rendered.body)}): assign one to the device, its role or its platform."
        )
        return _finding(RULE_TEMPLATE_MISSING, called, message)
    if status == FAILED:
        message = (
            f"The configuration template of device {called} on {where} failed, NetBox answering its render HTTP 500 "
            f"({_words(rendered.body)}): correct the template."
        )
        return _finding(RULE_FAILED, called, message)
    if status == REFUSED:
        message = (
            f"NetBox answered HTTP 400 to the render of device {called} on {where} ({_words(rendered.body)}), so it "
            "has no configuration."
        )
        return _finding(RULE_UNAVAILABLE, called, message)
    if status != RENDERED:
        said = f"NetBox answered HTTP {status} to the render of device {called} on {where}"
        grant = (
            "; NetBox answers 404 to a render where the token's account lacks view or render_config on dcim.device, "
            "though the read has just listed the device"
            if status == UNGRANTED
            else ""
        )
        return _finding(RULE_UNAVAILABLE, called, f"{said}, so it has no configuration{grant}.")
    given = (rendered.content_type or "").split(";")[0].strip().lower()
    if given != TEXT:
        named = f"as {given[:QUOTED]}" if given else "with no content type"
        message = (
            f"NetBox answered the render of device {called} on {where} {named}, not {TEXT}, so it has no "
            "configuration."
        )
        return _finding(RULE_INVALID, called, message)
    try:
        text = rendered.body.decode("utf-8")
    except UnicodeDecodeError as e:
        # The error's own text quotes the byte, which no finding holds.
        rule, said = RULE_INVALID, f"bytes that are no UTF-8 text from byte {e.start} of {len(rendered.body)}"
    else:
        if text.strip():
            return text
        rule, said = RULE_EMPTY, f"no character but whitespace, {len(rendered.body)} bytes"
    message = f"NetBox rendered device {called} on {where} to {said}, so it has no configuration: correct the template."
    return _finding(rule, called, message)


def _words(body: bytes) -> str:
    """NetBox's words in a refusal: the body as text, never parsed, its runs of whitespace made one space and cut at
    `QUOTED` characters."""
    said = " ".join(body.decode("utf-8", errors="replace").split())
    return said[:QUOTED] if said else "an empty body"


def _finding(rule: str, called: str, message: str) -> Finding:
    return Finding(rule=rule, severity="error", object=called, message=message)
