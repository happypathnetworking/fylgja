"""Each device's configuration: its artifact's content, exactly what Infrahub rendered (D-007, D-082).

Which artifact is the configuration is decided from the device's listing alone, before any content is fetched: the
one whose definition's `artifact_name` is the reader document's `artifact`, never one chosen among several, `Ready`,
with a storage id and a checksum. A rewrite moves both in place and leaves the status `Ready`, and an artifact being
generated reads `Pending` with neither (design/verified-facts.md, "Infrahub 1.11.11"); any status but `Ready` is
refused verbatim, an `Error` among them, which was not read. The content Infrahub serves for the storage id is then
held to the checksum, its MD5 in hex, and must be UTF-8 text. A read pinned at a past time lists the artifact as it
stood then, and its storage id still serves those bytes, so a pinned read never falls back to the present artifact.
No finding holds a byte of the content.
"""

from __future__ import annotations

import hashlib

from fylgja_core.findings import Finding

from fylgja_infrahub.rows import Artifact, Content, Device, incomplete

# Rule ids. Callers and tests match on them (rules.md).
RULE_MISSING = "artifact.missing"
RULE_AMBIGUOUS = "artifact.ambiguous"
RULE_UNREADY = "artifact.unready"
RULE_UNAVAILABLE = "artifact.content.unavailable"
RULE_MISMATCH = "artifact.checksum.mismatch"
RULE_INVALID = "artifact.content.invalid"

READY = "Ready"
"""The one status of an artifact whose content is the configuration rendered."""

SERVED = 200
"""The one status of content Infrahub serves."""


def select(device: Device, name: str, *, branch: str, at: str) -> Artifact | Finding:
    """The device's artifact named `name`, from its listing alone; or `read.incomplete` where the listing is not
    whole, `artifact.missing` where none is of that name, `artifact.ambiguous` where several are, and
    `artifact.unready` where the one is not `Ready`, or has no storage id or no checksum."""
    cut = incomplete(device.artifacts, branch=branch, at=at)
    if cut is not None:
        return cut
    when = f"on branch {branch} at {at}"
    held = sorted((a for a in device.artifacts.items if a.definition == name), key=lambda a: (a.checksum or "", a.id))
    if not held:
        others = sorted({a.definition for a in device.artifacts.items})
        beside = f" (it has {', '.join(others)})" if others else ""
        message = f"Device {device.name} {when} has no artifact {name}{beside}, so it has no configuration to read."
        return _finding(RULE_MISSING, device, message)
    if len(held) > 1:
        sums = ", ".join(a.checksum or "none" for a in held)
        message = (
            f"Device {device.name} {when} has {len(held)} artifacts {name}, of the checksums {sums}, and the reader "
            "never chooses among them."
        )
        return _finding(RULE_AMBIGUOUS, device, message)
    (artifact,) = held
    if artifact.status != READY:
        status = artifact.status if artifact.status is not None else "of no status"
        said = f"is {status}, not {READY}"
    elif artifact.storage_id is None:
        said = f"is {READY} with no storage id"
    elif artifact.checksum is None:
        said = f"is {READY} with no checksum"
    else:
        return artifact
    message = (
        f"Device {device.name}'s artifact {name} {when} {said}, so it holds no configuration rendered for it; "
        "regenerate it in Infrahub, and read again once it is Ready."
    )
    return _finding(RULE_UNREADY, device, message)


def judge(device: Device, artifact: Artifact, content: Content, *, branch: str, at: str) -> str | Finding:
    """The configuration `content` holds, as text; or `artifact.content.unavailable` where Infrahub answered other
    than 200, `artifact.checksum.mismatch` where the bytes' MD5 is not the artifact's checksum, and
    `artifact.content.invalid` where they are empty or no UTF-8 text."""
    whose = f"the content of device {device.name}'s artifact {artifact.definition} on branch {branch} at {at}"
    if content.status != SERVED:
        message = (
            f"Infrahub answered HTTP {content.status} for {whose}, stored under {artifact.storage_id}, so its "
            "configuration is not read."
        )
        return _finding(RULE_UNAVAILABLE, device, message)
    digest = hashlib.md5(content.body, usedforsecurity=False).hexdigest()
    if digest != artifact.checksum:
        message = (
            f"The MD5 of {whose} is {digest}, and the artifact lists the checksum {artifact.checksum}, so the bytes "
            "served are not the configuration Infrahub describes."
        )
        return _finding(RULE_MISMATCH, device, message)
    if not content.body:
        return _finding(RULE_INVALID, device, f"{_capital(whose)} is empty, so it holds no configuration.")
    try:
        return content.body.decode("utf-8")
    except UnicodeDecodeError as e:
        # The error's own text quotes the byte, which no finding holds.
        said = f"is no UTF-8 text from byte {e.start} of {len(content.body)}, so it holds no configuration"
    return _finding(RULE_INVALID, device, f"{_capital(whose)} {said}.")


def _finding(rule: str, device: Device, message: str) -> Finding:
    return Finding(rule=rule, severity="error", object=device.name, message=message)


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]
