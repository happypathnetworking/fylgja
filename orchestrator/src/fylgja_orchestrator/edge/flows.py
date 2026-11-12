"""The two Prefect flows a check starts (D-085), `stage-plan` and `twin-rehearse`, each `(branch: str)` and each a thin
wrap of `run`: it adds the run's id, the run's logger for the library's progress, and the document's artifact.

A flow reads its settings from the process's environment, opens the source and the core, and calls `run` once; the
document it is handed is filed as one artifact of type `ARTIFACT_TYPE`, keyed `fylgja-<flow>-<flow run id>`, which a
check reads back by the run's id, and returned, whatever its status: nothing is retried (D-086).

A cancel, or the flow's time limit, gives the body a `BaseException`: Prefect 3.9.2's `TerminationSignal` or its
`CancelledError` (verified-facts.md, "Prefect 3.9.2"). Inside `rehearse` it reaches the library, whose own handler asks
the twin's deletion, the one request that also cancels the run in flight, and raises it again. That clean-up has about
30 s, after which Prefect kills the flow's process; an `except` block's two requests and a `finally`'s artifact were
read to arrive within it after both a cancel and a time limit. So the flow's `finally` files the document only where
it was handed one, and adds no request, no wait and no following of its own: `rehearse` hands none on that path, so
none is filed, and the check concludes from the run's state, stopped (D-085). Then it closes the source and the core,
which asks nothing of either, whether or not the filing was made or raised.

The rehearsal's limit is `Limits().limit_s`, and the flow's own is 300 s above it, for the library's end after its
limit fires (its cancel, its deletion and its post), so that the library's limit fires first.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from fylgja_core.client import Client
from prefect import flow
from prefect.artifacts import Artifact
from prefect.context import FlowRunContext
from prefect.logging.loggers import flow_run_logger

from fylgja_orchestrator.edge import run, settings

ARTIFACT_TYPE = "fylgja-document"
"""The type of the artifact a flow files its document as."""

STAGE_PLAN = "stage-plan"
TWIN_REHEARSE = "twin-rehearse"
DEPLOYMENT = "main"
"""The name each flow is served under: `<flow>/main`."""

PLAN_TIMEOUT_S = 600
REHEARSE_TIMEOUT_S = 3900
"""`Limits().limit_s`, 3600 s, and 300 s for the library's own end after its limit."""


def key(flow: str, run_id: str) -> str:
    """The key of the document the run `run_id` of `flow` files."""
    return f"fylgja-{flow}-{run_id}"


def filed(flow: str, run_id: str, document: Mapping[str, Any]) -> None:
    """`document` filed as the one artifact of the run `run_id` of `flow`."""
    Artifact(type=ARTIFACT_TYPE, key=key(flow, run_id), data=dict(document)).create()


def _in_run() -> tuple[str, Callable[[str], None]]:
    """The flow run in progress: its id, and a line said on its logger."""
    context = FlowRunContext.get()
    if context is None or context.flow_run is None:
        raise RuntimeError("the edge's flows run as Prefect flow runs, and none is in progress")
    logger = flow_run_logger(flow_run=context.flow_run, flow=context.flow)
    return str(context.flow_run.id), logger.info


def _ended(flow: str, run_id: str, document: Mapping[str, Any] | None, source: run.EdgeSource, core: Client) -> None:
    """A flow's end, whatever ended it: `document` filed where the flow was handed one, then the source and the core
    closed, each whatever the step before it raised."""
    try:
        if document is not None:
            filed(flow, run_id, document)
    finally:
        try:
            source.close()
        finally:
            core.close()


@flow(name=STAGE_PLAN, timeout_seconds=PLAN_TIMEOUT_S)
def stage_plan(branch: str) -> dict[str, Any]:
    """The plan of the proposed change whose source branch is `branch`: its plan 1 document, filed and returned."""
    config = settings.from_env(os.environ)
    run_id, progress = _in_run()
    source, core = run.opened(config)
    document: dict[str, Any] | None = None
    try:
        document = run.plan(branch, config.scope, source=source, core=core, progress=progress)
        return document
    finally:
        _ended(STAGE_PLAN, run_id, document, source, core)


@flow(name=TWIN_REHEARSE, timeout_seconds=REHEARSE_TIMEOUT_S)
def twin_rehearse(branch: str) -> dict[str, Any]:
    """The rehearsal of the proposed change whose source branch is `branch`, on the twin the run's id names: its
    rehearsal 1 document, filed and returned. A draft is refused (`run.DraftRefused`), and nothing filed."""
    config = settings.from_env(os.environ)
    run_id, progress = _in_run()
    source, core = run.opened(config)
    document: dict[str, Any] | None = None
    try:
        document = run.rehearse(branch, config.scope, source=source, core=core, run_id=run_id, progress=progress)
        return document
    finally:
        _ended(TWIN_REHEARSE, run_id, document, source, core)
