"""Many twins at once on any driver (design/core.md, "Phase 7"; D-073 to D-076). The harness's
count of twins (`Harness.many()`), `cf-many-1` and on, are created together, the odd ones from
`three-node` and the even ones from `mixed` where the core can have the EOS image
(`reads.needs_ceos`, read once; where it cannot, every one from `three-node`, printed so), and
all reach Ready. Each is then stepped once while the others run, a `three-node` twin to
`three-node-unlinked` and a `mixed` one to `mixed-e2-port` with `--allow-restart`, every step
asked before any is waited for: each step's verdict, and the settled verify after it, reads no
node unread and no wait expired. A twin of forty nodes that no runtime has room for, `cf-big`,
is refused in a dry run and at its create with the shortfall named, leaving nothing; and every
twin is destroyed, leaving nothing.

The runtime's room is read through `GET /v1/capacity` before, during and after (`capacity`),
and agrees with the refusal in its hosts and in its sign, never to the unit, since nodes start
between two readings. Where each node runs is the harness's (`Harness.hosts`): where the
capacity read names more than one host, the twins' nodes are spread over two or more. While the
creates and the steps run, the test host's established TCP connections to a node's push or gNMI
port are counted every 2 s (`Connections`), as `ss -Htn state established` would count them,
from the kernel's own tables: where the core runs on this host they are its own connections to
the nodes, beside whatever else the host has open to those ports, and where it runs elsewhere
they are the suite's own. Timings are printed, never asserted, but for the two rules every step
is held to.

Creates, steps and destroys are asked with `--no-wait`, so the twins' runs are in flight
together, and are waited for through the API; verifies go through the CLI (`reads.verified`).
The tests run in order and share the module's twins; the session's close removes any left.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from conformance.harness import Fylgja, Harness
from conformance.reads import (
    BIG,
    BLUEPRINT,
    DEADLINE_S,
    MANY,
    MIXED,
    STEPS,
    TWINS,
    assert_settled_ready,
    assert_twin_record,
    big_blueprint,
    destroyed,
    gone,
    incarnations,
    needs_ceos,
    ready,
    record_nodes,
    remove,
    run_ids,
    runs_since,
    settled,
    twin_nodes,
    verdict_of,
    verified,
    wait_for,
)
from fylgja_core import schemas
from fylgja_core.reconcile import RULE_WAIT_EXPIRED
from fylgja_core.verify import RULE_NODE_UNREAD

STEP_TO = {BLUEPRINT: (STEPS / "three-node-unlinked.json", False), MIXED: (STEPS / "mixed-e2-port.json", True)}
"""By the blueprint a twin is created from, the one it is stepped to and whether the step allows a
restart: the EOS nodes' port is made by recreating them where the driver must."""
CAPACITY = "admission.capacity"
MEMORY = re.compile(r"The twin needs 81920 MiB of memory, and the (cluster|host) has (\d+) MiB free with (\d+) MiB "
                    r"pending\.$")
"""The refusal's memory sentence for `BIG`, whose demand is 81920 MiB, ending the message, whose
sentences are joined by a space: a CPU sentence may come before it, where twenty CPUs exceed the
free room too, and no node sentence after it, since every node fits a host."""
NONE_PENDING = {"nodes": 0, "cpu": 0.0, "memory_mb": 0}
PORTS = frozenset({443, 57400, 6030})
"""A package's push and gNMI ports: SR Linux's JSON-RPC (443) and gNMI (57400), EOS's eAPI (443)
and gNMI (6030)."""
TABLES = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
"""The kernel's TCP tables, IPv4's and IPv6's, which `ss` reads the same sockets of."""
ESTABLISHED = "01"
"""A socket's state in those tables when its connection is established."""
SAMPLE_S = 2.0
SETTLE_EVERY_S = 1.0


@dataclass
class Shared:
    """What the module's tests share, each adding what it read: when the first began, the twins
    with their blueprints, the room before any twin, and every host the twins' nodes ran on."""

    began: float | None = None
    bases: dict[str, Path] | None = None
    before: dict[str, Any] | None = None
    placed: set[str] = field(default_factory=set)


SHARED = Shared()


def bases(harness: Harness) -> dict[str, Path]:
    """Each twin of the scenario, `MANY` and its number, with the blueprint it is created from: the
    odd ones from `three-node`, the even ones from `mixed` where `needs_ceos` does not skip, and
    every one from `three-node` where it would, printed so. Each is one of `TWINS`, which the
    session's close removes, so a count above theirs fails here before any twin is made. Read once."""
    if SHARED.bases is None:
        names = [f"{MANY}{i}" for i in range(1, harness.many() + 1)]
        escaped = sorted(set(names) - set(TWINS))
        assert not escaped, f"{escaped} are not among the suite's twins, which the session's close removes"
        try:
            needs_ceos(harness)
            eos = True
        except pytest.skip.Exception as e:
            print(f"\n[conformance] every twin from {BLUEPRINT.stem}: {e.msg}", flush=True)
            eos = False
        SHARED.bases = {name: MIXED if eos and i % 2 == 0 else BLUEPRINT for i, name in enumerate(names, 1)}
    return SHARED.bases


def free(doc: dict[str, Any]) -> tuple[float, int]:
    """The capacity read's free CPU and memory, summed over its hosts."""
    return sum(h["cpu"]["free"] for h in doc["hosts"]), sum(h["memory_mb"]["free"] for h in doc["hosts"])


def capacity(harness: Harness) -> dict[str, Any]:
    """`GET /v1/capacity`: 200, held to API 1's `Capacity`, and printed in a line, its hosts by
    their count. Failing, it names where the document breaks its schema, never a value."""
    began = time.monotonic()
    answer = harness.client().get("/v1/capacity")
    took = time.monotonic() - began
    assert answer.status_code == 200, f"GET /v1/capacity: {answer.status_code} {answer.text}"
    doc: dict[str, Any] = answer.json()
    broken = [f"{e.json_path} {e.validator}" for e in schemas.api_validator("Capacity").iter_errors(doc)]
    assert not broken, f"the capacity read breaks API 1's Capacity at {broken}"
    cpu, memory_mb = free(doc)
    pending = doc["pending"]
    print(f"[conformance] capacity: {len(doc['hosts'])} hosts, free {cpu:g} CPU {memory_mb} MiB, pending "
          f"{pending['nodes']} nodes {pending['cpu']:g} CPU {pending['memory_mb']} MiB, twins {doc['twins']} "
          f"(read in {took:.2f}s)", flush=True)
    return doc


def established() -> int | None:
    """The host's established TCP connections whose peer port is one of `PORTS`, from the kernel's
    tables, as `ss -Htn state established '( dport = :57400 or dport = :443 or dport = :6030 )'`
    counts them; None where neither table can be read."""
    count, read = 0, 0
    for table in TABLES:
        try:
            lines = table.read_text().splitlines()[1:]
        except OSError:
            continue
        read += 1
        for line in lines:
            fields = line.split()  # sl, local_address, rem_address (hex address:port), st, ...
            if len(fields) > 3 and fields[3] == ESTABLISHED and int(fields[2].rsplit(":", 1)[1], 16) in PORTS:
                count += 1
    return count if read else None


@dataclass
class Connections:
    """`established()` on a thread of its own, once as it is entered, every `SAMPLE_S` after, and
    once as it is left, when its first reading, its maximum and its last are printed, however the
    block ended."""

    what: str
    samples: list[int | None] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def __enter__(self) -> Connections:
        self.samples.append(established())
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def _sample(self) -> None:
        while not self._stop.wait(SAMPLE_S):
            self.samples.append(established())

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self.samples.append(established())
        counts = [n for n in self.samples if n is not None]
        if not counts:
            print(f"[conformance] established connections to ports {sorted(PORTS)} during {self.what}: None, the "
                  "kernel's TCP tables are not readable here", flush=True)
            return
        print(f"[conformance] established connections to ports {sorted(PORTS)} during {self.what}: max "
              f"{max(counts)}, first {counts[0]}, last {counts[-1]}, {len(self.samples)} samples every "
              f"{SAMPLE_S:g}s: {self.samples}", flush=True)


def seconds(run: dict[str, Any], digits: int = 1) -> str:
    """The run's seconds from its request's acceptance to its end, by the core's clock, as a figure
    to print: `None` for a run that has not ended."""
    if "ended_at" not in run:
        return "None"
    took = (datetime.fromisoformat(run["ended_at"]) - datetime.fromisoformat(run["created_at"])).total_seconds()
    return f"{took:.{digits}f}s"


def phases(events: list[dict[str, Any]]) -> str:
    """Each phase of the run's events with its span, from its first event to its last, as a line."""
    spans: dict[str, tuple[datetime, datetime]] = {}
    for e in events:
        at = datetime.fromisoformat(e["at"])
        first, last = spans.get(e["phase"], (at, at))
        spans[e["phase"]] = (min(first, at), max(last, at))
    return ", ".join(f"{p} {(last - first).total_seconds():.1f}s" for p, (first, last) in spans.items())


def settled_by(harness: Harness, twins: list[str], deadline: float, what: str) -> dict[str, float]:
    """Each of `twins` by the moment its record was first read settled, every `SETTLE_EVERY_S`
    until `deadline`; failing, it names those that were not, with each one's newest verdict."""
    at: dict[str, float] = {}
    while True:
        for twin in twins:
            if twin in at:
                continue
            record = harness.record(twin)
            assert record is not None, f"{twin} is gone"
            if settled(record):
                at[twin] = time.monotonic()
        if len(at) == len(twins):
            return at
        left = [t for t in twins if t not in at]
        assert time.monotonic() < deadline, \
            f"{what}: {[(t, verdict_of(harness, t)) for t in left]} not settled in time"
        time.sleep(SETTLE_EVERY_S)


def placement(harness: Harness, twins: list[str], when: str) -> set[str]:
    """Each twin's nodes with the host each runs on, as the harness reads it, printed with the
    count of nodes a host; every host is added to `SHARED.placed`. The hosts named."""
    named: dict[str, int] = {}
    for twin in twins:
        hosts = harness.hosts(twin)
        print(f"[conformance] {twin}'s nodes {when}: {hosts}", flush=True)
        for host in hosts.values():
            named[host] = named.get(host, 0) + 1
    print(f"[conformance] {sum(named.values())} nodes of {len(twins)} twins over {len(named)} hosts {when}: "
          f"{sorted(named.values(), reverse=True)} nodes a host", flush=True)
    SHARED.placed |= set(named)
    return set(named)


def test_the_room_before_any_twin_is_read(harness: Harness) -> None:
    SHARED.began = time.monotonic()
    doc = capacity(harness)
    assert doc["hosts"], "the capacity read names no host"
    assert doc["pending"] == NONE_PENDING, doc["pending"]
    listed = harness.client().get("/v1/twins")
    assert listed.status_code == 200, listed.text
    allocated = sum(1 for record in listed.json()["twins"] if record["status"].get("allocation") is not None)
    print(f"[conformance] the records holding an allocation: {allocated}", flush=True)
    assert doc["twins"] == allocated == 0, (doc["twins"], allocated)
    SHARED.before = doc


def test_n_twins_created_together_all_reach_ready(harness: Harness, fylgja: Fylgja) -> None:
    twins = bases(harness)
    names = list(twins)
    for twin in names:
        assert harness.leftovers(twin) == [], f"the runtime holds {twin} already"
    print(f"\n[conformance] {len(twins)} twins created together: "
          f"{', '.join(f'{t} from {f.stem}' for t, f in twins.items())}", flush=True)
    before = {twin: run_ids(harness, twin) for twin in names}
    asked: dict[str, float] = {}
    with Connections("the creates"):
        began = time.monotonic()
        for twin, fixture in twins.items():
            code, _ = fylgja("twin", "create", twin, "--blueprint", str(fixture), "--no-wait")
            assert code == 0, f"the create of {twin} was not asked"
            asked[twin] = time.monotonic()
        last = time.monotonic()
        print(f"[conformance] {len(twins)} creates asked in {last - began:.1f}s", flush=True)

        # Admitted, or settled having been refused: the reading during counts the twins admitted.
        def admitted() -> bool | None:
            records = [harness.record(twin) for twin in names]
            done = all(r is not None and (r["status"].get("allocation") is not None or settled(r)) for r in records)
            return True if done else None

        wait_for(admitted, "every twin admitted", every_s=0.2)
        unadmitted = [(t, verdict_of(harness, t)) for t in names
                      if (r := harness.record(t)) is None or r["status"].get("allocation") is None]
        assert not unadmitted, f"not admitted: {unadmitted}"
        print(f"[conformance] every twin admitted {time.monotonic() - last:.1f}s after the last ask", flush=True)
        during = capacity(harness)  # its pending printed: how much is still to start is the runtime's moment
        assert during["twins"] == len(twins), during["twins"]
        ready_at = settled_by(harness, names, last + DEADLINE_S * 2, "the creates")
    made = {twin: runs_since(harness, twin, before[twin]) for twin in names}
    for twin, fixture in twins.items():  # every twin's line first, so the first failure hides none of them
        for run in made[twin]:
            verdict = run.get("verdict") or {}
            print(f"[conformance] create {twin} from {fixture.stem}: settled {ready_at[twin] - asked[twin]:.1f}s after "
                  f"its ask; the run {run['operation']} {verdict.get('status')} "
                  f"{[f['rule'] for f in verdict.get('findings', []) if f['severity'] != 'info']} in {seconds(run)}, "
                  f"its phases {phases(harness.events(run['id']))}", flush=True)
    for twin, fixture in twins.items():
        record = harness.record(twin)
        assert record is not None, f"{twin} is gone"
        assert_settled_ready(harness, record, f"{twin} after its create")
        assert_twin_record(record)
        assert sorted(record_nodes(record)) == sorted(twin_nodes(fixture))
        assert harness.nodes(twin) == incarnations(harness, twin), f"the runtime's nodes of {twin} are not the record's"
        ran = [(r["operation"], (r.get("verdict") or {}).get("status")) for r in made[twin]]
        assert ran == [("create", "ok")], f"the create of {twin} made {ran}"
    print(f"[conformance] {len(twins)} twins: the last Ready {max(ready_at.values()) - began:.1f}s after the first "
          "ask", flush=True)
    after = capacity(harness)
    assert after["pending"] == NONE_PENDING, after["pending"]
    assert after["twins"] == len(twins), after["twins"]
    if SHARED.before is not None:
        fell = free(SHARED.before)[1] - free(after)[1]
        print(f"[conformance] the free memory fell by {fell} MiB from the room before any twin", flush=True)
    placement(harness, names, "after the creates")


def test_each_twin_stepped_while_the_others_run_verifies_with_no_node_unread(harness: Harness, fylgja: Fylgja) -> None:
    twins = bases(harness)
    names = list(twins)
    for twin in names:  # every create settled before any step: a step asked on an unsettled twin would wait or refuse
        record = harness.record(twin)
        assert record is not None, f"{twin} is gone"
        assert_settled_ready(harness, record, f"{twin} before its step")
    before = {twin: run_ids(harness, twin) for twin in names}
    runs: dict[str, str] = {}
    asked: dict[str, float] = {}
    with Connections("the steps"):
        began = time.monotonic()
        for twin, base in twins.items():
            to, restart = STEP_TO[base]
            code, _ = fylgja("twin", "step", twin, "--blueprint", str(to), "--no-wait",
                             *(["--allow-restart"] if restart else []))
            assert code == 0, f"the step of {twin} was not asked"
            asked[twin] = time.monotonic()
            made = [(r["id"], r["operation"]) for r in runs_since(harness, twin, before[twin])]
            assert len(made) == 1 and made[0][1] == "step", f"the step of {twin} made {made}, not one step run"
            runs[twin] = made[0][0]
        last = time.monotonic()
        print(f"[conformance] {len(twins)} steps asked in {last - began:.1f}s", flush=True)
        ended_at: dict[str, float] = {}
        while len(ended_at) < len(names):
            for twin in names:
                if twin not in ended_at and harness.run(runs[twin])["state"] == "ended":
                    ended_at[twin] = time.monotonic()
            left = [t for t in names if t not in ended_at]
            assert not left or time.monotonic() < last + DEADLINE_S, \
                f"the steps of {left} did not end within {DEADLINE_S:g}s of the last ask"
            if left:
                time.sleep(SETTLE_EVERY_S)
        verdicts: dict[str, dict[str, Any]] = {}
        for twin, base in twins.items():  # every twin's verdict and timings first, so the first failure hides none
            run = harness.run(runs[twin])
            verdict = verdicts[twin] = run.get("verdict") or {}
            print(f"[conformance] step {twin} to {STEP_TO[base][0].stem}: ended {ended_at[twin] - asked[twin]:.1f}s "
                  f"after its ask, {verdict.get('status')} {sorted({f['rule'] for f in verdict.get('findings', [])})}; "
                  f"the run {seconds(run)}, its phases {phases(harness.events(run['id']))}; wait {verdict.get('wait')}",
                  flush=True)
        print(f"[conformance] {len(twins)} steps: the last ended {max(ended_at.values()) - began:.1f}s after the "
              "first ask", flush=True)
        for twin, verdict in verdicts.items():
            assert verdict, f"the step run of {twin} ended with no verdict"
            rules = sorted({f["rule"] for f in verdict["findings"]})
            assert RULE_NODE_UNREAD not in rules and RULE_WAIT_EXPIRED not in rules, \
                f"the step of {twin}: {verdict['status']} {[(f['rule'], f.get('object')) for f in verdict['findings']]}"
            assert verdict["status"] == "ok", (twin, verdict["status"], rules)
        for twin in names:
            record = harness.record(twin)
            assert record is not None, f"{twin} is gone"
            assert_settled_ready(harness, record, f"{twin} after its step")
        for twin, base in twins.items():
            verified(fylgja, twin, STEP_TO[base][0].stem)
        print(f"[conformance] {len(twins)} steps and verifies: {time.monotonic() - began:.1f}s from the first ask",
              flush=True)
    hosts = placement(harness, names, "after the steps")
    room = capacity(harness)
    offered = {h["name"] for h in room["hosts"]}
    if harness.many() > 1 and len(offered) > 1:
        assert len(hosts) >= 2, f"the {len(names)} twins' nodes run on {len(hosts)} host of the {len(offered)} offered"


def test_a_twin_that_does_not_fit_is_refused_in_a_dry_run_and_at_its_create(
    harness: Harness, fylgja: Fylgja, tmp_path: Path
) -> None:
    assert harness.record(BIG) is None, f"{BIG} is there already"
    big = big_blueprint(tmp_path / "big.json")
    code, out = fylgja("blueprint", "push", str(big), "--json")
    assert code == 0, code
    blueprint_id = json.loads(out)["id"]
    began = time.monotonic()
    answer = harness.client().put(f"/v1/twins/{BIG}", params={"dry_run": "true"}, headers={"If-None-Match": "*"},
                                  json={"spec": {"blueprint_id": blueprint_id}})
    print(f"\n[conformance] a dry run of a create of {BIG}: {answer.status_code} in {time.monotonic() - began:.2f}s",
          flush=True)
    assert answer.status_code == 422, f"a dry run of a create of {BIG}: {answer.status_code} {answer.text}"
    problem = answer.json()
    assert list(schemas.validator("problem-1").iter_errors(problem)) == [], problem
    findings = problem.get("findings", [])
    assert problem["rule"] == CAPACITY and len(findings) == 1, (problem["rule"], findings)
    (finding,) = findings
    print(f"[conformance] the dry run's refusal, {finding['rule']} on {finding.get('object')}: {finding['message']}",
          flush=True)
    assert (finding["rule"], finding.get("object")) == (CAPACITY, BIG), finding
    said = MEMORY.search(finding["message"])
    assert said is not None, finding["message"]
    free_mb, pending_mb = int(said.group(2)), int(said.group(3))
    assert free_mb - pending_mb < 81920, (free_mb, pending_mb)

    room = capacity(harness)
    room_mb = free(room)[1] - room["pending"]["memory_mb"]
    print(f"[conformance] the refusal's free less pending {free_mb - pending_mb} MiB; the capacity read's after it "
          f"{room_mb} MiB, {room_mb - (free_mb - pending_mb):+d} MiB", flush=True)
    assert room_mb < 81920, (free(room)[1], room["pending"]["memory_mb"])
    offered = {h["name"] for h in room["hosts"]}
    assert SHARED.placed, "no host the twins' nodes ran on was read: the module's earlier tests did not run"
    assert offered == SHARED.placed, \
        f"the capacity read offers {len(offered)} hosts, the twins' nodes ran on {len(SHARED.placed)}"

    before = run_ids(harness, BIG)
    began = time.monotonic()
    code, _ = fylgja("twin", "create", BIG, "--blueprint", str(big))
    print(f"[conformance] the create of {BIG}: exit {code} in {time.monotonic() - began:.1f}s", flush=True)
    assert code == 1, code
    (run,) = runs_since(harness, BIG, before)
    verdict = run["verdict"]
    rules = [f["rule"] for f in verdict["findings"]]
    print(f"[conformance] its run: {run['operation']} {verdict['status']} {rules} in {seconds(run, 2)}; "
          f"{[f['message'] for f in verdict['findings']]}", flush=True)
    assert (run["operation"], verdict["status"], rules) == ("create", "rejected", [CAPACITY]), (run["operation"],
                                                                                                verdict)
    record = harness.record(BIG)
    assert record is not None, f"{BIG} is gone"
    is_ready = ready(record)
    assert not is_ready, f"{BIG} is Ready"
    assert harness.leftovers(BIG) == []
    destroyed(harness, fylgja, BIG)


def test_every_twin_is_destroyed_and_nothing_is_left(harness: Harness, fylgja: Fylgja) -> None:
    twins = bases(harness)
    names = list(twins)
    try:
        before = {twin: run_ids(harness, twin) for twin in names}
        began = time.monotonic()
        for twin in names:
            code, _ = fylgja("twin", "destroy", twin, "--no-wait")
            assert code == 0, f"the destroy of {twin} was not asked"
        last = time.monotonic()
        left = names
        while left := [twin for twin in left if not gone(harness, twin)]:
            assert time.monotonic() < last + DEADLINE_S, \
                f"{left} not gone within {DEADLINE_S:g}s of the last destroy asked"
            time.sleep(SETTLE_EVERY_S)
        print(f"[conformance] {len(names)} twins gone {time.monotonic() - began:.1f}s after the first destroy was "
              "asked", flush=True)
        for twin in names:
            assert harness.leftovers(twin) == [], f"the runtime holds {twin}: {harness.leftovers(twin)}"
            made = [(r["operation"], (r.get("verdict") or {}).get("status"), seconds(r))
                    for r in runs_since(harness, twin, before[twin])]
            print(f"[conformance] destroy {twin}: {made}", flush=True)
            assert [m[:2] for m in made] == [("destroy", "ok")], made
        after = capacity(harness)
        assert after["pending"] == NONE_PENDING, after["pending"]
        assert after["twins"] == 0, after["twins"]
        if SHARED.before is not None:
            print(f"[conformance] the free memory {free(after)[1] - free(SHARED.before)[1]:+d} MiB from the room "
                  "before any twin", flush=True)
        if SHARED.began is not None:
            print(f"[conformance] the many-twins scenario: {time.monotonic() - SHARED.began:.1f}s", flush=True)
    finally:
        for twin in names:
            remove(harness, twin)
