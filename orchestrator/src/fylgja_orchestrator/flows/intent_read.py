"""The flow `intent-read` (data-model §7, R-08; FR-018): a branch, pinned or not, or a stage,
read through the adapter under a scope with the request's probes, taken as a snapshot `2`
and written to `out`, as `fylgja intent read` wrote it; then filed under the orchestrator's
`snapshots/`, as the core's server filed it in its store, and named in the summary line.

The summary line is the adapter's (research §5.13) with the store's path added: it names no
lossy mappings or shared ports, which are the compiler's survey, and a read compiles
nothing (research §5.17).
"""

from prefect import flow

from ..documents.findings import OP_INTENT_READ, Document
from .common import FILING_ERRORS, Deps, filing_failed, publish

FLOW = "intent-read"


def run(deps: Deps, branch: str = "", at: str = "", stage: str | None = None, scope: str | None = None,
        probes_path: str | None = None, out: str = "") -> Document:
    """The flow's body: the adapter's read, the snapshot filed, the lines printed, the
    document returned. `stage`, `scope` and `probes_path` are None when not given."""
    answer = deps.read(branch, at, stage, scope, probes_path, out, deps.env())
    doc, notes = answer.doc, list(answer.notes)
    if answer.snapshot is not None:
        try:
            snapshot_id, _ = deps.store.put(answer.snapshot)
        except FILING_ERRORS as e:
            failed = filing_failed(OP_INTENT_READ, doc.subject or {}, deps.store, e)
            if "stage" in doc.blocks:
                failed.set("stage", doc.blocks["stage"])
            doc, notes = failed, notes[:-1]
        else:
            notes[-1] += f", stored at {deps.store.path(snapshot_id)}"
    for line in notes:
        deps.out(line)
    return doc


@flow(name=FLOW, log_prints=False)
def intent_read(branch: str = "", at: str = "", stage: str | None = None, scope: str | None = None,
                probes_path: str | None = None, out: str = "") -> Document:
    """`fylgja-cli intent read`: a branch or a stage read to a snapshot file."""
    return publish(FLOW, run(Deps.from_env(), branch, at, stage, scope, probes_path, out))
