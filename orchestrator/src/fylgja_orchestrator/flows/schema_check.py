"""The flow `schema-check` (data-model §7, R-08; FR-018): a branch's schema against the
mapping's table, and the stage kind on the default branch beside it, passed through to the
adapter's `schema-check` as `fylgja schema check` ran it."""

from prefect import flow

from ..documents.findings import Document
from .common import Deps, publish

FLOW = "schema-check"


def run(deps: Deps, branch: str = "") -> Document:
    """The flow's body: the adapter's check, its lines printed, its document returned."""
    answer = deps.schema_check(branch, deps.env())
    for line in answer.notes:
        deps.out(line)
    return answer.doc


@flow(name=FLOW, log_prints=False)
def schema_check(branch: str = "") -> Document:
    """`fylgja-cli schema check`."""
    return publish(FLOW, run(Deps.from_env(), branch))
