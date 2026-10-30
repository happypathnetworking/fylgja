"""The snapshot the adapter writes (data-model §4, R-07): one document of version 2
wrapping a CTM 2 and the probe declarations beside it, with an id of its own, written as
the core's `internal/snapshot` writes it, so the core files it under the same id.

A snapshot is a plain dict here, as JSON decodes it: `snapshot_version`, `snapshot_id`,
`observed_at`, `ctm` and `probes`. The id is the lowercase-hex SHA-256 of the hashed
bytes: `{"ctm": …, "probes": […]}`, the CTM normalised and its envelope written without
`observed_at`, encoded as Go's `json.MarshalIndent(…, "", "  ")` encodes it plus a
newline. Key order is the Go structs' (`internal/ctm/types.go`, `internal/probe/decl.go`),
a field Go leaves out when empty left out alike, and strings escaped as Go escapes them:
`<`, `>`, `&`, U+2028 and U+2029 as `\\u` escapes, which `json.dumps` writes raw. The
bytes the id hashes are never stored.

It imports the standard library alone: nothing here reads a source.
"""

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

VERSION = "2"
"""The snapshot's format version, the one every document this module writes declares."""

VERSION_1 = "1"
"""The version 018 wrote, read as a VERSION with no probes and never written."""

CTM_VERSION = "2"

PROVENANCE_INTENT = "intent"

OBSERVED_AT_FORM = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
"""The take's observed_at: UTC, six fractional digits (`snapshot.ObservedAtLayout`)."""

# The characters Go's encoder escapes in a string and json.dumps(ensure_ascii=False)
# writes raw (encoding/json's HTML-safe set), and a lone surrogate, which Go decodes as
# U+FFFD and Python keeps. None can appear outside a string in the encoded text, so the
# encoded text is translated whole.
_GO_ESCAPES = str.maketrans(
    {
        "<": "\\u003c",
        ">": "\\u003e",
        "&": "\\u0026",
        "\N{LINE SEPARATOR}": "\\u2028",
        "\N{PARAGRAPH SEPARATOR}": "\\u2029",
        **{chr(c): "\N{REPLACEMENT CHARACTER}" for c in range(0xD800, 0xE000)},
    }
)


class SnapshotError(ValueError):
    """A document that is not a snapshot this module reads or writes. `rule` is the rule the
    core files the same refusal under (`snapshot.version.unsupported`, `snapshot.invalid`,
    `snapshot.id.mismatch`), and `field` the key at fault, empty for the document."""

    def __init__(self, rule: str, message: str, field: str = ""):
        super().__init__(message)
        self.rule = rule
        self.field = field


def _endpoint_id(endpoint: dict) -> str:
    return f"{endpoint.get('device', '')}:{endpoint.get('interface', '')}"


def normalize(ctm: dict) -> dict:
    """Puts a CTM into canonical form, in place, and returns it: `ctm.Normalize`'s defaults
    and sorts. The version, the lists left out or null as [], every object's provenance as
    `intent` and every interface enabled when unset; the fidelity rows by the whole row,
    each device's interfaces by name, the devices by name, each link's endpoints by
    `device:interface` and the links by id, every sort stable. Python orders strings by code
    point, which is UTF-8's byte order, Go's. It does not validate."""
    if not ctm.get("ctm_version"):
        ctm["ctm_version"] = CTM_VERSION
    if ctm.get("devices") is None:
        ctm["devices"] = []
    if ctm.get("links") is None:
        ctm["links"] = []
    envelope = ctm.setdefault("envelope", {})
    if envelope.get("fidelity") is None:
        envelope["fidelity"] = []
    envelope["fidelity"].sort(
        key=lambda r: (r.get("disposition", ""), r.get("object", ""), r.get("source", ""), r.get("reason", ""))
    )
    for device in ctm["devices"]:
        if not device.get("provenance"):
            device["provenance"] = PROVENANCE_INTENT
        if device.get("interfaces") is None:
            device["interfaces"] = []
        for interface in device["interfaces"]:
            if not interface.get("provenance"):
                interface["provenance"] = PROVENANCE_INTENT
            if interface.get("enabled") is None:
                interface["enabled"] = True
        device["interfaces"].sort(key=lambda i: i.get("name", ""))
    ctm["devices"].sort(key=lambda d: d.get("name", ""))
    for link in ctm["links"]:
        if not link.get("provenance"):
            link["provenance"] = PROVENANCE_INTENT
        if link.get("endpoints") is not None:
            link["endpoints"].sort(key=_endpoint_id)
    ctm["links"].sort(key=lambda link: link.get("id", ""))
    return ctm


# The encoders below write each object as Go's struct writes it: its fields in the struct's
# order, a string Go would write "" when absent, a field tagged omitempty (or omitzero, a
# provenance of intent) left out when empty. A key the struct does not hold is dropped, as
# Go's decode into the struct drops it.


def _put_provenance(out: dict, obj: dict) -> None:
    provenance = obj.get("provenance") or ""
    if provenance not in ("", PROVENANCE_INTENT):
        out["provenance"] = provenance


def _fidelity_row(row: dict) -> dict:
    return {k: row.get(k, "") for k in ("disposition", "object", "source", "reason")}


def _envelope(envelope: dict, with_observed_at: bool) -> dict:
    out = {"branch": envelope.get("branch", "")}
    if envelope.get("at"):
        out["at"] = envelope["at"]
    if with_observed_at:
        out["observed_at"] = envelope.get("observed_at", "")
    out["schema_hash"] = envelope.get("schema_hash", "")
    out["scope"] = envelope.get("scope", "")
    mapping = envelope.get("mapping") or {}
    out["mapping"] = {k: mapping.get(k, "") for k in ("reader", "model", "version")}
    fidelity = envelope.get("fidelity")
    out["fidelity"] = None if fidelity is None else [_fidelity_row(r) for r in fidelity]
    return out


def _interface(interface: dict) -> dict:
    out = {"name": interface.get("name", ""), "mgmt_only": bool(interface.get("mgmt_only", False))}
    if interface.get("enabled") is not None:
        out["enabled"] = bool(interface["enabled"])
    if interface.get("link"):
        out["link"] = interface["link"]
    _put_provenance(out, interface)
    return out


def _device(device: dict) -> dict:
    platform = device.get("platform") or {}
    out = {"name": device.get("name", ""), "platform": {"package": platform.get("package", "")}}
    if platform.get("version"):
        out["platform"]["version"] = platform["version"]
    interfaces = device.get("interfaces")
    out["interfaces"] = None if interfaces is None else [_interface(i) for i in interfaces]
    artifact = device.get("artifact")
    if artifact is not None:
        out["artifact"] = {k: artifact.get(k, "") for k in ("name", "content_type", "checksum", "content")}
    _put_provenance(out, device)
    return out


def _link(link: dict) -> dict:
    endpoints = link.get("endpoints")
    out = {
        "id": link.get("id", ""),
        "endpoints": None
        if endpoints is None
        else [{"device": e.get("device", ""), "interface": e.get("interface", "")} for e in endpoints],
    }
    _put_provenance(out, link)
    return out


def _ctm(ctm: dict, with_observed_at: bool) -> dict:
    devices, links = ctm.get("devices"), ctm.get("links")
    return {
        "ctm_version": ctm.get("ctm_version", ""),
        "envelope": _envelope(ctm.get("envelope") or {}, with_observed_at),
        "devices": None if devices is None else [_device(d) for d in devices],
        "links": None if links is None else [_link(lk) for lk in links],
    }


_PROBE_ENDPOINT_KEYS = ("device", "interface", "address", "gateway")


def _probe(probe: dict) -> dict:
    # Endpoints is a [2]Endpoint in Go: always two, a missing one written empty.
    endpoints = list(probe.get("endpoints") or [])[:2]
    endpoints += [{}] * (2 - len(endpoints))
    return {
        "name": probe.get("name", ""),
        "format": probe.get("format", ""),
        "endpoints": [{k: e.get(k, "") for k in _PROBE_ENDPOINT_KEYS} for e in endpoints],
    }


def _probes(probes) -> list:
    # Written [] and never null.
    return [_probe(p) for p in probes or []]


def _encode(value) -> bytes:
    """Go's json.MarshalIndent(value, "", "  ") plus a newline, over dicts already in the
    structs' key order."""
    text = json.dumps(value, indent=2, ensure_ascii=False)
    return (text.translate(_GO_ESCAPES) + "\n").encode("utf-8")


def hashed_bytes(snapshot: dict) -> bytes:
    """The bytes a snapshot's id hashes (`snapshot.Hashed`): `{"ctm": …, "probes": […]}`,
    the version, the id and both observed_at left out, the CTM normalised in place, as Go
    normalises it."""
    ctm = snapshot.get("ctm")
    if ctm is None:
        raise SnapshotError("snapshot.invalid", "snapshot: no ctm to hash", "ctm")
    normalize(ctm)
    return _encode({"ctm": _ctm(ctm, with_observed_at=False), "probes": _probes(snapshot.get("probes"))})


def snapshot_id(snapshot: dict) -> str:
    """A snapshot's content address: the lowercase-hex SHA-256 of its hashed bytes, never
    what its `snapshot_id` declares."""
    return hashlib.sha256(hashed_bytes(snapshot)).hexdigest()


def is_id(value) -> bool:
    """Whether value has a snapshot id's shape: 64 lowercase hex digits."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def take(ctm: dict, probes=None) -> dict:
    """Wraps a CTM and a list of probes as a snapshot of version 2 (`snapshot.Take`): both
    copied, the copy normalised, observed_at the CTM's envelope's, the id computed. The
    caller's are untouched. It holds the probes to no rule: the read validates them first."""
    inner = normalize(copy.deepcopy(ctm))
    snapshot = {
        "snapshot_version": VERSION,
        "snapshot_id": "",
        "observed_at": inner.get("envelope", {}).get("observed_at", ""),
        "ctm": inner,
        "probes": copy.deepcopy(list(probes or [])),
    }
    snapshot["snapshot_id"] = snapshot_id(snapshot)
    return snapshot


def _check(snapshot: dict) -> None:
    """Holds a snapshot to version 2's invariants before it is written, as `Marshal` does:
    the version "2", observed_at the inner CTM's and of its form, the id the body's hash.
    The probes' declaration rules are the read's, which validates them before the take."""
    ctm = snapshot.get("ctm")
    if not isinstance(ctm, dict):
        raise SnapshotError("snapshot.invalid", "snapshot: no ctm", "ctm")
    if snapshot.get("snapshot_version") != VERSION:
        raise SnapshotError(
            "snapshot.invalid",
            f"snapshot: snapshot_version {snapshot.get('snapshot_version')!r}, where this module writes {VERSION!r}",
            "snapshot_version",
        )
    observed_at = snapshot.get("observed_at", "")
    inner = (ctm.get("envelope") or {}).get("observed_at", "")
    if observed_at != inner:
        raise SnapshotError(
            "snapshot.invalid", f"snapshot: observed_at {observed_at!r} is not the inner CTM's {inner!r}", "observed_at"
        )
    if not isinstance(observed_at, str) or not OBSERVED_AT_FORM.match(observed_at):
        raise SnapshotError(
            "snapshot.invalid",
            f"snapshot: observed_at {observed_at!r} is not a UTC time with six fractional digits",
            "observed_at",
        )
    computed = snapshot_id(snapshot)
    if snapshot.get("snapshot_id") != computed:
        raise SnapshotError(
            "snapshot.id.mismatch",
            f"snapshot: snapshot_id {snapshot.get('snapshot_id')!r} is not its body's hash {computed}",
            "snapshot_id",
        )


def marshal(snapshot: dict) -> bytes:
    """A snapshot in its stored form, as `snapshot.Marshal` writes it: snapshot_version,
    snapshot_id, observed_at, then ctm (normalised, its envelope's observed_at kept), then
    probes; refused when it breaks version 2's invariants."""
    _check(snapshot)
    return _encode(
        {
            "snapshot_version": VERSION,
            "snapshot_id": snapshot["snapshot_id"],
            "observed_at": snapshot["observed_at"],
            "ctm": _ctm(snapshot["ctm"], with_observed_at=True),
            "probes": _probes(snapshot.get("probes")),
        }
    )


def write(path, snapshot: dict) -> None:
    """Writes a snapshot in its stored form to a temporary sibling renamed into place, mode
    0644, so the file is whole or absent."""
    data = marshal(snapshot)
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".fylgja-snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def unmarshal(data: bytes) -> dict:
    """Decodes a snapshot and returns it normalised with its id and observed_at filled: the
    version first (a "1" read as a "2" whose list must be empty), then the outer shape, then
    the id computed and held to the one declared. The inner CTM's own rules and the probes'
    are validation's, not this read's."""
    try:
        doc = json.loads(data)
    except ValueError as e:
        raise SnapshotError("snapshot.invalid", f"decoding snapshot: {e}") from e
    if not isinstance(doc, dict):
        raise SnapshotError("snapshot.invalid", "the snapshot is not a JSON object")
    version = doc.get("snapshot_version")
    if version not in (VERSION, VERSION_1):
        declares = "declares no snapshot_version" if version is None else f"declares snapshot_version {version!r}"
        raise SnapshotError(
            "snapshot.version.unsupported",
            f"the snapshot {declares}; this module reads {VERSION_1!r} and {VERSION!r}, and nothing converts one",
        )
    unknown = sorted(set(doc) - {"snapshot_version", "snapshot_id", "observed_at", "ctm", "probes"})
    if unknown:
        raise SnapshotError(
            "snapshot.invalid",
            f"the snapshot carries the key {unknown[0]!r}, which snapshot {VERSION} does not hold",
            unknown[0],
        )
    if not isinstance(doc.get("ctm"), dict):
        raise SnapshotError("snapshot.invalid", "ctm is not recorded or not an object", "ctm")
    probes = doc.get("probes")
    if not isinstance(probes, list):
        raise SnapshotError("snapshot.invalid", "probes is not recorded or not a list", "probes")
    if version == VERSION_1 and probes:
        raise SnapshotError("snapshot.invalid", "in snapshot 1 the list of probes is empty", "probes")
    declared = doc.get("snapshot_id")
    if "snapshot_id" in doc and not is_id(declared):
        raise SnapshotError(
            "snapshot.invalid", f"snapshot_id {declared!r} is not 64 lowercase hex characters", "snapshot_id"
        )
    ctm = normalize(doc["ctm"])
    inner = ctm["envelope"].get("observed_at", "")
    observed_at = doc.get("observed_at", inner)
    if observed_at != inner:
        raise SnapshotError(
            "snapshot.invalid", f"observed_at {observed_at!r} is not the inner CTM's ({inner!r})", "observed_at"
        )
    snapshot = {
        "snapshot_version": VERSION,
        "snapshot_id": "",
        "observed_at": observed_at,
        "ctm": ctm,
        "probes": probes,
    }
    computed = snapshot_id(snapshot)
    if declared is not None and declared != computed:
        raise SnapshotError(
            "snapshot.id.mismatch", f"declares snapshot_id {declared}, but its body hashes to {computed}", "snapshot_id"
        )
    snapshot["snapshot_id"] = computed
    return snapshot


def read(path) -> dict:
    """Reads a snapshot from a file, through unmarshal."""
    return unmarshal(Path(path).read_bytes())
