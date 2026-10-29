"""The CTM's intrinsic rules (`internal/validate`'s `Intrinsic`, and the
`compiler.LinkTerminations` it calls): the rules that read no package, with their ids and
words, which the read runs before it writes a snapshot (R-07). The core holds a sent
snapshot to the same rules before it files it, and to the rest, which need its packages,
at compile.

Every rule here runs against the CTM, not against Infrahub, so a fixture and a live branch
fail alike. Findings are gathered, never returned early: an operator fixing intent wants
every problem in one pass.

A CTM is a plain dict, as JSON decodes it and `snapshot.normalize` puts it in canonical
form, which this module does first, in place.
"""

import re

from fylgja_orchestrator.adapters.infrahub.snapshot import normalize
from fylgja_orchestrator.documents.findings import Findings, quote

RULE_REQUIRED_MISSING = "data.required.missing"
RULE_DEVICE_NAME_DUPLICATE = "device.name.duplicate"
RULE_LINK_ENDPOINTS_COUNT = "link.endpoints.count"
RULE_LINK_ENDPOINTS_SAME_DEVICE = "link.endpoints.same_device"
RULE_DEVICES_EMPTY = "ctm.devices.empty"

FIDELITY_APPROXIMATED = "approximated"
FIDELITY_OMITTED = "omitted"

DISP_CONFIGURED_NOT_CABLED = "configured-not-cabled"
"""The compiler's disposition of a port that exists on the node and is never wired."""

NAMES_ITS_LINK = "an interface names the one link it terminates"
"""The rule every link-termination refusal states."""


_SCOPE_FORM = re.compile(r"tag:[^\t\n\f\r ]+")
_READER_FORM = re.compile(r"[a-z0-9][a-z0-9-]*")


def valid_scope(value: str) -> bool:
    """Whether value is a scope, tag:<name>: the literal tag: and one shell word, `ctm`'s
    `^tag:\\S+$` (RE2's \\S, which excludes the ASCII spaces alone), matched whole."""
    return _SCOPE_FORM.fullmatch(value) is not None


def valid_reader(value: str) -> bool:
    """Whether value is a reader's name, as infrahub-dcim is: lowercase letters, digits and
    hyphens, beginning with a letter or a digit."""
    return _READER_FORM.fullmatch(value) is not None


def _s(obj: dict, key: str) -> str:
    value = obj.get(key)
    return value if isinstance(value, str) else ""


def _endpoint_id(endpoint: dict) -> str:
    return f"{_s(endpoint, 'device')}:{_s(endpoint, 'interface')}"


def _device(ctm: dict, name: str) -> dict | None:
    """The first device of a name, as `CTM.Device` finds it."""
    return next((d for d in ctm["devices"] if _s(d, "name") == name), None)


def _interface(device: dict, name: str) -> dict | None:
    return next((i for i in device["interfaces"] if _s(i, "name") == name), None)


def intrinsic(ctm: dict) -> Findings:
    """The rules of the core's Validate that read no package, as Validate words and orders
    them: the envelope's, the device list's, each device's name and its interfaces' names,
    and the links'. An interface's name is checked on every named device, whatever its
    platform: a nameless interface is the CTM's fault."""
    found = Findings()
    normalize(ctm)
    check_envelope(ctm, found)
    check_devices_present(ctm, found)
    seen: set[str] = set()
    for d in ctm["devices"]:
        if not check_device_name(d, seen, found):
            continue
        for i in d["interfaces"]:
            if not _s(i, "name"):
                found.reject(RULE_REQUIRED_MISSING, _s(d, "name"), "an interface has no name")
    check_links(ctm, found)
    return found


_ENVELOPE_FIELDS = (
    ("branch", ("branch",), "the branch intent was read from is not recorded"),
    ("observed_at", ("observed_at",), "the instant intent was read is not recorded"),
    ("schema_hash", ("schema_hash",), "the schema intent was read against is not recorded"),
    ("scope", ("scope",), "the scope intent was read under is not recorded"),
    ("mapping.reader", ("mapping", "reader"), "the reader that mapped intent is not recorded"),
    ("mapping.model", ("mapping", "model"), "the model the reader read is not recorded"),
    ("mapping.version", ("mapping", "version"), "the version of the model the reader read is not recorded"),
)


def _envelope_value(envelope: dict, path: tuple[str, ...]) -> str:
    value = envelope
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) else ""


def check_envelope(ctm: dict, found: Findings) -> None:
    """The CTM records what it was read against. `at` is not among these: it is present iff
    the operator pinned one."""
    envelope = ctm["envelope"]
    for name, path, why in _ENVELOPE_FIELDS:
        if not _envelope_value(envelope, path):
            found.reject(RULE_REQUIRED_MISSING, "envelope." + name, why)
    check_envelope_forms(envelope, found)


def check_envelope_forms(envelope: dict, found: Findings) -> None:
    """The envelope's values held to the forms the contracts give them, which reach the
    manifest and the twin record unchanged. A value left empty is named once, as not
    recorded. Rows are named by their place in the list as normalize sorts it."""
    scope = _s(envelope, "scope")
    if scope and not valid_scope(scope):
        found.reject(
            RULE_REQUIRED_MISSING,
            "envelope.scope",
            f"the scope intent was read under is {quote(scope)}, which is not a scope: "
            "the accepted form is tag:<name>, the literal tag: and one word",
        )
    reader = _envelope_value(envelope, ("mapping", "reader"))
    if reader and not valid_reader(reader):
        found.reject(
            RULE_REQUIRED_MISSING,
            "envelope.mapping.reader",
            f"the reader that mapped intent is named {quote(reader)}, which is not a reader's name: "
            "lowercase letters, digits and hyphens, beginning with a letter or a digit",
        )
    for i, row in enumerate(envelope.get("fidelity") or []):
        obj = f"envelope.fidelity[{i}]"
        what = f"fidelity row {i}"
        if _s(row, "object"):
            what += f" ({_s(row, 'object')})"
        disposition = _s(row, "disposition")
        if disposition not in (FIDELITY_APPROXIMATED, FIDELITY_OMITTED):
            found.reject(
                RULE_REQUIRED_MISSING,
                obj + ".disposition",
                f"{what} has disposition {quote(disposition)}: a row is {FIDELITY_APPROXIMATED} or {FIDELITY_OMITTED}",
            )
        for name in ("object", "source", "reason"):
            if not _s(row, name):
                found.reject(RULE_REQUIRED_MISSING, f"{obj}.{name}", f"{what} records no {name}")


def check_devices_present(ctm: dict, found: Findings) -> None:
    """A CTM with no devices is refused, naming the branch and the `at`: an empty read is
    almost always a wrong `at`, and a manifest of no node has no fidelity to report."""
    if ctm["devices"]:
        return
    envelope = ctm["envelope"]
    branch, at = _s(envelope, "branch"), _s(envelope, "at")
    where = f"branch {quote(branch)}"
    obj = branch or "envelope"
    if at:
        where += f" at {at}"
        obj += "@" + at
    found.reject(
        RULE_DEVICES_EMPTY,
        obj,
        f"no devices in intent for {where}; a twin of nothing cannot be built and has no fidelity to report",
    )


def check_device_name(device: dict, seen: set[str], found: Findings) -> bool:
    """Refuses a device with no name and a second device of a name, and says whether the
    device has a name of its own to check further by."""
    name = _s(device, "name")
    if not name:
        found.reject(RULE_REQUIRED_MISSING, "device", "a device has no name")
        return False
    if name in seen:
        found.reject(RULE_DEVICE_NAME_DUPLICATE, name, "two devices share this name; a node name must be unique")
        return False
    seen.add(name)
    return True


def check_links(ctm: dict, found: Findings) -> None:
    """Every link's shape and endpoints, then the links and each interface's link held to
    one another (link_terminations)."""
    for link in ctm["links"]:
        link_id = _s(link, "id")
        endpoints = link.get("endpoints") or []
        if len(endpoints) != 2:
            found.reject(
                RULE_LINK_ENDPOINTS_COUNT,
                link_id,
                f"link has {len(endpoints)} endpoints; a link connects exactly two interfaces",
            )
            continue
        a, b = endpoints
        if _s(a, "device") == _s(b, "device"):
            found.reject(RULE_LINK_ENDPOINTS_SAME_DEVICE, link_id, "both endpoints are on the same device")
        for e in endpoints:
            device = _device(ctm, _s(e, "device"))
            if device is None:
                found.reject(
                    RULE_REQUIRED_MISSING,
                    link_id,
                    f"endpoint names device {quote(_s(e, 'device'))}, which is not in intent",
                )
                continue
            if _interface(device, _s(e, "interface")) is None:
                found.reject(
                    RULE_REQUIRED_MISSING,
                    link_id,
                    f"endpoint names interface {quote(_s(e, 'interface'))}, which is not on {_s(e, 'device')}",
                )
    found.extend(link_terminations(ctm))


def link_terminations(ctm: dict) -> Findings:
    """Each interface's link and the CTM's links held to one another, every disagreement
    refused under data.required.missing: an interface two links end on; a link ending on
    an interface carrying no link, or another link's id; an interface carrying a link id
    no link ends on it. A link without two endpoints, an endpoint naming what is not in
    intent and a duplicated device's second entry are passed over: one fault is named
    once. Expects a normalized CTM."""
    found = Findings()

    # The link each interface carries, for the first device of each name.
    carried: dict[str, str] = {}
    order: list[str] = []
    seen: set[str] = set()
    for d in ctm["devices"]:
        name = _s(d, "name")
        if not name or name in seen:
            continue
        seen.add(name)
        for i in d["interfaces"]:
            iid = f"{name}:{_s(i, 'name')}"
            if iid in carried or not _s(i, "name"):
                continue
            carried[iid] = _s(i, "link")
            order.append(iid)

    # The links that end on each interface, by index, a link naming one interface at both
    # ends counted once.
    by_id: dict[str, int] = {}
    ends: dict[str, list[int]] = {}
    links = ctm["links"]
    for n, link in enumerate(links):
        by_id.setdefault(_s(link, "id"), n)
        endpoints = link.get("endpoints") or []
        if len(endpoints) != 2:
            continue
        for e in endpoints:
            eid = _endpoint_id(e)
            on = ends.get(eid)
            if eid not in carried or (on and on[-1] == n):
                continue
            ends.setdefault(eid, []).append(n)

    for iid in order:
        on, link = ends.get(iid, []), carried[iid]
        if len(on) > 1:
            ids = ", ".join(_s(links[n], "id") for n in on)
            found.reject(
                RULE_REQUIRED_MISSING,
                iid,
                f"{iid} is an endpoint of {len(on)} links ({ids}); {NAMES_ITS_LINK}, "
                "and a bundle whose links cable one port twice is never produced",
            )
        elif not on and link:
            n = by_id.get(link)
            if n is None:
                found.reject(
                    RULE_REQUIRED_MISSING,
                    iid,
                    f"{iid} carries link {quote(link)}, which is not in intent; {NAMES_ITS_LINK}, "
                    "and a bundle that calls a port cabled with no cable on it is never produced",
                )
            elif len(links[n].get("endpoints") or []) == 2:
                found.reject(
                    RULE_REQUIRED_MISSING,
                    iid,
                    f"{iid} carries link {quote(link)}, which does not end on it; {NAMES_ITS_LINK}, "
                    "and a bundle that calls a port cabled with no cable on it is never produced",
                )

    for link in links:
        endpoints = link.get("endpoints") or []
        if len(endpoints) != 2:
            continue
        link_id = _s(link, "id")
        for e in endpoints:
            eid = _endpoint_id(e)
            if eid not in carried or len(ends.get(eid, [])) != 1 or carried[eid] == link_id:
                continue
            if not carried[eid]:
                found.reject(
                    RULE_REQUIRED_MISSING,
                    link_id,
                    f"endpoint {eid} carries no link; {NAMES_ITS_LINK}, and a bundle that cables a port "
                    f"its mapping calls {DISP_CONFIGURED_NOT_CABLED} is never produced",
                )
                continue
            found.reject(
                RULE_REQUIRED_MISSING, link_id, f"endpoint {eid} carries link {quote(carried[eid])}; {NAMES_ITS_LINK}"
            )
    return found
