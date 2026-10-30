"""`fylgja-cli stage list` (FR-020, FR-021; R-09): the adapter's listing with the twin's row
read from the orchestrator's record. No flow: R-08 names six, and a listing starts nothing
and keeps nothing, so it runs as a plain body and is recorded on no platform.

The guards first (--branch's form, the scope), as `stage list` refused them before anything
was dialled; then the record, and only when there is one, `twin show`: trusted, the
record's stage is passed to the listing, which marks its row and judges `stage.twin.moved`;
distrusted, the listing marks no row and `record.twin.stale` (info) says why. Then the
adapter's listing, its lines printed.
"""

from ..adapters.infrahub import __main__ as tool
from ..adapters.infrahub import stages
from ..core import CoreFailure
from ..documents.findings import OP_STAGE_LIST, STEP_START, Document, error_document, rule_error_document
from ..record import RecordError, stale, trusted, view
from .common import Deps, core_failed


def run(deps: Deps, branch: str | None = None, scope: str | None = None) -> Document:
    """The body. `branch` and `scope` are None when not given."""
    op = OP_STAGE_LIST
    if branch is not None:
        try:
            stages.check_branch(branch)
        except stages.RefError as e:
            return rule_error_document(op, None, stages.RULE_STAGE_REF_INVALID, branch, str(e), STEP_START)
    scope, refused = tool.scope_of(op, None, scope, deps.env())
    if refused is not None:
        return refused

    try:
        record = deps.store.read_record()
    except RecordError as e:
        return error_document(op, {"scope": scope}, str(e), STEP_START, str(deps.store.record_path))
    held = distrust = None
    if record is not None:
        try:
            show = deps.core.show()
        except CoreFailure as e:
            return core_failed(op, {"scope": scope}, e)
        if trusted(record, show):
            held = view(record, show)
        else:
            distrust = stale(deps.store, record, show)

    answer = deps.stage_list(branch, scope, deps.env(), held)
    doc = answer.doc
    if distrust is not None and "stages" in doc.blocks:
        doc.findings.insert(0, distrust)
    for line in answer.notes:
        deps.out(line)
    return doc
