"""The rehearse flow (T026; data-model §7, R-09 to R-11; FR-019), its body called plain with
the adapter and the core stubbed: the golden rehearsal replayed through the core's answers
and held to the goldens byte for byte but for the stages' times; then the
composition of 015's `TestRehearse*` cases by name (`internal/provision/workflow_rehearse_test.go`'s
over the core's operations, `internal/server/rehearse_test.go`'s pure ones), the stop at the
first failed stage, the reclaim's four cases, the deadline's cut and a timeout's or a
cancellation's, and the report that cannot be posted."""

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from prefect import Flow

from fylgja_orchestrator.adapters.infrahub import stages
from fylgja_orchestrator.adapters.infrahub.session import BUILD_READ, MOVED_ALWAYS, MOVED_NEVER
from fylgja_orchestrator.core import Answer, CoreFailure, File, RunRef
from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents import rehearsal as r
from fylgja_orchestrator.documents.deadline import (
    CEILING_S,
    MECHANISM,
    ROLE_BASELINE,
    ROLE_REHEARSED,
    DeadlineStage,
    deadline,
    load_budgets,
    node_plans,
)
from fylgja_orchestrator.documents.findings import (
    OP_COMPILE,
    OP_RUN_READ,
    OP_TWIN_CREATE,
    OP_TWIN_DESTROY,
    OP_TWIN_DIFF,
    OP_TWIN_SHOW,
    OP_TWIN_STEP,
    OP_TWIN_VERIFY,
    REJECTION,
    WARNING,
    Document,
    Finding,
    Findings,
)
from fylgja_orchestrator.flows import common, twin_rehearse
from fylgja_orchestrator.flows.twin_rehearse import (
    TIMEOUT_S,
    WORKFLOW_DESTROY,
    WORKFLOW_PROVISION,
    WORKFLOW_REHEARSE,
    WORKFLOW_STEP,
    moved_or_closed,
    passed_over,
    rehearsal_stages,
    rehearsal_status,
)
from fylgja_orchestrator.record import FLOW_CREATE, FLOW_REHEARSE, ChangeRef, StageRef, new_record

from .test_flows import CountedBuilt, GoldenSession, GoldenStore

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
SCOPE = "tag:fylgja"
RUN = "01a1b2c3-0000-7000-8000-0000000000aa"
CHANGE = "change-1"
NOW = datetime(2026, 10, 17, 14, 2, 11, tzinfo=UTC)


def manifest(nodes=("n1", "n2", "n3")) -> bytes:
    return json.dumps({"nodes": [{"name": n, "psp": {"id": "nokia_srlinux"}, "artifact": {"name": "device-config"}}
                                 for n in nodes], "fidelity": {"lossy": []}}).encode()


COUNTS = {"host_name": {"held": 3, "failed": 0, "unread": 0},
          "port_enabled": {"held": 6, "failed": 0, "skipped": 0, "unread": 0},
          "neighbor": {"held": 6, "failed": 0, "skipped": 0, "unread": 0},
          "burst": {"held": 0, "failed": 0, "unread": 0}, "record": {"held": 3, "failed": 0}}


def neighbor(message: str) -> dict:
    return {"rule": "verify.neighbor", "object": "n1:ethernet-1/3", "message": message}


# The core, scripted.


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def created(status: str = "ok", found=(), cleanup=None) -> Document:
    blocks = {"bundle_id": "b" * 64}
    if cleanup is not None:
        blocks["cleanup"] = cleanup
    return Document(OP_RUN_READ, status, {"run_id": "p"}, Findings(found), blocks)


def verified(outcome: str = "settled", failing=(), after_s: float = 4.4, reads: int = 1, counts=None) -> Document:
    found = Findings(Finding(REJECTION, f["rule"], f["object"], f["message"], "observe") for f in failing)
    block = {"wait": {"budget_s": 120, "reads": reads, "outcome": outcome, "after_s": after_s},
             "counts": counts or COUNTS}
    return Document(OP_TWIN_VERIFY, "nonconforming" if failing else "ok", None, found, {"verify": block})


def stepped(outcome: str = "stepped", wait_outcome: str = "settled", failing=(), phase: str = "", status: str = "ok",
            found=(), pushed=None, run_id: str = "s", loss=None) -> Document:
    block = {"run": {"workflow_id": WORKFLOW_STEP, "run_id": run_id}, "outcome": outcome,
             "reconcile": {"added": [], "deleted": [], "recreated": [], "restarted": []},
             "pushed": pushed if pushed is not None else [{"node": "n1", "reasons": ["artifact"], "outcome": "landed",
                                                            "took_s": 2.9}],
             "timings": {"reconcile_s": 0.7, "push": {"n1": 2.9}, "whole_s": 5.1},
             "wait": {"budget_s": 120, "outcome": wait_outcome, "reads": 1, "after_s": 5.5, "failing": list(failing)},
             "wait_counts": COUNTS, "loss": loss or {"basis": "container", "probes": [], "added": [], "dropped": []}}
    if not outcome:
        del block["outcome"]
    if phase:
        block["phase"] = phase
    return Document(OP_RUN_READ, status, {"run_id": run_id}, Findings(found), {"step": block})


def destroyed(remaining=(), removed=("lab fylgja (3 containers)",)) -> Document:
    return Document(OP_RUN_READ, "unclean" if remaining else "ok", None, Findings(),
                    {"cleanup": {"teardown": "failed" if remaining else "done", "unstage": "done",
                                 "removed": list(removed), "remaining": list(remaining)}})


class RCore:
    """The core as the rehearse flow calls it: the plan's compiles and diffs, `twin.show`
    naming the twin the stubbed runs leave, the host check's dry run, and each child's start
    and reads answered by a handler of its own, `handler(core, stop)`, which may move the clock
    and answers its run's document, or None while it runs on past a `stop` that says so."""

    def __init__(self, clock: Clock, twin: str | None = None, run_ids=None, lines=None):
        self.clock = clock
        self.twin = twin
        self.in_flight = []
        self.calls = []
        self.interrupts = []
        self.compiled = {}
        self.dry = Document("twin.create", "ok", None, Findings(), {})
        self.refuse = {}
        self.fail_start = {}
        self.fail_read = {}
        self.run_ids = dict(run_ids or {})
        self.lines = lines or {}
        self.create = lambda core, stop: created()
        self.verify_ = lambda core: verified()
        self.steps = []
        self.step = lambda core, stop, n: stepped(run_id=f"step-{n}")
        self.destroy_ = lambda core, stop: destroyed()
        self.sent = {}
        self.n_steps = 0

    # The plan.

    def compile(self, snapshot, files=(), out=""):
        self.calls.append("compile")
        sid = Path(snapshot).stem
        bundle = self.compiled.get(sid, sid[:2] * 32)
        doc = Document(OP_COMPILE, "ok", {}, Findings(), {"snapshot_id": sid, "bundle_id": bundle})
        return Answer(OP_COMPILE, files=[File("manifest.json", manifest())], document=doc)

    def diff(self, from_, to, files=()):
        self.calls.append("diff")
        a, b = Path(from_).stem, Path(to).stem
        step = {"from": f"snapshot {a[:8]}…", "to": f"snapshot {b[:8]}…", "from_bundle_id": a[:2] * 32,
                "to_bundle_id": b[:2] * 32, "computed": True, "unchanged": False,
                "nodes": {"added": [], "removed": [], "changed": [{"node": "n1", "reasons": ["artifact"]}]},
                "links": {"added": [], "removed": []}, "artifacts": {"changed": []}}
        return Document(OP_TWIN_DIFF, "ok", None, Findings(), {"step": step})

    # The host.

    def show(self):
        self.calls.append("show")
        record = {"snapshot_id": self.twin, "scope": SCOPE} if self.twin else None
        return Document(OP_TWIN_SHOW, "ok", None, Findings(),
                        {"show": {"record": record, "in_flight": list(self.in_flight)}})

    def dry_run(self, op, args=None, files=(), on_out=None):
        self.calls.append("dry_run")
        return Answer(op, document=self.dry)

    # The runs.

    def start(self, op, args=None, files=(), on_out=None):
        name = {OP_TWIN_CREATE: "provision", OP_TWIN_STEP: "step", OP_TWIN_DESTROY: "destroy"}[op]
        wf = {OP_TWIN_CREATE: WORKFLOW_PROVISION, OP_TWIN_STEP: WORKFLOW_STEP, OP_TWIN_DESTROY: WORKFLOW_DESTROY}[op]
        self.calls.append(name)
        self.sent.setdefault(name, []).append(dict(args or {}))
        if name in self.fail_start:
            raise self.fail_start[name]
        if name in self.refuse:
            return Answer(op, document=self.refuse[name])
        if name == "step":
            self.n_steps += 1
        if args and args.get("snapshot"):
            self.pending = Path(args["snapshot"]).stem
        ids = self.run_ids.get(name)
        run_id = ids.pop(0) if isinstance(ids, list) and ids else f"{name}-{self.n_steps}"
        return Answer(op, run=RunRef(wf, run_id), document=Document(op, "ok", None, Findings(), {}))

    def read(self, workflow_id, run_id="", render=True, on_out=None, stop=None):
        name = {WORKFLOW_PROVISION: "provision", WORKFLOW_STEP: "step", WORKFLOW_DESTROY: "destroy"}[workflow_id]
        self.calls.append("read " + name)
        if name in self.fail_read:
            raise self.fail_read[name]
        if name == "provision":
            doc = self.create(self, stop)
        elif name == "step":
            doc = self.step(self, stop, self.n_steps)
        else:
            doc = self.destroy_(self, stop)
        for line in self.lines.get(run_id, []):
            on_out(line)
        if doc is None:
            return Answer(OP_RUN_READ, run=RunRef(workflow_id, run_id, "running"))
        # The twin the run leaves, as twin show names it after it.
        if name == "destroy" and not doc.blocks["cleanup"]["remaining"]:
            self.twin = None
        elif (name == "provision" and doc.status == "ok") or (
                name == "step" and (doc.blocks.get("step") or {}).get("outcome") in ("stepped", "unchanged")):
            self.twin = self.pending
        return Answer(OP_RUN_READ, run=RunRef(workflow_id, run_id, "completed"), document=doc)

    def interrupt(self, workflow_id, run_id=""):
        self.calls.append("interrupt " + workflow_id)
        self.interrupts.append((workflow_id, run_id))
        return Document("run.interrupt", "ok", None, Findings(), {})

    def verify(self, wait="", on_out=None):
        self.calls.append("verify")
        self.waited = wait
        return Answer(OP_TWIN_VERIFY, document=self.verify_(self))

    def children(self) -> list[str]:
        """The calls a rehearsal's run makes, as the workflow's tests name its children."""
        return [c for c in self.calls if c in ("provision", "verify", "step", "destroy")]


# The plan, as the adapter builds it.


class Spec:
    def __init__(self, label, at_source, at, snapshot=None, description="", branch=CHANGE, refused=None):
        self.label, self.at_source, self.at, self.snapshot = label, at_source, at, snapshot
        self.description, self.branch, self.refused = description, branch, refused


def fixture_specs():
    """015's example: the branch point refused scope.empty on an empty main, the mark seeded,
    the mark third-link and the head (`fixtureRehearsal`)."""
    return [
        Spec("branch-point", stages.AT_BRANCH_POINT, "2026-10-16T17:20:19.944651Z", branch="main",
             refused=Finding(REJECTION, "scope.empty", SCOPE, "scope tag:fylgja selects no device on branch main",
                             "read")),
        Spec("seeded", "written", "2026-10-16T17:25:30.118244+00:00", "a1" * 32, "after the link is cabled"),
        Spec("third-link", "given", "2026-10-16T17:30:00.000000+00:00", "a2" * 32, "third link"),
        Spec("head", "head", "2026-10-16T17:30:11.884302+00:00", "a4" * 32),
    ]


class Change:
    def __init__(self, specs, draft=False):
        self.proposed_change = stages.ProposedChange("pc-1", "third link", CHANGE, "main", draft)
        self.specs = specs

    def labels(self):
        return [s.label for s in self.specs]


class Session:
    """The adapter's session over specs: each stage built as the spec says, and the stages
    listed after the run as `listed` says (the same resolutions by default)."""

    def __init__(self, specs, listed=None, found=True):
        self.specs = {s.label: s for s in specs}
        self.ch = Change(specs)
        self.listed = listed
        self.found = found
        self.moved = []

    def find(self, branch):
        if not self.found:
            return None, Findings([Finding(REJECTION, "stage.unknown", branch, "no open proposed change", "resolve")])
        return self.ch, Findings()

    def resolved(self, s, ch=None):
        ch = ch or self.ch
        return stages.Resolved(stages.Ref(CHANGE, s.label), s.branch, s.label, ch.proposed_change, s.at, s.at_source,
                               s.description)

    def build(self, ch, ref, moved, now=None, on_resolved=None):
        self.moved.append(moved)
        s = self.specs[ref.label]
        b = CountedBuilt(ref, ref.label, s.description, s.at_source,
                         read={"devices": 3, "interfaces": 15, "links": 3, "artifacts": 3})
        b.resolved = self.resolved(s, ch)
        if s.refused is not None:
            return b.stop(Findings([s.refused]))
        b.snapshot = {"snapshot_id": s.snapshot}
        b.packages = [("nokia_srlinux", 3)]
        b.status = BUILD_READ
        return b

    def stage_list(self, branch):
        if isinstance(self.listed, Exception):
            raise self.listed
        rows = self.listed if self.listed is not None else [stages.Row(self.resolved(s)) for s in self.specs.values()]
        return stages.ListResult(branch=branch, rows=rows), Findings()


class Harness:
    def __init__(self, tmp_path, specs=None, twin=None, **kw):
        self.clock = Clock()
        self.core = RCore(self.clock, twin=twin)
        self.session = Session(specs or fixture_specs())
        self.lines = []
        self.posts = []
        self.flow_runs = {}
        self.post_failure = None

        def post(environ, change_id, text, by=None):
            self.posts.append((change_id, text))
            self.post_by = by
            return self.post_failure

        def flow_run(flow_run_id, environ):
            state = self.flow_runs.get(flow_run_id)
            if isinstance(state, Exception):
                raise state
            return None if state is None else {"id": flow_run_id, "state": {"type": state}}

        self.deps = common.Deps(core=self.core, store=GoldenStore(tmp_path / "orchestrator"),
                                environ={"FYLGJA_DEFAULT_SCOPE": SCOPE}, out=self.lines.append,
                                open=lambda op, subject, scope, probes, environ: (self.session, None),
                                flow_run_id=RUN, now=lambda: NOW, flow_run=flow_run, post=post, clock=self.clock,
                                **kw)

    def rehearse(self, branch=CHANGE, **kw) -> twin_rehearse.Rehearsed:
        return twin_rehearse.rehearse(self.deps, branch, **kw)

    def run(self, **kw) -> Document:
        done = self.rehearse(**kw)
        findings.validate(done.document.to_dict())
        return done.document


def verdicts(doc: Document) -> list[str]:
    return [f"{s['ref']} {s['verdict']}" for s in doc.blocks["rehearsal"]["stages"]]


def rules(doc: Document) -> list[str]:
    return [f.rule for f in doc.findings if f.severity == REJECTION]


def stage(doc: Document, label: str) -> dict:
    return next(s for s in doc.blocks["rehearsal"]["stages"] if s["label"] == label)


EVERY_PASSES = [f"{CHANGE}/branch-point refused", f"{CHANGE}/seeded baseline", f"{CHANGE}/third-link passed",
                f"{CHANGE}/head passed"]
STOPPED_AT_THIRD = [f"{CHANGE}/branch-point refused", f"{CHANGE}/seeded baseline", f"{CHANGE}/third-link error",
                    f"{CHANGE}/head not_reached"]
NOT_BUILT = [f"{CHANGE}/branch-point refused", f"{CHANGE}/seeded error", f"{CHANGE}/third-link not_reached",
             f"{CHANGE}/head not_reached"]


# The flow as Prefect sees it.


def test_the_flow_is_named_with_its_parameters():
    """data-model §7: twin-rehearse (branch, scope, probes_path, markdown), its timeout the
    bound no deadline exceeds, the ceiling within it."""
    f = twin_rehearse.twin_rehearse
    assert isinstance(f, Flow) and f.name == "twin-rehearse" == twin_rehearse.FLOW
    assert list(inspect.signature(f.fn).parameters) == ["branch", "scope", "probes_path", "markdown"]
    assert list(inspect.signature(twin_rehearse.run).parameters) == ["deps", "branch", "scope", "probes_path",
                                                                      "markdown"]
    assert f.timeout_seconds == TIMEOUT_S == 4020 and TIMEOUT_S <= 4260 - 240 and CEILING_S < TIMEOUT_S


# The golden, replayed.


class GoldenListing(GoldenSession):
    """The golden plan's session, its stages listed again after the run as they were."""

    def stage_list(self, branch):
        pc = self.ch.proposed_change
        rows = [stages.Row(stages.Resolved(stages.Ref(branch, s["label"]), s["branch"], s["label"], pc, s["at"],
                                           s["at_source"], s["description"])) for s in self.block["stages"]]
        return stages.ListResult(branch=branch, rows=rows), Findings()


def golden_harness(tmp_path):
    """The golden rehearsal's plan (`plan.json`, its stages as the adapter built them) and its
    run (`rehearsal.json`, `rehearsal.out.txt`) as the core answered each request."""
    plan = json.loads((GOLDEN / "plan.json").read_text())["plan"]
    doc = json.loads((GOLDEN / "rehearsal.json").read_text())
    b = doc["rehearsal"]
    out = (GOLDEN / "rehearsal.out.txt").read_text().splitlines()
    h = Harness(tmp_path)
    h.session = GoldenListing(plan)
    # The proposed change was marked ready between the plan's capture and the rehearsal's.
    pc = h.session.ch.proposed_change
    h.session.ch.proposed_change = stages.ProposedChange(pc.id, pc.name, pc.branch, pc.destination, False)
    h.deps.open = lambda op, subject, scope, probes, environ: (h.session, None)
    h.deps.flow_run_id = b["run"]["run_id"]
    h.deps.now = lambda: datetime(2026, 10, 29, 18, 15, 11, tzinfo=UTC)
    core = h.core
    core.compiled = {s["snapshot_id"]: s["bundle_id"] for s in plan["stages"] if s["snapshot_id"]}
    compile_found = {s["snapshot_id"]: [Finding.from_dict({**f, "step": ""}) for f in s["findings"]
                                        if f["step"] == "compile"] for s in plan["stages"] if s["snapshot_id"]}
    steps = iter(st for st in plan["steps"] if st["computed"])

    def compile_(snapshot, files=(), out=""):
        core.calls.append("compile")
        sid = Path(snapshot).stem
        d = Document(OP_COMPILE, "ok", {}, Findings(compile_found[sid]),
                     {"snapshot_id": sid, "bundle_id": core.compiled[sid]})
        return Answer(OP_COMPILE, files=[File("manifest.json", manifest())], document=d)

    core.compile = compile_
    core.diff = lambda a, b_, files=(): Document(OP_TWIN_DIFF, "ok", None, Findings(), {"step": next(steps)})

    by_label = {s["label"]: s for s in b["stages"]}
    seeded, third, bad = by_label["seeded"], by_label["third-link"], by_label["bad-port"]
    core.run_ids = {"provision": [seeded["provision"]["run"]["run_id"]],
                    "step": [third["step"]["run"]["run_id"], bad["step"]["run"]["run_id"]],
                    "destroy": ["01a188e0-d0c3-7ce5-a3ce-8cae374baa9e"]}

    # Each child's lines are the golden's, between the line naming its run and the next of
    # the rehearsal's own.
    def segment(after: str) -> list[str]:
        i = out.index(after) + 1
        j = i
        while j < len(out) and not out[j].startswith(("stage ", "destroying ")):
            j += 1
        return out[i:j]

    for name, ids in core.run_ids.items():
        wf = {"provision": WORKFLOW_PROVISION, "step": WORKFLOW_STEP, "destroy": WORKFLOW_DESTROY}[name]
        for run_id in ids:
            core.lines[run_id] = segment(f"run {wf} {run_id}")

    def wait_of(s):
        return {**s["wait"], "failing": []}

    def step_doc(s):
        st = s["step"]
        child = [f for f in s["findings"] if f["step"] not in ("resolve", "read", "compile")
                 and not f["rule"].startswith("rehearsal.")]
        block = {"run": st["run"], "outcome": st["outcome"],
                 "reconcile": {"added": st["created"], "recreated": st["recreated"], "restarted": st["restarted"]},
                 "pushed": st["pushed"], "timings": st["timings"], "wait": wait_of(s), "wait_counts": s["verify"],
                 "loss": s["loss"]}
        if st.get("phase"):
            block["phase"] = st["phase"]
        return Document(OP_RUN_READ, "diverged" if child else "ok", {}, Findings(Finding.from_dict(f) for f in child),
                        {"step": block})

    core.create = lambda c, stop: created()

    def verify_(c):
        h.clock.t += seeded["took_s"]
        return verified(after_s=seeded["wait"]["after_s"], counts=seeded["verify"])

    core.verify_ = verify_
    core.step = lambda c, stop, n: step_doc(third if n == 1 else bad)

    def destroy_(c, stop):
        h.clock.t = b["used_s"]
        return Document(OP_RUN_READ, "ok", None, Findings(), {"cleanup": b["destroy"]})

    core.destroy_ = destroy_
    return h, doc


def test_the_golden_rehearsal_is_replayed_byte_for_byte(tmp_path):
    """The golden plan built and the golden run answered: the document, the markdown posted,
    the text and every line printed are the goldens', but for each stage's time, which is
    the flow's clock's."""
    h, golden = golden_harness(tmp_path)
    done = h.rehearse(golden["subject"]["branch"])
    doc = done.document

    block = doc.blocks["rehearsal"]
    for mine, want in zip(block["stages"], golden["rehearsal"]["stages"], strict=True):
        assert mine["took_s"] == pytest.approx(want["took_s"], abs=1e-6) or mine["verdict"] != "baseline"
        mine["took_s"] = want["took_s"]
    raw = (GOLDEN / "rehearsal.json").read_text().replace("<state-root>", "\\u003cstate-root\\u003e")
    assert doc.json() == raw
    findings.validate(doc.to_dict())
    assert doc.exit_code == 5

    assert done.markdown == (GOLDEN / "rehearsal.md").read_text()
    assert h.posts == [(golden["rehearsal"]["proposed_change"]["id"], done.markdown)]
    printed = "".join(line + "\n" for line in h.lines)
    assert printed == (GOLDEN / "rehearsal.out.txt").read_text()
    assert printed.endswith((GOLDEN / "rehearsal.txt").read_text())
    assert doc.text() == (GOLDEN / "rehearsal.stderr.txt").read_text()
    # The deadline from the three-node bundles' packages, as the Go server summed it.
    assert block["deadline_s"] == 2580
    assert h.session.moved == [MOVED_ALWAYS] + [MOVED_NEVER] * 4
    assert h.core.children() == ["provision", "verify", "step", "step", "destroy"]
    assert h.core.waited == "2m0s"


# 015's TestRehearse*, the workflow's (internal/provision/workflow_rehearse_test.go).


def test_rehearse_every_stage_passes(tmp_path):
    """The refused branch point passed over, the baseline created and waited on, the two later
    stages stepped to in order, each its own snapshot with restarts allowed, then the twin
    destroyed (FR-001)."""
    h = Harness(tmp_path)
    doc = h.run()
    assert verdicts(doc) == EVERY_PASSES
    assert h.core.children() == ["provision", "verify", "step", "step", "destroy"]
    assert doc.status == "ok" and rules(doc) == ["scope.empty"]
    assert h.core.sent["step"] == [{"snapshot": str(h.deps.store.path("a2" * 32)), "allow_restart": True},
                                   {"snapshot": str(h.deps.store.path("a4" * 32)), "allow_restart": True}]
    assert h.core.sent["provision"] == [{"snapshot": str(h.deps.store.path("a1" * 32))}]
    b = doc.blocks["rehearsal"]
    assert b["run"] == {"workflow_id": WORKFLOW_REHEARSE, "run_id": RUN} and doc.subject["run_id"] == RUN
    assert b["destroy"]["remaining"] == [] and b["baseline"] == {"ref": f"{CHANGE}/seeded", "findings": []}
    base = stage(doc, "seeded")
    assert base["provision"]["outcome"] == "ready" and base["wait"]["outcome"] == "settled" and base["step"] is None
    for label in ("third-link", "head"):
        st = stage(doc, label)
        assert st["step"]["outcome"] == "stepped" and st["provision"] is None and st["new_findings"] == []
    assert stage(doc, "branch-point")["step"] is None and stage(doc, "branch-point")["wait"] is None
    assert h.lines[-1].startswith("rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed")


def test_rehearse_stops_at_a_failed_stage(tmp_path):
    """A stage that diverges at push fails, the stage after it is not reached and never
    stepped to, and the twin is destroyed (FR-002)."""
    h = Harness(tmp_path)
    h.core.step = lambda c, stop, n: stepped("diverged", phase="push", status="diverged", pushed=[
        {"node": "n3", "reasons": ["artifact"], "outcome": "landed"},
        {"node": "n1", "reasons": ["artifact"], "outcome": "refused", "rule": "push.refused"}],
        found=[Finding(REJECTION, "push.refused", "n1", "n1 refused", "push")])
    doc = h.run()
    assert verdicts(doc) == [f"{CHANGE}/branch-point refused", f"{CHANGE}/seeded baseline",
                             f"{CHANGE}/third-link failed", f"{CHANGE}/head not_reached"]
    assert h.core.children() == ["provision", "verify", "step", "destroy"]
    assert doc.status == "nonconforming"
    st = stage(doc, "third-link")
    assert st["step"]["phase"] == "push" and len(st["step"]["pushed"]) == 2
    assert stage(doc, "head")["step"] is None and stage(doc, "head")["took_s"] == 0
    assert doc.blocks["rehearsal"]["reproduce"][0] == f"fylgja-cli twin create --stage {CHANGE}/seeded --scope {SCOPE}"


def test_rehearse_new_finding_fails(tmp_path):
    """A finding the baseline's wait did not have fails the stage, naming it (FR-002)."""
    h = Harness(tmp_path)
    fresh = neighbor("n1:ethernet-1/3 sees no neighbor; want n3:ethernet-1/3")
    h.core.step = lambda c, stop, n: stepped(wait_outcome="expired", failing=[fresh], status="nonconforming")
    doc = h.run()
    assert verdicts(doc)[2] == f"{CHANGE}/third-link failed" and doc.status == "nonconforming"
    st = stage(doc, "third-link")
    assert st["new_findings"] == [fresh] and st["wait"]["outcome"] == "expired"


def test_rehearse_baseline_findings_fail_nothing(tmp_path):
    """A finding the baseline's wait had fails nothing when a later stage has it again,
    whatever its message says now; the baseline carries it (FR-002, SC-004)."""
    h = Harness(tmp_path)
    had = neighbor("n1:ethernet-1/3 sees no neighbor")
    h.core.verify_ = lambda c: verified("expired", [had])
    h.core.step = lambda c, stop, n: stepped(wait_outcome="expired", status="nonconforming",
                                             failing=[neighbor("n1:ethernet-1/3 sees n2:ethernet-1/1")])
    doc = h.run()
    assert verdicts(doc) == EVERY_PASSES and doc.status == "ok"
    assert doc.blocks["rehearsal"]["baseline"]["findings"] == [had]


def test_rehearse_baseline_not_built(tmp_path):
    """A baseline that is not built ends the rehearsal baseline_failed, status failed: no wait
    and no step, every later stage not reached, and the destroy still runs (FR-005)."""
    h = Harness(tmp_path)
    h.core.create = lambda c, stop: created("failed", [Finding(REJECTION, "readiness.timeout", "n1",
                                                               "n1 did not answer within 60s", "readiness")],
                                            {"teardown": "done", "unstage": "done", "remaining": []})
    h.core.destroy_ = lambda c, stop: destroyed(removed=())
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and doc.status == "failed"
    assert h.core.children() == ["provision", "destroy"]
    base = stage(doc, "seeded")
    assert base["provision"]["outcome"] == "failed" and base["provision"]["step"] == "readiness"
    assert base["provision"]["cleanup"]["teardown"] == "done" and base["wait"] is None
    assert "rehearsal.baseline.failed" in rules(doc) and "readiness.timeout" in rules(doc)


@pytest.mark.parametrize("status, found, outcome", [
    ("error", [Finding(REJECTION, "operation.failed", "lab fylgja", "the host check could not run", "host_check")],
     "error"),
    ("rejected", [Finding(REJECTION, "host.image.absent", "n1", "no image", "host_check")], "rejected"),
    ("failed", [Finding(REJECTION, "run.cancelled", "p", "run p was cancelled at step push", "push")], "cancelled"),
])
def test_rehearse_baseline_ended_otherwise_is_error(tmp_path, status, found, outcome):
    """A baseline whose create ended other than failed did not try to build it and clean up:
    stage_error, status error, never baseline_failed; the destroy still runs."""
    h = Harness(tmp_path)
    h.core.create = lambda c, stop: created(status, found)
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and doc.status == "error"
    assert stage(doc, "seeded")["provision"]["outcome"] == outcome
    assert "rehearsal.stage.error" in rules(doc) and "rehearsal.baseline.failed" not in rules(doc)
    assert h.core.children() == ["provision", "destroy"]


def test_rehearse_step_rejected_is_error(tmp_path):
    """A step its own locks reject is error, not a verdict on the change: the rehearsal stops
    there and ends stage_error after its destroy (FR-002)."""
    h = Harness(tmp_path)
    h.core.step = lambda c, stop, n: stepped("", status="rejected", found=[
        Finding(REJECTION, "step.node.unapplied", "n1", "the plan does not recreate n1", "compare")])
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and doc.status == "error"
    st = stage(doc, "third-link")
    assert st["step"]["outcome"] == "rejected"
    assert any(f["rule"] == "rehearsal.stage.error" and f["step"] == "compare" for f in st["findings"])


def test_rehearse_wait_incomplete_is_error(tmp_path):
    """A wait that could not read every node is error: a rehearsed stage's, the baseline's,
    and the baseline's verify failing outright."""
    unread = {"rule": "operation.failed", "object": "n2", "message": "n2 could not be read"}
    h = Harness(tmp_path / "a")
    h.core.step = lambda c, stop, n: stepped(wait_outcome="incomplete", failing=[unread], status="error")
    assert verdicts(h.run()) == STOPPED_AT_THIRD

    h = Harness(tmp_path / "b")
    h.core.verify_ = lambda c: verified("incomplete", [unread])
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and stage(doc, "seeded")["wait"]["outcome"] == "incomplete"
    assert h.core.children() == ["provision", "verify", "destroy"]

    h = Harness(tmp_path / "c")

    def fails(c):
        raise CoreFailure("api.unreachable", "127.0.0.1:7650", "nothing answers at 127.0.0.1:7650")

    h.core.verify_ = fails
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and stage(doc, "seeded")["wait"]["outcome"] == "incomplete"
    assert doc.status == "error"


def cut_at(h: Harness, then: Document):
    """A child that runs past the deadline: the clock moved beyond it, the read cut by the
    flow's stop, then the child's own end once it was interrupted."""
    def child(c, stop, n=None):
        if stop is not None:
            h.clock.t += 10_000
            assert stop()
            return None
        return then
    return child


def test_rehearse_deadline_cuts_a_step_and_destroys(tmp_path):
    """The deadline passing mid-step interrupts the step, which records diverged, ends the
    stage error and the run cut, and the destroy follows; the stage after it is not reached
    (FR-006)."""
    h = Harness(tmp_path)
    h.core.step = cut_at(h, stepped("", status="error", found=[
        Finding(REJECTION, "run.cancelled", "s", "run s was cancelled at step push", "push")]))
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and doc.status == "error"
    assert h.core.interrupts == [(WORKFLOW_STEP, "step-1")]
    assert h.core.children() == ["provision", "verify", "step", "destroy"]
    cut = [f for f in doc.findings if f.rule == "rehearsal.deadline.cut"]
    assert len(cut) == 1 and cut[0].object == f"{CHANGE}/third-link" and cut[0].step == "push"
    assert "no stage had finished" not in cut[0].message and f"{CHANGE}/seeded took" in cut[0].message
    assert h.lines[-1].startswith(f"rehearsal error: the deadline of {doc.blocks['rehearsal']['deadline_s']}s passed")


def test_rehearse_deadline_never_cuts_the_destroy(tmp_path):
    """The destroy runs whole after a cut, however long it takes, and is never interrupted;
    ended before the deadline, a long destroy hits no deadline."""
    h = Harness(tmp_path / "cut")
    h.core.step = cut_at(h, stepped("", status="error"))

    def slow(c, stop):
        assert stop is None
        h.clock.t += 50_000
        return destroyed()

    h.core.destroy_ = slow
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and doc.blocks["rehearsal"]["destroy"]["remaining"] == []
    assert h.core.interrupts == [(WORKFLOW_STEP, "step-1")]

    h = Harness(tmp_path / "ok")
    h.core.destroy_ = slow
    doc = h.run()
    assert verdicts(doc) == EVERY_PASSES and doc.status == "ok" and h.core.interrupts == []


def test_rehearse_deadline_cuts_a_step_that_finished_anyway(tmp_path):
    """A stage the deadline cut is error whatever its step says: a step that stepped and
    settled after the deadline passed is still the stage in progress (FR-002)."""
    h = Harness(tmp_path)

    def late(c, stop, n):
        h.clock.t += 10_000
        return stepped()

    h.core.step = late
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and "rehearsal.deadline.cut" in rules(doc)
    assert h.core.children() == ["provision", "verify", "step", "destroy"]


def test_rehearse_deadline_during_the_baseline(tmp_path):
    """The deadline passing while the baseline is built interrupts its create, which cleans
    up; no wait and no step run, and the destroy follows."""
    h = Harness(tmp_path)
    h.core.create = cut_at(h, created("failed", [Finding(REJECTION, "run.cancelled", "p", "cancelled", "deploy")],
                                      {"teardown": "done", "unstage": "done", "remaining": []}))
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and doc.blocks["rehearsal"]["stages"][1]["provision"]["outcome"] == "cancelled"
    assert h.core.children() == ["provision", "destroy"] and h.core.interrupts == [(WORKFLOW_PROVISION, "provision-0")]
    assert "rehearsal.deadline.cut" in rules(doc) and doc.status == "error"


def test_rehearse_deadline_during_a_wait(tmp_path):
    """The deadline passing during the baseline's wait ends the stage error and the run cut."""
    h = Harness(tmp_path)

    def long_wait(c):
        h.clock.t += 10_000
        return verified()

    h.core.verify_ = long_wait
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and "rehearsal.deadline.cut" in rules(doc)
    assert h.core.children() == ["provision", "verify", "destroy"]


@pytest.mark.parametrize("where", ["the baseline's create", "the baseline's wait", "a step"])
def test_rehearse_cancelled_destroys(tmp_path, where):
    """The run's own cancellation reaching the body, the operator's interrupt or the
    platform's, ends the stage in progress error and the run cancelled rather than cut, and
    the destroy still runs; the cancellation is kept for the flow to raise once the document
    is filed (`TestRehearseCancelledDestroys`, `TestRehearseCancelledBeforeTheBaselineIsBuilt`)."""
    h = Harness(tmp_path)

    def cancel(*a):
        raise KeyboardInterrupt

    if where == "the baseline's create":
        h.core.create = cancel
    elif where == "the baseline's wait":
        h.core.verify_ = cancel
    else:
        h.core.step = cancel
    done = h.rehearse()
    doc = done.document
    findings.validate(doc.to_dict())
    assert isinstance(done.raised, KeyboardInterrupt)
    assert doc.status == "error" and h.core.children()[-1] == "destroy"
    assert verdicts(doc) == (STOPPED_AT_THIRD if where == "a step" else NOT_BUILT)
    cancelled = [f for f in doc.findings if f.rule == "run.cancelled"]
    assert len(cancelled) == 1 and cancelled[0].object == RUN
    assert "rehearsal.stage.error" not in rules(doc) and "rehearsal.deadline.cut" not in rules(doc)
    assert h.lines[-1].startswith("rehearsal error: the run was cancelled at stage")
    assert len(h.posts) == 1


def test_a_cancelled_rehearsal_reads_its_destroy_within_the_platforms_grace(tmp_path):
    """After a cancellation the platform kills the flow's process 30 s on (research §5.18): the
    destroy, the core's run, is started at once and read for 20 s alone, a destroy still
    running then named as going on in the core, and the post bounded to 27 s after the
    cancellation; a destroy that ends within it reports as ever."""
    h = Harness(tmp_path)
    h.clock.t = 100.0

    def cancel(c, stop, n):
        raise KeyboardInterrupt

    def slow(c, stop):
        while not stop():
            h.clock.t += 2
        return None

    h.core.step, h.core.destroy_ = cancel, slow
    done = h.rehearse()
    doc = done.document
    assert doc.status == "unclean" and isinstance(done.raised, KeyboardInterrupt)
    assert h.clock.t == pytest.approx(120.0) and h.post_by == pytest.approx(127.0)
    d = doc.blocks["rehearsal"]["destroy"]
    assert d["teardown"] == "skipped" and "goes on in the core" in d["remaining"][0]
    assert [f.object for f in doc.findings if f.rule == "cleanup.incomplete"] == ["destroy-1"]

    h = Harness(tmp_path / "quick")
    h.core.step = cancel
    doc = h.rehearse().document
    assert doc.blocks["rehearsal"]["destroy"]["remaining"] == [] and h.post_by is not None


def test_a_timeout_reaching_the_body_is_the_cut(tmp_path):
    """The flow's own timeout_seconds, delivered in the body as a TimeoutError, cuts the stage
    in progress as the deadline does, and the finally destroys and reports; the timeout is
    kept for the flow to raise (research §1.5, §5.18)."""
    h = Harness(tmp_path)

    def timed_out(c, stop, n):
        raise TimeoutError("Flow run exceeded timeout of 4020.0 second(s)")

    h.core.step = timed_out
    done = h.rehearse()
    assert isinstance(done.raised, TimeoutError)
    assert verdicts(done.document) == STOPPED_AT_THIRD and h.core.children()[-1] == "destroy"
    assert "rehearsal.deadline.cut" in rules(done.document) and done.document.status == "error"
    assert len(h.posts) == 1


def test_rehearse_destroy_unclean(tmp_path):
    """The destroy leaving something does not change how the stages went; the status is
    unclean (FR-005)."""
    h = Harness(tmp_path)
    h.core.destroy_ = lambda c, stop: destroyed(remaining=["lab fylgja (3 containers)"])
    doc = h.run()
    assert verdicts(doc) == EVERY_PASSES and doc.status == "unclean"
    assert doc.blocks["rehearsal"]["destroy"]["remaining"] == ["lab fylgja (3 containers)"]


def test_rehearse_one_stage(tmp_path):
    """One stage alone compiled is the baseline, built, verified and destroyed, with
    rehearsal.steps.none, and the run is ok when its wait is (FR-003)."""
    specs = fixture_specs()
    h = Harness(tmp_path, [specs[0], specs[3]])
    doc = h.run()
    assert verdicts(doc) == [f"{CHANGE}/branch-point refused", f"{CHANGE}/head baseline"] and doc.status == "ok"
    assert h.core.children() == ["provision", "verify", "destroy"]
    none = [f for f in doc.findings if f.rule == "rehearsal.steps.none"]
    assert len(none) == 1 and none[0].object == f"{CHANGE}/head" and none[0].severity == WARNING
    assert h.lines[-1].startswith("rehearsal ok: the baseline alone was built and verified")


def test_rehearse_child_refused_is_error(tmp_path):
    """A step refused because a run holds its id is error, filing run.in_flight naming it,
    and the rehearsal still destroys."""
    h = Harness(tmp_path)
    h.core.refuse["step"] = Document(OP_TWIN_STEP, "rejected", None, Findings(
        [Finding(REJECTION, "run.in_flight", WORKFLOW_STEP, "step run x is already in flight", "start")]), {})
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and doc.status == "error"
    held = [f for f in doc.findings if f.rule == "run.in_flight"]
    assert len(held) == 1 and held[0].object == WORKFLOW_STEP
    assert h.core.children() == ["provision", "verify", "step", "destroy"]


def test_rehearse_a_step_the_core_refuses_at_its_start(tmp_path):
    """A step the core refuses before its run carries the core's refusal as the stage's and
    is error: its step did not run."""
    h = Harness(tmp_path)
    h.core.refuse["step"] = Document(OP_TWIN_STEP, "rejected", None, Findings(
        [Finding(REJECTION, "step.scope.mismatch", "tag:other", "the twin was read under another scope", "start")]),
        {})
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD
    st = stage(doc, "third-link")
    assert [f["rule"] for f in st["findings"]] == ["step.scope.mismatch", "rehearsal.stage.error"]


def test_rehearse_baseline_held_touches_nothing(tmp_path):
    """A baseline whose create cannot start because a run holds its id touched nothing: the
    rehearsal is rejected, run.in_flight naming the held id, every stage after the passed-over
    branch point not reached, and no destroy, which would tear down that run's lab (FR-007)."""
    h = Harness(tmp_path)
    h.core.refuse["provision"] = Document(OP_TWIN_CREATE, "rejected", None, Findings(
        [Finding(REJECTION, "run.in_flight", WORKFLOW_PROVISION, "provisioning run x is already in flight",
                 "start")]), {})
    doc = h.run()
    assert verdicts(doc) == [f"{CHANGE}/branch-point refused", f"{CHANGE}/seeded not_reached",
                             f"{CHANGE}/third-link not_reached", f"{CHANGE}/head not_reached"]
    assert doc.status == "rejected" and h.core.children() == ["provision"]
    held = [f for f in doc.findings if f.rule == "run.in_flight"]
    assert len(held) == 1 and "touched nothing and ran no destroy" in held[0].message
    assert doc.blocks["rehearsal"]["destroy"] is None
    assert h.lines[-1].startswith("rehearsal rejected: the run touched nothing")


@pytest.mark.parametrize("how", ["refused", "unreachable"])
def test_rehearse_destroy_not_started_is_unclean(tmp_path, how):
    """A destroy that cannot start checks nothing, and says so under cleanup.incomplete: the
    rehearsal never claims a host it did not look at."""
    h = Harness(tmp_path)
    if how == "refused":
        h.core.refuse["destroy"] = Document(OP_TWIN_DESTROY, "rejected", None, Findings(
            [Finding(REJECTION, "run.in_flight", WORKFLOW_DESTROY, "destroy run x is already in flight", "start")]), {})
    else:
        h.core.fail_start["destroy"] = CoreFailure("api.unreachable", "127.0.0.1:7650", "nothing answers")
    doc = h.run()
    assert doc.status == "unclean" and verdicts(doc) == EVERY_PASSES
    d = doc.blocks["rehearsal"]["destroy"]
    assert d["teardown"] == "skipped" and d["unstage"] == "skipped" and "not checked" in d["remaining"][0]
    assert "cleanup.incomplete" in rules(doc)


def test_rehearse_child_closed_without_a_result(tmp_path):
    """A child whose end cannot be read is operation.failed on its run and its stage error,
    the run stage_error, and the destroy still runs: the baseline's create and a step alike."""
    lost = CoreFailure("api.unreachable", "127.0.0.1:7650", "the answer ended before its document")
    h = Harness(tmp_path / "create")
    h.core.fail_read["provision"] = lost
    doc = h.run()
    assert verdicts(doc) == NOT_BUILT and doc.status == "error"
    failed = [f for f in doc.findings if f.rule == "operation.failed"]
    assert [(f.object, f.step) for f in failed] == [("provision-0", "provision")]
    assert h.core.children() == ["provision", "destroy"]

    h = Harness(tmp_path / "step")
    h.core.fail_read["step"] = lost
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD
    assert [(f.object, f.step) for f in doc.findings if f.rule == "operation.failed"] == [("step-1", "start")]


def test_rehearse_destroy_closed_without_a_result_is_unclean(tmp_path):
    """A destroy that started and whose end cannot be read vouches for nothing: cleanup
    incomplete naming its run, and the stages' outcome stands."""
    h = Harness(tmp_path)
    h.core.fail_read["destroy"] = CoreFailure("api.unreachable", "127.0.0.1:7650", "lost")
    doc = h.run()
    assert verdicts(doc) == EVERY_PASSES and doc.status == "unclean"
    incomplete = [f for f in doc.findings if f.rule == "cleanup.incomplete"]
    assert len(incomplete) == 1 and incomplete[0].object == "destroy-2"


def test_rehearse_cut_child_closed_without_a_result_files_nothing(tmp_path):
    """A child the deadline cut whose end then cannot be read files nothing of the run's own:
    the outcome, cut, says why."""
    h = Harness(tmp_path)

    def cut_then_lost(c, stop, n):
        if stop is not None:
            h.clock.t += 10_000
            return None
        raise CoreFailure("api.unreachable", "127.0.0.1:7650", "lost")

    h.core.step = cut_then_lost
    doc = h.run()
    assert verdicts(doc) == STOPPED_AT_THIRD and "operation.failed" not in rules(doc)
    assert "rehearsal.deadline.cut" in rules(doc)


# 015's server cases (internal/server/rehearse_test.go), the pure ones.


@pytest.mark.parametrize("kw, rule, step", [
    ({"branch": ""}, "operation.failed", ""),
    ({"branch": "a/b"}, "stage.ref.invalid", "start"),
    ({"branch": CHANGE, "scope": ""}, "scope.invalid", "start"),
])
def test_rehearse_guards_before_any_connection(tmp_path, kw, rule, step):
    h = Harness(tmp_path)
    opened = []
    h.deps.open = lambda *a: opened.append(a) or (h.session, None)
    done = twin_rehearse.rehearse(h.deps, **kw)
    assert done.document.status == "error" and [(f.rule, f.step) for f in done.document.findings] == [(rule, step)]
    assert opened == [] and h.core.calls == [] and h.posts == []
    assert done.markdown.startswith("## Fylgja did not rehearse branch")


def test_rehearse_of_no_open_proposed_change_posts_nothing(tmp_path):
    h = Harness(tmp_path)
    h.session.found = False
    doc = h.run()
    assert doc.status == "rejected" and rules(doc) == ["stage.unknown"] and h.posts == []


def plan_of(*stati):
    from fylgja_orchestrator.documents.plan import PLAN_COMPILED, PlanResult, PlanStage

    res = PlanResult(CHANGE)
    for i, (status, source, found) in enumerate(stati):
        ps = PlanStage(f"{CHANGE}/s{i}", f"s{i}", at_source=source)
        if status == PLAN_COMPILED:
            ps.status, ps.bundle_id, ps.snapshot_id = status, f"{i}" * 64, f"{i}" * 64
            ps.findings.extend(found)
        else:
            ps.stop(found)
        res.add(ps, None) if not res.stages else res.stages.append(ps)
    return res


def test_rehearsal_stages_take_the_baseline_rule():
    """The branch point refused scope.empty at read alone is passed over; any other refusal,
    the branch point's included, refuses the rehearsal, as does a plan with nothing compiled;
    a lone compiled stage is the baseline with rehearsal.steps.none; a failed stage or M1's
    precision rule makes the refusal error."""
    empty = [Finding(REJECTION, "scope.empty", SCOPE, "no device", "read")]
    stale = [Finding(REJECTION, "stage.artifact.stale", "n1", "stale", "resolve")]
    bp, w = stages.AT_BRANCH_POINT, "written"
    base, rows, refused = rehearsal_stages(plan_of(("refused", bp, empty), ("compiled", w, []), ("compiled", w, [])))
    assert (base, [x.role for x in rows], refused) == (1, ["refused", "baseline", "rehearsed"], False)
    assert passed_over(rows[0].stage)
    _, rows, refused = rehearsal_stages(plan_of(("refused", bp, empty + stale), ("compiled", w, [])))
    assert refused
    _, _, refused = rehearsal_stages(plan_of(("refused", w, empty), ("compiled", w, [])))
    assert refused
    _, _, refused = rehearsal_stages(plan_of(("refused", bp, empty)))
    assert refused
    base, rows, refused = rehearsal_stages(plan_of(("refused", bp, empty), ("compiled", "head", [])))
    assert not refused and [f.rule for f in rows[1].findings] == ["rehearsal.steps.none"]
    assert twin_rehearse.refusal_status(plan_of(("refused", w, stale))) == "rejected"
    precision = [Finding(REJECTION, "intent.at.precision", "x", "seven digits", "resolve")]
    assert twin_rehearse.refusal_status(plan_of(("refused", w, precision))) == "error"
    failed = [Finding(REJECTION, "operation.failed", "x", "unreachable", "read")]
    assert twin_rehearse.refusal_status(plan_of(("refused", w, failed))) == "error"


def test_rehearse_refused_on_a_stale_mark_before_any_run(tmp_path):
    """A stage whose mark is stale refuses the rehearsal before any run, with 014's rule, as
    the orchestrator's refusal (US1 scenario 5); the report is posted, the host untouched."""
    specs = fixture_specs()
    specs[2].refused = Finding(REJECTION, "stage.artifact.stale", "n1", "n1's intent is newer than its artifact",
                               "resolve")
    h = Harness(tmp_path, specs)
    doc = h.run()
    assert doc.status == "rejected" and "stage.artifact.stale" in rules(doc)
    assert h.core.children() == [] and "show" not in h.core.calls and "dry_run" not in h.core.calls
    assert doc.blocks["rehearsal"].get("run") is None and len(h.posts) == 1
    assert h.lines[0].startswith('rehearsal of proposed change "third link" (pc-1) on branch change-1: 4 stages, '
                                 "scope tag:fylgja")


def test_rehearse_deadline_over_the_ceiling(tmp_path):
    h = Harness(tmp_path)
    doc = h.rehearse(ceiling_s=600).document
    assert doc.status == "rejected" and rules(doc)[-1] == "rehearsal.deadline.unfit"
    assert h.core.children() == [] and doc.blocks["rehearsal"]["ceiling_s"] == 600
    budgets = load_budgets()
    plans = node_plans({"manifest.json": manifest()}, budgets)
    want = deadline(MECHANISM, [DeadlineStage(ROLE_BASELINE, plans), DeadlineStage(ROLE_REHEARSED, plans),
                                DeadlineStage(ROLE_REHEARSED, plans)])
    assert doc.blocks["rehearsal"]["deadline_s"] == want
    assert f"deadline {r_duration(want)} (ceiling 10m0s)" in h.lines[0]


def r_duration(s):
    from fylgja_orchestrator.documents.deadline import go_duration

    return go_duration(s)


@pytest.mark.parametrize("outcome, remaining, status", [
    (r.OUTCOME_OK, [], "ok"), (r.OUTCOME_STAGE_FAILED, [], "nonconforming"),
    (r.OUTCOME_BASELINE_FAILED, [], "failed"), (r.OUTCOME_STAGE_ERROR, [], "error"), (r.OUTCOME_CUT, [], "error"),
    (r.OUTCOME_CANCELLED, [], "error"), (r.OUTCOME_OK, ["lab fylgja"], "unclean"),
    (r.OUTCOME_STAGE_FAILED, ["lab fylgja"], "unclean"), (r.OUTCOME_REJECTED, [], "rejected"),
])
def test_rehearsal_status_is_r08s(outcome, remaining, status):
    destroy = None if outcome == r.OUTCOME_REJECTED else {"remaining": remaining}
    assert rehearsal_status(outcome, destroy) == status
    assert rehearsal_status(r.OUTCOME_OK, None) == "unclean"


def test_rehearse_stages_read_again_after_the_run(tmp_path):
    """After the run the stages are listed again: a rehearsed stage that moved or is gone is
    rehearsal.stage.moved, a proposed change no longer open rehearsal.change.closed, and a
    listing that fails says whether one moved is unknown; warnings all, the status kept."""
    h = Harness(tmp_path)
    specs = fixture_specs()
    moved = Spec("third-link", "given", "2026-10-16T17:31:00.000000+00:00", "a2" * 32, "third link")
    h.session.listed = [stages.Row(h.session.resolved(s)) for s in (specs[0], specs[1], moved)]
    doc = h.run()
    assert doc.status == "ok"
    warned = [(f.rule, f.object) for f in doc.findings if f.rule.startswith("rehearsal.stage.moved")]
    assert warned == [("rehearsal.stage.moved", f"{CHANGE}/third-link"), ("rehearsal.stage.moved", f"{CHANGE}/head")]

    h = Harness(tmp_path / "closed")
    h.session.listed = []
    doc = h.run()
    assert [f.rule for f in doc.findings if f.severity == WARNING] == ["rehearsal.change.closed"]

    h = Harness(tmp_path / "unread")
    h.session.listed = stages.StagesError("Infrahub unreachable")
    doc = h.run()
    assert [(f.rule, f.object) for f in doc.findings if f.severity == WARNING] == [
        ("rehearsal.stage.moved", CHANGE)]


def test_moved_or_closed_names_the_resolution():
    block = {"proposed_change": {"id": "pc-1", "name": "x", "branch": CHANGE}, "resolved_at": "t",
             "stages": [{"ref": f"{CHANGE}/s", "role": "rehearsed", "branch": CHANGE, "at": "a"}]}
    pc = stages.ProposedChange("pc-1", "x", CHANGE)
    row = stages.Row(stages.Resolved(stages.Ref(CHANGE, "s"), CHANGE, "s", pc, ""))
    found = moved_or_closed(CHANGE, block, [row])
    assert [f.message for f in found] == [f"stage {CHANGE}/s was rehearsed at branch {CHANGE} at a, and now resolves "
                                          f"to branch {CHANGE} at unresolved"]


# The host before the run.


def test_rehearse_refused_by_a_run_in_flight(tmp_path):
    """A run of the core's in flight refuses the rehearsal before any start, naming it; a
    refusal because the host is held is not posted, since a check asks again on it."""
    h = Harness(tmp_path)
    h.core.in_flight = [{"workflow_id": WORKFLOW_STEP, "run_id": "s-9", "step": "push"}]
    doc = h.run()
    assert doc.status == "rejected" and rules(doc)[-1] == "run.in_flight"
    assert "step run s-9 is already in flight" in doc.findings[-1].message
    assert h.core.children() == [] and h.posts == []


def test_a_twin_the_record_does_not_name_holds_the_host(tmp_path):
    """A twin standing that is not the record's own dead rehearsal's is the host check's to
    refuse (host.twin.present), never reclaimed (US6 scenario 4): no record, a record of
    another flow, a record twin show does not trust, a record with no flow run."""
    present = Document("twin.create", "rejected", None, Findings([
        Finding(REJECTION, "host.twin.present", "twin", "a twin is recorded", "host_check")]), {})
    for name, record in [("none", None), ("create", ("e" * 64, FLOW_CREATE, "run-0")),
                         ("other", ("f" * 64, FLOW_REHEARSE, "dead")), ("no run", ("e" * 64, FLOW_REHEARSE, ""))]:
        h = Harness(tmp_path / name.replace(" ", "-"), twin="e" * 64)
        h.flow_runs["dead"] = "CRASHED"
        if record is not None:
            sid, flow, run = record
            h.deps.store.write_record(new_record(StageRef(CHANGE, "seeded", "a"), ChangeRef("pc-1", CHANGE), sid, run,
                                                 flow))
        h.core.dry = present
        doc = h.run()
        assert doc.status == "rejected" and rules(doc)[-1] == "host.twin.present", name
        assert "destroy" not in h.core.calls and h.posts == [], name


def dead_record(h: Harness, sid: str = "d" * 64, run: str = "dead-run"):
    h.core.twin = sid
    h.deps.store.write_record(new_record(StageRef(CHANGE, "third-link", "a"), ChangeRef("pc-1", CHANGE), sid, run,
                                         FLOW_REHEARSE))


@pytest.mark.parametrize("state", ["FAILED", "CRASHED", "CANCELLED"])
def test_a_dead_rehearsals_twin_is_reclaimed(tmp_path, state):
    """The record's own rehearsal run ended without its destroy's word: its twin is destroyed
    before this rehearsal, rehearsal.twin.reclaimed naming the run and what was removed (US1
    scenario 7, US6 scenario 4)."""
    h = Harness(tmp_path)
    dead_record(h)
    h.flow_runs["dead-run"] = state
    doc = h.run()
    assert doc.status == "ok" and verdicts(doc) == EVERY_PASSES
    assert h.core.children() == ["destroy", "provision", "verify", "step", "step", "destroy"]
    assert h.core.calls.index("destroy") < h.core.calls.index("dry_run")
    reclaimed = [f for f in doc.findings if f.rule == "rehearsal.twin.reclaimed"]
    assert len(reclaimed) == 1 and reclaimed[0].object == "dead-run" and reclaimed[0].step == "destroy"
    assert "destroy run destroy-0" in reclaimed[0].message and "it removed lab fylgja (3 containers)" in \
        reclaimed[0].message
    assert doc.blocks["rehearsal"]["reclaimed"] == {"run": {"workflow_id": WORKFLOW_REHEARSE, "run_id": "dead-run"},
                                                    "cleanup": destroyed().blocks["cleanup"]}
    assert "reclaiming the twin of rehearsal run dead-run" in h.lines


def test_a_rehearsal_run_past_the_platforms_retention_is_reclaimed(tmp_path):
    h = Harness(tmp_path)
    dead_record(h)
    doc = h.run()
    assert [f.rule for f in doc.findings if f.rule == "rehearsal.twin.reclaimed"] == ["rehearsal.twin.reclaimed"]


@pytest.mark.parametrize("state", ["RUNNING", "COMPLETED", "PENDING", "CANCELLING", "unreachable"])
def test_a_rehearsal_not_dead_holds_the_host(tmp_path, state):
    """A rehearsal run still alive, or one that completed (its own destroy ran, so the twin is
    another's), or a platform that cannot say, holds the host: nothing is reclaimed."""
    h = Harness(tmp_path)
    dead_record(h)
    h.flow_runs["dead-run"] = CoreFailure("platform.unreachable", "x", "no answer") if state == "unreachable" else state
    h.core.dry = Document("twin.create", "rejected", None, Findings([
        Finding(REJECTION, "host.twin.present", "twin", "a twin is recorded", "host_check")]), {})
    doc = h.run()
    assert rules(doc)[-1] == "host.twin.present" and "destroy" not in h.core.calls


def test_a_reclaim_whose_destroy_leaves_something_is_unclean(tmp_path):
    h = Harness(tmp_path)
    dead_record(h)
    h.core.destroy_ = lambda c, stop: destroyed(remaining=["lab fylgja (1 container)"])
    doc = h.run()
    assert doc.status == "unclean" and h.core.children() == ["destroy"]
    assert doc.blocks["rehearsal"]["reclaimed"]["cleanup"]["remaining"] == ["lab fylgja (1 container)"]


def test_the_record_follows_the_rehearsal(tmp_path):
    """The record names each stage the twin stands at, with this flow's run, so a run that
    dies leaves its twin its own to reclaim; a clean destroy removes it."""
    h = Harness(tmp_path)
    seen = []
    step = h.core.step

    def watching(c, stop, n):
        rec = h.deps.store.read_record()
        seen.append((rec.stage.label, rec.flow, rec.flow_run_id) if rec else None)
        return step(c, stop, n)

    h.core.step = watching
    doc = h.run()
    assert doc.status == "ok"
    assert seen == [("seeded", FLOW_REHEARSE, RUN), ("third-link", FLOW_REHEARSE, RUN)]
    assert h.deps.store.read_record() is None


def test_the_host_checks_refusal_is_the_rehearsals(tmp_path):
    """The core's dry run of the baseline's create refuses the rehearsal under its own findings,
    the plan's not repeated; one that cannot run is error."""
    h = Harness(tmp_path)
    h.core.dry = Document("twin.create", "rejected", None, Findings([
        Finding(REJECTION, "host.image.absent", "n1", "ghcr.io/nokia/srlinux:24.7.1 is not on this host",
                "host_check")]), {})
    doc = h.run()
    assert doc.status == "rejected" and rules(doc) == ["scope.empty", "host.image.absent"]
    assert len(h.posts) == 1 and h.core.children() == []

    h = Harness(tmp_path / "error")
    h.core.dry = Document("twin.create", "error", None, Findings([
        Finding(REJECTION, "operation.failed", "host_check", "host check: docker not found", "host_check")]), {})
    doc = h.run()
    assert doc.status == "error" and doc.blocks["rehearsal"]["stages"][1]["verdict"] == "not_reached"


# The report's post.


def test_a_report_that_cannot_be_posted_keeps_its_status(tmp_path):
    """A post that fails files rehearsal.report.unposted, a warning naming the proposed change,
    and the status stays the report's (R-11)."""
    h = Harness(tmp_path)
    h.post_failure = "graphql: permission denied"
    doc = h.run()
    assert doc.status == "ok"
    unposted = [f for f in doc.findings if f.rule == "rehearsal.report.unposted"]
    assert len(unposted) == 1 and unposted[0].severity == WARNING and unposted[0].object == "pc-1"
    assert "graphql: permission denied" in unposted[0].message


def test_markdown_is_sent_where_asked(tmp_path):
    h = Harness(tmp_path)
    got = []
    token = twin_rehearse.MARKDOWN.set(got.append)
    try:
        doc = twin_rehearse.run(h.deps, CHANGE, markdown=True)
    finally:
        twin_rehearse.MARKDOWN.reset(token)
    assert doc.status == "ok" and len(got) == 1 and got[0].startswith("## Fylgja rehearsed proposed change")
    assert got[0] + "\n" == h.posts[0][1]


def test_run_raises_a_cancellation_once_the_document_is_made(tmp_path):
    h = Harness(tmp_path)

    def cancel(c, stop, n):
        raise KeyboardInterrupt

    h.core.step = cancel
    with pytest.raises(KeyboardInterrupt):
        twin_rehearse.run(h.deps, CHANGE)
    assert len(h.posts) == 1 and h.core.children()[-1] == "destroy"


# The comment, as the SDK writes it.


class FakeNode:
    def __init__(self, sdk, kind, data):
        self.sdk, self.kind, self.data, self.id = sdk, kind, data, None

    def save(self):
        if self.kind in self.sdk.fail_save:
            raise RuntimeError(f"{self.kind} refused\nquery: …")
        self.id = f"{self.kind}-1"
        self.sdk.saved.append((self.kind, self.data))

    def delete(self):
        self.sdk.deleted.append(self.id)


class FakeSDK:
    def __init__(self, fail_save=()):
        self.fail_save, self.saved, self.deleted, self.created = set(fail_save), [], [], []

    def create(self, kind, branch, data):
        self.created.append((kind, branch))
        return FakeNode(self, kind, data)


def test_post_comment_opens_a_thread_holding_the_comment():
    from fylgja_orchestrator.adapters.infrahub.comment import post_comment

    sdk = FakeSDK()
    assert post_comment(sdk, "pc-1", "## report") is None
    assert sdk.created == [("CoreChangeThread", "main"), ("CoreThreadComment", "main")]
    assert sdk.saved == [("CoreChangeThread", {"change": "pc-1", "label": "Conversation", "resolved": False}),
                         ("CoreThreadComment", {"text": "## report", "thread": "CoreChangeThread-1"})]


def test_post_comment_deletes_the_empty_thread():
    from fylgja_orchestrator.adapters.infrahub.comment import post_comment

    sdk = FakeSDK(fail_save={"CoreThreadComment"})
    failure = post_comment(sdk, "pc-1", "## report")
    assert failure == "CoreThreadComment refused" and sdk.deleted == ["CoreChangeThread-1"]


def test_post_comment_makes_no_call_once_its_time_has_passed():
    from fylgja_orchestrator.adapters.infrahub.comment import post_comment

    sdk = FakeSDK()
    failure = post_comment(sdk, "pc-1", "## report", by=0.0, clock=lambda: 1.0)
    assert failure == "the thread's creation was not made: no time remained" and sdk.created == []


def test_post_names_an_unset_credential_and_never_the_token():
    from fylgja_orchestrator.adapters.infrahub.comment import post

    assert post({}, "pc-1", "x") == "INFRAHUB_ADDRESS is not set"
    assert post({"INFRAHUB_ADDRESS": "http://localhost:8000"}, "pc-1", "x") == "INFRAHUB_API_TOKEN is not set"
