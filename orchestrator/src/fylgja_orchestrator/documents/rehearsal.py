"""A rehearsal's report (`internal/rehearsal`): the verdict of each stage
(`verdict.go`), the `rehearsal` block of `twin.rehearse`'s document
(`contracts/rehearsal.schema.json`), its text (`report.go`) and its markdown, the comment
the rehearse flow posts on the proposed change (`markdown.go`).

Each renders from the document alone, the markdown with the plan's steps beside it, so the
JSON, the text and the comment of one rehearsal cannot disagree; none names a line of
configuration, a token or a login. The reproduce lines name `fylgja-cli`, the orchestrator's
client, which runs them through the flows, where the core's server named its own; every
other byte is the Go renderers', held to the goldens captured from them
(`tests/golden/`, FR-023, SC-007).

A block's parts are the contract's shapes, as dicts in the Go structs' key order: a stage's
findings are finding dicts, a wait is `{"outcome", "budget_s", "reads", "after_s"}` and a
step's wait as the core reports it adds `failing`, a list of `{"rule", "object",
"message"}`. The rehearse flow fills `Input` and `Result` from the plan and from the core's
documents.
"""

from dataclasses import dataclass, field

from .deadline import ROLE_BASELINE, ROLE_NOT_REACHED, ROLE_REFUSED, ROLE_REHEARSED
from .findings import (
    REJECTION,
    STATUS_OK,
    STATUS_REJECTED,
    WARNING,
    Document,
    Finding,
    Findings,
    quote,
)
from .plan import Pair, StepDiff, link_text
from .stages import AT_GIVEN, AT_WRITTEN, at_source_text

CLI = "fylgja-cli"
"""The client the reproduce lines name: the orchestrator's, whose commands run the flows."""

# The verdicts a stage comes to (rehearsal.schema.json, $defs/stage).
VERDICT_REFUSED = "refused"
"""A stage the plan refused (ROLE_REFUSED)."""
VERDICT_BASELINE = "baseline"
"""The baseline: built and waited on, its wait's failing assertions the baseline findings,
which fail nothing."""
VERDICT_PASSED = "passed"
"""A step that ended stepped or unchanged whose wait holds nothing the baseline's did not."""
VERDICT_FAILED = "failed"
"""A step that diverged, at any phase, or whose wait holds a finding the baseline's did not:
something was learned about the change (status nonconforming)."""
VERDICT_ERROR = "error"
"""A step that could not run, was rejected by its locks or cancelled, a wait that could not
complete, or a stage the deadline or an interrupt cut: nothing was learned (status
error)."""
VERDICT_NOT_REACHED = "not_reached"
"""A stage after one that was not passed."""

# The rehearsal run's outcomes (015's data-model §6).
OUTCOME_OK = "ok"
OUTCOME_STAGE_FAILED = "stage_failed"
OUTCOME_STAGE_ERROR = "stage_error"
OUTCOME_BASELINE_FAILED = "baseline_failed"
OUTCOME_CUT = "cut"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_REJECTED = "rejected"
"""The baseline's create could not start, a run holding its id: nothing touched, no
destroy."""

PROVISION_READY = "ready"
"""The create's outcome for a twin built and recorded."""

# A step's outcomes, the core's three and the run's own.
STEP_STEPPED = "stepped"
STEP_UNCHANGED = "unchanged"
STEP_DIVERGED = "diverged"
STEP_REJECTED = "rejected"
STEP_ERROR = "error"
STEP_CANCELLED = "cancelled"

WAIT_SETTLED = "settled"
WAIT_EXPIRED = "expired"

PUSH_LANDED = "landed"
PUSH_NOT_ATTEMPTED = "not_attempted"

FLOW_MEASURED = "measured"
FLOW_INTERRUPTED = "interrupted"
FLOW_NOT_STARTED = "not_started"

# The steps a finding is filed at, as the core names them.
STEP_START = "start"
STEP_PROVISION = "provision"
STEP_OBSERVE = "observe"

RULE_STAGE_FAILED = "rehearsal.stage.failed"
RULE_STAGE_ERROR = "rehearsal.stage.error"
RULE_BASELINE_FAILED = "rehearsal.baseline.failed"
RULE_DEADLINE_CUT = "rehearsal.deadline.cut"
RULE_RECORD_HOLDS = "verify.record.holds"
RULE_STAGE_MAIN_MOVED = "stage.main.moved"


# The verdict (verdict.go).


@dataclass(frozen=True)
class StepOutcome:
    """A step's result as the verdict reads it: the outcome (stepped, unchanged, diverged,
    rejected, error or cancelled), the phase a step that touched the host stopped at (set on
    a diverged step and on one cancelled after its stage), and the step the run stopped at
    when it did not end stepped or unchanged."""

    outcome: str
    phase: str = ""
    step: str = ""

    def cancelled_before_stage(self) -> bool:
        """Whether the step was cancelled before it touched the host."""
        return self.outcome == STEP_CANCELLED and self.phase == ""


def classify(step: StepOutcome | None, wait: dict | None, baseline, cut: bool) -> tuple[str, list]:
    """A rehearsed stage's verdict, from its step's result, the step's wait, the baseline
    findings and whether the deadline cut the stage, with the wait's failing assertions the
    baseline's did not have (`Classify`):

    - error when cut, when the step gave no result, ended rejected, error or cancelled, or
      its wait did not run or ended incomplete or cancelled, so nothing can be compared;
    - failed when the step diverged, at any phase, with whatever new findings its wait
      holds, or when its wait holds a finding the baseline's did not;
    - passed when the step ended stepped or unchanged and its wait holds nothing new.

    A divergence is decisive: its wait's findings are reported only when the wait read every
    node (settled or expired)."""
    if cut or step is None:
        return VERDICT_ERROR, []
    if step.outcome == STEP_DIVERGED:
        if not _comparable(wait):
            return VERDICT_FAILED, []
        return VERDICT_FAILED, new_findings(baseline, wait.get("failing") or [])
    if step.outcome in (STEP_STEPPED, STEP_UNCHANGED):
        if not _comparable(wait):
            return VERDICT_ERROR, []
        added = new_findings(baseline, wait.get("failing") or [])
        if added:
            return VERDICT_FAILED, added
        return VERDICT_PASSED, []
    return VERDICT_ERROR, []


def _comparable(wait: dict | None) -> bool:
    """A wait that read every node: one that settled, or expired with an assertion still
    failing."""
    return wait is not None and wait.get("outcome") in (WAIT_SETTLED, WAIT_EXPIRED)


def new_findings(baseline, stage) -> list:
    """The stage's failing assertions whose rule and object no baseline finding has, in the
    stage's order (`NewFindings`). The record's claim is never among them."""
    had = {(f["rule"], f["object"]) for f in baseline or []}
    return [f for f in stage or [] if f["rule"] != RULE_RECORD_HOLDS and (f["rule"], f["object"]) not in had]


def stop(verdict: str) -> bool:
    """Whether a stage's verdict stops the run: every verdict but passed, the baseline's and
    the refused branch point's."""
    return verdict not in (VERDICT_PASSED, VERDICT_BASELINE, VERDICT_REFUSED)


# The block (report.go's Build).


@dataclass
class Stage:
    """One stage of the plan as the flow resolved, read and compiled it: its reference, the
    mark's label and description, where its at came from, the branch and the at it resolved
    to ("" when it did not), its snapshot and its bundle ("" when refused), the role the
    rehearsal gives it, and the plan's findings at resolve, read and compile."""

    ref: str
    label: str
    description: str = ""
    at_source: str = ""
    branch: str = ""
    at: str = ""
    snapshot_id: str = ""
    bundle_id: str = ""
    role: str = ""
    findings: Findings = field(default_factory=Findings)

    def __post_init__(self):
        self.findings = Findings(self.findings)


@dataclass
class Input:
    """What the flow decided before the run: the proposed change (`{"id", "name", "branch",
    "draft"}`), when its stages were resolved, the scope every stage was read under, the
    deadline and the ceiling in seconds, the dead rehearsal whose twin was reclaimed first
    (`{"run", "cleanup"}`), and every stage of the plan in order with its role."""

    proposed_change: dict
    resolved_at: str
    scope: str
    deadline_s: int
    ceiling_s: int
    reclaimed: dict | None = None
    stages: list = field(default_factory=list)


@dataclass
class Provision:
    """The baseline's create as it ended: its outcome, its run, the step it stopped at when it
    did not end ready, and its cleanup when it made one."""

    outcome: str
    run_id: str
    step: str = ""
    cleanup: dict | None = None
    workflow_id: str = "fylgja-provision"


@dataclass
class StepRun:
    """A rehearsed stage's step as it ended: its outcome and run, the phase a step that
    touched the host stopped at, the step the run stopped at when it did not end stepped or
    unchanged, the nodes containerlab's plan restarted, recreated or created, each push
    (`{"node", "outcome", "rule"?, "took_s"?}`) and its timings (`{"reconcile_s"?,
    "readiness"?, "push"?, "whole_s"}`)."""

    outcome: str
    phase: str = ""
    step: str = ""
    run_id: str = ""
    restarted: list = field(default_factory=list)
    recreated: list = field(default_factory=list)
    created: list = field(default_factory=list)
    pushed: list = field(default_factory=list)
    timings: dict = field(default_factory=lambda: {"whole_s": 0.0})
    workflow_id: str = "fylgja-step"


@dataclass
class StageResult:
    """One stage the run reached: its verdict, the child it ran (the baseline's create, or a
    rehearsed stage's step), its wait as the core reports it, the wait's last read counted,
    what the step's probe flows lost (None when it read none), the wait's findings the
    baseline's did not have, the child's own findings, and the stage's whole time."""

    ref: str
    verdict: str
    provision: Provision | None = None
    step: StepRun | None = None
    wait: dict | None = None
    counts: dict | None = None
    loss: dict | None = None
    new_findings: list = field(default_factory=list)
    findings: Findings = field(default_factory=Findings)
    took_s: float = 0.0

    def __post_init__(self):
        self.findings = Findings(self.findings)


@dataclass
class Result:
    """What the run came to: its outcome, its run (`{"workflow_id", "run_id"}`), its whole
    time, each stage it reached and the destroy's cleanup. The empty Result is a rehearsal
    refused before any run."""

    outcome: str = ""
    run: dict | None = None
    used_s: float = 0.0
    stages: list = field(default_factory=list)
    destroy: dict | None = None


def _finding(f) -> Finding:
    return f if isinstance(f, Finding) else Finding.from_dict(f)


def _findings(fs) -> Findings:
    return Findings(_finding(f) for f in fs or [])


def build(inp: Input, res: Result) -> dict:
    """The report's rehearsal block (`Build`): every stage of the plan in order, with the
    role the rehearsal gave it and what the run did at it. A stage the run did not reach is
    not reached, whatever role it was given; one the plan refused stays refused. Each stage's
    findings are the plan's, the child's, its wait's failing assertions as warnings, and the
    rehearsal's own; the baseline block is set once the baseline's verdict is baseline."""
    pc = inp.proposed_change
    b = {
        "proposed_change": {"id": pc["id"], "name": pc["name"], "branch": pc["branch"], "draft": bool(pc.get("draft"))},
        "resolved_at": inp.resolved_at, "deadline_s": inp.deadline_s, "ceiling_s": inp.ceiling_s,
        "used_s": res.used_s, "reclaimed": inp.reclaimed,
    }
    if res.run is not None:
        b["run"] = res.run
    b["baseline"] = None
    stages = []
    reached = {r.ref: r for r in res.stages}
    finished: list[str] = []
    for s in inp.stages:
        st = {"ref": s.ref, "label": s.label, "description": s.description, "at_source": s.at_source}
        if s.branch:
            st["branch"] = s.branch
        if s.at:
            st["at"] = s.at
        st.update({"snapshot_id": s.snapshot_id or None, "bundle_id": s.bundle_id or None, "role": s.role,
                   "verdict": "", "findings": [f.to_dict() for f in s.findings], "provision": None, "step": None,
                   "wait": None, "verify": None, "loss": None, "new_findings": [], "took_s": 0})
        r = reached.get(s.ref)
        if s.role == ROLE_REFUSED:
            st["verdict"] = VERDICT_REFUSED
        elif r is None or r.verdict == VERDICT_NOT_REACHED:
            st["role"], st["verdict"] = ROLE_NOT_REACHED, VERDICT_NOT_REACHED
        else:
            st["verdict"] = r.verdict
            st["provision"] = _provision_block(r.provision)
            st["step"] = _step_block(r.step)
            if r.wait is not None:
                w = r.wait
                st["wait"] = {"outcome": w["outcome"], "budget_s": w.get("budget_s", 0), "reads": w.get("reads", 0),
                              "after_s": w.get("after_s", 0)}
            st["verify"] = r.counts
            st["loss"] = r.loss
            st["new_findings"] = _sorted_failing(r.new_findings)
            st["took_s"] = r.took_s
            st["findings"] += [f.to_dict() for f in r.findings]
            st["findings"] += [f.to_dict() for f in stage_findings(s.ref, r.wait)]
            if s.role == ROLE_BASELINE and r.verdict == VERDICT_BASELINE:
                b["baseline"] = {"ref": s.ref, "findings": _failing_of(r.wait)}
            st["findings"] += [f.to_dict() for f in _own_findings(st, r, res.outcome, inp.deadline_s, finished)]
            finished.append(f"{s.ref} took {r.took_s:.1f}s")
        stages.append(st)
    b["stages"] = stages
    b["destroy"] = res.destroy
    b["reproduce"] = reproduce(b, inp.scope)
    return b


def _own_findings(st: dict, r: StageResult, outcome: str, deadline_s: int, finished: list[str]) -> Findings:
    """The rehearsal's own findings at a stage it reached, by its verdict and the run's
    outcome."""
    found = Findings()
    if st["role"] == ROLE_BASELINE and outcome == OUTCOME_BASELINE_FAILED:
        found.add_step(REJECTION, STEP_PROVISION, RULE_BASELINE_FAILED, st["ref"],
                       f"the baseline {st['ref']} could not be built: {_provision_ended(st['provision'])}")
    elif st["verdict"] == VERDICT_FAILED:
        step = STEP_OBSERVE
        why = "its wait holds a finding the baseline's did not: " + _findings_text(st["new_findings"])
        s = st["step"]
        if s is not None and s["outcome"] == STEP_DIVERGED:
            step, why = s.get("phase") or STEP_OBSERVE, _at_phase("diverged", s)
        found.add_step(REJECTION, step, RULE_STAGE_FAILED, st["ref"], why)
    elif st["verdict"] == VERDICT_ERROR and outcome == OUTCOME_CUT:
        done = ", ".join(finished) if finished else "no stage had finished"
        found.add_step(REJECTION, _step_reached(r), RULE_DEADLINE_CUT, st["ref"],
                       f"the deadline of {deadline_s}s passed at stage {st['ref']}: {done}")
    elif st["verdict"] == VERDICT_ERROR and outcome != OUTCOME_CANCELLED:
        found.add_step(REJECTION, _step_reached(r), RULE_STAGE_ERROR, st["ref"], _error_why(st))
    return found


def _step_reached(r: StageResult) -> str:
    """The step a stage that could not be rehearsed stopped at: its child's, the phase it
    stopped at, or observe when its child ended and its wait did not."""
    if r.step is not None and r.step.step:
        return r.step.step
    if r.step is not None and r.step.phase:
        return r.step.phase
    if r.provision is not None and r.provision.outcome != PROVISION_READY:
        return r.provision.step or STEP_PROVISION
    if r.step is not None or r.provision is not None:
        return STEP_OBSERVE
    return STEP_START


def stage_findings(ref: str, wait: dict | None) -> Findings:
    """A stage's wait's failing assertions as warnings, each object prefixed with the
    stage's reference (`StageFindings`)."""
    found = Findings()
    for f in (wait or {}).get("failing") or []:
        found.add_step(WARNING, STEP_OBSERVE, f["rule"], f"{ref}: {f['object']}", f["message"])
    return found


def findings_of(block: dict) -> Findings:
    """Every stage's findings in the stages' order: the block's share of the document's own
    list (`Findings`)."""
    out = Findings()
    for s in block["stages"]:
        out.extend(_finding(f) for f in s["findings"])
    return out


def reproduce(block: dict, scope: str) -> list[str]:
    """The commands that reproduce a failed stage by hand on the same stages, in order
    (`Reproduce`, FR-015): the create from the baseline under scope, a step with
    --allow-restart to each rehearsed stage up to and including the failed one, the verify
    and the destroy. A rehearsed stage at the branch and at of the last stage a command
    named is left out, since the step would refuse it; the verify waits when no step
    precedes it. None when no stage failed."""
    failed = next((i for i, s in enumerate(block["stages"]) if s["verdict"] == VERDICT_FAILED), -1)
    if failed < 0:
        return []
    out: list[str] = []
    branch, at = "", ""
    verify = f"{CLI} twin verify --wait"
    for s in block["stages"][: failed + 1]:
        if s["role"] == ROLE_BASELINE:
            out.append(f"{CLI} twin create --stage {shell_word(s['ref'])} --scope {shell_word(scope)}")
        elif s["role"] == ROLE_REHEARSED:
            if s.get("at") and s.get("branch", "") == branch and s["at"] == at:
                continue
            out.append(f"{CLI} twin step --stage {shell_word(s['ref'])} --allow-restart")
            verify = f"{CLI} twin verify"
        else:
            continue
        branch, at = s.get("branch", ""), s.get("at", "")
    return out + [verify, f"{CLI} twin destroy"]


SHELL_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/@%+=:,-")
"""The characters no shell interprets in a word."""


def shell_word(s: str) -> str:
    """A reference or a scope as a shell reads it: as it is when every character is one no
    shell interprets, and single-quoted otherwise."""
    if s and all(c in SHELL_SAFE for c in s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


# The text (report.go).


def stage_lines(block: dict) -> list[str]:
    """The text's one line per stage after the run (`StageLines`): what the run did at the
    stage, its wait and its counts, its loss when its step measured a probe's flow, then its
    verdict."""
    out = []
    for s in block["stages"]:
        if s["verdict"] == VERDICT_REFUSED:
            parts = [_refused_text(s)]
        elif s["verdict"] == VERDICT_NOT_REACHED:
            parts = ["not reached"]
        else:
            parts = [_child_text(s)]
            if s.get("wait") is not None:
                parts.append(_wait_text(s["wait"]))
            if s.get("verify") is not None:
                parts.append(counts_text(s["verify"]))
            figures = _loss_figures(s.get("loss"), False)
            if figures:
                parts.append("loss " + "; ".join(figures))
            parts.append(_verdict_phrase(s))
        out.append(f"stage {s['ref']}: " + "; ".join(p for p in parts if p))
    return out


def closing(doc: Document) -> str:
    """The text's last line (`Closing`): the status, what the rehearsal came to, the twin's
    end, and on ok the time used against the deadline; on a failure the commands that
    reproduce it follow, one per line, indented. A run whose end was not read says it was
    started, why its end was not read, and that it goes on to its destroy."""
    status = doc.status
    b = doc.blocks.get("rehearsal")
    if b is None:
        return f"rehearsal {status}: nothing was started"
    if b.get("run") is None:
        parts = [_what_it_came_to(b, status)]
    elif _end_unread(b, status):
        run = b["run"]
        parts = [f"run {run['workflow_id']} {run['run_id']} was started and its end was not read "
                 f"({_or_none(_why_unread(doc))})", "it goes on to its destroy, and fylgja twin show says where it is"]
    elif b.get("destroy") is None and status == STATUS_REJECTED:
        parts = [_what_it_came_to(b, status), "no destroy was needed"]
    else:
        parts = [_what_it_came_to(b, status), _destroy_text(b.get("destroy"))]
    if status == STATUS_OK:
        parts.append(f"{b['used_s']:.1f}s of the {b['deadline_s']}s deadline")
    line = f"rehearsal {status}: " + "; ".join(p for p in parts if p)
    if not b.get("reproduce"):
        return line
    return line + "; reproduce it by hand:\n  " + "\n  ".join(b["reproduce"])


def text_lines(doc: Document) -> list[str]:
    """The report's text on stdout: the stage lines, then the closing line, whose reproduce
    commands are lines of their own."""
    b = doc.blocks.get("rehearsal")
    lines = stage_lines(b) if b is not None else []
    return lines + closing(doc).split("\n")


def text(doc: Document) -> str:
    """The report's text as stdout carries it, each line ended."""
    return "".join(line + "\n" for line in text_lines(doc))


def _what_it_came_to(b: dict, status: str) -> str:
    if b.get("run") is None:
        return "nothing was started"
    if not _reached_any(b) and status == STATUS_REJECTED:
        return "the run touched nothing, since a run already holds the id of its baseline's provision"
    built = 0
    for s in b["stages"]:
        if _carries(s["findings"], RULE_BASELINE_FAILED):
            return f"the baseline {s['ref']} could not be built: {_provision_ended(s.get('provision'))}"
        if s["verdict"] == VERDICT_FAILED:
            st = s.get("step")
            if st is not None and st["outcome"] == STEP_DIVERGED:
                return f"stage {s['ref']} failed at phase {st.get('phase', '')}"
            return f"stage {s['ref']} failed: {_findings_text(s['new_findings'])}"
        if s["verdict"] == VERDICT_ERROR:
            return _error_at(s, b["deadline_s"])
        if s["role"] in (ROLE_BASELINE, ROLE_REHEARSED):
            built += 1
    if built == 1:
        return "the baseline alone was built and verified, and no step was rehearsed"
    return f"{built} stages rehearsed, every one passed"


def _end_unread(b: dict, status: str) -> bool:
    """Whether the block is a started run's whose end was not read."""
    return b.get("run") is not None and b.get("destroy") is None and not _reached_any(b) and status != STATUS_REJECTED


def _unfiled(doc: Document) -> Findings:
    """The document's rejections that no stage of its block filed."""
    filed = set()
    b = doc.blocks.get("rehearsal")
    if b is not None:
        filed = {(f.rule, f.step, f.object, f.message) for f in findings_of(b)}
    return Findings(f for f in doc.findings
                    if f.severity == REJECTION and (f.rule, f.step, f.object, f.message) not in filed)


def _why_unread(doc: Document) -> list[str]:
    return [f.message for f in _unfiled(doc)]


def _reached_any(b: dict) -> bool:
    return any(s["role"] in (ROLE_BASELINE, ROLE_REHEARSED) for s in b["stages"])


def _error_at(s: dict, deadline_s: int) -> str:
    if _carries(s["findings"], RULE_DEADLINE_CUT):
        return f"the deadline of {deadline_s}s passed at stage {s['ref']}"
    if _carries(s["findings"], RULE_STAGE_ERROR):
        return f"stage {s['ref']} could not be rehearsed: {_error_why(s)}"
    return "the run was cancelled at stage " + s["ref"]


def _destroy_text(c: dict | None) -> str:
    if c is None:
        return "the destroy did not report"
    if c.get("remaining"):
        return f"the destroy left {', '.join(c['remaining'])}; twin destroy clears it"
    return "the twin is destroyed"


def _child_text(s: dict) -> str:
    p = s.get("provision")
    if p is not None:
        return "created" if p["outcome"] == PROVISION_READY else "not built: " + _provision_ended(p)
    st = s.get("step")
    if st is None:
        return ""
    outcome = st["outcome"]
    if outcome == STEP_STEPPED:
        return f"stepped in {st['timings']['whole_s']:.1f}s" + _parenthesised(_touched(st))
    if outcome == STEP_UNCHANGED:
        return f"unchanged in {st['timings']['whole_s']:.1f}s"
    if outcome == STEP_DIVERGED:
        return _at_phase("diverged", st, *_lifecycle(st))
    if outcome == STEP_CANCELLED:
        if not st.get("phase"):
            return "cancelled before its stage"
        return _at_phase("cancelled", st, *_lifecycle(st))
    if outcome == STEP_REJECTED:
        return "rejected"
    return "could not run"


def _touched(st: dict) -> list[str]:
    out = _lifecycle(st)
    pushes = [f"{p['node']} {p['took_s']:.1f}s" if p.get("took_s") is not None else p["node"] for p in st["pushed"]]
    if pushes:
        out.append("push " + ", ".join(pushes))
    return out


def _lifecycle(st: dict) -> list[str]:
    """The nodes containerlab's plan restarted, recreated or created, by verb, each restarted
    or recreated node with the seconds its readiness took when known:
    `restarted n3 61.2s; recreated n1 70.4s; created n4`."""
    readiness = st["timings"].get("readiness") or {}
    out = []
    for verb, nodes, timed in (("restarted", st["restarted"], True), ("recreated", st["recreated"], True),
                               ("created", st["created"], False)):
        if not nodes:
            continue
        named = [f"{n} {readiness[n]:.1f}s" if timed and n in readiness else n for n in nodes]
        out.append(verb + " " + ", ".join(named))
    return out


def _parenthesised(parts: list[str]) -> str:
    return " (" + "; ".join(parts) + ")" if parts else ""


def _at_phase(ended: str, st: dict, *before: str) -> str:
    """A step that ended at a phase: how it ended and the phase, then the parts before what
    landed, and once a push was planned the nodes whose push landed and those whose did not,
    with each one's identifier."""
    line = f"{ended} at phase {st.get('phase', '')}"
    parts = list(before)
    if st["pushed"]:
        landed, not_landed = [], []
        for p in st["pushed"]:
            if p["outcome"] == PUSH_LANDED:
                landed.append(p["node"])
            elif p.get("rule"):
                not_landed.append(f"{p['node']} ({p['rule']})")
            elif p["outcome"] == PUSH_NOT_ATTEMPTED:
                not_landed.append(p["node"] + " (not attempted)")
            else:
                not_landed.append(p["node"])
        parts.append("landed " + _or_none(landed))
        if not_landed:
            parts.append("not landed " + ", ".join(not_landed))
    return line + ": " + "; ".join(parts) if parts else line


def _verdict_phrase(s: dict) -> str:
    if _carries(s["findings"], RULE_BASELINE_FAILED):
        return ""
    if s["verdict"] == VERDICT_FAILED:
        if s.get("step") is not None and s["step"]["outcome"] == STEP_DIVERGED:
            return "failed"
        return "failed: " + _findings_text(s["new_findings"])
    if s["verdict"] == VERDICT_ERROR:
        if _carries(s["findings"], RULE_DEADLINE_CUT):
            return "error: the deadline passed"
        p = s.get("provision")
        if _carries(s["findings"], RULE_STAGE_ERROR) and p is not None and p["outcome"] != PROVISION_READY:
            return "error"
        if _carries(s["findings"], RULE_STAGE_ERROR):
            return "error: " + _error_why(s)
        return "error: the run was cancelled"
    return s["verdict"]


def _error_why(s: dict) -> str:
    p, st = s.get("provision"), s.get("step")
    if p is not None and p["outcome"] != PROVISION_READY:
        return _provision_ended(p)
    if st is not None:
        if st["outcome"] == STEP_REJECTED:
            return "its step was rejected"
        if st["outcome"] == STEP_ERROR:
            return "its step could not run"
        if st["outcome"] == STEP_CANCELLED:
            if not st.get("phase"):
                return "its step was cancelled before its stage"
            return "its step was cancelled at phase " + st["phase"]
    if st is None and p is None:
        if s["role"] == ROLE_BASELINE:
            return "its provision did not run"
        return "its step did not run"
    w = s.get("wait")
    if w is not None:
        return f"its wait ended {w['outcome']} after {w['after_s']:.1f}s"
    return "its wait did not run"


def _provision_ended(p: dict | None) -> str:
    if p is None:
        return "its provision did not report"
    line = "its provision ended " + p["outcome"]
    if p.get("step"):
        line += " at " + p["step"]
    return line


def _refused_text(s: dict) -> str:
    rules = sorted({f["rule"] for f in s["findings"] if f["severity"] == REJECTION})
    return "refused (" + ", ".join(rules) + ")" if rules else "refused"


def _loss_figures(loss: dict | None, brief: bool) -> list[str]:
    """What a step's probe flows lost, one figure per probe (`lossFigures`):
    `n1-loop 274/300, gap 54.8s`, `n1-loop 12/40 interrupted, gap 3.0s`, `n1-loop not
    started`, `n2-loop added, not measured`. Brief, a figure drops its gap."""
    if loss is None:
        return []
    out = []
    for p in loss.get("probes") or []:
        figure = f"{p['probe']} {p['lost']}/{p['sent']}"
        if p["outcome"] == FLOW_MEASURED:
            pass
        elif p["outcome"] == FLOW_INTERRUPTED:
            figure += " interrupted"
        elif p["outcome"] == FLOW_NOT_STARTED:
            out.append(p["probe"] + " not started")
            continue
        else:
            out.append(p["probe"] + " not read")
            continue
        if not brief:
            figure += f", gap {p['longest_gap_s']:.1f}s"
        out.append(figure)
    out += [p + " added, not measured" for p in loss.get("added") or []]
    out += [p + " dropped, not measured" for p in loss.get("dropped") or []]
    return out


def _wait_text(w: dict) -> str:
    reads = "read" if w["reads"] == 1 else "reads"
    return f"{w['outcome']} after {w['after_s']:.1f}s ({w['reads']} {reads})"


def counts_text(c: dict) -> str:
    """The wait's last read counted over the four assertion kinds, the bursts among them, the
    record's claims aside: `19 held, 0 failed, 0 skipped`, and the unread when any was."""
    held = failed = skipped = unread = 0
    for kind in ("host_name", "port_enabled", "neighbor", "burst"):
        k = c.get(kind) or {}
        held += k.get("held", 0)
        failed += k.get("failed", 0)
        skipped += k.get("skipped") or 0
        unread += k.get("unread") or 0
    line = f"{held} held, {failed} failed, {skipped} skipped"
    if unread > 0:
        line += f", {unread} unread"
    return line


def _findings_text(fs) -> str:
    return _or_none([f"{f['rule']} {f['object']}" for f in fs])


def _carries(fs, rule: str) -> bool:
    return any((f.rule if isinstance(f, Finding) else f["rule"]) == rule for f in fs)


def _or_none(xs) -> str:
    return ", ".join(xs) if xs else "none"


def _provision_block(p: Provision | None) -> dict | None:
    if p is None:
        return None
    out = {"outcome": p.outcome, "run": {"workflow_id": p.workflow_id, "run_id": p.run_id}}
    if p.step:
        out["step"] = p.step
    if p.cleanup is not None:
        out["cleanup"] = p.cleanup
    return out


def _step_block(s: StepRun | None) -> dict | None:
    if s is None:
        return None
    out = {"outcome": s.outcome, "run": {"workflow_id": s.workflow_id, "run_id": s.run_id}}
    if s.phase:
        out["phase"] = s.phase
    pushed = []
    for p in s.pushed:
        push = {"node": p["node"], "outcome": p["outcome"]}
        if p.get("rule"):
            push["rule"] = p["rule"]
        if p.get("took_s") is not None:
            push["took_s"] = p["took_s"]
        pushed.append(push)
    timings = {}
    t = s.timings or {}
    if t.get("reconcile_s") is not None:
        timings["reconcile_s"] = t["reconcile_s"]
    if t.get("readiness"):
        timings["readiness"] = dict(t["readiness"])
    if t.get("push"):
        timings["push"] = dict(t["push"])
    timings["whole_s"] = t.get("whole_s", 0.0)
    out.update({"restarted": list(s.restarted), "recreated": list(s.recreated), "created": list(s.created),
                "pushed": pushed, "timings": timings})
    return out


def _failing_of(wait: dict | None) -> list:
    return [{"rule": f["rule"], "object": f["object"], "message": f["message"]}
            for f in (wait or {}).get("failing") or []]


def _sorted_failing(fs) -> list:
    out = [{"rule": f["rule"], "object": f["object"], "message": f["message"]} for f in fs or []]
    return sorted(out, key=lambda f: (f["rule"], f["object"]))


# The markdown (markdown.go).

CAVEAT = ("*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing; "
          "a loss figure is the container's, never a hardware forwarder's.*")
"""The markdown's last line: what a twin's fidelity is (FR-014), and what a loss figure is
(016, FR-022)."""

COMMENT_MAX = 4092
"""The longest markdown Infrahub keeps as a comment, in bytes: 1.11.2 refuses a text
attribute when 3 and its UTF-8 length reach 4096, and the flow posts the markdown as one
comment's text."""

NAME_MAX = 120
"""The most of a proposed change's name, a branch's or a scope's a brief heading keeps, in
bytes."""

NEW_FEW = 2
"""How many new findings a brief cell names before it counts the rest."""


def _n(s: str) -> int:
    """A string's length as Go's len counts it: in bytes."""
    return len(s.encode("utf-8"))


def markdown(doc: Document, steps=()) -> str:
    """The rehearsal's report as GitHub-flavoured markdown (`Markdown`, FR-014), the
    comment the flow posts on the proposed change: the heading naming Fylgja, the proposed
    change, its branch and the scope read; the run, when the stages were resolved, the
    status and the time used against the deadline and the ceiling; a table of the stages; a
    Mermaid drawing of the stages and what each step between them changed; on any status but
    ok the findings that say why; the stages; the warnings; the baseline's findings; on a
    failure the commands that reproduce it; and the fidelity caveat, last.

    steps are the plan's, each a Pair or a pair as the contract carries it. The markdown is
    never longer than COMMENT_MAX bytes: a report that would be names each finding by its
    identifier and object alone, the table each step by its outcome, and leaves whole
    sections out by an order of preference, the table never; a note before the caveat says
    what was shortened."""
    pairs = [p if isinstance(p, Pair) else Pair.from_dict(p) for p in steps or ()]
    md = _join(_parts(doc, pairs, False))
    if _n(md) <= COMMENT_MAX:
        return md
    return _fit(_parts(doc, pairs, True))


@dataclass
class _Part:
    """A paragraph of the markdown, kept or left out whole: rank 0 always, then the lowest
    rank first. The table, which _fit shrinks rather than leaves out, carries its block."""

    text: str
    name: str = ""
    rank: int = 0
    table: tuple | None = None  # (block, unread)


def _parts(doc: Document, steps: list, brief: bool) -> list[_Part]:
    b = doc.blocks.get("rehearsal")

    def name(s: str) -> str:
        return clip(s, NAME_MAX) if brief else s

    subject = doc.subject or {}
    scope = ", scope " + _inline(name(subject["scope"])) if subject.get("scope") else ""
    if b is None:
        return [
            _Part("## Fylgja did not rehearse branch " + _inline(name(subject.get("branch", ""))) + scope),
            _Part(f"Status **{doc.status}**."),
            _Part(_findings_section("Findings", _rejections(doc.findings), brief, None), "the findings", 1),
            _Part(_warnings_section(doc.findings, [], brief), "the warnings", 2),
            _Part(CAVEAT),
        ]
    unread = _end_unread(b, doc.status)
    verb = "rehearsed"
    if unread:
        verb = "started rehearsing"
    elif b.get("run") is None or not _reached_any(b):
        verb = "did not rehearse"
    pc = b["proposed_change"]
    out = [_Part(f"## Fylgja {verb} proposed change {_inline(quote(name(pc['name'])))} on "
                 f"{_inline(name(pc['branch']))}{scope}")]
    run = b.get("run")
    run_code = _code(f"{run['workflow_id']} {run['run_id']}") if run else ""
    tail = f"Deadline {b['deadline_s']}s (ceiling {b['ceiling_s']}s)."
    if unread:
        out.append(_Part(f"Run {run_code} was started, and its end was not read: {_why_text(doc, brief)}. It goes "
                         f"on to its destroy, and {_code('fylgja twin show')} says where it is. Stages resolved at "
                         f"{_inline(b['resolved_at'])}. Status **{doc.status}**. {tail}"))
    elif run is not None and not _reached_any(b) and doc.status == STATUS_REJECTED:
        out.append(_Part(f"Run {run_code} touched nothing, since a run already holds the id of its baseline's "
                         f"provision, and no destroy was needed; stages resolved at {_inline(b['resolved_at'])}. "
                         f"Status **{doc.status}**. {tail}"))
    elif run is not None:
        out.append(_Part(f"Run {run_code}, stages resolved at {_inline(b['resolved_at'])}. Status **{doc.status}**. "
                         f"{b['used_s']:.1f}s of the {b['deadline_s']}s deadline (ceiling {b['ceiling_s']}s)."))
    else:
        out.append(_Part(f"No run was started; stages resolved at {_inline(b['resolved_at'])}. "
                         f"Status **{doc.status}**. {tail}"))
    out.append(_Part(_table(b, unread, brief), "the table", 0, (b, unread)))
    out.append(_Part(_drawing(b, steps, unread), "the drawing", 6))
    if doc.status != STATUS_OK:
        out.append(_Part(_findings_section("Findings", _rejections(doc.findings), brief, None), "the findings", 3))
    out.append(_Part(_stages_section(b), "the stages", 4))
    out.append(_Part(_warnings_section(doc.findings, b["stages"], brief), "the warnings", 5))
    baseline = (b.get("baseline") or {}).get("findings") or []
    out.append(_Part(_failing_section("Baseline findings", "(reported, failing nothing)", baseline, brief),
                     "the baseline's findings", 7))
    if b.get("reproduce"):
        out.append(_Part("**Reproduce by hand**:\n\n" + _fenced("", "\n".join(b["reproduce"])),
                         "the commands that reproduce it", 2))
    out.append(_Part(CAVEAT))
    return out


def _join(parts: list[_Part]) -> str:
    """The parts as the markdown: a blank line between two, and a newline at the end."""
    return "\n\n".join(p.text for p in parts) + "\n"


@dataclass(frozen=True)
class _Shrunk:
    """How far _fit shrank the table: to each stage's reference and verdict, and how many
    stages it left out; none when there is no table. gaps is whether the brief table dropped
    a loss figure's gap."""

    none: bool = False
    verdicts: bool = False
    left: int = 0
    gaps: bool = False


def _fit(ps: list[_Part]) -> str:
    """The brief parts within COMMENT_MAX (`fit`): those of rank 0, the table among them,
    then each other in rank order while it fits beside the note, which is placed before the
    caveat, the last part."""
    names = []
    longest = _Shrunk(none=True)
    gaps = False
    for p in ps:
        if p.rank > 0:
            names.append(p.name)
        if p.table is not None:
            longest = _Shrunk(verdicts=True, left=len(p.table[0]["stages"]))
            gaps = _measured_any(p.table[0])
    note = _n(_fit_note(names, longest))
    if gaps:
        note = max(note, _n(_fit_note(names, _Shrunk(gaps=True))))
    size = -1 + note + 2
    for p in ps:
        if p.rank == 0 and p.table is None:
            size += 2 + _n(p.text)
    shrunk = _Shrunk(none=longest.none)
    for p in ps:
        if p.table is None:
            continue
        p.text, shrunk = _within(p.table, p.text, COMMENT_MAX - size - 2, gaps)
        size += 2 + _n(p.text)
    order = sorted(range(len(ps)), key=lambda i: ps[i].rank)
    kept = [False] * len(ps)
    for i in order:
        if ps[i].rank == 0:
            kept[i] = True
            continue
        n = size + 2 + _n(ps[i].text)
        if n <= COMMENT_MAX:
            kept[i], size = True, n
    out, left = [], []
    for i, p in enumerate(ps[:-1]):
        if kept[i]:
            out.append(p)
        else:
            left.append(p.name)
    return _join(out + [_Part(_fit_note(left, shrunk)), ps[-1]])


def _within(table: tuple, brief: str, room: int, gaps: bool) -> tuple[str, _Shrunk]:
    """The table within room bytes: brief as it is, or each stage's reference and verdict
    alone, or as many of those rows as fit and a last one counting the rest."""
    if _n(brief) <= room:
        return brief, _Shrunk(gaps=gaps)
    b, unread = table
    lines = ["| stage | verdict |", "|---|---|"]
    size = _n(lines[0]) + 1 + _n(lines[1])
    rows = [_row(_cell(s["ref"]), _cell(_verdict_cell(s, unread))) for s in b["stages"]]
    n = len(rows)
    for r in rows:
        size += 1 + _n(r)
    if size <= room:
        return "\n".join(lines + rows), _Shrunk(verdicts=True)
    while n > 0 and size + 1 + _n(_more_row(len(rows) - n)) > room:
        n -= 1
        size -= 1 + _n(rows[n])
    return "\n".join(lines + rows[:n] + [_more_row(len(rows) - n)]), _Shrunk(verdicts=True, left=len(rows) - n)


def _more_row(left: int) -> str:
    return _row(f"… and {left} more", "")


def fit_note(left: list[str], none: bool = False, verdicts: bool = False, rows_left: int = 0,
             gaps: bool = False) -> str:
    """What the shortening did, as the note says it (`fitNote`), for the tests."""
    return _fit_note(left, _Shrunk(none, verdicts, rows_left, gaps))


def _fit_note(left: list[str], t: _Shrunk) -> str:
    note = (f"*To fit what Infrahub keeps of a comment ({COMMENT_MAX} bytes), each finding is named by its "
            "identifier and object alone")
    if t.none:
        pass
    elif t.left > 0:
        note += f"; the table gives each stage's reference and verdict alone, and the last {t.left} are left out of it"
    elif t.verdicts:
        note += "; the table gives each stage's reference and verdict alone"
    elif t.gaps:
        note += (", and the table each step by its outcome, its loss without its gaps and its new verification "
                 "failures by the first few")
    else:
        note += ", and the table each step by its outcome and its new verification failures by the first few"
    if len(left) == 1:
        note += "; " + left[0] + " is left out"
    elif len(left) > 1:
        note += "; " + ", ".join(left[:-1]) + " and " + left[-1] + " are left out"
    return note + "; fylgja-twin's message is the whole report as text.*"


def clip(s: str, limit: int) -> str:
    """s cut to at most limit bytes, at a character's edge, with an ellipsis when cut."""
    if _n(s) <= limit:
        return s
    cut, offset = 0, 0
    for i, ch in enumerate(s):
        if offset > limit - _n("…"):
            break
        cut = i
        offset += _n(ch)
    return s[:cut] + "…"


def _why_text(doc: Document, brief: bool) -> str:
    if not brief:
        return _inline(_or_none(_why_unread(doc)))
    return _or_none([_code(f.rule) for f in _unfiled(doc)])


def _table(b: dict, unread: bool, brief: bool) -> str:
    """One row per stage: the reference, the at, the snapshot and the bundle by their short
    ids, the step's outcome with the nodes it touched, the wait's outcome, the counts, the
    loss, the new findings and the verdict. Brief, the step is its outcome alone, the loss
    each probe's figure without its gap, and the new findings the first few and how many
    more."""
    lines = [
        "| stage | at | snapshot | bundle | step | wait | verify | loss | new verification failures | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in b["stages"]:
        at = _cell(s["at"]) if s.get("at") else "—"
        snapshot = _short(s["snapshot_id"]) if s.get("snapshot_id") is not None else "—"
        bundle = _short(s["bundle_id"]) if s.get("bundle_id") is not None else "—"
        w = s.get("wait")
        wait = f"{w['outcome']} after {w['after_s']:.1f}s" if w is not None else ""
        counts = counts_text(s["verify"]) if s.get("verify") is not None else ""
        stepped, found = (_step_outcome(s), _new_brief(s)) if brief else (_step_cell(s), _new_cell(s))
        lines.append(_row(_cell(s["ref"]), at, snapshot, bundle, _cell(stepped), wait, counts,
                          _cell(_loss_cell(s, brief)), _cell(found), _cell(_verdict_cell(s, unread))))
    return "\n".join(lines)


def _row(*cells: str) -> str:
    """A table row; an empty cell is written as one space."""
    return "|" + "".join(" |" if c == "" else f" {c} |" for c in cells)


def _step_cell(s: dict) -> str:
    """What the stage's child did, in a cell."""
    p = s.get("provision")
    if p is not None:
        if p["outcome"] == PROVISION_READY:
            return "created"
        return "not built (" + _provision_ended(p).removeprefix("its provision ended ") + ")"
    st = s.get("step")
    if st is None:
        return ""
    outcome = st["outcome"]
    if outcome == STEP_STEPPED:
        parts = [f"stepped {st['timings']['whole_s']:.1f}s"]
    elif outcome == STEP_UNCHANGED:
        return "unchanged"
    elif outcome == STEP_DIVERGED:
        parts = [f"diverged at {st.get('phase', '')} {st['timings']['whole_s']:.1f}s"]
    elif outcome == STEP_CANCELLED:
        if not st.get("phase"):
            return "cancelled before its stage"
        parts = ["cancelled at " + st["phase"]]
    elif outcome == STEP_REJECTED:
        return "rejected"
    else:
        return "could not run"
    parts += _lifecycle(st)
    landed, not_landed = [], []
    for p in st["pushed"]:
        if p["outcome"] == PUSH_LANDED:
            landed.append(p["node"])
        elif p.get("rule"):
            not_landed.append(f"{p['node']} ({p['rule']})")
        else:
            not_landed.append(p["node"])
    if landed:
        parts.append("push " + ", ".join(landed))
    if not_landed:
        parts.append("not landed " + ", ".join(not_landed))
    return "; ".join(parts)


def _step_outcome(s: dict) -> str:
    """The step cell brief: what the stage's child came to, without its nodes and times."""
    p = s.get("provision")
    if p is not None:
        return "created" if p["outcome"] == PROVISION_READY else "not built"
    st = s.get("step")
    if st is None:
        return ""
    if st["outcome"] == STEP_DIVERGED:
        return "diverged at " + st.get("phase", "")
    if st["outcome"] in (STEP_STEPPED, STEP_UNCHANGED, STEP_CANCELLED, STEP_REJECTED):
        return st["outcome"]
    return "could not run"


def _loss_cell(s: dict, brief: bool) -> str:
    """The stage's loss: each probe's figure joined by "; ", or — for a stage whose step read
    no flow."""
    figures = _loss_figures(s.get("loss"), brief)
    return "; ".join(figures) if figures else "—"


def _measured_any(b: dict) -> bool:
    for s in b["stages"]:
        for p in (s.get("loss") or {}).get("probes") or []:
            if p["outcome"] in (FLOW_MEASURED, FLOW_INTERRUPTED):
                return True
    return False


def _new_brief(s: dict) -> str:
    if s["role"] != ROLE_REHEARSED or not _compared(s.get("wait")) or len(s["new_findings"]) <= NEW_FEW:
        return _new_cell(s)
    return f"{_findings_text(s['new_findings'][:NEW_FEW])} and {len(s['new_findings']) - NEW_FEW} more"


def _new_cell(s: dict) -> str:
    """A dash on the baseline, none or each by rule and object on a rehearsed stage whose
    wait settled or expired, not compared on one whose wait ended otherwise, and nothing
    elsewhere."""
    if s["role"] == ROLE_BASELINE:
        return "—"
    if s["role"] == ROLE_REHEARSED and _compared(s.get("wait")):
        return _findings_text(s["new_findings"])
    if s["role"] == ROLE_REHEARSED and s.get("wait") is not None:
        return "not compared"
    return ""


def _compared(w: dict | None) -> bool:
    return w is not None and w["outcome"] in (WAIT_SETTLED, WAIT_EXPIRED)


def _verdict_cell(s: dict, unread: bool) -> str:
    if s["verdict"] == VERDICT_REFUSED:
        return _refused_text(s)
    return _shown_verdict(s, unread)


def _shown_verdict(s: dict, unread: bool) -> str:
    if unread and s["verdict"] == VERDICT_NOT_REACHED:
        return "not read"
    return s["verdict"].replace("_", " ")


def _drawing(b: dict, steps: list, unread: bool) -> str:
    """The Mermaid flowchart, top to bottom: one node per stage labelled with its reference
    and verdict, one edge per pair of stages labelled with what the step between them
    changed, dotted where the plan computed none; a stage that failed or erred outlined red
    by a class."""
    stages = b["stages"]
    lines = ["```mermaid", "flowchart TD"]
    for i, s in enumerate(stages):
        lines.append(f'  s{i}["{_mermaid(s["ref"])}<br/>{_mermaid(_shown_verdict(s, unread))}"]')
    for i in range(1, len(stages)):
        frm, to = stages[i - 1]["ref"], stages[i]["ref"]
        label, computed = "not computed", False
        for p in steps:
            if p.from_ == frm and p.to == to and p.step is not None:
                label, computed = changed(p.step), True
                break
        if computed:
            lines.append(f'  s{i - 1} -- "{_mermaid(label)}" --> s{i}')
        else:
            lines.append(f'  s{i - 1} -. "{_mermaid(label)}" .-> s{i}')
    failed = [f"s{i}" for i, s in enumerate(stages) if s["verdict"] in (VERDICT_FAILED, VERDICT_ERROR)]
    if failed:
        lines += ["  classDef failed stroke:#d32f2f,stroke-width:3px", "  class " + ",".join(failed) + " failed"]
    return "\n".join(lines + ["```"])


def changed(s: StepDiff) -> str:
    """What a step changed, by name and never by content: the links added and removed, the
    nodes added, removed and changed with their reasons (nodes changed for the same reasons
    together), and the nodes whose artifact changed, came or went:
    `+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3`."""
    if s.unchanged:
        return "unchanged"
    parts = ["+link " + link_text(link) for link in s.links_added]
    parts += ["-link " + link_text(link) for link in s.links_removed]
    parts += ["+" + n for n in s.nodes_added]
    parts += ["-" + n for n in s.nodes_removed]
    by_reasons: dict[str, list[str]] = {}
    for c in s.nodes_changed:
        by_reasons.setdefault(", ".join(c["reasons"]), []).append("~" + c["node"])
    parts += [f"{', '.join(nodes)} ({why})" for why, nodes in by_reasons.items()]
    nodes = sorted({a["node"] for a in s.artifacts_changed + s.artifacts_added + s.artifacts_removed})
    if nodes:
        parts.append("artifacts " + ", ".join(nodes))
    return "; ".join(parts) if parts else "unchanged"


def _stages_section(b: dict) -> str:
    """The proposed change's stages as stage list prints them: each reference, the branch
    and the at it resolved to and where the at came from, and a mark's description,
    quoted."""
    lines = ["**Stages** (Infrahub's view does not show them):", ""]
    for s in b["stages"]:
        line = "- " + _code(s["ref"])
        if not s.get("at"):
            line += f" unresolved ({at_source_text(s['at_source'])})"
        else:
            line += f" {_inline(s.get('branch', ''))} at {_inline(s['at'])} ({at_source_text(s['at_source'])})"
        if s["at_source"] in (AT_GIVEN, AT_WRITTEN):
            line += " " + _inline(quote(s["description"]))
        lines.append(line)
    return "\n".join(lines)


def _warnings_section(found, stages: list, brief: bool) -> str:
    """The document's warnings, verify's aside; a warning a stage filed is listed once,
    naming each stage that filed it; the run's own as they came."""
    filed = _stages_filing(stages)
    warnings = Findings()
    listed = set()
    for f in found:
        if f.severity != WARNING or f.rule.startswith("verify."):
            continue
        k = (f.rule, f.object, f.message)
        if k in filed:
            if k in listed:
                continue
            listed.add(k)
        warnings.append(f)

    def suffix(f: Finding) -> str:
        labels = filed.get((f.rule, f.object, f.message))
        if labels is None:
            return ""
        word = "stages" if len(labels) > 1 else "stage"
        return f" ({word} " + ", ".join(_inline(label) for label in labels) + ")"

    return _findings_section("Warnings", warnings, brief, suffix)


def _stages_filing(stages: list) -> dict:
    """Each warning a stage filed, but the run's own, with the labels of the stages that
    filed it, each once, in the stages' order."""
    filed: dict[tuple, list[str]] = {}
    for s in stages:
        for f in s["findings"]:
            f = _finding(f)
            if f.severity != WARNING or _runs_own(f.rule):
                continue
            labels = filed.setdefault((f.rule, f.object, f.message), [])
            if s["label"] not in labels:
                labels.append(s["label"])
    return filed


def _runs_own(rule: str) -> bool:
    return rule == RULE_STAGE_MAIN_MOVED or rule.startswith("rehearsal.")


def _rejections(found) -> Findings:
    return Findings(f for f in found if f.severity == REJECTION)


def _findings_section(title: str, found, brief: bool, suffix) -> str:
    """A titled list of findings, each by identifier, object and message, by rule then
    object, each followed by what suffix adds to it; none when there are none."""
    if not found:
        return f"**{title}**: none"
    ordered = sorted(found, key=lambda f: (f.rule, f.object))
    lines = []
    for f in ordered:
        line = _finding_line(f.rule, f.object, f.message, brief)
        if suffix is not None:
            line += suffix(f)
        lines.append(line)
    return f"**{title}**:\n\n" + "\n".join(_counted(lines))


def _failing_section(title: str, note: str, fs: list, brief: bool) -> str:
    head = f"**{title}** {note}:"
    if not fs:
        return head + " none"
    lines = [_finding_line(f["rule"], f["object"], f["message"], brief) for f in fs]
    return head + "\n\n" + "\n".join(_counted(lines))


def _finding_line(rule: str, obj: str, message: str, brief: bool) -> str:
    line = "- " + _code(rule)
    if obj:
        line += " " + _inline(obj)
    if brief:
        return line
    return line + ": " + _inline(message)


def _counted(lines: list[str]) -> list[str]:
    """Each run of identical lines written once, followed by its count when there are
    several."""
    out = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1
        out.append(f"{lines[i]} (×{j - i})" if j - i > 1 else lines[i])
        i = j
    return out


def _short(id: str) -> str:
    return id[:8] + "…" if len(id) > 8 else id


_MARKUP = set("\\`*_[]<>|~&#!")


def _inline(s: str) -> str:
    """Text as markdown shows it verbatim: each character markdown or GFM would read as
    markup escaped with a backslash, and a line break as a space."""
    out = []
    for ch in s:
        if ch in "\n\r":
            out.append(" ")
        elif ch in _MARKUP:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


_cell = _inline


def _longest_run(s: str, c: str) -> int:
    longest = run = 0
    for ch in s:
        if ch == c:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


def _code(s: str) -> str:
    """A code span holding s verbatim: fenced by one backtick more than the longest run in
    it, and padded when it begins or ends with one."""
    fence = "`" * (_longest_run(s, "`") + 1)
    if s.startswith("`") or s.endswith("`"):
        s = f" {s} "
    return fence + s + fence


def _fenced(info: str, content: str) -> str:
    """A fenced code block holding content verbatim, fenced by three backticks or one more
    than the longest run in it."""
    fence = "`" * max(3, _longest_run(content, "`") + 1)
    return f"{fence}{info}\n{content}\n{fence}"


_MERMAID = str.maketrans({"#": "#35;", '"': "#quot;", "`": "#96;", "<": "#lt;", ">": "#gt;", "\n": " ", "\r": " "})


def _mermaid(s: str) -> str:
    """Text inside one of Mermaid's quoted labels: #, the quote, the backtick and the angle
    brackets as their entities, a line break as a space."""
    return s.translate(_MERMAID)
