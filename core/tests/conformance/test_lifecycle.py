"""A twin's lifecycle on any driver (design/core.md, phase 6, "The conformance suite"): the
`three-node` fixture end to end through API 1 and the thin CLI, created, each node answering
with its own host name, verified and destroyed; the core killed at every phase boundary of a
create, during its apply and during a destroy, and resumed each time to the state asked for,
a waiting CLI riding through the kill during a create's apply and during a destroy; and a
deletion asked during the apply. Phase 4's scenarios, and phase 6's waiting CLI through a kill,
written once over the harness (`harness/`).

A scenario reads the API, the CLI, the nodes' own answers at the record's addresses and the
harness, never a runtime: what a driver can do comes from `caps`, the default driver's
capabilities, and what only the runtime's own account shows is asserted behind the harness's
audits. The tests run in order and share the session's core; each prints what it took and what
it saw (`-s`), and removes its twin however it ends.

No assertion here shows a secret when it fails: the harness keeps the token and the core's
environment out of its repr, and the log check reports line numbers, never lines.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from conformance.harness import Fylgja, Harness, Resume
from conformance.nodes import host_name
from conformance.reads import (
    BLUEPRINT,
    DEADLINE_S,
    IN_APPLY_S,
    NODES,
    apply_ended,
    apply_started,
    assert_events_whole,
    assert_settled_ready,
    assert_twin_record,
    created_until,
    destroyed,
    remove,
    run_ids,
    runs_since,
    settled_ready,
    started,
    wait_for,
)
from fylgja_core import schemas

LIFE = "cf-life"
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed")
CREATE_PHASES = {"compile", "admit", "plan", "apply", "ready", "push"}
VERIFIED = {"held": 15, "failed": 0, "skipped": 3}
"""Verify of a `three-node` twin: 3 links, so 6 ports enabled and 6 neighbours, and 3 claims, held;
each node's host name a skip, reported."""


def incarnations(record: dict[str, Any]) -> dict[str, Any]:
    """Each node's incarnation, as the record holds it."""
    return {n["name"]: n.get("incarnation") for n in record["status"]["nodes"]}


# 1 and 2: create, show, verify, destroy.


def test_a_twin_is_created_and_each_node_answers_with_its_own_host_name(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    since, before = harness.mark(), run_ids(harness, LIFE)
    began = time.monotonic()
    code, _ = fylgja("twin", "create", LIFE, "--blueprint", str(BLUEPRINT))
    elapsed = time.monotonic() - began
    print(f"\n[conformance] create, end to end: {elapsed:.1f}s", flush=True)
    assert code == 0 and elapsed < DEADLINE_S

    code, out = fylgja("twin", "show", LIFE, "--json")
    record = json.loads(out)
    assert code == 0
    assert_twin_record(record)
    status = record["status"]
    assert_settled_ready(harness, record, f"{LIFE} after its create")
    assert record["generation"] == 1, record["generation"]
    assert [n["name"] for n in status["nodes"]] == list(NODES)
    assert all(n["holds"] == status["bundle_id"] for n in status["nodes"])
    held = harness.nodes(LIFE)
    print(f"[conformance] the runtime holds {sorted(held)}", flush=True)
    assert held == incarnations(record), "the runtime's nodes are not the record's"
    if caps["access"] == "direct":
        names = {n["name"]: host_name(n["address"], n["name"]) for n in status["nodes"]}
        print(f"[conformance] host names through each node's push transport: {names}", flush=True)
        assert names == {n: n for n in NODES}
    else:
        print("[conformance] the driver's access is not direct: no node is asked its host name", flush=True)

    (run,) = runs_since(harness, LIFE, before)
    code, out = fylgja("run", "get", run["id"], "--json")
    assert code == 0 and json.loads(out)["verdict"]["status"] == "ok"
    events = harness.events(run["id"])
    assert_events_whole(events)
    assert {e["phase"] for e in events} == CREATE_PHASES
    timings: dict[str, float] = {}
    for e in events:
        if e["outcome"] == "done":  # a phase's, or each node's in `ready` and `push`, summed
            timings[e["phase"]] = timings.get(e["phase"], 0.0) + e["duration_s"]
    print(f"[conformance] the create's phases: {', '.join(f'{p} {s:.2f}s' for p, s in timings.items())}", flush=True)

    code, out = fylgja("twin", "verify", LIFE, "--json")
    verdict = json.loads(out)
    print(f"[conformance] twin verify {LIFE}: exit {code}, {verdict['status']} {verdict.get('counts')}", flush=True)
    assert code == 0 and list(schemas.validator("findings-1").iter_errors(verdict)) == [], verdict
    assert verdict["counts"] == VERIFIED, verdict["findings"]
    harness.audit_apply(LIFE, since, 1)


def test_the_twin_is_destroyed_and_nothing_is_left(harness: Harness, fylgja: Fylgja) -> None:
    destroyed(harness, fylgja, LIFE)


# 3: a kill at every phase boundary of a create, and in its apply.


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_core_killed_at_a_create_phase_resumes_the_same_run_to_ready(
    harness: Harness, fylgja: Fylgja, phase: str
) -> None:
    twin = "cf-ckill"
    try:
        since, before = harness.mark(), run_ids(harness, twin)
        began = time.monotonic()
        seen = created_until(harness, fylgja, twin, phase)
        back = harness.kill()  # the kill follows the phase's record at once
        after = harness.record(twin)
        assert after is not None
        assert seen["status"].get("phase") == phase
        print(f"[conformance] killed at {phase}, {time.monotonic() - began - back:.1f}s in; serving again "
              f"{back:.2f}s after the kill, the record at {after['status'].get('phase')}", flush=True)

        record = settled_ready(harness, twin)
        took = time.monotonic() - began
        run_id = seen["status"]["run_id"]  # the run the record named when the core was killed
        creates = [r for r in runs_since(harness, twin, before) if r["operation"] == "create"]
        assert [r["id"] for r in creates] == [run_id], "the resume made a second create run"
        assert creates[0]["state"] == "ended" and creates[0]["verdict"]["status"] == "ok", creates[0].get("verdict")
        events = harness.events(run_id)
        assert_events_whole(events)
        applies = started(events, "apply")
        after_applied = KILL_AT.index(phase) >= KILL_AT.index("applied")
        print(f"[conformance] killed at {phase}: Ready {took:.1f}s after the create, the same run {run_id}, "
              f"{applies} apply started", flush=True)
        if after_applied:
            assert applies == 1, f"an apply started after {phase} was recorded"
            kept = incarnations(seen)
            assert all(kept.values()) and kept == incarnations(record), "the resume made a node anew"
        else:
            assert 1 <= applies <= 2
        assert [n["name"] for n in record["status"]["nodes"]] == list(NODES)
        harness.audit_resume(twin, since, Resume("create", applies, after_applied, in_apply=False))

        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert harness.leftovers(twin) == []
    finally:
        remove(harness, twin)


def test_a_core_killed_in_a_creates_apply_resumes_the_same_run_to_ready(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """The longest window a kill lands in, between `planned` and `applied`: read just before the
    kill, the run's events show its `apply` started and not ended."""
    twin = "cf-akill"
    try:
        since, before = harness.mark(), run_ids(harness, twin)
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        run_id = apply_started(harness, twin, "create", before)
        began = time.monotonic()  # once the apply has started: Ready is read from there
        time.sleep(IN_APPLY_S)
        assert not apply_ended(harness, run_id), f"the apply ended within {IN_APPLY_S}s"
        back = harness.kill()
        record = settled_ready(harness, twin)
        took = time.monotonic() - began
        creates = [r for r in runs_since(harness, twin, before) if r["operation"] == "create"]
        assert [r["id"] for r in creates] == [run_id], "the resume made a second create run"
        assert creates[0]["verdict"]["status"] == "ok", creates[0].get("verdict")
        events = harness.events(run_id)
        assert_events_whole(events)
        applies = started(events, "apply")
        print(f"[conformance] killed {IN_APPLY_S}s into the apply, serving again {back:.2f}s after: Ready {took:.1f}s "
              f"after the apply started, {applies} apply started (reapply {caps['reapply']})", flush=True)
        if caps["reapply"]:
            assert applies == 2, f"{applies} apply started"
        else:
            assert 1 <= applies <= 2, f"{applies} apply started"
        assert [n["name"] for n in record["status"]["nodes"]] == list(NODES)
        harness.audit_resume(twin, since, Resume("create", applies, after_applied=False, in_apply=True))
        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert harness.leftovers(twin) == []
    finally:
        remove(harness, twin)


# 4: the CLI waiting through a kill, during a create's apply and during a destroy; a deletion during the apply.


def test_a_waiting_create_rides_through_a_kill_of_the_core_during_the_apply(harness: Harness, fylgja: Fylgja) -> None:
    """The core killed `IN_APPLY_S` into the apply of a `twin create` that waits, with no
    `--no-wait`: the CLI's watch is cut, reconnects to the core serving again, and the command
    ends as it would have."""
    twin = "cf-wkill"
    # Set once the CLI has ended, before any assertion, and first of all in the `finally`: a killer
    # still waiting then stops, and kills nothing, so neither a join that timed out nor a CLI call
    # that raised can leave it to kill the core under the `finally`'s removal.
    cli_ended = threading.Event()
    try:
        before = run_ids(harness, twin)
        raised: list[BaseException] = []
        killed: list[tuple[float, float]] = []  # the kill's moment, and the seconds to the core's answer

        def kill_during_the_apply() -> None:
            try:
                run_id = apply_started(harness, twin, "create", before, ended=cli_ended)
                time.sleep(IN_APPLY_S)
                assert not apply_ended(harness, run_id), f"the apply ended within {IN_APPLY_S}s"
                assert not cli_ended.is_set(), "the create ended before the kill"
                back = harness.kill()  # the seconds from the kill to the core's answer
                killed.append((time.monotonic() - back, back))
            except BaseException as e:  # kept for the test's thread to report
                raised.append(e)

        killer = threading.Thread(target=kill_during_the_apply, daemon=True)
        killer.start()
        began = time.monotonic()
        code, out = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT))
        ended_at = time.monotonic()
        cli_ended.set()
        killer.join(timeout=60)
        assert not killer.is_alive() and raised == [], (raised, code)
        # The kill's own moment, not kill()'s return: a CLI may end between the core's answer and that return.
        assert killed and killed[0][0] < ended_at, ("the core was not killed while the create waited", raised, code)
        [(at, back)] = killed
        print(f"[conformance] a waiting create: the core killed {at - began:.1f}s after it was asked and serving again "
              f"{back:.1f}s after the kill; the command ended {ended_at - at:.1f}s after the kill", flush=True)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_ready = "Ready: True" in out
        assert code == 0 and said_ready, (raised, code)
        (run,) = [r for r in runs_since(harness, twin, before) if r["operation"] == "create"]
        assert run["verdict"]["status"] == "ok", run["verdict"]
        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert harness.leftovers(twin) == []
    finally:
        cli_ended.set()
        remove(harness, twin)


def test_a_core_killed_during_a_destroy_resumes_it_and_the_waiting_cli_ends(harness: Harness, fylgja: Fylgja) -> None:
    """The core killed under a `twin destroy` that waits: the CLI's watch is cut, reconnects to
    the core serving again, and the command ends as it would have. The kill waits for the destroy
    to have started, the loop's `destroy` event, since the API makes the destroy run before it
    answers the deletion: a kill then would cut the CLI's own request."""
    twin = "cf-dkill"
    cli_ended = threading.Event()  # as in the waiting create: set once the CLI has ended, and first in the `finally`
    try:
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT))
        assert code == 0
        before = run_ids(harness, twin)
        raised: list[BaseException] = []
        killed: list[tuple[float, float]] = []  # the kill's moment, and the seconds to the core's answer

        def destroying() -> bool | None:
            assert not cli_ended.is_set(), "the destroy ended before it was seen started"
            destroys = [r for r in runs_since(harness, twin, before) if r["operation"] == "destroy"]
            return True if destroys and started(harness.events(destroys[0]["id"]), "destroy") else None

        def kill_during_the_destroy() -> None:
            try:
                # Once the destroy has started, not at the run's first sight: the API makes the destroy run
                # before it answers the DELETE, so a kill then could cut the CLI's own request.
                wait_for(destroying, "the destroy's start", every_s=0.05)
                assert not cli_ended.is_set(), "the destroy ended before the kill"
                back = harness.kill()  # the seconds from the kill to the core's answer
                killed.append((time.monotonic() - back, back))
            except BaseException as e:  # kept for the test's thread to report
                raised.append(e)

        killer = threading.Thread(target=kill_during_the_destroy, daemon=True)
        killer.start()
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", twin)
        ended_at = time.monotonic()
        cli_ended.set()
        killer.join(timeout=60)
        assert not killer.is_alive() and raised == [], (raised, code)
        # The kill's own moment, not kill()'s return: a CLI may end between the core's answer and that return.
        assert killed and killed[0][0] < ended_at, ("the core was not killed while the destroy waited", raised, code)
        [(at, back)] = killed
        print(f"[conformance] a waiting destroy: the core killed {at - began:.1f}s after it was asked and serving "
              f"again {back:.1f}s after the kill; the command ended {ended_at - at:.1f}s after the kill", flush=True)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_deleted = f"twin {twin} deleted" in out
        assert code == 0 and said_deleted, (raised, code)
        assert harness.record(twin) is None
        (destroy,) = [r for r in runs_since(harness, twin, before) if r["operation"] == "destroy"]
        assert destroy["verdict"]["status"] == "ok", destroy["verdict"]
        assert harness.leftovers(twin) == []
    finally:
        cli_ended.set()
        remove(harness, twin)


def test_a_delete_during_the_apply_cancels_the_create_and_leaves_nothing(harness: Harness, fylgja: Fylgja) -> None:
    twin = "cf-del"
    try:
        before = run_ids(harness, twin)
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        run_id = apply_started(harness, twin, "create", before)
        applying = time.monotonic()
        # Asked once the apply has made nodes, so the cancel leaves a partial twin to tear down.
        wait_for(lambda: True if harness.nodes(twin) else None, "the apply's first nodes", every_s=0.2)
        assert not apply_ended(harness, run_id), "the apply ended before the deletion was asked"
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", twin)
        print(f"[conformance] deleted {began - applying:.1f}s into the apply, its first nodes made: gone "
              f"{time.monotonic() - began:.1f}s after it was asked", flush=True)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_deleted = f"twin {twin} deleted" in out
        assert code == 0 and said_deleted, code
        destroy, create = runs_since(harness, twin, before)
        assert (create["operation"], create["verdict"]["status"]) == ("create", "failed"), create["verdict"]
        assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]
        assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok"), destroy["verdict"]
        assert harness.leftovers(twin) == []
    finally:
        remove(harness, twin)
