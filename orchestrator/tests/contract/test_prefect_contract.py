"""The two deployments on a real Prefect, started, waited for, cancelled and read as a check does (D-085, D-034).

A module fixture serves the core on plan 4's fake runtime in this process (`harness.serving`), and starts, each in a
session of its own under a directory of the module's and each ended by its pid at the module's end, a Prefect server
on a free loopback port, never 4200, with a basic auth made here and its analytics off, and the runner,
`fylgja-orchestrator serve`, given that server, the core and the example's account's token. Before any test it makes
the module's proposed change on the seed's branch, waits for its artifact validation to complete, and reads its plan
once through the library, so that a rehearsal reaches its twin's apply within the cancel test's deadline (P5-24,
P5-57).

The tests drive the checks' glue, loaded by its path as the task worker loads it, with an `ask` that sends the glue's
query to Infrahub over httpx, as a check's own client does: the glue runs here, not on a task worker, and no test
reaches Prefect from one (P5-8); plan 6's acceptance run is the first that does.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fylgja_core.client import base_url, trust
from fylgja_infrahub import ReaderDocument
from harness import ALICE, Served, serving

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.infrahub import InfrahubSource
from fylgja_orchestrator.rehearsal import Change, twin_name
from fylgja_orchestrator.rehearsal.documents import validate

from .conftest import (
    ADDRESS,
    CA,
    READER_DOCUMENT,
    ROOT,
    TIMEOUT,
    TOKEN,
    WRITE_TOKEN,
    Proposal,
    Proposals,
    Secret,
    Writer,
    ca,
    hide,
    secret,
)

GLUE_PATH = ROOT / "infrahub" / "checks" / "fylgja_glue.py"
BIN = Path(sys.executable).parent
"""The venv running the tests, whose `prefect` and `fylgja-orchestrator` are run."""

UP_S = 90.0
"""How long the server is given to answer `/api/health`, and the runner to serve both deployments."""
END_S = 30.0
"""How long a process is given to exit after SIGTERM before its session is killed."""
CANCELLED_S = 45.0
"""The bound from the cancel to the run read `CANCELLED`."""
GONE_S = 30.0
"""The bound from `CANCELLED` to the core listing the rehearsal's twin gone or its deletion asked."""
CANCEL_TIMEOUT_S = 660
"""The cancel test's check `timeout`: its deadline 420 s after it begins (the 240 s `fylgja_glue.DEADLINE_MARGIN_S`
less), its close at 540 s. A rehearsal's four stage reads were read to take about 70 s before its twin's create, past a
deadline of 60 s (P5-57). At plan 6's closing gate the plan read once in 187.3 s and `fylgja-step` concluded in 206.5 s,
and at the deadline of 180 s the rehearsal had made no driver call; in the run that passed at this `timeout` the plan
read in 211.6 s and `fylgja-step` concluded in 236.7 s. 420 s is 1.77 times the slowest of these, 236.7 s (a
derivation)."""

USER = "fylgja"
MESSAGES: list[str] = []
"""Every `Outcome.message` the module's checks concluded, searched for the secrets last."""

Ask = Callable[[str, Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fylgja_glue_contract", GLUE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass resolves its module's annotations through sys.modules
    spec.loader.exec_module(module)
    return module


glue = _load()


@dataclass
class Edge:
    """What the module's tests drive and read: the core served, the Prefect server at `address` and a client of its
    API, the glue's two variables, the check's `ask`, the module's proposed change, the secrets the runner holds, and
    the two processes' output files."""

    served: Served
    address: str
    api: httpx.Client
    environ: dict[str, str] = field(repr=False)
    ask: Ask
    proposal: Proposal
    branch: str
    secrets: dict[str, str] = field(repr=False)
    outputs: tuple[Path, ...]


def free_port() -> int:
    """A loopback port nothing listens on now, never 4200."""
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        if port != 4200:
            return port


def start(argv: list[str], env: Mapping[str, str], output: Path) -> subprocess.Popen[bytes]:
    """`argv` in a session of its own, under `env` alone, its output into `output`."""
    with output.open("ab") as out:
        return subprocess.Popen(argv, env=dict(env), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)


def end(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM to the session `process` leads, by its pid, and SIGKILL to it where anything of it is left `END_S` on."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + END_S
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def waited(what: str, ready: Callable[[], bool], process: subprocess.Popen[bytes], output: Path) -> float:
    """The seconds until `ready()`, within `UP_S`, while `process` runs."""
    began = time.monotonic()
    while not ready():
        assert process.poll() is None, f"{what}: its process exited {process.returncode}; read {output}"
        assert time.monotonic() - began < UP_S, f"{what} not within {UP_S:g} s; read {output}"
        time.sleep(0.5)
    return time.monotonic() - began


def answers(api: httpx.Client, path: str) -> bool:
    try:
        return api.get(path).status_code == 200
    except httpx.HTTPError:
        return False


def asker(address: str, token: Secret) -> Ask:
    """The check's own client of Infrahub, as `self.client.execute_graphql(..., branch_name="main")`: the query on
    `main`, answered by its `data`, and an error where Infrahub answers any."""

    async def ask(query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        async with httpx.AsyncClient(base_url=base_url(address), headers={"X-INFRAHUB-KEY": token.value},
                                     timeout=TIMEOUT, verify=trust(ca()), trust_env=False) as client:
            response = await client.post("/graphql/main", json={"query": query, "variables": dict(variables)})
        answer = response.json()
        if response.status_code != 200 or answer.get("errors"):
            raise RuntimeError(f"Infrahub answered HTTP {response.status_code} with errors")
        data: Mapping[str, Any] = answer["data"]
        return data

    return ask


@pytest.fixture(scope="module")
def edge(
    tmp_path_factory: pytest.TempPathFactory,
    proposals: Proposals,
    writer: Writer,
    document: ReaderDocument,
    example_token: Secret,
    seed: dict[str, Any],
) -> Iterator[Edge]:
    root = tmp_path_factory.mktemp("edge")
    home, records = root / "prefect", root / "records"
    home.mkdir(mode=0o700)
    records.mkdir()
    server_output, runner_output = root / "server.out", root / "runner.out"
    port = free_port()
    address = f"127.0.0.1:{port}"
    auth = hide(Secret("the tests' Prefect auth", f"{USER}:{secrets.token_urlsafe(24)}"))
    hide(Secret("the tests' Prefect password", auth.value.partition(":")[2]))
    reader, writer_token = secret(TOKEN), secret(WRITE_TOKEN)
    quiet = {"DO_NOT_TRACK": "1", "PREFECT_SERVER_ANALYTICS_ENABLED": "false", "PREFECT_HOME": str(home)}
    base = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    proposal = proposals.make(draft=False)
    with contextlib.ExitStack() as stack:
        served = stack.enter_context(serving(root / "core"))
        server = start([str(BIN / "prefect"), "server", "start", "--host", "127.0.0.1", "--port", str(port), "--no-ui"],
                       base | quiet | {"PREFECT_SERVER_API_AUTH_STRING": auth.value}, server_output)
        stack.callback(end, server)
        basic = httpx.BasicAuth(*auth.value.split(":"))
        api = stack.enter_context(httpx.Client(base_url=f"http://{address}/api", auth=basic, timeout=TIMEOUT,
                                               trust_env=False))
        up = waited("the Prefect server's /api/health", lambda: answers(api, "/health"), server, server_output)
        runner_env = base | quiet | {
            "PREFECT_API_URL": f"http://{address}/api",
            "PREFECT_API_AUTH_STRING": auth.value,
            "FYLGJA_API_ADDRESS": served.address,
            "FYLGJA_API_TOKEN": ALICE,
            "FYLGJA_INFRAHUB_ADDRESS": os.environ[ADDRESS],
            "FYLGJA_INFRAHUB_TOKEN": example_token.value,
            "FYLGJA_ORCHESTRATOR_SCOPE": seed["scope"],
            "FYLGJA_ORCHESTRATOR_READER": str(READER_DOCUMENT),
            "FYLGJA_ORCHESTRATOR_ROOT": str(records),
        }
        if os.environ.get(CA):
            runner_env[CA] = os.environ[CA]
        runner = start([str(BIN / "fylgja-orchestrator"), "serve"], runner_env, runner_output)
        stack.callback(end, runner)
        serving_s = waited(
            "both deployments",
            lambda: all(answers(api, f"/deployments/name/{flow}/main") for flow in ("stage-plan", "twin-rehearse")),
            runner,
            runner_output,
        )
        validator = proposals.validated(proposal.id)
        made = InfrahubSource(os.environ[ADDRESS], example_token.value, document, ca=ca())
        began = time.monotonic()
        try:
            planned = rehearsal.plan(made, served.client, seed["branch"], seed["scope"])
        finally:
            made.close()
        print(f"the server answered /api/health {up:.1f} s after its start, the runner served both deployments "
              f"{serving_s:.1f} s after its; the validation completed at {validator['completed_at']}; the plan read "
              f"once in {time.monotonic() - began:.1f} s, {planned['status']}")
        assert planned["status"] == "planned"
        held = {
            "the Prefect basic auth": auth.value,
            "the Prefect basic auth's password": auth.value.partition(":")[2],
            "the example's Infrahub token": example_token.value,
            "the core's token": ALICE,
            "the writer's token": writer_token.value,
            "the reader's token": reader.value,
        }
        yield Edge(
            served=served,
            address=address,
            api=api,
            environ={glue.ENV_ADDRESS: address, glue.ENV_AUTH: auth.value},
            ask=asker(os.environ[ADDRESS], reader),
            proposal=proposal,
            branch=seed["branch"],
            secrets=held,
            outputs=(server_output, runner_output),
        )
    listed = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=True, timeout=30).stdout
    columns = [line.split() for line in listed.splitlines()]
    assert [row for row in columns if len(row) > 3 and row[3].endswith(f":{port}")] == []


def run_ids(api: httpx.Client) -> set[str]:
    """The ids of every flow run the server holds."""
    found = api.post("/flow_runs/filter", json={"limit": 200})
    assert found.status_code == 200
    return {run["id"] for run in found.json()}


def new_run(api: httpx.Client, before: set[str]) -> str:
    [made] = run_ids(api) - before
    return made


def document_of(api: httpx.Client, run: str) -> dict[str, Any]:
    """The one artifact the run filed, as Prefect answers it."""
    found = api.post("/artifacts/filter", json={"artifacts": {"flow_run_id": {"any_": [run]}}})
    assert found.status_code == 200
    [artifact] = found.json()
    return dict(artifact)


def states(api: httpx.Client, run: str) -> list[tuple[str, float]]:
    """The run's states in order, each its type and its timestamp as a POSIX time."""
    found = api.get("/flow_run_states/", params={"flow_run_id": run})
    assert found.status_code == 200
    held = [(state["type"], datetime.fromisoformat(state["timestamp"]).timestamp()) for state in found.json()]
    return sorted(held, key=lambda state: state[1])


def concluded(outcome: Any) -> Any:
    MESSAGES.append(outcome.message)
    return outcome


def test_stage_plan_is_started_waited_for_and_read(edge: Edge) -> None:
    before = run_ids(edge.api)
    began = time.monotonic()
    outcome = concluded(asyncio.run(glue.step(edge.ask, edge.branch, timeout=900, environ=edge.environ)))
    print(f"fylgja-step concluded {outcome.passed} in {time.monotonic() - began:.1f} s: {outcome.message}")
    assert outcome.passed is True
    run = new_run(edge.api, before)
    artifact = document_of(edge.api, run)
    assert (artifact["type"], artifact["key"]) == ("fylgja-document", f"fylgja-stage-plan-{run}")
    planned = json.loads(artifact["data"])
    assert validate("plan-1", planned) == []
    assert planned["status"] == "planned"


def test_twin_rehearse_runs_to_its_document_and_posts_its_thread(edge: Edge, writer: Writer) -> None:
    before, threads = run_ids(edge.api), writer.threads(edge.proposal.id)
    began = time.monotonic()
    outcome = concluded(asyncio.run(glue.twin(edge.ask, edge.branch, timeout=4260, environ=edge.environ)))
    print(f"fylgja-twin concluded {outcome.passed} in {time.monotonic() - began:.1f} s: {outcome.message}")
    run = new_run(edge.api, before)
    artifact = document_of(edge.api, run)
    assert (artifact["type"], artifact["key"]) == ("fylgja-document", f"fylgja-twin-rehearse-{run}")
    rehearsed = json.loads(artifact["data"])
    assert validate("rehearsal-1", rehearsed) == []
    assert rehearsed["status"] == "passed"
    assert outcome.passed is (rehearsed["status"] == "passed")
    after = writer.threads(edge.proposal.id)
    [thread] = set(after) - set(threads)
    assert len(after) == len(threads) + 1
    assert len(writer.comments(thread)) == 2


def test_a_rehearsal_cancelled_at_the_checks_deadline_is_stopped_and_its_twin_deleted(
    edge: Edge, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = edge.served.driver
    asked: list[tuple[float, list[tuple[str, ...]]]] = []
    real = glue.Prefect.cancel

    def cancel(self: Any, run_id: str) -> Any:
        asked.append((time.time(), list(driver.calls)))
        return real(self, run_id)

    monkeypatch.setattr(glue.Prefect, "cancel", cancel)
    change = Change(edge.branch, edge.proposal.id, edge.proposal.name, "")
    before, earlier = run_ids(edge.api), len(driver.calls)
    driver.block = "apply"
    try:
        checked = glue.twin(edge.ask, edge.branch, timeout=CANCEL_TIMEOUT_S, environ=edge.environ)
        outcome = concluded(asyncio.run(checked))
        run = new_run(edge.api, before)
        name = twin_name(change, run)  # the twin the run's id names
        gone: float | None = None
        listed: list[str] = []
        deadline = time.time() + GONE_S + 15
        while gone is None and time.time() < deadline:
            twins = [twin for twin in edge.served.other.list_twins() if twin["name"] == name]
            if all("deletion_requested_at" in twin for twin in twins):
                gone, listed = time.time(), [twin["name"] for twin in twins]
            else:
                time.sleep(0.2)
    finally:
        driver.block = None
        driver.release("apply")
    print(f"fylgja-twin concluded {outcome.passed}: {outcome.message}")
    assert outcome.passed is False
    assert outcome.message.startswith("this check's own deadline, 420 s after it began, passed: the run was asked to "
                                      "cancel\n")
    [(cancelled_at, calls)] = asked
    # An apply of this rehearsal's own twin, after the calls the tests before it left.
    assert ("apply", name) in calls[earlier:], (
        f"the rehearsal made no apply of its twin {name} before the check's deadline; its calls were {calls[earlier:]}")
    held = states(edge.api, run)
    print(f"the run's states, seconds after the cancel was sent: "
          f"{[(kind, round(at - cancelled_at, 3)) for kind, at in held]}")
    ends = [at for kind, at in held if kind == "CANCELLED"]
    assert ends != []
    print(f"CANCELLED {ends[0] - cancelled_at:.2f} s after the cancel was sent; the core listed the twin "
          f"{name} {'with its deletion asked' if listed else 'no more'}, "
          f"{f'{gone - ends[0]:.2f}' if gone is not None else 'not'} s after CANCELLED")
    assert ends[0] - cancelled_at <= CANCELLED_S
    assert gone is not None and gone - ends[0] <= GONE_S


def test_a_draft_starts_no_run(edge: Edge, proposals: Proposals) -> None:
    proposals.set_draft(edge.proposal.id, True)
    before = run_ids(edge.api)
    outcome = concluded(asyncio.run(glue.twin(edge.ask, edge.branch, timeout=4260, environ=edge.environ)))
    assert outcome.passed is True
    assert outcome.message.startswith(f'not rehearsed: proposed change "{edge.proposal.name}" is a draft.')
    assert run_ids(edge.api) == before


def test_no_credential_reaches_a_message_or_the_runners_output(edge: Edge) -> None:
    texts = [*MESSAGES, *(path.read_text(errors="replace") for path in edge.outputs)]
    found = [name for name, value in edge.secrets.items() if value and any(value in text for text in texts)]
    print(f"searched {len(MESSAGES)} messages and {sum(len(text) for text in texts[len(MESSAGES):])} characters of "
          "output")
    assert len(MESSAGES) == 4
    assert found == []
