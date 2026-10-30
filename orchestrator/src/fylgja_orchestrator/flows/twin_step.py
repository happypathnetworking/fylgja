"""The flow `twin-step` (data-model §7, R-08; FR-018, FR-021): the twin stepped to a stage,
`fylgja twin step [--stage]` re-made over the core's operations and the orchestrator's
record.

The target is the stage given, of any proposed change, or, with none given, the next stage
of the record's own, which needs the record trusted: `twin show` names the record's snapshot,
else `step.target.required` (US6 scenario 2). The target's proposed change is found once and
the target chosen among its stages by the step's rules (`stages.target`: step.target.unknown,
step.target.current, step.stage.skipped), with `stage.twin.moved` beside it when the record's
stage of that proposed change has moved, judged under the record's scope; every read is under
the scope `twin show`'s record names, unless one is given. Then the target is built as `stage
plan` builds a stage (resolved, its line printed, read and taken), its snapshot filed under
the orchestrator's `snapshots/`, and `twin.step` asked to step to that snapshot file with
`allow_restart`, `wait` and `dry_run` passed through: started detached and read every two
seconds to its document, or the core's dry run. The core judges the twin and the host, the
target's scope and mapping against the twin's, the plan and the wait.

The record moves with the twin: once the run has ended and `twin show` names the target's
snapshot, it is written naming the target stage and this flow's run. A dry run, a step
refused, or one that left the twin diverged, leaves it as it was.
"""

from prefect import flow

from ..adapters.infrahub import __main__ as tool
from ..adapters.infrahub import stages
from ..adapters.infrahub.session import BUILD_READ, ERRORS, MOVED_RESOLVED
from ..core import CoreFailure
from ..documents import stages as stages_text
from ..documents.findings import (
    OP_TWIN_STEP,
    STEP_COMPILE,
    STEP_RESOLVE,
    STEP_START,
    Document,
    Findings,
    error_document,
    new_document,
    rule_error_document,
)
from ..record import FLOW_STEP, RecordError, shown_record, target_required, trusted, view
from .common import (
    FILING_ERRORS,
    Deps,
    composed,
    core_failed,
    file_snapshot,
    filing_failed,
    follow_record,
    publish,
    run_core,
)
from .twin_create import refused_build

FLOW = FLOW_STEP


def run(deps: Deps, stage: str | None = None, scope: str | None = None, probes_path: str | None = None,
        allow_restart: bool = False, wait: str | None = None, dry_run: bool = False) -> Document:
    """The flow's body. `stage`, `scope`, `probes_path` and `wait` are None when not given."""
    op = OP_TWIN_STEP
    subject: dict = {}
    given = None
    if stage is not None:
        try:
            given = stages.parse_ref(stage)
        except stages.RefError as e:
            return rule_error_document(op, subject, stages.RULE_STAGE_REF_INVALID, stage, str(e), STEP_START)
        subject["stage"] = str(given)

    # The record, read beside twin show's and trusted only while the two name one snapshot.
    try:
        show = deps.core.show()
    except CoreFailure as e:
        return core_failed(op, subject, e)
    try:
        record = deps.store.read_record()
    except RecordError as e:
        return error_document(op, subject, str(e), STEP_START, str(deps.store.record_path))
    if given is None:
        refused = target_required(record, show)
        if refused is not None:
            return new_document(op, subject, [refused])
    twin = shown_record(show)

    # Every read under the scope the twin records (017; FR-020), unless one is given.
    if scope is None and twin.get("scope"):
        scope = twin["scope"]
    scope, refused = tool.scope_of(op, subject, scope, deps.env())
    if refused is not None:
        return refused
    subject["scope"] = scope
    session, refused = deps.session(op, subject, scope, probes_path)
    if refused is not None:
        return refused

    # The target's proposed change, found once by the given reference's source branch or the
    # record's stage's, and the target chosen among its stages.
    branch = given.branch if given is not None else record.proposed_change.branch
    try:
        ch, found = session.find(branch)
    except ERRORS as e:
        return error_document(op, subject, str(e), STEP_RESOLVE, op)
    if ch is None:
        return new_document(op, subject, found)
    held = view(record, show, ch) if trusted(record, show) else None
    target, _, found = stages.target(ch, held, twin.get("branch") or "", twin.get("at") or "", given)
    if target is None:
        return new_document(op, subject, found)
    found = Findings(found)
    # The record's stage moved under the twin is stage list's warning, beside the target's
    # findings: it refuses nothing, and says nothing of another proposed change's target.
    if held is not None:
        found.extend(stages.twin_moved(ch, held))
    subject["stage"] = str(target)

    def on_resolved(res: stages.Resolved) -> None:
        subject["branch"], subject["at"] = res.branch, res.at
        deps.out(stages_text.line(res.block()))

    built = session.build(ch, target, MOVED_RESOLVED, on_resolved=on_resolved)
    found.extend(built.findings)
    resolved = built.resolved
    blocks = {"stage": resolved.block()} if resolved is not None else {}
    if built.status != BUILD_READ:
        return refused_build(op, subject, found, built.status, blocks.get("stage"))

    try:
        snapshot_id, file = file_snapshot(deps.store, built.snapshot)
    except FILING_ERRORS as e:
        doc = filing_failed(op, subject, deps.store, e, found, STEP_COMPILE)
        doc.blocks.update(blocks)
        return doc
    args: dict = {"snapshot": file.path}
    if allow_restart:
        args["allow_restart"] = True
    if wait is not None:
        args["wait"] = wait
    try:
        answer, started = run_core(deps.core, op, args, [file], deps.out, dry_run)
    except CoreFailure as e:
        doc = core_failed(op, subject, e, found)
        doc.blocks.update(blocks)
        return doc
    doc = composed(op, subject, found, answer, started, blocks)
    if not dry_run and started is not None:
        follow_record(deps, FLOW, snapshot_id, resolved)
    return doc


@flow(name=FLOW, log_prints=False)
def twin_step(stage: str | None = None, scope: str | None = None, probes_path: str | None = None,
              allow_restart: bool = False, wait: str | None = None, dry_run: bool = False) -> Document:
    """`fylgja-cli twin step [--stage]`."""
    return publish(FLOW, run(Deps.from_env(), stage, scope, probes_path, allow_restart, wait, dry_run))
