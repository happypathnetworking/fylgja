"""Phase 4's done criterion (design/core.md, "Phase 4"): the `three-node` fixture end to end
through API 1 and the thin CLI, on the local containerlab driver, with the server killed at
every phase boundary of a create, during the deploy and during a destroy, and resumed each time
to the state asked for; and a deletion asked during the deploy.

The module starts `fylgja-core-server` as a subprocess over a store in a temporary directory,
with a token it makes for the principal `e2e`, and `restart()` kills it with SIGKILL and starts
it again the same way. The CLI runs in-process through `cli.main`, each call within a deadline.
The tests run in order and share the server; each prints what it took and what it saw, and
removes its twin however it ends. At the module's end every twin left is destroyed through the
API, and any twin whose lab is still on the host is torn down by containerlab, so the host is
left clean whatever happened.

No assertion here shows a secret when it fails: the token and the environment the server is
started with (every node login) are kept out of `Core`'s repr and out of every frame's
arguments, and the log checks report line numbers, never lines.
"""

from __future__ import annotations

import asyncio
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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from fylgja_core import cli, node_http, platform_package, schemas
from fylgja_core.client import messages
from fylgja_core.credentials import Provider
from fylgja_core.push import post
from fylgja_core.server import auth

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "testdata" / "blueprint" / "three-node.json"
SERVER = Path(sys.executable).parent / "fylgja-core-server"
SRLINUX = platform_package.load(ROOT / "psp" / "nokia_srlinux.yaml")
NODES = ("n1", "n2", "n3")
DEADLINE_S = 600.0
"""Every wait's budget: a create of three SR Linux nodes takes about 60-90 s."""
QUIET_S = 120.0
"""The longest a watch of a create goes without a write: the deploy's 40 s, twice over and more."""
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed")
CREATE_PHASES = {"compile", "admit", "plan", "apply", "ready", "push"}
TWINS = ("e2e", "e2e-kill", "e2e-kill2", "e2e-kill3", "e2e-del")
"""Every twin the module makes, for the teardown's last look at the host."""
SSE = "text/event-stream"

pytestmark = pytest.mark.skipif(
    not os.environ.get("FYLGJA_CREDENTIAL_SRLINUX_USERNAME"),
    reason="the live tier reads the node logins from the environment: load local/.env first "
    "(set -a; . local/.env; set +a)",
)


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
        core.client().delete(f"/v1/twins/{twin}")
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


def clean_up_by_hand(core: Core, twin: str) -> None:
    """Tear down whatever the host still holds of `twin` with containerlab itself: its stray
    commands killed, its lab destroyed by its topology (or its name), its network removed."""
    topology = core.store / "containerlab" / twin / "topology.clab.yml"
    for pid in containerlab_processes(f"/{twin}/"):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    command = (["containerlab", "destroy", "-t", str(topology), "--cleanup"] if topology.exists()
               else ["containerlab", "destroy", "--name", twin, "--cleanup"])
    destroyed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    docker("network", "rm", f"clab-{twin}")
    print(f"\n[e2e] teardown: {' '.join(command[:3])}… for {twin}: status {destroyed.returncode}; "
          f"left {leftovers(twin)}", flush=True)


@pytest.fixture(scope="module")
def core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Core]:
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
    })
    server = Core(env=env, port=port, token=token, stderr=here / "server.stderr")
    server.start()
    try:
        yield server
    finally:
        try:
            for twin in TWINS:
                remove(server, twin)
        finally:
            server.stop()
            for twin in TWINS:
                if leftovers(twin) != CLEAN or containerlab_processes(f"/{twin}/"):
                    clean_up_by_hand(server, twin)
            print(f"\n[e2e] server starts: {', '.join(f'{s:.2f}s' for s in server.starts)}; "
                  f"its log: {server.stderr}", flush=True)


@pytest.fixture
def fylgja(
    core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str]]:
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
                answer.append(cli.main(list(args)))
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
            code = f" ({raised[0].code!r})" if isinstance(raised[0], SystemExit) else ""
            pytest.fail(f"fylgja-core {' '.join(args[:2])} raised {type(raised[0]).__name__}{code}")
        assert answer, f"fylgja-core {' '.join(args[:2])} did not end within {DEADLINE_S:g}s"
        return answer[0], out

    return run


def host_name(address: str) -> str:
    """The node's host name, read through its own push transport: a JSON-RPC `cli` request."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "cli",
            "params": {"commands": ["info from running / system name host-name"], "output-format": "text"}}
    credential = Provider(os.environ).login(SRLINUX.credentials)  # its repr hides the password

    async def ask() -> dict[str, Any]:
        async with node_http.client() as client:
            url = node_http.url(address, SRLINUX.push.port, "/jsonrpc")
            return await post(client, url, body, credential, timeout_s=SRLINUX.push.timeout_s)

    answer = asyncio.run(ask())
    assert "error" not in answer, answer
    entries = answer["result"]
    print(f"[e2e] {address}'s answer: a {type(entries).__name__} of {[type(e).__name__ for e in entries]}: "
          f"{entries!r:.120}", flush=True)
    text = "\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries)
    found = re.search(r"host-name (\S+)", text)
    assert found, entries
    return found.group(1)


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=False)


def leftovers(twin: str) -> dict[str, Any]:
    """What the host holds of `twin`: its containers by label, its lines of /etc/hosts (its block's
    markers and its nodes' names, exactly), its ssh config and its management network."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    exact = {f"clab-{twin}-{node}" for node in NODES}
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


# 1 and 2: create, show, destroy.


def test_a_twin_is_created_and_each_node_answers_with_its_own_host_name(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    began = time.monotonic()
    code, _ = fylgja("twin", "create", "e2e", "--blueprint", str(BLUEPRINT))
    elapsed = time.monotonic() - began
    print(f"\n[e2e] create, end to end: {elapsed:.1f}s", flush=True)
    assert code == 0 and elapsed < DEADLINE_S

    code, out = fylgja("twin", "show", "e2e", "--json")
    record = json.loads(out)
    assert code == 0 and list(schemas.validator("twin-record-1").iter_errors(record)) == []
    status = record["status"]
    assert ready(record) and status["observed_generation"] == record["generation"] == 1
    assert [n["name"] for n in status["nodes"]] == list(NODES)
    assert all(n["holds"] == status["bundle_id"] for n in status["nodes"])
    names = {n["name"]: host_name(n["address"]) for n in status["nodes"]}
    print(f"[e2e] host names through each node's push transport: {names}", flush=True)
    assert names == {n: n for n in NODES}

    (run,) = core.runs("e2e")
    code, out = fylgja("run", "get", run["id"], "--json")
    assert code == 0 and json.loads(out)["verdict"]["status"] == "ok"
    events = core.events(run["id"])
    assert_events_whole(events)
    assert {e["phase"] for e in events} == CREATE_PHASES
    timings: dict[str, float] = {}
    for e in events:
        if e["outcome"] == "done":  # a phase's, or each node's in `ready` and `push`, summed
            timings[e["phase"]] = timings.get(e["phase"], 0.0) + e["duration_s"]
    print(f"[e2e] the create's phases: {', '.join(f'{p} {s:.2f}s' for p, s in timings.items())}", flush=True)


def test_the_twin_is_destroyed_and_nothing_is_left(core: Core, fylgja: Callable[..., tuple[int, str]]) -> None:
    try:
        code, out = fylgja("twin", "destroy", "e2e")
        assert code == 0 and "twin e2e deleted" in out
        assert core.record("e2e") is None
        assert leftovers("e2e") == CLEAN
        assert not [line for line in Path("/etc/hosts").read_text().splitlines() if "clab-e2e-" in line]
        destroy = core.runs("e2e")[0]
        assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    finally:
        remove(core, "e2e")


# 3: a kill at every phase boundary of a create.


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


def created_until(core: Core, fylgja: Callable[..., tuple[int, str]], twin: str, phase: str) -> dict[str, Any]:
    """Create `twin` with a watch of every twin already open, so no write is missed, and answer
    its record as the loop writes `phase`; a create that settles first fails the test."""
    deadline = time.monotonic() + DEADLINE_S
    timeout = httpx.Timeout(30.0, read=QUIET_S)
    with core.client().stream("GET", "/v1/twins", params={"watch": "true"}, headers={"Accept": SSE},
                              timeout=timeout) as stream:
        assert stream.status_code == 200
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
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


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_server_killed_at_a_create_phase_resumes_the_same_run_to_ready(
    core: Core, fylgja: Callable[..., tuple[int, str]], phase: str
) -> None:
    twin = "e2e-kill"
    try:
        since = core.stderr.stat().st_size
        began = time.monotonic()
        seen = created_until(core, fylgja, twin, phase)
        core.restart()  # the kill follows the phase's record at once
        after = core.record(twin)
        assert after is not None
        assert seen["status"].get("phase") == phase
        print(f"[e2e] killed at {phase}, {time.monotonic() - began:.1f}s in; the record read "
              f"{after['status'].get('phase')} after the restart", flush=True)

        record = settled_ready(core, twin)
        took = time.monotonic() - began
        creates = [r for r in core.runs(twin) if r["operation"] == "create"]  # newest first
        run_id = seen["status"]["run_id"]  # the run the record named when it was killed
        assert creates[0]["id"] == run_id, "the resume made a second create run"
        assert all(r["state"] == "ended" for r in creates)
        assert creates[0]["verdict"]["status"] == "ok", creates[0]["verdict"]
        events = core.events(run_id)
        assert_events_whole(events)
        applies, deployed, remade = started(events, "apply"), core.deploys(since, twin), reconfigures(core, since, twin)
        print(f"[e2e] killed at {phase}: Ready {took:.1f}s after the create, the same run {run_id}, "
              f"{applies} apply started, {len(deployed)} deploy, {remade} --reconfigure", flush=True)
        assert remade == 0, "a --reconfigure deploy"
        assert len(deployed) == 1, "a second deploy"
        if KILL_AT.index(phase) >= KILL_AT.index("applied"):
            assert applies == 1, f"an apply started after {phase} was recorded"
        else:
            assert 1 <= applies <= 2
        assert [n["name"] for n in record["status"]["nodes"]] == list(NODES)

        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


def test_a_server_killed_during_the_deploy_resumes_the_same_run_to_ready(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    """The longest window a kill lands in, between `planned` and `applied`: containerlab's deploy,
    which runs in a session of its own and so outlives the server killed under it."""
    twin = "e2e-kill3"
    try:
        since = core.stderr.stat().st_size
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        began = time.monotonic()
        wait_for(lambda: True if core.deploys(since, twin) else None, "the deploy", every_s=0.1)
        time.sleep(10)
        after_kill = core.stderr.stat().st_size
        core.restart()
        record = settled_ready(core, twin)
        took = time.monotonic() - began
        (run,) = [r for r in core.runs(twin) if r["operation"] == "create"]
        assert run["verdict"]["status"] == "ok", run["verdict"]
        events = core.events(run["id"])
        assert_events_whole(events)
        resumed = core.deploys(after_kill, twin)
        print(f"[e2e] killed 10s into the deploy: Ready {took:.1f}s after the create, {started(events, 'apply')} "
              f"apply started; the resume's deploys: {len(resumed)}", flush=True)
        assert started(events, "apply") <= 2 and [n["name"] for n in record["status"]["nodes"]] == list(NODES)
        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


# 4: a kill during a destroy, and a deletion during the deploy.


def test_a_server_killed_during_a_destroy_resumes_it_and_nothing_is_left(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    twin = "e2e-kill2"
    try:
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT))
        assert code == 0
        code, _ = fylgja("twin", "destroy", twin, "--no-wait")
        assert code == 0
        began = time.monotonic()
        wait_for(lambda: True if any(r["operation"] == "destroy" for r in core.runs(twin)) else None,
                 "the destroy run", every_s=0.05)
        core.restart()
        wait_for(lambda: gone(core, twin), f"{twin} gone")
        print(f"[e2e] killed during the destroy: gone {time.monotonic() - began:.1f}s after it was asked", flush=True)
        destroy = next(r for r in core.runs(twin) if r["operation"] == "destroy")
        assert destroy["verdict"]["status"] == "ok"
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


def test_a_delete_during_the_deploy_cancels_the_create_and_leaves_nothing(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    twin = "e2e-del"
    try:
        since = core.stderr.stat().st_size
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        wait_for(lambda: True if containerlab_processes(f"/{twin}/") else None, "the deploy's process", every_s=0.1)
        deploying = time.monotonic()
        assert core.deploys(since, twin)
        # Asked once the deploy has made its containers, so the cancel leaves a partial lab to tear down.
        wait_for(lambda: True if leftovers(twin)["containers"] else None, "the deploy's containers", every_s=0.2)
        assert containerlab_processes(f"/{twin}/"), "the deploy ended before the deletion was asked"
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", twin)
        print(f"[e2e] deleted {began - deploying:.1f}s into the deploy, its containers made: gone "
              f"{time.monotonic() - began:.1f}s after it was asked", flush=True)
        assert code == 0 and f"twin {twin} deleted" in out
        destroy, create = core.runs(twin)
        assert (create["operation"], create["verdict"]["status"]) == ("create", "failed"), create["verdict"]
        assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]
        assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok"), destroy["verdict"]
        assert leftovers(twin) == CLEAN
        assert containerlab_processes() == [], "a containerlab process is left"
    finally:
        remove(core, twin)


# 5: the server's log.


def test_every_line_the_server_logged_is_json_and_holds_no_secret(core: Core) -> None:
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
