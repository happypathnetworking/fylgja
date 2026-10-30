"""The flow `twin-create` (data-model §7, R-08; FR-018): a twin created from a branch or a
stage, `fylgja twin create --branch|--stage` re-made over the core's operations.

The guards and the scope as the core's server held them (`internal/server/create.go`'s
`runCreate`), each refusal at its step; then the read through the adapter, a stage resolved
first and its line printed, each finding at resolve or read; the snapshot filed under the
orchestrator's `snapshots/`; then `twin.create` of that snapshot file, started detached and
read every two seconds to its document, its out lines printed as they arrive, or, under
`dry_run`, the core's dry run of it, which starts nothing. The document is the create's, as
the core's CLI printed it when the core read the branch: the flow's subject, the stage block
after a resolution, and the resolution's and the read's findings before the core's.

The record follows the twin, as `twin show` names it once the run has ended: a create from a
stage whose twin stands at the stage's snapshot writes it, naming the stage, its proposed
change, the snapshot and this flow's run; a create from a branch whose twin stands removes
it, since that twin names no stage. A dry run, or a create that left no twin at its
snapshot, leaves it as it was.
"""

from prefect import flow

from ..adapters.infrahub import __main__ as tool
from ..adapters.infrahub import stages
from ..adapters.infrahub.session import BUILD_FAILED, BUILD_READ, ERRORS, MOVED_RESOLVED
from ..core import CoreFailure
from ..documents import stages as stages_text
from ..documents.findings import (
    OP_TWIN_CREATE,
    STATUS_ERROR,
    STEP_COMPILE,
    STEP_READ,
    STEP_RESOLVE,
    STEP_START,
    Document,
    Findings,
    error_document,
    new_document,
    rule_error_document,
)
from ..record import FLOW_CREATE
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

FLOW = FLOW_CREATE


def stage_guards(op: str, subject: dict, stage: str, conflicts) -> tuple[stages.Ref | None, Document | None]:
    """A stage's guards at start, before any connection (`stageGuards`): the reference's
    syntax, then each flag a stage stands for, given beside it."""
    try:
        ref = stages.parse_ref(stage)
    except stages.RefError as e:
        return None, rule_error_document(op, subject, stages.RULE_STAGE_REF_INVALID, stage, str(e), STEP_START)
    subject["stage"] = str(ref)
    for given, flag, why in conflicts:
        if given:
            return None, rule_error_document(op, subject, tool.RULE_STAGE_FLAGS_CONFLICT, flag,
                                             f"{flag} is meaningless with --stage: {why}", STEP_START)
    return ref, None


def refused_build(op: str, subject: dict, found: Findings, status: str, block: dict | None) -> Document:
    """The document of a stage's build that stopped before its snapshot: exit 2 for a build
    that could not run and for M1's precision rule, as a resolution kept them."""
    doc = new_document(op, subject, found)
    if status == BUILD_FAILED or found.carries(stages.RULE_AT_PRECISION):
        doc.status = STATUS_ERROR
    if block is not None:
        doc.set("stage", block)
    return doc


def run(deps: Deps, branch: str = "", stage: str | None = None, scope: str | None = None,
        probes_path: str | None = None, dry_run: bool = False) -> Document:
    """The flow's body. `stage`, `scope` and `probes_path` are None when not given."""
    op = OP_TWIN_CREATE
    subject: dict = {"branch": branch}
    if not branch and stage is None:
        return error_document(op, subject, "--branch or --stage is required")
    ref = None
    if stage is not None:
        ref, refused = stage_guards(op, subject, stage, [(branch != "", "--branch", tool.WHOLE_REFERENCE)])
        if refused is not None:
            return refused
    scope, refused = tool.scope_of(op, subject, scope, deps.env())
    if refused is not None:
        return refused
    subject["scope"] = scope
    session, refused = deps.session(op, subject, scope, probes_path)
    if refused is not None:
        return refused

    found = Findings()
    resolved = None
    if ref is not None:
        try:
            ch, found = session.find(ref.branch)
        except ERRORS as e:
            return error_document(op, subject, str(e), STEP_RESOLVE, op)
        if ch is None:
            return refused_build(op, subject, Findings(found).at_step(STEP_RESOLVE), "", None)

        def on_resolved(res: stages.Resolved) -> None:
            subject["branch"], subject["at"] = res.branch, res.at
            deps.out(stages_text.line(res.block()))

        built = session.build(ch, ref, MOVED_RESOLVED, on_resolved=on_resolved)
        resolved = built.resolved
        block = resolved.block() if resolved is not None else None
        if built.status != BUILD_READ:
            return refused_build(op, subject, built.findings, built.status, block)
        snapshot, found = built.snapshot, built.findings
    else:
        try:
            snapshot, found = session.read(branch)
        except ERRORS as e:
            return error_document(op, subject, str(e), STEP_READ, "branch " + branch)
        if snapshot is None:
            return new_document(op, subject, found)
        block = None
    blocks = {"stage": block} if block is not None else {}

    try:
        snapshot_id, file = file_snapshot(deps.store, snapshot)
    except FILING_ERRORS as e:
        doc = filing_failed(op, subject, deps.store, e, found, STEP_COMPILE)
        doc.blocks.update(blocks)
        return doc
    try:
        answer, started = run_core(deps.core, op, {"snapshot": file.path}, [file], deps.out, dry_run)
    except CoreFailure as e:
        doc = core_failed(op, subject, e, found)
        doc.blocks.update(blocks)
        return doc
    doc = composed(op, subject, found, answer, started, blocks)
    if not dry_run and started is not None:
        follow_record(deps, FLOW, snapshot_id, resolved)
    return doc


@flow(name=FLOW, log_prints=False)
def twin_create(branch: str = "", stage: str | None = None, scope: str | None = None,
                probes_path: str | None = None, dry_run: bool = False) -> Document:
    """`fylgja-cli twin create --branch|--stage`."""
    return publish(FLOW, run(Deps.from_env(), branch, stage, scope, probes_path, dry_run))
