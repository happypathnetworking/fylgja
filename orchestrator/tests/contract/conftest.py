"""Tier 2: every test here is marked `contract` and reads a real Infrahub, the one the Go
contract tier reads (research R-15). Without INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN each
skips, saying why, so `pytest -m contract` on a host with no Infrahub reports skips, never
failures.

A test that writes seeds Infrahub through the Go fixture tool, `cmd/fylgja-fixture`, as a
subprocess (T020): `internal/testsupport` is not ported, and the tool, built once per session
from this tree, is the one place a test's writes are made. Every branch a test seeds is a
throwaway `fylgja-test-py-<pid>-<label>`, deleted however the test ends, its stages and
proposed changes first. A test that needs the core's half, a snapshot compiled, gets a core
server of its own (`core`): `bin/fylgja serve` on a loopback port the system chose, with a
token it makes, a state root under the session's temporary directory and no INFRAHUB_*
variable, so it files nothing of the host's and reads no Infrahub."""

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from fylgja_orchestrator.adapters.infrahub import packages
from fylgja_orchestrator.adapters.infrahub import read as reading
from fylgja_orchestrator.adapters.infrahub.client import Client, Config, from_env
from fylgja_orchestrator.documents.findings import Findings

ENV = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN")
REPO = Path(__file__).resolve().parents[3]
FIXTURE_BRANCH = "fylgja-fixture"
SCOPE = "tag:fylgja"
"""The scope every fixture is read under: the tag each seeded device carries."""
TEST_PREFIX = "fylgja-test-py-"
SEED_TIMEOUT_S = 900
"""A seed's bound: the schema's 90 s wait twice and the artifacts' 180 s, with a margin."""
LISTEN_WAIT_S = 15


def require_infrahub():
    missing = [name for name in ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(f"tier 2 needs {' and '.join(missing)} (load local/.env)")


@pytest.fixture(autouse=True)
def _infrahub_required():
    require_infrahub()


@pytest.fixture
def infrahub_address():
    return os.environ["INFRAHUB_ADDRESS"].rstrip("/")


def redact(text: str) -> str:
    token = os.environ.get("INFRAHUB_API_TOKEN", "")
    return text.replace(token, "<redacted>") if token else text


def branch_name(label: str) -> str:
    """A throwaway branch's name: the Go fixture tool changes only `fylgja-test-*` branches."""
    return f"{TEST_PREFIX}{os.getpid()}-{label}"


def branch_exists(name: str) -> bool:
    """Whether Infrahub lists the branch, read on main; it writes nothing."""
    data = Client(from_env("main")).graphql(f"query {{ Branch(name: {json.dumps(name)}) {{ name }} }}")
    return any(b.get("name") == name for b in data.get("Branch") or [])


def probe_count() -> int:
    """How many objects of the probe kind the default branch holds; it writes nothing."""
    data = Client(from_env("main")).graphql("query { FylgjaProbe { count } }")
    return data["FylgjaProbe"]["count"]


class FixtureTool:
    """The Go fixture tool, run from the repository's root with this process's environment,
    whose INFRAHUB_* it reads. A failure raises with its stderr, the token redacted."""

    def __init__(self, path: Path):
        self.path = path

    def run(self, *args: str, timeout: float = SEED_TIMEOUT_S) -> str:
        done = subprocess.run([str(self.path), *args], cwd=REPO, env=os.environ, capture_output=True, text=True,
                              timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(redact(f"fylgja-fixture {' '.join(args)}: exit {done.returncode}: "
                                      f"{done.stderr.strip() or done.stdout.strip()}"))
        return done.stdout

    def seed(self, branch: str, mixed: bool = False, schema_only: bool = False) -> str:
        args = ["-branch", branch]
        if mixed:
            args.append("-mixed")
        if schema_only:
            args.append("-schema-only")
        return self.run(*args)

    def change(self, branch: str, flag: str, value: str = "") -> str:
        return self.run("-branch", branch, flag, *([value] if value else []))

    def delete(self, branch: str) -> str:
        return self.run("-delete", "-branch", branch)

    @contextmanager
    def throwaway(self, label: str, *, mixed: bool = False, schema_only: bool = False):
        """A branch seeded with the three-node fixture (the mixed one, or the schema alone),
        deleted when the block ends, however it ends, and then read to be gone."""
        name = branch_name(label)
        started = time.monotonic()
        try:
            self.seed(name, mixed=mixed, schema_only=schema_only)
            print(f"branch {name} seeded in {time.monotonic() - started:.0f}s")
            yield name
        finally:
            if branch_exists(name):
                self.delete(name)
            if branch_exists(name):
                raise RuntimeError(f"branch {name} still exists after its delete")


@pytest.fixture(scope="session")
def fixture_tool(tmp_path_factory) -> FixtureTool:
    """The fixture tool, built once per session from this tree (`go run -tags fixture
    ./cmd/fylgja-fixture`, compiled once rather than per call). It skips without Infrahub
    itself, since a module-scoped seed sets up before the autouse skip."""
    require_infrahub()
    if shutil.which("go") is None:
        pytest.skip("tier 2's seeding needs Go, which builds cmd/fylgja-fixture")
    path = tmp_path_factory.mktemp("fixture-tool") / "fylgja-fixture"
    done = subprocess.run(["go", "build", "-tags", "fixture", "-o", str(path), "./cmd/fylgja-fixture"], cwd=REPO,
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"building cmd/fylgja-fixture: {done.stderr.strip()}")
    return FixtureTool(path)


@dataclass
class Core:
    """A core server of the test's own and its CLI, which sends it a snapshot to compile."""

    binary: Path
    address: str
    token: str

    def run(self, *args: str, timeout: float = 120) -> tuple[int, dict]:
        """One `fylgja` command with --json: its exit and its document."""
        env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
               "FYLGJA_API_ADDRESS": self.address, "FYLGJA_API_TOKEN": self.token}
        done = subprocess.run([str(self.binary), *args, "--json"], env=env, capture_output=True, text=True,
                              timeout=timeout)
        try:
            return done.returncode, json.loads(done.stdout)
        except ValueError:
            raise RuntimeError(f"fylgja {' '.join(args)}: exit {done.returncode}, no document: "
                               f"{redact(done.stderr.strip())}") from None

    def compile(self, snapshot: Path, out: Path) -> tuple[int, dict]:
        return self.run("twin", "compile", "--snapshot", str(snapshot), "--out", str(out))


@pytest.fixture(scope="session")
def core(tmp_path_factory):
    """`bin/fylgja serve` on 127.0.0.1:0 with a token of its own, a temporary state root and
    no INFRAHUB_*: the compile needs neither Infrahub nor the workflow service, and files
    nothing."""
    binary = REPO / "bin" / "fylgja"
    if not binary.is_file():
        pytest.skip(f"the core's half needs {binary}: make build")
    root = tmp_path_factory.mktemp("core")
    token = secrets.token_hex(16)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "FYLGJA_STATE_ROOT": str(root / "state"), "FYLGJA_API_TOKEN": token}
    log = root / "server.log"
    with open(log, "w") as out:
        server = subprocess.Popen([str(binary), "serve", "--listen", "127.0.0.1:0"], env=env, cwd=root, stdout=out,
                                  stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + LISTEN_WAIT_S
        address = ""
        while not address:
            m = re.search(r"^fylgja serve: listening on (\S+) \(", log.read_text(), re.M)
            if m:
                address = m.group(1)
            elif server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"the core's server did not listen: {log.read_text()}")
            else:
                time.sleep(0.1)
        yield Core(binary, address, token)
    finally:
        server.terminate()
        server.wait(timeout=10)


def read_under(branch: str, at: str = "", scope: str = SCOPE, address: str = ""):
    """The read `intent read` runs under scope, as the Go tests' `readUnder` ran it: the CTM,
    None when the read refused to write one; every finding of the pass; and the ReadError
    when the read could not run at all. The adapter's read ends at the CTM's intrinsic rules,
    which the fixture's live cases never trip (research §5.11). `address` replaces
    INFRAHUB_ADDRESS, as a recording proxy's does."""
    cfg = from_env(branch, at)
    client = Client(Config(address=address or cfg.address, token=cfg.token, branch=branch, at=at))
    registry = packages.load()
    try:
        ctm, found = reading.read(client, scope, registry, reading.observed_now())
    except reading.ReadError as e:
        return None, Findings(), e
    return ctm, found, None


class _Forward(BaseHTTPRequestHandler):
    """Forwards one request to the real Infrahub and keeps its method, path and body."""

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.recorded.append((self.command, self.path, body.decode("utf-8", "replace")))
        skip = ("host", "content-length", "connection", "accept-encoding")
        headers = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        answer = httpx.request(self.command, self.server.upstream + self.path, headers=headers, content=body,
                               timeout=120)
        self.send_response(answer.status_code)
        for k, v in answer.headers.items():
            if k.lower() not in ("content-length", "transfer-encoding", "connection", "content-encoding"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(answer.content)))
        self.end_headers()
        self.wfile.write(answer.content)

    do_GET = do_POST = _forward

    def log_message(self, *args):
        pass


@dataclass
class Proxy:
    """A recording proxy in front of the real Infrahub: asserting on what was not asked is
    the only way to prove a command reads no intent."""

    address: str
    recorded: list

    def paths(self) -> list[str]:
        return [path.split("?", 1)[0] for _, path, _ in self.recorded]

    def graphql_bodies(self) -> list[str]:
        return [body for method, path, body in self.recorded if method == "POST" and path.startswith("/graphql")]


@pytest.fixture
def proxy():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Forward)
    server.upstream = os.environ["INFRAHUB_ADDRESS"].rstrip("/")
    server.recorded = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Proxy(f"http://127.0.0.1:{server.server_address[1]}", server.recorded)
    finally:
        server.shutdown()
        server.server_close()
