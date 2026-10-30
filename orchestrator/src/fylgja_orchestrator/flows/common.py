"""What the flows share (data-model §7, R-08): what a flow's body reads through (`Deps`: the
core, the store, the adapter), where its out lines go, the document a run of the core ends
with as the flow's own, and the artifact every flow ends by writing.

Each flow is a body, a plain function of its parameters and a `Deps`, which the tests call
with the adapter and the core stubbed, and a `@flow` of the same parameters in its module,
which builds the `Deps` from the process's environment, runs the body and writes the
artifact. Prefect is imported by the flows' modules alone, and here only inside the
functions that ask it for the current run, so `fylgja_orchestrator.flows` imports none.
"""

import contextvars
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..adapters.infrahub import __main__ as tool
from ..adapters.infrahub import comment
from ..adapters.infrahub import snapshot as snapshots
from ..adapters.infrahub.session import Session
from ..core import Answer, Core, CoreFailure, File
from ..documents.deadline import load_budgets
from ..documents.findings import Document, Findings, error_document
from ..record import ChangeRef, RecordError, StageRef, Store, new_record, read_flow_run, shown_snapshot

ARTIFACT_TYPE = "fylgja-findings"
"""The type of the artifact every flow's run carries its document under (research §1.4)."""

RULE_RUN_DETACHED = "run.detached"


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


OUT: contextvars.ContextVar[Callable[[str], None]] = contextvars.ContextVar("fylgja_out", default=_print)
"""Where a flow's out lines go when it runs as a flow: stdout by default, `fylgja-cli`'s
own when it sets one (T027)."""


def out_line(line: str) -> None:
    """One out line: to the sink, and to the run's log when a run is current, so the
    platform's view of a runner's run shows what a hand command prints."""
    OUT.get()(line)
    logger = _run_logger()
    if logger is not None:
        logger.info(line)


@dataclass
class Deps:
    """What a flow's body reads through: the core's client, the orchestrator's store, the
    adapter's environment and how it opens a session, its three commands, the out sink, the
    run's id ("" when the body runs with no run) and the clock; and the rehearsal's: a flow
    run's state on the platform, the report's post on its proposed change, the packages'
    budgets and the monotonic clock its deadline is kept on. Tests replace any of them."""

    core: Core
    store: Store
    environ: dict = field(default_factory=lambda: dict(os.environ))
    out: Callable[[str], None] = out_line
    open: Callable = Session.open
    read: Callable = tool.read
    schema_check: Callable = tool.schema_check
    flow_run_id: str = ""
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    flow_run: Callable = read_flow_run
    post: Callable = comment.post
    budgets: Callable = load_budgets
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def from_env(cls) -> "Deps":
        environ = dict(os.environ)
        return cls(Core(environ), Store.from_env(environ), environ, flow_run_id=flow_run_id())

    def env(self) -> tool.Env:
        """The adapter's environment for one of its commands: no start-up line, which is the
        tool's on stderr, not a flow's."""
        return tool.Env(environ=self.environ)

    def session(self, op: str, subject: dict | None, scope: str, probes_path: str | None):
        return self.open(op, subject, scope, probes_path, self.environ)


# The run.


def _flow_run():
    try:
        from prefect.context import FlowRunContext
    except ImportError:  # pragma: no cover - Prefect is the project's dependency
        return None
    ctx = FlowRunContext.get()
    return ctx.flow_run if ctx is not None else None


def flow_run_id() -> str:
    """The current flow run's id, "" when the body runs with no run (a test, or `fylgja-cli`
    with no platform)."""
    run = _flow_run()
    return str(run.id) if run is not None else ""


def _run_logger():
    if _flow_run() is None:
        return None
    from prefect import get_run_logger

    return get_run_logger()


def artifact_key(flow: str, run_id: str) -> str:
    """The key the document is filed under on the platform: fylgja-<flow>-<run id>."""
    return f"fylgja-{flow}-{run_id}"


def publish(flow: str, doc: Document) -> Document:
    """Writes the document as the current run's artifact `fylgja-findings`, its `data` the
    JSON a check reads (research §1.4), and returns it. With no run there is nothing to file
    it under, and it is returned alone."""
    run = _flow_run()
    if run is None:
        return doc
    from prefect.artifacts import Artifact

    Artifact(type=ARTIFACT_TYPE, key=artifact_key(flow, str(run.id)), data=doc.to_dict(),
             description=f"the findings document of {flow}").create()
    return doc


# The core's answers as the flow's document.


def without_repeats(run: Findings, reported: Findings) -> Findings:
    """The run's findings without those the command already reported, by step, rule, object
    and message (`withoutRepeats`): the run checks the host and the plan again as second
    locks."""
    key = lambda f: (f.step, f.rule, f.object, f.message)  # noqa: E731
    seen = {key(f) for f in reported}
    return Findings(f for f in run if key(f) not in seen)


def composed(op: str, subject: dict, found: Findings, answer: Answer, started: Answer | None = None,
             blocks: dict | None = None) -> Document:
    """The flow's document of a core operation, as the core's CLI printed it when the core
    read the source: operation op and the flow's subject, the run's id added once the run
    has one; the status the core's last answer gives; its findings after found, what the
    flow found before it asked, with a detached start's own (its run.detached left out) and
    the run's without the start's repeats; the start's blocks, then the run's over them,
    then the flow's own over both."""
    last = answer.document
    first = started.document if started is not None else None
    findings = Findings(found)
    doc_blocks: dict = {}
    if first is not None:
        findings.extend(f for f in first.findings if f.rule != RULE_RUN_DETACHED)
        doc_blocks.update({k: v for k, v in first.blocks.items() if v not in (None, "")})
    findings.extend(without_repeats(last.findings, findings))
    doc_blocks.update({k: v for k, v in last.blocks.items() if v not in (None, "")})
    doc_blocks.update(blocks or {})
    subject = dict(subject)
    run = answer.run or (started.run if started is not None else None)
    run_id = (run.run_id if run is not None else "") or (last.subject or {}).get("run_id", "")
    if run_id:
        subject["run_id"] = run_id
    return Document(op, last.status, subject, findings, doc_blocks)


def run_core(core: Core, op: str, args: dict, files, out: Callable[[str], None], dry_run: bool
             ) -> tuple[Answer, Answer | None]:
    """A run of the core's operation op (twin.create, twin.step): its dry run, which starts
    nothing and is never detached, or the run started detached and read every two seconds to
    its document (R-08), the out lines reaching out as they arrive. Returns the last answer
    and the start's, None for a dry run or a start the core refused."""
    if dry_run:
        return core.dry_run(op, args, files, on_out=out), None
    started = core.start(op, args, files, on_out=out)
    if started.run is None or not started.run.run_id:
        return started, None
    return core.read(started.run.workflow_id, started.run.run_id, on_out=out), started


def file_snapshot(store: Store, snapshot: dict) -> tuple[str, File]:
    """Files a snapshot the flow took under the orchestrator's store, once, and returns its
    id and the file the core is sent: the entry's bytes under the entry's path."""
    snapshot_id, _ = store.put(snapshot)
    path = store.path(snapshot_id)
    return snapshot_id, File(str(path), path.read_bytes())


FILING_ERRORS = (RecordError, snapshots.SnapshotError, OSError)


def filing_failed(op: str, subject: dict, store: Store, e: Exception, found: Findings | None = None,
                  step: str = "") -> Document:
    """A snapshot the store could not file: operation.failed naming the store, after what was
    found before it."""
    doc = error_document(op, subject, f"filing the snapshot under {store.snapshots}: {e}", step, str(store.snapshots))
    if found:
        doc.findings[:0] = list(found)
    return doc


def core_failed(op: str, subject: dict, e: CoreFailure, found: Findings | None = None) -> Document:
    """A failure between the flow and the core, as the command's own document, after what was
    found before it."""
    doc = e.document(op, subject)
    if found:
        doc.findings[:0] = list(found)
    return doc


def follow_record(deps: Deps, flow: str, snapshot_id: str, resolved) -> None:
    """The record after a create's or a step's run, following the twin as `twin show` names
    it once the run has ended: written, naming the stage resolved, its proposed change, the
    snapshot and this flow's run, when the twin stands at the snapshot sent; removed when it
    does and the create was from a branch (`resolved` None), since that twin names no stage;
    left as it was otherwise, or when the core cannot be asked."""
    try:
        if shown_snapshot(deps.core.show()) != snapshot_id:
            return
    except CoreFailure:
        return
    if resolved is None:
        deps.store.clear_record()
        return
    pc = resolved.proposed_change
    deps.store.write_record(new_record(StageRef(resolved.branch, resolved.label, resolved.at),
                                       ChangeRef(pc.id, pc.branch), snapshot_id, deps.flow_run_id, flow))
