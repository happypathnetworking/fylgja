"""A node replaced or stopped behind the core's back, on any driver (design/core.md, phase 6, "The
conformance suite"; D-067, D-058). The twin `cf-restore`, created from `three-node`, settled and
Ready, has its `n2` replaced by the harness, no client writing anything, and the core's own run,
a restore, readies it and pushes it again; stepped to `three-node-unmanaged`, it has its `n2`,
which carries no configuration, replaced again, readied and pushed nothing; then its `n3` is
stopped, reported missing past its boot window and never made, and the twin is destroyed.

The harness's core resyncs no sooner than every 3600 s (`Harness.start`), so a restore a scenario
reads was asked for by the driver's events alone, never by the resync. A replacement's restore is
read through a watch of the twin opened before it: Ready False for `twin.restoring`, then True. A
node that reads `twin.node.missing` before that has booted past its window: the scenario fails
with the reading (pre-flight ruling 4), and branches on nothing.

The unmanaged node's replacement is the one place a pushed line can be read after a replacement
with no push racing the read: where the driver's `access` is `direct`, `n2`'s description pushed
by `three-node` is read again after it, and printed present or absent, failing on neither; it
answers the open question of the SR Linux marker (decisions.md).

The tests run in order and share the twin; each prints what it took and what it saw (`-s`).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from conformance.harness import Fylgja, Harness
from conformance.nodes import srlinux_described
from conformance.reads import (
    BLUEPRINT,
    DEADLINE_S,
    DESCRIBED,
    NODES,
    QUIET_S,
    ROOT,
    SSE,
    addresses,
    assert_events_whole,
    assert_settled_ready,
    assert_twin_record,
    by,
    created,
    destroyed,
    ended,
    holds,
    incarnations,
    record_nodes,
    run_ids,
    runs_since,
    verified,
    wait_for,
    walk,
)
from fylgja_core import schemas
from fylgja_core.client import messages
from fylgja_core.reconcile import REASON_READY, REASON_RESTORING, RESTORE_PRINCIPAL, RULE_NODE_MISSING
from fylgja_core.run import Operation
from fylgja_core.verify import RULE_NODE_UNREAD

TWIN = "cf-restore"
UNMANAGED = ROOT / "testdata" / "blueprint" / "three-node-unmanaged.json"
RESTORE: Operation = "restore"
"""The restore run's operation, typed by the contract's operations."""
REPORTED_S = 180.0
"""How long a stopped node may take to be reported: its boot window, SR Linux's 60 s from the first
pass that saw it absent, and the passes around it."""


@dataclass(frozen=True)
class Restored:
    """A node replaced behind the core's back and the twin restored: the record before the
    replacement and after the restore, the incarnations before, and the restore run with its
    events."""

    before: dict[str, Any]
    record: dict[str, Any]
    was: dict[str, str]
    run: dict[str, Any]
    events: list[dict[str, Any]]


def ready_of(record: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """The record's Ready condition: its status, its reason and its `since`."""
    (condition,) = [c for c in record["status"]["conditions"] if c["type"] == "Ready"]
    return condition["status"], condition.get("reason"), condition.get("since")


def seconds(at: str | None, origin: datetime) -> float:
    """The seconds from `origin` to the time `at`, a record's or a run's: `at` by the core's clock
    and `origin` by this host's, one clock locally and two on the cluster, which agreed within
    about 50 ms (verified-facts.md, the development host's clock and the Lease holder's)."""
    assert at is not None, "no time to read"
    return (datetime.fromisoformat(at) - origin).total_seconds()


def replaced(harness: Harness, twin: str, node: str) -> Restored:
    """`node` of `twin`, settled and Ready, replaced by the harness with a watch of the twin open
    and nothing written by any client; the watch followed until it shows Ready False for
    `twin.restoring`, then True, in that order (`twin.node.missing` before them fails the test with
    its reading, pre-flight ruling 4); then the one run made since: a restore, the core's own,
    ended `ok`, its verdict held to findings 1, its events whole and holding no `apply`. The record
    after it is held to twin record 1. The seconds from the replacement's return to the run's
    making, to Ready and to the run's end are printed, with the run's events and its wait."""
    before = harness.record(twin)
    assert before is not None, f"{twin} is gone"
    assert_settled_ready(harness, before, f"{twin} before {node}'s replacement")
    runs_before, was = run_ids(harness, twin), incarnations(harness, twin)
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    after: dict[str, Any] | None = None
    with harness.client().stream("GET", f"/v1/twins/{twin}", params={"watch": "true"}, headers={"Accept": SSE},
                                 timeout=timeout) as stream:
        assert stream.status_code == 200
        began = time.monotonic()
        harness.replace_node(twin, node)
        returned, took = datetime.now(UTC), time.monotonic() - began
        restoring = False
        for message in messages(by(deadline, stream.iter_lines(), f"{twin} was not restored")):
            seen: dict[str, Any] = json.loads(message.data)["object"]
            status, reason, since = ready_of(seen)
            if not restoring:
                if (status, reason) == ("False", REASON_RESTORING):
                    restoring = True
                    continue
                if reason == RULE_NODE_MISSING:
                    pytest.fail(f"{twin} read Ready False for {RULE_NODE_MISSING} {seconds(since, returned):+.1f}s "
                                f"after {node}'s replacement returned, before {REASON_RESTORING}: the replacement "
                                "booted past its window (pre-flight ruling 4)")
                assert (status, reason) == ("True", REASON_READY), \
                    f"{twin} read Ready {status} for {reason} before {REASON_RESTORING}"
            elif (status, reason) == ("True", REASON_READY):
                after = seen
                break
            else:
                assert (status, reason) == ("False", REASON_RESTORING), \
                    f"{twin} read Ready {status} for {reason} while restoring"
    assert after is not None, f"the watch of {twin} ended before it was restored"
    made = runs_since(harness, twin, runs_before)
    assert [(r["operation"], r["principal"]) for r in made] == [(RESTORE, RESTORE_PRINCIPAL)], \
        f"the replacement made {[(r['operation'], r['principal']) for r in made]}, not the core's one restore"
    (run,) = made
    assert schemas.api_validator("Run").is_valid(run), run
    assert run["state"] == "ended" and run["verdict"]["status"] == "ok", run.get("verdict")
    assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
    events = harness.events(run["id"])
    assert_events_whole(events)
    record = harness.record(twin)
    assert record is not None, f"{twin} is gone after its restore"
    assert_twin_record(record)
    verdict = run["verdict"]
    print(f"[conformance] {twin}: {node} replaced in {took:.2f}s; from its return, the restore run made "
          f"{seconds(run['created_at'], returned):+.2f}s, Ready True {seconds(ready_of(after)[2], returned):+.2f}s, "
          f"the run ended {seconds(run.get('ended_at'), returned):+.2f}s; its events "
          f"{[(e['phase'], e['outcome'], e.get('node')) for e in events if e['outcome'] != 'started']}; the wait "
          f"{verdict.get('wait')}; counts {verdict.get('counts')}; findings "
          f"{[(f['rule'], f.get('object')) for f in verdict['findings']]}", flush=True)
    assert "apply" not in {e["phase"] for e in events}, "the restore applied"
    return Restored(before=before, record=record, was=was, run=run, events=events)


def test_the_twin_is_created_from_three_node(harness: Harness, fylgja: Fylgja) -> None:
    record = created(harness, fylgja, TWIN, BLUEPRINT, NODES)
    assert set(holds(harness, TWIN).values()) == {record["status"]["bundle_id"]}
    verified(fylgja, TWIN, "three-node")


def test_a_node_replaced_behind_the_core_is_readied_and_pushed_again_without_the_resync(
    harness: Harness, fylgja: Fylgja
) -> None:
    """No client writes after the replacement, and the resync is an hour away: the driver's events
    alone ask for the restore, which readies and pushes `n2` and touches no other node."""
    r = replaced(harness, TWIN, "n2")
    assert ended(r.events, "ready") == {"n2": "done"}, ended(r.events, "ready")
    pushed = ended(r.events, "push")
    assert {n for n, outcome in pushed.items() if outcome == "done"} == {"n2"}, pushed
    now = {name: str(n["incarnation"]) for name, n in record_nodes(r.record).items()}
    held = harness.nodes(TWIN)
    assert now["n2"] != r.was["n2"], "n2's incarnation did not move"
    assert held == now, "the runtime's nodes are not the record's"
    others = [n for n in NODES if n != "n2"]
    assert {n: now[n] for n in others} == {n: r.was[n] for n in others}, "another node moved"
    assert holds(harness, TWIN) == dict.fromkeys(NODES, r.record["status"]["bundle_id"])
    assert r.record["generation"] == r.before["generation"]
    assert r.record["status"].get("last_step") == r.before["status"].get("last_step")
    verified(fylgja, TWIN, "three-node")


def test_an_unmanaged_node_replaced_is_restored_with_no_push(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """`n2` carries no configuration in `three-node-unmanaged`, so the step pushes nothing and
    `n2` keeps the configuration pushed before (D-048); replaced, it is readied and marked holding
    the bundle with no push, so nothing races a read of what it runs."""
    s = walk(harness, fylgja, caps, TWIN, UNMANAGED)
    direct = caps["access"] == "direct"
    if direct:
        # Held first, since pytest would explain a False with the call's arguments, the node's address.
        described = srlinux_described(addresses(s.record)["n2"], "ethernet-1/1")
        assert described == DESCRIBED, described
    else:
        print("[conformance] the driver's access is not direct: n2's configuration is not read", flush=True)
    r = replaced(harness, TWIN, "n2")
    assert ended(r.events, "ready") == {"n2": "done"}, ended(r.events, "ready")
    pushed = ended(r.events, "push")
    print(f"[conformance] n2's push in the restore: {pushed.get('n2', 'no event')}", flush=True)
    assert pushed.get("n2") != "done", pushed
    assert holds(harness, TWIN)["n2"] == r.record["status"]["bundle_id"]
    verified(fylgja, TWIN, "three-node-unmanaged")
    if direct:
        found = srlinux_described(addresses(r.record)["n2"], "ethernet-1/1")
        print(f"[conformance] marker after a replacement: {'present' if found == DESCRIBED else 'absent'}", flush=True)
    else:
        print("[conformance] the driver's access is not direct: the marker is not read", flush=True)


def test_a_node_stopped_behind_the_core_is_reported_and_never_made(harness: Harness, fylgja: Fylgja) -> None:
    """A node that stays stopped is waited for through its boot window, then reported, with no run
    made and nothing made anew (D-067); verify reads it unread, and the twin is destroyed whole. A
    harness whose runtime keeps no node stopped says why, and the twin is destroyed and the
    scenario skipped with that reason."""
    before = harness.record(TWIN)
    assert before is not None, f"{TWIN} is gone"
    assert_settled_ready(harness, before, f"{TWIN} before n3's stop")
    runs_before, held_before = run_ids(harness, TWIN), harness.nodes(TWIN)
    began = time.monotonic()
    try:
        harness.stop_node(TWIN, "n3")
    except NotImplementedError as e:
        destroyed(harness, fylgja, TWIN)
        pytest.skip(str(e))
    stopped, took = datetime.now(UTC), time.monotonic() - began

    def reported() -> dict[str, Any] | None:
        record = harness.record(TWIN)
        assert record is not None, f"{TWIN} is gone"
        return record if ready_of(record)[:2] == ("False", RULE_NODE_MISSING) else None

    record = wait_for(reported, f"{TWIN}'s Ready False for {RULE_NODE_MISSING}", timeout_s=REPORTED_S)
    print(f"[conformance] {TWIN}: n3 stopped in {took:.2f}s; Ready False for {RULE_NODE_MISSING} "
          f"{seconds(ready_of(record)[2], stopped):+.1f}s after the stop returned", flush=True)
    assert run_ids(harness, TWIN) == runs_before, "a run was made"
    assert record["generation"] == before["generation"]
    held = harness.nodes(TWIN)
    assert held.get("n3") in (None, held_before["n3"]), "the runtime holds n3 at a new incarnation"
    code, out = fylgja("twin", "verify", TWIN, "--json")
    assert out.strip(), f"twin verify {TWIN} printed nothing: exit {code}"
    doc = json.loads(out)
    errors = sorted((f["rule"], f.get("object")) for f in doc["findings"] if f["severity"] == "error")
    print(f"[conformance] twin verify {TWIN}: exit {code}, {doc.get('status')} {doc.get('counts')}, errors {errors}",
          flush=True)
    assert list(schemas.validator("findings-1").iter_errors(doc)) == [], doc
    assert code == 1 and doc["status"] == "failed", (code, doc["status"])
    assert errors == [(RULE_NODE_UNREAD, "n3")], doc["findings"]
    destroyed(harness, fylgja, TWIN)
