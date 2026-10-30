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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from fylgja_orchestrator.adapters.infrahub import packages, stages
from fylgja_orchestrator.adapters.infrahub import read as reading
from fylgja_orchestrator.adapters.infrahub import stage_reader as sr
from fylgja_orchestrator.adapters.infrahub.client import Client, Config, default_from_env, from_env
from fylgja_orchestrator.documents.findings import REJECTION, Findings

ENV = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN")
REPO = Path(__file__).resolve().parents[3]
FIXTURE_BRANCH = "fylgja-fixture"
SCOPE = "tag:fylgja"
"""The scope every fixture is read under: the tag each seeded device carries."""
TEST_PREFIX = "fylgja-test-py-"
SEED_TIMEOUT_S = 900
"""A seed's bound: the schema's 90 s wait twice and the artifacts' 180 s, with a margin."""
LISTEN_WAIT_S = 15
ARTIFACT_WAIT_S = 180
"""`testsupport.ArtifactWait`: how long a checksum is awaited to move after a generate."""
ARTIFACT_NAME = "device-config"


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


def graphql(branch: str, query: str) -> dict:
    """One read of a branch's GraphQL, `main` the default branch's; it writes nothing."""
    return Client(from_env(branch)).graphql(query)


def proposed_changes_of(branch: str) -> dict[str, list[str]]:
    """Every proposed change whose source the branch is, whatever its state, each with its
    stages' ids, read on main: what a throwaway's deletion must leave none of."""
    data = graphql("main", "query { CoreProposedChange(source_branch__value: %s) { edges { node { id "
                   "fylgja_stages { edges { node { id } } } } } } }" % json.dumps(branch))
    return {e["node"]["id"]: [s["node"]["id"] for s in e["node"]["fylgja_stages"]["edges"]]
            for e in data["CoreProposedChange"]["edges"]}


def stages_present(ids: list[str]) -> list[str]:
    """Which of the stages are still read on main."""
    if not ids:
        return []
    data = graphql("main", "query { FylgjaStage(ids: %s) { edges { node { id } } } }" % json.dumps(ids))
    return [e["node"]["id"] for e in data["FylgjaStage"]["edges"]]


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

    def propose(self, branch: str) -> str:
        """A draft proposed change from the branch into main, its pipeline awaited: its id."""
        started = time.monotonic()
        out = self.run("-branch", branch, "-propose")
        m = re.search(r"^proposed change (\S+) opened on ", out, re.M)
        if not m:
            raise RuntimeError(f"-propose printed no id: {out!r}")
        print(f"proposed change {m.group(1)} on {branch}, its pipeline concluded after "
              f"{time.monotonic() - started:.0f}s")
        return m.group(1)

    def mark(self, branch: str, label: str, at: str = "", description: str = "") -> tuple[str, str]:
        """One stage marked on the branch's open proposed change, through the default branch's
        GraphQL: its id, and its at, the label's write stamp verbatim unless one is given."""
        args = ["-branch", branch, "-stage", label]
        if at:
            args += ["-at", at]
        if description:
            args += ["-description", description]
        out = self.run(*args)
        m = re.search(r"\(stage id (\S+)\) at (\S+) \((written|given)\)$", out.strip())
        if not m:
            raise RuntimeError(f"-stage printed no id and at: {out!r}")
        return m.group(1), m.group(2)

    def update_stage(self, branch: str, label: str, field: str, value: str) -> str:
        return self.run("-branch", branch, "-update-stage", f"{label}:{field}={value}")

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
            # What hangs on the branch is collected before the deletion, by id, so the check
            # after it is of the test's own objects (the Go tests' testBranch).
            made = proposed_changes_of(name)
            marks = [m for ids in made.values() for m in ids]
            if branch_exists(name):
                print(self.delete(name).strip())
            if branch_exists(name):
                raise RuntimeError(f"branch {name} still exists after its delete")
            left = proposed_changes_of(name)
            if left:
                raise RuntimeError(f"the proposed changes {sorted(left)} on {name} are still read after its delete")
            if stages_present(marks):
                raise RuntimeError(f"the stages {stages_present(marks)} made on {name} are still read after its delete")


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
    state: Path
    log: Path | None = None
    """The server's log, one line a request (T028 reads which operations it was asked)."""

    def operations(self) -> list[tuple[str, str]]:
        """Each request the server logged, in order: its operation and its outcome (its log
        holds one line a request, never a token)."""
        if self.log is None:
            return []
        return re.findall(r" msg=request operation=(\S+) outcome=(\S+)", self.log.read_text())

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

    def diff(self, a: Path, b: Path) -> tuple[int, dict]:
        """`twin diff` of two snapshot files: the step between their bundles (T010)."""
        return self.run("twin", "diff", "--from", str(a), "--to", str(b))


@contextmanager
def serving(root: Path, extra: dict[str, str] | None = None):
    """`bin/fylgja serve` on 127.0.0.1:0 with a token of its own, its state root under root and
    no INFRAHUB_*: the compile needs neither Infrahub nor the workflow service. `extra` adds
    variables to its environment (the flows' tests give the host held its logins' names)."""
    binary = REPO / "bin" / "fylgja"
    if not binary.is_file():
        pytest.skip(f"the core's half needs {binary}: make build")
    root.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    state = root / "state"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "FYLGJA_STATE_ROOT": str(state), "FYLGJA_API_TOKEN": token, **(extra or {})}
    assert not any(name.startswith("INFRAHUB_") for name in env), "the core's server is given no INFRAHUB_*"
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
        yield Core(binary, address, token, state, log)
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def core(tmp_path_factory):
    """A core server for the session, which files nothing of the host's."""
    with serving(tmp_path_factory.mktemp("core")) as c:
        yield c


@pytest.fixture
def own_core(tmp_path):
    """A core server of the test's own, whose stores hold only what the test files."""
    with serving(tmp_path / "core") as c:
        yield c


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


# The stages' harness (T021): Infrahub's own state read beside the product's, and the
# stage plan's outcomes made of the adapter's resolution and take and the core's compile and
# diff, since the plan itself is the orchestrator's flow's.


def artifacts_ready_at(branch: str) -> datetime:
    """When the branch's last artifact was rendered: the latest checksum stamp among them,
    every artifact Ready (`testsupport.ArtifactsReadyAt`)."""
    edges = graphql(branch, "query { CoreArtifact { edges { node { status { value } checksum { updated_at } } } } }"
                    )["CoreArtifact"]["edges"]
    assert edges, f"branch {branch} holds no artifact"
    stamps = []
    for edge in edges:
        node = edge["node"]
        assert node["status"]["value"] == "Ready", f"branch {branch} holds an artifact {node['status']['value']}"
        stamps.append(datetime.fromisoformat(node["checksum"]["updated_at"]))
    return max(stamps)


def artifacts_of(branch: str, ready_only: bool = False) -> dict[str, dict]:
    """Each device's device-config artifact as Infrahub lists it now: its checksum, storage id
    and status, read through the library's device and Infrahub's target interface as the read
    does; with ready_only, the Ready ones alone (the Go tests' `checksums`)."""
    data = graphql(branch, """query { DcimDevice { edges { node { name { value }
        ... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value } storage_id { value }
            definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }""")
    out = {}
    for d in data["DcimDevice"]["edges"]:
        for a in d["node"]["artifacts"]["edges"]:
            n = a["node"]
            if n["definition"]["node"]["artifact_name"]["value"] != ARTIFACT_NAME:
                continue
            if ready_only and n["status"]["value"] != "Ready":
                continue
            out[d["node"]["name"]["value"]] = {"checksum": n["checksum"]["value"],
                                              "storage_id": n["storage_id"]["value"], "status": n["status"]["value"]}
    return out


def checksums(branch: str) -> dict[str, str]:
    """Each device's Ready device-config checksum, as Infrahub lists it now."""
    return {d: a["checksum"] for d, a in artifacts_of(branch, ready_only=True).items()}


def await_moved(branch: str, before: dict[str, str], *devices: str, wait: float = ARTIFACT_WAIT_S) -> dict[str, str]:
    """Polls until each named device's artifact is Ready with a checksum other than before's,
    as scripts/e2e.sh's await_checksums_moved does."""
    deadline = time.monotonic() + wait
    while True:
        now = checksums(branch)
        if all(now.get(d) and now[d] != before.get(d) for d in devices):
            return now
        if time.monotonic() > deadline:
            raise AssertionError(f"the artifacts of {devices} on {branch} did not move from {before} within {wait}s: "
                                 f"{now}")
        time.sleep(1)


def await_joined(branch: str, device: str = "n1", port: str = "ethernet-1/3") -> None:
    """Polls until the new port is stamped later than the branch's latest checksum: Infrahub's
    task workers add what a generation read for the first time to the template query's groups
    a few seconds after it, which moves the node's stamp past the generation (D-058). Its
    absence after a minute is D-058's revisit."""
    generated = artifacts_ready_at(branch)
    query = ('query { InterfacePhysical(device__name__value: %s, name__value: %s) '
             '{ edges { node_metadata { updated_at } } } }' % (json.dumps(device), json.dumps(port)))
    deadline = time.monotonic() + 60
    while True:
        edges = graphql(branch, query)["InterfacePhysical"]["edges"]
        if len(edges) == 1:
            at = datetime.fromisoformat(edges[0]["node_metadata"]["updated_at"])
            if at > generated:
                print(f"the query groups took in {device}:{port} at {at.isoformat()}, "
                      f"{(at - generated).total_seconds():.1f}s after the latest checksum")
                return
        if time.monotonic() > deadline:
            raise AssertionError(f"{device}:{port} on {branch} is not stamped after the latest checksum "
                                 f"{generated.isoformat()} a minute on: Infrahub no longer restamps a generation's "
                                 "new members (D-058's revisit)")
        time.sleep(0.5)


def branch_origin(branch: str) -> tuple[str, str]:
    """A branch's branched_from and created_at, read on main, verbatim."""
    [b] = graphql("main", "query { Branch(name: %s) { branched_from created_at } }" % json.dumps(branch))["Branch"]
    return b["branched_from"], b["created_at"]


def stage_reader() -> sr.StageReader:
    """The product's reader of the default branch, on the process's INFRAHUB_*."""
    return sr.StageReader(default_from_env())


def stamper() -> stages.Stamper:
    """The stamper the adapter's commands build: an intent client per (branch, at)."""
    return stages.stamper_of(default_from_env())


def resolve(ref: stages.Ref, scope: str = SCOPE):
    """One reference resolved by the adapter's nine steps, under the clock now."""
    return stages.resolve(stage_reader(), stamper(), packages.load(), ref, scope, datetime.now(UTC))


def find(branch: str, scope: str = SCOPE) -> stages.Change:
    ch, found = stages.find(stage_reader(), stamper(), branch, scope)
    assert ch is not None and not list(found), f"finding {branch}'s proposed change: {list(found)}"
    return ch


def refused(what: str, found, rule: str, *objects: str) -> list[str]:
    """Asserts the findings' rejections are each of rule at step resolve, on exactly objects in
    that order, and returns their messages (the Go tests' `refused`)."""
    got, messages = [], []
    for f in found:
        if f.severity != REJECTION:
            continue
        assert (f.rule, f.step) == (rule, stages.STEP_RESOLVE), (
            f"{what}: {f.rule} at step {f.step!r} on {f.object} ({f.message}); want {rule} at resolve")
        got.append(f.object)
        messages.append(f.message)
    assert got == list(objects), f"{what}: {rule} names {got}, want {list(objects)}"
    return messages


@dataclass
class Planned:
    """One stage as far as the plan got: its place in the listing, refused (the first
    rejection's rule) or compiled; the snapshot file the take wrote and the bundle the core
    compiled it to; and every finding."""

    stage: stages.Stage
    status: str
    rule: str = ""
    found: list = field(default_factory=list)
    resolved: stages.Resolved | None = None
    snapshot: dict | None = None
    path: Path | None = None
    bundle_id: str = ""
    counts: reading.Counts | None = None

    @property
    def outcome(self) -> tuple[str, str, str]:
        return (self.stage.label, self.status, self.rule)


PLAN_REFUSED = "refused"
PLAN_COMPILED = "compiled"


@dataclass
class Plan:
    """A stage plan of a proposed change made of the adapter's halves and the core's: each
    stage resolved and taken by the adapter, compiled by a core server, and each pair of
    consecutive compiled stages diffed by it. `steps` holds the `twin diff` step block of each
    pair, None where either side was refused."""

    change: stages.Change | None
    found: list
    stages: list[Planned]
    steps: list[dict | None]

    @property
    def outcomes(self) -> list[tuple[str, str, str]]:
        return [p.outcome for p in self.stages]


def plan_of(branch: str, core: "Core", out: Path, scope: str = SCOPE) -> Plan:
    """`stage plan` as the Go tests' planOf ran it: find the proposed change, then each of its
    stages in order resolved (steps 4–9), read at its at and taken, the take written under
    `out`, and compiled by the core, the first rejection of each ending it; then the step
    between each two consecutive compiled stages."""
    started = time.monotonic()
    reader, stamp, registry = stage_reader(), stamper(), packages.load()
    ch, found = stages.find(reader, stamp, branch, scope)
    if ch is None:
        return Plan(None, list(found), [], [])
    default = default_from_env()
    out.mkdir(parents=True, exist_ok=True)
    planned = []
    for i, st in enumerate(ch.stages):
        res, got = stages.resolve_from(reader, stamp, registry, ch, st.ref, datetime.now(UTC))
        if res is None:
            first = next(f for f in got if f.severity == REJECTION)
            planned.append(Planned(st, PLAN_REFUSED, first.rule, list(got)))
            continue
        client = Client(Config(address=default.config.address, token=default.config.token, branch=res.branch,
                               at=res.at))
        path = out / f"{i}-{st.label}.json"
        taken, read_found = reading.read_snapshot(client, scope, registry, [], None, path)
        all_found = list(got) + list(read_found)
        if taken is None:
            first = next(f for f in read_found if f.severity == REJECTION)
            planned.append(Planned(st, PLAN_REFUSED, first.rule, all_found, res))
            continue
        code, doc = core.compile(path, out / f"{i}-{st.label}.bundle")
        if code != 0:
            first = next(f for f in doc["findings"] if f["severity"] == REJECTION)
            planned.append(Planned(st, PLAN_REFUSED, first["rule"], all_found + doc["findings"], res, taken, path))
            continue
        planned.append(Planned(st, PLAN_COMPILED, "", all_found, res, taken, path, doc["bundle_id"],
                               reading.summarize(taken["ctm"])))
    steps = []
    for a, b in zip(planned, planned[1:], strict=False):
        if a.status != PLAN_COMPILED or b.status != PLAN_COMPILED:
            steps.append(None)
            continue
        code, doc = core.diff(a.path, b.path)
        assert code == 0, f"twin diff {a.stage.ref} → {b.stage.ref}: {doc}"
        steps.append(doc["step"])
    print(f"planned {branch} in {time.monotonic() - started:.1f}s: {len(planned)} stage(s), "
          f"{sum(s is not None for s in steps)} step(s)")
    return Plan(ch, list(found), planned, steps)


# The flows' harness (T028): each flow run in this process on Prefect's test harness, an
# ephemeral server under a home of the session's own, against a core server of the test's
# own, which reaches the host's Temporal dev server on :7233 (its default) and no Infrahub.

PLATFORM_STARTUP_S = 180
"""The harness's start-up bound: a first start in a fresh home took 10–40 s (research §5.17,
§5.19), past Prefect's 30 s default for the harness."""
USER_CHECKS_WAIT_S = 360
"""A creation's user checks' bound, as `internal/checks` bounds them (Go's creationChecksWait)."""
LOGIN_NAMES = ("FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD", "FYLGJA_EOS_USERNAME", "FYLGJA_EOS_PASSWORD")
"""The node logins' names, which the core's host check reads only as set or not."""


@pytest.fixture(scope="session")
def platform(tmp_path_factory):
    """`prefect_test_harness`: a temporary database and an ephemeral server for the session,
    under a PREFECT_HOME of its own, so a flow called here is a run recorded on it and its
    document the run's artifact. Its first start is timed (research §4, §5). It skips without
    Infrahub itself, since a session fixture sets up before the autouse skip, and the harness
    would start for a tier that runs nothing (`test_layout`'s skip case)."""
    require_infrahub()
    home = tmp_path_factory.mktemp("prefect-home")
    os.environ["PREFECT_HOME"] = str(home)
    os.environ.setdefault("PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL", "CRITICAL")
    from prefect.settings import PREFECT_HOME, temporary_settings
    from prefect.testing.utilities import prefect_test_harness

    started = time.monotonic()
    with temporary_settings(updates={PREFECT_HOME: home}), prefect_test_harness(PLATFORM_STARTUP_S):
        print(f"prefect_test_harness up in {time.monotonic() - started:.1f}s (PREFECT_HOME {home})")
        yield home


@dataclass
class Flows:
    """The flows' environment: the core of the test's own and the orchestrator's state root
    under the test's directory, and what the flows print."""

    core: Core
    root: Path
    out: list[str] = field(default_factory=list)
    markdown: list[str] = field(default_factory=list)
    """What the rehearse flow sent its markdown sink under `markdown=True`, as `--markdown`."""

    def run(self, flow, **params):
        """One flow called here, its out lines and markdown kept: its document and its time."""
        from fylgja_orchestrator.flows import common, twin_rehearse

        self.out.clear()
        self.markdown.clear()
        tokens = [(common.OUT, common.OUT.set(self.out.append)),
                  (twin_rehearse.MARKDOWN, twin_rehearse.MARKDOWN.set(self.markdown.append))]
        started = time.monotonic()
        try:
            doc = flow(**params)
        finally:
            for var, token in reversed(tokens):
                var.reset(token)
        took = time.monotonic() - started
        print(f"{flow.name} {params}: {doc.status} in {took:.1f}s")
        return doc, took

    def text(self) -> str:
        return "\n".join(self.out)


def use_core(monkeypatch, core: Core, root: Path) -> Flows:
    """The process's environment as a flow reads it (`Deps.from_env`): the test's core, an
    orchestrator root under root, the fixture's scope; no platform to reclaim against."""
    monkeypatch.setenv("FYLGJA_API_ADDRESS", core.address)
    monkeypatch.setenv("FYLGJA_API_TOKEN", core.token)
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_ROOT", str(root))
    monkeypatch.setenv("FYLGJA_DEFAULT_SCOPE", SCOPE)
    for name in ("PREFECT_API_URL", "PREFECT_API_AUTH_STRING"):
        monkeypatch.delenv(name, raising=False)
    return Flows(core, root)


def artifact_of(run_id: str) -> dict:
    """The document a flow run filed on the harness, as a check reads it: its artifact of
    type `fylgja-findings`, its `data` parsed."""
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.filters import ArtifactFilter, ArtifactFilterFlowRunId

    with get_client(sync_client=True) as client:
        of_run = ArtifactFilter(flow_run_id=ArtifactFilterFlowRunId(any_=[run_id]))
        found = client.read_artifacts(artifact_filter=of_run)
    [a] = [a for a in found if a.type == "fylgja-findings"]
    return json.loads(a.data) if isinstance(a.data, str) else a.data


def flow_runs_of(name: str) -> list:
    """Every run of the flow the harness recorded, newest first."""
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.filters import FlowFilter, FlowFilterName

    with get_client(sync_client=True) as client:
        return client.read_flow_runs(flow_filter=FlowFilter(name=FlowFilterName(any_=[name])))


def threads_of(change_id: str) -> list[list[str]]:
    """The proposed change's threads on main, each its comments' texts."""
    data = graphql("main", "query { CoreChangeThread(change__ids: [%s]) { edges { node { id "
                   "comments { edges { node { text { value } } } } } } } }" % json.dumps(change_id))
    return [[c["node"]["text"]["value"] for c in e["node"]["comments"]["edges"]]
            for e in data["CoreChangeThread"]["edges"]]


def check_definitions(branch: str = "main") -> list[dict]:
    """The check definitions a branch sees, each with its repository's id or None."""
    data = graphql(branch, "query { CoreCheckDefinition { edges { node { id name { value } "
                   "repository { node { id } } } } } }")
    return [{"id": e["node"]["id"], "name": e["node"]["name"]["value"],
             "repository": (e["node"]["repository"]["node"] or {}).get("id")}
            for e in data["CoreCheckDefinition"]["edges"]]


def user_validators(change_id: str) -> list[dict]:
    """The proposed change's user validators on main: each one's definition, state and
    conclusion."""
    data = graphql("main", "query { CoreUserValidator(proposed_change__ids: [%s]) { edges { node { "
                   "state { value } conclusion { value } check_definition { node { id name { value } } } } } } }"
                   % json.dumps(change_id))
    out = []
    for e in data["CoreUserValidator"]["edges"]:
        n = e["node"]
        d = n["check_definition"]["node"] or {}
        out.append({"definition": d.get("id"), "name": (d.get("name") or {}).get("value"),
                    "state": n["state"]["value"], "conclusion": n["conclusion"]["value"]})
    return out


def await_user_checks(branch: str, change_id: str, wait: float = USER_CHECKS_WAIT_S) -> list[dict]:
    """Polls until every check definition of a registered repository the branch sees has a
    user validator on the proposed change, completed (`AwaitUserChecks`): marked ready before
    the creation's fylgja-twin has read it as a draft, it would rehearse it on a twin."""
    defs = [d for d in check_definitions(branch) if d["repository"]]
    deadline = time.monotonic() + wait
    started = time.monotonic()
    while True:
        vs = {v["definition"]: v for v in user_validators(change_id)}
        pending = [f"{d['name']} {vs[d['id']]['state'] if d['id'] in vs else 'not started'}" for d in defs
                   if vs.get(d["id"], {}).get("state") != "completed"]
        if not pending:
            print(f"the creation's user checks concluded on {change_id} after {time.monotonic() - started:.0f}s: "
                  f"{sorted((v['name'], v['conclusion']) for v in vs.values())}")
            return list(vs.values())
        if time.monotonic() > deadline:
            raise AssertionError(f"proposed change {change_id}: user checks not concluded within {wait}s: {pending}")
        time.sleep(5)
