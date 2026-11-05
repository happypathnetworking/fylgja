"""Phase 5's done criterion (design/core.md, "Phase 5", plan 6): `fylgja-core twin step` takes
fixture twins to every step fixture from its base (testdata/blueprint/steps/README.md), end to
end through API 1 and the thin CLI on the local containerlab driver. The twin `e2e-step`,
created from `three-node`, takes each SR Linux fixture, on the kind that re-cables live, and
steps back to the base where the next step needs it: a link removed and added back, a port
disabled by intent and enabled again, a node's configuration dropped (unmanaged, D-048) and
given back, a node removed and added back, a probe's two hosts added, moved to `n2` (recreated,
under `allow_restart`, after a dry run through the CLI) and removed, and a step to the bundle
the twin runs. Then its `n3` becomes cEOS, a kind change. The twin `e2e-step-eos`, created
from `mixed`, has a port added to its two cEOS nodes: a recreate (the hot-add, D-049), refused
without the spec's `allow_restart` before anything is touched, and made with it. The twin
`e2e-step-kill`, created from `two-node`, steps to `three-node`, a node added, with the server
killed (SIGKILL) at each phase boundary of the step, 10 s into its deploy, and 5 s into it
before a deletion asked at once: each resume ends the same run `stepped` without a
`--reconfigure` (D-050, D-054), and the deletion removes everything, the node the cut-short
deploy made among it (D-055). The twin `e2e-step-cancel`, created from `two-node`, has its step
to `three-node` cancelled 5 s into the deploy: no rollback (D-029), the twin is left diverged,
refuses a new spec, still answers verify, and is deleted whole.

The cEOS scenarios are skipped, with the reason, when `docker image inspect ceos:4.32.0.2F`
fails: import the image to run them.

Each step's record is read back through the API and held to twin record 1, its run's events
whole and its verdict to findings 1, and the lab read twice over: each container's
`State.StartedAt` through `docker`, which the record's incarnations must equal, and the nodes'
own answers, by a verify through the API once the step has ended (one asked during a step's
wait may find a node's read still held, and answer it unread at once, D-054). The module's last
test holds the server's log to Constitution X: every line JSON, none holding the token or a
password.

The harness is `e2e.py`'s: the server as a subprocess, with its step wait at `STEP_WAIT_S`, the
CLI in-process, the teardown that removes every twin the module made and fails if the host is
left dirty. The tests run in order and share each twin, each starting from what the one before
left; each prints what it took and what it saw (`-s`).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from e2e import (
    BLUEPRINT,
    CLEAN,
    DEADLINE_S,
    NEEDS_LOGINS,
    NODES,
    QUIET_S,
    ROOT,
    SSE,
    STEP_WAIT_S,
    Core,
    Fylgja,
    assert_events_whole,
    assert_log_clean,
    by,
    cli,
    containerlab_processes,
    docker,
    leftovers,
    ready,
    reconfigures,
    serve,
    settled,
    settled_ready,
    started,
    verdict_of,
    wait_for,
)

from fylgja_core import node_http, platform_package, schemas
from fylgja_core.client import messages
from fylgja_core.credentials import Provider
from fylgja_core.push import post

TWIN = "e2e-step"
EOS_TWIN = "e2e-step-eos"
KILL_TWIN = "e2e-step-kill"
CANCEL_TWIN = "e2e-step-cancel"
STEPS = ROOT / "testdata" / "blueprint" / "steps"
PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
MOVED = STEPS / "three-node-probed-moved.json"
UNMANAGED = ROOT / "testdata" / "blueprint" / "three-node-unmanaged.json"
MIXED = ROOT / "testdata" / "blueprint" / "mixed.json"
TWO_NODE = STEPS / "two-node.json"
HOSTS = ("n1-loop-a", "n1-loop-b")
EOS_NODES = ("e1", "e2", "s1")
TWINS = (TWIN, EOS_TWIN, KILL_TWIN, CANCEL_TWIN)
"""Every twin the module makes, for the teardown's last look at the host."""
CEOS = "ceos:4.32.0.2F"
SRLINUX = platform_package.load(ROOT / "psp" / "nokia_srlinux.yaml")
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed", "verified")
"""Each phase boundary of a step a kill follows: before `applied` a step records its phases in
`last_step.phase` alone, from it on in `phase` too (D-054)."""
STEP_PHASES = (*KILL_AT, "flows")
"""A step's phases in order: a resume never starts before the phase a kill followed."""
EOS_WAIT_S = 60.0
"""How long a test waits for EOS's CLI to list a port `connected`, from the step's end."""
ETHERNET10 = "show interfaces Ethernet10 status"
UNCHANGED_S = 2.0
"""A step to the bundle the twin runs ends at `compiled`, touching nothing: within this, end to end."""
VERIFY_TIMEOUT = httpx.Timeout(30.0, read=300.0)

pytestmark = NEEDS_LOGINS


@dataclass(frozen=True)
class Verified:
    """What verify of a fixture's twin answers when it holds: its counts, and the objects of its
    findings, each an info skip (a configured node's host name, reported; a probe endpoint's
    neighbour). A held assertion files no finding, so a link end missing here was asserted and
    held, or not asserted at all, which the held count tells apart."""

    held: int
    skipped: int
    skips: frozenset[str]


DEVICES = frozenset(NODES)
VERIFIED = {
    # 2 links: 4 ports enabled, 4 neighbours, 3 claims; the link n2:ethernet-1/2-n3:ethernet-1/1 is not asserted.
    "three-node-unlinked": Verified(held=11, skipped=3, skips=DEVICES),
    # 3 links: 6 ports, 6 neighbours, 3 claims.
    "three-node": Verified(held=15, skipped=3, skips=DEVICES),
    # three-node's 15, less n1:ethernet-1/2's admin state and its link's two neighbours: intent disables it.
    "three-node-n1-disabled": Verified(held=12, skipped=6,
                                       skips=DEVICES | {"n1:ethernet-1/2", "n3:ethernet-1/2"}),
    # three-node's 15, n2's host name asserted for its reported one, and its claim a skip: it has no configuration.
    "three-node-unmanaged": Verified(held=15, skipped=3, skips=DEVICES),
    # 1 link: 2 ports, 2 neighbours, 2 claims.
    "two-node": Verified(held=6, skipped=2, skips=frozenset({"n1", "n2"})),
    # three-node's 15, the probe's 2 endpoints enabled and its 2 bursts; its endpoints' neighbours are skips.
    "three-node-probed": Verified(held=19, skipped=5,
                                  skips=DEVICES | {"n1:ethernet-1/10", "n1:ethernet-1/11"}),
    # The same probe on n2's ports.
    "three-node-probed-moved": Verified(held=19, skipped=5,
                                        skips=DEVICES | {"n2:ethernet-1/10", "n2:ethernet-1/11"}),
    # n3 as cEOS, its links on Ethernet2 and Ethernet1: three-node's 15, each neighbour judged across kinds.
    "three-node-n3-eos": Verified(held=15, skipped=3, skips=DEVICES),
    # 3 links: 6 ports, 6 neighbours, 3 claims; every node configured, so each host name reported.
    "mixed": Verified(held=15, skipped=3, skips=frozenset(EOS_NODES)),
    # mixed's 15, and the link e1:Ethernet10-e2:Ethernet10: 2 ports, 2 neighbours.
    "mixed-e2-port": Verified(held=19, skipped=3, skips=frozenset(EOS_NODES)),
}


@pytest.fixture(scope="module")
def core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Core]:
    yield from serve(tmp_path_factory, TWINS, (*NODES, *HOSTS, *EOS_NODES))


@pytest.fixture
def fylgja(core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
    return cli(core, monkeypatch, capsys)


# What the tests read.


def step(
    core: Core, fylgja: Fylgja, twin: str, fixture: Path, *, allow_restart: bool = False
) -> tuple[int, dict[str, Any]]:
    """`twin step` of `twin` to the blueprint `fixture`: its exit code, and the record read after."""
    code, _ = fylgja("twin", "step", twin, "--blueprint", str(fixture), *(["--allow-restart"] if allow_restart else []))
    record = core.record(twin)
    assert record is not None, f"{twin} is gone"
    return code, record


def nodes(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["name"]: n for n in record["status"]["nodes"]}


def incarnations(core: Core, twin: str) -> dict[str, str]:
    """Each node's incarnation, from the record: every node has one."""
    record = core.record(twin)
    assert record is not None, f"{twin} is gone"
    found = {name: n.get("incarnation") for name, n in nodes(record).items()}
    assert all(found.values()), f"a node without an incarnation: {found}"
    return {name: str(value) for name, value in found.items()}


def holds(core: Core, twin: str) -> dict[str, str | None]:
    """The bundle each node holds, from the record; None for a probe host, which holds none."""
    record = core.record(twin)
    assert record is not None, f"{twin} is gone"
    return {name: n.get("holds") for name, n in nodes(record).items()}


def verify(core: Core, twin: str) -> dict[str, Any]:
    """`POST /v1/twins/{twin}/verifications`: the verdict, held to findings 1."""
    began = time.monotonic()
    r = core.client().post(f"/v1/twins/{twin}/verifications", timeout=VERIFY_TIMEOUT)
    assert r.status_code == 200, r.text
    doc: dict[str, Any] = r.json()
    assert list(schemas.validator("findings-1").iter_errors(doc)) == [], doc
    print(f"[e2e-step] verify {twin}: {doc['status']} in {time.monotonic() - began:.2f}s, {doc.get('counts')}, "
          f"findings {[(f['rule'], f.get('object')) for f in doc['findings']]}", flush=True)
    return doc


def lab(twin: str) -> dict[str, str]:
    """Each container of the twin's lab by its node name, with its `State.StartedAt`, read from
    `docker`; every one running."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    if not names:
        return {}
    shown = docker("inspect", "--format", '{{index .Config.Labels "clab-node-name"}} {{.State.Running}} '
                   "{{.State.StartedAt}}", *names)
    assert shown.returncode == 0, shown.stderr
    found = {}
    for line in shown.stdout.splitlines():
        name, running, started_at = line.split()
        assert running == "true", f"{name} is not running"
        found[name] = started_at
    return found


def ended(events: list[dict[str, Any]], phase: str) -> dict[str, str]:
    """Each node's ending of `phase`, from the run's per-node events."""
    return {e["node"]: e["outcome"] for e in events
            if e["phase"] == phase and "node" in e and e["outcome"] != "started"}


@dataclass(frozen=True)
class Stepped:
    """One step through the CLI: the twin, its exit code and what it took, the record before and
    after, the run it ran with its events, and the deploys the server logged for it."""

    twin: str
    code: int
    took_s: float
    before: dict[str, Any]
    record: dict[str, Any]
    run: dict[str, Any]
    events: list[dict[str, Any]]
    deploys: list[str]
    reconfigures: int

    @property
    def verdict(self) -> dict[str, Any]:
        verdict: dict[str, Any] = self.run["verdict"]
        return verdict


def stepped(
    core: Core, fylgja: Fylgja, fixture: Path, *, twin: str = TWIN, allow_restart: bool = False,
    ready_before: bool = True,
) -> Stepped:
    """`twin`, settled (and Ready, by `ready_before`), stepped to `fixture` through the CLI; then
    its record, its run and its events read through the API and held to their formats, and the
    step's timings printed."""
    before = core.record(twin)
    assert before is not None and settled(before), f"{twin} is not settled to step"
    assert ready(before) or not ready_before, f"{twin} is not Ready to step"
    since = core.stderr.stat().st_size
    began = time.monotonic()
    code, record = step(core, fylgja, twin, fixture, allow_restart=allow_restart)
    took = time.monotonic() - began
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == [], record
    last = record["status"]["last_step"]
    run = core.run(last["run_id"])
    assert (run["operation"], run["state"]) == ("step", "ended"), run
    assert schemas.api_validator("Run").is_valid(run), run
    assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
    events = core.events(run["id"])
    assert_events_whole(events)
    phases: dict[str, float] = {}
    for e in events:
        if e["outcome"] != "started" and "duration_s" in e:  # a phase's, or each node's in `ready` and `push`, summed
            phases[e["phase"]] = phases.get(e["phase"], 0.0) + e["duration_s"]
    verdict, deploys = run["verdict"], core.deploys(since, twin)
    print(f"[e2e-step] step to {fixture.stem}: exit {code} in {took:.1f}s, {verdict['status']}, last step "
          f"{last['outcome']} at {last['phase']}; phases {', '.join(f'{p} {s:.2f}s' for p, s in phases.items())}; "
          f"wait {verdict.get('wait')}; counts {verdict.get('counts')}; loss {verdict.get('loss')}; "
          f"{len(deploys)} deploy", flush=True)
    return Stepped(twin=twin, code=code, took_s=took, before=before, record=record, run=run, events=events,
                   deploys=deploys, reconfigures=reconfigures(core, since, twin))


def assert_stepped(s: Stepped) -> None:
    """What every step that changes the twin ends with: exit 0 and the run `ok`; `last_step`
    `stepped` at `flows`, from the bundle the twin ran to the one it runs now; Ready True and
    Stepping False for `twin.ready`; the wait settled; one plain deploy; every device node holding
    the new bundle; and the record's incarnations the lab's own."""
    record, verdict = s.record, s.verdict
    status, last = record["status"], record["status"]["last_step"]
    assert s.code == 0 and verdict["status"] == "ok", verdict
    assert [f for f in verdict["findings"] if f["severity"] != "info"] == [], verdict["findings"]
    assert (last["outcome"], last["phase"]) == ("stepped", "flows"), last
    assert last["from"] == s.before["status"]["bundle_id"] != status["bundle_id"] == last["to"]
    assert settled(record) and status["phase"] == "flows"
    conditions = {c["type"]: (c["status"], c.get("reason")) for c in status["conditions"]}
    assert conditions["Ready"] == ("True", "twin.ready") and conditions["Stepping"] == ("False", "twin.ready")
    assert "Diverged" not in conditions or conditions["Diverged"][0] == "False", conditions
    wait = verdict["wait"]
    print(f"[e2e-step] the wait: {wait['outcome']} after {wait['after_s']:.2f}s of {wait['budget_s']}s", flush=True)
    assert (wait["outcome"], wait["budget_s"]) == ("settled", STEP_WAIT_S), wait
    assert verdict["counts"]["failed"] == 0, verdict["counts"]
    assert len(s.deploys) == 1 and s.reconfigures == 0, s.deploys
    held = {name: n.get("holds") for name, n in nodes(record).items() if name not in HOSTS}
    assert held and set(held.values()) == {status["bundle_id"]}, held
    assert lab(s.twin) == {name: n["incarnation"] for name, n in nodes(record).items()}, "the lab is not the record's"


def assert_verified(core: Core, fixture: str, twin: str = TWIN) -> dict[str, Any]:
    """Verify through the API, once the step has ended: `ok`, with `VERIFIED`'s counts and skips."""
    doc = verify(core, twin)
    assert_holds(doc, fixture)
    return doc


def assert_holds(doc: Mapping[str, Any], fixture: str) -> None:
    """A verify verdict on a twin of `fixture`: `ok`, with `VERIFIED`'s counts and skips."""
    expected = VERIFIED[fixture]
    assert doc["status"] == "ok", doc["findings"]
    assert doc["counts"] == {"held": expected.held, "failed": 0, "skipped": expected.skipped}, doc["counts"]
    assert all(f["rule"] == "verify.skipped" and f["severity"] == "info" for f in doc["findings"]), doc["findings"]
    assert {f["object"] for f in doc["findings"]} == expected.skips, doc["findings"]


def needs_ceos() -> None:
    if docker("image", "inspect", CEOS).returncode != 0:
        pytest.skip(f"the cEOS image {CEOS} is not on the host (docker image inspect fails): import it to run "
                    "the cEOS scenarios")


def image(twin: str, node: str) -> str:
    shown = docker("inspect", "--format", "{{.Config.Image}}", f"clab-{twin}-{node}")
    assert shown.returncode == 0, shown.stderr
    return shown.stdout.strip()


def eos(twin: str, node: str, command: str) -> subprocess.CompletedProcess[str]:
    """`command` in EOS's CLI on `node`, through `docker exec` (verified-facts.md: no `-p 15`)."""
    return docker("exec", f"clab-{twin}-{node}", "Cli", "-c", command)


def until_eos(twin: str, node: str, command: str, answered: re.Pattern[str]) -> tuple[str, str, float]:
    """`command` in EOS's CLI on `node` until its status is 0 and its stdout matches `answered`,
    for at most `EOS_WAIT_S`: the first answer's stdout, the last's, and the seconds it took."""
    start = time.monotonic()
    first = answer = eos(twin, node, command)
    while not (answer.returncode == 0 and answered.search(answer.stdout)) and time.monotonic() - start < EOS_WAIT_S:
        time.sleep(2)
        answer = eos(twin, node, command)
    assert answer.returncode == 0 and answered.search(answer.stdout), (answer.returncode, answer.stdout)
    return first.stdout, answer.stdout, time.monotonic() - start


def eos_neighbours(twin: str, node: str) -> dict[str, tuple[str, str]]:
    """Each port's LLDP neighbour as EOS lists it, `show lldp neighbors | json`: its device and its port."""
    shown = eos(twin, node, "show lldp neighbors | json")
    assert shown.returncode == 0, shown.stdout
    entries = json.loads(shown.stdout)["lldpNeighbors"]
    print(f"[e2e-step] {node}'s LLDP neighbours, as EOS lists them: {entries}", flush=True)
    return {e["port"]: (e["neighborDevice"], e["neighborPort"]) for e in entries}


def srlinux_get(address: str, path: str, datastore: str) -> Any:
    """`path` read from SR Linux's `datastore` through its push transport, a JSON-RPC `get`: the
    answer's result."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "get",
            "params": {"commands": [{"path": path, "datastore": datastore}]}}
    credential = Provider(os.environ).login(SRLINUX.credentials)  # its repr hides the password

    async def ask() -> dict[str, Any]:
        async with node_http.client() as client:
            url = node_http.url(address, SRLINUX.push.port, "/jsonrpc")
            return await post(client, url, body, credential, timeout_s=SRLINUX.push.timeout_s)

    answer = asyncio.run(ask())
    assert "error" not in answer, answer
    return answer["result"]


def objects(value: Any) -> Iterator[dict[str, Any]]:
    """Every JSON object within `value`, outermost first."""
    if isinstance(value, dict):
        yield value
        for inner in value.values():
            yield from objects(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from objects(inner)


def srlinux_described(address: str, port: str) -> Any:
    """`port`'s description in SR Linux's running configuration, None when it has none: only a
    pushed configuration sets one, the kind's baseline none."""
    found = srlinux_get(address, f"/interface[name={port}]", "running")
    print(f"[e2e-step] {port} in the running configuration: {found!r:.200}", flush=True)
    return next((o["description"] for o in objects(found) if "description" in o), None)


def srlinux_neighbours(address: str, port: str) -> list[tuple[str, str]]:
    """The LLDP neighbours SR Linux lists on `port`, read from its state through its push
    transport (a JSON-RPC `get`): each one's `system-name` and `port-id`."""
    found = srlinux_get(address, f"/system/lldp/interface[name={port}]/neighbor", "state")
    neighbours = [o for o in objects(found) if "system-name" in o]
    print(f"[e2e-step] {port}'s LLDP neighbours, as SR Linux lists them: "
          f"{[{k: n.get(k) for k in ('system-name', 'port-id', 'port-id-type')} for n in neighbours]}", flush=True)
    return [(str(n["system-name"]), str(n.get("port-id"))) for n in neighbours]


# The twin, and its steps.


def test_the_twin_is_created_from_three_node(core: Core, fylgja: Fylgja) -> None:
    assert leftovers(TWIN, (*NODES, *HOSTS)) == CLEAN, f"the host holds {TWIN} already"
    assert containerlab_processes() == [], "a containerlab process is running"
    began = time.monotonic()
    code, _ = fylgja("twin", "create", TWIN, "--blueprint", str(BLUEPRINT))
    print(f"[e2e-step] create, end to end: {time.monotonic() - began:.1f}s", flush=True)
    assert code == 0
    record = core.record(TWIN)
    assert record is not None and ready(record) and settled(record)
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == []
    assert sorted(nodes(record)) == list(NODES) and lab(TWIN) == incarnations(core, TWIN)
    assert set(holds(core, TWIN).values()) == {record["status"]["bundle_id"]}
    assert_verified(core, "three-node")


def test_a_link_removed_keeps_every_node_and_its_push(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, STEPS / "three-node-unlinked.json")
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert holds(core, TWIN) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    doc = assert_verified(core, "three-node-unlinked")
    removed = {"n2:ethernet-1/2", "n3:ethernet-1/1"}
    assert not [f for f in doc["findings"] if f["object"] in removed], "a finding names the removed link"


def test_a_link_added_keeps_every_node_and_its_push(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, BLUEPRINT)
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert holds(core, TWIN) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    assert_verified(core, "three-node")  # every neighbour, the link's two ends among them, held


def test_a_port_disabled_by_intent_keeps_every_node_and_its_push(core: Core, fylgja: Fylgja) -> None:
    """`three-node-n1-disabled` changes intent alone: `n1`'s configuration is the same, so
    nothing is pushed, and verify asserts neither the port's admin state nor its link's ends."""
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, STEPS / "three-node-n1-disabled.json")
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert holds(core, TWIN) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    doc = assert_verified(core, "three-node-n1-disabled")
    ports = sorted(f["object"] for f in doc["findings"] if ":" in f["object"])
    assert ports == ["n1:ethernet-1/2", "n1:ethernet-1/2", "n3:ethernet-1/2"], doc["findings"]


def test_the_port_enabled_again_keeps_every_node_and_its_push(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, BLUEPRINT)
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    assert_verified(core, "three-node")


def test_a_configuration_dropped_pushes_nothing_and_the_node_keeps_what_it_runs(core: Core, fylgja: Fylgja) -> None:
    """`three-node-unmanaged`: `n2` carries no configuration, so it is unmanaged, and a step from a
    configuration to none pushes nothing (D-048). `n2` keeps the configuration pushed before."""
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, UNMANAGED)
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert holds(core, TWIN) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    # n2's running configuration is the one pushed before, by a line the kind's baseline does not set.
    addresses = {name: n["address"] for name, n in nodes(s.record).items()}
    assert srlinux_described(addresses["n2"], "ethernet-1/1") == "to n1 ethernet-1/1"
    doc = assert_verified(core, "three-node-unmanaged")
    (claim,) = [f for f in doc["findings"] if f["object"] == "n2"]
    assert "carries no configuration" in claim["message"], claim


def test_the_configuration_given_back_is_pushed_to_that_node_alone(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, BLUEPRINT)
    assert_stepped(s)
    assert incarnations(core, TWIN) == kept, "a node was made anew"
    assert ended(s.events, "ready") == {}, "a node was readied"
    assert ended(s.events, "push") == {"n1": "skipped", "n2": "done", "n3": "skipped"}
    assert s.verdict["loss"] == []
    assert_verified(core, "three-node")


def test_a_node_removed_is_gone_from_the_record_and_the_lab(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, STEPS / "two-node.json")
    assert_stepped(s)
    assert sorted(nodes(s.record)) == ["n1", "n2"]
    assert sorted(lab(TWIN)) == ["n1", "n2"], "n3's container is left"
    assert docker("ps", "-a", "--filter", "name=clab-e2e-step-n3", "--format", "{{.Names}}").stdout.split() == []
    assert incarnations(core, TWIN) == {n: kept[n] for n in ("n1", "n2")}, "a node was made anew"
    assert ended(s.events, "ready") == {}
    assert ended(s.events, "push") == {"n1": "skipped", "n2": "skipped"}
    assert s.verdict["loss"] == []
    assert_verified(core, "two-node")


def test_a_node_added_is_readied_and_pushed_alone(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, BLUEPRINT)
    assert_stepped(s)
    print(f"[e2e-step] the node added: the step took {s.took_s:.1f}s end to end", flush=True)
    now = incarnations(core, TWIN)
    assert sorted(now) == list(NODES) and {n: now[n] for n in ("n1", "n2")} == kept, "a node was made anew"
    assert ended(s.events, "ready") == {"n3": "done"}
    assert ended(s.events, "push") == {"n1": "skipped", "n2": "skipped", "n3": "done"}
    assert holds(core, TWIN) == dict.fromkeys(NODES, s.record["status"]["bundle_id"])
    assert s.verdict["loss"] == []
    assert_verified(core, "three-node")


def test_a_probe_added_readies_its_hosts_and_its_bursts_hold(core: Core, fylgja: Fylgja) -> None:
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, PROBED)
    assert_stepped(s)
    now = incarnations(core, TWIN)
    assert sorted(now) == sorted((*NODES, *HOSTS)) and {n: now[n] for n in NODES} == kept, "a node was made anew"
    assert ended(s.events, "ready") == dict.fromkeys(HOSTS, "done")
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    bundle_id = s.record["status"]["bundle_id"]
    assert holds(core, TWIN) == {**dict.fromkeys(NODES, bundle_id), **dict.fromkeys(HOSTS)}
    assert s.verdict["loss"] == [{"probe": "n1-loop", "from": "a", "outcome": "not_started"},
                                 {"probe": "n1-loop", "from": "b", "outcome": "not_started"}]
    assert s.verdict["counts"] == {"held": 19, "failed": 0, "skipped": 5}, "the wait's verify, bursts and all"
    assert_verified(core, "three-node-probed")  # both bursts held: no verify.burst finding
    # The same through the CLI, which exits by the verdict.
    code, out = fylgja("twin", "verify", TWIN, "--json")
    answer = json.loads(out)
    print(f"[e2e-step] twin verify {TWIN}: exit {code}, {answer['status']} {answer.get('counts')}", flush=True)
    assert code == 0 and list(schemas.validator("findings-1").iter_errors(answer)) == [], answer
    assert_holds(answer, "three-node-probed")


def test_a_step_to_the_bundle_the_twin_runs_is_unchanged(core: Core, fylgja: Fylgja) -> None:
    before = core.record(TWIN)
    assert before is not None and ready(before)
    bundle_id, kept = before["status"]["bundle_id"], incarnations(core, TWIN)
    since = core.stderr.stat().st_size
    began = time.monotonic()
    code, _ = fylgja("twin", "step", TWIN, "--bundle", bundle_id)
    took = time.monotonic() - began
    record = core.record(TWIN)
    assert record is not None
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == []
    last, run = record["status"]["last_step"], core.run(record["status"]["last_step"]["run_id"])
    events = core.events(run["id"])
    assert_events_whole(events)
    print(f"[e2e-step] a step to the bundle it runs: exit {code} in {took:.2f}s, last step {last['outcome']} at "
          f"{last['phase']}; the run's phases {sorted({e['phase'] for e in events})}", flush=True)
    assert code == 0 and took < UNCHANGED_S
    assert (last["outcome"], last["phase"], last["from"], last["to"]) == ("unchanged", "compiled", bundle_id, bundle_id)
    assert run["operation"] == "step" and run["verdict"]["status"] == "ok", run["verdict"]
    assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == []
    assert ready(record) and settled(record) and record["status"]["bundle_id"] == bundle_id
    assert {e["phase"] for e in events} == {"compile"}
    assert core.deploys(since, TWIN) == [] and incarnations(core, TWIN) == kept


def test_a_dry_run_of_the_probe_moved_answers_its_changes_and_touches_nothing(core: Core, fylgja: Fylgja) -> None:
    """`twin step --dry-run` writes no spec and deploys nothing: its plan's `changes` are what the
    step would do to each node and link, the probe's hosts recreated for their new `exec` lines,
    and its verdict the refusal the step would meet without `allow_restart`, exited by."""
    before = core.record(TWIN)
    assert before is not None
    kept, since = incarnations(core, TWIN), core.stderr.stat().st_size
    code, out = fylgja("twin", "step", TWIN, "--blueprint", str(MOVED), "--dry-run", "--json")
    plan = json.loads(out)
    verdict, changes = plan["verdict"], plan.get("changes")
    print(f"[e2e-step] a dry run to {MOVED.stem}: exit {code}, {verdict['status']} "
          f"{[(f['rule'], f.get('object')) for f in verdict['findings']]}, changes {changes}", flush=True)
    assert schemas.api_validator("Plan").is_valid(plan), plan
    assert code == 1 and verdict["status"] == "rejected", verdict
    errors = sorted((f["rule"], f.get("object")) for f in verdict["findings"] if f["severity"] == "error")
    assert errors == [("step.restart.required", host) for host in HOSTS], verdict["findings"]
    assert changes is not None
    assert {c["node"]: (c["action"], c["reasons"]) for c in changes["nodes"]} == {
        "n1": ("recabled", ["links"]), "n2": ("recabled", ["links"]), "n3": ("kept", []),
        "n1-loop-a": ("recreated", ["exec", "links"]), "n1-loop-b": ("recreated", ["exec", "links"])}
    assert changes["links_added"] == [["n1-loop-a:eth1", "n2:ethernet-1/10"], ["n1-loop-b:eth1", "n2:ethernet-1/11"]]
    assert changes["links_removed"] == [["n1-loop-a:eth1", "n1:ethernet-1/10"], ["n1-loop-b:eth1", "n1:ethernet-1/11"]]
    after = core.record(TWIN)
    assert after is not None and (after["generation"], after["spec"]) == (before["generation"], before["spec"])
    assert core.deploys(since, TWIN) == [] and lab(TWIN) == kept == incarnations(core, TWIN), "the lab was touched"


def test_a_probe_moved_recreates_its_hosts_alone_and_its_bursts_hold(core: Core, fylgja: Fylgja) -> None:
    """With `allow_restart`, which the hosts' recreate needs."""
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, MOVED, allow_restart=True)
    assert_stepped(s)
    now = incarnations(core, TWIN)
    assert sorted(now) == sorted((*NODES, *HOSTS)) and {n: now[n] for n in NODES} == {n: kept[n] for n in NODES}, \
        "a device node was made anew"
    assert all(now[h] != kept[h] for h in HOSTS), "a probe host kept its incarnation through its exec change"
    assert ended(s.events, "ready") == dict.fromkeys(HOSTS, "done")
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    bundle_id = s.record["status"]["bundle_id"]
    assert holds(core, TWIN) == {**dict.fromkeys(NODES, bundle_id), **dict.fromkeys(HOSTS)}
    assert s.verdict["loss"] == [{"probe": "n1-loop", "from": "a", "outcome": "not_started"},
                                 {"probe": "n1-loop", "from": "b", "outcome": "not_started"}]
    assert s.verdict["counts"] == {"held": 19, "failed": 0, "skipped": 5}, "the wait's verify, bursts and all"
    assert_verified(core, "three-node-probed-moved")  # both bursts held, from the hosts' new addresses


def test_a_probe_removed_takes_its_hosts_away(core: Core, fylgja: Fylgja) -> None:
    """From `n2`, back to `three-node`, the base the kind change steps from."""
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, BLUEPRINT)
    assert_stepped(s)
    assert sorted(nodes(s.record)) == list(NODES) and sorted(lab(TWIN)) == list(NODES), "a probe host is left"
    assert incarnations(core, TWIN) == {n: kept[n] for n in NODES}, "a node was made anew"
    assert ended(s.events, "ready") == {}
    assert ended(s.events, "push") == dict.fromkeys(NODES, "skipped")
    assert s.verdict["loss"] == []
    assert_verified(core, "three-node")


def test_a_kind_change_recreates_n3_as_ceos_and_its_neighbours_hold_across_kinds(
    core: Core, fylgja: Fylgja
) -> None:
    needs_ceos()
    kept = incarnations(core, TWIN)
    s = stepped(core, fylgja, STEPS / "three-node-n3-eos.json", allow_restart=True)
    assert_stepped(s)
    print(f"[e2e-step] the kind change: the step took {s.took_s:.1f}s end to end", flush=True)
    now = incarnations(core, TWIN)
    assert {n: now[n] for n in ("n1", "n2")} == {n: kept[n] for n in ("n1", "n2")}, "an SR Linux node was made anew"
    assert now["n3"] != kept["n3"] and image(TWIN, "n3") == CEOS, "n3 is not a new cEOS node"
    assert ended(s.events, "ready") == {"n3": "done"}
    assert ended(s.events, "push") == {"n1": "skipped", "n2": "skipped", "n3": "done"}
    assert s.verdict["loss"] == []
    doc = assert_verified(core, "three-node-n3-eos")
    (reported,) = [f for f in doc["findings"] if f["object"] == "n3"]
    assert "reports its host name as n3;" in reported["message"], reported
    # The two links' neighbours, which verify held, as each end lists them.
    addresses = {name: n["address"] for name, n in nodes(s.record).items()}
    assert srlinux_neighbours(addresses["n1"], "ethernet-1/2") == [("n3", "Ethernet2")]
    assert srlinux_neighbours(addresses["n2"], "ethernet-1/2") == [("n3", "Ethernet1")]
    listed = {port: far for port, far in eos_neighbours(TWIN, "n3").items() if port.startswith("Ethernet")}
    assert listed == {"Ethernet1": ("n2", "ethernet-1/2"), "Ethernet2": ("n1", "ethernet-1/2")}, listed


def test_the_twin_is_destroyed_and_nothing_is_left(core: Core, fylgja: Fylgja) -> None:
    code, out = fylgja("twin", "destroy", TWIN)
    assert code == 0 and f"twin {TWIN} deleted" in out
    assert core.record(TWIN) is None
    assert leftovers(TWIN, (*NODES, *HOSTS)) == CLEAN
    assert not [line for line in Path("/etc/hosts").read_text().splitlines()
                if f"clab-{TWIN}-" in line and not any(f"clab-{t}-" in line for t in TWINS if t != TWIN)]
    assert containerlab_processes() == [], "a containerlab process is left"
    destroy = core.runs(TWIN)[0]
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")


# The cEOS twin: a port added, refused without `allow_restart` and made with it.


def test_the_ceos_twin_is_created_from_mixed(core: Core, fylgja: Fylgja) -> None:
    needs_ceos()
    assert leftovers(EOS_TWIN, EOS_NODES) == CLEAN, f"the host holds {EOS_TWIN} already"
    began = time.monotonic()
    code, _ = fylgja("twin", "create", EOS_TWIN, "--blueprint", str(MIXED))
    print(f"[e2e-step] create {EOS_TWIN}, end to end: {time.monotonic() - began:.1f}s", flush=True)
    assert code == 0
    record = core.record(EOS_TWIN)
    assert record is not None and ready(record) and settled(record)
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == []
    assert sorted(nodes(record)) == sorted(EOS_NODES) and lab(EOS_TWIN) == incarnations(core, EOS_TWIN)
    absent = eos(EOS_TWIN, "e2", ETHERNET10)
    print(f"[e2e-step] e2, before the step, {ETHERNET10!r}: status {absent.returncode}, {absent.stdout!r}",
          flush=True)
    assert not re.search(r"^Et10\s", absent.stdout, re.MULTILINE), "e2 lists Et10 before the step"
    assert_verified(core, "mixed", EOS_TWIN)


def test_a_ceos_port_added_without_allow_restart_is_refused_before_anything_is_touched(
    core: Core, fylgja: Fylgja
) -> None:
    needs_ceos()
    kept, held = lab(EOS_TWIN), holds(core, EOS_TWIN)
    s = stepped(core, fylgja, STEPS / "mixed-e2-port.json", twin=EOS_TWIN)
    status, before, verdict = s.record["status"], s.before["status"], s.verdict
    last = status["last_step"]
    assert s.code == 1 and verdict["status"] == "rejected", verdict
    errors = sorted((f["rule"], f.get("object")) for f in verdict["findings"] if f["severity"] == "error")
    assert errors == [("step.restart.required", "e1"), ("step.restart.required", "e2")], verdict["findings"]
    conditions = {c["type"]: (c["status"], c.get("reason")) for c in status["conditions"]}
    assert conditions["Ready"] == ("False", "step.restart.required"), conditions
    assert conditions["Stepping"] == ("False", "step.restart.required"), conditions
    assert "Diverged" not in conditions or conditions["Diverged"][0] == "False", conditions
    # Refused at `planned`, after `plan done`: the twin runs what it ran, its phase too.
    assert (last["outcome"], last["phase"], last["from"]) == ("rejected", "planned", before["bundle_id"]), last
    assert last["to"] != last["from"] and settled(s.record)
    assert [status.get(k) for k in ("bundle_id", "blueprint_id", "deployment_id", "phase")] == [
        before.get(k) for k in ("bundle_id", "blueprint_id", "deployment_id", "phase")]
    assert {e["phase"] for e in s.events} == {"compile", "admit", "plan"}, "a phase past the plan ran"
    assert s.deploys == [] and lab(EOS_TWIN) == kept, "the lab was touched"
    assert incarnations(core, EOS_TWIN) == kept and holds(core, EOS_TWIN) == held


def test_a_ceos_port_added_with_allow_restart_recreates_both_nodes_with_it(core: Core, fylgja: Fylgja) -> None:
    needs_ceos()
    kept = incarnations(core, EOS_TWIN)
    s = stepped(core, fylgja, STEPS / "mixed-e2-port.json", twin=EOS_TWIN, allow_restart=True,
                ready_before=False)  # the refusal before it left Ready False
    assert_stepped(s)
    print(f"[e2e-step] the cEOS restart: the step took {s.took_s:.1f}s end to end", flush=True)
    now = incarnations(core, EOS_TWIN)
    assert now["s1"] == kept["s1"], "s1 was made anew"
    assert now["e1"] != kept["e1"] and now["e2"] != kept["e2"], "a cEOS node was not made anew"
    assert ended(s.events, "ready") == {"e1": "done", "e2": "done"}
    assert ended(s.events, "push") == {"e1": "done", "e2": "done", "s1": "skipped"}
    assert s.verdict["loss"] == []
    connected = re.compile(r"^Et10\s+connected\s", re.MULTILINE)
    for node in ("e1", "e2"):
        first, last, took = until_eos(EOS_TWIN, node, ETHERNET10, connected)
        print(f"[e2e-step] {node}'s {ETHERNET10!r} after the step, first: {first!r}; connected in {took:.1f}s: "
              f"{last!r}", flush=True)
    assert_verified(core, "mixed-e2-port", EOS_TWIN)


def test_the_ceos_twin_is_destroyed_and_nothing_is_left(core: Core, fylgja: Fylgja) -> None:
    needs_ceos()
    code, out = fylgja("twin", "destroy", EOS_TWIN)
    assert code == 0 and f"twin {EOS_TWIN} deleted" in out
    assert core.record(EOS_TWIN) is None
    assert leftovers(EOS_TWIN, EOS_NODES) == CLEAN
    assert not [line for line in Path("/etc/hosts").read_text().splitlines() if f"clab-{EOS_TWIN}-" in line]
    assert containerlab_processes() == [], "a containerlab process is left"
    destroy = core.runs(EOS_TWIN)[0]
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")


# A server killed at each phase boundary of a step, during its deploy, and a deletion after one.


def stepped_until(core: Core, fylgja: Fylgja, twin: str, fixture: Path, phase: str) -> dict[str, Any]:
    """Step `twin` to `fixture` (`--no-wait`) with a watch of every twin already open, so no
    write is missed, and answer its record as the loop records `phase` for the step: while
    `last_step` is `running`, its `phase`, where a step's phases before `applied` are recorded
    alone (D-054). A step that ends first fails the test."""
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    with core.client().stream("GET", "/v1/twins", params={"watch": "true"}, headers={"Accept": SSE},
                              timeout=timeout) as stream:
        assert stream.status_code == 200
        before = core.record(twin)
        assert before is not None and settled(before)
        asked = before["generation"] + 1  # the generation the step's spec is written at
        code, _ = fylgja("twin", "step", twin, "--blueprint", str(fixture), "--no-wait")
        assert code == 0
        for message in messages(by(deadline, stream.iter_lines(), f"{twin}'s step did not reach {phase}")):
            record: dict[str, Any] = json.loads(message.data)["object"]
            if record["name"] != twin or record["generation"] < asked:  # the watch's first look, before the spec
                continue
            last = record["status"].get("last_step")
            if last is not None and last["outcome"] == "running" and last["phase"] == phase:
                return record
            if settled(record):
                pytest.fail(f"{twin}'s step ended before {phase}: Ready {ready(record)}, {verdict_of(core, twin)}")
    pytest.fail(f"the watch ended before {twin}'s step reached {phase}")


def logged(core: Core, since: int) -> list[dict[str, Any]]:
    """The server's log lines after byte `since`, each a JSON object."""
    with core.stderr.open("rb") as f:
        f.seek(since)
        return [json.loads(line) for line in f.read().decode(errors="replace").splitlines() if line.strip()]


def stray_wait(core: Core, since: int, twin: str) -> float | None:
    """The seconds the driver waited on a stray deploy of `twin` after byte `since`: from its
    line saying it waits to the deploy that followed; None when it never waited."""
    lines = logged(core, since)
    waits = [i for i, line in enumerate(lines)
             if "a stray deploy" in line["message"] and f" {twin}:" in line["message"]]
    if not waits:
        return None
    after = next((line for line in lines[waits[0]:]
                  if "containerlab deploy" in line["message"] and f"/{twin}/" in line["message"]), None)
    assert after is not None, f"the driver logged a wait on a stray deploy of {twin}, and no deploy after it"
    began, ended = (datetime.fromisoformat(line["time"]) for line in (lines[waits[0]], after))
    return (ended - began).total_seconds()


def resumed_after(core: Core, since: int, run_id: str) -> str | None:
    """The phase the server's log says the step run `run_id` resumed after, after byte `since`;
    None when no pass resumed it."""
    for line in logged(core, since):
        found = re.search(rf"step run {run_id} resumed after (\w+)$", line["message"])
        if found:
            return found.group(1)
    return None


def outlived(pids: list[int], killed: float) -> float | None:
    """How long the `containerlab` processes `pids`, found running at the kill at `killed`, ran on
    after it; None when there were none."""
    if not pids:
        return None
    ended = wait_for(lambda: None if any(Path(f"/proc/{pid}").exists() for pid in pids) else time.monotonic(),
                     "the stray deploy's end", timeout_s=300, every_s=0.1)
    return ended - killed


def started_after(record: Mapping[str, Any], node: str, killed_at: datetime) -> float:
    """Seconds from the kill at `killed_at` (wall clock) to the node's `State.StartedAt`."""
    incarnation = re.sub(r"(\.\d{6})\d+", r"\1", nodes(record)[node]["incarnation"])
    return (datetime.fromisoformat(incarnation) - killed_at).total_seconds()


def kill_base(core: Core, fylgja: Fylgja) -> None:
    """`KILL_TWIN` Ready on `two-node`: created from it when it is absent, stepped back to it when
    it runs another bundle, and created anew when an earlier scenario left it unready."""
    record = core.record(KILL_TWIN)
    if record is not None and not (ready(record) and settled(record)):
        print(f"[e2e-step] {KILL_TWIN} is left unready ({verdict_of(core, KILL_TWIN)}): made anew", flush=True)
        code, _ = fylgja("twin", "destroy", KILL_TWIN)
        assert code == 0
        record = None
    if record is None:
        assert leftovers(KILL_TWIN, NODES) == CLEAN, f"the host holds {KILL_TWIN} already"
        code, _ = fylgja("twin", "create", KILL_TWIN, "--blueprint", str(TWO_NODE))
        assert code == 0
        record = core.record(KILL_TWIN)
        assert record is not None and ready(record)
    if sorted(nodes(record)) != ["n1", "n2"]:
        assert_stepped(stepped(core, fylgja, TWO_NODE, twin=KILL_TWIN))
    assert sorted(lab(KILL_TWIN)) == ["n1", "n2"]


def assert_resumed(core: Core, run_id: str, since: int, record: dict[str, Any]) -> list[dict[str, Any]]:
    """What a resumed step ends with: the same step run, the only one since `since`, ended `ok`,
    its wait settled (a run resumed after its wait carries none, D-054); its record `stepped`, `n3`
    added and holding the bundle; one lab, of the three nodes; no `--reconfigure`; verify `ok`.
    Its events."""
    steps = [r for r in core.runs(KILL_TWIN) if r["operation"] == "step"]  # newest first
    assert steps[0]["id"] == run_id, "the resume made a second step run"
    assert steps[0]["state"] == "ended" and steps[0]["verdict"]["status"] == "ok", steps[0].get("verdict")
    assert list(schemas.validator("findings-1").iter_errors(steps[0]["verdict"])) == []
    wait = steps[0]["verdict"].get("wait")
    if wait is None:
        assert resumed_after(core, since, run_id) in ("verified", "flows"), "a step that waited carries no wait"
    else:
        assert wait["outcome"] == "settled", wait
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == []
    last = record["status"]["last_step"]
    assert (last["outcome"], last["phase"], last["run_id"]) == ("stepped", "flows", run_id), last
    assert sorted(nodes(record)) == list(NODES) and sorted(lab(KILL_TWIN)) == list(NODES), "not one lab of three"
    assert lab(KILL_TWIN) == {name: n["incarnation"] for name, n in nodes(record).items()}
    assert holds(core, KILL_TWIN) == dict.fromkeys(NODES, record["status"]["bundle_id"])
    assert reconfigures(core, since, KILL_TWIN) == 0, "a --reconfigure deploy"
    events = core.events(run_id)
    assert_events_whole(events)
    assert sum(1 for e in events if e["phase"] == "apply" and e["outcome"] == "done") == 1
    assert_verified(core, "three-node", KILL_TWIN)
    return events


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_server_killed_at_a_step_phase_resumes_the_same_run_to_stepped(
    core: Core, fylgja: Fylgja, phase: str
) -> None:
    kill_base(core, fylgja)
    since = core.stderr.stat().st_size
    began = time.monotonic()
    seen = stepped_until(core, fylgja, KILL_TWIN, BLUEPRINT, phase)
    strays, killed, killed_at = containerlab_processes(f"/{KILL_TWIN}/"), time.monotonic(), datetime.now(UTC)
    core.restart()  # the kill follows the phase's record at once
    after = core.record(KILL_TWIN)
    assert after is not None
    run_id = seen["status"]["last_step"]["run_id"]
    print(f"[e2e-step] killed at {phase}, {killed - began:.1f}s into the step; after the restart the record read "
          f"phase {after['status'].get('phase')}, last step {after['status']['last_step']['outcome']} at "
          f"{after['status']['last_step']['phase']}", flush=True)
    ran_on = outlived(strays, killed)
    record = settled_ready(core, KILL_TWIN)
    resumed = time.monotonic() - killed
    events = assert_resumed(core, run_id, since, record)
    applies, deployed = started(events, "apply"), core.deploys(since, KILL_TWIN)
    waited, point = stray_wait(core, since, KILL_TWIN), resumed_after(core, since, run_id)
    print(f"[e2e-step] killed at {phase}: resumed after {point or 'nothing (the run had ended)'}, stepped "
          f"{resumed:.1f}s after the kill ({time.monotonic() - began:.1f}s after "
          f"the step), the same run {run_id}; {applies} apply started, {len(deployed)} deploy; a deploy running at "
          f"the kill: {'none' if ran_on is None else f'ran on {ran_on:.1f}s'}; the driver waited for it "
          f"{'no' if waited is None else f'{waited:.1f}s'}; n3 started {started_after(record, 'n3', killed_at):+.1f}s "
          "from the kill", flush=True)
    # A resume never starts before the phase the kill followed: the record moved first.
    assert point is None or STEP_PHASES.index(point) >= STEP_PHASES.index(phase), point
    if KILL_AT.index(phase) >= KILL_AT.index("applied"):
        # The apply ended before the kill: nothing is applied again.
        assert applies == 1 and len(deployed) == 1 and waited is None, (applies, deployed)
    else:
        # Before `applied` the kill may land before the apply began (one apply, one deploy), or in
        # it: the resume probes and applies again plainly, the driver first waiting for a stray
        # deploy still running then. The stray runs to completion (D-056), about as long as the
        # step's whole deploy, and in the runs recorded it had ended before the resume reached
        # its apply (verified-facts.md).
        assert 1 <= applies <= 2 and 1 <= len(deployed) <= applies, (applies, deployed)
        assert waited is None or (applies, len(deployed)) == (2, 2), (applies, deployed, waited)


def test_a_server_killed_during_a_step_deploy_resumes_the_same_run_to_stepped(core: Core, fylgja: Fylgja) -> None:
    """Killed 10 s into the step's deploy, which runs on in a session of its own to completion,
    its output in a file (D-056): the resume probes the lab and applies again plainly, the driver
    first waiting for the stray deploy if it still runs."""
    kill_base(core, fylgja)
    since = core.stderr.stat().st_size
    code, _ = fylgja("twin", "step", KILL_TWIN, "--blueprint", str(BLUEPRINT), "--no-wait")
    assert code == 0
    wait_for(lambda: True if core.deploys(since, KILL_TWIN) else None, "the step's deploy", every_s=0.1)
    deploying = time.monotonic()
    time.sleep(10)
    assert containerlab_processes(f"/{KILL_TWIN}/"), "the deploy ended within 10 s"
    stepping = core.record(KILL_TWIN)
    assert stepping is not None
    run_id = stepping["status"]["last_step"]["run_id"]
    strays, killed, killed_at = containerlab_processes(f"/{KILL_TWIN}/"), time.monotonic(), datetime.now(UTC)
    core.restart()
    ran_on = outlived(strays, killed)
    assert ran_on is not None
    record = settled_ready(core, KILL_TWIN)
    resumed = time.monotonic() - killed
    events = assert_resumed(core, run_id, since, record)
    applies, deployed = started(events, "apply"), core.deploys(since, KILL_TWIN)
    waited = stray_wait(core, since, KILL_TWIN)
    print(f"[e2e-step] killed {killed - deploying:.1f}s into the step's deploy: stepped {resumed:.1f}s after the kill; "
          f"{applies} apply started, {len(deployed)} deploy; the deploy ran on {ran_on:.1f}s after the kill; the "
          f"driver waited for it {'no' if waited is None else f'{waited:.1f}s'}; n3 started "
          f"{started_after(record, 'n3', killed_at):+.1f}s from the kill", flush=True)
    # The resume probes the lab and applies again plainly, after the stray deploy has ended: the
    # driver waits for it when it is still running then, which the probe's readiness wait may outlast.
    assert applies == 2 and len(deployed) == 2, (applies, deployed)


def test_a_deletion_right_after_a_kill_during_a_step_deploy_leaves_nothing(core: Core, fylgja: Fylgja) -> None:
    """The twin's deletion asked at once after a server killed 5 s into a step's deploy, which
    runs on: the step is cancelled (diverged, its apply begun), and the destroy removes the lab,
    the node the cut-short deploy adds among it."""
    kill_base(core, fylgja)
    since = core.stderr.stat().st_size
    code, _ = fylgja("twin", "step", KILL_TWIN, "--blueprint", str(BLUEPRINT), "--no-wait")
    assert code == 0
    wait_for(lambda: True if core.deploys(since, KILL_TWIN) else None, "the step's deploy", every_s=0.1)
    time.sleep(5)
    strays = containerlab_processes(f"/{KILL_TWIN}/")
    assert strays, "the deploy ended within 5 s"
    killed = time.monotonic()
    core.restart()
    running = bool(containerlab_processes(f"/{KILL_TWIN}/"))
    began = time.monotonic()
    code, out = fylgja("twin", "destroy", KILL_TWIN)
    ran_on = outlived(strays, killed)
    assert ran_on is not None
    asked = began - killed
    print(f"[e2e-step] deleted {asked:.1f}s after a kill 5s into the step's deploy, the deploy "
          f"{'still' if running else 'no longer'} running: gone {time.monotonic() - began:.1f}s after it was asked; "
          f"the deploy ran on {ran_on:.1f}s after the kill", flush=True)
    lines = logged(core, since)
    for line in lines:
        if KILL_TWIN in line["message"] and any(k in line["message"] for k in ("stray", "destroy", "deploy",
                                                                                 "removed")):
            print(f"[e2e-step]   {line['time'][11:23]} {line['message'][:160]}", flush=True)
    assert code == 0 and f"twin {KILL_TWIN} deleted" in out
    assert core.record(KILL_TWIN) is None
    destroy, step_run = (next(r for r in core.runs(KILL_TWIN) if r["operation"] == op) for op in ("destroy", "step"))
    assert "verdict" in destroy and "verdict" in step_run, (destroy, step_run)
    for run in (destroy, step_run):
        assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
        assert_events_whole(core.events(run["id"]))
    print(f"[e2e-step] the step run: {step_run['verdict']['status']} "
          f"{[(f['rule'], f.get('object')) for f in step_run['verdict']['findings']]}; the destroy run: "
          f"{destroy['verdict']['status']}", flush=True)
    assert (destroy["verdict"]["status"], step_run["verdict"]["status"]) == ("ok", "diverged")
    # D-055 in the server's log: the destroy waited for the deploy still running when it began,
    # then removed n3, which the two-node deployment it destroyed does not name, before containerlab's destroy.
    said = [line["message"] for line in lines]
    waited = next((i for i, m in enumerate(said) if m.startswith(f"destroy {KILL_TWIN}: a stray deploy")), None)
    removed = next((i for i, m in enumerate(said) if m.startswith(f"destroy {KILL_TWIN}: removed n3,")), None)
    destroyed = next((i for i, m in enumerate(said) if m.startswith("containerlab destroy") and f"/{KILL_TWIN}/" in m),
                     None)
    if ran_on > asked + 5.0:  # the deploy ran on well past the deletion's ask, so the destroy found it running
        assert waited is not None, "the destroy did not wait for the stray deploy"
    assert removed is not None and destroyed is not None and removed < destroyed, (removed, destroyed)
    assert waited is None or waited < removed
    wait_for(lambda: None if containerlab_processes(f"/{KILL_TWIN}/") else True, "the stray deploy's end",
             timeout_s=120)
    assert leftovers(KILL_TWIN, NODES) == CLEAN, "the stray deploy left the twin on the host"
    assert containerlab_processes() == [], "a containerlab process is left"


# A step cancelled during its apply: diverged, and then deleted whole.


def test_a_step_cancelled_during_its_apply_ends_diverged_and_the_twin_is_then_deleted_whole(
    core: Core, fylgja: Fylgja
) -> None:
    assert leftovers(CANCEL_TWIN, NODES) == CLEAN, f"the host holds {CANCEL_TWIN} already"
    code, _ = fylgja("twin", "create", CANCEL_TWIN, "--blueprint", str(TWO_NODE))
    assert code == 0
    before = core.record(CANCEL_TWIN)
    assert before is not None and ready(before)
    since = core.stderr.stat().st_size
    code, _ = fylgja("twin", "step", CANCEL_TWIN, "--blueprint", str(BLUEPRINT), "--no-wait")
    assert code == 0
    wait_for(lambda: True if core.deploys(since, CANCEL_TWIN) else None, "the step's deploy", every_s=0.1)
    time.sleep(5)
    assert containerlab_processes(f"/{CANCEL_TWIN}/"), "the deploy ended within 5 s"
    stepping = core.record(CANCEL_TWIN)
    assert stepping is not None
    run_id = stepping["status"]["last_step"]["run_id"]

    began = time.monotonic()
    asked = core.client().post(f"/v1/runs/{run_id}/cancel")
    assert asked.status_code == 202, asked.text

    def ended() -> dict[str, Any] | None:
        run = core.run(run_id)
        return run if run["state"] == "ended" else None

    run = wait_for(ended, "the cancelled step's end", every_s=0.1)
    print(f"[e2e-step] cancelled 5s into the step's deploy: the run ended {time.monotonic() - began:.2f}s after the "
          f"cancel was asked", flush=True)
    assert_events_whole(core.events(run_id))
    # The cancel stopped the deploy, its whole process group killed: nothing runs on.
    assert containerlab_processes(f"/{CANCEL_TWIN}/") == [], "the cancel left the deploy running"
    verdict = run["verdict"]
    assert list(schemas.validator("findings-1").iter_errors(verdict)) == []
    print(f"[e2e-step] the step's verdict: {verdict['status']} "
          f"{[(f['rule'], f.get('object'), f['message']) for f in verdict['findings']]}", flush=True)
    diverged = [f for f in verdict["findings"] if f["rule"] == "step.diverged"]
    assert verdict["status"] == "diverged" and len(diverged) == 1, verdict
    assert "cancelled during apply" in diverged[0]["message"], diverged[0]

    record = wait_for(lambda: r if (r := core.record(CANCEL_TWIN)) is not None and settled(r) else None,
                      f"{CANCEL_TWIN} settled")
    assert list(schemas.validator("twin-record-1").iter_errors(record)) == []
    status = record["status"]
    conditions = {c["type"]: (c["status"], c.get("reason")) for c in status["conditions"]}
    assert conditions["Diverged"] == ("True", "step.diverged"), conditions
    assert conditions["Ready"] == ("False", "step.diverged"), conditions
    last = status["last_step"]
    assert (last["outcome"], last["run_id"]) == ("diverged", run_id), last
    # Cut short before `applied`: the record describes the twin it ran, its deployment the old one.
    assert last["phase"] == "planned" and status["bundle_id"] == before["status"]["bundle_id"], last
    assert status["deployment_id"] == before["status"]["deployment_id"]
    print(f"[e2e-step] the record: Diverged {conditions['Diverged']}, Ready {conditions['Ready']}, last step "
          f"{last['outcome']} at {last['phase']}", flush=True)

    # A diverged twin accepts only deletion: a new spec is refused.
    unlinked = json.loads((STEPS / "three-node-unlinked.json").read_text())
    filed = core.client().post("/v1/blueprints", json=unlinked)
    assert filed.status_code in (200, 201), filed.text
    refused = core.client().put(f"/v1/twins/{CANCEL_TWIN}", json={"spec": {"blueprint_id": filed.json()["id"]}})
    print(f"[e2e-step] a PUT of another spec: {refused.status_code} {refused.json().get('rule')}", flush=True)
    assert refused.status_code == 409 and refused.json()["rule"] == "twin.diverged", refused.text

    # Verify still answers, against the bundle the record names, the running one (D-054).
    code, out = fylgja("twin", "verify", CANCEL_TWIN, "--json")
    answer = json.loads(out)
    print(f"[e2e-step] twin verify of the diverged twin: exit {code}, {answer['status']} {answer.get('counts')}, "
          f"findings {[(f['rule'], f.get('object')) for f in answer['findings']]}", flush=True)
    assert (code, answer["status"]) in ((0, "ok"), (1, "nonconforming")), (code, answer["status"])
    assert answer["subject"]["bundle_id"] == before["status"]["bundle_id"]

    # The deletion removes everything, the node the cut-short deploy made among it (D-055).
    assert sorted(lab(CANCEL_TWIN)) == list(NODES), "n3 is not in the lab the destroy is asked of"
    since = core.stderr.stat().st_size
    began = time.monotonic()
    code, out = fylgja("twin", "destroy", CANCEL_TWIN)
    print(f"[e2e-step] the diverged twin destroyed in {time.monotonic() - began:.1f}s", flush=True)
    said = [line["message"] for line in logged(core, since)]
    for message in said:
        if CANCEL_TWIN in message and any(k in message for k in ("stray", "destroy", "removed")):
            print(f"[e2e-step]   {message[:160]}", flush=True)
    assert code == 0 and f"twin {CANCEL_TWIN} deleted" in out
    assert core.record(CANCEL_TWIN) is None
    destroy = core.runs(CANCEL_TWIN)[0]
    assert "verdict" in destroy and (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    removed = next((i for i, m in enumerate(said) if m.startswith(f"destroy {CANCEL_TWIN}: removed n3,")), None)
    destroyed = next((i for i, m in enumerate(said)
                      if m.startswith("containerlab destroy") and f"/{CANCEL_TWIN}/" in m), None)
    assert removed is not None and destroyed is not None and removed < destroyed, (removed, destroyed)
    assert not any(m.startswith(f"destroy {CANCEL_TWIN}: a stray deploy") for m in said), "a stray after the cancel"
    assert leftovers(CANCEL_TWIN, NODES) == CLEAN
    assert not [line for line in Path("/etc/hosts").read_text().splitlines() if f"clab-{CANCEL_TWIN}-" in line]
    assert containerlab_processes() == [], "a containerlab process is left"


# The server's log, after every test above.


def test_every_line_the_server_logged_is_json_and_holds_no_secret(core: Core) -> None:
    assert_log_clean(core)
