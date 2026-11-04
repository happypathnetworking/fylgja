"""Phase 4's done criterion (design/core.md, "Phase 4"): the `three-node` fixture end to end
through API 1 and the thin CLI, on the local containerlab driver, with the server killed at
every phase boundary of a create and once during a destroy, and resumed each time to the state
asked for.

The module starts `fylgja-core-server` as a subprocess over a store in a temporary directory,
with a token it makes for the principal `e2e`, and `restart()` kills it with SIGKILL and starts
it again the same way. The CLI runs in-process through `cli.main`. The tests run in order and
share the server; each prints what it took and what it saw. At the module's end every twin
left is destroyed through the API, whatever happened, and the server is stopped.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
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
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed")
CREATE_PHASES = {"compile", "admit", "plan", "apply", "ready", "push"}

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
    """The server as a subprocess, and an HTTP client of it as `e2e`."""

    env: dict[str, str]
    port: int
    token: str
    stderr: Path
    process: subprocess.Popen[bytes] | None = None
    starts: list[float] = field(default_factory=list)

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    def start(self) -> None:
        began = time.monotonic()
        with self.stderr.open("ab") as err:
            self.process = subprocess.Popen([str(SERVER)], env=self.env, stdout=subprocess.DEVNULL, stderr=err)
        wait_for(self._answers, "the server's first answer", timeout_s=60, every_s=0.05)
        self.starts.append(time.monotonic() - began)

    def _answers(self) -> bool | None:
        assert self.process is not None and self.process.poll() is None, "the server exited"
        try:
            return True if httpx.get(f"http://{self.address}/v1/version", timeout=1.0).status_code == 200 else None
        except httpx.TransportError:
            return None

    def restart(self) -> None:
        """SIGKILL, as a host losing the process would, then a start the same way."""
        assert self.process is not None
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=30)
        self.start()

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def get(self, path: str, **params: str) -> httpx.Response:
        return httpx.get(f"http://{self.address}{path}", params=params, timeout=30.0,
                         headers={"Authorization": f"Bearer {self.token}"})

    def delete(self, path: str) -> httpx.Response:
        return httpx.delete(f"http://{self.address}{path}", timeout=30.0,
                            headers={"Authorization": f"Bearer {self.token}"})

    def record(self, twin: str) -> dict[str, Any] | None:
        """The twin's record, or None once it is gone."""
        r = self.get(f"/v1/twins/{twin}")
        if r.status_code == 404:
            return None
        assert r.status_code == 200, r.text
        doc: dict[str, Any] = r.json()
        return doc

    def runs(self, twin: str) -> list[dict[str, Any]]:
        r = self.get("/v1/runs", twin=twin)
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["runs"]
        return found

    def events(self, run_id: str) -> list[dict[str, Any]]:
        r = self.get(f"/v1/runs/{run_id}/events")
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["events"]
        return found


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
            if server.process is None or server.process.poll() is not None:
                server.start()
            for twin in [t["name"] for t in server.get("/v1/twins").json()["twins"]]:
                print(f"\n[e2e] teardown: destroying the twin {twin} left behind", flush=True)
                server.delete(f"/v1/twins/{twin}")
                wait_for(functools.partial(gone, server, twin), f"{twin}'s teardown")
        finally:
            server.stop()
            print(f"\n[e2e] server starts: {', '.join(f'{s:.2f}s' for s in server.starts)}; "
                  f"its log: {server.stderr}", flush=True)


def gone(core: Core, twin: str) -> bool | None:
    return True if core.record(twin) is None else None


@pytest.fixture
def fylgja(
    core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Callable[..., tuple[int, str]]:
    """The thin CLI in-process as `e2e`: its exit code and its stdout, timed and printed."""
    monkeypatch.setenv("FYLGJA_API_ADDRESS", core.address)
    monkeypatch.setenv("FYLGJA_API_TOKEN", core.token)

    def run(*args: str) -> tuple[int, str]:
        earlier = capsys.readouterr()  # what the test printed since: shown, and kept out of this command's stdout
        with capsys.disabled():
            print(earlier.out, end="", flush=True)
        began = time.monotonic()
        code = cli.main(list(args))
        out, err = capsys.readouterr()
        assert core.token not in out and core.token not in err
        with capsys.disabled():
            print(f"\n[e2e] fylgja-core {' '.join(args)}: exit {code} in {time.monotonic() - began:.1f}s", flush=True)
            if code != 0:
                print(err, flush=True)
        return code, out

    return run


def host_name(address: str) -> str:
    """The node's host name, read through its own push transport: a JSON-RPC `cli` request."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "cli",
            "params": {"commands": ["info from running / system name host-name"], "output-format": "text"}}
    credential = Provider(os.environ).login(SRLINUX.credentials)

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


def settled_ready(core: Core, twin: str) -> dict[str, Any]:
    def read() -> dict[str, Any] | None:
        record = core.record(twin)
        assert record is not None, f"{twin} is gone"
        return record if record["status"]["observed_generation"] == record["generation"] else None

    record = wait_for(read, f"{twin} settled")
    assert ready(record), record["status"]
    return record


def assert_events_whole(events: list[dict[str, Any]]) -> None:
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), "a gap in the events' seq"
    for event in events:
        assert schemas.api_validator("Event").is_valid(event), event


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
    code, out = fylgja("twin", "destroy", "e2e")
    assert code == 0 and "twin e2e deleted" in out
    assert core.record("e2e") is None
    assert leftovers("e2e") == CLEAN
    assert not [line for line in Path("/etc/hosts").read_text().splitlines() if "clab-e2e-" in line]
    destroy = core.runs("e2e")[0]
    assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")


# 3: a kill at every phase boundary of a create.


def reconfigures(core: Core, since: int, twin: str) -> int:
    """How many `--reconfigure` deploys of `twin` the server's log holds after byte `since`."""
    with core.stderr.open("rb") as f:
        f.seek(since)
        lines = f.read().decode(errors="replace").splitlines()
    return sum(1 for line in lines if "--reconfigure" in line and f"/{twin}/" in line and "deploy" in line)


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_server_killed_at_a_create_phase_resumes_the_same_run_to_ready(
    core: Core, fylgja: Callable[..., tuple[int, str]], phase: str
) -> None:
    twin = "e2e-kill"
    code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
    assert code == 0
    began = time.monotonic()
    seen: dict[str, Any] = {}
    # The watch sees each write as it lands, so the kill follows the phase's record at once.
    headers = {"Authorization": f"Bearer {core.token}", "Accept": "text/event-stream"}
    with httpx.stream("GET", f"http://{core.address}/v1/twins/{twin}", params={"watch": "true"}, headers=headers,
                      timeout=httpx.Timeout(30.0, read=DEADLINE_S)) as stream:
        for message in messages(stream.iter_lines()):
            record = json.loads(message.data)["object"]
            if record["status"].get("phase") == phase or ready(record):
                seen = record
                break
    assert seen, "the watch ended before the phase"
    since = core.stderr.stat().st_size
    core.restart()
    after = core.record(twin)
    assert after is not None
    print(f"[e2e] killed at {phase}: the record read {seen['status'].get('phase')} "
          f"(Ready {ready(seen)}) {time.monotonic() - began:.1f}s in, and {after['status'].get('phase')} "
          f"after the restart", flush=True)
    record = settled_ready(core, twin)
    took = time.monotonic() - began
    creates = [r for r in core.runs(twin) if r["operation"] == "create"]  # newest first
    # The run the record named when it was killed; a twin killed once Ready names none, and its run is the newest.
    run_id = seen["status"].get("run_id") or after["status"].get("run_id") or creates[0]["id"]
    assert creates[0]["id"] == run_id, "the resume made a second create run"
    assert all(r["state"] == "ended" for r in creates)
    run = creates[0]
    assert run["verdict"]["status"] == "ok", run
    events = core.events(run_id)
    assert_events_whole(events)
    applies = [e for e in events if e["phase"] == "apply" and e["outcome"] == "started"]
    assert len(applies) <= 2
    remade = reconfigures(core, since, twin)
    print(f"[e2e] killed at {phase}: Ready {took:.1f}s after the create, the same run {run_id}, "
          f"{len(applies)} apply started, {remade} --reconfigure", flush=True)
    assert [n["name"] for n in record["status"]["nodes"]] == list(NODES)

    code, _ = fylgja("twin", "destroy", twin)
    assert code == 0
    assert leftovers(twin) == CLEAN


def deploys(core: Core, since: int, twin: str) -> list[str]:
    """The `containerlab deploy` lines of `twin` the server's log holds after byte `since`."""
    with core.stderr.open("rb") as f:
        f.seek(since)
        lines = f.read().decode(errors="replace").splitlines()
    return [json.loads(line)["message"] for line in lines
            if "containerlab deploy" in line and f"/{twin}/" in line]


def test_a_server_killed_during_the_deploy_resumes_the_same_run_to_ready(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    """The longest window a kill lands in, between `planned` and `applied`: containerlab's deploy,
    which runs in a session of its own and so outlives the server killed under it."""
    twin = "e2e-kill3"
    since = core.stderr.stat().st_size
    code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
    assert code == 0
    began = time.monotonic()
    wait_for(lambda: True if deploys(core, since, twin) else None, "the deploy", every_s=0.1)
    time.sleep(10)
    after_kill = core.stderr.stat().st_size
    core.restart()
    record = settled_ready(core, twin)
    took = time.monotonic() - began
    (run,) = [r for r in core.runs(twin) if r["operation"] == "create"]
    assert run["verdict"]["status"] == "ok", run
    events = core.events(run["id"])
    assert_events_whole(events)
    applies = [e for e in events if e["phase"] == "apply" and e["outcome"] == "started"]
    resumed = deploys(core, after_kill, twin)
    print(f"[e2e] killed 10s into the deploy: Ready {took:.1f}s after the create, {len(applies)} apply started; "
          f"the resume's deploys: {[d.rsplit(' ', 1)[-1] for d in resumed]}", flush=True)
    assert len(applies) <= 2 and [n["name"] for n in record["status"]["nodes"]] == list(NODES)
    code, _ = fylgja("twin", "destroy", twin)
    assert code == 0
    assert leftovers(twin) == CLEAN


# 4: a kill during a destroy.


def test_a_server_killed_during_a_destroy_resumes_it_and_nothing_is_left(
    core: Core, fylgja: Callable[..., tuple[int, str]]
) -> None:
    twin = "e2e-kill2"
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


# 5: the server's log.


def test_every_line_the_server_logged_is_json_and_holds_no_secret(core: Core) -> None:
    lines = core.stderr.read_text(errors="replace").splitlines()
    assert lines
    for line in lines:
        json.loads(line)
    assert not [line for line in lines if core.token in line]
    passwords = [v for k, v in os.environ.items() if k.startswith("FYLGJA_CREDENTIAL_") and k.endswith("_PASSWORD")]
    for password in passwords:
        pattern = re.compile(rf"(?<![\w-]){re.escape(password)}(?![\w-])")
        assert not [line for line in lines if pattern.search(line)], "a credential's password is in the log"
    print(f"\n[e2e] the server logged {len(lines)} lines, every one JSON, no token or password", flush=True)
