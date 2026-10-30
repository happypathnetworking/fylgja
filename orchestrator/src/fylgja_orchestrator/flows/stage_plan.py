"""The flow `stage-plan` (data-model §7, R-08; FR-011, FR-018): a proposed change's plan,
`fylgja stage plan` re-made over the core's operations (`internal/server/stages.go`'s
`runStagePlan` and `internal/stages/plan.go`'s `Plan` and `build`).

The guards (--branch, its form, the scope), then the session (the packages, the request's one
probe list), then the open proposed change on the branch, found once, its heading printed.
Each of its stages in order is built as far as Infrahub takes it (resolved, stage.main.moved
filed with the branch point alone, read and taken), its snapshot filed under the
orchestrator's `snapshots/`, then compiled by the core's `twin.compile` of that file, each
compile finding at compile; a refused stage is reported and the plan goes on. The step
between each two consecutive stages that compiled is the core's `twin.diff` of their two
snapshot files, the artifacts that came and went with their nodes read from the two
manifests (`plan.step_of_diff`). Each step is printed before the stage it leads to, as each
is known, and the `plan` block and its findings are the document's.

A compiled stage's lossy mappings and shared ports are its manifest's `fidelity.lossy`
counted as the compiler's survey counts them (`Manifest.LossyCounts`); a stage whose compile
was refused has no manifest, and counts none (research §5.17).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime

from prefect import flow

from ..adapters.infrahub import __main__ as tool
from ..adapters.infrahub import stages
from ..adapters.infrahub.session import BUILD_READ, ERRORS, MOVED_ALWAYS, MOVED_NEVER
from ..core import CoreFailure
from ..documents import stages as stages_text
from ..documents.findings import (
    OP_STAGE_PLAN,
    REJECTION,
    RULE_OPERATION_FAILED,
    STATUS_OK,
    STEP_COMPILE,
    STEP_RESOLVE,
    STEP_START,
    Document,
    Findings,
    error_document,
    rule_error_document,
)
from ..documents.plan import PLAN_COMPILED, PlanResult, PlanStage, step_of_diff
from .common import FILING_ERRORS, Deps, core_failed, file_snapshot, publish

FLOW = "stage-plan"

MANIFEST = "manifest.json"


def lossy_counts(manifest: bytes) -> tuple[int, int]:
    """A bundle's lossy record in two numbers (`Manifest.LossyCounts`): its entries, and the
    distinct ports of a device that more than one interface renders to."""
    lossy = (json.loads(manifest).get("fidelity") or {}).get("lossy") or []
    shared = {(e["device"], e["port"]) for e in lossy if e.get("shares")}
    return len(lossy), len(shared)


class _Compiled:
    """A stage the core compiled: the snapshot file it was sent, its id, its bundle's manifest
    and the stage it resolved to (the record's, should a flow create or step to it)."""

    def __init__(self, file, manifest: bytes, snapshot_id: str = "", resolved=None):
        self.file, self.manifest = file, manifest
        self.snapshot_id, self.resolved = snapshot_id, resolved


@dataclass
class Planned:
    """A plan as far as it went (`plannedStages`): the scope every stage was planned under, the
    subject the command's document carries, the session it was read through, when the stages
    began to be resolved, the result, and each compiled stage by its reference."""

    scope: str
    subject: dict
    session: object
    began: datetime
    res: PlanResult
    compiled: dict = field(default_factory=dict)


def run(deps: Deps, branch: str = "", scope: str | None = None, probes_path: str | None = None) -> Document:
    """The flow's body. `scope` and `probes_path` are None when not given."""
    planned, refused = plan(deps, OP_STAGE_PLAN, branch, scope, probes_path, {}, printing=True)
    if refused is not None:
        return refused
    return planned.res.document(planned.scope)


def plan(deps: Deps, op: str, branch: str, scope: str | None, probes_path: str | None, subject: dict,
         printing: bool = False) -> tuple["Planned | None", Document | None]:
    """The proposed change's plan under op (`planStages`), or the document op ends with: the
    guards (--branch, its form), the scope, named in subject, then the session, then the open
    proposed change on the branch and each of its stages built, compiled and stepped from the
    one before. A plan refused before its proposed change was found is a Planned whose result
    names none. With `printing`, the heading and each stage are printed as `stage plan` prints
    them, each step before the stage it leads to."""
    if not branch:
        return None, error_document(op, None, "--branch is required")
    try:
        stages.check_branch(branch)
    except stages.RefError as e:
        return None, rule_error_document(op, None, stages.RULE_STAGE_REF_INVALID, branch, str(e), STEP_START)
    scope, refused = tool.scope_of(op, subject or None, scope, deps.env())
    if refused is not None:
        return None, refused
    subject = {**subject, "scope": scope}
    session, refused = deps.session(op, subject, scope, probes_path)
    if refused is not None:
        return None, refused

    began = deps.now()
    try:
        ch, found = session.find(branch)
    except ERRORS as e:
        return None, error_document(op, subject, str(e), STEP_RESOLVE, op)
    res = PlanResult(branch)
    planned = Planned(scope, subject, session, began, res)
    if ch is None:
        res.findings = Findings(found)
        return planned, None
    pc = ch.proposed_change
    res.proposed_change, res.destination = pc.block(), pc.destination
    labels = ch.labels()
    if printing:
        deps.out(stages_text.heading(res.proposed_change, len(labels), pc.destination, scope))

    before = None
    for i, label in enumerate(labels):
        ref = stages.Ref(branch, label)
        try:
            ps, compiled = plan_stage(deps, session, ch, ref, MOVED_ALWAYS if i == 0 else MOVED_NEVER)
        except CoreFailure as e:
            return None, core_failed(op, subject, e, res.findings)
        step = None
        if before is not None and compiled is not None:
            try:
                answer = deps.core.diff(before.file.path, compiled.file.path, [before.file, compiled.file])
            except CoreFailure as e:
                return None, core_failed(op, subject, e, res.findings + ps.findings)
            if answer.status != STATUS_OK:
                # Two bundles the compile just produced always step; one that does not is a
                # defect, not a finding (`pairOf`).
                why = "; ".join(f.message for f in answer.findings if f.severity == REJECTION) or answer.status
                return None, error_document(op, subject, f"the step {res.stages[-1].ref} → {ps.ref}: {why}",
                                            STEP_RESOLVE, op)
            step = step_of_diff(answer.blocks, before.manifest, compiled.manifest)
        pair = res.add(ps, step)
        if printing:
            if pair is not None:
                for line in pair.text().split("\n"):
                    deps.out(line)
            for line in ps.lines():
                deps.out(line)
        if compiled is not None:
            planned.compiled[ps.ref] = compiled
        before = compiled
    return planned, None


def plan_stage(deps: Deps, session, ch, ref: stages.Ref, moved: str) -> tuple[PlanStage, "_Compiled | None"]:
    """One stage as far as it goes (`build`): Infrahub's half through the session, then its
    snapshot filed and compiled by the core, its bundle's manifest kept for the step. Raises
    CoreFailure when the core cannot be asked."""
    built = session.build(ch, ref, moved)
    ps = PlanStage(ref=str(ref), label=ref.label, description=built.description, at_source=built.at_source,
                   observed_at=built.observed_at)
    if built.resolved is not None:
        ps.branch, ps.at = built.resolved.branch, built.resolved.at
    if built.status != BUILD_READ:
        return ps.stop(built.findings), None
    ps.findings.extend(built.findings)
    ps.packages = list(built.packages)
    counts = built.counts

    try:
        snapshot_id, file = file_snapshot(deps.store, built.snapshot)
    except FILING_ERRORS as e:
        ps.read = {**counts, "lossy_mappings": 0, "shared_ports": 0}
        failed = Findings()
        failed.add_step(REJECTION, STEP_COMPILE, RULE_OPERATION_FAILED, str(deps.store.snapshots),
                        f"filing the snapshot under {deps.store.snapshots}: {e}")
        return ps.stop(failed), None
    ps.snapshot_id = snapshot_id
    answer = deps.core.compile(file.path, [file])
    doc = answer.document
    compiled = Findings(doc.findings).at_step(STEP_COMPILE)
    manifest = next((f.data for f in answer.files if f.path == MANIFEST), None)
    if doc.status != STATUS_OK or manifest is None:
        ps.read = {**counts, "lossy_mappings": 0, "shared_ports": 0}
        if not compiled.rejected:
            compiled.add_step(REJECTION, STEP_COMPILE, RULE_OPERATION_FAILED, str(ref),
                              f"twin compile of snapshot {snapshot_id} answered no {MANIFEST}")
        return ps.stop(compiled), None
    lossy, shared = lossy_counts(manifest)
    ps.read = {**counts, "lossy_mappings": lossy, "shared_ports": shared}
    ps.findings.extend(compiled)
    ps.bundle_id = doc.blocks.get("bundle_id") or ""
    ps.status = PLAN_COMPILED
    return ps, _Compiled(file, manifest, snapshot_id, built.resolved)


@flow(name=FLOW, log_prints=False)
def stage_plan(branch: str = "", scope: str | None = None, probes_path: str | None = None) -> Document:
    """`fylgja-cli stage plan --branch <b>`."""
    return publish(FLOW, run(Deps.from_env(), branch, scope, probes_path))
