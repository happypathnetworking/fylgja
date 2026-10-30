"""When a branch's intent last changed, removals included, which no stamp records (D-048),
ported from `internal/intent/events.go`: the branch's event log, read through
InfrahubEvent on the default branch's endpoint (it answers alike on a branch's), pinned to
nothing, newest first.

A cable re-ended, a port deleted and a relationship unset move no stamp the stamps read
selects, and a cable's delete stamps its two end ports; the event is how the head and the
staleness rule see the rest. An event is intent's when it is a node's own write (a
NodeMutatedEvent) whose primary node is of a kind the stamps read on the branch (each
implementer of the library's three generics, found through the branch schema's used_by, so
an implementer of the operator's own counts, and the platform and the manufacturer), and it
created or deleted that node, or changed an attribute or a relationship that is not
Infrahub's own churn (a query group's membership, an artifact).
"""

from dataclasses import dataclass, field

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub.client import DEFAULT_BRANCH, ClientError
from fylgja_orchestrator.adapters.infrahub.read import ReadError
from fylgja_orchestrator.adapters.infrahub.read import query as ask
from fylgja_orchestrator.adapters.infrahub.schema import schema_info
from fylgja_orchestrator.adapters.infrahub.stamps import StampError, parse_stamp

EVENT_NODE_CREATED = "infrahub.node.created"
EVENT_NODE_DELETED = "infrahub.node.deleted"
NODE_MUTATED = "NodeMutatedEvent"

INTENT_GENERICS = ("DcimGenericDevice", "DcimInterface", "DcimConnector")
"""The library's generics whose implementers' writes are intent's: the kinds the stamps read."""

INTENT_NODES = ("DcimPlatform", "OrganizationManufacturer")
"""The concrete kinds the stamps read beside the generics' implementers."""

CHURN_RELATIONSHIPS = frozenset(
    {"member_of_groups", "subscriber_of_groups", "artifacts", "profiles", "object_template"}
)
"""Infrahub's own relationships on every node, whose writes alone are churn and never
intent (D-048): a query group's membership is rewritten seconds after each generation; an
artifact's creation adds one on its device."""


@dataclass(frozen=True)
class Event:
    """One write the branch's event log records that is intent's, every field as Infrahub
    returned it: its name (`infrahub.node.deleted`), when it occurred, its primary node's
    concrete kind (read only to be mapped and named, never queried), and the ids it names,
    its primary node's then each peer of its relationships, a removed one included."""

    name: str
    occurred_at: str
    kind: str
    nodes: list[str] = field(default_factory=list)

    def names(self, ids) -> bool:
        """Whether the event names any of ids, as its primary node or a peer."""
        return any(n in ids for n in self.nodes)


def changes_intent(node: dict) -> bool:
    """Whether a node's write is intent's: its creation or deletion, or an update naming
    any attribute, or any relationship but Infrahub's churn."""
    if node.get("event") in (EVENT_NODE_CREATED, EVENT_NODE_DELETED):
        return True
    if node.get("attributes"):
        return True
    return any((r or {}).get("name") not in CHURN_RELATIONSHIPS for r in node.get("relationships") or [])


def intent_kinds(reader, branch: str) -> set[str]:
    """Every concrete kind on the branch the stamps read: each implementer of the generics,
    from the branch's schema endpoint as conformance reads it, and the two nodes."""
    try:
        info = schema_info(reader.on_branch(branch))
    except ClientError as e:
        raise ReadError(str(e), e.branch_missing) from None
    kinds = set(INTENT_NODES)
    for generic in INTENT_GENERICS:
        kinds.update(info.used_by.get(generic) or [])
    return kinds


def intent_events(reader, branch: str, since: str, after: str = "") -> list[Event]:
    """The branch's events that are intent's and occurred after `after`, newest first,
    bounded to the branch and to `since` (its branched_from, verbatim, so an earlier branch
    of the same name is not read). Paging stops at the first page reaching an event no later
    than `after`; an empty `after` reads every page since `since`. An event with no primary
    node is skipped. The schema is read once, and only when an event is to be mapped.

    An event Infrahub records while the pages are read shifts the later pages by one, so one
    can come back twice and none is missed; a caller takes the latest or asks whether one
    names a device, which a repeat does not change. `reader` is a DefaultClient."""
    what = f"reading the event log of branch {branch}"
    floor = None
    if after:
        try:
            floor = parse_stamp(after)
        except StampError as e:
            raise ReadError(f"{what} {DEFAULT_BRANCH}: {e}") from None
    kinds = None
    out = []
    offset = 0
    while True:
        variables = {"branch": branch, "since": since, "limit": queries.EVENT_PAGE_SIZE, "offset": offset}
        page = ask(reader, queries.INTENT_EVENTS, variables, what).get("InfrahubEvent")
        nodes = [edge.get("node") for edge in queries.edges(page)]
        done = not nodes or offset + len(nodes) >= queries.count(page)
        for n in nodes:
            if not isinstance(n, dict):
                continue
            try:
                at = parse_stamp(n.get("occurred_at") or "")
            except StampError as e:
                raise ReadError(f"{what} {DEFAULT_BRANCH}: {e}") from None
            if floor is not None and at <= floor:
                done = True
                break
            if n.get("__typename") != NODE_MUTATED:
                continue  # an artifact's, a group's or a branch's own event: no node's write
            primary = n.get("primary_node") if isinstance(n.get("primary_node"), dict) else {}
            if not primary.get("id"):
                continue  # no primary node: a schema's update names none
            if kinds is None:
                kinds = intent_kinds(reader, branch)
            if primary.get("kind") not in kinds or not changes_intent(n):
                continue
            ids = [primary["id"]]
            for r in n.get("relationships") or []:
                peer = (r or {}).get("peer")
                ids.append((peer.get("id") or "") if isinstance(peer, dict) else "")
            out.append(Event(n.get("event") or "", n.get("occurred_at") or "", primary.get("kind") or "", ids))
        if done:
            return out
        offset += queries.EVENT_PAGE_SIZE
