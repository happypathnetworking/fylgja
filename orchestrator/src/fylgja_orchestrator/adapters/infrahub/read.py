"""The read: a scope of a branch, as the schema library's DCIM holds it, into the CTM `2`
by the one documented mapping (D-057, Constitution III;
`specs/017-dcim-reader/contracts/mapping.md`), then taken as a snapshot `2` (D-061,
D-066). Ported from `internal/intent`'s project.go, cable.go, artifact.go,
completeness.go and summary.go, and `internal/stage`'s `Read`, word for word: every
refusal and omission is filed under the rule the Go reader filed it under, worded as it
worded it, and a read of one branch writes the snapshot the Go reader wrote, byte for byte.

The read selects the DcimDevices carrying the scope's tag, whatever their status, then
their physical ports by the devices' ids, each cable through its port's connector. Inside
the scope it is strict: a scope selecting no device is refused `scope.empty`, and a device
no package can be chosen for `platform.missing` or `platform.unmatched`, every one in one
pass, with no CTM. At the scope's edge it is not: a cable the mapping cannot place is
omitted, an info finding and a row of the envelope's fidelity list. Otherwise it projects
and judges nothing, but the configuration artifact, whose selection needs Infrahub in hand
(M5, D-028): which of a device's artifacts is its configuration, whether its content is
held, and whether the bytes served are the bytes Infrahub described. Then the CTM's own
rules (`validate.intrinsic`), and the take.

Only the intrinsic rules run here, where the Go reader ran every rule the compile runs
(`validate.Validate` with the registry): the rules that read a package's ports and
profiles are the core's, which runs them when it compiles the snapshot, so a scope the
core cannot build is refused there, under the same rules and words (R-07; research §5.11).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote as escape

from fylgja_orchestrator.adapters.infrahub import mapping, queries, snapshot, validate
from fylgja_orchestrator.adapters.infrahub.client import ClientError, check_at_precision, explain_status
from fylgja_orchestrator.adapters.infrahub.schema import check_conformance
from fylgja_orchestrator.documents.findings import INFO, REJECTION, Finding, Findings, quote

SCOPE_PREFIX = "tag:"
"""Begins every scope, `tag:<name>` (017)."""

ROLE_MANAGEMENT = "management"
"""The role of the management port (mapping.md §1)."""

STATUS_DISABLED = "disabled"
"""The status of a port that is not enabled (mapping.md §1)."""

STATUS_READY = "Ready"
"""The one artifact status a read accepts. Pending and Error mean the bytes on offer are not
the bytes production runs, and Fylgja never regenerates an artifact: that is a write."""

PHYSICAL_PORT = "InterfacePhysical"
"""The one endpoint kind a link may end on (mapping.md §4)."""

CABLE_KIND = "DcimCable"
"""The one connector kind a link may be; a kind of the operator's own beside it is omitted."""

OBSERVED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
"""The envelope's observed_at: UTC, six fractional digits, Z (`stage.ObservedAtFormat`)."""

RULE_SCOPE_EMPTY = "scope.empty"
RULE_PLATFORM_MISSING = "platform.missing"
RULE_PLATFORM_UNMATCHED = "platform.unmatched"
RULE_OMIT_CABLE_ENDS = "omit.cable.ends"
RULE_OMIT_CABLE_ENDPOINT = "omit.cable.endpoint"
RULE_OMIT_CABLE_OUTSIDE_SCOPE = "omit.cable.outside_scope"
RULE_OMIT_CABLE_KIND = "omit.cable.kind"
RULE_ARTIFACT_MISSING = "artifact.missing"
RULE_ARTIFACT_AMBIGUOUS = "artifact.ambiguous"
RULE_ARTIFACT_NOT_READY = "artifact.not_ready"
RULE_ARTIFACT_CONTENT_TYPE_UNSUPPORTED = "artifact.content_type.unsupported"
RULE_ARTIFACT_CONTENT_UNAVAILABLE = "artifact.content.unavailable"
RULE_ARTIFACT_CHECKSUM_MISMATCH = "artifact.checksum.mismatch"
RULE_AT_PRECISION = "intent.at.precision"

ARTIFACT_RULES = "artifact."
"""The prefix of every artifact rule, which `dedupe` reads."""

FIDELITY_APPROXIMATED = "approximated"
FIDELITY_OMITTED = "omitted"


class ReadError(Exception):
    """A read that could not be made, safe to print: the scope is not `tag:<name>`, or
    Infrahub refused or never answered (its ClientError's words), or answered a stamp that
    is no time. The command files it `operation.failed`, exit 2, as the Go reader's error
    was filed. `branch_missing` keeps the ClientError's mark."""

    def __init__(self, message: str, branch_missing: bool = False):
        super().__init__(message)
        self.branch_missing = branch_missing


def query(client, document: str, variables: dict, what: str) -> dict:
    """One GraphQL request's `data`, a refusal raised as ReadError."""
    try:
        return client.graphql(document, variables, what) or {}
    except ClientError as e:
        raise ReadError(str(e), e.branch_missing) from None


def paged(client, document: str, root: str, variables: dict, what: str, size: int = queries.PAGE_SIZE) -> list:
    """Every node of a paged root, `size` at a time, until a page reaches the count."""
    out = []
    offset = 0
    while True:
        page = query(client, document, {**variables, "limit": size, "offset": offset}, what).get(root)
        out.extend(queries.nodes(page))
        if offset + size >= queries.count(page):
            return out
        offset += size


def scope_tag(scope: str) -> str:
    """The name of the tag a scope names: `tag:<name>` without its `tag:`."""
    return scope.removeprefix(SCOPE_PREFIX)


def observed_now() -> str:
    """Now, as the envelope's observed_at: captured before the first request, so it is
    never later than anything the read could have seen, and never sent to Infrahub."""
    return datetime.now(UTC).strftime(OBSERVED_AT_FORMAT)


def read_fidelity() -> list[dict]:
    """What this reader approximates on every read (mapping.md §5): the management port and
    the admin state, each read from a field whose meaning is close to Fylgja's and not the
    same, and the platform's version, which the library does not carry. Each omitted cable,
    or connector of another kind, adds a row of its own."""
    return [
        {
            "disposition": FIDELITY_APPROXIMATED,
            "object": "interface.mgmt_only",
            "source": "InterfacePhysical.role",
            "reason": "the management port is the port whose role is management; "
            "the library has no management-only flag",
        },
        {
            "disposition": FIDELITY_APPROXIMATED,
            "object": "interface.enabled",
            "source": "InterfacePhysical.status",
            "reason": "a port is enabled unless its status is disabled; the library's status is not an admin state",
        },
        {
            "disposition": FIDELITY_OMITTED,
            "object": "platform.version",
            "source": "DcimPlatform",
            "reason": "the library's platform carries no version",
        },
    ]


def scope_empty(scope: str, branch: str, at: str) -> Finding:
    """The refusal of a read whose scope selects no device: the tag absent from the branch,
    or on no DcimDevice, which the read does not tell apart (telling them apart would read
    BuiltinTag itself). `at` is the read's, "" unpinned. The stages file it for a head whose
    stamps selected no device, in the read's words."""
    message = f"scope {scope} selects no device on branch {branch}"
    if at:
        message += " at " + at
    return Finding(REJECTION, RULE_SCOPE_EMPTY, scope, message)


# The devices.


@dataclass
class ReadDevice:
    """One device the Devices query answered: its id, its name, and its platform's pair as
    far as it carries one. `has_platform` is whether it has a platform at all and
    `has_manufacturer` whether that platform has a manufacturer; either name may be empty
    on a node that exists."""

    id: str
    name: str
    node: dict
    has_platform: bool = False
    has_manufacturer: bool = False
    platform: str = ""
    manufacturer: str = ""


def project_device(node: dict) -> ReadDevice:
    d = ReadDevice(id=node.get("id") or "", name=queries.value(node.get("name")), node=node)
    platform = queries.node_of(node.get("platform"))
    if platform is None:
        return d
    d.has_platform = True
    d.platform = queries.value(platform.get("name"))
    manufacturer = queries.node_of(platform.get("manufacturer"))
    if manufacturer is not None:
        d.has_manufacturer = True
        d.manufacturer = queries.value(manufacturer.get("name"))
    return d


def completeness(devices: list[ReadDevice], registry) -> tuple[dict, Findings]:
    """Every device no package can be chosen for, refused in one pass and before any
    artifact is fetched: one with no platform, or a platform with no manufacturer, is
    `platform.missing`, and one whose pair no package names exactly `platform.unmatched`,
    an empty name among them. Returns each matched device's package by its id, and the
    refusals in name order, the order the CTM lists the devices in."""
    packages = {}
    found = Findings()
    for d in sorted(devices, key=lambda d: d.name):
        if not d.has_platform:
            found.reject(
                RULE_PLATFORM_MISSING,
                d.name,
                f"device {d.name} carries no platform; its support package is the one whose matches name its "
                "platform and manufacturer",
            )
        elif not d.has_manufacturer:
            found.reject(
                RULE_PLATFORM_MISSING,
                d.name,
                f"device {d.name} carries platform {quote(d.platform)} with no manufacturer; its support package "
                "is the one whose matches name both",
            )
        else:
            package = registry.match(d.manufacturer, d.platform)
            if package is None:
                found.reject(*registry.unmatched(d.name, d.manufacturer, d.platform))
                continue
            packages[d.id] = package
    return packages, found


def project_port(node: dict) -> dict:
    """One physical port in production naming, tagged `intent` by its absence. The
    management port is the port whose role is management, and a port is enabled unless its
    status is disabled, a null included: both approximations, rows of the fidelity list.
    Its link is set when its cable is judged one."""
    return {
        "name": queries.value(node.get("name")),
        "mgmt_only": queries.value(node.get("role")) == ROLE_MANAGEMENT,
        "enabled": queries.value(node.get("status")) != STATUS_DISABLED,
        "provenance": snapshot.PROVENANCE_INTENT,
    }


# The cables.


@dataclass(frozen=True)
class CableEnd:
    """One end of a cable: `device_name` is set when the device is among those read, and
    `port` when the end is a physical port; `kind` is its __typename."""

    kind: str
    device_id: str = ""
    device_name: str = ""
    port: str = ""

    def name(self) -> str:
        """`<device>:<port>`, a device outside the scope by its id, its name never read."""
        return f"{self.device_name or self.device_id}:{self.port}"


@dataclass
class CableJudgement:
    """One connector reached from a port in the scope, with every end it joins, judged once
    by its id however many of its ends were read. `count` is connected_endpoints.count as
    Infrahub answered it, which the ends rule reads, rather than the ends listed."""

    id: str
    label: str
    kind: str
    count: int
    ends: list[CableEnd] = field(default_factory=list)

    def object(self) -> str:
        """Its label, or its id when it has none, as a connector of another kind always
        has: the read selects a label on a DcimCable alone."""
        return self.label or self.id

    def noun(self) -> str:
        return "cable" if self.kind == CABLE_KIND else "connector"

    def omission(self) -> tuple[str, str] | None:
        """Why the mapping cannot place it, the first of the four reasons that applies, in
        order, the connector's own kind first; None for a cable that is a link."""
        if self.kind != CABLE_KIND:
            return RULE_OMIT_CABLE_KIND, f"a connector that is not a DcimCable ({self.kind})"
        if self.count != 2:
            return RULE_OMIT_CABLE_ENDS, f"other than two ends ({self.count})"
        if len(self.ends) != 2:
            return RULE_OMIT_CABLE_ENDS, f"other than two ends ({len(self.ends)} listed of {self.count})"
        for e in self.ends:
            if e.kind != PHYSICAL_PORT:
                return RULE_OMIT_CABLE_ENDPOINT, f"an end not on a physical port ({e.kind})"
        for e in self.ends:
            if not e.device_name:
                return RULE_OMIT_CABLE_OUTSIDE_SCOPE, f"an end outside the scope ({e.name()})"
        return None

    def known_ends(self) -> list[str]:
        """The ends a finding can name, `<device>:<port>`, sorted: every physical port."""
        return sorted(e.name() for e in self.ends if e.kind == PHYSICAL_PORT)

    def endpoints(self) -> tuple[dict, dict]:
        a, b = self.ends
        return (
            {"device": a.device_name, "interface": a.port},
            {"device": b.device_name, "interface": b.port},
        )


def judge_of(connector: dict, devices: dict[str, str]) -> CableJudgement:
    """A connector as its judgement. An end's device is named when it is among the devices
    read, by id, and only then: a device outside the scope is never read."""
    endpoints = connector.get("connected_endpoints") or {}
    j = CableJudgement(
        id=connector.get("id") or "",
        label=queries.value(connector.get("label")),
        kind=connector.get("__typename") or "",
        count=queries.count(endpoints),
    )
    for node in queries.nodes(endpoints):
        kind = node.get("__typename") or ""
        if kind != PHYSICAL_PORT:
            j.ends.append(CableEnd(kind=kind))
            continue
        device = queries.node_of(node.get("device"))
        device_id = (device or {}).get("id") or ""
        j.ends.append(
            CableEnd(
                kind=kind,
                device_id=device_id,
                device_name=devices.get(device_id, "") if device else "",
                port=queries.value(node.get("name")),
            )
        )
    return j


def canonical_link_id(a: dict, b: dict) -> str:
    """`ctm.CanonicalLinkID`: the two ends' `device:interface`, sorted, joined by `|`."""
    ids = sorted(f"{e['device']}:{e['interface']}" for e in (a, b))
    return f"{ids[0]}|{ids[1]}"


def judge_cables(ctm: dict, cables: dict[str, CableJudgement], found: Findings) -> None:
    """Places every cable reached from a port in the scope. One with exactly two ends, each
    a physical port of a device read, is a link with the canonical id, both ports linked.
    Any other, and any connector that is not a DcimCable, is omitted, never refusing the
    read: an info finding and a fidelity row whose source is the connector's kind. Judged in
    object order, so two reads of one branch report them alike whatever order Infrahub paged
    the ports in."""
    ports = {}
    for d in ctm["devices"]:
        for interface in d["interfaces"]:
            ports[f"{d['name']}:{interface['name']}"] = interface
    for j in sorted(cables.values(), key=lambda j: (j.object(), j.id)):
        omitted = j.omission()
        if omitted is not None:
            rule, reason = omitted
            message = f"{j.noun()} {j.object()} is omitted: {reason}"
            ends = j.known_ends()
            if ends:
                message += "; its ends are " + ", ".join(ends)
            found.add(INFO, rule, j.object(), message)
            ctm["envelope"]["fidelity"].append(
                {"disposition": FIDELITY_OMITTED, "object": j.object(), "source": j.kind, "reason": reason}
            )
            continue
        a, b = j.endpoints()
        link_id = canonical_link_id(a, b)
        ctm["links"].append({"id": link_id, "endpoints": [a, b], "provenance": snapshot.PROVENANCE_INTENT})
        for e in (a, b):
            port = ports.get(f"{e['device']}:{e['interface']}")
            if port is not None:
                port["link"] = link_id


# The artifacts.


@dataclass(frozen=True)
class ListedArtifact:
    """One artifact as the device query listed it. Nothing of Infrahub's addressing
    survives past the read: the storage id fetches the content and is dropped, and the
    artifact's own id is never selected."""

    name: str
    status: str
    content_type: str
    checksum: str
    storage_id: str
    definition_name: str


def list_artifacts(node: dict) -> list[ListedArtifact]:
    """What a device node carries through the ArtifactFields fragment; a kind that does not
    inherit CoreArtifactTarget carries none, which conformance has refused before."""
    out = []
    for a in queries.nodes(node.get("artifacts")):
        definition = queries.node_of(a.get("definition")) or {}
        out.append(
            ListedArtifact(
                name=queries.value(a.get("name")),
                status=queries.value(a.get("status")),
                content_type=queries.value(a.get("content_type")),
                checksum=queries.value(a.get("checksum")),
                storage_id=queries.value(a.get("storage_id")),
                definition_name=queries.value(definition.get("artifact_name")),
            )
        )
    return out


def storage_object_path(storage_id: str) -> str:
    """One artifact's content in Infrahub's object store, by the id the listing gave."""
    return "/api/storage/object/" + escape(storage_id, safe="")


def state_then(state: str, at: str) -> str:
    """`is <State>` now, or `was <State> at <at>` for a pinned read."""
    return f"was {state} at {at}" if at else f"is {state}"


def as_it_stood(at: str) -> str:
    return f" as it stood at {at}" if at else ""


def select_artifact(name: str, node: dict, package, branch: str, at: str, found: Findings) -> ListedArtifact | None:
    """Which of a device's artifacts is its configuration, or why none is (steps 1 to 5),
    from the listing alone. A pinned read is refused in its own words, and never falls back
    to the current artifact: a twin built from today's configuration would be of neither
    moment."""
    want = package.artifact_name
    # Step 1: the definition's artifact_name selects, the name the package declares.
    candidates = [a for a in list_artifacts(node) if a.definition_name == want]
    if not candidates:
        message = f"device {name} has no artifact named {want} on branch {branch}"
        if at:
            message += f" at {at}; the artifact did not exist then"
        found.reject(RULE_ARTIFACT_MISSING, name, message)
        return None
    # Step 2: choosing among several would be Fylgja deciding what production runs.
    if len(candidates) > 1:
        sums = ", ".join(sorted(a.checksum for a in candidates))
        found.reject(
            RULE_ARTIFACT_AMBIGUOUS,
            name,
            f"device {name} has {len(candidates)} artifacts named {want} (checksums {sums}); "
            "fylgja never chooses among them",
        )
        return None
    a = candidates[0]
    # Step 3: any state but Ready, named verbatim.
    if a.status != STATUS_READY:
        found.reject(
            RULE_ARTIFACT_NOT_READY,
            name,
            f"device {name}: artifact {want} {state_then(a.status, at)}, not Ready; fylgja never regenerates "
            "an artifact, because that is a write to Infrahub",
        )
        return None
    # Step 4: the package says which types it accepts.
    if a.content_type not in package.artifact_content_types:
        found.reject(
            RULE_ARTIFACT_CONTENT_TYPE_UNSUPPORTED,
            name,
            f"device {name}: artifact {want} (checksum {a.checksum}) is {a.content_type}; the {package.id} package "
            f"accepts {', '.join(package.artifact_content_types)}",
        )
        return None
    # Step 5: Ready with no object or no checksum is not held as current.
    if not a.storage_id or not a.checksum:
        held = (
            "had no stored content, so it was not held as current"
            if at
            else "has no stored content, so it is not held as current"
        )
        found.reject(
            RULE_ARTIFACT_NOT_READY,
            name,
            f"device {name}: artifact {want} {state_then(a.status, at)} but {held}; fylgja never regenerates "
            "an artifact, because that is a write to Infrahub",
        )
        return None
    return a


def join_and(items: list[str]) -> str:
    """Items as a sentence lists them: `a`, `a and b`, `a, b and c`."""
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def fetch_artifacts(client, devices: list[dict], nodes: list[dict], registry) -> tuple[dict, Findings]:
    """Each device's configuration artifact, by its index among the devices. Steps 1 to 5
    are decided from the listing for every device before any content is fetched, every
    refusal collected; then one object is fetched per surviving device, in name order, and
    steps 7 and 8 verify what came back. A refused credential is no device's fault but the
    read's failure: the other devices are still fetched, so the one error names every
    device refused, grouped by cause. An Infrahub that never answers stops the fetches.
    Findings never carry a byte of content."""
    found = Findings()
    work = sorted(
        ((i, d["name"], d["platform"]["package"], nodes[i]) for i, d in enumerate(devices) if i < len(nodes)),
        key=lambda w: w[1],
    )
    ready = []
    for index, name, package_id, node in work:
        package = registry.lookup_id(package_id)
        if package is None:
            # Completeness has refused the device; no package says which artifact to look for.
            continue
        a = select_artifact(name, node, package, client.branch, client.at, found)
        if a is not None:
            ready.append((index, name, a))

    out = {}
    failed: list[tuple[str, list[str]]] = []

    def fail(detail: str, which: str) -> None:
        for cause, named in failed:
            if cause == detail:
                named.append(which)
                return
        failed.append((detail, [which]))

    for index, name, a in ready:
        which = f"device {name} (artifact {a.definition_name}, checksum {a.checksum})"
        try:
            body, status = client.get_at(storage_object_path(a.storage_id))
        except ClientError as e:
            fail(e.detail, which)
            if e.credential_refused:
                continue
            break
        if status != 200:
            found.reject(
                RULE_ARTIFACT_CONTENT_UNAVAILABLE,
                name,
                f"device {name}: artifact {a.definition_name} (checksum {a.checksum}): Infrahub does not serve its "
                f"content{as_it_stood(client.at)}: {_explain(status, body)}",
            )
            continue
        # Infrahub's checksum is the MD5 of the content (verified): a difference means the
        # bytes served are not the bytes the listing described.
        digest = hashlib.md5(body, usedforsecurity=False).hexdigest()
        if digest != a.checksum:
            found.reject(
                RULE_ARTIFACT_CHECKSUM_MISMATCH,
                name,
                f"device {name}: artifact {a.definition_name} fetched with checksum {digest}, Infrahub reports "
                f"{a.checksum}",
            )
            continue
        try:
            content = body.decode("utf-8")
        except UnicodeDecodeError:
            found.reject(
                RULE_ARTIFACT_CONTENT_TYPE_UNSUPPORTED,
                name,
                f"device {name}: artifact {a.definition_name} (checksum {a.checksum}) is {a.content_type} but its "
                "content is not text",
            )
            continue
        out[index] = {
            "name": a.definition_name,
            "content_type": a.content_type,
            "checksum": a.checksum,
            "content": content,
        }
    if failed:
        raise ReadError(
            "; ".join(
                f"reading the artifact content for {join_and(named)} {client.where()}: {cause}"
                for cause, named in failed
            )
        )
    return out, found


def _explain(status: int, body: bytes) -> str:
    return explain_status(status, body.decode("utf-8", "replace"))


# The read.


def read_devices(client, tag: str) -> list[ReadDevice]:
    """Every DcimDevice carrying the tag, whatever its status."""
    return [project_device(n) for n in paged(client, queries.DEVICES, "DcimDevice", {"tag": tag}, "reading devices")]


def read_ports(client, ids: list[str]) -> list[dict]:
    """The physical ports of the devices read, one Ports request per hundred device ids,
    each paged itself. An InterfaceVirtual is never asked for."""
    out = []
    for start in range(0, len(ids), queries.PAGE_SIZE):
        chunk = ids[start : start + queries.PAGE_SIZE]
        out.extend(paged(client, queries.PORTS, "InterfacePhysical", {"devices": chunk}, "reading ports"))
    return out


def fetch(client, scope: str, schema_hash: str, observed_at: str, registry) -> tuple[dict | None, Findings]:
    """The scope of the client's branch as a CTM, normalised, with the read's findings; None
    when the read refused (`intent.Client.Fetch`). The envelope names the branch, the `at`
    verbatim when the operator gave one, the schema hash conformance read, the scope, the
    mapping and the fidelity rows. Raises ReadError when Infrahub cannot be read."""
    ctm = {
        "ctm_version": snapshot.CTM_VERSION,
        "envelope": {
            "branch": client.branch,
            "at": client.at,
            "observed_at": observed_at,
            "schema_hash": schema_hash,
            "scope": scope,
            "mapping": {"reader": mapping.READER, "model": mapping.MODEL, "version": mapping.VERSION},
            "fidelity": read_fidelity(),
        },
        "devices": [],
        "links": [],
    }
    devices = read_devices(client, scope_tag(scope))
    # No device, no ports to ask for: a Ports request with no ids would filter by none.
    if not devices:
        return None, Findings([scope_empty(scope, client.branch, client.at)])
    names = {d.id: d.name for d in devices}
    ports = read_ports(client, [d.id for d in devices])

    packages, found = completeness(devices, registry)

    by_id = {}
    nodes = []
    for d in devices:
        package = packages.get(d.id)
        by_id[d.id] = len(ctm["devices"])
        ctm["devices"].append(
            {
                "name": d.name,
                "platform": {"package": package.id if package else ""},
                "interfaces": [],
                "provenance": snapshot.PROVENANCE_INTENT,
            }
        )
        nodes.append(d.node)

    cables: dict[str, CableJudgement] = {}
    for p in ports:
        owner = queries.node_of(p.get("device"))
        if owner is None or owner.get("id") not in by_id:
            continue
        ctm["devices"][by_id[owner["id"]]]["interfaces"].append(project_port(p))
        connector = queries.node_of(p.get("connector"))
        if connector is not None and connector.get("id") and connector["id"] not in cables:
            cables[connector["id"]] = judge_of(connector, names)
    omitted = Findings()
    judge_cables(ctm, cables, omitted)
    found.extend(omitted)

    # Before normalising, which reorders the devices: the artifacts are matched to the
    # nodes they were listed on by position.
    artifacts, artifact_findings = fetch_artifacts(client, ctm["devices"], nodes, registry)
    found.extend(artifact_findings)
    # A device without a package refuses the read: no CTM carries one.
    if len(packages) < len(devices):
        return None, found
    for i, d in enumerate(ctm["devices"]):
        if i in artifacts:
            d["artifact"] = artifacts[i]
    if not ctm["envelope"]["at"]:
        del ctm["envelope"]["at"]
    snapshot.normalize(ctm)
    return ctm, found


def dedupe(add: Findings, have: Findings) -> Findings:
    """`add` without what `have` already named: the same severity, rule and object, or an
    `artifact.missing` about a device the read refused under an artifact rule, the read's
    account kept as the one with Infrahub in hand (`stage.dedupe`)."""
    if not have:
        return add
    seen = {(f.severity, f.rule, f.object) for f in have}
    refused = {f.object for f in have if f.rule.startswith(ARTIFACT_RULES)}
    out = Findings()
    for f in add:
        if (f.severity, f.rule, f.object) in seen:
            continue
        if f.rule == RULE_ARTIFACT_MISSING and f.object in refused:
            continue
        out.append(f)
    return out


def read(client, scope: str, registry, observed_at: str) -> tuple[dict | None, Findings]:
    """A scope of the client's branch into a validated CTM (`stage.Read`): conformance,
    the fetch, then the CTM's intrinsic rules, every finding in one pass; None when any
    refused. Raises ReadError when the scope is not `tag:<name>` or Infrahub cannot be
    read. The `at`'s precision is the caller's to hold first (`at_precision`)."""
    if not validate.valid_scope(scope):
        raise ReadError(f"the read names scope {quote(scope)}, which is not tag:<name>")
    try:
        conformance, found = check_conformance(client)
    except ClientError as e:
        raise ReadError(str(e), e.branch_missing) from None
    if found.rejected:
        return None, found
    ctm, fetched = fetch(client, scope, conformance.schema_hash, observed_at, registry)
    found.extend(fetched)
    if ctm is None:
        return None, found
    found.extend(dedupe(validate.intrinsic(ctm), found))
    if found.rejected:
        return None, found
    return ctm, found


def at_precision(at: str) -> Finding | None:
    """The refusal of an `at` finer than Infrahub honours, before any query (`intent.at.precision`)."""
    message = check_at_precision(at)
    return Finding(REJECTION, RULE_AT_PRECISION, at, message) if message else None


def read_snapshot(
    client, scope: str, registry, probes=None, observed_at: str | None = None, out=None
) -> tuple[dict | None, Findings]:
    """The read taken as a snapshot `2` with the request's one probe list, the probes
    already held to their rules (`probes.declared`), and written to `out` when given: the
    file the Go reader wrote, byte for byte. None and the findings when the read refused."""
    refused = at_precision(client.at)
    if refused is not None:
        return None, Findings([refused])
    ctm, found = read(client, scope, registry, observed_at or observed_now())
    if ctm is None:
        return None, found
    taken = snapshot.take(ctm, probes or [])
    if out is not None:
        snapshot.write(out, taken)
    return taken, found


# The summary.


@dataclass(frozen=True)
class Counts:
    """The size of what was read, for the success line: a clean result as evidence rather
    than an absence of complaint. `artifacts` counts the devices that came back with their
    configuration; `cables_omitted` the connectors the read could not place, each a fidelity
    row."""

    devices: int = 0
    interfaces: int = 0
    links: int = 0
    artifacts: int = 0
    cables_omitted: int = 0


def summarize(ctm: dict | None) -> Counts:
    if ctm is None:
        return Counts()
    # Every omitted row but the ones each read writes is a connector the read omitted.
    fixed = read_fidelity()
    keys = ("disposition", "object", "source", "reason")
    omitted = sum(
        1
        for r in ctm["envelope"].get("fidelity") or []
        if r.get("disposition") == FIDELITY_OMITTED and {k: r.get(k, "") for k in keys} not in fixed
    )
    return Counts(
        devices=len(ctm["devices"]),
        interfaces=sum(len(d.get("interfaces") or []) for d in ctm["devices"]),
        links=len(ctm["links"]),
        artifacts=sum(1 for d in ctm["devices"] if d.get("artifact") is not None),
        cables_omitted=omitted,
    )


def devices_by_package(ctm: dict | None) -> list[tuple[str, int]]:
    """The read's devices counted per support package, in package id order."""
    if ctm is None:
        return []
    counts: dict[str, int] = {}
    for d in ctm["devices"]:
        package = (d.get("platform") or {}).get("package", "")
        counts[package] = counts.get(package, 0) + 1
    return sorted(counts.items())
