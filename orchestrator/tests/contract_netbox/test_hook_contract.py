"""NetBox's own webhook starting the rehearsal on a real Prefect (D-097, D-034): the tag set on a branch, the event rule
`make netbox-hook` installs, and one flow run of `twin-rehearse/main` whose report arrives on the branch.

A module fixture starts, each in a session of its own under a directory of the module's and each ended by its pid at
the module's end, a Prefect server on the address NetBox's worker reaches the host at (`scripts/edge_dev.py`'s
`bind_address`, the Docker bridge's gateway) at a free port, never 4200, its home its own, with a basic auth made here
and hidden and its analytics off; and the runner, `fylgja-orchestrator serve` under the source `netbox`, given that
server, the conftest's core (the marks are given to it, and a mark belongs to the core it was given to), NetBox's
address, the example's account's token, the reader document and the scope. Once both deployments answer, it runs
`netbox/seed/hook.py` as a child, as `make netbox-hook` does, with `--prefect` that server's API and `--receiver`
`host.docker.internal:<its port>`: a deployment's id is another under a new home, so the trigger is installed after its
Prefect is up. The hook has no names but the installed trigger's, `fylgja-rehearse`, which the source's tag is, so it
rewrites the installed webhook to name this server: what the webhook, the rule and the tag held is read first and
written back at the module's end whatever happened, member for member, or each deleted where the hook made it.
The server's home is removed once it has stopped, its flow runs and deployments with it. Each step of the module's end
runs whatever the one before it raised.

A run killed before the module's end leaves the installed webhook naming this module's Prefect, at a port no one
serves, with the tests' throwaway auth, so that a setting of the tag starts nothing: the fixture refuses to start where
the webhook does not name what `make netbox-hook` installs (`trigger_fault`), and never takes such a webhook for the
state to write back; `make netbox-hook`, with the development Prefect up, puts it right. The server and the runner are
ended at the module's end and, where the interpreter exits without it, by an `atexit` of the session's (`LIVE`). A
`SIGINT` of pytest runs the module's end. A `SIGTERM`, a `SIGHUP` or a `SIGKILL` runs neither, since pytest handles
none of them and Python's default for each ends the process without its `atexit`, and leaves both: they are found by
`pgrep -x prefect` and `pgrep -x fylgja-orchestr`, each whose `/proc/<pid>/environ` names a `PREFECT_HOME` under
pytest's own temporary directory, and ended by their pids.
"""

from __future__ import annotations

import atexit
import base64
import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from harness import ALICE, Served

from fylgja_orchestrator.netbox import TAG, NetBoxSource
from fylgja_orchestrator.rehearsal import twin_prefix
from fylgja_orchestrator.rehearsal.documents import validate

from .conftest import (
    ADDRESS,
    CA,
    CHANGE,
    EXAMPLE_TOKEN,
    READER_DOCUMENT,
    READER_TOKEN,
    ROOT,
    SCOPE,
    SEED,
    TAGS,
    TIMEOUT,
    WRITE_TOKEN,
    Secret,
    Writes,
    entries,
    hide,
    in_turn,
    loaded,
    need,
    secret,
    set_tags,
    tags_of,
    trigger_fault,
)

EDGE_DEV = loaded("fylgja_orchestrator_contract_edge_dev", ROOT / "scripts" / "edge_dev.py")
"""`scripts/edge_dev.py`, for the address the edge's Prefect is served on."""
HOOK = SEED / "hook.py"
BIN = Path(sys.executable).parent
"""The venv running the tests, whose `python`, `prefect` and `fylgja-orchestrator` are run."""

NAME = "fylgja-rehearse"
"""The installed webhook's and event rule's name, `netbox/seed/hook.py`'s `NAME`."""
HOST = "host.docker.internal"
"""The name NetBox's worker reaches the development host by (`netbox/dev/compose.override.yml`)."""
WEBHOOKS = "extras/webhooks/"
RULES = "extras/event-rules/"
TRIGGER = (
    (TAGS, ("object_types",)),
    (WEBHOOKS, ("payload_url", "http_method", "http_content_type", "additional_headers", "body_template")),
    (RULES, ("object_types", "event_types", "enabled", "conditions", "action_type", "action_object_type",
             "action_object_id")),
)
"""The installed trigger's three, by their paths, and the members `hook.py` writes of each, which the module writes
back."""

USER = "fylgja"
UP_S = 90.0
"""How long the server is given to answer `/api/health`, and the runner to serve both deployments. The server
answered 25.6 s to 30.7 s after its start, on loopback and on the bridge's gateway, and the deployments 3.5 s to
4.1 s after the runner's (design/verified-facts.md, "Prefect 3.9.2"): 90 s is 2.9 times the slowest, 30.7 s, a
derivation."""
END_S = 30.0
"""How long a process is given to exit after SIGTERM before its session is killed: phase 8's first value, set before
any end here was timed. In a run of this module the runner was read since to end in 0.8 s and the server in 0.2 s
(design/verified-facts.md, "The module's end"), the bound 37 times the slower, a derivation that sized nothing."""
HOOK_S = 120.0
"""How long `hook.py` is given to install the trigger: a first value, set before any run of it was timed. Its runs
were read since at 1.4 s, 1.4 s and 1.2 s in a run of this module (design/verified-facts.md, "The module's end"), the
bound 86 times the slowest, a derivation that sized nothing."""
RUN_S = 60.0
"""The bound from the tag's setting to Prefect listing its flow run. The run's `created` was read 0.967 s to 1.027 s
after the setting's `PATCH` over four settings, and 0.982 s through the installed trigger (design/verified-facts.md,
"One setting of the tag is one flow run", "The installed trigger starts the rehearsal's own flow run"): 60 s is 58
times the slowest, 1.027 s, a derivation. A request lost stays lost, and a setting behind a send still waiting is sent
only once that one has timed out, at 60 s ("A setting after a lost one"): no test here sets the tag while a send
waits, since the one receiver left unanswered is a port that refuses, a send that failed in 0.729 s."""
DONE_S = 300.0
"""The bound from the run's listing to its reading `COMPLETED`. This tier's whole rehearsal of four stages on the fake
runtime read `COMPLETED` 25.654 s, 23.351 s and 21.756 s after the tag's setting in three runs, and a probe flow's run
5.68 s to 11.23 s after it (design/verified-facts.md, "The installed trigger starting a whole rehearsal", "One setting
of the tag is one flow run"): 300 s is 11.7 times the slowest, 25.654 s, a derivation."""
QUIET_S = 30.0
"""How long after the run's end Prefect is read to list no second run, as the readings of the trigger watched: the
flow's own untagging started none in the 30 s after the run's end."""
LOST_S = 45.0
"""How long a setting sent to a receiver that refuses is watched for a run: the send failed 0.729 s after its start
and nothing was sent again in the 120 s watched ("A port nothing listens on"); 45 s is 62 times 0.729 s."""
CANCELLED_S = 45.0
"""The bound from the cancel to the run read `CANCELLED`, as phase 8's Prefect contract gives it: a run read
`CANCELLED` 3.1 s and 3.2 s after `CANCELLING` (design/verified-facts.md, "A cancel over HTTP"), 14 times the
slowest."""
GONE_S = 30.0
"""How long the core is given to list no twin of the change after the quiet `QUIET_S`: a first value. The library
deletes its twin before it posts the report, and in this tier's three runs the core listed none at the first read."""

ENDED = ("COMPLETED", "FAILED", "CRASHED", "CANCELLED")
"""The states a run ends in."""

OUTPUTS: list[str] = []
"""Every journal entry's text of the module's branches, searched for the credentials last."""


@dataclass
class Edge:
    """What the module's tests drive and read: the core, the Prefect server at `address` on `port` and a client of its
    API, the deployment the webhook names, the bind address, the credentials, and the processes' output files."""

    core: Served
    bind: str
    port: int
    address: str
    api: httpx.Client
    deployment: str
    auth: Secret
    secrets: dict[str, str] = field(repr=False)
    outputs: tuple[Path, ...]
    hook: Callable[[str], None]


def free_port(host: str) -> int:
    """A port of `host` nothing listens on now, never 4200."""
    while True:
        with socket.socket() as probe:
            probe.bind((host, 0))
            port = int(probe.getsockname()[1])
        if port != 4200:
            return port


LIVE: list[subprocess.Popen[bytes]] = []
"""The processes the module started and has not ended, which the session's `atexit` ends where the module's end did
not run."""


def start(argv: list[str], env: Mapping[str, str], output: Path) -> subprocess.Popen[bytes]:
    """`argv` in a session of its own, under `env` alone, its output into `output`; held in `LIVE` until it is ended."""
    with output.open("ab") as out:
        made = subprocess.Popen(argv, env=dict(env), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
    LIVE.append(made)
    return made


def end(process: subprocess.Popen[bytes]) -> float:
    """SIGTERM to the session `process` leads, by its pid, and SIGKILL to it where anything of it is left `END_S` on;
    the seconds it took."""
    began = time.monotonic()
    with contextlib.suppress(ValueError):
        LIVE.remove(process)
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
    return time.monotonic() - began


@atexit.register
def _ended() -> None:
    """Every process of `LIVE` ended, where the session ends with the module's end not run."""
    for process in list(LIVE):
        with contextlib.suppress(Exception):
            end(process)


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


def plain(value: object) -> object:
    """A member as it is meant: a choice by its value, a list of names as a sorted list."""
    if isinstance(value, dict) and set(value) == {"value", "label"}:
        return value["value"]
    if isinstance(value, list) and all(isinstance(member, str) for member in value):
        return sorted(value)
    return value


def standing(box: Writes) -> dict[str, dict[str, Any] | None]:
    """The installed trigger's three as they stand, by their paths, None where one is not."""
    return {path: box.one(path, name=NAME if path != TAGS else TAG) for path, _ in TRIGGER}


def put_back(box: Writes, before: Mapping[str, dict[str, Any] | None]) -> list[str]:
    """The installed trigger brought back to `before`: each member `hook.py` writes that differs written back, in one
    `PATCH` an object, and one the hook made where none was deleted, the rule before the webhook it names; what was
    written, by path and member."""
    done: list[str] = []
    now = standing(box)
    for path, members in reversed(TRIGGER):
        held, was = now[path], before[path]
        if held is None:
            continue
        if was is None:
            box.delete(f"{path}{held['id']}/")
            done.append(f"deleted {path}{held['id']}")
            continue
        differ = {member: plain(was.get(member)) for member in members
                  if plain(held.get(member)) != plain(was.get(member))}
        if differ:
            box.patch(f"{path}{held['id']}/", differ)
            done.append(f"wrote {path}{held['id']}'s {', '.join(differ)} back")
    return done


def runs(api: httpx.Client) -> dict[str, dict[str, Any]]:
    """Every flow run the server holds, by its id."""
    found = api.post("/flow_runs/filter", json={"limit": 200})
    assert found.status_code == 200
    return {run["id"]: run for run in found.json()}


def until[T](what: str, bound_s: float, read: Callable[[], T | None], every_s: float = 0.25) -> tuple[T, float]:
    """`read()` once it answers something, and the seconds it took, polled every `every_s` within `bound_s`."""
    began = time.monotonic()
    while (value := read()) is None:
        assert time.monotonic() - began < bound_s, f"{what} not within {bound_s:g} s"
        time.sleep(every_s)
    return value, time.monotonic() - began


def state(api: httpx.Client, run: str) -> str:
    found = api.get(f"/flow_runs/{run}")
    assert found.status_code == 200
    return str(found.json()["state"]["type"])


def document_of(api: httpx.Client, run: str) -> dict[str, Any]:
    """The one artifact the run filed, its data parsed."""
    found = api.post("/artifacts/filter", json={"artifacts": {"flow_run_id": {"any_": [run]}}})
    assert found.status_code == 200
    [artifact] = found.json()
    assert (artifact["type"], artifact["key"]) == ("fylgja-document", f"fylgja-twin-rehearse-{run}")
    data: dict[str, Any] = json.loads(artifact["data"])
    return data


def at(stamp: str) -> float:
    """A time of Prefect's as a POSIX time."""
    return datetime.fromisoformat(stamp).timestamp()


@pytest.fixture(scope="module")
def edge(
    tmp_path_factory: pytest.TempPathFactory,
    core: Served,
    box: Writes,
    tag: dict[str, Any],
    example_token: Secret,
) -> Iterator[Edge]:
    need(ADDRESS, WRITE_TOKEN, EXAMPLE_TOKEN)
    write_token = secret(WRITE_TOKEN)
    bind = EDGE_DEV.bind_address(os.environ)
    root = tmp_path_factory.mktemp("edge")
    home, records = root / "prefect", root / "records"
    home.mkdir(mode=0o700)
    records.mkdir()
    server_output, runner_output, hook_output = root / "server.out", root / "runner.out", root / "hook.out"
    port = free_port(bind)
    address = f"{bind}:{port}"
    auth = hide(Secret("the tests' Prefect auth", f"{USER}:{secrets.token_urlsafe(24)}"))
    hide(Secret("the tests' Prefect password", auth.value.partition(":")[2]))
    encoded = hide(Secret("the tests' Prefect auth in base64", base64.b64encode(auth.value.encode()).decode()))
    box.hide(auth.value, encoded.value)
    before = standing(box)
    fault = trigger_fault(before[WEBHOOKS])
    if fault is not None:
        pytest.fail(fault, pytrace=False)
    held = {
        "the Prefect basic auth": auth.value,
        "the Prefect basic auth's password": auth.value.partition(":")[2],
        "the Prefect basic auth in base64": encoded.value,
        "the example's NetBox token": example_token.value,
        "the core's token": ALICE,
        "the superuser's NetBox token": write_token.value,
        "the reader's NetBox token": os.environ.get(READER_TOKEN, ""),
    }
    held |= installed_secrets(before[WEBHOOKS])
    for name, value in held.items():
        if value:
            hide(Secret(name, value))
    box.hide(*(value for value in held.values() if value))
    quiet = {"DO_NOT_TRACK": "1", "PREFECT_SERVER_ANALYTICS_ENABLED": "false", "PREFECT_HOME": str(home)}
    base = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    api_url = f"http://{address}/api"
    outputs = (server_output, runner_output, hook_output)
    hooked: list[float] = []

    def hook(receiver: str) -> None:
        """`hook.py` run as `make netbox-hook` runs it, with this server's API, `receiver`, and the tests' auth."""
        env = base | {ADDRESS: os.environ[ADDRESS], WRITE_TOKEN: write_token.value, "FYLGJA_ORCHESTRATOR_AUTH":
                      auth.value}
        began = time.monotonic()
        with hook_output.open("ab") as out:
            done = subprocess.run([str(BIN / "python"), str(HOOK), "--prefect", api_url, "--receiver", receiver],
                                  env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=HOOK_S, check=False)
        hooked.append(time.monotonic() - began)
        assert done.returncode == 0, f"hook.py exited {done.returncode}; read {hook_output}"

    server: subprocess.Popen[bytes] | None = None
    runner: subprocess.Popen[bytes] | None = None
    api: httpx.Client | None = None
    restored: list[str] = []
    ended: dict[str, float] = {}
    try:
        server = start([str(BIN / "prefect"), "server", "start", "--host", bind, "--port", str(port), "--no-ui"],
                       base | quiet | {"PREFECT_SERVER_API_AUTH_STRING": auth.value}, server_output)
        basic = httpx.BasicAuth(*auth.value.split(":"))
        api = httpx.Client(base_url=api_url, auth=basic, timeout=TIMEOUT, trust_env=False)
        client = api
        up = waited("the Prefect server's /api/health", lambda: answers(client, "/health"), server, server_output)
        runner_env = base | quiet | {
            "PREFECT_API_URL": api_url,
            "PREFECT_API_AUTH_STRING": auth.value,
            "FYLGJA_ORCHESTRATOR_SOURCE": "netbox",
            "FYLGJA_API_ADDRESS": core.address,
            "FYLGJA_API_TOKEN": ALICE,
            ADDRESS: os.environ[ADDRESS],
            "FYLGJA_NETBOX_TOKEN": example_token.value,
            "FYLGJA_ORCHESTRATOR_SCOPE": SCOPE,
            "FYLGJA_ORCHESTRATOR_READER": str(READER_DOCUMENT),
            "FYLGJA_ORCHESTRATOR_ROOT": str(records),
        }
        if os.environ.get(CA):
            runner_env[CA] = os.environ[CA]
        runner = start([str(BIN / "fylgja-orchestrator"), "serve"], runner_env, runner_output)
        serving_s = waited(
            "both deployments",
            lambda: all(answers(client, f"/deployments/name/{flow}/main") for flow in ("stage-plan", "twin-rehearse")),
            runner,
            runner_output,
        )
        hook(f"{HOST}:{port}")
        deployment = str(api.get("/deployments/name/twin-rehearse/main").json()["id"])
        print(f"the server answered /api/health {up:.1f} s after its start, the runner served both deployments "
              f"{serving_s:.1f} s after its; hook.py installed the trigger for deployment {deployment} in "
              f"{hooked[-1]:.1f} s")
        yield Edge(core=core, bind=bind, port=port, address=address, api=api, deployment=deployment, auth=auth,
                   secrets=held, outputs=outputs, hook=hook)
    finally:

        def stopped(name: str, process: subprocess.Popen[bytes] | None) -> None:
            if process is not None:
                ended[name] = end(process)

        def closed() -> None:
            if api is not None:
                api.close()

        in_turn(
            lambda: restored.extend(put_back(box, before)),
            lambda: stopped("runner", runner),
            closed,
            lambda: stopped("server", server),
            lambda: print(f"the installed trigger put back: {'; '.join(restored) or 'nothing differed'}; ended "
                          f"{', '.join(f'the {name} in {s:.1f} s' for name, s in ended.items()) or 'nothing'}; "
                          f"hook.py ran in {', '.join(f'{s:.1f}' for s in hooked) or 'no'} s"),
            lambda: as_before(box, before),
            lambda: port_free(port),
            lambda: no_leak(held, outputs),
            lambda: shutil.rmtree(home),
        )


def installed_secrets(webhook: Mapping[str, Any] | None) -> dict[str, str]:
    """The installed webhook's header line, its base64 and the basic auth and password it carries, by a name each:
    what the module reads of the installed trigger, which no report or output of the tier may hold."""
    line = str((webhook or {}).get("additional_headers") or "")
    if not line:
        return {}
    encoded = line.rpartition(" ")[2]
    try:
        decoded = base64.b64decode(encoded, validate=True).decode()
    except ValueError:
        decoded = ""
    return {
        "the installed webhook's header": line,
        "the installed webhook's auth in base64": encoded,
        "the installed webhook's auth": decoded,
        "the installed webhook's password": decoded.partition(":")[2],
    }


def as_before(box: Writes, before: Mapping[str, dict[str, Any] | None]) -> None:
    """The installed trigger read back as `before` held it, member for member, compared outside the assert."""
    after = standing(box)
    assert [path for path, _ in TRIGGER if (before[path] is None) != (after[path] is None)] == []
    for path, members in TRIGGER:
        was, now = before[path], after[path]
        if was is not None and now is not None:
            same = all(plain(was.get(member)) == plain(now.get(member)) for member in members)
            assert same, f"the installed {path} was not put back as it was"


def port_free(port: int) -> None:
    listed = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=True, timeout=30).stdout
    assert [row for row in (line.split() for line in listed.splitlines()) if len(row) > 3
            and row[3].endswith(f":{port}")] == []


def leaked(held: Mapping[str, str], outputs: tuple[Path, ...]) -> list[str]:
    """The names of the credentials of `held` that the processes' outputs or a journal entry of `OUTPUTS` hold, each
    compared outside any assert."""
    texts = [*OUTPUTS, *(path.read_text(errors="replace") for path in outputs if path.exists())]
    return [name for name, value in held.items() if value and any(value in text for text in texts)]


def no_leak(held: Mapping[str, str], outputs: tuple[Path, ...]) -> None:
    """At the module's end, whatever order its tests ran in: no credential in any output or entry."""
    found = leaked(held, outputs)
    print(f"searched {len(OUTPUTS)} journal entries and the module's {len(outputs)} outputs at its end")
    assert found == []


def test_setting_the_tag_starts_one_rehearsal_whose_report_is_the_branchs_journal_entry(
    edge: Edge, box: Writes, branch: dict[str, Any], source: NetBoxSource, example_user: int
) -> None:
    change = source.change(branch["name"])
    for label, _, _ in CHANGE.STEPS:
        CHANGE.step(box, branch["schema_id"], label)
        assert source.mark(change, label, SCOPE).blueprint_id is not None
    before, held = runs(edge.api), entries(box, branch)
    sent = time.time()
    set_tags(box, branch, TAG)

    def new() -> dict[str, Any] | None:
        made = [run for key, run in runs(edge.api).items() if key not in before]
        return made[0] if made else None

    run, _ = until("the tag's flow run", RUN_S, new)
    assert run["deployment_id"] == edge.deployment
    assert run["parameters"] == {"branch": branch["name"]}
    def over() -> str | None:
        now = state(edge.api, run["id"])
        return now if now in ENDED else None

    _, ran_s = until("the run's end", DONE_S, over, every_s=1.0)
    ended = edge.api.get(f"/flow_runs/{run['id']}").json()
    assert ended["state"]["type"] == "COMPLETED", ended["state"]["type"]
    rehearsed = document_of(edge.api, run["id"])
    assert validate("rehearsal-1", rehearsed) == []
    assert rehearsed["status"] == "passed", rehearsed["headline"]

    written = entries(box, branch)
    OUTPUTS.extend(entry["comments"] for entry in written)
    assert len(written) == len(held) + 1
    report = written[-1]
    assert report["kind"]["value"] == "success"
    assert report["comments"].startswith("## Rehearsal passed")
    assert report["created_by"] == example_user
    assert TAG not in tags_of(box, branch)
    entry_s = at(report["created"]) - sent
    created_s, end_s = at(run["created"]) - sent, at(ended["state"]["timestamp"]) - sent
    print(f"from the tag's setting: the run created {created_s:.3f} s, its report filed {entry_s:.3f} s and the run "
          f"COMPLETED {end_s:.3f} s on; the run read ended {ran_s:.1f} s after it was listed")

    time.sleep(max(0.0, at(ended["state"]["timestamp"]) + QUIET_S - time.time()))
    since = [key for key, made in runs(edge.api).items() if key not in before]
    assert since == [run["id"]], "the flow's own untagging, or anything else, started a run"

    webhook = box.one(WEBHOOKS, name=NAME)
    assert webhook is not None
    assert webhook["payload_url"] == f"http://{HOST}:{edge.port}/api/deployments/{edge.deployment}/create_flow_run"
    prefix = twin_prefix(change)
    left, gone_s = until("the core listing no twin of the change", GONE_S,
                         lambda: True if not [t for t in edge.core.other.list_twins()
                                              if t["name"].startswith(prefix)] else None)
    assert left is True
    print(f"the core listed no twin {prefix}* {gone_s:.1f} s after the quiet {QUIET_S:g} s")


def test_a_tag_set_while_the_receiver_does_not_answer_starts_nothing_and_the_next_setting_does(
    edge: Edge, box: Writes, branch: dict[str, Any]
) -> None:
    dead = free_port(edge.bind)
    edge.hook(f"{HOST}:{dead}")
    try:
        before, held = runs(edge.api), entries(box, branch)
        set_tags(box, branch, TAG)
        time.sleep(LOST_S)
        assert set(runs(edge.api)) == set(before)
        assert TAG in tags_of(box, branch)
        assert entries(box, branch) == held
    finally:
        edge.hook(f"{HOST}:{edge.port}")
    set_tags(box, branch)
    sent = time.time()
    set_tags(box, branch, TAG)

    def new() -> dict[str, Any] | None:
        made = [run for key, run in runs(edge.api).items() if key not in before]
        return made[0] if made else None

    run, _ = until("the next setting's flow run", RUN_S, new)
    assert run["parameters"] == {"branch": branch["name"]}
    asked = edge.api.post(f"/flow_runs/{run['id']}/set_state", json={"state": {"type": "CANCELLING"}})
    assert asked.status_code in (200, 201)
    cancelled, cancel_s = until("CANCELLED", CANCELLED_S,
                                lambda: "CANCELLED" if state(edge.api, run["id"]) == "CANCELLED" else None)
    print(f"the next setting's run created {at(run['created']) - sent:.3f} s after it, answered "
          f"{asked.json().get('status')} to the cancel and read {cancelled} {cancel_s:.1f} s after it")
    OUTPUTS.extend(entry["comments"] for entry in entries(box, branch))


def test_no_credential_reaches_an_output_or_the_journal(edge: Edge) -> None:
    """What the processes have said so far and the entries the module's tests have read, whichever ran; the module's
    end searches it all again (`no_leak`)."""
    found = leaked(edge.secrets, edge.outputs)
    print(f"searched {len(OUTPUTS)} journal entries and {sum(p.stat().st_size for p in edge.outputs if p.exists())} "
          "bytes of output")
    assert found == []
