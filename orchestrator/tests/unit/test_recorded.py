"""The adapter on a real Infrahub's answers: the fixture branch `fylgja-fixture` as this
host's Infrahub 1.11.2 answered the read, the stamps and the event log on 2026-10-29
(`tests/data/graphql/fylgja-fixture/`, recorded read-only by the adapter itself), replayed
request by request. The read files the fixture's snapshot, `0940db93…`, the id the Go
reader files; the stamps and the events are the Go reader's own of the same branch at the
same moment (`go-stamps-events.json`, written by `intent.Client.Stamps` and
`StageReader.IntentEvents`). Tier 2 reads the live branch (T020); this holds the port to
real wire shapes with no Infrahub."""

import json

import pytest

from fylgja_orchestrator.adapters.infrahub import events, packages, read, stamps
from fylgja_orchestrator.adapters.infrahub.client import Client, Config, DefaultClient

from .conftest import ADDRESS, DATA, TOKEN

RECORDED = DATA / "graphql" / "fylgja-fixture"
FIXTURE_SNAPSHOT = "0940db93e2ad1244a097824ececdaa6979500b1ddeeef15ca3cd612da68656ef"


def replay(infrahub, name):
    """Answers each recorded operation with the response recorded for its variables."""
    recorded = json.loads((RECORDED / name).read_text())
    by_request = {}
    for a in recorded["answers"]:
        key = (a["operation"], json.dumps(a["variables"], sort_keys=True))
        by_request[key] = (a["status"], a["body"])
        table = infrahub.default_operations if a.get("path") == "/graphql" else infrahub.operations

        def answer(variables, query, branch, params, operation=a["operation"]):
            return by_request[(operation, json.dumps(variables, sort_keys=True))]

        table[a["operation"]] = answer
    return recorded


@pytest.fixture
def recorded(infrahub):
    infrahub.branches.add("fylgja-fixture")
    for path in RECORDED.glob("object-*.txt"):
        infrahub.objects[path.stem.removeprefix("object-")] = (200, path.read_bytes())
    return infrahub


def test_the_recorded_fixture_reads_to_its_snapshot(recorded):
    read_answers = replay(recorded, "read.json")
    # The schema endpoint's document is the library's as recorded for the conformance
    # tests; its hash is the branch's as the read recorded it.
    recorded.schema["main"] = read_answers["schema_hash"]
    client = Client(Config(address=ADDRESS, token=TOKEN, branch="fylgja-fixture"), requester=recorded)

    taken, found = read.read_snapshot(client, "tag:fylgja", packages.load(override_dir=""), [],
                                     "2026-10-29T00:00:00.000000Z")

    assert list(found) == []
    assert taken["snapshot_id"] == FIXTURE_SNAPSHOT
    assert read.summarize(taken["ctm"]) == read.Counts(devices=3, interfaces=15, links=3, artifacts=3)


def test_the_recorded_fixtures_stamps_are_the_go_readers(recorded):
    replay(recorded, "stamps.json")
    go = json.loads((RECORDED / "go-stamps-events.json").read_text())["stamps"]
    client = Client(Config(address=ADDRESS, token=TOKEN, branch="fylgja-fixture"), requester=recorded)

    s = stamps.read_stamps(client, "fylgja")

    assert s.latest == go["Latest"]
    assert {
        name: {
            "Match": {"manufacturer": d.match.manufacturer, "platform": d.match.platform},
            "IDs": d.ids,
            "Intent": d.intent,
            "Artifacts": d.artifacts,
        }
        for name, d in s.devices.items()
    } == go["Devices"]


def test_the_recorded_fixtures_events_are_the_go_readers(recorded):
    answers = replay(recorded, "stamps.json")
    since = next(a for a in answers["answers"] if a["operation"] == "IntentEvents")["variables"]["since"]
    go = json.loads((RECORDED / "go-stamps-events.json").read_text())["events"]
    reader = DefaultClient(ADDRESS, TOKEN, requester=recorded)

    found = events.intent_events(reader, "fylgja-fixture", since)

    assert [{"Name": e.name, "OccurredAt": e.occurred_at, "Kind": e.kind, "Nodes": e.nodes} for e in found] == go
    assert len(recorded.served("IntentEvents")) == 3
