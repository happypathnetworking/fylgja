"""The event log against `internal/intent`'s events_test.go: a branch's InfrahubEvent log,
newest first, read on the unnamed `/graphql`, and the branch's schema, whose used_by maps
each event's kind: only a node's own write of a kind the stamps read is intent, a creation
or a deletion whatever it names, an update by any attribute or any relationship but
Infrahub's churn; an implementer of the operator's own counts; the pages stop at the bound;
a quiet log reads no schema, and a stamp that is no time is refused without the
credential. The fake (FakeEvents) is the Go test's fakeEvents on tier 1's FakeInfrahub."""

import pytest

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub.client import DefaultClient
from fylgja_orchestrator.adapters.infrahub.events import Event, intent_events
from fylgja_orchestrator.adapters.infrahub.read import ReadError

from .conftest import ADDRESS, TOKEN

# Go's StageKind, the stage kind of Fylgja's own.
STAGE_KIND = "FylgjaStage"

EVENT_BRANCHED = "2026-10-17T13:54:10.452384Z"
EVENT_DELETED = "2026-10-17T13:55:09.031152+00:00"


class FakeEvents:
    """Infrahub's event log for one branch, newest first, and the branch's schema, the
    library's kinds implementing its generics; it records what it was asked. `extra` are
    implementers of the operator's own beside the library's, kind to generic."""

    def __init__(self, infrahub, events, extra=None, branch="change-1"):
        self.infrahub = infrahub
        self.events = list(events)
        self.extra = dict(extra or {})
        self.pages: list[dict] = []  # the variables of each page read
        infrahub.branches.add(branch)
        infrahub.schema = self._schema()
        infrahub.default_operations["IntentEvents"] = self._intent_events

    def schemas(self) -> list[str]:
        """The branch of each schema read."""
        return [r["query"].get("branch", [""])[0] for r in self.infrahub.requests if r["path"] == "/api/schema"]

    def _schema(self) -> dict:
        def generic(kind, *used_by):
            return {"kind": kind, "used_by": list(used_by) + [k for k, g in self.extra.items() if g == kind]}

        return {
            "main": "908871c3",
            "generics": [
                generic("DcimGenericDevice", "DcimDevice"),
                generic("DcimInterface", "InterfacePhysical", "InterfaceVirtual"),
                generic("DcimEndpoint", "InterfacePhysical"),
                generic("DcimConnector", "DcimCable"),
                generic("CoreGroup", "CoreGraphQLQueryGroup"),
                generic("CoreArtifactTarget", "DcimDevice"),
            ],
            "nodes": [
                {"kind": "DcimDevice"},
                {"kind": "DcimPlatform"},
                {"kind": "OrganizationManufacturer"},
                {"kind": "BuiltinTag"},
                {"kind": STAGE_KIND},
            ],
        }

    def _intent_events(self, variables, query_text, branch, params):
        self.pages.append(variables)
        limit, offset = variables.get("limit", 0), variables.get("offset", 0)
        edges = [{"node": e} for e in self.events[offset : offset + limit]]
        return {"data": {"InfrahubEvent": {"count": len(self.events), "edges": edges}}}

    def reader(self) -> DefaultClient:
        return DefaultClient(ADDRESS, TOKEN, requester=self.infrahub)


def rel(name: str, peer: str) -> tuple[str, str]:
    """One relationship an event says changed: its name and its peer's id."""
    return name, peer


def mutated(name: str, at: str, kind: str, id_: str, attrs=None, *rels) -> dict:
    """A NodeMutatedEvent of the log: a node's own write, with the attributes and
    relationships it changed."""
    return {
        "__typename": "NodeMutatedEvent",
        "event": name,
        "occurred_at": at,
        "primary_node": {"id": id_, "kind": kind},
        "attributes": [{"name": a} for a in attrs or []],
        "relationships": [{"name": n, "peer": {"id": p}} for n, p in rels],
    }


def other(typename: str, name: str, at: str, kind: str, id_: str) -> dict:
    """An event of another type, which records no node's write: an artifact's, a group's,
    a branch's (kind "" names no node)."""
    n = {"__typename": typename, "event": name, "occurred_at": at, "primary_node": None}
    if kind:
        n["primary_node"] = {"id": id_, "kind": kind}
    return n


def test_intent_events_maps_kinds(infrahub):
    """The log of a branch over the library's kinds, newest first (research §1.8, §8.18):
    the regenerate's churn, a cable re-ended with its child event on the former port, a tag
    added and removed, the generation's churn, the seed. Only a node's own write of a kind
    the stamps read is intent, at any level: the device, an interface of either kind, a
    cable, a platform and a manufacturer. Of an update, one changing any attribute or any
    relationship but Infrahub's churn: the query groups' memberships Infrahub rewrites on
    every node after each generation, a device's artifacts, a profile. A tag's own write, an
    artifact's, a group's, the stage kind's and an event with no primary node are not
    intent. A creation or a deletion is, whatever it names: one naming no attribute and only
    a query group's membership among them. Each names its primary node and every peer."""
    updated, created, deleted = "infrahub.node.updated", "infrahub.node.created", "infrahub.node.deleted"
    f = FakeEvents(
        infrahub,
        [
            mutated(updated, "2026-10-17T13:55:32.691250+00:00", "DcimDevice", "dev-n1", None,
                    rel("member_of_groups", "g-1")),
            mutated(updated, "2026-10-17T13:55:32.500000+00:00", "InterfaceVirtual", "if-n1-lo0", None,
                    rel("member_of_groups", "g-1"), rel("subscriber_of_groups", "g-2")),
            other("ArtifactEvent", "infrahub.artifact.updated", "2026-10-17T13:55:29.770104+00:00",
                  "CoreArtifact", "a-1"),
            mutated(updated, "2026-10-17T13:55:29.617911+00:00", "CoreArtifact", "a-1", ["storage_id", "checksum"]),
            mutated(updated, "2026-10-17T13:55:21.000000+00:00", "DcimDevice", "dev-n2", None,
                    rel("profiles", "prof-1"), rel("object_template", "tpl-1")),
            mutated(updated, "2026-10-17T13:55:18.000000+00:00", STAGE_KIND, "st-1", ["label"]),
            mutated(updated, "2026-10-17T13:55:17.000000+00:00", "BuiltinTag", "tag-1", ["description"]),
            # infrahub.schema.updated names no primary node, as a standard event and as a
            # mutated one alike.
            other("StandardEvent", "infrahub.schema.updated", "2026-10-17T13:55:16.000000+00:00", "", ""),
            {"__typename": "NodeMutatedEvent", "event": "infrahub.schema.updated",
             "occurred_at": "2026-10-17T13:55:15.000000+00:00", "primary_node": None, "attributes": [],
             "relationships": [{"name": "nodes", "peer": {"id": "x"}}]},
            # A tag removed, then added: the device's tags edge, both ways.
            mutated(updated, "2026-10-17T13:55:12.000000+00:00", "DcimDevice", "dev-n3", None, rel("tags", "tag-1")),
            mutated(updated, "2026-10-17T13:55:11.000000+00:00", "DcimDevice", "dev-n3", None, rel("tags", "tag-1")),
            other("GroupEvent", "infrahub.group.member_removed", "2026-10-17T13:55:09.051000+00:00",
                  "CoreGraphQLQueryGroup", "g-1"),
            mutated(updated, "2026-10-17T13:55:09.049000+00:00", "CoreGraphQLQueryGroup", "g-1", None,
                    rel("members", "cable-12")),
            # The cable re-ended to n1's end alone, and the former port's own event.
            mutated(updated, "2026-10-17T13:55:09.034000+00:00", "InterfacePhysical", "if-n2-e1", None,
                    rel("connector", "cable-12")),
            mutated(updated, "2026-10-17T13:55:09.031152+00:00", "DcimCable", "cable-12", None,
                    rel("connected_endpoints", "if-n2-e1")),
            mutated(updated, "2026-10-17T13:54:30.000000+00:00", "OrganizationManufacturer", "mf-1", ["description"]),
            mutated(updated, "2026-10-17T13:54:29.000000+00:00", "DcimPlatform", "pf-1", ["description"]),
            mutated(updated, "2026-10-17T13:54:27.731070+00:00", "DcimDevice", "dev-n1", None,
                    rel("member_of_groups", "g-1")),
            mutated(updated, "2026-10-17T13:54:22.418356+00:00", "DcimDevice", "dev-n1", None,
                    rel("artifacts", "a-1")),
            mutated(updated, "2026-10-17T13:54:20.000000+00:00", "DcimDevice", "dev-n2", ["serial"]),
            # A port created, then deleted, each event naming no attribute and only a query
            # group's membership: a creation or a deletion is intent by its event alone,
            # whatever it names (contracts/mapping.md §6).
            mutated(deleted, "2026-10-17T13:54:19.000000+00:00", "InterfacePhysical", "if-n3-e2", None,
                    rel("member_of_groups", "g-1")),
            mutated(created, "2026-10-17T13:54:18.000000+00:00", "InterfacePhysical", "if-n3-e2", None,
                    rel("member_of_groups", "g-1")),
            mutated(created, "2026-10-17T13:54:16.683012+00:00", "DcimCable", "cable-12",
                    ["human_friendly_id", "display_label"],
                    rel("connected_endpoints", "if-n1-e1"), rel("connected_endpoints", "if-n2-e1")),
            mutated(created, "2026-10-17T13:54:15.360731+00:00", "InterfaceVirtual", "if-n1-lo0",
                    ["name"], rel("device", "dev-n1")),
            other("BranchCreatedEvent", "infrahub.branch.created", "2026-10-17T13:54:10.452400+00:00", "", ""),
        ],
    )
    got = intent_events(f.reader(), "change-1", EVENT_BRANCHED, "")
    want = [
        Event(updated, "2026-10-17T13:55:12.000000+00:00", "DcimDevice", ["dev-n3", "tag-1"]),
        Event(updated, "2026-10-17T13:55:11.000000+00:00", "DcimDevice", ["dev-n3", "tag-1"]),
        Event(updated, "2026-10-17T13:55:09.034000+00:00", "InterfacePhysical", ["if-n2-e1", "cable-12"]),
        Event(updated, EVENT_DELETED, "DcimCable", ["cable-12", "if-n2-e1"]),
        Event(updated, "2026-10-17T13:54:30.000000+00:00", "OrganizationManufacturer", ["mf-1"]),
        Event(updated, "2026-10-17T13:54:29.000000+00:00", "DcimPlatform", ["pf-1"]),
        Event(updated, "2026-10-17T13:54:20.000000+00:00", "DcimDevice", ["dev-n2"]),
        Event(deleted, "2026-10-17T13:54:19.000000+00:00", "InterfacePhysical", ["if-n3-e2", "g-1"]),
        Event(created, "2026-10-17T13:54:18.000000+00:00", "InterfacePhysical", ["if-n3-e2", "g-1"]),
        Event(created, "2026-10-17T13:54:16.683012+00:00", "DcimCable", ["cable-12", "if-n1-e1", "if-n2-e1"]),
        Event(created, "2026-10-17T13:54:15.360731+00:00", "InterfaceVirtual", ["if-n1-lo0", "dev-n1"]),
    ]
    assert got == want
    # The re-ended cable's event names its former port, and so counts for that port's
    # device, n2, and the port's own event does too; neither names n3.
    n2 = ["dev-n2", "if-n2-e1"]
    assert got[3].names(n2) and got[2].names(n2) and not got[3].names(["dev-n3", "if-n3-e1"]), (
        f"the re-ending names {got[3].nodes} and {got[2].nodes}"
    )
    assert f.schemas() == ["change-1"], "want the branch's schema, read once"
    assert len(f.pages) == 1
    page = f.pages[0]
    assert page["branch"] == "change-1" and page["since"] == EVENT_BRANCHED
    assert page["limit"] == queries.EVENT_PAGE_SIZE and page["offset"] == 0


def test_intent_events_map_an_implementer_of_the_operators_own(infrahub):
    """An implementer of the operator's own, found through the branch schema's used_by, is
    intent's as the library's are; a kind that implements none is not."""
    f = FakeEvents(
        infrahub,
        [
            mutated("infrahub.node.updated", "2026-10-17T13:55:02.000000+00:00", "AcmeWidget", "w-1", ["name"]),
            mutated("infrahub.node.updated", "2026-10-17T13:55:01.000000+00:00", "InterfaceLag", "lag-1", ["name"]),
        ],
        extra={"InterfaceLag": "DcimInterface"},
    )
    got = intent_events(f.reader(), "change-1", EVENT_BRANCHED, "")
    assert [e.kind for e in got] == ["InterfaceLag"], "want InterfaceLag's alone"


def test_intent_events_pages_to_the_bound(infrahub):
    """The pages stop at the first event no later than after, which none of the events
    returned is; an empty after reads every page, fifty at a time."""
    # Newest first: 13:55:59.000119 down to 13:55:59.000000.
    events = [
        mutated("infrahub.node.updated", f"2026-10-17T13:55:59.{119 - i:06d}+00:00", "InterfacePhysical",
                f"if-{119 - i}", ["status"])
        for i in range(120)
    ]
    f = FakeEvents(infrahub, events)
    r = f.reader()
    got = intent_events(r, "change-1", EVENT_BRANCHED, "")
    assert len(got) == 120 and len(f.pages) == 3, "every page"
    f.pages.clear()
    got = intent_events(r, "change-1", EVENT_BRANCHED, "2026-10-17T13:55:59.000060+00:00")
    assert len(got) == 59
    assert got[0].occurred_at == "2026-10-17T13:55:59.000119+00:00"
    assert got[58].occurred_at == "2026-10-17T13:55:59.000061+00:00"
    assert len(f.pages) == 2, "want the two pages that reach the bound"


def test_intent_events_quiet_and_refused(infrahub):
    """A log with nothing after the bound reads one page and no schema; a stamp that is not
    a time is refused, and nothing the reader returns carries the credential."""
    f = FakeEvents(
        infrahub,
        [mutated("infrahub.node.updated", "2026-10-17T13:54:00.000000+00:00", "InterfacePhysical", "if-1", ["status"])],
    )
    got = intent_events(f.reader(), "change-1", EVENT_BRANCHED, EVENT_DELETED)
    assert got == [] and len(f.pages) == 1 and f.schemas() == [], "quiet"
    with pytest.raises(ReadError):
        intent_events(f.reader(), "change-1", EVENT_BRANCHED, "not a time")

    f = FakeEvents(
        infrahub, [mutated("infrahub.node.updated", "yesterday", "InterfacePhysical", "if-1", ["status"])]
    )
    with pytest.raises(ReadError) as raised:
        intent_events(f.reader(), "change-1", EVENT_BRANCHED, "")
    message = str(raised.value)
    assert '"yesterday"' in message and TOKEN not in message, f"a stamp that is not a time: {message}"
