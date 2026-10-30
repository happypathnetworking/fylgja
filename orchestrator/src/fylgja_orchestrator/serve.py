"""`fylgja-orchestrator serve`, the runner (research R-01, R-08): the six flows, each as its
deployment `main`, served by one process on the platform PREFECT_API_URL names, which the
checks start runs of (`GET /api/deployments/name/<flow>/main`, then `create_flow_run`).

The platform must answer this process's credential first (`platform.unreachable`'s words,
exit 2); with no PREFECT_API_URL there is nothing to serve, since a runner on an ephemeral
server would serve no one else. Its start-up line names the platform's address and the six
deployments, never PREFECT_API_AUTH_STRING. Prefect's own starting table is not printed.
"""

import argparse
import os
import sys
from collections.abc import Callable, Mapping

from .core import CoreFailure
from .record import ENV_PLATFORM, check_platform, platform_of

PROG = "fylgja-orchestrator"
DEPLOYMENT = "main"


def flows() -> list:
    """The six flows, in data-model §7's order."""
    from .flows.intent_read import intent_read
    from .flows.schema_check import schema_check
    from .flows.stage_plan import stage_plan
    from .flows.twin_create import twin_create
    from .flows.twin_rehearse import twin_rehearse
    from .flows.twin_step import twin_step

    return [intent_read, twin_create, twin_step, stage_plan, twin_rehearse, schema_check]


def deployments(served: list) -> list:
    """Each flow as its deployment `main`, which the runner serves, its entrypoint the flow's
    module path: the runner loads a run's flow by its entrypoint, and a file path is loaded as
    a script, outside the package its relative imports need."""
    from prefect.types.entrypoint import EntrypointType

    return [f.to_deployment(name=DEPLOYMENT, entrypoint_type=EntrypointType.MODULE_PATH) for f in served]


def startup_line(base: str, served: list) -> str:
    names = ", ".join(f"{f.name}/{DEPLOYMENT}" for f in served)
    return f"{PROG}: serving {names} on the platform at {base}"


def _prefect_serve(*deps) -> None:
    """Prefect's `serve`, its starting table not printed and the deployments not paused on
    shutdown: they carry no schedule, and a pause is one more request to a platform that may
    be gone, which held a runner stopped after its platform."""
    from prefect import serve

    serve(*deps, print_starting_message=False, pause_on_shutdown=False)


def main(argv=None, stdout=None, stderr=None, environ: Mapping[str, str] | None = None,
         serve: Callable | None = None, served: list | None = None) -> int:
    """Runs `serve` until the runner stops, and returns the exit code: 2 for a command line
    refused, a platform unset or one that does not answer; else 0."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    environ = os.environ if environ is None else environ
    p = argparse.ArgumentParser(prog=PROG, description="The orchestrator's runner: serve the six flows' deployments "
                                                       "on the platform PREFECT_API_URL names")
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")
    sub.add_parser("serve", help="serve each flow's deployment main until interrupted")
    try:
        p.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    base, _ = platform_of(environ)
    if not base:
        stderr.write(f"{PROG}: {ENV_PLATFORM} is not set: the runner serves the orchestrator's platform, which make "
                     "prefect-server starts\n")
        return 2
    try:
        check_platform(environ)
    except CoreFailure as e:
        stderr.write(f"{PROG}: {e.message}\n")
        return 2
    served = flows() if served is None else served
    deps = deployments(served)
    stdout.write(startup_line(base, served) + "\n")
    stdout.flush()
    (serve or _prefect_serve)(*deps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
