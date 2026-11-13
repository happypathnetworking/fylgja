"""The runner, `fylgja-orchestrator serve` (D-085): the two flows a check or a tag starts, `stage-plan` and
`twin-rehearse`, served to Prefect as `<flow>/main`, each by its module path (verified-facts.md, "Prefect 3.9.2").

It refuses to start, exit 2 in one line, where `PREFECT_API_URL` is unset, or a setting the flows read is unset or
refused by the clients' rules, or the source named is neither (`settings.refused`), so a runner never serves flows that
can only fail. A runner serves the one source its settings name, under the same two names whichever it is, so one
Prefect serves one source's runner (D-097). Then it says which deployments it serves and where, never
`PREFECT_API_AUTH_STRING`, and serves them until it is stopped, unpaused when it stops. With `flows`, the one module
that imports Prefect.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import cast

import prefect
from prefect.deployments.runner import RunnerDeployment
from prefect.types.entrypoint import EntrypointType

from fylgja_orchestrator.edge import flows, settings

API_URL = "PREFECT_API_URL"
"""Where Prefect's API is, which Prefect reads from the environment itself."""

EXIT_OK = 0
EXIT_FAILURE = 2


def main(environ: Mapping[str, str]) -> int:
    """Serve the two flows, under `environ`, until the runner is stopped; exit 2 where it cannot start."""
    address = environ.get(API_URL)
    if not address:
        print(f"{API_URL} is not set: make orchestrator-serve sets it", file=sys.stderr)
        return EXIT_FAILURE
    refused = settings.refused(environ)
    if refused:
        print("; ".join(refused), file=sys.stderr)
        return EXIT_FAILURE
    # Called outside an event loop, `to_deployment` answers the deployment itself, never a coroutine.
    deployments = [
        cast(RunnerDeployment, each.to_deployment(name=flows.DEPLOYMENT, entrypoint_type=EntrypointType.MODULE_PATH))
        for each in (flows.stage_plan, flows.twin_rehearse)
    ]
    served = ", ".join(f"{each.flow_name}/{each.name}" for each in deployments)
    print(f"fylgja-orchestrator: serving {served} at {address}", flush=True)
    prefect.serve(*deployments, pause_on_shutdown=False, print_starting_message=False)
    return EXIT_OK
