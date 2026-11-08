"""Phase 5's step scenarios on any driver (design/core.md, phase 6, "The conformance suite"):
`fylgja-core twin step` takes a fixture twin to every step fixture from its base
(testdata/blueprint/steps/README.md), end to end through API 1 and the thin CLI. The twin
`cf-step`, created from `three-node`, takes each SR Linux fixture and steps back to the base
where the next step needs it: a link removed and added back, a port disabled by intent and
enabled again, a node's configuration dropped (unmanaged, D-048) and given back, a node removed
and added back, a probe's two hosts added, moved to `n2` (after a dry run through the CLI) and
removed, and a step to the bundle the twin runs. Then its `n3` becomes EOS, a kind change. The
twin `cf-eos`, created from `mixed`, has a port added to its two EOS nodes: refused without the
spec's `allow_restart` before anything is touched, where the driver must restart a node for it,
and made with it.

Each step goes by what its dry run answers (`reads.walk`): which nodes keep their incarnation,
which are made anew, and whether the spec must allow a restart, so the same walk holds on a
driver whose answer differs. Each step's record, run and events are held to their formats, the
runtime's nodes to the record's incarnations, and the nodes' own answers read by a verify
through the CLI once the step has ended (one asked during a step's wait may find a node's read
still held, D-054); what only the runtime's own account shows is asserted behind the harness's
audits. Where the driver's `access` is `direct`, a scenario also asks the nodes themselves at
the record's addresses. The EOS scenarios skip, with the rule quoted, where the core says the
image cannot be had (`reads.needs_ceos`).

The tests run in order and share each twin, each starting from what the one before left; each
prints what it took and what it saw (`-s`).
"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest

from conformance.harness import Fylgja, Harness
from conformance.nodes import eos, eos_answer, srlinux_described, srlinux_neighbours
from conformance.reads import (
    BLUEPRINT,
    DESCRIBED,
    MIXED,
    MIXED_NODES,
    NODES,
    RESTART,
    ROOT,
    addresses,
    assert_settled_ready,
    created,
    destroyed,
    expected,
    holds,
    incarnations,
    needs_ceos,
    record_nodes,
    settled,
    stepped,
    verified,
    walk,
)
from fylgja_core.push import Unreachable

STEP = "cf-step"
EOS_TWIN = "cf-eos"
STEPS = ROOT / "testdata" / "blueprint" / "steps"
UNLINKED = STEPS / "three-node-unlinked.json"
DISABLED = STEPS / "three-node-n1-disabled.json"
UNMANAGED = ROOT / "testdata" / "blueprint" / "three-node-unmanaged.json"
TWO_NODE = STEPS / "two-node.json"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
MOVED = STEPS / "three-node-probed-moved.json"
N3_EOS = STEPS / "three-node-n3-eos.json"
E2_PORT = STEPS / "mixed-e2-port.json"
HOSTS = ("n1-loop-a", "n1-loop-b")
"""The probe `n1-loop`'s two hosts, as the record names them."""
NOT_STARTED = [{"probe": "n1-loop", "from": "a", "outcome": "not_started"},
               {"probe": "n1-loop", "from": "b", "outcome": "not_started"}]
"""A step's `loss` when the probe's hosts were just made: no burst ran before the step."""
UNCHANGED_S = 2.0
"""A step to the bundle the twin runs ends at `compiled`, touching nothing: within this, end to end."""
EOS_WAIT_S = 60.0
"""How long a test waits for EOS to list a port `connected`, from the step's end."""
ETHERNET10 = "show interfaces Ethernet10 status"
LISTED = re.compile(r"^Et10\s", re.MULTILINE)
"""EOS's status table names the port by its short name, never `Ethernet10`."""
CONNECTED = re.compile(r"^Et10\s+connected\s", re.MULTILINE)


def ethernet10(address: str) -> str | None:
    """What EOS answers `show interfaces Ethernet10 status` with, through eAPI at `address`: the
    table's text, or None when the node refuses the command, as it does for a port it lacks."""
    answer = eos_answer(address, ETHERNET10)
    if "error" in answer:
        error = answer["error"]
        print(f"[conformance] {ETHERNET10!r} refused: code {error.get('code')!r}, message "
              f"{error.get('message')!r:.200}, data {error.get('data')!r:.300}", flush=True)
        return None
    output = str(answer["result"][0]["output"])
    print(f"[conformance] {ETHERNET10!r}: {output!r:.300}", flush=True)
    return output


def until_connected(address: str) -> tuple[str | None, str, float]:
    """`ethernet10` until it lists `Et10` `connected`, for at most `EOS_WAIT_S`: the first
    answer, the last, and the seconds it took. A node that gives no answer, as a node made anew
    may while its address has no endpoint yet, is asked again, as one that refuses is."""
    start = time.monotonic()

    def ask() -> str | None:
        try:
            return ethernet10(address)
        except Unreachable as e:  # Timeout too, its subclass; the message names the node's URL, so its class alone
            print(f"[conformance] {ETHERNET10!r}: no answer ({type(e).__name__})", flush=True)
            return None

    first = shown = ask()
    while not (shown is not None and CONNECTED.search(shown)) and time.monotonic() - start < EOS_WAIT_S:
        time.sleep(2)
        shown = ask()
    assert shown is not None and CONNECTED.search(shown), f"Et10 not connected within {EOS_WAIT_S:g}s: {shown!r}"
    return first, shown, time.monotonic() - start


def eos_neighbours(address: str) -> dict[str, tuple[str, str]]:
    """Each port's LLDP neighbour as EOS lists it, `show lldp neighbors` through eAPI as JSON:
    its device and its port."""
    entries = eos(address, "show lldp neighbors", format="json")["lldpNeighbors"]
    print(f"[conformance] the LLDP neighbours, as EOS lists them: {entries}", flush=True)
    return {e["port"]: (e["neighborDevice"], e["neighborPort"]) for e in entries}


# The twin, and its steps.


def test_the_twin_is_created_from_three_node(harness: Harness, fylgja: Fylgja) -> None:
    record = created(harness, fylgja, STEP, BLUEPRINT, NODES)
    assert set(holds(harness, STEP).values()) == {record["status"]["bundle_id"]}
    verified(fylgja, STEP, "three-node")


def test_a_link_removed_leaves_its_ends_out_of_verify(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    s = walk(harness, fylgja, caps, STEP, UNLINKED)
    assert holds(harness, STEP) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []
    assert s.verify is not None
    removed = {"n2:ethernet-1/2", "n3:ethernet-1/1"}
    assert not [f for f in s.verify["findings"] if f["object"] in removed], "a finding names the removed link"


def test_the_link_added_back_is_held_at_both_ends(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    s = walk(harness, fylgja, caps, STEP, BLUEPRINT)  # verify: every neighbour, the link's two ends among them, held
    assert holds(harness, STEP) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []


def test_a_port_disabled_by_intent_is_neither_pushed_nor_asserted(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """`three-node-n1-disabled` changes intent alone: `n1`'s configuration is the same, so
    nothing is pushed, and verify asserts neither the port's admin state nor its link's ends."""
    s = walk(harness, fylgja, caps, STEP, DISABLED)
    assert holds(harness, STEP) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []
    assert s.verify is not None
    ports = sorted(f["object"] for f in s.verify["findings"] if ":" in f["object"])
    assert ports == ["n1:ethernet-1/2", "n1:ethernet-1/2", "n3:ethernet-1/2"], s.verify["findings"]


def test_the_port_enabled_again_is_asserted_again(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    s = walk(harness, fylgja, caps, STEP, BLUEPRINT)
    assert s.verdict["loss"] == []


def test_a_configuration_dropped_pushes_nothing_and_the_node_keeps_what_it_runs(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """`three-node-unmanaged`: `n2` carries no configuration, so it is unmanaged, and a step from a
    configuration to none pushes nothing (D-048). `n2` keeps the configuration pushed before."""
    s = walk(harness, fylgja, caps, STEP, UNMANAGED)
    assert holds(harness, STEP) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []
    if caps["access"] == "direct":
        # n2's running configuration is the one pushed before, by a line the kind's baseline does not set;
        # held first, since pytest would explain a False with the call's arguments, the node's address.
        described = srlinux_described(addresses(s.record)["n2"], "ethernet-1/1")
        assert described == DESCRIBED, described
    else:
        print("[conformance] the driver's access is not direct: n2's configuration is not read", flush=True)
    assert s.verify is not None
    (claim,) = [f for f in s.verify["findings"] if f["object"] == "n2"]
    assert "carries no configuration" in claim["message"], claim


def test_the_configuration_given_back_is_pushed_to_that_node_alone(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    s = walk(harness, fylgja, caps, STEP, BLUEPRINT, pushed=frozenset({"n2"}))
    assert s.verdict["loss"] == []


def test_a_node_removed_is_gone_from_the_record_and_the_runtime(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    s = walk(harness, fylgja, caps, STEP, TWO_NODE)
    assert sorted(record_nodes(s.record)) == ["n1", "n2"]
    assert sorted(harness.nodes(STEP)) == ["n1", "n2"], "n3 is left in the runtime"
    assert s.verdict["loss"] == []


def test_a_node_added_is_readied_and_pushed_alone(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    s = walk(harness, fylgja, caps, STEP, BLUEPRINT)
    print(f"[conformance] the node added: the step took {s.took_s:.1f}s end to end", flush=True)
    assert sorted(record_nodes(s.record)) == list(NODES)
    assert holds(harness, STEP) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []


def test_a_probe_added_readies_its_hosts_and_its_bursts_hold(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    s = walk(harness, fylgja, caps, STEP, PROBED)  # verify: both bursts held, no verify.burst finding
    assert sorted(record_nodes(s.record)) == sorted((*NODES, *HOSTS))
    bundle_id = s.record["status"]["bundle_id"]
    assert holds(harness, STEP) == {**dict.fromkeys(NODES, bundle_id), **dict.fromkeys(HOSTS)}, "a probe host holds"
    assert s.verdict["loss"] == NOT_STARTED
    assert s.verdict["counts"] == {"held": 19, "failed": 0, "skipped": 5}, "the wait's verify, bursts and all"


def test_a_step_to_the_bundle_the_twin_runs_is_unchanged(harness: Harness, fylgja: Fylgja) -> None:
    """A new spec in form, a bundle for a blueprint, of the bundle the twin runs: a run that
    compiles and ends there."""
    before = harness.record(STEP)
    assert before is not None
    bundle_id, kept = before["status"]["bundle_id"], incarnations(harness, STEP)
    s = stepped(harness, fylgja, STEP, bundle=bundle_id)  # Ready before, the one run its own, all held to formats
    last = s.record["status"]["last_step"]
    print(f"[conformance] a step to the bundle it runs: exit {s.code} in {s.took_s:.2f}s, the run's phases "
          f"{sorted({e['phase'] for e in s.events})}", flush=True)
    assert s.code == 0 and s.took_s < UNCHANGED_S
    assert (last["outcome"], last["phase"], last["from"], last["to"]) == ("unchanged", "compiled", bundle_id, bundle_id)
    assert s.verdict["status"] == "ok", s.verdict
    assert_settled_ready(harness, s.record, f"{STEP} after a step to the bundle it runs")
    assert s.record["status"]["bundle_id"] == bundle_id
    assert {e["phase"] for e in s.events} == {"compile"}
    harness.audit_apply(STEP, s.since, 0)
    assert incarnations(harness, STEP) == kept == harness.nodes(STEP), "a node was touched"


def test_a_dry_run_of_the_probe_moved_answers_its_changes_and_touches_nothing(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """`twin step --dry-run` writes no spec and makes nothing: its plan's `changes` say what the
    step would do to each node, and its verdict the refusal the step would meet without
    `allow_restart`, exited by (`expected` holds all of it)."""
    e = expected(harness, fylgja, caps, STEP, MOVED)
    print(f"[conformance] the probe moved, by the dry run: {e}", flush=True)


def test_a_probe_moved_makes_what_the_dry_run_answers_and_its_bursts_hold(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """With `allow_restart` where the dry run refuses without it."""
    s = walk(harness, fylgja, caps, STEP, MOVED)  # verify: both bursts held, from the hosts' new places
    assert sorted(record_nodes(s.record)) == sorted((*NODES, *HOSTS))
    bundle_id = s.record["status"]["bundle_id"]
    assert holds(harness, STEP) == {**dict.fromkeys(NODES, bundle_id), **dict.fromkeys(HOSTS)}, "a probe host holds"
    assert s.verdict["loss"] == NOT_STARTED
    assert s.verdict["counts"] == {"held": 19, "failed": 0, "skipped": 5}, "the wait's verify, bursts and all"


def test_a_probe_removed_takes_its_hosts_away(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    """From `n2`, back to `three-node`, the base the kind change steps from."""
    s = walk(harness, fylgja, caps, STEP, BLUEPRINT)
    assert sorted(record_nodes(s.record)) == list(NODES) and sorted(harness.nodes(STEP)) == list(NODES), \
        "a probe host is left"
    assert s.verdict["loss"] == []


def test_a_kind_change_makes_n3_eos_and_its_neighbours_hold_across_kinds(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    needs_ceos(harness)
    s = walk(harness, fylgja, caps, STEP, N3_EOS)
    print(f"[conformance] the kind change: the step took {s.took_s:.1f}s end to end", flush=True)
    assert s.verdict["loss"] == []
    assert s.verify is not None
    (reported,) = [f for f in s.verify["findings"] if f["object"] == "n3"]
    assert "reports its host name as n3;" in reported["message"], reported
    if caps["access"] != "direct":
        print("[conformance] the driver's access is not direct: no node is asked its LLDP neighbours", flush=True)
        return
    # The two links' neighbours, which verify held, as each end lists them; n3 answers eAPI, which only EOS does.
    at = addresses(s.record)
    assert srlinux_neighbours(at["n1"], "ethernet-1/2") == [("n3", "Ethernet2")]
    assert srlinux_neighbours(at["n2"], "ethernet-1/2") == [("n3", "Ethernet1")]
    listed = {port: far for port, far in eos_neighbours(at["n3"]).items() if port.startswith("Ethernet")}
    assert listed == {"Ethernet1": ("n2", "ethernet-1/2"), "Ethernet2": ("n1", "ethernet-1/2")}, listed


def test_the_twin_is_destroyed_and_nothing_is_left(harness: Harness, fylgja: Fylgja) -> None:
    destroyed(harness, fylgja, STEP)


# The EOS twin: a port added, refused without `allow_restart` and made with it.


def test_the_ceos_twin_is_created_from_mixed(harness: Harness, fylgja: Fylgja, caps: dict[str, Any]) -> None:
    needs_ceos(harness)
    record = created(harness, fylgja, EOS_TWIN, MIXED, MIXED_NODES)
    if caps["access"] == "direct":
        shown = ethernet10(addresses(record)["e2"])
        assert shown is None or not LISTED.search(shown), "e2 lists Et10 before the step"
    else:
        print("[conformance] the driver's access is not direct: e2's ports are not read", flush=True)
    verified(fylgja, EOS_TWIN, "mixed")


def test_a_ceos_port_added_without_allow_restart_is_refused_before_anything_is_touched(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    needs_ceos(harness)
    e = expected(harness, fylgja, caps, EOS_TWIN, E2_PORT)
    if e.refused != RESTART:
        pytest.skip(f"the dry run of {E2_PORT.stem} answers {e.refused or 'no refusal'}, not {RESTART}: this driver "
                    "makes the port with no restart, so there is no refusal to read")
    kept, held = harness.nodes(EOS_TWIN), holds(harness, EOS_TWIN)
    s = stepped(harness, fylgja, EOS_TWIN, E2_PORT)
    status, before, verdict = s.record["status"], s.before["status"], s.verdict
    last = status["last_step"]
    assert s.code == 1 and verdict["status"] == "rejected", verdict
    errors = sorted((f["rule"], f.get("object")) for f in verdict["findings"] if f["severity"] == "error")
    assert errors == sorted((RESTART, node) for node in e.restarted | e.recreated), verdict["findings"]
    conditions = {c["type"]: (c["status"], c.get("reason")) for c in status["conditions"]}
    assert conditions["Ready"] == ("False", RESTART), conditions
    assert conditions["Stepping"] == ("False", RESTART), conditions
    assert "Diverged" not in conditions or conditions["Diverged"][0] == "False", conditions
    # Refused at `planned`, after `plan done`: the twin runs what it ran, its phase too.
    assert (last["outcome"], last["phase"], last["from"]) == ("rejected", "planned", before["bundle_id"]), last
    # Held as a bool: pytest would explain a False with the record, which holds each node's address.
    is_settled = settled(s.record)
    assert last["to"] != last["from"] and is_settled
    assert [status.get(k) for k in ("bundle_id", "blueprint_id", "deployment_id", "phase")] == [
        before.get(k) for k in ("bundle_id", "blueprint_id", "deployment_id", "phase")]
    assert {event["phase"] for event in s.events} == {"compile", "admit", "plan"}, "a phase past the plan ran"
    harness.audit_apply(EOS_TWIN, s.since, 0)
    assert harness.nodes(EOS_TWIN) == kept == incarnations(harness, EOS_TWIN), "a node was touched"
    assert holds(harness, EOS_TWIN) == held


def test_the_ceos_port_added_with_allow_restart_is_made_as_the_dry_run_answers(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    needs_ceos(harness)
    s = walk(harness, fylgja, caps, EOS_TWIN, E2_PORT, ready_before=False)  # a refusal before it leaves Ready False
    print(f"[conformance] the EOS port added: the step took {s.took_s:.1f}s end to end", flush=True)
    assert s.verdict["loss"] == []
    if caps["access"] != "direct":
        print("[conformance] the driver's access is not direct: no node's ports are read", flush=True)
        return
    at = addresses(s.record)
    for node in ("e1", "e2"):
        first, last, took = until_connected(at[node])
        print(f"[conformance] {node}'s {ETHERNET10!r} after the step, first: {first!r}; connected in {took:.1f}s: "
              f"{last!r}", flush=True)


def test_the_ceos_twin_is_destroyed_and_nothing_is_left(harness: Harness, fylgja: Fylgja) -> None:
    needs_ceos(harness)
    destroyed(harness, fylgja, EOS_TWIN)
