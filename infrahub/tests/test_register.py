"""`infrahub/seed/register.py`: the schema library, the group and this repository's registration on `main`.

Infrahub is a fake behind `httpx.MockTransport` that answers each GraphQL operation by its root field, `infrahubctl`
a fake `run`, and the clock a fake: nothing here opens a socket or starts a process.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import register
import yaml
from hub import Hub, HubError, connect

HOST = "infrahub.example"
ADDRESS = f"http://{HOST}"
CTL = Path("/opt/example/bin/infrahubctl")
REF = "phase-8/2-infrahub-seed"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
OLD = "fedcba9876543210fedcba9876543210fedcba98"
ID = "18e6777d-d2eb-35cb-3349-c51655b03250"

LIBRARY = {
    "dcim.yml": {
        "version": "1.0",
        "generics": [{"namespace": "Dcim", "name": "Endpoint"}],
        "nodes": [{"namespace": "Dcim", "name": "Device"}],
    },
    "cable.yml": {"version": "1.0", "nodes": [{"namespace": "Dcim", "name": "Cable"}]},
}
KINDS = [("Dcim", "Cable"), ("Dcim", "Device"), ("Dcim", "Endpoint")]
BUILTIN = [("Builtin", "Tag"), ("Core", "StandardGroup")]

SETTLED = {"commit": COMMIT, "sync_status": "in-sync", "operational_status": "online"}
FIELDS = ("ref", "commit", "sync_status", "operational_status")
"""What the fake answers of the repository, each as `{"value": …}`."""


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from an environment of its own, `PATH` alone, so none holds the developer's (a shell may
    have `local/.env` loaded) where an assertion or a local could show it."""
    path = os.environ.get("PATH", "")
    for name in list(os.environ):
        if name != "PYTEST_CURRENT_TEST":
            monkeypatch.delenv(name)
    monkeypatch.setenv("PATH", path)


@pytest.fixture
def schema(tmp_path: Path) -> Path:
    """A library of two files and three kinds, with a licence and a commit beside them, as the vendored one has."""
    library = tmp_path / "dcim"
    library.mkdir()
    for name, content in LIBRARY.items():
        (library / name).write_text(yaml.safe_dump(content))
    (library / "LICENSE.txt").write_text("Apache License\n")
    (library / "COMMIT").write_text(f"{OLD}\n")
    return library


class Clock:
    """A clock that moves only when its `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class Infrahub:
    """`main` as Infrahub answers it: the schema's kinds, the group's count, the repository and the definitions.

    `progress` is what the repository reads after a create, an update or an import: one entry a read, the last kept.
    `schema_reads` is how many reads of the schema after a load still list none of the library.
    """

    def __init__(
        self,
        *,
        kinds: list[tuple[str, str]],
        groups: int = 1,
        repository: dict[str, Any] | None = None,
        definitions: int = 1,
        progress: list[dict[str, Any]] | None = None,
        schema_reads: int = 1,
    ) -> None:
        self.kinds = [*BUILTIN, *kinds]
        self.groups = groups
        self.repository = repository
        self.definitions = definitions
        self.progress = progress or [SETTLED]
        self.moving: list[dict[str, Any]] = []
        self.schema_reads = schema_reads
        self.loaded = False
        self.mutations: list[tuple[str, dict[str, Any]]] = []
        self.reads: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/schema":
            assert request.url.params["branch"] == "main"
            self.reads.append("schema")
            if self.loaded:
                if self.schema_reads:
                    self.schema_reads -= 1
                else:
                    self.kinds = [*BUILTIN, *KINDS]
            entries = [{"namespace": namespace, "name": name} for namespace, name in self.kinds]
            return httpx.Response(200, json={"main": "a-hash", "nodes": entries[1:], "generics": entries[:1]})
        assert request.url.path == "/graphql/main"
        body = json.loads(request.content)
        found = re.search(r"\{\s*(\w+)", body["query"])
        assert found
        root = found[1]
        if body["query"].lstrip().startswith("mutation"):
            self.mutations.append((root, body["variables"]))
        else:
            self.reads.append(root)
        answer: dict[str, Any] = getattr(self, root)(body["variables"])
        return httpx.Response(200, json={"data": {root: answer}})

    def CoreStandardGroup(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables == {"name": "fylgja-devices"}
        return {"count": self.groups}

    def CoreStandardGroupCreate(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.groups += 1
        return {"ok": True}

    def CoreReadOnlyRepository(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables == {"name": "fylgja"}
        if self.repository is None:
            return {"count": 0, "edges": []}
        if self.moving:
            self.repository |= self.moving.pop(0) if len(self.moving) > 1 else self.moving[0]
        node = {"id": self.repository["id"]}
        node |= {field: {"value": self.repository.get(field)} for field in FIELDS}
        return {"count": 1, "edges": [{"node": node}]}

    def CoreArtifactDefinition(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert variables == {"name": "device-config"}
        return {"count": self.definitions}

    def CoreReadOnlyRepositoryCreate(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.repository = {"id": ID, "ref": variables["ref"], "commit": None, "sync_status": "unknown",
                           "operational_status": "unknown"}
        self.moving = list(self.progress)
        return {"ok": True, "object": {"id": ID}}

    def CoreReadOnlyRepositoryUpdate(self, variables: dict[str, Any]) -> dict[str, Any]:
        assert self.repository is not None
        self.repository["ref"] = variables["ref"]
        return {"ok": True}

    def InfrahubReadOnlyRepositoryImportLastCommit(self, variables: dict[str, Any]) -> dict[str, Any]:
        self.moving = list(self.progress)
        return {"ok": True}


class Ctl:
    """`infrahubctl`'s fake: each argument list kept; a schema load marks the fake Infrahub loaded."""

    def __init__(self, infrahub: Infrahub) -> None:
        self.infrahub = infrahub
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[1:3] == ["schema", "load"]:
            self.infrahub.loaded = True
        return subprocess.CompletedProcess(argv, 0, stdout="")


def hub_for(infrahub: Infrahub) -> tuple[Hub, Ctl]:
    ctl = Ctl(infrahub)
    environ = {"FYLGJA_INFRAHUB_ADDRESS": ADDRESS, "FYLGJA_INFRAHUB_WRITE_TOKEN": "a-tests-token"}
    return connect(environ, ctl=CTL, transport=httpx.MockTransport(infrahub), run=ctl), ctl


def registered(**fields: Any) -> dict[str, Any]:
    return {"id": ID, "ref": REF} | SETTLED | fields


WORKERS = ("fylgja-core-infrahub-task-worker-1", "fylgja-core-infrahub-task-worker-2")


def everywhere(repository_id: str, commit: str) -> dict[str, bool]:
    """Each task worker holding the tree of the registration's commit."""
    assert (repository_id, commit) == (ID, COMMIT)
    return dict.fromkeys(WORKERS, True)


class Workers:
    """The task workers' trees of the registration's commits, `<id>/commits/<commit>`, as Infrahub's runs leave them
    (design/verified-facts.md, "Infrahub 1.11.11"): an import gives the commit the registration then reads to the one
    worker that runs it, `lands` naming that worker for each import in turn; and with `broadcast_at`, every worker holds
    it from that time on, as the fetch Infrahub sends to each worker after a new commit's import makes. `held` is what
    each worker holds before, by commit."""

    def __init__(
        self,
        infrahub: Infrahub,
        clock: Clock,
        *,
        lands: tuple[str, ...] = (),
        held: dict[str, set[str]] | None = None,
        broadcast_at: float | None = None,
    ) -> None:
        self.infrahub = infrahub
        self.clock = clock
        self.lands = lands
        self.held = {worker: set((held or {}).get(worker, set())) for worker in WORKERS}
        self.broadcast_at = broadcast_at
        self.given = 0

    def __call__(self, repository_id: str, commit: str) -> dict[str, bool]:
        assert repository_id == ID
        assert self.infrahub.repository is not None
        reads = self.infrahub.repository["commit"]
        imports = [name for name, _ in self.infrahub.mutations if name == "InfrahubReadOnlyRepositoryImportLastCommit"]
        for worker in self.lands[self.given : len(imports)]:
            self.held[worker].add(reads)
        self.given = max(self.given, min(len(imports), len(self.lands)))
        if self.broadcast_at is not None and self.clock.now >= self.broadcast_at:
            for worker in WORKERS:
                self.held[worker].add(reads)
        return {worker: commit in self.held[worker] for worker in WORKERS}


IMPORT = ("InfrahubReadOnlyRepositoryImportLastCommit", {"id": ID})


def test_library_kinds_are_the_files_nodes_and_generics_sorted(schema: Path) -> None:
    assert register.library_kinds(schema) == ("DcimCable", "DcimDevice", "DcimEndpoint")


def test_the_library_is_loaded_only_where_main_holds_none_of_it(schema: Path) -> None:
    held = Infrahub(kinds=KINDS, repository=registered())
    hub, ctl = hub_for(held)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert ctl.calls == []
    assert held.mutations == []

    empty = Infrahub(kinds=[], repository=registered(), schema_reads=2)
    hub, ctl = hub_for(empty)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert ctl.calls == [[str(CTL), "schema", "load", str(schema), "--branch", "main"]]
    assert empty.reads.count("schema") == 4
    assert clock.slept == [2.0, 2.0]


def test_a_main_holding_part_of_the_library_is_refused(schema: Path) -> None:
    infrahub = Infrahub(kinds=[("Dcim", "Device"), ("Dcim", "Endpoint")], groups=0)
    hub, ctl = hub_for(infrahub)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert "DcimCable" in str(raised.value)
    assert "DcimDevice" not in str(raised.value)
    assert "make infrahub-down PURGE=1" in str(raised.value)
    assert infrahub.mutations == []
    assert ctl.calls == []


def test_the_group_is_made_once(schema: Path) -> None:
    none = Infrahub(kinds=KINDS, groups=0, repository=registered())
    hub, _ = hub_for(none)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert none.mutations == [("CoreStandardGroupCreate", {"name": "fylgja-devices"})]

    one = Infrahub(kinds=KINDS, groups=1, repository=registered())
    hub, _ = hub_for(one)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert one.mutations == []


def test_a_first_registration_is_created_and_waited_for(schema: Path) -> None:
    infrahub = Infrahub(
        kinds=KINDS,
        definitions=0,
        progress=[
            {"commit": None, "sync_status": "unknown"},
            {"commit": COMMIT, "sync_status": "syncing"},
            {"sync_status": "in-sync"},
            {"operational_status": "online"},
        ],
    )
    hub, _ = hub_for(infrahub)
    clock = Clock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= 8:
            infrahub.definitions = 1

    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=sleep)
    assert infrahub.mutations == [
        ("CoreReadOnlyRepositoryCreate", {"name": "fylgja", "location": "/srv/fylgja", "ref": REF}),
    ]
    assert infrahub.repository == {"id": ID, "ref": REF} | SETTLED
    assert clock.now == 8


def test_a_registration_already_there_imports_its_last_commit(schema: Path) -> None:
    infrahub = Infrahub(
        kinds=KINDS,
        repository=registered(commit=OLD),
        progress=[{"sync_status": "syncing"}, {"commit": COMMIT, "sync_status": "in-sync"}],
    )
    hub, _ = hub_for(infrahub)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert infrahub.mutations == [("InfrahubReadOnlyRepositoryImportLastCommit", {"id": ID})]
    assert infrahub.repository is not None
    assert infrahub.repository["commit"] == COMMIT
    assert clock.slept == [2.0]

    there = Infrahub(kinds=KINDS, repository=registered())
    hub, _ = hub_for(there)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert there.mutations == []


def test_another_ref_is_what_step_1_showed(schema: Path) -> None:
    """Read on 1.11.11 (design/verified-facts.md): `commit` follows a `ref` changed by the update and an import."""
    infrahub = Infrahub(
        kinds=KINDS,
        repository=registered(ref="phase-8/1-base-install", commit=OLD),
        progress=[{"sync_status": "syncing"}, {"commit": COMMIT, "sync_status": "in-sync"}],
    )
    hub, _ = hub_for(infrahub)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert infrahub.mutations == [
        ("CoreReadOnlyRepositoryUpdate", {"id": ID, "ref": REF}),
        ("InfrahubReadOnlyRepositoryImportLastCommit", {"id": ID}),
    ]
    assert infrahub.repository == {"id": ID, "ref": REF} | SETTLED


def test_an_import_that_errors_ends_at_once_and_one_that_never_syncs_at_its_bound(schema: Path) -> None:
    errs = Infrahub(kinds=KINDS, repository=None, progress=[{"operational_status": "error"}])
    hub, _ = hub_for(errs)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert REF in str(raised.value)
    assert "operational_status error" in str(raised.value)
    assert clock.slept == []

    stuck = Infrahub(kinds=KINDS, repository=None, progress=[{"commit": COMMIT, "sync_status": "syncing"}])
    hub, _ = hub_for(stuck)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert str(raised.value).endswith("not within 300 s: sync_status syncing, operational_status unknown")
    assert clock.now == register.IMPORT_WAIT_S


def test_a_settled_registration_on_workers_holding_no_clone_is_imported_until_each_holds_one(
    schema: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Read on 1.11.11 (design/verified-facts.md): a recreated task worker holds no clone, and an import with no new
    commit clones on the one worker that runs it; so the import is asked again, `CLONE_ASK_S` apart, until each holds
    one. The first is asked at once: a settled registration was sent nothing that would clone."""
    infrahub = Infrahub(kinds=KINDS, repository=registered())
    hub, _ = hub_for(infrahub)
    clock = Clock()
    workers = Workers(infrahub, clock, lands=(WORKERS[0], WORKERS[0], WORKERS[1]), held={WORKERS[1]: {OLD}})
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=workers, clock=clock, sleep=clock.sleep)
    assert infrahub.mutations == [IMPORT, IMPORT, IMPORT]
    assert clock.now == 2 * register.CLONE_ASK_S + register.CLONE_POLL_S
    said = capsys.readouterr().out
    assert f"{WORKERS[1]} holds no tree of fylgja at 0123456" in said
    assert f"each of the 2 task workers holds the tree of fylgja at 0123456, {clock.now:.0f} s on" in said

    held = Infrahub(kinds=KINDS, repository=registered())
    hub, _ = hub_for(held)
    clock = Clock()
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=everywhere, clock=clock, sleep=clock.sleep)
    assert held.mutations == []
    assert clock.slept == []


def test_after_a_new_commits_import_the_workers_fetch_is_waited_for_before_another(schema: Path) -> None:
    """Read on 1.11.11: after an import of a new commit Infrahub sends each other worker a fetch, which clones the
    registration where it holds none, seconds after the import has settled; no import more is asked meanwhile."""
    infrahub = Infrahub(
        kinds=KINDS,
        repository=registered(commit=OLD),
        progress=[{"sync_status": "syncing"}, {"commit": COMMIT, "sync_status": "in-sync"}],
    )
    hub, _ = hub_for(infrahub)
    clock = Clock()
    old = {worker: {OLD} for worker in WORKERS}
    workers = Workers(infrahub, clock, lands=(WORKERS[0],), held=old, broadcast_at=16.0)
    register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=workers, clock=clock, sleep=clock.sleep)
    assert infrahub.mutations == [IMPORT]
    assert clock.now == 16.0


def test_no_task_worker_or_one_never_cloned_is_refused(schema: Path) -> None:
    none = Infrahub(kinds=KINDS, repository=registered())
    hub, _ = hub_for(none)
    clock = Clock()
    with pytest.raises(HubError) as raised:
        register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=lambda _, __: {}, clock=clock,
                          sleep=clock.sleep)
    assert str(raised.value) == (
        "no task worker of the Compose project fylgja-core-infrahub is running: start it with make infrahub-up"
    )
    assert none.mutations == []

    never = Infrahub(kinds=KINDS, repository=registered())
    hub, _ = hub_for(never)
    clock = Clock()
    workers = Workers(never, clock, lands=(WORKERS[0],) * 20)
    with pytest.raises(HubError) as raised:
        register.register(hub, ref=REF, commit=COMMIT, schema=schema, clones=workers, clock=clock, sleep=clock.sleep)
    assert str(raised.value) == (
        f"{WORKERS[1]} held no tree of fylgja at 0123456 within {register.CLONE_WAIT_S} s, "
        f"{len(never.mutations)} imports asked: read /opt/infrahub/git in it and Infrahub's task log; "
        "run make infrahub-register again"
    )
    assert clock.now == register.CLONE_WAIT_S - register.CLONE_POLL_S
    assert len(never.mutations) == register.CLONE_WAIT_S // register.CLONE_ASK_S


def test_a_workers_clone_is_read_in_its_git_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The task workers are the Compose project's running `task-worker` containers, by their labels, and a worker holds
    the registration at a commit where `/opt/infrahub/git/<the registration's id>/commits/<the commit's 40 hex>` is a
    directory in it, the tree Infrahub checks the commit out in (design/verified-facts.md, "Infrahub 1.11.11")."""
    import infrahub_dev

    assert register.PROJECT == infrahub_dev.PROJECT
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        assert kwargs == {"capture_output": True, "text": True, "check": False, "timeout": register.DOCKER_TIMEOUT_S}
        if argv[1] == "ps":
            return subprocess.CompletedProcess(argv, 0, stdout=f"{WORKERS[1]}\n{WORKERS[0]}\n")
        return subprocess.CompletedProcess(argv, 0 if argv[2] == WORKERS[0] else 1, stdout="")

    assert register.worker_clones(ID, COMMIT, run=run) == {WORKERS[0]: True, WORKERS[1]: False}
    assert calls == [
        [
            "docker", "ps", "--filter", "label=com.docker.compose.project=fylgja-core-infrahub",
            "--filter", "label=com.docker.compose.service=task-worker", "--format", "{{.Names}}",
        ],
        ["docker", "exec", WORKERS[0], "test", "-d", f"/opt/infrahub/git/{ID}/commits/{COMMIT}"],
        ["docker", "exec", WORKERS[1], "test", "-d", f"/opt/infrahub/git/{ID}/commits/{COMMIT}"],
    ]

    def refused(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Cannot connect to the Docker daemon")

    with pytest.raises(HubError) as raised:
        register.worker_clones(ID, COMMIT, run=refused)
    assert str(raised.value) == "`docker ps` exited 1, so the task workers' clones cannot be read"


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        ([], "the following arguments are required"),
        (["--ref", REF, "--commit", "831630f", "--schema", "d", "--ctl", "c"], "--commit"),
        (["--ref", REF, "--commit", COMMIT, "--schema", "d", "--ctl", "c"], "FYLGJA_INFRAHUB_ADDRESS is not set"),
    ],
    ids=["no-arguments", "a-short-commit", "no-address"],
)
def test_a_command_line_not_understood_or_a_variable_not_set_is_exit_2(
    argv: list[str], says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert register.main(argv) == 2
    assert says in capsys.readouterr().err
