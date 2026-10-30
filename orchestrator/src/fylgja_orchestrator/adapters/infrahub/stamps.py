"""When a scope's intent and its artifacts were last written, as one read at the client's
(branch, at) returns them (014; D-046; 017 research R-10), ported from
`internal/intent/stamps.go`.

It reads stamps and never a value of intent but the names that key them: the platform's and
its manufacturer's names, which pick each device's package, and the ids an intent event
names a device by (D-048). A node's stamp is its `Edged*` wrapper's
`node_metadata.updated_at`, the latest write among its current attributes and relationship
edges (017 research §1.7), or its `created_at` when Infrahub's own account wrote it last
(D-058): the account that created the internal groups of the queries the scope's artifacts
render through, read at the same (branch, at) (D-059, D-060). A generation's query-group
join is that account's write, and never intent. Every stamp is kept as the string Infrahub
returned; each comparison parses it.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub.packages import Match
from fylgja_orchestrator.adapters.infrahub.read import ReadError, paged
from fylgja_orchestrator.adapters.infrahub.read import query as ask
from fylgja_orchestrator.documents.findings import quote

_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")


class StampError(ValueError):
    """A stamp Infrahub returned that is not an RFC 3339 time."""


def parse_stamp(s: str) -> datetime:
    """A stamp Infrahub returned: RFC 3339, six fractional digits as Infrahub writes them,
    the offset +00:00 or Z. Nothing else Python's parser would take is a stamp."""
    if not isinstance(s, str) or _RFC3339.fullmatch(s) is None:
        raise StampError(f"the stamp {quote(str(s))} Infrahub returned is not an RFC 3339 time")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise StampError(f"the stamp {quote(s)} Infrahub returned is not an RFC 3339 time") from None


@dataclass(frozen=True)
class DeviceStamps:
    """One device's side of the staleness rule (D-046). `match` is its pair as the read
    reads it, "" where it has none; `ids` its own id, its platform's, its manufacturer's,
    each of its interfaces' and each of its cables', as read, by which an intent event names
    it; `intent` the latest stamp of its own intent (FR-023): its node, its platform, its
    manufacturer, each of its interfaces of both kinds and each cable one of its physical
    ports is an end of; `artifacts` each of its artifacts by name to its
    `checksum.updated_at`, which moves only when Infrahub stores bytes that differ, "" when
    Infrahub returned none."""

    match: Match
    ids: list[str]
    intent: str
    artifacts: dict[str, str]


@dataclass(frozen=True)
class Stamps:
    """`latest` is the latest stamp the read returned, every device's, interface's,
    platform's, manufacturer's, cable's and artifact checksum's, as D-058 counts it, "" when
    the scope holds nothing stamped; the head's `at` is one microsecond after the later of
    it and the branch's latest intent event (D-048). `devices` holds each device's own by
    its name."""

    latest: str
    devices: dict[str, DeviceStamps]


class _Fold:
    """The latest of the stamps it is shown, as the string Infrahub returned; two naming
    one instant keep the first."""

    def __init__(self):
        self.stamp = ""
        self.at = None

    def take(self, stamp: str, at: datetime) -> None:
        if not self.stamp or at > self.at:
            self.stamp, self.at = stamp, at


@dataclass
class _DeviceFold:
    manufacturer: str = ""
    platform: str = ""
    ids: list[str] = field(default_factory=list)
    intent: _Fold = field(default_factory=_Fold)
    artifacts: dict[str, _Fold] = field(default_factory=dict)


def _meta(edge) -> dict:
    meta = (edge or {}).get("node_metadata") if isinstance(edge, dict) else None
    return meta if isinstance(meta, dict) else {}


def stamp_of(meta: dict, own: set[str]) -> str:
    """A node's stamp as D-058 counts it: its updated_at, or its created_at when the account
    that last wrote it is Infrahub's own. That account writes a node only to add it to a
    query's group after a generation read it, so the node's creation is no later than that
    generation. An intent write by that account, a generator's, is still seen by the events."""
    by = meta.get("updated_by") if isinstance(meta.get("updated_by"), dict) else {}
    if by.get("id") and by["id"] in own:
        return meta.get("created_at") or ""
    return meta.get("updated_at") or ""


class _Reader:
    """One read's stamps, kept with the folds each belongs to in the order read, and folded
    once Infrahub's own account is known."""

    def __init__(self):
        self.all = _Fold()
        self.devices: dict[str, _DeviceFold] = {}
        self.by_id: dict[str, _DeviceFold] = {}
        self.pending: list[tuple[dict, tuple[_Fold, ...]]] = []
        self.queries: list[str] = []
        self.error: StampError | None = None

    def node(self, meta: dict, *into: _Fold) -> None:
        self.pending.append((meta, into))

    def fold(self, own: set[str]) -> None:
        for meta, into in self.pending:
            self.see(stamp_of(meta, own), *into)
        self.pending = []

    def see(self, stamp: str, *into: _Fold) -> None:
        """One stamp folded; "" is a null, a node not set, and is skipped. The first that
        does not parse is kept and raised after the read."""
        if not stamp:
            return
        try:
            at = parse_stamp(stamp)
        except StampError as e:
            self.error = self.error or e
            return
        self.all.take(stamp, at)
        for f in into:
            f.take(stamp, at)

    def device(self, edge: dict) -> str:
        """One device's edge folded; its id."""
        n = edge.get("node") or {}
        name = queries.value(n.get("name"))
        d = self.devices.setdefault(name, _DeviceFold())
        device_id = n.get("id") or ""
        self.by_id[device_id] = d
        d.ids.append(device_id)
        self.node(_meta(edge), d.intent)

        # The platform and its manufacturer reach every device on them: their names pick
        # the device's package, and the template renders them into its artifact.
        platform = n.get("platform") if isinstance(n.get("platform"), dict) else {}
        self.node(_meta(platform), d.intent)
        p = queries.node_of(platform)
        if p is not None:
            d.platform = queries.value(p.get("name"))
            d.ids.append(p.get("id") or "")
            manufacturer = p.get("manufacturer") if isinstance(p.get("manufacturer"), dict) else {}
            self.node(_meta(manufacturer), d.intent)
            m = queries.node_of(manufacturer)
            if m is not None:
                d.manufacturer = queries.value(m.get("name"))
                d.ids.append(m.get("id") or "")

        for e in queries.edges(n.get("interfaces")):
            self.node(_meta(e), d.intent)
            interface = queries.node_of(e)
            if interface is not None and interface.get("id"):
                d.ids.append(interface["id"])

        # A checksum's stamp is the branch's latest and the artifact's, never the device's
        # intent, and names no account. Its definition's query is where Infrahub's own
        # account is read.
        for a in queries.nodes(n.get("artifacts")):
            name_ = queries.value(a.get("name"))
            fold = d.artifacts.setdefault(name_, _Fold())
            checksum = a.get("checksum") if isinstance(a.get("checksum"), dict) else {}
            updated = checksum.get("updated_at")
            self.node({"updated_at": updated if isinstance(updated, str) else ""}, fold)
            definition = queries.node_of(a.get("definition")) or {}
            transformation = queries.node_of(definition.get("transformation")) or {}
            query = queries.node_of(transformation.get("query")) or {}
            query_id = query.get("id") or ""
            if query_id and query_id not in self.queries:
                self.queries.append(query_id)
        return device_id

    def port(self, p: dict) -> None:
        """One cabled port's cable folded into its device's intent: a cable's stamp is the
        intent of the device of each of its ends in the scope, and of no third. A cable
        whose two ends are on one device is that device's once."""
        owner = queries.node_of(p.get("device"))
        if owner is None:
            return
        d = self.by_id.get(owner.get("id") or "")
        if d is None:
            return
        connector = p.get("connector") if isinstance(p.get("connector"), dict) else {}
        cable = queries.node_of(connector)
        if cable is None or not cable.get("id"):
            return  # uncabled: the query asks for none
        self.node(_meta(connector), d.intent)
        if cable["id"] not in d.ids:
            d.ids.append(cable["id"])


def own_accounts(client, query_ids: list[str]) -> set[str]:
    """Infrahub's own account in D-058's sense, at the client's (branch, at): the creator of
    each internal group of the queries given (D-059, D-060). No query, or no group, is no
    account: nothing has been generated through the query there."""
    if not query_ids:
        return set()
    own = set()
    offset = 0
    while True:
        variables = {"queries": query_ids, "limit": queries.PAGE_SIZE, "offset": offset}
        page = ask(client, queries.QUERY_GROUPS, variables, "reading stamps").get("CoreGraphQLQueryGroup")
        for edge in queries.edges(page):
            created_by = _meta(edge).get("created_by")
            if isinstance(created_by, dict) and created_by.get("id"):
                own.add(created_by["id"])
        if offset + queries.PAGE_SIZE >= queries.count(page):
            return own
        offset += queries.PAGE_SIZE


def read_stamps(client, tag: str) -> Stamps:
    """The stamps of the scope's devices at the client's `at`, sent on every page iff set:
    the DcimDevices carrying the tag, then their cabled physical ports by the devices' ids,
    each with its cable, as the read reads them, then the internal groups of the queries
    their artifacts render through. Only then is each stamp folded. Each request is paged
    by 100. Raises ReadError when Infrahub cannot be read or answers a stamp that is no
    time."""
    r = _Reader()
    ids = []
    offset = 0
    while True:
        variables = {"tag": tag, "limit": queries.PAGE_SIZE, "offset": offset}
        page = ask(client, queries.INTENT_STAMPS, variables, "reading stamps").get("DcimDevice")
        for edge in queries.edges(page):
            ids.append(r.device(edge))
        if offset + queries.PAGE_SIZE >= queries.count(page):
            break
        offset += queries.PAGE_SIZE
    # No device, no ports to ask for: a request with no ids would filter by none.
    for start in range(0, len(ids), queries.PAGE_SIZE):
        chunk = ids[start : start + queries.PAGE_SIZE]
        for p in paged(client, queries.PORT_STAMPS, "InterfacePhysical", {"devices": chunk}, "reading stamps"):
            r.port(p)
    r.fold(own_accounts(client, r.queries))
    if r.error is not None:
        raise ReadError(f"reading stamps {client.where()}: {r.error}")
    return Stamps(
        latest=r.all.stamp,
        devices={
            name: DeviceStamps(
                match=Match(d.manufacturer, d.platform),
                ids=list(d.ids),
                intent=d.intent.stamp,
                artifacts={a: fold.stamp for a, fold in d.artifacts.items()},
            )
            for name, d in r.devices.items()
        },
    )
