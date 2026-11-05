"""The end-to-end modules' shared harness: `fylgja-core-server` as a subprocess, the thin CLI
in-process, and what they read of the host. `test_e2e.py` (phase 4's create, kill and delete)
and `test_e2e_step.py` (phase 5's steps) import it; neither shares a server with the other.

`serve` starts the server over a store in a temporary directory, with a token it makes for the
principal `e2e`, the node logins from the environment, and `FYLGJA_STEP_WAIT_S` at
`STEP_WAIT_S`, so a step whose verify never holds ends within the tier's deadline;
`Core.restart()` kills it with SIGKILL and starts it again the same way. At the end every twin
the module names is destroyed through the API, the server started again if it is down, any whose
lab is still on the host is torn down by containerlab, and the module fails if the host still
holds any of them. `cli` runs the CLI in-process, each call within a deadline. Each module wraps
the two in fixtures of its own. `assert_log_clean` holds the server's log to Constitution X, and
each module runs it as its last test.

No assertion here shows a secret when it fails: the token and the environment the server is
started with (every node login) are kept out of `Core`'s repr and out of every frame's
arguments, and the log check reports line numbers, never lines.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from fylgja_core import cli as thin_cli
from fylgja_core import schemas
from fylgja_core.client import messages
from fylgja_core.server import auth

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "testdata" / "blueprint" / "three-node.json"
SERVER = Path(sys.executable).parent / "fylgja-core-server"
NODES = ("n1", "n2", "n3")
DEADLINE_S = 600.0
"""Every wait's budget: a create of three SR Linux nodes takes about 60-90 s."""
QUIET_S = 120.0
"""The longest a watch of a create goes without a write: the deploy's 40 s, twice over and more."""
STEP_WAIT_S = 90
"""The server's step wait (`FYLGJA_STEP_WAIT_S`), half its default: a step whose verify never
holds ends `stepped` with `step.wait.expired` within the tier's deadline."""
SSE = "text/event-stream"

NEEDS_LOGINS = pytest.mark.skipif(
    not os.environ.get("FYLGJA_CREDENTIAL_SRLINUX_USERNAME"),
    reason="the live tier reads the node logins from the environment: load local/.env first "
    "(set -a; . local/.env; set +a)",
)
"""Each module's `pytestmark`."""

type Fylgja = Callable[..., tuple[int, str]]
"""The CLI in-process (`cli`): its exit code and its stdout."""


def wait_for[T](read: Callable[[], T | None], what: str, timeout_s: float = DEADLINE_S, every_s: float = 0.5) -> T:
    """`read()` once it answers something, polled each `every_s`, failing after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    while (value := read()) is None:
        assert time.monotonic() < deadline, f"{what}: not within {timeout_s:g}s"
        time.sleep(every_s)
    return value


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@dataclass
class Core:
    """The server as a subprocess, and an HTTP client of it as `e2e`. The environment it is
    started with, which holds every node login, and the token are no part of its repr."""

    env: dict[str, str] = field(repr=False)
    port: int
    token: str = field(repr=False)
    stderr: Path
    process: subprocess.Popen[bytes] | None = None
    starts: list[float] = field(default_factory=list)
    http: httpx.Client | None = field(default=None, repr=False)

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def store(self) -> Path:
        return Path(self.env["FYLGJA_STORE"])

    def start(self) -> None:
        began = time.monotonic()
        with self.stderr.open("ab") as err:
            try:
                self.process = subprocess.Popen([str(SERVER)], env=self.env, stdout=subprocess.DEVNULL, stderr=err)
            except OSError as e:  # raised afresh, so that no frame shown holds the environment
                raise RuntimeError(f"fylgja-core-server did not start: {e.strerror}") from None
        if self.http is not None:
            self.http.close()
        # The token rides in the client's own headers, never in a call's arguments.
        self.http = httpx.Client(base_url=f"http://{self.address}", headers={"Authorization": f"Bearer {self.token}"},
                                 timeout=30.0, trust_env=False)
        wait_for(self._answers, "the server's first answer", timeout_s=60, every_s=0.05)
        self.starts.append(time.monotonic() - began)

    def _answers(self) -> bool | None:
        assert self.process is not None and self.process.poll() is None, "the server exited"
        try:
            answer = httpx.get(f"http://{self.address}/v1/version", timeout=1.0, trust_env=False)
        except httpx.TransportError:
            return None
        return True if answer.status_code == 200 else None

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def restart(self) -> None:
        """SIGKILL, as a host losing the process would, then a start the same way."""
        assert self.process is not None
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=30)
        self.start()

    def stop(self) -> None:
        if self.http is not None:
            self.http.close()
        if self.running():
            assert self.process is not None
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def client(self) -> httpx.Client:
        assert self.http is not None, "the server was never started"
        return self.http

    def record(self, twin: str) -> dict[str, Any] | None:
        """The twin's record, or None once it is gone."""
        r = self.client().get(f"/v1/twins/{twin}")
        if r.status_code == 404:
            return None
        assert r.status_code == 200, r.text
        doc: dict[str, Any] = r.json()
        return doc

    def runs(self, twin: str) -> list[dict[str, Any]]:
        r = self.client().get("/v1/runs", params={"twin": twin})
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["runs"]
        return found

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.client().get(f"/v1/runs/{run_id}")
        assert r.status_code == 200, r.text
        doc: dict[str, Any] = r.json()
        return doc

    def events(self, run_id: str) -> list[dict[str, Any]]:
        r = self.client().get(f"/v1/runs/{run_id}/events")
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["events"]
        return found

    def deploys(self, since: int, twin: str) -> list[str]:
        """The `containerlab deploy` command lines of `twin` the server logged after byte `since`."""
        with self.stderr.open("rb") as f:
            f.seek(since)
            lines = f.read().decode(errors="replace").splitlines()
        return [json.loads(line)["message"] for line in lines if "containerlab deploy" in line and f"/{twin}/" in line]


def gone(core: Core, twin: str) -> bool | None:
    return True if core.record(twin) is None else None


def remove(core: Core, twin: str) -> None:
    """Destroy `twin` through the API if it is still there, the server started again if it is down."""
    if not core.running():
        core.start()
    if core.record(twin) is not None:
        print(f"\n[e2e] removing the twin {twin} left behind", flush=True)
        asked = core.client().delete(f"/v1/twins/{twin}")
        # 202, the deletion asked; 404, the twin gone since it was read.
        assert asked.status_code in (202, 404), f"DELETE /v1/twins/{twin}: {asked.status_code} {asked.text}"
        wait_for(functools.partial(gone, core, twin), f"{twin}'s removal")


def containerlab_processes(needle: str = "") -> list[int]:
    """The pids of the `containerlab` processes whose command line holds `needle`."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv and Path(argv[0].decode(errors="replace")).name == "containerlab" and needle in " ".join(
            a.decode(errors="replace") for a in argv
        ):
            found.append(int(entry.name))
    return found


def clean_up_by_hand(core: Core, twin: str, nodes: Iterable[str] = NODES) -> None:
    """Tear down whatever the host still holds of `twin` with containerlab itself: its stray
    commands killed, its lab destroyed by its topology (or its name), any container of the lab
    left removed with `docker`, its network removed."""
    topology = core.store / "containerlab" / twin / "topology.clab.yml"
    for pid in containerlab_processes(f"/{twin}/"):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    command = (["containerlab", "destroy", "-t", str(topology), "--cleanup"] if topology.exists()
               else ["containerlab", "destroy", "--name", twin, "--cleanup"])
    destroyed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    # containerlab's destroy removes only the nodes the topology names (verified-facts.md, 0.81.0).
    for name in docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split():
        docker("rm", "-f", name)
    docker("network", "rm", f"clab-{twin}")
    print(f"\n[e2e] teardown: {' '.join(command[:3])}… for {twin}: status {destroyed.returncode}; "
          f"left {leftovers(twin, nodes)}", flush=True)


def serve(
    tmp_path_factory: pytest.TempPathFactory, twins: Iterable[str], nodes: Iterable[str] = NODES
) -> Iterator[Core]:
    """The module's server, for a module-scoped fixture to yield from: started over a store of its
    own; at the end each of `twins` (every twin the module makes, each node of which is one of
    `nodes`) removed through the API, then torn down by hand if the host still holds it, and the
    module failed if it holds it still."""
    twins, nodes = tuple(twins), tuple(nodes)
    here = tmp_path_factory.mktemp("e2e")
    token = secrets.token_urlsafe(24)
    (here / "tokens").write_text(f"# the live end-to-end test\n{auth.hash_token(token)} e2e\n")
    port = free_port()
    env = {name: value for name, value in os.environ.items() if not name.startswith("FYLGJA_")}
    env.update({name: value for name, value in os.environ.items() if name.startswith("FYLGJA_CREDENTIAL_")})
    env.update({
        "FYLGJA_STORE": str(here / "store"),
        "FYLGJA_LISTEN": f"127.0.0.1:{port}",
        "FYLGJA_DRIVER": "containerlab",
        "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
        "FYLGJA_TOKENS": str(here / "tokens"),
        "FYLGJA_STEP_WAIT_S": str(STEP_WAIT_S),
    })
    server = Core(env=env, port=port, token=token, stderr=here / "server.stderr")
    server.start()
    try:
        yield server
    finally:
        try:
            for twin in twins:
                remove(server, twin)
        finally:
            server.stop()
            for twin in twins:
                if leftovers(twin, nodes) != CLEAN or containerlab_processes(f"/{twin}/"):
                    clean_up_by_hand(server, twin, nodes)
            print(f"\n[e2e] server starts: {', '.join(f'{s:.2f}s' for s in server.starts)}; "
                  f"its log: {server.stderr}", flush=True)
            dirty = {twin: left for twin in twins if (left := leftovers(twin, nodes)) != CLEAN}
            if dirty or containerlab_processes():
                pytest.fail(f"the teardown left the host dirty: {dirty}, containerlab processes "
                            f"{containerlab_processes()}", pytrace=False)


def assert_log_clean(core: Core) -> None:
    """Every line the server logged is one JSON object, and none holds the token or a node's
    password (Constitution X): failing, it names the lines by number, never their text."""
    lines = core.stderr.read_text(errors="replace").splitlines()
    assert lines

    def is_json(line: str) -> bool:
        try:
            json.loads(line)
        except ValueError:
            return False
        return True

    not_json = [i for i, line in enumerate(lines, 1) if not is_json(line)]
    assert not not_json, f"lines {not_json} of the log are no JSON"
    with_token = [i for i, line in enumerate(lines, 1) if core.token in line]
    assert not with_token, f"lines {with_token} of the log hold the token"
    for variable in sorted(core.env):
        if variable.startswith("FYLGJA_CREDENTIAL_") and variable.endswith("_PASSWORD"):
            pattern = re.compile(rf"(?<![\w-]){re.escape(core.env[variable])}(?![\w-])")
            holding = [i for i, line in enumerate(lines, 1) if pattern.search(line)]
            assert not holding, f"lines {holding} of the log hold {variable}'s value"
    print(f"\n[e2e] the server logged {len(lines)} lines, every one JSON, no token or password", flush=True)


def cli(core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
    """The thin CLI in-process as `e2e`, within `DEADLINE_S`: its exit code and its stdout, timed
    and printed. It runs on a thread of its own, so that a command that never ends fails the test."""
    monkeypatch.setenv("FYLGJA_API_ADDRESS", core.address)
    monkeypatch.setenv("FYLGJA_API_TOKEN", core.token)

    def run(*args: str) -> tuple[int, str]:
        earlier = capsys.readouterr()  # what the test printed since: shown, and kept out of this command's stdout
        with capsys.disabled():
            print(earlier.out, end="", flush=True)
        began = time.monotonic()
        answer: list[int] = []
        raised: list[BaseException] = []

        def call() -> None:
            try:
                answer.append(thin_cli.main(list(args)))
            except BaseException as e:  # SystemExit too: kept for the test's thread to report
                raised.append(e)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(DEADLINE_S)
        out, err = capsys.readouterr()
        leaked = core.token in out or core.token in err
        with capsys.disabled():
            status = f"exit {answer[0]}" if answer else f"raised {type(raised[0]).__name__}" if raised else "no exit"
            print(f"\n[e2e] fylgja-core {' '.join(args)}: {status} in {time.monotonic() - began:.1f}s", flush=True)
            if not leaked and answer and answer[0] != 0:
                print(err, flush=True)
        assert not leaked, "the CLI's output holds the token"
        if raised:  # its type alone: the message of an exception that escaped the CLI's own guard is not shown
            exited = raised[0].code if isinstance(raised[0], SystemExit) else None
            code = f" ({exited})" if isinstance(exited, int) else ""  # a status alone, never a text payload
            pytest.fail(f"fylgja-core {' '.join(args[:2])} raised {type(raised[0]).__name__}{code}")
        assert answer, f"fylgja-core {' '.join(args[:2])} did not end within {DEADLINE_S:g}s"
        return answer[0], out

    return run


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=False)


def leftovers(twin: str, nodes: Iterable[str] = NODES) -> dict[str, Any]:
    """What the host holds of `twin`: its containers by label, its lines of /etc/hosts (its block's
    markers and the names of `nodes`, exactly), its ssh config and its management network."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    exact = {f"clab-{twin}-{node}" for node in nodes}
    marked = {f"###### CLAB-{twin}-START ######", f"###### CLAB-{twin}-END ######"}
    lines = [line for line in hosts if line.strip() in marked or exact & set(line.split()[1:])]
    return {
        "containers": names,
        "hosts": lines,
        "ssh_config": Path(f"/etc/ssh/ssh_config.d/clab-{twin}.conf").exists(),
        "network": docker("network", "inspect", f"clab-{twin}").returncode == 0,
    }


CLEAN = {"containers": [], "hosts": [], "ssh_config": False, "network": False}


def ready(record: dict[str, Any]) -> bool:
    return any(c["type"] == "Ready" and c["status"] == "True" for c in record["status"]["conditions"])


def settled(record: dict[str, Any]) -> bool:
    return bool(record["status"]["observed_generation"] == record["generation"])


def verdict_of(core: Core, twin: str) -> str:
    """The newest run's verdict, in a line: its status and its findings' rules."""
    runs = core.runs(twin)
    verdict = runs[0].get("verdict") if runs else None
    if verdict is None:
        return "no verdict"
    return f"{verdict['status']} {[f['rule'] for f in verdict['findings']]}"


def settled_ready(core: Core, twin: str) -> dict[str, Any]:
    def read() -> dict[str, Any] | None:
        record = core.record(twin)
        assert record is not None, f"{twin} is gone"
        return record if settled(record) else None

    record = wait_for(read, f"{twin} settled")
    assert ready(record), f"{twin} settled not Ready: {verdict_of(core, twin)}"
    return record


def assert_events_whole(events: list[dict[str, Any]]) -> None:
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), "a gap in the events' seq"
    for event in events:
        assert schemas.api_validator("Event").is_valid(event), event


def started(events: list[dict[str, Any]], phase: str) -> int:
    return sum(1 for e in events if e["phase"] == phase and e["outcome"] == "started")


def reconfigures(core: Core, since: int, twin: str) -> int:
    """How many `--reconfigure` deploys of `twin` the server logged after byte `since`."""
    return sum(1 for line in core.deploys(since, twin) if "--reconfigure" in line)


def by(deadline: float, lines: Iterator[str], what: str) -> Iterator[str]:
    """A stream's lines, failing the test once `deadline` has passed: checked on every line, the
    server's keepalive comments included, so a twin that stops being written fails the test
    within the deadline even while the stream stays alive."""
    for line in lines:
        if time.monotonic() > deadline:
            pytest.fail(f"{what} within {DEADLINE_S:g}s")
        yield line


def created_until(core: Core, fylgja: Fylgja, twin: str, phase: str, blueprint: Path = BLUEPRINT) -> dict[str, Any]:
    """Create `twin` with a watch of every twin already open, so no write is missed, and answer
    its record as the loop writes `phase`; a create that settles first fails the test."""
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    with core.client().stream("GET", "/v1/twins", params={"watch": "true"}, headers={"Accept": SSE},
                              timeout=timeout) as stream:
        assert stream.status_code == 200
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(blueprint), "--no-wait")
        assert code == 0
        for message in messages(by(deadline, stream.iter_lines(), f"{twin} did not reach {phase}")):
            record: dict[str, Any] = json.loads(message.data)["object"]
            if record["name"] != twin:
                continue
            if record["status"].get("phase") == phase:
                return record
            if settled(record):
                pytest.fail(f"{twin} settled before {phase}: Ready {ready(record)}, {verdict_of(core, twin)}")
    pytest.fail(f"the watch ended before {twin} reached {phase}")
