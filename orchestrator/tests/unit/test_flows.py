"""The five flows (T025; data-model §7, R-08; FR-018, FR-021), their bodies called plain with
the adapter and the core stubbed, which keeps `make test` in budget (research §5.17): the
read filed and named, the check passed through, the create and its dry run, the step's
default target, its record and its moved rule, and the plan held to the golden captured from
`fylgja stage plan` byte for byte. Each stage is resolved by the adapter's real rules over
`test_stages`' reader and stamper; only the branch's read, the core and the store's ids are
stubbed."""

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest
from prefect import Flow

from fylgja_orchestrator.adapters.infrahub import __main__ as tool
from fylgja_orchestrator.adapters.infrahub import snapshot as snapshots
from fylgja_orchestrator.adapters.infrahub import stages
from fylgja_orchestrator.adapters.infrahub.session import (
    BUILD_READ,
    MOVED_ALWAYS,
    MOVED_NEVER,
    MOVED_RESOLVED,
    Built,
    Session,
)
from fylgja_orchestrator.core import Answer, CoreFailure, File, RunRef
from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents.findings import (
    INFO,
    OP_COMPILE,
    OP_INTENT_READ,
    OP_RUN_READ,
    OP_SCHEMA_CHECK,
    OP_TWIN_CREATE,
    OP_TWIN_DIFF,
    OP_TWIN_SHOW,
    OP_TWIN_STEP,
    REJECTION,
    WARNING,
    Document,
    Finding,
    Findings,
    new_document,
)
from fylgja_orchestrator.flows import common, intent_read, schema_check, stage_plan, twin_create, twin_step
from fylgja_orchestrator.record import (
    FLOW_CREATE,
    FLOW_STEP,
    ChangeRef,
    StageRef,
    Store,
    new_record,
)

from .test_stages import CABLED_AT, LIVE_AT, REGISTRY, story

DATA = Path(__file__).resolve().parents[1] / "data"
GOLDEN = Path(__file__).resolve().parents[1] / "golden"
SCOPE = "tag:fylgja"
RUN = "flow-run-1"


def snap(name: str) -> dict:
    return snapshots.read(DATA / "snapshot" / f"{name}.json")


THREE = snap("three-node")
MIXED = snap("mixed")


# The fakes.


def show_of(snapshot_id: str | None = None, **record) -> Document:
    """twin.show's document, its record naming snapshot_id, or no twin when None."""
    block = {"record": None}
    if snapshot_id is not None:
        block["record"] = {"snapshot_id": snapshot_id, "scope": SCOPE, **record}
    return Document(OP_TWIN_SHOW, "ok", None, Findings(), {"show": block})


def detached(op: str, workflow_id: str, out=()) -> Answer:
    doc = Document(op, "ok", {"run_id": "r-1"}, Findings([
        Finding(WARNING, "host.memory.low", "host", "the host is short of memory", "host_check"),
        Finding(INFO, "run.detached", f"{workflow_id} r-1", f"run {workflow_id} r-1 started; read it", "start"),
    ]), {"snapshot_id": "5" * 64, "bundle_id": "b" * 64})
    return Answer(op, run=RunRef(workflow_id, "r-1"), out=list(out), document=doc)


def ended(workflow_id: str, status: str = "ok", out=()) -> Answer:
    doc = Document(OP_RUN_READ, status, {"run_id": "r-1"}, Findings([
        Finding(WARNING, "host.memory.low", "host", "the host is short of memory", "host_check"),
        Finding(INFO, "run.done", "r-1", "the run ended", "record"),
    ]), {"bundle_id": "b" * 64, "cleanup": None})
    return Answer(OP_RUN_READ, run=RunRef(workflow_id, "r-1", "completed"), out=list(out), document=doc)


class FakeCore:
    """The core's client as the flows call it, recording every call: `shows` answered in
    order, the last repeated."""

    def __init__(self, shows=(), started=None, ran=None, dry=None, compiles=(), diffs=()):
        self.shows = list(shows) or [show_of()]
        self.started, self.ran, self.dry = started, ran, dry
        self.compiles, self.diffs = list(compiles), list(diffs)
        self.calls = []
        self.fail = None

    def show(self):
        self.calls.append(("show",))
        return self.shows.pop(0) if len(self.shows) > 1 else self.shows[0]

    def _out(self, answer, on_out):
        for line in answer.out:
            on_out(line)
        return answer

    def start(self, op, args=None, files=(), on_out=None):
        self.calls.append(("start", op, dict(args or {}), list(files)))
        if self.fail:
            raise self.fail
        return self._out(self.started, on_out)

    def read(self, workflow_id, run_id="", render=True, on_out=None):
        self.calls.append(("read", workflow_id, run_id))
        return self._out(self.ran, on_out)

    def dry_run(self, op, args=None, files=(), on_out=None):
        self.calls.append(("dry_run", op, dict(args or {}), list(files)))
        return self._out(self.dry, on_out)

    def compile(self, snapshot, files=(), out=""):
        self.calls.append(("compile", snapshot, list(files)))
        return self.compiles.pop(0)

    def diff(self, from_, to, files=()):
        self.calls.append(("diff", from_, to, list(files)))
        return self.diffs.pop(0)

    def named(self, kind):
        return [c for c in self.calls if c[0] == kind]


class StorySession(Session):
    """The adapter's session over `test_stages`' story: the real resolution, its reader and
    stamper the fakes; each branch's read answered by `takes`, keyed by (branch, at)."""

    def __init__(self, takes=None, scope=SCOPE):
        r, s = story()
        super().__init__(REGISTRY, scope, r, s, [])
        self.takes = takes or {}
        self.taken = []

    def take(self, branch, at, scope, observed_at=None):
        self.taken.append((branch, at, scope))
        return self.takes.get((branch, at), (THREE, Findings()))


def deps_of(tmp_path, core=None, session=None, **kw) -> tuple[common.Deps, list, list]:
    """The flow's Deps over a store under tmp_path, its out lines and every session opened."""
    lines, opened = [], []

    def open_(op, subject, scope, probes_path, environ):
        opened.append((op, scope, probes_path))
        return session, None

    deps = common.Deps(core=core or FakeCore(), store=Store(tmp_path / "orchestrator"),
                       environ={"FYLGJA_DEFAULT_SCOPE": SCOPE}, out=lines.append, open=open_,
                       flow_run_id=RUN, **kw)
    return deps, lines, opened


def record_at(deps, label: str, at: str, snapshot_id: str, flow=FLOW_CREATE):
    deps.store.write_record(new_record(StageRef("change-1", label, at), ChangeRef("pc-1", "change-1"),
                                       snapshot_id, "run-0", flow))


# The flows as Prefect sees them.


@pytest.mark.parametrize("module, name, params", [
    (intent_read, "intent-read", ["branch", "at", "stage", "scope", "probes_path", "out"]),
    (schema_check, "schema-check", ["branch"]),
    (twin_create, "twin-create", ["branch", "stage", "scope", "probes_path", "dry_run"]),
    (twin_step, "twin-step", ["stage", "scope", "probes_path", "allow_restart", "wait", "dry_run"]),
    (stage_plan, "stage-plan", ["branch", "scope", "probes_path"]),
])
def test_each_flow_is_named_with_its_parameters(module, name, params):
    """data-model §7: each @flow by its name, its parameters its fylgja-cli flags, and its body
    the same parameters after the Deps."""
    f = next(v for v in vars(module).values() if isinstance(v, Flow))
    assert f.name == name == module.FLOW
    assert list(inspect.signature(f.fn).parameters) == params
    assert list(inspect.signature(module.run).parameters) == ["deps", *params]


def test_publish_with_no_run_files_nothing():
    doc = new_document(OP_SCHEMA_CHECK, {"branch": "b"})
    assert common.publish("schema-check", doc) is doc
    assert common.flow_run_id() == ""
    assert common.artifact_key("twin-create", "0f1e") == "fylgja-twin-create-0f1e"


def test_deps_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FYLGJA_API_ADDRESS", "127.0.0.1:7699")
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_ROOT", str(tmp_path))
    deps = common.Deps.from_env()
    assert deps.core.address == "127.0.0.1:7699"
    assert deps.store.root == tmp_path
    assert deps.flow_run_id == ""


def test_composed_drops_the_detach_and_the_runs_repeats():
    found = Findings([Finding(WARNING, "stage.main.moved", "b", "main moved", "resolve")])
    doc = common.composed(OP_TWIN_CREATE, {"branch": "b"}, found, ended("fylgja-provision", "failed"),
                          detached(OP_TWIN_CREATE, "fylgja-provision"), {"stage": {"ref": "b/l"}})
    assert doc.operation == OP_TWIN_CREATE and doc.status == "failed"
    assert doc.subject == {"branch": "b", "run_id": "r-1"}
    assert [f.rule for f in doc.findings] == ["stage.main.moved", "host.memory.low", "run.done"]
    assert doc.blocks == {"snapshot_id": "5" * 64, "bundle_id": "b" * 64, "stage": {"ref": "b/l"}}


# intent-read and schema-check.


def test_intent_read_files_the_snapshot_and_names_it(tmp_path):
    doc = new_document(OP_INTENT_READ, {"branch": "fylgja-fixture", "out": "s.json", "scope": SCOPE})
    doc.set("snapshot_id", THREE["snapshot_id"])
    notes = ["wrote s.json: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts (branch fylgja-fixture, "
             f"scope {SCOPE}, schema fixture); snapshot {THREE['snapshot_id']}"]
    calls = []

    def read(*args):
        calls.append(args[:-1])
        return tool.Answer(doc, notes, THREE)

    deps, lines, _ = deps_of(tmp_path, read=read)
    got = intent_read.run(deps, "fylgja-fixture", "", None, None, None, "s.json")
    assert got is doc
    assert calls == [("fylgja-fixture", "", None, None, None, "s.json")]
    path = deps.store.path(THREE["snapshot_id"])
    assert deps.store.fetch(THREE["snapshot_id"]) == THREE
    assert lines == [notes[0] + f", stored at {path}"]


def test_intent_read_refused_files_nothing(tmp_path):
    doc = new_document(OP_INTENT_READ, {"branch": "b"}, [Finding(REJECTION, "scope.empty", SCOPE, "no device")])
    deps, lines, _ = deps_of(tmp_path, read=lambda *a: tool.Answer(doc))
    assert intent_read.run(deps, branch="b", out="s.json") is doc
    assert lines == [] and not deps.store.snapshots.exists()


def test_intent_read_a_store_that_cannot_file(tmp_path):
    doc = new_document(OP_INTENT_READ, {"branch": "b", "out": "s.json"})
    doc.set("stage", {"ref": "b/l"})
    deps, lines, _ = deps_of(tmp_path, read=lambda *a: tool.Answer(doc, ["stage b/l: …", "wrote s.json: …"], THREE))
    deps.store.root.mkdir()
    (deps.store.root / "snapshots").write_text("not a directory")
    got = intent_read.run(deps, branch="b", out="s.json")
    assert got.status == "error" and got.findings[0].rule == "operation.failed"
    assert got.blocks["stage"] == {"ref": "b/l"}
    assert lines == ["stage b/l: …"]


def test_schema_check_is_passed_through(tmp_path):
    doc = new_document(OP_SCHEMA_CHECK, {"branch": "b"})
    deps, lines, _ = deps_of(tmp_path, schema_check=lambda branch, env: tool.Answer(doc, [f"checked {branch}"]))
    assert schema_check.run(deps, "b") is doc
    assert lines == ["checked b"]


# twin-create.


def created_core(snapshot_id: str) -> FakeCore:
    return FakeCore(shows=[show_of(snapshot_id)],
                    started=detached(OP_TWIN_CREATE, "fylgja-provision", ["snapshot_id …"]),
                    ran=ended("fylgja-provision", out=["twin ready: …"]))


def test_create_from_a_stage(tmp_path):
    core = created_core(THREE["snapshot_id"])
    session = StorySession({("change-1", CABLED_AT): (THREE, Findings([Finding(WARNING, "w.read", "n1", "r")]))})
    deps, lines, opened = deps_of(tmp_path, core, session)
    doc = twin_create.run(deps, stage="change-1/cabled")

    assert opened == [(OP_TWIN_CREATE, SCOPE, None)]
    assert session.taken == [("change-1", CABLED_AT, SCOPE)]
    assert lines == ['stage change-1/cabled: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), '
                     '"after the link is cabled"', "snapshot_id …", "twin ready: …"]
    path = deps.store.path(THREE["snapshot_id"])
    (start,) = core.named("start")
    assert start[1:3] == (OP_TWIN_CREATE, {"snapshot": str(path)})
    assert start[3] == [File(str(path), path.read_bytes())]
    assert core.named("read") == [("read", "fylgja-provision", "r-1")]

    assert doc.operation == OP_TWIN_CREATE and doc.status == "ok"
    assert doc.subject == {"branch": "change-1", "at": CABLED_AT, "stage": "change-1/cabled", "scope": SCOPE,
                           "run_id": "r-1"}
    assert doc.blocks["stage"]["ref"] == "change-1/cabled" and doc.blocks["stage"]["at_source"] == "written"
    assert [(f.rule, f.step) for f in doc.findings] == [("w.read", "read"), ("host.memory.low", "host_check"),
                                                         ("run.done", "record")]
    findings.validate(doc.to_dict())

    rec = deps.store.read_record()
    assert rec.to_dict() | {"written_at": ""} == {
        "record_version": "1", "stage": {"branch": "change-1", "label": "cabled", "at": CABLED_AT},
        "proposed_change": {"id": "pc-1", "branch": "change-1"}, "snapshot_id": THREE["snapshot_id"],
        "flow_run_id": RUN, "flow": FLOW_CREATE, "written_at": ""}


def test_create_from_a_branch_removes_the_record(tmp_path):
    core = created_core(THREE["snapshot_id"])
    session = StorySession({("fylgja-fixture", ""): (THREE, Findings())})
    deps, lines, _ = deps_of(tmp_path, core, session)
    record_at(deps, "cabled", CABLED_AT, MIXED["snapshot_id"])
    doc = twin_create.run(deps, branch="fylgja-fixture")
    assert doc.status == "ok" and "stage" not in doc.blocks
    assert doc.subject == {"branch": "fylgja-fixture", "scope": SCOPE, "run_id": "r-1"}
    assert deps.store.read_record() is None
    assert deps.store.has(THREE["snapshot_id"])


def test_create_whose_twin_does_not_stand_keeps_the_record(tmp_path):
    core = created_core(MIXED["snapshot_id"])
    core.ran = ended("fylgja-provision", "failed")
    deps, _, _ = deps_of(tmp_path, core, StorySession())
    record_at(deps, "cabled", CABLED_AT, MIXED["snapshot_id"])
    doc = twin_create.run(deps, stage="change-1/live")
    assert doc.status == "failed"
    assert deps.store.read_record().stage.label == "cabled"


def test_create_dry_run_reaches_the_cores_dry_run_and_writes_no_record(tmp_path):
    dry = Answer(OP_TWIN_CREATE, out=["dry run: no lab …"], document=Document(
        OP_TWIN_CREATE, "ok", {"branch": "x", "snapshot": "p"}, Findings(), {"bundle_id": "b" * 64, "dry_run": {}}))
    core = FakeCore(dry=dry)
    deps, lines, _ = deps_of(tmp_path, core, StorySession())
    doc = twin_create.run(deps, stage="change-1/cabled", dry_run=True)
    (call,) = core.named("dry_run")
    assert call[1:3] == (OP_TWIN_CREATE, {"snapshot": str(deps.store.path(THREE["snapshot_id"]))})
    assert core.named("start") == [] and core.named("show") == []
    assert lines[-1] == "dry run: no lab …"
    assert doc.subject == {"branch": "change-1", "at": CABLED_AT, "stage": "change-1/cabled", "scope": SCOPE}
    assert doc.blocks["dry_run"] == {} and doc.blocks["stage"]["label"] == "cabled"
    assert deps.store.read_record() is None


@pytest.mark.parametrize("kw, rule, object, step", [
    ({}, "operation.failed", OP_TWIN_CREATE, ""),
    ({"stage": "a/b/c"}, "stage.ref.invalid", "a/b/c", "start"),
    ({"stage": "change-1/cabled", "branch": "b"}, "stage.flags.conflict", "--branch", "start"),
    ({"branch": "b", "scope": "fylgja"}, "scope.invalid", "fylgja", "start"),
])
def test_create_guards_before_any_read(tmp_path, kw, rule, object, step):
    deps, _, opened = deps_of(tmp_path, FakeCore(), StorySession())
    doc = twin_create.run(deps, **kw)
    assert doc.status == "error" and doc.exit_code == 2
    assert [(f.rule, f.object, f.step) for f in doc.findings] == [(rule, object, step)]
    assert opened == []


def test_create_refused_at_resolution_and_at_read(tmp_path):
    core = FakeCore()
    deps, _, _ = deps_of(tmp_path, core, StorySession())
    doc = twin_create.run(deps, stage="change-1/gone")
    assert doc.status == "rejected" and [(f.rule, f.step) for f in doc.findings] == [("stage.unknown", "resolve")]
    assert "stage" not in doc.blocks

    refused = Findings([Finding(REJECTION, "scope.empty", SCOPE, "no device")])
    deps, _, _ = deps_of(tmp_path, core, StorySession({("change-1", CABLED_AT): (None, refused)}))
    doc = twin_create.run(deps, stage="change-1/cabled")
    assert doc.status == "rejected" and [(f.rule, f.step) for f in doc.findings] == [("scope.empty", "read")]
    assert doc.blocks["stage"]["label"] == "cabled"
    assert core.calls == [] and not deps.store.snapshots.exists()


def test_create_the_core_unreachable(tmp_path):
    core = FakeCore()
    core.fail = CoreFailure("api.unreachable", "127.0.0.1:7650", "the API cannot be reached")
    warned = Findings([Finding(WARNING, "w", "o", "m")])
    deps, _, _ = deps_of(tmp_path, core, StorySession({("b", ""): (THREE, warned)}))
    doc = twin_create.run(deps, branch="b")
    assert doc.status == "error" and [f.rule for f in doc.findings] == ["w", "api.unreachable"]


# twin-step.


def stepped_core(*shows) -> FakeCore:
    return FakeCore(shows=list(shows), started=detached(OP_TWIN_STEP, "fylgja-step", ["twin: …"]),
                    ran=ended("fylgja-step", out=["step …"]))


def twin_at(snapshot_id, at=CABLED_AT, **record):
    return show_of(snapshot_id, branch="change-1", at=at, **record)


def test_step_by_default_to_the_next_stage(tmp_path):
    core = stepped_core(twin_at(THREE["snapshot_id"]), twin_at(MIXED["snapshot_id"], LIVE_AT))
    session = StorySession({("change-1", LIVE_AT): (MIXED, Findings())})
    deps, lines, opened = deps_of(tmp_path, core, session)
    record_at(deps, "cabled", CABLED_AT, THREE["snapshot_id"])
    doc = twin_step.run(deps)

    assert opened == [(OP_TWIN_STEP, SCOPE, None)]
    assert lines[0].startswith("stage change-1/live: branch change-1 at 2026-10-16T17:30:00.000000+00:00 (given)")
    (start,) = core.named("start")
    assert start[1:3] == (OP_TWIN_STEP, {"snapshot": str(deps.store.path(MIXED["snapshot_id"]))})
    assert doc.operation == OP_TWIN_STEP and doc.status == "ok"
    assert doc.subject == {"branch": "change-1", "at": LIVE_AT, "stage": "change-1/live", "scope": SCOPE,
                           "run_id": "r-1"}
    assert doc.blocks["stage"]["label"] == "live"
    findings.validate(doc.to_dict())
    rec = deps.store.read_record()
    assert (rec.stage.label, rec.snapshot_id, rec.flow, rec.flow_run_id) == ("live", MIXED["snapshot_id"], FLOW_STEP,
                                                                              RUN)


@pytest.mark.parametrize("held, shown", [
    (None, None),
    (None, "b9"),
    ("cabled", None),
    ("cabled", "other"),
])
def test_step_with_no_stage_needs_the_record_trusted(tmp_path, held, shown):
    """US6 scenario 2: a record twin show does not confirm names no next stage."""
    core = FakeCore(shows=[twin_at(shown * 32)] if shown else [show_of()])
    deps, _, opened = deps_of(tmp_path, core, StorySession())
    if held:
        record_at(deps, held, CABLED_AT, THREE["snapshot_id"])
    doc = twin_step.run(deps)
    assert doc.status == "rejected" and doc.exit_code == 1
    assert [(f.rule, f.object, f.step) for f in doc.findings] == [("step.target.required", "--stage", "start")]
    assert opened == [] and core.named("start") == []


def test_step_given_a_stage_while_the_record_is_distrusted(tmp_path):
    core = stepped_core(twin_at(MIXED["snapshot_id"], LIVE_AT), twin_at(THREE["snapshot_id"]))
    deps, _, _ = deps_of(tmp_path, core, StorySession())
    record_at(deps, "branch-point", "2026-10-16T17:20:19.944651Z", "a" * 64)
    doc = twin_step.run(deps, stage="change-1/cabled")
    assert doc.status == "ok"
    assert "stage.twin.moved" not in [f.rule for f in doc.findings]
    assert deps.store.read_record().stage.label == "cabled"


def test_step_warns_the_records_stage_moved(tmp_path):
    """US6 scenario 3: the record's stage no longer resolves to its (branch, at)."""
    earlier = "2026-10-16T17:24:00.000000+00:00"
    core = stepped_core(twin_at(THREE["snapshot_id"], earlier))
    deps, _, _ = deps_of(tmp_path, core, StorySession({("change-1", LIVE_AT): (MIXED, Findings())}))
    record_at(deps, "cabled", earlier, THREE["snapshot_id"])
    doc = twin_step.run(deps)
    moved = [f for f in doc.findings if f.rule == "stage.twin.moved"]
    assert [(f.severity, f.object) for f in moved] == [(WARNING, "change-1/cabled")]
    assert moved[0].message == (
        f"the twin was built from stage change-1/cabled at branch change-1, at {earlier} (written); change-1/cabled "
        f"now resolves to branch change-1, at {CABLED_AT} (written); the twin is pinned to what it was built from")
    assert doc.subject["stage"] == "change-1/live"


def test_step_to_the_twins_own_stage_is_refused(tmp_path):
    core = stepped_core(twin_at(THREE["snapshot_id"]))
    deps, _, _ = deps_of(tmp_path, core, StorySession())
    record_at(deps, "cabled", CABLED_AT, THREE["snapshot_id"])
    doc = twin_step.run(deps, stage="change-1/cabled")
    assert [(f.rule, f.step) for f in doc.findings] == [("step.target.current", "resolve")]
    assert core.named("start") == []


def test_step_reads_under_the_twins_scope_and_passes_its_flags(tmp_path):
    other = "tag:lab"
    core = stepped_core(twin_at(THREE["snapshot_id"], scope=other))
    core.dry = Answer(OP_TWIN_STEP, out=["verdict: …"], document=Document(OP_TWIN_STEP, "ok", {}, Findings(), {}))
    deps, lines, opened = deps_of(tmp_path, core, StorySession({("change-1", LIVE_AT): (MIXED, Findings())},
                                                               scope=other))
    record_at(deps, "cabled", CABLED_AT, THREE["snapshot_id"])
    doc = twin_step.run(deps, allow_restart=True, wait="0", dry_run=True)
    assert opened == [(OP_TWIN_STEP, other, None)]
    (call,) = core.named("dry_run")
    assert call[2] == {"snapshot": str(deps.store.path(MIXED["snapshot_id"])), "allow_restart": True, "wait": "0"}
    assert core.named("start") == [] and lines[-1] == "verdict: …"
    assert doc.subject["scope"] == other
    assert deps.store.read_record().stage.label == "cabled"


def test_step_that_leaves_the_twin_elsewhere_keeps_the_record(tmp_path):
    core = stepped_core(twin_at(THREE["snapshot_id"]))
    core.ran = ended("fylgja-step", "diverged")
    deps, _, _ = deps_of(tmp_path, core, StorySession({("change-1", LIVE_AT): (MIXED, Findings())}))
    record_at(deps, "cabled", CABLED_AT, THREE["snapshot_id"])
    doc = twin_step.run(deps)
    assert doc.status == "diverged" and doc.exit_code == 4
    assert deps.store.read_record().stage.label == "cabled"


# stage-plan, held to the golden.


class GoldenStore(Store):
    """A store that files the golden's snapshots under their recorded ids, which no snapshot
    the test can make hashes to."""

    def put(self, snapshot):
        path = self.path(snapshot["snapshot_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot))
        return snapshot["snapshot_id"], True


class CountedBuilt(Built):
    def __init__(self, *a, read=None, **kw):
        super().__init__(*a, **kw)
        self._read = read

    @property
    def counts(self):
        return {k: self._read[k] for k in ("devices", "interfaces", "links", "artifacts")}


class GoldenChange:
    def __init__(self, block):
        pc = block["proposed_change"]
        self.proposed_change = stages.ProposedChange(pc["id"], pc["name"], pc["branch"], "main", pc["draft"])
        self.labels_ = [s["label"] for s in block["stages"]]

    def labels(self):
        return list(self.labels_)


class GoldenSession:
    """The golden plan's stages as the adapter built them: each stage's resolution and read
    findings, its snapshot (its id alone), and the moved mode each build was asked for."""

    def __init__(self, block):
        self.block = block
        self.ch = GoldenChange(block)
        self.moved = []

    def find(self, branch):
        assert branch == self.block["branch"]
        return self.ch, Findings()

    def build(self, ch, ref, moved, now=None, on_resolved=None):
        self.moved.append(moved)
        sb = next(s for s in self.block["stages"] if s["label"] == ref.label)
        b = CountedBuilt(ref, ref.label, sb["description"], sb["at_source"], read=sb["read"])
        b.resolved = stages.Resolved(ref, sb["branch"], ref.label, ch.proposed_change, sb["at"], sb["at_source"],
                                     sb["description"])
        found = Findings(Finding.from_dict(f) for f in sb["findings"] if f["step"] in ("resolve", "read"))
        if not sb["snapshot_id"]:
            return b.stop(found)
        b.findings.extend(found)
        b.snapshot = {"snapshot_id": sb["snapshot_id"]}
        b.packages = [("nokia_srlinux", 3)]
        b.status = BUILD_READ
        return b


def golden_core(block) -> FakeCore:
    manifest = json.dumps({"nodes": [{"name": n, "artifact": {"name": "device-config"}} for n in ("n1", "n2", "n3")],
                           "fidelity": {"lossy": []}}).encode()
    compiles, diffs = [], []
    for sb in block["stages"]:
        if not sb["snapshot_id"]:
            continue
        found = Findings(replace(Finding.from_dict(f), step="") for f in sb["findings"] if f["step"] == "compile")
        doc = Document(OP_COMPILE, "ok", {}, found, {"snapshot_id": sb["snapshot_id"], "bundle_id": sb["bundle_id"]})
        compiles.append(Answer(OP_COMPILE, files=[File("configs/n1.cfg", b""), File("manifest.json", manifest)],
                               document=doc))
    for st in block["steps"]:
        if st["computed"]:
            diffs.append(Document(OP_TWIN_DIFF, "ok", None, Findings(), {"step": st}))
    return FakeCore(compiles=compiles, diffs=diffs)


def test_stage_plan_renders_the_golden(tmp_path):
    golden = json.loads((GOLDEN / "plan.json").read_text())
    block = golden["plan"]
    session, core = GoldenSession(block), golden_core(block)
    deps, lines, opened = deps_of(tmp_path, core, session)
    deps.store = GoldenStore(tmp_path / "orchestrator")
    doc = stage_plan.run(deps, block["branch"])

    assert opened == [("stage.plan", SCOPE, None)]
    assert session.moved == [MOVED_ALWAYS] + [MOVED_NEVER] * 4
    assert "".join(line + "\n" for line in lines) == (GOLDEN / "plan.txt").read_text()
    assert doc.json() == (GOLDEN / "plan.json").read_text()
    assert doc.text() == (GOLDEN / "plan.stderr.txt").read_text()
    assert doc.exit_code == 1
    findings.validate(doc.to_dict())
    compiled = [c[1] for c in core.named("compile")]
    assert compiled == [str(deps.store.path(s["snapshot_id"])) for s in block["stages"] if s["snapshot_id"]]
    assert [(c[1], c[2]) for c in core.named("diff")] == list(zip(compiled, compiled[1:], strict=False))


def test_stage_plan_counts_the_manifests_lossy_record():
    lossy = [{"device": "c1", "port": "eth49", "shares": [{}]}, {"device": "c1", "port": "eth49", "shares": [{}]},
             {"device": "c1", "port": "eth1", "shares": []}]
    assert stage_plan.lossy_counts(json.dumps({"fidelity": {"lossy": lossy}}).encode()) == (3, 1)
    assert stage_plan.lossy_counts(b"{}") == (0, 0)


def test_stage_plan_a_refused_compile_goes_on(tmp_path):
    """A stage the core refuses is reported, its snapshot named, and the plan goes on."""
    block = json.loads((GOLDEN / "plan.json").read_text())["plan"]
    core = golden_core(block)
    refused = Findings([Finding(REJECTION, "psp.unknown", "n1", "no package")])
    core.compiles[1] = Answer(OP_COMPILE, document=Document(OP_COMPILE, "rejected", {}, refused, {}))
    core.diffs = [core.diffs[-1]]
    deps, lines, _ = deps_of(tmp_path, core, GoldenSession(block))
    deps.store = GoldenStore(tmp_path / "orchestrator")
    doc = stage_plan.run(deps, block["branch"])
    third = doc.blocks["plan"]["stages"][2]
    assert third["snapshot_id"] == block["stages"][2]["snapshot_id"] and third["bundle_id"] is None
    assert third["findings"][-1] == {"severity": "rejection", "rule": "psp.unknown", "object": "n1",
                                     "message": "no package", "step": "compile"}
    assert "fylgja-test-golden-41263/third-link: refused (psp.unknown)" in lines
    steps = doc.blocks["plan"]["steps"]
    assert [s["computed"] for s in steps] == [False, False, False, True]
    assert len(core.named("diff")) == 1


@pytest.mark.parametrize("kw, rule, step", [
    ({}, "operation.failed", ""),
    ({"branch": "a/b"}, "stage.ref.invalid", "start"),
    ({"branch": "b", "scope": ""}, "scope.invalid", "start"),
])
def test_stage_plan_guards(tmp_path, kw, rule, step):
    deps, _, opened = deps_of(tmp_path, FakeCore(), StorySession())
    doc = stage_plan.run(deps, **kw)
    assert doc.status == "error" and [(f.rule, f.step) for f in doc.findings] == [(rule, step)]
    assert opened == []


def test_stage_plan_of_no_open_proposed_change(tmp_path):
    deps, lines, _ = deps_of(tmp_path, FakeCore(), StorySession())
    doc = stage_plan.run(deps, "change-9")
    assert doc.status == "rejected" and [f.rule for f in doc.findings] == ["stage.unknown"]
    assert "plan" not in doc.to_dict() and lines == []


def test_stage_plan_through_the_story(tmp_path):
    """The plan of change-1 over the real resolution: the branch point refused on an empty
    main, every later stage read, compiled and stepped."""
    main_empty = Findings([Finding(REJECTION, "scope.empty", SCOPE, "scope selects no device")])
    session = StorySession({("main", "2026-10-16T17:20:19.944651Z"): (None, main_empty)})
    doc3 = Document(OP_COMPILE, "ok", {}, Findings(), {"bundle_id": "c" * 64})
    manifest = b'{"nodes": [], "fidelity": {"lossy": []}}'
    unchanged = {"from": "snapshot b9db37f8…", "to": "snapshot b9db37f8…", "from_bundle_id": "c" * 64,
                 "to_bundle_id": "c" * 64, "computed": True, "unchanged": True, "nodes": {}, "links": {},
                 "artifacts": {}}
    core = FakeCore(compiles=[Answer(OP_COMPILE, files=[File("manifest.json", manifest)], document=doc3)] * 3,
                    diffs=[Document(OP_TWIN_DIFF, "ok", None, Findings(), {"step": unchanged})] * 2)
    deps, lines, _ = deps_of(tmp_path, core, session)
    doc = stage_plan.run(deps, "change-1")
    assert [s[1] for s in session.taken] == ["2026-10-16T17:20:19.944651Z", CABLED_AT, LIVE_AT,
                                             "2026-10-16T17:30:11.884302+00:00"]
    assert lines[0] == ('proposed change "third link" (pc-1) on branch change-1 → main, draft (4 stages), '
                        'scope tag:fylgja')
    assert "step change-1/cabled → change-1/live (cccccccc… → cccccccc…): unchanged; the two are one bundle" in lines
    assert [(s["label"], s["bundle_id"] is not None) for s in doc.blocks["plan"]["stages"]] == [
        ("branch-point", False), ("cabled", True), ("live", True), ("head", True)]
    assert doc.status == "rejected"
    findings.validate(doc.to_dict())


def test_session_build_moved_modes():
    """stage.main.moved with the branch point always, never after it, and with a create's or
    a step's stage once it resolved."""
    session = StorySession()
    later = stages.Stamps("2026-10-16T17:50:00.000000+00:00", {})
    session.stamper.by_branch["main"] = later
    ch, _ = session.find("change-1")
    rules = lambda b: [f.rule for f in b.findings]  # noqa: E731
    assert rules(session.build(ch, stages.Ref("change-1", "cabled"), MOVED_RESOLVED)) == ["stage.main.moved"]
    assert rules(session.build(ch, stages.Ref("change-1", "cabled"), MOVED_NEVER)) == []
    gone = session.build(ch, stages.Ref("change-1", "gone"), MOVED_ALWAYS)
    assert rules(gone) == ["stage.unknown", "stage.main.moved"] and gone.status == "refused"
    assert gone.rule == "stage.unknown" and gone.resolved is None
