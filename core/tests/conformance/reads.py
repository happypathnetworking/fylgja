"""What a conformance scenario reads, on any harness: the API's records, runs and events, the
CLI's answers and the core's own log, never a runtime (`test_conformance_scenarios.py` holds
that). Every wait is bounded by `DEADLINE_S` unless it says otherwise, and every assertion names
what it found, never a secret. The fixtures' constants are defined here, the neutral place:
`tests/live` imports them from here too (`live.host`).

A step is walked by what its dry run answers (`expected`, `walk`): which nodes keep their
incarnation, which are made anew, and whether the spec must allow a restart, never by the
driver's name; what a driver can do comes from its capabilities. A step a kill cuts short is
asked so too: its twin kept on its base (`kill_base`), the step watched to the phase the kill
follows (`stepped_until`), and its resume held to the same run (`assert_resumed`).
"""

from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from fylgja_core import schemas
from fylgja_core.client import messages
from fylgja_core.verify import RULE_NODE_UNREAD

if TYPE_CHECKING:
    import threading

    from conformance.harness import Fylgja, Harness, Mark

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "testdata" / "blueprint" / "three-node.json"
NODES = ("n1", "n2", "n3")
"""`BLUEPRINT`'s nodes."""
DESCRIBED = "to n1 ethernet-1/1"
"""`n2`'s `ethernet-1/1` description in `BLUEPRINT`'s configuration: a line the kind's baseline
does not set, so only a push puts it there."""
MIXED = ROOT / "testdata" / "blueprint" / "mixed.json"
MIXED_NODES = ("e1", "e2", "s1")
"""`MIXED`'s nodes: `e1` and `e2` run EOS."""
UNMADE = "cf-none"
"""The twin `needs_ceos` dry-runs a create of: never made, so not one of `TWINS`."""
RESTART = "step.restart.required"
"""A step's refusal for a node the runtime would restart or recreate, unless the spec allows it."""
RELINK = "step.relink.unsupported"
"""A step's refusal for a change of links the driver cannot make on a running twin."""
TWINS = ("cf-life", "cf-ckill", "cf-akill", "cf-dkill", "cf-wkill", "cf-del", "cf-step", "cf-eos", "cf-skill",
         "cf-cancel", "cf-restore", "cf-iso-a", "cf-iso-b")
"""Every twin the suite makes, none a prefix of another: each is removed at the session's end
(`Harness.close`)."""
DEADLINE_S = 600.0
"""Every wait's budget: a create of three SR Linux nodes takes about 60-90 s."""
QUIET_S = 120.0
"""The longest a watch of a create goes without a write: the apply's 40 s, twice over and more."""
IN_APPLY_S = 10
"""How long after its `apply` started a scenario kills the core in it: well inside an apply of
three SR Linux nodes."""
UNREAD_S = 30.0
"""How long a verify asked once a step has ended asks again, every `UNREAD_EVERY_S`, while its only
errors are nodes it could not read: on the cluster, a node's Service can be without its endpoint
for a second or two some seconds after a step that kept its pod (verified-facts.md), and a read
then is refused."""
UNREAD_EVERY_S = 2.0
"""How often that verify asks again."""
SSE = "text/event-stream"


def wait_for[T](read: Callable[[], T | None], what: str, timeout_s: float = DEADLINE_S, every_s: float = 0.5) -> T:
    """`read()` once it answers something, polled each `every_s`, failing after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    while (value := read()) is None:
        assert time.monotonic() < deadline, f"{what}: not within {timeout_s:g}s"
        time.sleep(every_s)
    return value


def gone(harness: Harness, twin: str) -> bool | None:
    return True if harness.record(twin) is None else None


def remove(harness: Harness, twin: str) -> None:
    """Destroy `twin` through the API if it is still there, and wait until it is gone: a
    scenario's own cleanup, however it ended."""
    if harness.record(twin) is not None:
        print(f"\n[conformance] removing the twin {twin} left behind", flush=True)
        asked = harness.client().delete(f"/v1/twins/{twin}")
        # 202, the deletion asked; 404, the twin gone since it was read.
        assert asked.status_code in (202, 404), f"DELETE /v1/twins/{twin}: {asked.status_code} {asked.text}"
        wait_for(functools.partial(gone, harness, twin), f"{twin}'s removal")


def run_ids(harness: Harness, twin: str) -> set[str]:
    """The ids of the twin's runs now: what a scenario takes before it acts, for `runs_since`."""
    return {r["id"] for r in harness.runs(twin)}


def runs_since(harness: Harness, twin: str, before: set[str]) -> list[dict[str, Any]]:
    """The twin's runs, newest first, but those whose ids are `before`: a scenario's own. The store
    keeps a destroyed twin's runs, so a name used again lists its earlier lives' runs too, and on a
    store that outlives the session, an earlier session's."""
    return [r for r in harness.runs(twin) if r["id"] not in before]


def ready(record: dict[str, Any]) -> bool:
    return any(c["type"] == "Ready" and c["status"] == "True" for c in record["status"]["conditions"])


def settled(record: dict[str, Any]) -> bool:
    return bool(record["status"]["observed_generation"] == record["generation"])


def verdict_of(harness: Harness, twin: str) -> str:
    """The newest run's verdict, in a line: its status and its findings' rules."""
    runs = harness.runs(twin)
    verdict = runs[0].get("verdict") if runs else None
    if verdict is None:
        return "no verdict"
    return f"{verdict['status']} {[f['rule'] for f in verdict['findings']]}"


def assert_settled_ready(harness: Harness, record: dict[str, Any], what: str) -> None:
    """`record` settled and Ready: failing, it says `what` it read, which of the two it is not and
    the twin's newest verdict (`verdict_of`), never the record, which holds each node's address.
    The two are read as bools before the assertion, and this frame, whose argument is the record,
    is left out of pytest's traceback, as a frame's arguments are shown there."""
    __tracebackhide__ = True
    is_settled, is_ready = settled(record), ready(record)
    assert is_settled and is_ready, (f"{what} is not settled and Ready (settled {is_settled}, Ready {is_ready}); "
                                     f"the twin's newest run: {verdict_of(harness, record['name'])}")


def assert_twin_record(record: Mapping[str, Any]) -> None:
    """`record` held to twin record 1: failing, it names each place the record breaks it, by its
    path and the keyword it breaks, never a value, since a record holds each node's address and
    jsonschema's own message quotes the value; this frame, whose argument is the record, is left
    out of pytest's traceback."""
    __tracebackhide__ = True
    broken = [f"{e.json_path} {e.validator}" for e in schemas.validator("twin-record-1").iter_errors(record)]
    assert not broken, f"the record of {record.get('name')} breaks twin record 1 at {broken}"


def settled_ready(harness: Harness, twin: str) -> dict[str, Any]:
    def read() -> dict[str, Any] | None:
        record = harness.record(twin)
        assert record is not None, f"{twin} is gone"
        return record if settled(record) else None

    record = wait_for(read, f"{twin} settled")
    assert_settled_ready(harness, record, twin)
    return record


def assert_events_whole(events: list[dict[str, Any]]) -> None:
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), "a gap in the events' seq"
    for event in events:
        assert schemas.api_validator("Event").is_valid(event), event


def started(events: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for e in events if e["phase"] == phase and e["outcome"] == "started")


def ended(events: list[dict[str, Any]], phase: str) -> dict[str, str]:
    """Each node's ending of `phase`, from the run's per-node events."""
    return {e["node"]: e["outcome"] for e in events
            if e["phase"] == phase and "node" in e and e["outcome"] != "started"}


def by(deadline: float, lines: Iterator[str], what: str) -> Iterator[str]:
    """A stream's lines, failing the test once `deadline` has passed: checked on every line, the
    server's keepalive comments included, so a twin that stops being written fails the test
    within the deadline even while the stream stays alive."""
    for line in lines:
        if time.monotonic() > deadline:
            pytest.fail(f"{what} within {DEADLINE_S:g}s")
        yield line


def created_until(
    harness: Harness, fylgja: Fylgja, twin: str, phase: str, blueprint: Path = BLUEPRINT
) -> dict[str, Any]:
    """Create `twin` with a watch of every twin already open, so no write is missed, and answer
    its record as the loop writes `phase`; a create that settles first fails the test."""
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    with harness.client().stream("GET", "/v1/twins", params={"watch": "true"}, headers={"Accept": SSE},
                                 timeout=timeout) as stream:
        assert stream.status_code == 200
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(blueprint), "--no-wait")
        assert code == 0
        for message in messages(by(deadline, stream.iter_lines(), f"{twin} did not reach {phase}")):
            record: dict[str, Any] = json.loads(message.data)["object"]
            if record["name"] != twin:
                continue
            if record["status"].get("phase") == phase:
                return record
            if settled(record):
                pytest.fail(f"{twin} settled before {phase}: Ready {ready(record)}, {verdict_of(harness, twin)}")
    pytest.fail(f"the watch ended before {twin} reached {phase}")


def apply_started(
    harness: Harness, twin: str, operation: str, before: set[str] | None = None, *, ended: threading.Event | None = None
) -> str:
    """The id of the twin's newest run of `operation`, but those whose ids are `before` (`run_ids`),
    once its events show its `apply` started. Given `before`, it may be asked before the run is
    made, as a thread beside a waiting CLI asks it; given `ended`, set once that CLI has ended, it
    fails at its next read once it is set, rather than wait on."""

    def read() -> str | None:
        assert ended is None or not ended.is_set(), f"the {operation} of {twin} ended before its apply started"
        runs = [r for r in runs_since(harness, twin, before or set()) if r["operation"] == operation]  # newest first
        if not runs:
            return None
        run_id: str = runs[0]["id"]
        return run_id if started(harness.events(run_id), "apply") else None

    return wait_for(read, f"{twin}'s {operation} run's apply", every_s=0.1)


def apply_ended(harness: Harness, run_id: str) -> bool:
    """Whether the run's newest `apply` that started has ended, by its events: an `apply` event of
    another outcome follows it."""
    events = harness.events(run_id)
    starts = [i for i, e in enumerate(events) if e["phase"] == "apply" and e["outcome"] == "started"]
    return bool(starts) and any(e["phase"] == "apply" and e["outcome"] != "started" for e in events[starts[-1]:])


def resumed_after(harness: Harness, since: Mark, run_id: str) -> str | None:
    """The phase the core's log says the run `run_id` resumed after, in a line after the mark
    `since`: a line of the core's, whichever runtime it drives. None when no pass resumed it."""
    pattern = re.compile(rf" run {re.escape(run_id)} resumed after (\w+)$")
    for line in harness.log()[since:]:
        try:
            said = json.loads(line).get("message", "")
        except (ValueError, AttributeError):
            continue
        found = pattern.search(said) if isinstance(said, str) else None
        if found:
            return found.group(1)
    return None


def _is_json(line: str) -> bool:
    try:
        json.loads(line)
    except ValueError:
        return False
    return True


def assert_log_clean(harness: Harness) -> None:
    """Every line the core logged is one JSON object, and none holds a value of `secrets()`
    (Constitution X): failing, it names the lines by number and the variable, never a line or a
    value. A password is found where no word character or dash adjoins it, as the live tier has
    always looked for it; the token anywhere."""
    lines = harness.log()
    assert lines, "the core logged nothing"
    not_json = [i for i, line in enumerate(lines, 1) if not _is_json(line)]
    assert not not_json, f"lines {not_json} of the log are no JSON"
    for variable, value in sorted(harness.secrets().items()):
        if not value:
            continue
        pattern = re.compile(re.escape(value) if variable == "FYLGJA_API_TOKEN"
                             else rf"(?<![\w-]){re.escape(value)}(?![\w-])")
        holding = [i for i, line in enumerate(lines, 1) if pattern.search(line)]
        assert not holding, f"lines {holding} of the log hold {variable}'s value"
    print(f"\n[conformance] the core logged {len(lines)} lines, every one JSON, no token or password", flush=True)


# The steps.


@dataclass(frozen=True)
class Verified:
    """What verify of a fixture's twin answers when it holds: its counts, and the objects of its
    findings, each an info skip (a configured node's host name, reported; a probe endpoint's
    neighbour). A held assertion files no finding, so a link end missing here was asserted and
    held, or not asserted at all, which the held count tells apart."""

    held: int
    skipped: int
    skips: frozenset[str]


_DEVICES = frozenset(NODES)
VERIFIED = {
    # 2 links: 4 ports enabled, 4 neighbours, 3 claims; the link n2:ethernet-1/2-n3:ethernet-1/1 is not asserted.
    "three-node-unlinked": Verified(held=11, skipped=3, skips=_DEVICES),
    # 3 links: 6 ports, 6 neighbours, 3 claims.
    "three-node": Verified(held=15, skipped=3, skips=_DEVICES),
    # three-node's 15, less n1:ethernet-1/2's admin state and its link's two neighbours: intent disables it.
    "three-node-n1-disabled": Verified(held=12, skipped=6,
                                       skips=_DEVICES | {"n1:ethernet-1/2", "n3:ethernet-1/2"}),
    # three-node's 15, n2's host name asserted for its reported one, and its claim a skip: it has no configuration.
    "three-node-unmanaged": Verified(held=15, skipped=3, skips=_DEVICES),
    # 1 link: 2 ports, 2 neighbours, 2 claims.
    "two-node": Verified(held=6, skipped=2, skips=frozenset({"n1", "n2"})),
    # three-node's 15, the probe's 2 endpoints enabled and its 2 bursts; its endpoints' neighbours are skips.
    "three-node-probed": Verified(held=19, skipped=5,
                                  skips=_DEVICES | {"n1:ethernet-1/10", "n1:ethernet-1/11"}),
    # The same probe on n2's ports.
    "three-node-probed-moved": Verified(held=19, skipped=5,
                                        skips=_DEVICES | {"n2:ethernet-1/10", "n2:ethernet-1/11"}),
    # n3 as EOS, its links on Ethernet2 and Ethernet1: three-node's 15, each neighbour judged across kinds.
    "three-node-n3-eos": Verified(held=15, skipped=3, skips=_DEVICES),
    # 3 links: 6 ports, 6 neighbours, 3 claims; every node configured, so each host name reported.
    "mixed": Verified(held=15, skipped=3, skips=frozenset(MIXED_NODES)),
    # mixed's 15, and the link e1:Ethernet10-e2:Ethernet10: 2 ports, 2 neighbours.
    "mixed-e2-port": Verified(held=19, skipped=3, skips=frozenset(MIXED_NODES)),
}
"""By the fixture's name, what verify of a twin of it answers."""


def record_nodes(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The record's nodes by name."""
    return {n["name"]: n for n in record["status"]["nodes"]}


def addresses(record: Mapping[str, Any]) -> dict[str, str]:
    """Each node's address, from the record."""
    return {name: n["address"] for name, n in record_nodes(record).items()}


def devices(fixture: Path) -> frozenset[str]:
    """The device nodes of the blueprint `fixture`: every node a twin of it holds but its probes'
    hosts."""
    doc = json.loads(fixture.read_text())
    return frozenset(device["name"] for device in doc["network"]["devices"])


def twin_nodes(fixture: Path) -> frozenset[str]:
    """Every node a twin of the blueprint `fixture` holds: its devices, and each probe's two hosts,
    `<probe>-a` and `<probe>-b` (twin record 1), a probe having two ends (blueprint 1)."""
    doc = json.loads(fixture.read_text())
    return devices(fixture) | {f"{probe['name']}-{side}" for probe in doc["probes"] for side in "ab"}


def step(
    harness: Harness, fylgja: Fylgja, twin: str, fixture: Path | None = None, *, bundle: str | None = None,
    allow_restart: bool = False,
) -> tuple[int, dict[str, Any]]:
    """`twin step` of `twin` to the blueprint `fixture`, or to the filed bundle `bundle`: its exit
    code, and the record read after."""
    assert (fixture is None) != (bundle is None), "a step names a blueprint or a bundle, not both"
    source = ["--blueprint", str(fixture)] if fixture is not None else ["--bundle", str(bundle)]
    code, _ = fylgja("twin", "step", twin, *source, *(["--allow-restart"] if allow_restart else []))
    record = harness.record(twin)
    assert record is not None, f"{twin} is gone"
    return code, record


def incarnations(harness: Harness, twin: str) -> dict[str, str]:
    """Each node's incarnation, from the record: every node has one."""
    record = harness.record(twin)
    assert record is not None, f"{twin} is gone"
    found = {name: n.get("incarnation") for name, n in record_nodes(record).items()}
    assert all(found.values()), f"a node without an incarnation: {found}"
    return {name: str(value) for name, value in found.items()}


def holds(harness: Harness, twin: str) -> dict[str, str | None]:
    """The bundle each node holds, from the record; None for a probe host, which holds none."""
    record = harness.record(twin)
    assert record is not None, f"{twin} is gone"
    return {name: n.get("holds") for name, n in record_nodes(record).items()}


def created(harness: Harness, fylgja: Fylgja, twin: str, fixture: Path, nodes: Iterable[str]) -> dict[str, Any]:
    """`twin create <twin> --blueprint <fixture>`, waited for, the runtime holding nothing of the
    twin before: exit 0; the record Ready and settled, held to twin record 1, with the nodes
    `nodes`; and the runtime's nodes the record's, at its incarnations. The record."""
    assert harness.leftovers(twin) == [], f"the runtime holds {twin} already"
    began = time.monotonic()
    code, _ = fylgja("twin", "create", twin, "--blueprint", str(fixture))
    print(f"[conformance] create {twin}, end to end: {time.monotonic() - began:.1f}s", flush=True)
    assert code == 0
    record = harness.record(twin)
    assert record is not None, f"{twin} is gone"
    assert_settled_ready(harness, record, f"{twin} after its create")
    assert_twin_record(record)
    assert sorted(record_nodes(record)) == sorted(nodes)
    assert harness.nodes(twin) == incarnations(harness, twin), "the runtime's nodes are not the record's"
    return record


def destroyed(harness: Harness, fylgja: Fylgja, twin: str) -> None:
    """`twin destroy <twin>`, waited for: exit 0 and `twin <twin> deleted`; no record; nothing of
    the twin left in the runtime; and the one run made since, a destroy, `ok`. The twin is removed
    however that ends (`remove`)."""
    try:
        before = run_ids(harness, twin)
        code, out = fylgja("twin", "destroy", twin)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_deleted = f"twin {twin} deleted" in out
        assert code == 0 and said_deleted, code
        assert harness.record(twin) is None
        assert harness.leftovers(twin) == []
        made = [(r["operation"], (r.get("verdict") or {}).get("status")) for r in runs_since(harness, twin, before)]
        assert made == [("destroy", "ok")], made
    finally:
        remove(harness, twin)


@dataclass(frozen=True)
class Stepped:
    """One step through the CLI: the twin and the fixture (None for a step to a bundle), its exit
    code and what it took, the log's mark before it (for the harness's audits), the record before
    and after, the run it ran with its events, and the verify after it, once `walk` has asked it."""

    twin: str
    fixture: Path | None
    code: int
    took_s: float
    since: Mark
    before: dict[str, Any]
    record: dict[str, Any]
    run: dict[str, Any]
    events: list[dict[str, Any]]
    verify: dict[str, Any] | None = None

    @property
    def verdict(self) -> dict[str, Any]:
        verdict: dict[str, Any] = self.run["verdict"]
        return verdict


def stepped(
    harness: Harness, fylgja: Fylgja, twin: str, fixture: Path | None = None, *, bundle: str | None = None,
    allow_restart: bool = False, ready_before: bool = True,
) -> Stepped:
    """`twin`, settled (and Ready, by `ready_before`), stepped to `fixture`, or to the filed bundle
    `bundle`, through the CLI; then its record, the one run the step made, the record's, and its
    events read through the API and held to their formats, and the step's timings printed."""
    before = harness.record(twin)
    assert before is not None, f"{twin} is gone"
    if ready_before:
        assert_settled_ready(harness, before, f"{twin} before its step")
    else:
        assert settled(before), f"{twin} is not settled to step"
    since, ids = harness.mark(), run_ids(harness, twin)
    began = time.monotonic()
    code, record = step(harness, fylgja, twin, fixture, bundle=bundle, allow_restart=allow_restart)
    took = time.monotonic() - began
    assert_twin_record(record)
    last = record["status"]["last_step"]
    made = [(r["id"], r["operation"]) for r in runs_since(harness, twin, ids)]
    assert made == [(last["run_id"], "step")], f"the step made {made}, not the one step run its record names"
    run = harness.run(last["run_id"])
    assert (run["operation"], run["state"]) == ("step", "ended"), run
    assert schemas.api_validator("Run").is_valid(run), run
    assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
    events = harness.events(run["id"])
    assert_events_whole(events)
    phases: dict[str, float] = {}
    for e in events:
        if e["outcome"] != "started" and "duration_s" in e:  # a phase's, or each node's in `ready` and `push`, summed
            phases[e["phase"]] = phases.get(e["phase"], 0.0) + e["duration_s"]
    verdict = run["verdict"]
    to = fixture.stem if fixture is not None else f"the bundle {bundle}"
    print(f"[conformance] step to {to}: exit {code} in {took:.2f}s, {verdict['status']}, last step "
          f"{last['outcome']} at {last['phase']}; phases {', '.join(f'{p} {s:.2f}s' for p, s in phases.items())}; "
          f"wait {verdict.get('wait')}; counts {verdict.get('counts')}; loss {verdict.get('loss')}", flush=True)
    return Stepped(twin=twin, fixture=fixture, code=code, took_s=took, since=since, before=before, record=record,
                   run=run, events=events)


def assert_stepped(harness: Harness, s: Stepped) -> None:
    """What every step that changes the twin ends with: exit 0 and the run `ok`; `last_step`
    `stepped` at `flows`, from the bundle the twin ran to the one it runs now; Ready True and
    Stepping False for `twin.ready`; the wait settled; one apply, and the runtime's own account
    of it (`audit_apply`); every device node holding the new bundle; and the runtime's nodes the
    record's, at its incarnations."""
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
    # The budget is the core's own setting, which the API does not give: printed, not asserted.
    print(f"[conformance] the wait: {wait['outcome']} after {wait['after_s']:.2f}s of {wait['budget_s']}s", flush=True)
    assert wait["outcome"] == "settled", wait
    assert verdict["counts"]["failed"] == 0, verdict["counts"]
    assert started(s.events, "apply") == 1, f"{started(s.events, 'apply')} apply started"
    harness.audit_apply(s.twin, s.since, 1)
    assert s.fixture is not None, "a step that changes the twin is to a blueprint here, whose devices hold its bundle"
    owed = devices(s.fixture)
    held = {name: n.get("holds") for name, n in record_nodes(record).items() if name in owed}
    assert held == dict.fromkeys(owed, status["bundle_id"]), held
    assert harness.nodes(s.twin) == {name: n["incarnation"] for name, n in record_nodes(record).items()}, \
        "the runtime's nodes are not the record's"


def assert_holds(doc: Mapping[str, Any], fixture: str) -> None:
    """A verify verdict on a twin of `fixture`: `ok`, with `VERIFIED`'s counts and skips."""
    holding = VERIFIED[fixture]
    assert doc["status"] == "ok", doc["findings"]
    assert doc["counts"] == {"held": holding.held, "failed": 0, "skipped": holding.skipped}, doc["counts"]
    assert all(f["rule"] == "verify.skipped" and f["severity"] == "info" for f in doc["findings"]), doc["findings"]
    assert {f["object"] for f in doc["findings"]} == holding.skips, doc["findings"]


def verified(fylgja: Fylgja, twin: str, fixture: str) -> dict[str, Any]:
    """`twin verify --json` through the CLI, asked once a step has ended: exit 0, its verdict held
    to findings 1 and to `VERIFIED[fixture]`'s counts and skips. Asked again within `UNREAD_S`
    while its only errors are nodes it could not read (`verify.node.unread`), each ask printed.
    The verdict."""
    deadline = time.monotonic() + UNREAD_S
    while True:
        code, out = fylgja("twin", "verify", twin, "--json")
        assert out.strip(), f"twin verify {twin} printed nothing: exit {code}"
        doc: dict[str, Any] = json.loads(out)
        print(f"[conformance] twin verify {twin}: exit {code}, {doc.get('status')} {doc.get('counts')}, findings "
              f"{[(f['rule'], f.get('object')) for f in doc.get('findings', [])]}", flush=True)
        errors = [f for f in doc.get("findings", []) if f.get("severity") == "error"]
        if not errors or any(f["rule"] != RULE_NODE_UNREAD for f in errors) or time.monotonic() > deadline:
            break
        print(f"[conformance] {sorted(str(f.get('object')) for f in errors)} unread: verify asked again in "
              f"{UNREAD_EVERY_S:g}s", flush=True)
        time.sleep(UNREAD_EVERY_S)
    assert code == 0 and list(schemas.validator("findings-1").iter_errors(doc)) == [], doc
    assert_holds(doc, fixture)
    return doc


_CEOS: dict[int, str | None] = {}
"""`needs_ceos`'s answer by the harness it was read from (its `id`): read once a session."""


def needs_ceos(harness: Harness) -> None:
    """Skip the test, with the rule quoted, where the core says the EOS image cannot be had: a dry
    run of a create of `UNMADE` from `MIXED` answered `422` with `admission.image.absent`, or with
    `plan.rejected` holding `plan.registry.absent`. Read once a session; any other refusal fails
    the test."""
    if id(harness) not in _CEOS:
        _CEOS[id(harness)] = _ceos_refusal(harness)
    reason = _CEOS[id(harness)]
    if reason is not None:
        pytest.skip(reason)


def _ceos_refusal(harness: Harness) -> str | None:
    """Why the core cannot have the EOS image, by a dry run of a create from `MIXED`; None when
    its plan is `ok`. The dry run writes nothing, so `UNMADE` is never made."""
    client = harness.client()
    filed = client.post("/v1/blueprints", json=json.loads(MIXED.read_text()))
    assert filed.status_code in (200, 201), f"POST /v1/blueprints: {filed.status_code} {filed.text}"
    answer = client.put(f"/v1/twins/{UNMADE}", params={"dry_run": "true"}, headers={"If-None-Match": "*"},
                        json={"spec": {"blueprint_id": filed.json()["id"]}})
    if answer.status_code == 200:
        plan = answer.json()
        assert schemas.api_validator("Plan").is_valid(plan) and plan["verdict"]["status"] == "ok", plan
        print(f"\n[conformance] a dry run of a create of {UNMADE} from {MIXED.stem}: ok, so the core can have the EOS "
              "image", flush=True)
        return None
    assert answer.status_code == 422, f"a dry run of a create of {UNMADE}: {answer.status_code} {answer.text}"
    problem = answer.json()
    rule, held = problem["rule"], sorted({f["rule"] for f in problem.get("findings", [])})
    said = problem.get("detail") or problem["title"]
    if rule == "admission.image.absent" or (rule == "plan.rejected" and "plan.registry.absent" in held):
        holding = f" holding {held}" if rule == "plan.rejected" else ""
        return (f"the core cannot have the EOS image: a dry run of a create from {MIXED.stem} answers "
                f"{rule}{holding}: {said}")
    pytest.fail(f"a dry run of a create of {UNMADE} from {MIXED.stem} answers 422 {rule}, findings {held}: {said}")


@dataclass(frozen=True)
class Expected:
    """What a step's dry run says the step does, by the actions of its `changes`: the nodes that
    keep their incarnation (`kept`, `recabled`), those restarted, recreated, added and removed;
    and the rule of its refusal, the spec allowing no restart, or None where it would go ahead."""

    kept: frozenset[str]
    restarted: frozenset[str]
    recreated: frozenset[str]
    added: frozenset[str]
    removed: frozenset[str]
    refused: str | None


def expected(harness: Harness, fylgja: Fylgja, caps: Mapping[str, Any], twin: str, fixture: Path) -> Expected:
    """`twin step <twin> --blueprint <fixture> --dry-run --json`, the spec allowing no restart: the
    plan held to API 1's `Plan`, with a step's changes naming every node of either side, none of
    them `unsupported`; a refusal of one rule, exited 1 exactly then; `step.relink.unsupported`
    exactly where the driver cannot relink and the links change (one added or removed, or a node
    recabled, as the core counts them), and otherwise `step.restart.required` naming exactly the
    nodes restarted or recreated; and nothing moved, neither the record's generation and spec nor
    the runtime's nodes, and nothing applied in the runtime's own account (`audit_apply`)."""
    before = harness.record(twin)
    assert before is not None, f"{twin} is gone"
    held, since = harness.nodes(twin), harness.mark()
    code, out = fylgja("twin", "step", twin, "--blueprint", str(fixture), "--dry-run", "--json")
    assert out.strip(), f"the dry run of {fixture.stem} printed nothing: exit {code}"
    plan = json.loads(out)
    verdict, changes = plan["verdict"], plan.get("changes")
    print(f"[conformance] a dry run to {fixture.stem}: exit {code}, {verdict['status']} "
          f"{[(f['rule'], f.get('object')) for f in verdict['findings']]}, changes {changes}", flush=True)
    assert schemas.api_validator("Plan").is_valid(plan), plan
    assert changes is not None, "a step's dry run answered no changes"
    actions = {c["node"]: c["action"] for c in changes["nodes"]}
    either = set(record_nodes(before)) | twin_nodes(fixture)
    assert set(actions) == either, \
        f"the changes name {sorted(actions)}, not every node of either side, {sorted(either)}"
    unsupported = sorted(node for node, action in actions.items() if action == "unsupported")
    assert not unsupported, f"the driver cannot make the change the step asks of {unsupported}: no walk steps it"

    def acting(*named: str) -> frozenset[str]:
        return frozenset(node for node, action in actions.items() if action in named)

    errors = [f for f in verdict["findings"] if f["severity"] == "error"]
    rules = sorted({f["rule"] for f in errors})
    refused: str | None = None
    if verdict["status"] == "rejected":
        assert len(rules) == 1, f"the dry run refuses for {rules}, not for one rule"
        refused = rules[0]
    else:
        assert verdict["status"] == "ok" and errors == [], verdict
    assert code == (1 if refused is not None else 0), (code, verdict["status"])
    e = Expected(kept=acting("kept", "recabled"), restarted=acting("restarted"), recreated=acting("recreated"),
                 added=acting("added"), removed=acting("removed"), refused=refused)
    relinked = bool(changes["links_added"] or changes["links_removed"]) or "recabled" in actions.values()
    assert (RELINK in rules) == (not caps["relink"] and relinked), (rules, caps["relink"], relinked)
    if RELINK not in rules:  # the refusal no spec clears comes first; the restart's only without it
        restart = {f.get("object") for f in errors if f["rule"] == RESTART}
        assert restart == e.restarted | e.recreated, (sorted(map(str, restart)), e)
    after = harness.record(twin)
    assert after is not None and (after["generation"], after["spec"]) == (before["generation"], before["spec"]), \
        "the dry run wrote a spec"
    assert harness.nodes(twin) == held, "the dry run touched the runtime's nodes"
    harness.audit_apply(twin, since, 0)
    return e


# The kills of a step.


def stepped_until(
    harness: Harness, fylgja: Fylgja, twin: str, fixture: Path, phase: str, *, allow_restart: bool = False
) -> dict[str, Any]:
    """Step `twin` to `fixture` (`--no-wait`) with a watch of every twin already open, so no write
    is missed, and answer its record as the loop records `phase` for the step: while `last_step` is
    `running`, its `phase`, where a step's phases before `applied` are recorded alone (D-054). A
    step that ends first fails the test."""
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    with harness.client().stream("GET", "/v1/twins", params={"watch": "true"}, headers={"Accept": SSE},
                                 timeout=timeout) as stream:
        assert stream.status_code == 200
        before = harness.record(twin)
        assert before is not None and settled(before), f"{twin} is not settled to step"
        asked = before["generation"] + 1  # the generation the step's spec is written at
        code, _ = fylgja("twin", "step", twin, "--blueprint", str(fixture), "--no-wait",
                         *(["--allow-restart"] if allow_restart else []))
        assert code == 0
        for message in messages(by(deadline, stream.iter_lines(), f"{twin}'s step did not reach {phase}")):
            record: dict[str, Any] = json.loads(message.data)["object"]
            if record["name"] != twin or record["generation"] < asked:  # the watch's first look, before the spec
                continue
            last = record["status"].get("last_step")
            if last is not None and last["outcome"] == "running" and last["phase"] == phase:
                return record
            if settled(record):
                pytest.fail(f"{twin}'s step ended before {phase}: Ready {ready(record)}, {verdict_of(harness, twin)}")
    pytest.fail(f"the watch ended before {twin}'s step reached {phase}")


def kill_base(harness: Harness, fylgja: Fylgja, caps: Mapping[str, Any], twin: str, base: Path) -> None:
    """`twin` Ready and settled on the blueprint `base`, the runtime holding its nodes: created from
    it when it is absent, stepped back to it (`walk`) when it holds other nodes, and made anew when
    an earlier scenario left it unready or unsettled."""
    record = harness.record(twin)
    if record is not None and not (ready(record) and settled(record)):
        print(f"[conformance] {twin} is left unready ({verdict_of(harness, twin)}): made anew", flush=True)
        destroyed(harness, fylgja, twin)
        record = None
    if record is None:
        created(harness, fylgja, twin, base, twin_nodes(base))
    elif set(record_nodes(record)) != twin_nodes(base):
        walk(harness, fylgja, caps, twin, base)
    held = harness.nodes(twin)
    assert set(held) == twin_nodes(base), f"the runtime holds {sorted(held)} of {twin}, not {base.stem}'s nodes"


def assert_resumed(
    harness: Harness, fylgja: Fylgja, twin: str, fixture: Path, run_id: str, record: dict[str, Any], *,
    e: Expected, runs_before: set[str], incarnations_before: Mapping[str, str], since: Mark,
) -> list[dict[str, Any]]:
    """What a step to `fixture` resumed after a kill ends with, `record` read once `twin` settled:
    the same step run `run_id`, the only one since `runs_before`, ended `ok`, its wait settled (a
    run resumed after its wait carries none, D-054, and the core's log then says it resumed after
    `verified` or `flows`); `last_step` `stepped` at `flows`; the fixture's nodes in the record and
    in the runtime, the two at the same incarnations; every device node holding the bundle; every
    node the dry run `e` keeps at the incarnation it had before the step; one `apply` done; and
    `verified`. The run's events."""
    made = [(r["id"], r["operation"]) for r in runs_since(harness, twin, runs_before)]
    assert made == [(run_id, "step")], f"the resume made {made}, not the one step run {run_id}"
    run = harness.run(run_id)
    assert run["state"] == "ended" and run["verdict"]["status"] == "ok", run.get("verdict")
    assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
    wait = run["verdict"].get("wait")
    if wait is None:
        assert resumed_after(harness, since, run_id) in ("verified", "flows"), "a step that waited carries no wait"
    else:
        assert wait["outcome"] == "settled", wait
    assert_twin_record(record)
    status, last = record["status"], record["status"]["last_step"]
    assert (last["outcome"], last["phase"], last["run_id"]) == ("stepped", "flows", run_id), last
    now = {name: str(n["incarnation"]) for name, n in record_nodes(record).items()}
    assert set(now) == twin_nodes(fixture), f"the record holds {sorted(now)}, not {fixture.stem}'s nodes"
    assert harness.nodes(twin) == now, "the runtime's nodes are not the record's"
    owed = devices(fixture)
    held = {name: n.get("holds") for name, n in record_nodes(record).items() if name in owed}
    assert held == dict.fromkeys(owed, status["bundle_id"]), held
    assert {n: now[n] for n in e.kept} == {n: incarnations_before[n] for n in e.kept}, \
        "a node the dry run keeps was made anew"
    events = harness.events(run_id)
    assert_events_whole(events)
    applied = sum(1 for event in events if event["phase"] == "apply" and event["outcome"] == "done")
    assert applied == 1, f"{applied} apply done"
    verified(fylgja, twin, fixture.stem)
    return events


def walk(
    harness: Harness, fylgja: Fylgja, caps: Mapping[str, Any], twin: str, fixture: Path,
    pushed: frozenset[str] = frozenset(), *, ready_before: bool = True,
) -> Stepped:
    """`twin` stepped to `fixture` as its dry run says (`expected`), with `--allow-restart` exactly
    where the dry run refuses for a restart; then `assert_stepped`, and: each node the dry run
    keeps at the incarnation it had and each it recreates at another (a restarted node's is not
    asserted: a runtime may keep it, `reconcile.py`'s `_apply`); those removed gone from the record
    and the runtime, those added in both; `ready` done for exactly the nodes added, restarted and
    recreated; `push` done for the device nodes among those and among `pushed`, and skipped for
    every other device node; then `verified`. The step, with the verify's verdict."""
    e = expected(harness, fylgja, caps, twin, fixture)
    before = incarnations(harness, twin)
    s = stepped(harness, fylgja, twin, fixture, allow_restart=e.refused == RESTART, ready_before=ready_before)
    assert_stepped(harness, s)
    print(f"[conformance] {twin} to {fixture.stem}, by the dry run: kept {sorted(e.kept)}, restarted "
          f"{sorted(e.restarted)}, recreated {sorted(e.recreated)}, added {sorted(e.added)}, removed "
          f"{sorted(e.removed)}", flush=True)
    now = {name: str(n["incarnation"]) for name, n in record_nodes(s.record).items()}
    held = harness.nodes(twin)
    assert set(now) == (set(before) - e.removed) | e.added, (sorted(before), sorted(now))
    assert {n: now[n] for n in e.kept} == {n: before[n] for n in e.kept}, "a node the dry run keeps was made anew"
    assert all(now[n] != before[n] for n in e.recreated), "a node the dry run recreates kept its incarnation"
    assert not e.removed & (set(now) | set(held)), "a node removed is left"
    assert e.added <= set(now) & set(held), "a node added is missing"
    made = e.added | e.restarted | e.recreated
    assert ended(s.events, "ready") == dict.fromkeys(made, "done"), ended(s.events, "ready")
    owed = devices(fixture)
    assert ended(s.events, "push") == {n: "done" if n in made | pushed else "skipped" for n in owed}, \
        ended(s.events, "push")
    return replace(s, verify=verified(fylgja, twin, fixture.stem))
