"""`infrahub/seed/seed.py`: the reader's kind and the stage kind loaded on `main` where it lacks them; the fixture
network on `main`, its configurations generated and waited for; an earlier seed's marks and open proposed change of
the branch removed; the seeded branch made anew, each of its two staged edits loaded, generated, waited for, timed by
`head` and marked; by a flag, its proposed change; and `seed.json`.

Infrahub is a fake behind `httpx.MockTransport` that answers each GraphQL operation by its root fields, the branch's,
the marks' and the proposed changes' mutations, the schema's read and the generation's REST call, `infrahubctl` a fake
`run`, the reader's `head` the fake's own, and the clock a fake: nothing here opens a socket or starts a process.
Infrahub's own times come from a second clock of the fake's, `server`, which moves with each write it is sent.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import register
import seed
from fylgja_infrahub import Refused
from hub import Hub, HubError, connect

from fylgja_core.findings import Finding

A = seed.Artifact

HOST = "infrahub.example"
ADDRESS = f"http://{HOST}"
CTL = Path("/opt/example/bin/infrahubctl")
SEED = Path(__file__).resolve().parents[1] / "seed"
FILES = SEED / "main"
PROBE_KIND = Path(__file__).resolve().parents[2] / "readers" / "infrahub" / "schema" / "fylgja-probe.yml"
"""The reader's kind, which `make infrahub-seed` passes as `--schema`."""
STAGE_KIND = Path(__file__).resolve().parents[2] / "infrahub" / "schema" / "fylgja-stage.yml"
"""The example's stage kind, which `make infrahub-seed` passes as a second `--schema`."""
DEFINITION_ID = "18e6777e-0000-0000-0000-000000000001"
NAMES = ("n1", "n2", "n3")
BRANCH = "third-link"

RENDERS = {"1-third-link.yml": ("n1", "n3"), "2-n1-address.yml": ("n1",)}
"""The configurations each stage's file changes, as the reading of the two on a scratch branch showed
(design/verified-facts.md, "Infrahub 1.11.11")."""

EPOCH = datetime(2026, 11, 9, 13, 44, 0, 984696, tzinfo=UTC)


def server(seconds: float) -> str:
    """Infrahub's time `seconds` after the fake's epoch, in the layout of its stamps and events."""
    return (EPOCH + timedelta(seconds=seconds)).isoformat()


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from an environment of its own, `PATH` alone, so none holds the developer's (a shell may
    have `local/.env` loaded) where an assertion or a local could show it."""
    path = os.environ.get("PATH", "")
    for name in list(os.environ):
        if name != "PYTEST_CURRENT_TEST":
            monkeypatch.delenv(name)
    monkeypatch.setenv("PATH", path)


class Clock:
    """A clock that moves only when its `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def ready(checksum: str) -> dict[str, Any]:
    return {"status": "Ready", "checksum": checksum, "stamp": server(0)}


def roots(query: str) -> list[str]:
    """The fields at the top of `query`'s selection, in their order; braces inside an argument list are no
    selection."""
    found = []
    depth = parens = 0
    for token in re.findall(r"[{}()]|[\w$]+", query):
        if token in "()":
            parens += 1 if token == "(" else -1
        elif token in "{}" and not parens:
            depth += 1 if token == "{" else -1
        elif depth == 1 and not parens:
            found.append(token)
    return found


class Infrahub:
    """Infrahub as the seed meets it: `main` and its branches, `main`'s schema's kinds, the definition, the devices
    tagged `fylgja` and each branch's artifacts, the generation, and a branch's `head`.

    `kinds` are the kinds `main`'s schema lists, and a schema file loaded adds its own unless `unlisted`. On `main`,
    `generated` is what the devices' artifacts read after a generation is asked: one entry a read, the last kept; a
    load of the devices' file puts the devices on `main`. A branch is made holding `main`'s artifacts; a stage's file
    loaded on it marks the configurations it changes (`RENDERS`), and its next generation rewrites each of them but
    those in `stuck` (a file and a device). Each write moves the server's clock 10 s. `head` answers the branch's
    latest write: its last load, its checksums' stamps and its newest event, a generation's trailing it by 0.5 s, and
    Infrahub's own writes after it by 3 s, which `head` shows from its second read on; where `restless`, every read
    shows a later one. A create `unanswered` goes unanswered, the branch listed from that many reads of it on
    (`math.inf`: never); a delete `undeleting` answers no `ok` and leaves its branch. `marks` are the `FylgjaStage`s
    held, each its branch and label, and `proposed` the proposed changes, each its source branch and state; their
    ids are `mark-<n>` and `pc-<n>` in the order made. `events` keeps every load, mutation, generation and read of
    `head` in order, `mutations` each mutation's text.
    """

    def __init__(
        self,
        *,
        definitions: int = 1,
        devices: tuple[str, ...] = (),
        artifacts: Mapping[str, dict[str, Any]] | None = None,
        generated: list[dict[str, dict[str, Any]]] | None = None,
        branches: tuple[str, ...] = (),
        branch_definitions: int = 1,
        stuck: tuple[tuple[str, str], ...] = (),
        restless: bool = False,
        unanswered: float | None = None,
        undeleting: bool = False,
        kinds: tuple[str, ...] = (),
        unlisted: bool = False,
        marks: tuple[tuple[str, str], ...] = (),
        proposed: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.kinds = set(kinds)
        self.made_ids = 0
        self.marks: list[dict[str, Any]] = []
        self.proposed: list[dict[str, Any]] = []
        for held, label in marks:
            self.marks.append({"id": self.new_id("mark"), "branch": held, "label": label, "as_of": None})
        for held, state in proposed:
            self.proposed.append({"id": self.new_id("pc"), "branch": held, "state": state})
        self.unlisted = unlisted
        self.definitions = definitions
        self.devices = devices
        self.artifacts: dict[str, dict[str, dict[str, Any]]] = {"main": dict(artifacts or {})}
        self.generated = list(generated or [])
        self.moving: list[dict[str, dict[str, Any]]] = []
        self.made: dict[str, str] = {}
        self.branch_definitions = branch_definitions
        self.stuck = set(stuck)
        self.restless = restless
        self.unanswered = unanswered
        self.undeleting = undeleting
        self.listing = 0.0
        self.seconds = 0.0
        self.changing: dict[str, set[tuple[str, str]]] = {}
        self.written: dict[str, str] = {}
        self.newest: dict[str, str] = {}
        self.coming: dict[str, list[str]] = {}
        self.events: list[tuple[str, ...]] = []
        self.mutations: list[str] = []
        self.artifact_reads = 0
        for name in branches:
            self.make(name)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/schema":
            assert (request.method, request.url.params["branch"]) == ("GET", "main")
            nodes = [{"namespace": "", "name": kind} for kind in sorted(self.kinds)]
            return httpx.Response(200, json={"main": "a-hash", "nodes": nodes, "generics": []})
        if request.url.path.startswith("/api/artifact/generate/"):
            assert request.method == "POST"
            assert json.loads(request.content) == {"nodes": []}
            branch = request.url.params["branch"]
            self.events.append(("generate", request.url.path.rsplit("/", 1)[1], branch))
            if branch == "main":
                self.moving = list(self.generated)
            else:
                self.render(branch)
            return httpx.Response(200, content=b"null")
        branch = request.url.path.removeprefix("/graphql/")
        assert request.url.path == f"/graphql/{branch}"
        assert branch == "main" or branch in self.made
        body = json.loads(request.content)
        query, variables = body["query"], body["variables"]
        if query.lstrip().startswith("mutation"):
            assert branch == "main"
            [root] = roots(query)
            self.events.append((root, *(str(value) for value in variables.values())))
            self.mutations.append(query)
            answer: dict[str, Any] = getattr(self, root)(request, variables)
        else:
            answer = {root: getattr(self, root)(branch, query, variables) for root in roots(query)}
        return httpx.Response(200, json={"data": answer})

    def new_id(self, prefix: str) -> str:
        self.made_ids += 1
        return f"{prefix}-{self.made_ids}"

    def make(self, name: str) -> None:
        self.seconds += 10
        self.made[name] = server(self.seconds)
        self.artifacts[name] = dict(self.artifacts["main"])

    def load(self, branch: str, file: str) -> None:
        self.seconds += 10
        self.written[branch] = server(self.seconds)
        self.changing.setdefault(branch, set()).update((file, name) for name in RENDERS[file])

    def render(self, branch: str) -> None:
        self.seconds += 10
        for file, name in sorted(self.changing.pop(branch, set())):
            if (file, name) not in self.stuck:
                held = self.artifacts[branch][name]["checksum"]
                self.artifacts[branch][name] = {
                    "status": "Ready",
                    "checksum": f"{held}+{file}",
                    "stamp": server(self.seconds),
                }
        self.newest[branch] = server(self.seconds + 0.5)
        self.coming[branch] = [server(self.seconds + 3)]

    def BranchCreate(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables["name"] not in self.made
        if self.unanswered is not None:
            self.listing = self.unanswered
            raise httpx.ReadTimeout("timed out", request=request)
        self.make(variables["name"])
        return {"BranchCreate": {"ok": True}}

    def BranchDelete(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        if self.undeleting:
            return {"BranchDelete": {"ok": False}}
        del self.made[variables["name"]]
        del self.artifacts[variables["name"]]
        return {"BranchDelete": {"ok": True}}

    def Branch(self, branch: str, query: str, variables: dict[str, Any]) -> list[dict[str, str]]:
        name = variables["name"]
        if name not in self.made and self.listing:
            self.listing -= 1
            if not self.listing:
                self.make(name)
        return [{"name": name, "branched_from": self.made[name]}] if name in self.made else []

    def FylgjaStage(self, branch: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert branch == "main"
        edges = [{"node": {"id": mark["id"]}} for mark in self.marks if mark["branch"] == variables["branch"]]
        return {"count": len(edges), "edges": edges}

    def FylgjaStageCreate(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        held = (variables["branch"], variables["label"])
        assert held not in [(mark["branch"], mark["label"]) for mark in self.marks], "Violates uniqueness constraint"
        mark = {"id": self.new_id("mark"), "branch": held[0], "label": held[1], "as_of": variables["at"]}
        self.marks.append(mark | {"description": variables["description"]})
        return {"FylgjaStageCreate": {"ok": True, "object": {"id": mark["id"]}}}

    def FylgjaStageDelete(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        self.marks = [mark for mark in self.marks if mark["id"] != variables["id"]]
        return {"FylgjaStageDelete": {"ok": True}}

    def CoreProposedChange(self, branch: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert branch == "main"
        assert 'state__value: "open"' in query
        found = [held for held in self.proposed if (held["branch"], held["state"]) == (variables["branch"], "open")]
        edges = [{"node": {"id": held["id"]}} for held in found]
        return {"count": len(edges), "edges": edges}

    def CoreProposedChangeCreate(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        assert not [held for held in self.proposed if (held["branch"], held["state"]) == (variables["branch"], "open")]
        held = {"id": self.new_id("pc"), "branch": variables["branch"], "state": "open", "name": variables["name"]}
        self.proposed.append(held)
        return {"CoreProposedChangeCreate": {"ok": True, "object": {"id": held["id"]}}}

    def CoreProposedChangeDelete(self, request: httpx.Request, variables: dict[str, Any]) -> dict[str, Any]:
        self.proposed = [held for held in self.proposed if held["id"] != variables["id"]]
        return {"CoreProposedChangeDelete": {"ok": True}}

    def head(self, name: str) -> str:
        """The branch's latest write, as the reader's `head` would time it for the test: the latest of its last load,
        its artifacts' checksum stamps and its newest event."""
        newest = self.newest.get(name)
        stamps = [self.written.get(name, server(0)), *(held["stamp"] for held in self.artifacts[name].values())]
        latest: str = max([*stamps, *([newest] if newest else [])], key=datetime.fromisoformat)
        self.events.append(("head", name, latest))
        if self.restless and newest is not None:
            self.newest[name] = (datetime.fromisoformat(newest) + timedelta(seconds=1)).isoformat()
        elif self.coming.get(name):
            self.newest[name] = self.coming[name].pop(0)
        return latest

    def CoreArtifactDefinition(self, branch: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables == {"name": "device-config"}
        count = self.definitions if branch == "main" else self.branch_definitions
        return {"count": count, "edges": [{"node": {"id": DEFINITION_ID}}] * count}

    def DcimDevice(self, branch: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables["tag"] == "fylgja"
        if "artifacts" in query:
            assert variables["name"] == "device-config"
            return self.artifact_answer(branch)
        edges = [{"node": {"name": {"value": name}}} for name in self.devices]
        return {"count": len(edges), "edges": edges}

    def artifact_answer(self, branch: str) -> dict[str, Any]:
        self.artifact_reads += 1
        if branch == "main" and self.moving:
            self.artifacts["main"] = dict(self.moving.pop(0) if len(self.moving) > 1 else self.moving[0])
        edges = []
        for name in self.devices:
            held = self.artifacts[branch].get(name)
            artifacts = []
            if held is not None:
                checksum = {"value": held["checksum"], "updated_at": held["stamp"]}
                node = {"status": {"value": held["status"]}, "checksum": checksum}
                artifacts.append({"node": node})
            edges.append({"node": {"name": {"value": name}, "artifacts": {"edges": artifacts}}})
        return {"count": len(edges), "edges": edges}


class Ctl:
    """`infrahubctl`'s fake: each argument list kept in the fake Infrahub's events; a schema file loaded adds its kinds
    to `main`'s, a load of the devices' file puts the three devices on `main`, and a load of a stage's file marks the
    configurations it changes on its branch."""

    def __init__(self, infrahub: Infrahub) -> None:
        self.infrahub = infrahub
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.infrahub.events.append(("infrahubctl", *argv[1:]))
        if argv[1:3] == ["schema", "load"] and not self.infrahub.unlisted:
            assert argv[4:] == ["--branch", "main"]
            self.infrahub.kinds.update(register.file_kinds(Path(argv[3])))
        if argv[1:3] == ["object", "load"]:
            name = Path(argv[3]).name
            if name == "5-devices.yml":
                self.infrahub.devices = NAMES
            elif name in RENDERS:
                self.infrahub.load(argv[argv.index("--branch") + 1], name)
        return subprocess.CompletedProcess(argv, 0, stdout="")


def hub_for(infrahub: Infrahub) -> tuple[Hub, Ctl]:
    ctl = Ctl(infrahub)
    environ = {"FYLGJA_INFRAHUB_ADDRESS": ADDRESS, "FYLGJA_INFRAHUB_WRITE_TOKEN": "a-tests-token"}
    return connect(environ, ctl=CTL, transport=httpx.MockTransport(infrahub), run=ctl), ctl


def seeded(**kwargs: Any) -> Infrahub:
    """An Infrahub whose `main` holds the fixture's devices, each configuration `Ready`, as a seed leaves it."""
    return Infrahub(devices=NAMES, artifacts={name: ready(f"c-{name}") for name in NAMES}, **kwargs)


def seed_whole(infrahub: Infrahub, out: Path, monkeypatch: pytest.MonkeyPatch, *flags: str) -> int:
    """`seed.main` run as `make infrahub-seed` runs it, the two kinds passed and `flags` after them, over the fake,
    its record written to `out`, each stage timed by the fake's `head`."""
    monkeypatch.setenv("FYLGJA_INFRAHUB_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_INFRAHUB_WRITE_TOKEN", "a-tests-token")
    clock = Clock()
    argv = ["--branch", BRANCH, "--files", str(SEED), "--out", str(out), "--ctl", str(CTL)]
    argv += ["--schema", str(PROBE_KIND), "--schema", str(STAGE_KIND), *flags]
    transport = httpx.MockTransport(infrahub)
    return seed.main(argv, transport=transport, run=Ctl(infrahub), clock=clock, sleep=clock.sleep, head=infrahub.head)


def test_unready_names_each_device_and_why() -> None:
    members = ("n1", "n2", "n3")
    old = A("Ready", "c-old", "s-old")
    new = A("Ready", "c-new", "s-new")
    before = {"n1": old, "n2": old, "n3": old}
    assert seed.unready(before, {"n1": old, "n3": old}, members, ()) == ["n2: no artifact"]
    assert seed.unready(before, {"n1": A("Pending", "", ""), "n2": old, "n3": old}, members, ()) == ["n1: Pending"]
    assert seed.unready(before, {"n1": old, "n2": old, "n3": old}, members, ("n1",)) == ["n1: not regenerated"]
    assert seed.unready(before, {"n1": new, "n2": old, "n3": old}, members, ("n1",)) == []
    assert seed.unready({"n2": old, "n3": old}, {"n1": old, "n2": old, "n3": old}, members, ("n1",)) == []
    assert seed.unready(before, {"n2": old}, ("n3", "n1", "n2"), ("n2",)) == [
        "n1: no artifact",
        "n2: not regenerated",
        "n3: no artifact",
    ]


def test_a_render_that_failed_ends_the_wait_at_once() -> None:
    infrahub = Infrahub(
        devices=NAMES,
        artifacts={name: ready("c0") for name in NAMES},
        generated=[{"n1": ready("c0"), "n2": {"status": "Error", "checksum": "c0", "stamp": "s"}, "n3": ready("c0")}],
    )
    hub, _ = hub_for(infrahub)
    clock = Clock()
    with pytest.raises(seed.RenderFailed) as raised:
        seed.generate(hub, "main", ("n2",), clock=clock, sleep=clock.sleep)
    assert "n2" in str(raised.value)
    assert "n1" not in str(raised.value)
    assert isinstance(raised.value, HubError)
    assert clock.slept == []
    assert infrahub.artifact_reads == 2  # one before the generation is asked, and one after


def test_the_baseline_loads_each_file_in_order_joins_the_group_and_generates() -> None:
    files = sorted(FILES.glob("*.yml"))
    assert len(files) == 7
    pending = {name: {"status": "Pending", "checksum": "", "stamp": ""} for name in NAMES}
    infrahub = Infrahub(generated=[pending, {name: ready("c1") for name in NAMES}])
    hub, _ = hub_for(infrahub)
    clock = Clock()
    seed.baseline(hub, FILES, clock=clock, sleep=clock.sleep)
    loads = [("infrahubctl", "object", "load", str(path), "--branch", "main") for path in files]
    assert infrahub.events == [*loads, ("generate", DEFINITION_ID, "main")]
    assert clock.slept == [2.0]


def test_a_seeded_main_loads_nothing_and_still_generates(capsys: pytest.CaptureFixture[str]) -> None:
    """A load would replace each device's groups, the query groups Infrahub joined it to at its first generation among
    them (design/verified-facts.md, "Infrahub 1.11.11")."""
    infrahub = seeded()
    hub, ctl = hub_for(infrahub)
    clock = Clock()
    seed.baseline(hub, FILES, clock=clock, sleep=clock.sleep)
    assert ctl.calls == []
    assert infrahub.events == [("generate", DEFINITION_ID, "main")]
    assert "main holds the fixture's devices n1, n2, n3 already: loading nothing" in capsys.readouterr().out
    # With `changed` empty, the artifacts already Ready end the wait at its first read: a device counted as changed
    # would wait for a checksum that never moves, to the bound.
    assert clock.slept == []


def test_a_main_holding_part_of_the_fixture_is_refused() -> None:
    partial = Infrahub(devices=("n1",))
    hub, ctl = hub_for(partial)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.baseline(hub, FILES, clock=clock, sleep=clock.sleep)
    assert str(raised.value).startswith("main holds n1 and lacks n2, n3 of the fixture's devices")
    assert "make infrahub-down PURGE=1" in str(raised.value)
    assert ctl.calls == []
    assert partial.events == []

    others = Infrahub(devices=("r1", "r2"))
    hub, ctl = hub_for(others)
    with pytest.raises(HubError) as raised:
        seed.baseline(hub, FILES, clock=clock, sleep=clock.sleep)
    said = str(raised.value)
    assert said.startswith("main holds r1, r2 tagged fylgja, none of them the fixture's devices n1, n2, n3:")
    assert "make infrahub-down PURGE=1" in said
    assert ctl.calls == []
    assert others.events == []


def test_the_seed_refuses_a_main_without_the_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    infrahub = Infrahub(definitions=0)
    hub, ctl = hub_for(infrahub)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.baseline(hub, FILES, clock=clock, sleep=clock.sleep)
    assert str(raised.value) == "main holds no artifact definition device-config: run make infrahub-register"
    assert ctl.calls == []
    assert infrahub.events == []

    # Run whole, the seed is refused before the kind is loaded too: nothing is written.
    assert seed_whole(infrahub, tmp_path / "seed.json", monkeypatch) == 1
    assert "main holds no artifact definition device-config" in capsys.readouterr().err
    assert (infrahub.events, infrahub.kinds) == ([], set())


def test_a_kind_main_lacks_is_loaded_before_the_baseline_and_one_it_holds_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    infrahub = Infrahub(generated=[{name: ready("c1") for name in NAMES}])
    out = tmp_path / "seed.json"
    assert seed_whole(infrahub, out, monkeypatch) == 0
    loads = [("infrahubctl", "object", "load", str(path), "--branch", "main") for path in sorted(FILES.glob("*.yml"))]
    assert infrahub.events[: len(loads) + 3] == [
        ("infrahubctl", "schema", "load", str(PROBE_KIND), "--branch", "main"),
        ("infrahubctl", "schema", "load", str(STAGE_KIND), "--branch", "main"),
        *loads,
        ("generate", DEFINITION_ID, "main"),
    ]
    assert infrahub.kinds == {"FylgjaProbe", "FylgjaStage"}
    capsys.readouterr()

    first = len(infrahub.events)
    assert seed_whole(infrahub, out, monkeypatch) == 0
    again = infrahub.events[first:]
    assert [event for event in again if event[0] == "infrahubctl" and event[1] == "schema"] == []
    assert again[0] == ("generate", DEFINITION_ID, "main"), "a seeded main loads nothing"
    said = capsys.readouterr().out
    assert "main holds FylgjaProbe of fylgja-probe.yml already" in said
    assert "main holds FylgjaStage of fylgja-stage.yml already" in said


def test_a_kind_main_never_lists_lapses_and_a_file_of_no_kind_is_refused(tmp_path: Path) -> None:
    infrahub = Infrahub(unlisted=True)
    hub, _ = hub_for(infrahub)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.schemas(hub, [PROBE_KIND], clock=clock, sleep=clock.sleep)
    said = str(raised.value)
    assert said.startswith("the kinds of fylgja-probe.yml on main not within 120 s: FylgjaProbe"), said
    assert clock.now == register.SCHEMA_WAIT_S

    empty = tmp_path / "empty.yml"
    empty.write_text('version: "1.0"\nnodes: []\n')
    hub, ctl = hub_for(Infrahub())
    with pytest.raises(HubError) as raised:
        seed.schemas(hub, [empty], clock=clock, sleep=clock.sleep)
    assert str(raised.value) == f"{empty} defines no kind"
    assert ctl.calls == []


def refusal(rule: str, said: str) -> Refused:
    return Refused([Finding(rule=rule, severity="error", object="InfrahubEvent", message=said)])


INCOMPLETE = refusal("read.incomplete", "Infrahub counted 7 in InfrahubEvent and answered 8, so the list is not whole.")


def answering(*answers: str | Refused) -> seed.Head:
    """A `head` answering each of `answers` in turn, a `Refused` raised."""
    held = iter(answers)

    def head(name: str) -> str:
        answer = next(held)
        if isinstance(answer, Refused):
            raise answer
        return answer

    return head


def test_a_head_refused_for_a_list_not_whole_is_read_again() -> None:
    """A page of the branch's event log once answered more events than its own `count` just after a generation, and
    `head` refused it (design/verified-facts.md, "Infrahub 1.11.11"): such a refusal is a reading not yet still, read
    again within `QUIET_WAIT_S` (P3-36)."""
    clock = Clock()
    assert seed.settled(answering(INCOMPLETE, "T", "T"), BRANCH, clock=clock, sleep=clock.sleep) == "T"
    assert clock.slept == [seed.QUIET_S] * 2

    clock = Clock()
    assert seed.settled(answering("T", INCOMPLETE, "T", "T"), BRANCH, clock=clock, sleep=clock.sleep) == "T"
    assert clock.slept == [seed.QUIET_S] * 3, "a refused reading breaks the agreement"

    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.settled(answering(*[INCOMPLETE] * 13), BRANCH, clock=clock, sleep=clock.sleep)
    said = str(raised.value)
    assert "third-link's head standing still for 10 s not within 120 s" in said
    assert "counted 7 in InfrahubEvent" in said, "the lapse says the last refusal"

    empty = refusal("scope.empty", "No DcimDevice carries the tag fylgja.")
    clock = Clock()
    with pytest.raises(Refused):
        seed.settled(answering(INCOMPLETE, empty), BRANCH, clock=clock, sleep=clock.sleep)
    assert clock.slept == [seed.QUIET_S], "a refusal of another rule ends it"


def test_a_head_refused_otherwise_ends_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FYLGJA_INFRAHUB_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_INFRAHUB_WRITE_TOKEN", "a-tests-token")
    out = tmp_path / "seed.json"
    infrahub = seeded()
    clock = Clock()
    argv = ["--branch", BRANCH, "--files", str(SEED), "--out", str(out), "--ctl", str(CTL)]
    empty = answering(refusal("scope.empty", "No DcimDevice on branch third-link carries the tag fylgja."))
    transport = httpx.MockTransport(infrahub)
    assert seed.main(argv, transport=transport, run=Ctl(infrahub), clock=clock, sleep=clock.sleep, head=empty) == 1
    assert "scope.empty InfrahubEvent: No DcimDevice on branch third-link" in capsys.readouterr().err
    assert not out.exists()


def test_a_stages_time_is_the_readers_head_once_it_stands_still() -> None:
    answers = iter(["T1", "T2", "T2", "T3", "T3"])
    asked: list[str] = []

    def head(name: str) -> str:
        asked.append(name)
        return next(answers)

    hub, _ = hub_for(seeded())
    clock = Clock()
    stages = seed.branch(hub, BRANCH, SEED, head=head, clock=clock, sleep=clock.sleep)
    assert stages == [{"label": "third-link", "at": "T2"}, {"label": "n1-address", "at": "T3"}]
    assert asked == [BRANCH] * 5
    assert clock.slept == [seed.QUIET_S] * 3, "read again QUIET_S on, until two readings agree"


def test_the_edits_are_the_two_in_order() -> None:
    edits = (
        seed.Edit("third-link", "stages/1-third-link.yml", ("n1", "n3")),
        seed.Edit("n1-address", "stages/2-n1-address.yml", ("n1",)),
    )
    assert edits == seed.EDITS
    for edit in seed.EDITS:
        assert (SEED / edit.file).is_file(), edit.file


def test_the_branch_is_remade_and_refused_where_it_does_not_see_the_definition(
    capsys: pytest.CaptureFixture[str],
) -> None:
    kept = seeded(branches=(BRANCH,))
    hub, _ = hub_for(kept)
    clock = Clock()
    seed.branch(hub, BRANCH, SEED, head=kept.head, clock=clock, sleep=clock.sleep)
    assert kept.events[:2] == [("BranchDelete", BRANCH), ("BranchCreate", BRANCH)]
    assert "sync_with_git: false" in kept.mutations[1]
    assert "deleted third-link, an earlier seed's" in capsys.readouterr().out

    unseen = seeded(branch_definitions=0)
    hub, ctl = hub_for(unseen)
    with pytest.raises(HubError) as raised:
        seed.branch(hub, BRANCH, SEED, head=unseen.head, clock=clock, sleep=clock.sleep)
    assert str(raised.value) == (
        "third-link holds no artifact definition device-config: run make infrahub-register, then make infrahub-seed"
    )
    assert ctl.calls == []
    assert unseen.events == [("BranchCreate", BRANCH)]

    assert seed.main(["--branch", "main", "--files", str(SEED), "--out", "o", "--ctl", str(CTL)]) == 2
    assert "--branch main" in capsys.readouterr().err


def test_a_delete_refused_stops_the_seed_naming_the_branch() -> None:
    """Kept, the earlier seed's branch would be listed after the create failed, and loaded again."""
    kept = seeded(branches=(BRANCH,), undeleting=True)
    hub, ctl = hub_for(kept)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.branch(hub, BRANCH, SEED, head=kept.head, clock=clock, sleep=clock.sleep)
    assert str(raised.value) == "deleting third-link, an earlier seed's: BranchDelete answered no ok"
    assert kept.events == [("BranchDelete", BRANCH)]
    assert ctl.calls == []
    assert clock.slept == []


def test_a_create_unanswered_is_read_for_the_branch_within_its_bound() -> None:
    """A create once went unanswered past the request's 60 s, its branch made 75.1 s after it was sent
    (design/verified-facts.md, "Infrahub 1.11.11")."""
    late = seeded(unanswered=3)
    hub, _ = hub_for(late)
    clock = Clock()
    stages = seed.branch(hub, BRANCH, SEED, head=late.head, clock=clock, sleep=clock.sleep)
    assert [stage["label"] for stage in stages] == ["third-link", "n1-address"]
    assert late.events[0] == ("BranchCreate", BRANCH)
    assert clock.slept[:2] == [2.0, 2.0]  # listed at the third read

    never = seeded(unanswered=math.inf)
    hub, ctl = hub_for(never)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        seed.branch(hub, BRANCH, SEED, head=never.head, clock=clock, sleep=clock.sleep)
    said = str(raised.value)
    assert said.startswith("third-link, after its BranchCreate failed (POST /graphql/main was not answered")
    assert said.endswith("not within 120 s: third-link is not listed")
    assert clock.now == 120
    assert ctl.calls == []


def test_each_edit_is_loaded_generated_waited_for_and_timed_in_order() -> None:
    infrahub = seeded()
    hub, _ = hub_for(infrahub)
    clock = Clock()
    stages = seed.branch(hub, BRANCH, SEED, head=infrahub.head, clock=clock, sleep=clock.sleep)
    first, second = (("infrahubctl", "object", "load", str(SEED / e.file), "--branch", BRANCH) for e in seed.EDITS)
    # The server's clock: the branch made at 10 s, the first load at 20 s, its generation at 30 s, the second load at
    # 40 s and its generation at 50 s; after each generation the branch's newest event is its own, then Infrahub's.
    times = zip(seed.EDITS, (33, 53), strict=True)
    marked = [("FylgjaStageCreate", BRANCH, e.label, server(at), seed.described(e)) for e, at in times]
    assert infrahub.events == [
        ("BranchCreate", BRANCH),
        first,
        ("generate", DEFINITION_ID, BRANCH),
        ("head", BRANCH, server(30.5)),
        *[("head", BRANCH, server(33))] * 2,
        marked[0],
        second,
        ("generate", DEFINITION_ID, BRANCH),
        ("head", BRANCH, server(50.5)),
        *[("head", BRANCH, server(53))] * 2,
        marked[1],
    ]
    assert stages == [{"label": "third-link", "at": server(33)}, {"label": "n1-address", "at": server(53)}]
    # Each generation's wait passed at its first read; `head` was read every 10 s until two readings agreed.
    assert clock.slept == [10.0] * 4
    assert {name: held["checksum"] for name, held in infrahub.artifacts[BRANCH].items()} == {
        "n1": "c-n1+1-third-link.yml+2-n1-address.yml",
        "n2": "c-n2",
        "n3": "c-n3+1-third-link.yml",
    }


def test_main_seeds_main_then_the_branch_and_writes_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    infrahub = seeded()
    out = tmp_path / "seed.json"
    assert seed_whole(infrahub, out, monkeypatch) == 0
    assert json.loads(out.read_text()) == {
        "branch": BRANCH,
        "scope": "tag:fylgja",
        "stages": [{"label": "third-link", "at": server(33)}, {"label": "n1-address", "at": server(53)}],
        "marks": ["third-link", "n1-address"],
        "proposed_change": None,
    }
    assert infrahub.events[:4] == [
        ("infrahubctl", "schema", "load", str(PROBE_KIND), "--branch", "main"),
        ("infrahubctl", "schema", "load", str(STAGE_KIND), "--branch", "main"),
        ("generate", DEFINITION_ID, "main"),
        ("BranchCreate", BRANCH),
    ]


def test_a_wait_that_lapses_leaves_no_seed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "seed.json"
    cases = [
        (seeded(stuck=(("2-n1-address.yml", "n1"),)), ("n1: not regenerated", "180 s")),
        (seeded(restless=True), ("third-link's head standing still for 10 s", "120 s")),
    ]
    for infrahub, says in cases:
        out.write_text('{"branch": "an earlier run\'s"}\n')
        assert seed_whole(infrahub, out, monkeypatch) == 1
        said = capsys.readouterr().err
        for words in says:
            assert words in said
        assert not out.exists()


def test_the_file_is_the_five_members(tmp_path: Path) -> None:
    path = tmp_path / "seed.json"
    path.write_text("an earlier run's\n")
    earlier = path.stat().st_ino
    stages = [
        {"label": "third-link", "at": "2026-11-09T13:44:54.984697+00:00"},
        {"label": "n1-address", "at": "2026-11-09T13:45:12.000001+00:00"},
    ]
    marks = ["third-link", "n1-address"]
    seed.write(path, "third-link", stages, marks=marks)
    text = path.read_text()
    held = {"branch": "third-link", "scope": "tag:fylgja", "stages": stages, "marks": marks, "proposed_change": None}
    assert json.loads(text) == held
    assert text.endswith("}\n")
    # Written whole beside it and renamed over it: a new file, and nothing else left in the directory.
    assert path.stat().st_ino != earlier
    assert [found.name for found in tmp_path.iterdir()] == ["seed.json"]

    proposed = {"id": "18e6cba4-0000-0000-0000-000000000001", "name": "Rehearse third-link"}
    seed.write(path, "third-link", stages, marks=marks, proposed_change=proposed)
    assert json.loads(path.read_text()) == held | {"proposed_change": proposed}
    seed.write(path, "third-link", stages)
    assert json.loads(path.read_text()) == held | {"marks": []}


def test_an_earlier_seeds_marks_and_open_proposed_change_are_removed_before_the_branch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A mark outlives its branch, and an open proposed change outlives its branch's delete (D-088;
    design/verified-facts.md, "Infrahub 1.11.11"), so both are removed whether or not the branch is listed."""
    earlier = ((BRANCH, "third-link"), (BRANCH, "n1-address"), ("another", "third-link"))
    proposed = ((BRANCH, "open"), (BRANCH, "closed"), ("another", "open"))
    for listed in (True, False):
        infrahub = seeded(branches=(BRANCH,) if listed else (), marks=earlier, proposed=proposed)
        hub, _ = hub_for(infrahub)
        clock = Clock()
        seed.branch(hub, BRANCH, SEED, head=infrahub.head, clock=clock, sleep=clock.sleep)
        removed = [
            ("FylgjaStageDelete", "mark-1"),
            ("FylgjaStageDelete", "mark-2"),
            ("CoreProposedChangeDelete", "pc-4"),
        ]
        branch = [("BranchDelete", BRANCH)] if listed else []
        assert infrahub.events[: len(removed) + len(branch) + 1] == [*removed, *branch, ("BranchCreate", BRANCH)]
        # The other branch's mark and proposed change, and the branch's closed one, are kept; the branch's marks are
        # this run's.
        assert [(mark["id"], mark["branch"]) for mark in infrahub.marks][:1] == [("mark-3", "another")]
        assert [mark["label"] for mark in infrahub.marks if mark["branch"] == BRANCH] == ["third-link", "n1-address"]
        assert [(held["id"], held["state"]) for held in infrahub.proposed] == [("pc-5", "closed"), ("pc-6", "open")]
        said = capsys.readouterr().out
        assert "removed 2 marks of third-link, an earlier seed's" in said
        assert "removed the open proposed change pc-4 of third-link, an earlier seed's" in said


def test_each_stage_is_marked_at_its_time() -> None:
    """One `FylgjaStage` a stage on `main`, its `as_of` the stage's time verbatim, sent as a `String` variable: a
    `DateTime!` one is refused, and the value is answered as written (design/verified-facts.md, "Infrahub 1.11.11";
    P5-29)."""
    infrahub = seeded()
    hub, _ = hub_for(infrahub)
    clock = Clock()
    stages = seed.branch(hub, BRANCH, SEED, head=infrahub.head, clock=clock, sleep=clock.sleep)
    creates = [text for text in infrahub.mutations if "FylgjaStageCreate" in text]
    assert len(creates) == len(stages) == 2
    assert all("$at: String!" in text for text in creates)
    held = [(mark["branch"], mark["label"], mark["as_of"], mark["description"]) for mark in infrahub.marks]
    staged = zip(stages, seed.EDITS, strict=True)
    assert held == [(BRANCH, stage["label"], stage["at"], seed.described(edit)) for stage, edit in staged]
    said = "the seed's stage third-link: stages/1-third-link.yml and its configurations"
    assert seed.described(seed.EDITS[0]) == said


def test_the_proposed_change_is_made_only_by_the_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Infrahub runs a proposed change's checks when it is created, so without the flag the seed makes none, and the
    maintainer's opening one is what starts the rehearsal (D-088)."""
    out = tmp_path / "seed.json"
    infrahub = seeded()
    assert seed_whole(infrahub, out, monkeypatch) == 0
    assert [event for event in infrahub.events if event[0] == "CoreProposedChangeCreate"] == []
    assert (infrahub.proposed, json.loads(out.read_text())["proposed_change"]) == ([], None)

    infrahub = seeded()
    assert seed_whole(infrahub, out, monkeypatch, "--proposed-change") == 0
    made = [event for event in infrahub.events if event[0] == "CoreProposedChangeCreate"]
    assert made == [("CoreProposedChangeCreate", "Rehearse third-link", BRANCH)]
    # Made last, after both marks, so the rehearsal it starts finds them.
    assert infrahub.events[-1] == made[0]
    [text] = [text for text in infrahub.mutations if "CoreProposedChangeCreate" in text]
    assert 'destination_branch: {value: "main"}' in text
    assert "is_draft: {value: false}" in text
    record = json.loads(out.read_text())
    assert record["proposed_change"] == {"id": infrahub.proposed[0]["id"], "name": "Rehearse third-link"}
    assert record["marks"] == ["third-link", "n1-address"]

    # A second run with the flag removes the first's and makes its own: one open, of another id.
    first = infrahub.proposed[0]["id"]
    assert seed_whole(infrahub, out, monkeypatch, "--proposed-change") == 0
    assert [(held["branch"], held["state"]) for held in infrahub.proposed] == [(BRANCH, "open")]
    assert json.loads(out.read_text())["proposed_change"]["id"] == infrahub.proposed[0]["id"] != first


@pytest.mark.parametrize(
    ("token", "status", "says", "asked"),
    [
        (None, 2, "FYLGJA_INFRAHUB_TOKEN is not set", []),
        ("not a token", 2, "the reader's FYLGJA_INFRAHUB_ADDRESS, FYLGJA_INFRAHUB_TOKEN or FYLGJA_INFRAHUB_CA", []),
        ("a-refused-token", 1, "Infrahub refused the token FYLGJA_INFRAHUB_TOKEN holds", ["/api/info"]),
    ],
    ids=["unset", "malformed", "refused"],
)
def test_the_readers_connect_failing_ends_the_seed_with_nothing_removed(
    token: str | None,
    status: int,
    says: str,
    asked: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a `head` given, each stage is timed by the reader's, read with the reader's token and never the
    writer's; it is connected before anything is removed or written."""
    monkeypatch.setenv("FYLGJA_INFRAHUB_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_INFRAHUB_WRITE_TOKEN", "a-tests-token")
    if token is not None:
        monkeypatch.setenv("FYLGJA_INFRAHUB_TOKEN", token)
    out = tmp_path / "seed.json"
    out.write_text("an earlier run's\n")
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(401, json={"errors": [{"message": "Invalid token"}]})

    argv = ["--branch", BRANCH, "--files", str(SEED), "--out", str(out), "--ctl", str(CTL), "--schema", str(PROBE_KIND)]
    assert seed.main(argv, transport=httpx.MockTransport(answer), run=Ctl(Infrahub())) == status
    assert says in capsys.readouterr().err
    assert ([request.url.path for request in sent], out.read_text()) == (asked, "an earlier run's\n")


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        ([], "the following arguments are required"),
        (["--branch", "third-link", "--files", "f", "--out", "o", "--ctl", "c"], "FYLGJA_INFRAHUB_ADDRESS is not set"),
    ],
    ids=["no-arguments", "no-address"],
)
def test_a_command_line_not_understood_or_a_variable_not_set_is_exit_2(
    argv: list[str], says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(argv) == 2
    assert says in capsys.readouterr().err
