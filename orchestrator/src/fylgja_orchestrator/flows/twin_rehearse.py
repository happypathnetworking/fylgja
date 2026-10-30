"""The flow `twin-rehearse` (data-model §7, R-09 to R-11; FR-019): a proposed change's stages
rehearsed on one twin, `fylgja twin rehearse` and the workflow `fylgja-rehearse` re-made over
the core's operations (`internal/server/rehearse.go`, `internal/provision/workflow_rehearse.go`).

In order, each refusal ending the flow with its document and nothing started:

1. the plan, `stage plan`'s (`stage_plan.plan`): the guards, the open proposed change on the
   branch, every stage resolved, read, its snapshot filed, compiled by `twin.compile` and
   stepped from the one before by `twin.diff`; then the baseline rule (015's R-03): the first
   compiled stage is the baseline and each compiled stage after it is rehearsed, the branch
   point refused `scope.empty` at read alone passed over, any other stage refused refusing
   the rehearsal; one compiled stage alone is the baseline, `rehearsal.steps.none`;
2. the deadline, the compiled stages' budgets summed from the packages their manifests name
   (`deadline.py`), refused `rehearsal.deadline.unfit` over the ceiling;
3. the host: a run of the core's in flight refuses it (`run.in_flight`); a twin the record
   names as its own dead rehearsal's (`record.reclaimable`: the platform says the record's
   flow run ended without its destroy, or no longer knows it) is destroyed first,
   `rehearsal.twin.reclaimed`; then the core's dry run of the baseline's create, the host
   check, whose refusal (`host.twin.present` for any other twin) is the rehearsal's.

Then the run: the baseline created by `twin.create` and waited on by `twin.verify --wait`,
its failing assertions the baseline findings; each rehearsed stage stepped to by `twin.step
--allow-restart`, whose wait is its verify, classified against them; stopping at the first
stage whose verdict stops the run; every run started detached and read every two seconds.
The record follows the twin after each create and step, naming this flow's run, so a twin a
run that dies leaves is its own to reclaim. Last, in a `finally`, `twin.destroy`, unless the
baseline's create could not start because a run holds its id, which touched nothing.

The deadline is kept by the flow on its own clock from the run's start, as the workflow's
timer was: once it has passed, the child in progress is interrupted through `run.interrupt`
and read to its end (a create cleans up, a step records diverged), the stage is error, the
run cut, `rehearsal.deadline.cut`, and the destroy follows; no deadline cuts the destroy. The
flow's own `timeout_seconds` is the bound the deadline cannot exceed (research §5.18): a
timeout or a cancellation reaching the body is the cut or the cancellation of the stage in
progress, and the `finally` still destroys and reports. A cancelled flow's process is killed
30 s after its SIGTERM by the platform's runner; the destroy, a run of the core's started at
once, ends whatever becomes of the process, so the flow reads it for 20 s and bounds the post
to the rest.

The report is the `rehearsal` block, its text and its markdown (`documents/rehearsal.py`),
the stages listed again after the run for `rehearsal.stage.moved` and `rehearsal.change.closed`;
the markdown is posted on the proposed change as one thread holding one comment through the
SDK on `main` (`adapters/infrahub/comment.py`), `rehearsal.report.unposted` (warning) when it
cannot be, the status kept. A refusal because the host is held is not posted: a check asks
again while the host is held, and one thread per ask would bury the report.
"""

import contextlib
import contextvars
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from prefect import flow

from ..adapters.infrahub import stages
from ..adapters.infrahub.session import ERRORS
from ..core import CoreFailure
from ..documents import rehearsal as r
from ..documents.deadline import (
    CEILING_S,
    MANIFEST,
    MECHANISM,
    ROLE_BASELINE,
    ROLE_REFUSED,
    ROLE_REHEARSED,
    DeadlineStage,
    deadline,
    fits,
    go_duration,
    node_plans,
    unfit,
)
from ..documents.findings import (
    OP_TWIN_CREATE,
    OP_TWIN_DESTROY,
    OP_TWIN_REHEARSE,
    OP_TWIN_STEP,
    REJECTION,
    RULE_OPERATION_FAILED,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_NONCONFORMING,
    STATUS_OK,
    STATUS_REJECTED,
    STATUS_UNCLEAN,
    STEP_RESOLVE,
    STEP_START,
    WARNING,
    Document,
    Finding,
    Findings,
    new_document,
    quote,
)
from ..documents.plan import PLAN_COMPILED, PLAN_FAILED, PLAN_REFUSED, PlanStage
from ..documents.stages import plural, resolution
from ..record import FLOW_REHEARSE, RecordError, reclaimable, shown_snapshot, trusted
from . import stage_plan
from .common import Deps, follow_record, publish, without_repeats

FLOW = FLOW_REHEARSE

# The runs, as the rehearsal block names them (rehearsal.schema.json, $defs/run): the
# rehearsal's own, the flow's run under the name its report has always given it, and the
# core's three it starts.
WORKFLOW_REHEARSE = "fylgja-rehearse"
WORKFLOW_PROVISION = "fylgja-provision"
WORKFLOW_STEP = "fylgja-step"
WORKFLOW_DESTROY = "fylgja-destroy"
HOLDING = (WORKFLOW_REHEARSE, WORKFLOW_PROVISION, WORKFLOW_STEP, WORKFLOW_DESTROY)
"""The core's runs in flight that refuse a rehearsal (`holdingRun`)."""

ALLOWANCE_S = 300
"""What a rehearsal's flow is allowed before its run starts: the plan, a reclaim and the host
check; `fylgja-twin`'s ALLOWANCE_S."""
DESTROY_S = 120
"""The destroy's whole budget, `fylgja-twin`'s DESTROY_S."""
TIMEOUT_S = ALLOWANCE_S + CEILING_S + DESTROY_S
"""The flow's `timeout_seconds`: the allowance, the ceiling no deadline exceeds and the
destroy, which `fylgja-twin`'s timeout less its own margin covers (4,260 - 240)."""

GRACE_S = 30
"""What Prefect 3.8.8's runner gives a cancelled flow's process between its SIGTERM and its
SIGKILL, fixed in its source and set by no setting (research §5.18)."""
CANCEL_READ_S = 20
"""How long a cancelled rehearsal reads its destroy for: the destroy is the core's run and ends
whatever becomes of the flow's process, so the flow reads it within the grace and leaves room
for the report's post."""
CANCEL_POST_S = 27
"""When, after the cancellation, the report's post makes no further call."""

WAIT_S = MECHANISM.wait
"""Every stage's wait budget: verify's default."""

HELD = frozenset({"run.in_flight", "host.lab.present", "host.twin.present"})
"""The refusals that say the host is held, which `fylgja-twin` asks again on."""

RULE_RUN_IN_FLIGHT = "run.in_flight"
RULE_RUN_CANCELLED = "run.cancelled"
RULE_CLEANUP_INCOMPLETE = "cleanup.incomplete"
RULE_SCOPE_EMPTY = "scope.empty"
RULE_TWIN_RECLAIMED = "rehearsal.twin.reclaimed"
RULE_STEPS_NONE = "rehearsal.steps.none"
RULE_STAGE_MOVED = "rehearsal.stage.moved"
RULE_CHANGE_CLOSED = "rehearsal.change.closed"
RULE_REPORT_UNPOSTED = "rehearsal.report.unposted"

STEP_READ = "read"
STEP_DESTROY = "destroy"
STEP_PROVISION = r.STEP_PROVISION

WAIT_INCOMPLETE = "incomplete"
CLEANUP_SKIPPED = "skipped"
LAB = "lab fylgja"

MARKDOWN: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar("fylgja_markdown",
                                                                                       default=None)
"""Where `markdown=True` sends the report's markdown: the out sink when unset, `fylgja-cli
twin rehearse --markdown`'s stdout when it sets one (T027)."""


@dataclass
class Rehearsed:
    """What the body came to: the document, the markdown rendered from it with the plan's
    steps ("" when no proposed change was found), and the timeout or cancellation that
    reached the run, re-raised by the flow once the document is filed."""

    document: Document
    markdown: str = ""
    raised: BaseException | None = None


# The baseline rule.


@dataclass
class Row:
    """One stage of the plan as the rehearsal takes it: the plan's stage, the role the
    baseline rule gives it, its findings (the plan's, and rehearsal.steps.none on a baseline
    alone)."""

    stage: PlanStage
    role: str
    findings: Findings = field(default_factory=Findings)


def passed_over(ps: PlanStage) -> bool:
    """Whether a planned stage is the branch point refused at read scope.empty, and for
    nothing else: the one refusal a rehearsal passes over (FR-003; 017's FR-015)."""
    if ps.status != PLAN_REFUSED or ps.at_source != stages.AT_BRANCH_POINT:
        return False
    rejections = [f for f in ps.findings if f.severity == REJECTION]
    return len(rejections) == 1 and rejections[0].rule == RULE_SCOPE_EMPTY and rejections[0].step == STEP_READ


def rehearsal_stages(plan) -> tuple[int, list[Row], bool]:
    """The baseline rule over the plan's stages, in order (`rehearsalStages`): the first
    compiled stage is the baseline and each compiled stage after it rehearsed; the branch
    point passed over is a refused row; any other stage refused or failed refuses the
    rehearsal, as does a plan with no compiled stage. Returns the baseline's index (-1 when
    refused), the rows, and whether the rehearsal is refused."""
    baseline, refused, rows = -1, False, []
    for ps in plan.stages:
        row = Row(ps, "", Findings(ps.findings))
        if ps.status == PLAN_COMPILED and baseline < 0:
            row.role, baseline = ROLE_BASELINE, len(rows)
        elif ps.status == PLAN_COMPILED:
            row.role = ROLE_REHEARSED
        else:
            row.role = ROLE_REFUSED
            refused = refused or not passed_over(ps)
        rows.append(row)
    if refused or baseline < 0:
        return -1, rows, True
    if len(rows) - baseline == 1:
        b = rows[baseline]
        b.findings.add_step(WARNING, STEP_RESOLVE, RULE_STEPS_NONE, b.stage.ref,
                            f"stage {b.stage.ref} is the only stage that compiled: it is built, verified and "
                            "destroyed, and no step is rehearsed")
    return baseline, rows, False


def refusal_status(plan) -> str:
    """How a rehearsal the plan refused ends (`refusalStatus`): error when a stage could not be
    planned or broke M1's precision rule, rejected otherwise."""
    for ps in plan.stages:
        if ps.status == PLAN_FAILED or ps.findings.carries(stages.RULE_AT_PRECISION):
            return STATUS_ERROR
    return STATUS_REJECTED


def rehearsal_status(outcome: str, destroy: dict | None) -> str:
    """How a rehearsal that ran ends (015's R-08): rejected when its baseline's create could not
    start because a run holds its id; unclean when the destroy left something or did not
    report; then ok, nonconforming for a stage that failed, failed for a baseline that could
    not be built, and error for a stage that could not be rehearsed, a cut or a cancellation."""
    if outcome == r.OUTCOME_REJECTED:
        return STATUS_REJECTED
    if destroy is None or destroy.get("remaining"):
        return STATUS_UNCLEAN
    return {r.OUTCOME_OK: STATUS_OK, r.OUTCOME_STAGE_FAILED: STATUS_NONCONFORMING,
            r.OUTCOME_BASELINE_FAILED: STATUS_FAILED}.get(outcome, STATUS_ERROR)


def moved_or_closed(branch: str, block: dict, rows) -> Findings:
    """The stages as they were rehearsed against `rows`, the stages listed again after the run
    (`movedOrClosed`): rehearsal.change.closed when the proposed change is no longer open on
    the branch, otherwise rehearsal.stage.moved for each stage built or stepped to that no
    longer resolves to the branch and at it was rehearsed at, or is gone. Warnings both."""
    found = Findings()
    pc = block["proposed_change"]
    now = {str(row.resolved.ref): row.resolved for row in rows if row.resolved.proposed_change.id == pc["id"]}
    if not now:
        found.add_step(WARNING, STEP_RESOLVE, RULE_CHANGE_CLOSED, branch,
                       f"proposed change {quote(pc['name'])} ({pc['id']}) is no longer open on branch {branch}: it was "
                       f"rehearsed as it stood at {block['resolved_at']}")
        return found
    for s in block["stages"]:
        if s["role"] not in (ROLE_BASELINE, ROLE_REHEARSED):
            continue
        res = now.get(s["ref"])
        branch_was, at_was = s.get("branch", ""), s.get("at", "")
        if res is None:
            found.add_step(WARNING, STEP_RESOLVE, RULE_STAGE_MOVED, s["ref"],
                           f"stage {s['ref']} was rehearsed at branch {branch_was} at {at_was}, and is gone from the "
                           "proposed change")
        elif res.branch != branch_was or res.at != at_was:
            found.add_step(WARNING, STEP_RESOLVE, RULE_STAGE_MOVED, s["ref"],
                           f"stage {s['ref']} was rehearsed at branch {branch_was} at {at_was}, and now resolves to "
                           f"branch {res.branch} at {res.at or 'unresolved'}")
    return found


# The core's documents as the report reads them.


def _first_rejection(doc: Document) -> Finding | None:
    return next((f for f in doc.findings if f.severity == REJECTION), None)


def _failing(doc: Document) -> list[dict]:
    """A document's rejections as a wait's failing assertions: rule, object and message."""
    return [{"rule": f.rule, "object": f.object, "message": f.message} for f in doc.findings
            if f.severity == REJECTION]


def provision_outcome(doc: Document) -> str:
    """The baseline's create as it ended, from its run's document: cancelled when the run says
    so, else ready, failed, rejected or error by the status."""
    if doc.findings.carries(RULE_RUN_CANCELLED):
        return "cancelled"
    return {STATUS_OK: r.PROVISION_READY, STATUS_FAILED: "failed", STATUS_REJECTED: "rejected"}.get(doc.status,
                                                                                                 "error")


def step_outcome(doc: Document) -> str:
    """A step as it ended, from its run's document: cancelled when the run says so, else the
    block's outcome (stepped, unchanged or diverged), else rejected or error by the status."""
    if doc.findings.carries(RULE_RUN_CANCELLED):
        return r.STEP_CANCELLED
    outcome = (doc.blocks.get("step") or {}).get("outcome")
    if outcome:
        return outcome
    return r.STEP_REJECTED if doc.status == STATUS_REJECTED else r.STEP_ERROR


def destroy_not_run(what: str, object: str) -> tuple[dict, Findings]:
    """The destroy's cleanup when it checked nothing: neither teardown nor unstage attempted,
    the lab and the twin directory remaining unchecked, under cleanup.incomplete
    (`destroyNotRun`)."""
    cleanup = {"teardown": CLEANUP_SKIPPED, "unstage": CLEANUP_SKIPPED,
               "remaining": [f"{LAB} and the twin directory (not checked: the rehearsal's destroy {what})"]}
    found = Findings()
    found.add_step(REJECTION, STEP_DESTROY, RULE_CLEANUP_INCOMPLETE, object,
                   f"the rehearsal's destroy {what}; what the rehearsal built may remain, and fylgja twin destroy "
                   "clears it")
    return cleanup, found


def held(doc: Document, passed: Findings) -> bool:
    """Whether a refusal says the host is held, and nothing else: rejected, and every rejection
    but the passed-over branch point's one of HELD (`fylgja-twin`'s `holders`)."""
    if doc.status != STATUS_REJECTED:
        return False
    skip = {(f.rule, f.step, f.object, f.message) for f in passed}
    rejections = [f for f in doc.findings
                  if f.severity == REJECTION and (f.rule, f.step, f.object, f.message) not in skip]
    return bool(rejections) and all(f.rule in HELD for f in rejections)


# The rehearsal.


class Rehearsing:
    """One rehearsal as the flow decides and runs it: the plan, the rows the baseline rule made
    of it, the deadline and the ceiling, the findings filed before the run, the reclaim, and,
    once it runs, what each stage came to."""

    def __init__(self, deps: Deps, planned, rows: list[Row], ceiling_s: int):
        self.deps, self.planned, self.rows, self.ceiling_s = deps, planned, rows, ceiling_s
        self.op = OP_TWIN_REHEARSE
        self.subject = planned.subject
        self.deadline_s = 0
        self.before = Findings()
        self.reclaimed: dict | None = None
        self.run_id = ""
        # The run.
        self.started_at = 0.0
        self.deadline_hit = False
        self.cancelled = False
        self.cancelled_at = 0.0
        self.held = False
        self.baseline: list = []
        self.findings = Findings()
        self.results: list[r.StageResult] = []
        self.outcome = ""
        self.raised: BaseException | None = None

    @property
    def pc(self) -> dict:
        return self.planned.res.proposed_change

    def out(self, line: str) -> None:
        self.deps.out(line)

    # Before the run.

    def compute_deadline(self) -> int:
        """The time the rehearsal is bounded by, summed from each compiled stage's node plans
        as the packages its manifest names budget them; a manifest that cannot be read is a
        ValueError naming the stage."""
        budgets = self.deps.budgets()
        counted = []
        for row in self.rows:
            compiled = self.planned.compiled.get(row.stage.ref)
            if compiled is None:
                continue
            try:
                plans = node_plans({MANIFEST: compiled.manifest}, budgets)
            except ValueError as e:
                raise ValueError(f"planning stage {row.stage.ref}'s nodes for the deadline: {e}") from None
            counted.append(DeadlineStage(row.role, plans))
        return deadline(MECHANISM, counted)

    def print_plan(self) -> None:
        """The plan as the rehearsal takes it (`printPlan`): the heading, with the deadline once
        it is known and the scope, then one line per stage and its findings under it."""
        pc = self.pc
        line = f"rehearsal of proposed change {quote(pc['name'])} ({pc['id']}) on branch {pc['branch']}"
        if pc.get("draft"):
            line += ", draft"
        line += ": " + plural(len(self.rows), "stage")
        if self.deadline_s > 0:
            line += f"; deadline {go_duration(self.deadline_s)} (ceiling {go_duration(self.ceiling_s)})"
        self.out(line + ", scope " + self.planned.scope)
        for row in self.rows:
            ps = row.stage
            if ps.status != PLAN_COMPILED:
                self.out(f"{ps.ref}: {ps.status} ({ps.rule})" if ps.rule else f"{ps.ref}: {ps.status}")
            else:
                said = resolution({"branch": ps.branch, "at": ps.at, "at_source": ps.at_source,
                                   "description": ps.description})
                self.out(f"{ps.ref}: {said}; baseline" if row.role == ROLE_BASELINE else f"{ps.ref}: {said}")
            for text in row.findings.text_lines():
                self.out("  " + text)

    def input(self) -> r.Input:
        """The report's input: the proposed change, when the stages were resolved, the scope,
        the deadline and the ceiling, the reclaim, and every stage with its role and
        findings, its snapshot and bundle once it compiled."""
        out = []
        for row in self.rows:
            ps = row.stage
            out.append(r.Stage(ps.ref, ps.label, ps.description, ps.at_source, ps.branch, ps.at,
                               ps.snapshot_id if ps.bundle_id else "", ps.bundle_id, row.role, row.findings))
        resolved_at = self.planned.began.strftime("%Y-%m-%dT%H:%M:%SZ")
        return r.Input(self.pc, resolved_at, self.planned.scope, self.deadline_s, self.ceiling_s, self.reclaimed, out)

    def refuse(self, status: str, extra=()) -> Document:
        """A rehearsal refused before any run: the block, the findings filed before, extra."""
        block = r.build(self.input(), r.Result())
        doc = Document(self.op, status, dict(self.subject),
                       Findings(list(self.before) + list(r.findings_of(block)) + list(extra)))
        doc.set("rehearsal", block)
        return doc

    def failed(self, doc: Document) -> Document:
        """A failure before any run, as the rehearsal's document: its status and findings after
        the block's and those filed before (`failed`)."""
        block = r.build(self.input(), r.Result())
        out = Document(self.op, doc.status, dict(self.subject),
                       Findings(list(self.before) + list(r.findings_of(block)) + list(doc.findings)))
        out.set("rehearsal", block)
        return out

    def host(self) -> Document | None:
        """The host before the run: a run of the core's in flight, then the reclaim of a twin
        the record names as its own dead rehearsal's, then the core's dry run of the baseline's
        create, its host check. None when the host takes the baseline."""
        core = self.deps.core
        try:
            show = core.show()
        except CoreFailure as e:
            return self.failed(e.document(self.op, self.subject))
        for run in (show.blocks.get("show") or {}).get("in_flight") or []:
            wf, run_id = run.get("workflow_id", ""), run.get("run_id", "")
            if wf in HOLDING:
                return self.failed(new_document(self.op, self.subject, [Finding(
                    REJECTION, RULE_RUN_IN_FLIGHT, wf, _in_flight(wf, run_id), STEP_START)]))
        if shown_snapshot(show) is not None:
            refused = self.reclaim(show)
            if refused is not None:
                return refused

        baseline = next(row for row in self.rows if row.role == ROLE_BASELINE)
        compiled = self.planned.compiled[baseline.stage.ref]
        try:
            dry = core.dry_run(OP_TWIN_CREATE, {"snapshot": compiled.file.path}, [compiled.file])
        except CoreFailure as e:
            return self.failed(e.document(self.op, self.subject))
        doc = dry.document
        found = without_repeats(doc.findings, self.planned.res.findings)
        if doc.status == STATUS_REJECTED:
            return self.refuse(STATUS_REJECTED, found)
        if doc.status != STATUS_OK:
            return self.failed(Document(self.op, doc.status, None, found))
        return None

    def reclaim(self, show) -> Document | None:
        """A twin its own dead rehearsal left, destroyed before this one (R-09): the record names
        it, its flow is twin-rehearse, `twin show` names its snapshot, and the platform says
        its flow run ended without its destroy's word or no longer knows it. Any other twin is
        left to the host check, which refuses it. Refused unclean when the destroy leaves
        something; a destroy that cannot start is the rehearsal's failure."""
        try:
            record = self.deps.store.read_record()
        except RecordError:
            return None
        if record is None or record.flow != FLOW_REHEARSE or not record.flow_run_id or not trusted(record, show):
            return None
        try:
            flow_run = self.deps.flow_run(record.flow_run_id, self.deps.environ)
        except CoreFailure:
            return None  # what the run came to is not known: the host is held
        if not reclaimable(record, show, flow_run):
            return None
        dead = record.flow_run_id
        self.out(f"reclaiming the twin of rehearsal run {dead}")
        cleanup, found, destroy_run = self.destroy_run()
        if destroy_run == "":
            message = next((f.message for f in found if f.severity == REJECTION), "the destroy could not start")
            return self.failed(Document(self.op, STATUS_ERROR, None, Findings(
                [Finding(REJECTION, RULE_OPERATION_FAILED, WORKFLOW_DESTROY, message, STEP_DESTROY)])))
        self.reclaimed = {"run": {"workflow_id": WORKFLOW_REHEARSE, "run_id": dead}, "cleanup": cleanup}
        self.before.extend(found)
        if cleanup.get("remaining"):
            return self.refuse(STATUS_UNCLEAN)
        removed = cleanup.get("removed") or []
        said = "it removed " + ", ".join(removed) if removed else "nothing was left to remove"
        self.before.add_step(WARNING, STEP_DESTROY, RULE_TWIN_RECLAIMED, dead,
                             f"the twin of rehearsal run {dead}, which is no longer running, was destroyed by destroy "
                             f"run {destroy_run} before this rehearsal: {said}")
        self.deps.store.clear_record()
        return None

    # The run.

    def passed(self) -> bool:
        """Whether the deadline has passed on the run's clock; once it has, it stays passed."""
        if not self.deadline_hit and self.deps.clock() - self.started_at >= self.deadline_s:
            self.deadline_hit = True
        return self.deadline_hit

    def interrupted(self) -> bool:
        """The deadline passed or the run cancelled: the children are cut."""
        return self.passed() or self.cancelled

    def run(self) -> None:
        """The stages in order, then the destroy, which runs whatever stopped the stages unless
        the baseline's create could not start because a run holds its id."""
        self.started_at = self.deps.clock()
        self.run_id = self.deps.flow_run_id or str(uuid.uuid4())
        self.subject["run_id"] = self.run_id
        self.out(f"run {WORKFLOW_REHEARSE} {self.run_id}")
        self.destroy = None
        self.destroy_findings = Findings()
        try:
            self.stages()
        finally:
            if self.outcome != r.OUTCOME_REJECTED:
                until = self.cancelled_at + CANCEL_READ_S if self.cancelled else None
                self.destroy, self.destroy_findings, _ = self.destroy_run(announce=True, until=until)
                self.forget()
            self.used_s = self.deps.clock() - self.started_at

    def stages(self) -> None:
        stopped = False
        current: tuple[Row, float] | None = None
        try:
            for row in self.rows:
                ref = row.stage.ref
                if row.role == ROLE_REFUSED:
                    self.results.append(r.StageResult(ref, r.VERDICT_REFUSED))
                    continue
                if stopped or row.role not in (ROLE_BASELINE, ROLE_REHEARSED):
                    self.results.append(r.StageResult(ref, r.VERDICT_NOT_REACHED))
                    continue
                current = (row, self.deps.clock())
                if self.passed():
                    # Cut between two stages: this one is the stage in progress.
                    st = self._took(r.StageResult(ref, r.VERDICT_ERROR), current[1])
                elif row.role == ROLE_BASELINE:
                    st = self.baseline_stage(row)
                else:
                    st = self.rehearsed_stage(row)
                current = None
                self.results.append(st)
                if r.stop(st.verdict):
                    stopped = True
                    self.outcome = self.outcome_of(row, st)
        except BaseException as e:  # noqa: BLE001 - a timeout, a cancellation or a fault: the destroy follows
            if current is not None:
                self.results.append(self._took(r.StageResult(current[0].stage.ref, r.VERDICT_ERROR), current[1]))
            if isinstance(e, TimeoutError):
                self.deadline_hit, self.raised = True, e
                self.outcome = r.OUTCOME_CUT
            elif isinstance(e, Exception):
                ref = current[0].stage.ref if current is not None else self.run_id
                self.findings.add_step(REJECTION, STEP_START, RULE_OPERATION_FAILED, ref,
                                       f"the rehearsal stopped at stage {ref}: {e}")
                self.outcome = r.OUTCOME_CUT if self.deadline_hit else r.OUTCOME_STAGE_ERROR
            else:
                self.cancelled, self.cancelled_at, self.raised = True, self.deps.clock(), e
                self.outcome = r.OUTCOME_CANCELLED
        if not self.outcome:
            self.outcome = r.OUTCOME_OK

    def outcome_of(self, row: Row, st: r.StageResult) -> str:
        """The run's outcome when stage st stopped it (`outcome`)."""
        if row.role == ROLE_BASELINE and st.provision is None and self.held:
            return r.OUTCOME_REJECTED
        if self.deadline_hit:
            return r.OUTCOME_CUT
        if self.cancelled:
            return r.OUTCOME_CANCELLED
        if row.role == ROLE_BASELINE and st.provision is not None and st.provision.outcome == "failed":
            return r.OUTCOME_BASELINE_FAILED
        if st.verdict == r.VERDICT_FAILED:
            return r.OUTCOME_STAGE_FAILED
        return r.OUTCOME_STAGE_ERROR

    def _took(self, st: r.StageResult, began: float) -> r.StageResult:
        st.took_s = self.deps.clock() - began
        return st

    def start(self, op: str, args: dict, files, workflow_id: str, step: str, st: r.StageResult) -> str:
        """Starts a child detached and returns its run id, "" when it did not start: a child
        refused because a run holds its id files run.in_flight and sets held; one refused
        otherwise carries the core's refusal as its own findings; one the core could not be
        asked for files operation.failed at step (`started`)."""
        self.held = False
        try:
            started = self.deps.core.start(op, args, files)
        except CoreFailure as e:
            if not self.interrupted():
                self.findings.add_step(REJECTION, step, RULE_OPERATION_FAILED, workflow_id,
                                       f"the rehearsal's {workflow_id} could not start: {e.message}")
            return ""
        if started.run is not None and started.run.run_id:
            self.out(f"run {workflow_id} {started.run.run_id}")
            return started.run.run_id
        doc = started.document
        if doc is not None and doc.findings.carries(RULE_RUN_IN_FLIGHT):
            self.held = True
            message = f"the rehearsal's {workflow_id} could not start: a run is already in flight under its id"
            if workflow_id == WORKFLOW_PROVISION:
                message += (", so the rehearsal touched nothing and ran no destroy; wait for that run to finish, "
                            "or run fylgja twin destroy to cancel it")
            self.findings.add_step(REJECTION, step, RULE_RUN_IN_FLIGHT, workflow_id, message)
        elif doc is not None:
            st.findings.extend(doc.findings)
        return ""

    def follow(self, workflow_id: str, run_id: str):
        """A child read every two seconds to its document; once the deadline has passed, the
        child is interrupted and read on to its end, its cleanup or its record. Raises
        CoreFailure when the core cannot be asked."""
        core = self.deps.core
        answer = core.read(workflow_id, run_id, on_out=self.out, stop=self.passed)
        if answer.document is None:
            # A failed interrupt leaves the read to go on; the destroy cancels what still runs.
            with contextlib.suppress(CoreFailure):
                core.interrupt(workflow_id, run_id)
            answer = core.read(workflow_id, run_id, on_out=self.out)
        return answer

    def closed_without(self, e: CoreFailure, run_id: str, step: str) -> None:
        """A child whose end could not be read: operation.failed on its run, unless the deadline
        or the cancellation stopped it."""
        if not self.interrupted():
            self.findings.add_step(REJECTION, step, RULE_OPERATION_FAILED, run_id, e.message)

    def baseline_stage(self, row: Row) -> r.StageResult:
        """The twin created from the baseline by `twin.create` of its snapshot, then waited on by
        `twin.verify --wait`: a wait that read every node gives the baseline findings and the
        verdict baseline; anything else is error, since no later stage could be compared with
        it. A create refused because a run holds its id did not reach the stage."""
        began = self.deps.clock()
        ref = row.stage.ref
        st = r.StageResult(ref, r.VERDICT_ERROR)
        compiled = self.planned.compiled[ref]
        self.out(f"stage {ref}: creating the twin")
        run_id = self.start(OP_TWIN_CREATE, {"snapshot": compiled.file.path}, [compiled.file], WORKFLOW_PROVISION,
                            STEP_PROVISION, st)
        if not run_id:
            if self.held:
                st.verdict = r.VERDICT_NOT_REACHED
            return self._took(st, began)
        try:
            doc = self.follow(WORKFLOW_PROVISION, run_id).document
        except CoreFailure as e:
            self.closed_without(e, run_id, STEP_PROVISION)
            return self._took(st, began)
        outcome = provision_outcome(doc)
        first = _first_rejection(doc)
        st.provision = r.Provision(outcome, run_id)
        if outcome != r.PROVISION_READY:
            st.provision.step = first.step if first is not None else ""
            st.provision.cleanup = doc.blocks.get("cleanup")
        st.findings.extend(doc.findings)
        if outcome == r.PROVISION_READY:
            follow_record(self.deps, FLOW, compiled.snapshot_id, compiled.resolved)
        if outcome != r.PROVISION_READY or self.interrupted():
            return self._took(st, began)

        st.wait, st.counts = self.verify(ref)
        w = st.wait
        if w is not None and not self.interrupted() and w["outcome"] in (r.WAIT_SETTLED, r.WAIT_EXPIRED):
            st.verdict = r.VERDICT_BASELINE
            self.baseline = list(w["failing"])
        return self._took(st, began)

    def verify(self, ref: str) -> tuple[dict | None, dict | None]:
        """The baseline's wait, `twin.verify --wait` under the stage's budget: its outcome, its
        reads and their time, its failing assertions (the verify's rejections) and the last
        read's counts. A verify that answers no wait is incomplete with what it said; one the
        core cannot be asked for, incomplete with the failure, or no wait once cut."""
        try:
            doc = self.deps.core.verify(wait=go_duration(WAIT_S)).document
        except CoreFailure as e:
            if self.interrupted():
                return None, None
            wait = {"outcome": WAIT_INCOMPLETE, "budget_s": WAIT_S, "reads": 0, "after_s": 0.0,
                    "failing": [{"rule": e.rule, "object": e.object, "message": e.message}]}
            self.out(f"stage {ref}: verify: {r.wait_text(wait)}")
            return wait, None
        block = doc.blocks.get("verify") or {}
        w = block.get("wait")
        if w is None:
            wait = {"outcome": WAIT_INCOMPLETE, "budget_s": WAIT_S, "reads": 0, "after_s": 0.0,
                    "failing": _failing(doc)}
        else:
            wait = {"outcome": w.get("outcome", WAIT_INCOMPLETE), "budget_s": w.get("budget_s", WAIT_S),
                    "reads": w.get("reads", 0), "after_s": w.get("after_s", 0.0), "failing": _failing(doc)}
        self.out(f"stage {ref}: verify: {r.wait_text(wait)}")
        return wait, block.get("counts")

    def rehearsed_stage(self, row: Row) -> r.StageResult:
        """The twin stepped to the stage by `twin.step --allow-restart` of its snapshot, whose
        wait after its record is the stage's verify, classified against the baseline findings.
        A stage the deadline or the cancellation cut is error whatever its step says."""
        began = self.deps.clock()
        ref = row.stage.ref
        st = r.StageResult(ref, r.VERDICT_ERROR)
        compiled = self.planned.compiled[ref]
        self.out(f"stage {ref}: stepping")
        run_id = self.start(OP_TWIN_STEP, {"snapshot": compiled.file.path, "allow_restart": True}, [compiled.file],
                            WORKFLOW_STEP, STEP_START, st)
        if not run_id:
            return self._took(st, began)
        try:
            doc = self.follow(WORKFLOW_STEP, run_id).document
        except CoreFailure as e:
            self.closed_without(e, run_id, STEP_START)
            return self._took(st, began)
        block = doc.blocks.get("step") or {}
        outcome = step_outcome(doc)
        first = _first_rejection(doc)
        stopped_at = "" if outcome in (r.STEP_STEPPED, r.STEP_UNCHANGED) else (first.step if first else "")
        plan = block.get("reconcile") or {}
        st.step = r.StepRun(outcome, block.get("phase", ""), stopped_at, run_id, list(plan.get("restarted") or []),
                            list(plan.get("recreated") or []), list(plan.get("added") or []),
                            list(block.get("pushed") or []), dict(block.get("timings") or {"whole_s": 0.0}))
        w = block.get("wait")
        st.wait = w if w is not None and w.get("outcome") else None
        st.counts, st.loss = block.get("wait_counts"), block.get("loss")
        st.findings.extend(doc.findings)
        st.verdict, st.new_findings = r.classify(r.StepOutcome(outcome, st.step.phase, stopped_at), st.wait,
                                                 self.baseline, self.interrupted())
        follow_record(self.deps, FLOW, compiled.snapshot_id, compiled.resolved)
        return self._took(st, began)

    def destroy_run(self, announce: bool = False, until: float | None = None) -> tuple[dict, Findings, str]:
        """`twin.destroy`, detached and read to its end: its cleanup, its findings and its run,
        or, when it checked nothing, the cleanup and finding saying so and no run (""). No
        deadline cuts it; after a cancellation it is read until `until` alone, the platform
        killing the flow's process soon after, and a destroy still running then goes on in the
        core, its report not read."""
        core = self.deps.core
        if announce:
            self.out("destroying the twin")
        said: list[str] = []
        try:
            started = core.start(OP_TWIN_DESTROY, {}, (), on_out=said.append)
        except CoreFailure as e:
            return (*destroy_not_run(f"could not start ({e.message})", WORKFLOW_DESTROY), "")
        if started.run is None or not started.run.run_id:
            first = _first_rejection(started.document) if started.document is not None else None
            why = first.message if first is not None else "the core started no run"
            return (*destroy_not_run(f"could not start ({why})", WORKFLOW_DESTROY), "")
        run_id = started.run.run_id
        # What the destroy cancels first is its start's to say, its run named once.
        for line in said:
            self.out(line)
        if f"{WORKFLOW_DESTROY} {run_id}" not in " ".join(said):
            self.out(f"run {WORKFLOW_DESTROY} {run_id}")
        stop = (lambda: self.deps.clock() >= until) if until is not None else None
        try:
            doc = core.read(WORKFLOW_DESTROY, run_id, on_out=self.out, stop=stop).document
        except CoreFailure as e:
            return (*destroy_not_run(f"run {run_id} closed without a result ({e.message})", run_id), run_id)
        if doc is None:
            return (*destroy_not_run(f"run {run_id} had not ended {CANCEL_READ_S}s after the cancellation, within "
                                     f"the {GRACE_S}s the platform gives a cancelled flow; it goes on in the core",
                                     run_id), run_id)
        cleanup = doc.blocks.get("cleanup")
        if cleanup is None:
            return (*destroy_not_run(f"run {run_id} closed without its cleanup", run_id), run_id)
        return cleanup, Findings(doc.findings), run_id

    def forget(self) -> None:
        """The record after the destroy: removed when it is this rehearsal's and nothing
        remains, since no twin stands for it to name."""
        if self.destroy is None or self.destroy.get("remaining"):
            return
        try:
            record = self.deps.store.read_record()
        except RecordError:
            return
        if record is not None and record.flow == FLOW and record.flow_run_id == self.deps.flow_run_id:
            self.deps.store.clear_record()

    # The report.

    def result(self) -> r.Result:
        return r.Result(self.outcome, {"workflow_id": WORKFLOW_REHEARSE, "run_id": self.run_id}, self.used_s,
                        self.results, self.destroy)

    def reported(self) -> Document:
        """The rehearsal's document once its run closed (`reported`): the block, its findings,
        the run's own, the destroy's, the cancellation's, the stages read again; the status by
        015's R-08; then the stage lines and the closing line."""
        block = r.build(self.input(), self.result())
        found = Findings(list(self.before) + list(r.findings_of(block)) + list(self.findings))
        found.extend(self.destroy_findings)
        if self.outcome == r.OUTCOME_CANCELLED:
            reached = next((s for s in reversed(self.results) if s.verdict == r.VERDICT_ERROR), None)
            step = r.step_reached(reached) if reached is not None else STEP_START
            at = reached.ref if reached is not None else "none"
            found.add_step(REJECTION, step, RULE_RUN_CANCELLED, self.run_id,
                           f"rehearsal run {self.run_id} was cancelled at stage {at}, by the operator's interrupt or "
                           "the platform's cancellation; its destroy ran")
        found.extend(self.after(block))
        doc = Document(self.op, rehearsal_status(self.outcome, self.destroy), dict(self.subject), found)
        doc.set("rehearsal", block)
        for line in r.stage_lines(block):
            self.out(line)
        for line in r.closing(doc).split("\n"):
            self.out(line)
        return doc

    def after(self, block: dict) -> Findings:
        """The proposed change's stages listed again once the run has closed, for
        moved_or_closed's warnings; stages that cannot be listed are rehearsal.stage.moved
        naming the branch."""
        branch = self.planned.res.branch
        why = ""
        try:
            listed, refused = self.planned.session.stage_list(branch)
            if refused.rejected:
                why = next(f.message for f in refused if f.severity == REJECTION)
        except ERRORS as e:
            why = str(e)
        if why:
            found = Findings()
            found.add_step(WARNING, STEP_RESOLVE, RULE_STAGE_MOVED, branch,
                           f"the stages of branch {branch} could not be read again after the run ({why}): whether a "
                           "rehearsed stage moved is unknown")
            return found
        return moved_or_closed(branch, block, listed.rows)


def _in_flight(workflow_id: str, run_id: str) -> str:
    """run.in_flight's words for a run of the core's that holds the host (`InFlightRefusal`)."""
    remedy = "wait for it to finish, or run fylgja twin destroy to cancel it"
    if workflow_id == WORKFLOW_PROVISION:
        return f"provisioning run {run_id} is already in flight; {remedy}"
    if workflow_id == WORKFLOW_DESTROY:
        return f"destroy run {run_id} is already in flight; wait for it to finish"
    if workflow_id == WORKFLOW_REHEARSE:
        return f"rehearsal run {run_id} is already in flight; {remedy}"
    return f"step run {run_id} is already in flight; {remedy}"


def rehearse(deps: Deps, branch: str = "", scope: str | None = None, probes_path: str | None = None,
             ceiling_s: int = CEILING_S) -> Rehearsed:
    """The flow's body: the plan, the baseline rule, the deadline, the host, the run, the
    report and its post."""
    op = OP_TWIN_REHEARSE
    planned, refused = stage_plan.plan(deps, op, branch, scope, probes_path, {"branch": branch})
    if refused is not None:
        return Rehearsed(refused, r.markdown(refused))
    res = planned.res
    if res.proposed_change is None:
        # Refused whole before any stage was planned: the kind absent, no open proposed
        # change on the branch, or the branch gone. There is no proposed change to post on.
        doc = new_document(op, planned.subject, res.findings)
        return Rehearsed(doc, r.markdown(doc))

    baseline, rows, refused_plan = rehearsal_stages(res)
    rh = Rehearsing(deps, planned, rows, ceiling_s)
    if refused_plan:
        rh.print_plan()
        return _finish(rh, rh.refuse(refusal_status(res)))
    try:
        rh.deadline_s = rh.compute_deadline()
    except ValueError as e:
        return _finish(rh, rh.failed(Document(op, STATUS_ERROR, None, Findings(
            [Finding(REJECTION, RULE_OPERATION_FAILED, op, str(e), STEP_START)]))))
    rh.print_plan()
    if not fits(rh.deadline_s, ceiling_s):
        return _finish(rh, rh.refuse(STATUS_REJECTED, unfit(branch, rh.deadline_s, ceiling_s)))
    refusal = rh.host()
    if refusal is not None:
        return _finish(rh, refusal)
    rh.run()
    by = rh.cancelled_at + CANCEL_POST_S if rh.cancelled else None
    return _finish(rh, rh.reported(), rh.raised, by)


def _finish(rh: Rehearsing, doc: Document, raised: BaseException | None = None, by: float | None = None
            ) -> Rehearsed:
    """The document, its markdown and its post on the proposed change: one thread holding one
    comment, unless the host is held, which a check asks again on, bounded by `by` on the
    flow's clock after a cancellation. A post that fails files rehearsal.report.unposted, a
    warning: the status is the report's."""
    md = r.markdown(doc, rh.planned.res.steps)
    passed = Findings(f for row in rh.rows if row.role == ROLE_REFUSED and passed_over(row.stage)
                      for f in row.findings if f.severity == REJECTION)
    if not held(doc, passed):
        pc = rh.pc["id"]
        failure = rh.deps.post(rh.deps.environ, pc, md, by)
        if failure:
            doc.findings.append(Finding(WARNING, RULE_REPORT_UNPOSTED, pc,
                                        f"the rehearsal's report could not be posted as a thread on proposed change "
                                        f"{pc}: {failure}; the status is kept"))
    return Rehearsed(doc, md, raised)


def run(deps: Deps, branch: str = "", scope: str | None = None, probes_path: str | None = None,
        markdown: bool = False) -> Document:
    """The flow's run: the body, the markdown sent where MARKDOWN says under `markdown`, the
    document filed as the run's artifact, then a timeout or a cancellation that reached the run
    raised again, so the platform records it."""
    done = rehearse(deps, branch, scope, probes_path)
    if markdown and done.markdown:
        sink = MARKDOWN.get() or deps.out
        sink(done.markdown.removesuffix("\n"))
    publish(FLOW, done.document)
    if done.raised is not None:
        raise done.raised
    return done.document


@flow(name=FLOW, log_prints=False, timeout_seconds=TIMEOUT_S)
def twin_rehearse(branch: str = "", scope: str | None = None, probes_path: str | None = None,
                  markdown: bool = False) -> Document:
    """`fylgja-cli twin rehearse --branch <b>`."""
    return run(Deps.from_env(), branch, scope, probes_path, markdown)


