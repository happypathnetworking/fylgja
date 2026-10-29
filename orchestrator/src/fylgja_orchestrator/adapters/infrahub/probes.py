"""The request's one probe list (016, D-064; R-06): the file `--probes` names, else the
probes declared in `FylgjaProbe` on the default branch, else none. Ported from
`internal/probe/decl.go` (`Parse`, `DecodeProbe`, `Validate`), `internal/intent/probes.go`
(the kind's check and read) and `internal/server/probes.go` (`readProbes`), word for word.

A probe is a pair of synthesized hosts on two uncabled ports of the intent's devices. It is
not intent and never enters the CTM: the snapshot carries the list beside it, each element
`{name, format, endpoints: [a, b]}`, each endpoint `{device, interface, address, gateway}`.
A file replaces the kind's probes, never adds to them. The file is `probes 1`
(`contracts/probes.schema.json`), decoded strictly: every key exact and required, every
fault in one pass; an empty file, or one of JSON's whitespace alone, declares none. Every
probe is then held to the rules that read no CTM, with the formats the probe packages
declare; the placement's rules read the CTM and are the core's compile's.
"""

import ipaddress
import json
import os
import re
from pathlib import Path

import yaml

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub.client import ClientError
from fylgja_orchestrator.adapters.infrahub.packages import ENV_OVERRIDE, shipped_dir
from fylgja_orchestrator.adapters.infrahub.read import ReadError, paged
from fylgja_orchestrator.documents.findings import REJECTION, Finding, Findings, quote

VERSION = "1"
"""The declaration file's version, the one this build reads; nothing older exists."""

PROBE_KIND = "FylgjaProbe"
PROBE_SCHEMA_FILE = "schema/fylgja-probe.yaml"
PROBE_FIELDS = (
    "name",
    "format",
    "a_device",
    "a_interface",
    "a_address",
    "a_gateway",
    "b_device",
    "b_interface",
    "b_address",
    "b_gateway",
)
"""Every attribute of the kind the build reads, in the declaration's order; the kind's
description is never read."""

NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")
"""Matched whole (`fullmatch`): Python's `$` also matches before a trailing newline,
which Go's does not."""
NAME_PATTERN_TEXT = "^[a-z0-9][a-z0-9-]{0,23}$"
ENDS = ("a", "b")

DOCUMENT_KEYS = ("probes_version", "probes")
PROBE_KEYS = ("name", "format", "endpoints")
ENDPOINT_KEYS = ("device", "interface", "address", "gateway")

STEP_START = "start"
STEP_RESOLVE = "resolve"

RULE_PROBES_VERSION_UNSUPPORTED = "probes.version.unsupported"
RULE_PROBES_INVALID = "probes.invalid"
RULE_PROBE_NAME_INVALID = "probe.name.invalid"
RULE_PROBE_NAME_DUPLICATE = "probe.name.duplicate"
RULE_PROBE_FORMAT_UNKNOWN = "probe.format.unknown"
RULE_PROBE_ADDRESS_INVALID = "probe.address.invalid"
RULE_PROBE_GATEWAY_INVALID = "probe.gateway.invalid"
RULE_PROBE_GATEWAY_OUTSIDE = "probe.gateway.outside"
RULE_PROBE_FAMILY_MIXED = "probe.family.mixed"
RULE_PROBE_ADDRESS_DUPLICATE = "probe.address.duplicate"
RULE_PROBE_KIND_ABSENT = "probe.kind.absent"

PROBE_KIND_REMEDY = f": load {PROBE_SCHEMA_FILE} on it; only a request that sends no --probes file reads it"
"""What follows the kind's error in every probe.kind.absent finding."""


class ProbeKindError(Exception):
    """The default branch's schema cannot serve a read of the kind: the kind is absent, or it
    lacks an attribute this build reads, named in PROBE_FIELDS' order."""

    def __init__(self, missing=()):
        self.missing = list(missing)
        if not self.missing:
            message = f"the default branch's schema has no kind {PROBE_KIND}"
        elif len(self.missing) == 1:
            message = (
                f"kind {PROBE_KIND} on the default branch lacks the attribute {self.missing[0]}, "
                "which this build reads"
            )
        else:
            message = (
                f"kind {PROBE_KIND} on the default branch lacks the attributes {', '.join(self.missing)}, "
                "which this build reads"
            )
        super().__init__(message)


class ProbesError(ReadError):
    """The probes could not be read, safe to print: Infrahub refused or never answered, or
    the probe packages could not be loaded. The command files it `operation.failed` at
    `step`, about `object`."""

    def __init__(self, message: str, step: str, object: str):
        super().__init__(message)
        self.step = step
        self.object = object


# The declaration.


def _raw(value) -> str:
    """A JSON value as its text, as Go's raw message names a value of the wrong type."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _no_constant(name: str):
    """NaN, Infinity and -Infinity are no JSON, as Go's decoder holds: the document is
    refused as not a JSON object."""
    raise ValueError(f"{name} is not JSON")


def _unknown_keys(fields: dict, keys) -> list[str]:
    return sorted(k for k in fields if k not in keys)


def _object(raw, at: str, keys, what: str, found: Findings) -> dict | None:
    """raw as an object of exactly keys, each required: a finding for a value that is not
    an object, each unknown key and each key absent."""
    if not isinstance(raw, dict):
        found.reject(RULE_PROBES_INVALID, at, f"{at} is not a JSON object: it is {what}")
        return None
    for k in _unknown_keys(raw, keys):
        found.reject(
            RULE_PROBES_INVALID,
            f"{at}.{k}",
            f"{what} carries the key {quote(k)}, which it does not hold: it holds {', '.join(keys)}",
        )
    for k in keys:
        if k not in raw:
            found.reject(RULE_PROBES_INVALID, f"{at}.{k}", f"{what} has no {k}, which it requires")
    return raw


def _str(fields: dict, key: str, at: str, found: Findings) -> str:
    """A present field as a string, a finding when it is not one; absent reads as ""."""
    if key not in fields:
        return ""
    v = fields[key]
    if not isinstance(v, str):
        found.reject(RULE_PROBES_INVALID, f"{at}.{key}", f"{key} is {_raw(v)}, not a string")
        return ""
    return v


def decode_probe(raw, at: str) -> tuple[dict, Findings]:
    """One probe object decoded strictly: every key exact, every field present and a string,
    exactly two endpoints. Each fault is probes.invalid at `<at>.<field>`, at
    `<at>.endpoints[<j>].<field>` for an endpoint's."""
    found = Findings()
    probe = {"name": "", "format": "", "endpoints": [dict.fromkeys(ENDPOINT_KEYS, "") for _ in ENDS]}
    fields = _object(raw, at, PROBE_KEYS, "a probe", found)
    if fields is None:
        return probe, found
    probe["name"] = _str(fields, "name", at, found)
    probe["format"] = _str(fields, "format", at, found)
    if "endpoints" not in fields:
        return probe, found
    ends = fields["endpoints"]
    if not isinstance(ends, list):
        found.reject(
            RULE_PROBES_INVALID, f"{at}.endpoints", "endpoints is not a list: a probe has exactly two endpoints"
        )
        return probe, found
    if len(ends) != 2:
        found.reject(
            RULE_PROBES_INVALID,
            f"{at}.endpoints",
            f"endpoints holds {len(ends)}; a probe has exactly two, a and b",
        )
        return probe, found
    for j, e in enumerate(ends):
        where = f"{at}.endpoints[{j}]"
        f = _object(e, where, ENDPOINT_KEYS, "an endpoint", found)
        if f is None:
            continue
        probe["endpoints"][j] = {k: _str(f, k, where, found) for k in ENDPOINT_KEYS}
    return probe, found


def parse(data: bytes, path: str) -> tuple[dict | None, Findings]:
    """A declaration decoded strictly and held to the rules that read no CTM. The version
    is read first, on its own: not "1", or none, is probes.version.unsupported and nothing
    else is read. Then the shape, every fault in one pass; then, when it holds, `validate`'s
    rules with no formats, each probe named by its name. The declaration, `{probes_version,
    probes}`, is returned only when nothing is rejected. An empty file, or one of JSON's
    whitespace alone, declares no probes."""
    if not data.strip(b" \t\r\n"):
        return {"probes_version": VERSION, "probes": []}, Findings()
    found = Findings()
    try:
        outer = json.loads(data.decode("utf-8", "replace"), parse_constant=_no_constant)
    except ValueError:
        outer = None
    if not isinstance(outer, dict):
        found.reject(RULE_PROBES_INVALID, path, "the probe declaration is not a JSON object")
        return None, found

    version = outer.get("probes_version")
    if version is None:
        found.reject(
            RULE_PROBES_VERSION_UNSUPPORTED,
            path,
            f"the probe declaration names no probes_version; this build reads probes {VERSION}",
        )
        return None, found
    if version != VERSION:
        # A value that is not a string is named as its JSON text, so 1 and "1" differ.
        found.reject(
            RULE_PROBES_VERSION_UNSUPPORTED,
            path,
            f"the probe declaration is probes_version {_raw(version)}; this build reads probes {quote(VERSION)}",
        )
        return None, found

    for k in _unknown_keys(outer, DOCUMENT_KEYS):
        found.reject(
            RULE_PROBES_INVALID,
            path,
            f"the probe declaration carries the key {quote(k)}, which probes {VERSION} does not hold: it holds "
            "probes_version and probes",
        )
    elements = []
    raw_probes = outer.get("probes")
    if raw_probes is None:
        found.reject(
            RULE_PROBES_INVALID, path, "the probe declaration has no probes list; write probes: [] to declare none"
        )
    elif not isinstance(raw_probes, list):
        found.reject(RULE_PROBES_INVALID, path, "the probe declaration's probes is not a list")
    else:
        elements = raw_probes
    probes = []
    for i, element in enumerate(elements):
        probe, faults = decode_probe(element, f"probes[{i}]")
        found.extend(faults)
        probes.append(probe)
    if found.rejected:
        return None, found
    rules = validate(probes)
    if rules.rejected:
        found.extend(rules)
        return None, found
    return {"probes_version": VERSION, "probes": probes}, found


def _family(address) -> str:
    if address.version == 4 or address.ipv4_mapped is not None:
        return "IPv4"
    return "IPv6"


def _addr_text(address) -> str:
    """An address as Go's netip writes it: an IPv4-mapped IPv6 address with its dotted
    tail."""
    if address.version == 6 and address.ipv4_mapped is not None:
        return f"::ffff:{address.ipv4_mapped}"
    return str(address)


def _parse_prefix(text: str):
    """An address with its prefix length, as netip.ParsePrefix reads one: the length
    decimal, with no sign and no leading zero, and no zone."""
    addr, sep, bits = text.partition("/")
    if not sep or not bits.isascii() or not bits.isdigit() or (len(bits) > 1 and bits[0] == "0") or "%" in addr:
        return None
    try:
        return ipaddress.ip_interface(text)
    except ValueError:
        return None


def _parse_addr(text: str):
    """An address alone, as netip.ParseAddr reads one with no zone."""
    if "/" in text or "%" in text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def validate(probes: list[dict], formats=None, object_of=None) -> Findings:
    """A list of probes held to the rules that read no CTM, every fault in one pass:
    probe.name.invalid, probe.name.duplicate, probe.format.unknown (only when `formats` is
    given), probe.address.invalid, probe.gateway.invalid, probe.gateway.outside,
    probe.family.mixed and probe.address.duplicate, across the whole list. `object_of(i)`
    names probe i in a finding, its name when None; a finding about one endpoint's field is
    at `<object>/<a|b>.<field>`."""
    if object_of is None:

        def object_of(i):
            return probes[i]["name"]

    found = Findings()
    first_by_name: dict[str, int] = {}
    by_address: dict = {}
    for i, p in enumerate(probes):
        name = object_of(i)
        if not NAME_PATTERN.fullmatch(p["name"]):
            found.reject(
                RULE_PROBE_NAME_INVALID,
                name,
                f"probe name {quote(p['name'])} is not {NAME_PATTERN_TEXT}: lowercase letters, digits and '-', at "
                "most 24, beginning with a letter or a digit",
            )
        if p["name"] in first_by_name:
            found.reject(
                RULE_PROBE_NAME_DUPLICATE,
                name,
                f"probe name {quote(p['name'])} is declared at probes[{first_by_name[p['name']]}] and probes[{i}]; "
                "a name is one probe's",
            )
        else:
            first_by_name[p["name"]] = i
        if formats is not None and p["format"] not in formats:
            found.reject(
                RULE_PROBE_FORMAT_UNKNOWN,
                name,
                f"format {quote(p['format'])}: no probe package declares it; the formats loaded are "
                f"{', '.join(formats)}",
            )

        families = []
        for j, e in enumerate(p["endpoints"]):
            end = f"{name}/{ENDS[j]}"
            prefix = _parse_prefix(e["address"])
            if prefix is None:
                found.reject(
                    RULE_PROBE_ADDRESS_INVALID,
                    end + ".address",
                    f"address {quote(e['address'])} is not an address with a prefix length, as 10.1.10.2/24",
                )
            gateway = _parse_addr(e["gateway"])
            if gateway is None:
                why = (
                    "carries a prefix length; a gateway is an address alone"
                    if "/" in e["gateway"]
                    else "is not an address"
                )
                found.reject(
                    RULE_PROBE_GATEWAY_INVALID, end + ".gateway", f"gateway {quote(e['gateway'])} {why}, as 10.1.10.1"
                )
            if prefix is not None:
                host = prefix.ip
                families.append(_family(host))
                if host in by_address:
                    prior_probe, prior_end = by_address[host]
                    found.reject(
                        RULE_PROBE_ADDRESS_DUPLICATE,
                        end + ".address",
                        f"address {_addr_text(host)} of probe {p['name']} endpoint {ENDS[j]} is probe {prior_probe} "
                        f"endpoint {prior_end}'s too: two hosts on one address cannot be told apart by a ping",
                    )
                else:
                    by_address[host] = (p["name"], ENDS[j])
            if gateway is not None:
                families.append(_family(gateway))
            if (
                prefix is not None
                and gateway is not None
                and _family(prefix.ip) == _family(gateway)
                and (prefix.ip.version != gateway.version or gateway not in prefix.network)
            ):
                found.reject(
                    RULE_PROBE_GATEWAY_OUTSIDE,
                    end + ".gateway",
                    f"gateway {_addr_text(gateway)} is not within {_addr_text(prefix.network.network_address)}/"
                    f"{prefix.network.prefixlen}, so the host's route to the far host could not be added",
                )
        if "IPv4" in families and "IPv6" in families:
            found.reject(
                RULE_PROBE_FAMILY_MIXED,
                name,
                f"probe {p['name']}'s addresses and gateways are of two families ({', '.join(families)}); a probe's "
                "four are of one",
            )
    return found


# The probe packages' formats.


def shipped_probes_dir() -> Path:
    """`probes/` beside the shipped `psp/`: the repository's, or FYLGJA_PSP_SHIPPED's
    sibling when the orchestrator is installed elsewhere."""
    return shipped_dir().parent / "probes"


def formats(override_dir: str | None = None, shipped: str | Path | None = None) -> list[str]:
    """The formats the probe packages declare, sorted: the shipped packages', then those
    under the override directory's `probes/` (FYLGJA_PSP_DIR when none is given), as the
    core's probe registry loads them. Only `format` is read: the packages are the core's,
    which validates them."""
    directory = Path(shipped) if shipped else shipped_probes_dir()
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise ProbesError(f"no probe package under {directory}", STEP_START, STEP_START)
    if override_dir is None:
        override_dir = os.environ.get(ENV_OVERRIDE, "")
    if override_dir:
        paths += sorted((Path(override_dir) / "probes").glob("*.yaml"))
    out = set()
    for path in paths:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            raise ProbesError(f"reading probe package {path}: {e}", STEP_START, STEP_START) from None
        if isinstance(doc, dict) and isinstance(doc.get("format"), str):
            out.add(doc["format"])
    return sorted(out)


# The kind.


def check_kind(reader) -> None:
    """The default branch's schema holds the kind with every attribute in PROBE_FIELDS:
    ProbeKindError when it does not. Run before the query, since a query of a kind the
    schema lacks is an HTTP 200 whose message names nothing an operator can act on."""
    for node in reader.schema_nodes():
        if node.get("kind") != PROBE_KIND:
            continue
        have = {a.get("name") for a in node.get("attributes") or [] if isinstance(a, dict)}
        missing = [f for f in PROBE_FIELDS if f not in have]
        if missing:
            raise ProbeKindError(missing)
        return
    raise ProbeKindError()


def read_kind(reader) -> list[dict]:
    """Every object of the kind, each the declaration's element by renaming alone, every
    value verbatim, sorted by name (the kind's order_by) whatever order the server answers
    in; [] when none."""
    out = []
    for n in paged(reader, queries.PROBES, PROBE_KIND, {}, f"reading the probes of kind {PROBE_KIND}"):
        out.append(
            {
                "name": queries.value(n.get("name")),
                "format": queries.value(n.get("format")),
                "endpoints": [
                    {k: queries.value(n.get(f"{end}_{k}")) for k in ENDPOINT_KEYS} for end in ENDS
                ],
            }
        )
    out.sort(key=lambda p: p["name"])
    return out


def in_file(found: Findings, path: str) -> Findings:
    """The probe file named in each finding not already at it."""
    return Findings(
        f if f.object == path else Finding(f.severity, f.rule, f.object, f"probe file {path}: {f.message}", f.step)
        for f in found
    )


def in_kind(found: Findings) -> Findings:
    """The kind named in each finding about a probe read from it."""
    return Findings(
        Finding(f.severity, f.rule, f.object, f"{PROBE_KIND} on the default branch: {f.message}", f.step)
        for f in found
    )


def from_file(data: bytes, path: str, loaded_formats=None) -> tuple[list[dict] | None, Findings]:
    """The list of a probe file, at start: its version and shape, then its rules with the
    formats the probe packages declare. Findings about the document are at its path; those
    about a probe or a field say the path before their sentence."""
    declaration, found = parse(data, path)
    if declaration is None:
        return None, in_file(found, path).at_step(STEP_START)
    if loaded_formats is None:
        loaded_formats = formats()
    found.extend(validate(declaration["probes"], loaded_formats))
    if found.rejected:
        return None, in_file(found, path).at_step(STEP_START)
    return declaration["probes"], found


def from_kind(reader, loaded_formats=None) -> tuple[list[dict] | None, Findings]:
    """The probes declared in the kind on the default branch, unpinned, held to the same
    rules, each refusal at resolve; the kind absent is probe.kind.absent. An Infrahub that
    cannot be asked raises ProbesError at resolve, about the kind."""
    try:
        check_kind(reader)
    except ProbeKindError as e:
        found = Findings()
        found.add_step(REJECTION, STEP_RESOLVE, RULE_PROBE_KIND_ABSENT, PROBE_KIND, f"{e}{PROBE_KIND_REMEDY}")
        return None, found
    except ClientError as e:
        raise ProbesError(str(e), STEP_RESOLVE, PROBE_KIND) from None
    try:
        probes = read_kind(reader)
    except ReadError as e:
        raise ProbesError(str(e), STEP_RESOLVE, PROBE_KIND) from None
    if loaded_formats is None:
        try:
            loaded_formats = formats()
        except ProbesError as e:
            raise ProbesError(str(e), STEP_RESOLVE, STEP_RESOLVE) from None
    found = validate(probes, loaded_formats)
    if found.rejected:
        return None, in_kind(found).at_step(STEP_RESOLVE)
    return probes, found


def declared(path: str | None, reader=None, loaded_formats=None) -> tuple[list[dict] | None, Findings]:
    """The request's one probe list, read once, after the guards and before any read of
    intent: the file at `path` when one is named (`--probes`), else the kind's on the
    default branch through `reader` (a DefaultClient), else []. None and the refusals when
    either refused; ProbesError when a source could not be read."""
    if path is not None:
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            raise ProbesError(f"reading the probe file {path}: {e.strerror}", STEP_START, "--probes") from None
        return from_file(data, path, loaded_formats)
    if reader is None:
        return [], Findings()
    return from_kind(reader, loaded_formats)

