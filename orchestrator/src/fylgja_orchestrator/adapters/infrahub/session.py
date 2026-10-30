"""The adapter as the flows read through it (T025): one command's packages, Infrahub's
credentials, the request's one probe list and its scope, opened once, and what a flow reads
under them: a proposed change found by its source branch, a stage built as far as Infrahub
takes it, and a branch read.

A stage's build is the Infrahub half of `internal/stages/plan.go`'s `build`: resolved (steps
4–9, stage.main.moved as the caller asks), then read at its at and taken as a snapshot `2`
with the request's probes, each finding at its step, the first rejection ending it. The
other half, the compile, the filing and the step between two stages, is the core's, which
the flow asks through the API. `stage plan`, `twin create --stage` and `twin step` build
every stage through it, so a stage's snapshot is the same whichever flow took it (D-011).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...documents.findings import (
    REJECTION,
    RULE_OPERATION_FAILED,
    STEP_READ,
    STEP_RESOLVE,
    Document,
    Findings,
    error_document,
    new_document,
)
from . import packages, probes, stages
from . import read as reading
from . import stage_reader as sr
from .client import Client, ClientError, Config, ConfigError, DefaultClient, env_credentials

ERRORS = (reading.ReadError, stages.StagesError, ClientError)
"""What a read through the session raises when Infrahub cannot be read, for the flow to
report as operation.failed."""

# When a build files step 9's warning, stage.main.moved (`movedWhen`).
MOVED_NEVER = "never"
"""A plan's stages after the first, the warning being the branch point's."""
MOVED_RESOLVED = "resolved"
"""A create's or a step's stage, as a resolution files it, the first refusal ending it before
step 9."""
MOVED_ALWAYS = "always"
"""A plan's branch point, refused or not."""

BUILD_READ = "read"
"""A build that read its stage and took the snapshot: what follows is the core's."""
BUILD_REFUSED = "refused"
"""A build refused at resolution or read, under a rule of its own."""
BUILD_FAILED = "failed"
"""A build whose resolution or read could not run (operation.failed)."""


@dataclass
class Built:
    """One stage as far as Infrahub takes it (`stages.PlanStage`'s first half): its reference,
    label, description and at's source in every case; its resolution once it resolved; its
    snapshot, when its read began and its devices by package once it read clean; its
    findings, each at its step; and how far it got, with the first rejection's rule when it
    stopped."""

    ref: stages.Ref
    label: str
    description: str = ""
    at_source: str = ""
    resolved: stages.Resolved | None = None
    snapshot: dict | None = None
    observed_at: str = ""
    packages: list = field(default_factory=list)
    findings: Findings = field(default_factory=Findings)
    status: str = ""
    rule: str = ""

    def stop(self, found) -> "Built":
        """Ends the build with found: refused under the first rejection's rule, failed when
        that rule is operation.failed."""
        self.findings.extend(found)
        self.status = BUILD_REFUSED
        for f in self.findings:
            if f.severity == REJECTION:
                self.rule = f.rule
                if f.rule == RULE_OPERATION_FAILED:
                    self.status = BUILD_FAILED
                break
        return self

    def failed(self, step: str, e: Exception) -> "Built":
        found = Findings()
        found.add_step(REJECTION, step, RULE_OPERATION_FAILED, str(self.ref), str(e))
        return self.stop(found)

    @property
    def counts(self) -> dict:
        """What the read holds, as a plan's block counts it before the compile's survey."""
        n = reading.summarize(self.snapshot["ctm"] if self.snapshot else None)
        return {"devices": n.devices, "interfaces": n.interfaces, "links": n.links, "artifacts": n.artifacts}


class Session:
    """One command's reads of Infrahub, opened by `open`: the packages, the scope, the
    default branch's stage reader and the stamper, the request's probe list, and the client
    every branch read is made through (`default`)."""

    def __init__(self, registry, scope: str, reader, stamper, declared: list, default: DefaultClient | None = None):
        self.registry = registry
        self.scope = scope
        self.reader = reader
        self.stamper = stamper
        self.probes = declared
        self.default = default

    @classmethod
    def open(cls, op: str, subject: dict | None, scope: str, probes_path: str | None,
             environ: dict, requester=None) -> tuple["Session | None", Document | None]:
        """The session of a command under scope, already held to its rules, or the document
        the command ends with: the packages first, a package `psp validate` refuses filed with
        its own findings at read and anything else operation.failed there (`loadFailureAt`);
        the credentials, unset ones operation.failed at resolve; then the request's one probe
        list, the file's at start or the kind's at resolve (`readProbes`)."""
        try:
            registry = packages.load(override_dir=environ.get(packages.ENV_OVERRIDE, ""))
        except packages.PackageError as e:
            if e.findings:
                return None, new_document(op, subject, Findings(e.findings).at_step(STEP_READ))
            return None, error_document(op, subject, str(e), STEP_READ, STEP_READ)
        try:
            address, token = env_credentials(environ)
        except ConfigError as e:
            return None, error_document(op, subject, str(e), STEP_RESOLVE, op)
        default = DefaultClient(address, token, requester)
        try:
            declared, found = probes.declared(probes_path, default)
        except probes.ProbesError as e:
            return None, error_document(op, subject, str(e), e.step, e.object)
        if declared is None:
            return None, new_document(op, subject, found)
        return cls(registry, scope, sr.StageReader(default), stages.stamper_of(default), declared, default), None

    def find(self, branch: str) -> tuple[stages.Change | None, Findings]:
        """The open proposed change whose source branch is branch (steps 1–3 and the head's
        at), or its refusal at resolve. Raises one of ERRORS when Infrahub cannot be read."""
        return stages.find(self.reader, self.stamper, branch, self.scope)

    def stage_list(self, branch: str) -> tuple[stages.ListResult, Findings]:
        """The open proposed change's stages on branch as `stage list` lists them, under the
        session's scope, no record marked. Raises one of ERRORS when Infrahub cannot be read."""
        return stages.list_stages(self.reader, self.stamper, branch, self.scope)

    def take(self, branch: str, at: str, scope: str, observed_at: str | None = None) -> tuple[dict | None, Findings]:
        """A branch read at at, unpinned when it is "", under scope, and taken as a snapshot
        `2` with the request's probes (`stage.Read` then the take); None when the read
        refused. Raises one of ERRORS when Infrahub cannot be read."""
        c = self.default.config
        client = Client(Config(address=c.address, token=c.token, branch=branch, at=at), self.default._requester)
        return reading.read_snapshot(client, scope, self.registry, self.probes, observed_at)

    def read(self, branch: str, at: str = "") -> tuple[dict | None, Findings]:
        """A branch read under the session's scope and taken, each finding at read
        (`readTakeCompile`'s read and take); None when the read refused."""
        taken, found = self.take(branch, at, self.scope)
        return taken, Findings(found).at_step(STEP_READ)

    def build(self, ch: stages.Change, ref: stages.Ref, moved: str = MOVED_RESOLVED, now: datetime | None = None,
              on_resolved: Callable[[stages.Resolved], None] | None = None) -> Built:
        """One stage of a proposed change already found, as far as Infrahub takes it: resolved
        (steps 4–9) with stage.main.moved as moved says, `on_resolved` told once it resolved;
        then read with an observed_at of its own and taken. A read or a resolution that
        cannot run stops it failed at its step, never raising. `now` is the clock for the
        future rule alone."""
        b = Built(ref, ref.label)
        st = ch.first(ref.label)
        if st is not None:
            b.description, b.at_source = st.resolved.description, st.at_source
        try:
            resolved, found = stages._resolve(self.reader, self.stamper, self.registry, ch, ref,
                                              now or datetime.now(UTC))
            if moved == MOVED_ALWAYS or (moved == MOVED_RESOLVED and not found.rejected):
                found = Findings(found)
                found.extend(stages._unfiled(ch.main_moved(self.stamper), found))
        except ERRORS as e:
            return b.failed(STEP_RESOLVE, e)
        found = Findings(found).at_step(STEP_RESOLVE)
        if found.rejected:
            return b.stop(found)
        b.findings.extend(found)
        b.resolved = resolved
        if on_resolved is not None:
            on_resolved(resolved)

        # Captured before the read's first request, so observed_at is never later than
        # anything the read could have seen.
        b.observed_at = reading.observed_now()
        try:
            taken, found = self.take(resolved.branch, resolved.at, ch.scope, b.observed_at)
        except ERRORS as e:
            return b.failed(STEP_READ, e)
        found = Findings(found).at_step(STEP_READ)
        if taken is None:
            return b.stop(found)
        b.findings.extend(found)
        b.snapshot = taken
        b.packages = reading.devices_by_package(taken["ctm"])
        b.status = BUILD_READ
        return b
