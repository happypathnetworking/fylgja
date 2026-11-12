"""The schema library, the group and this repository's registration on the development Infrahub's `main`.

Run by `make infrahub-register` as `core/.venv/bin/python infrahub/seed/register.py --ref <branch> --commit <hash>
--schema infrahub/schema/dcim --ctl <infrahubctl>`, with `local/.env` loaded (CONTRIBUTING.md, D-083):

- the library: loaded by `infrahubctl` where `main` holds none of its kinds, and waited for until `main` lists them
  all; a `main` holding part of it is refused with nothing written, since it is no state this target makes;
- the group `GROUP`, made where `main` has none;
- the registration `REPOSITORY`, a read-only repository of the main checkout's `.git` mounted at `LOCATION`: created
  where there is none, its `ref` updated where it names another, and its last commit imported where it reads
  another; then waited for until it reads `--commit`, `in-sync` and `online`, with the artifact definition
  `DEFINITION` on `main`;
- the tree of `--commit` on each running task worker of the Compose project `PROJECT`, read by `docker` as
  `GIT_DIRECTORY/<the registration's id>/commits/<the commit's 40 hex>`: a recreated worker holds no clone, and a user
  check run on it fails, so a worker without the commit's tree is not settled. Where one lacks it, the import is
  asked, at once where this run sent nothing and else once `CLONE_ASK_S` have passed, and again every `CLONE_ASK_S`
  until each holds it, within `CLONE_WAIT_S`: an import with no new commit clones on the one worker that runs it, and
  after an import of a new commit each worker held the tree by an import or a pull of its own, Infrahub's fetch to
  each worker beginning after.

A registration already there and settled, its commit's tree on each worker, is sent nothing.

A branch's name, `phase-8/2-infrahub-seed` among them, registers from the mount, an import follows the branch moved
forwards or backwards, `commit` follows a `ref` changed by an update and an import, and the clones are made as above
(design/verified-facts.md, "Infrahub 1.11.11"). Exit 0; 1 for a refusal or a failure said on stderr; 2 for a command
line not understood or a variable not set.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from hub import Hub, HubError, Run, connect, wait_until

GROUP = "fylgja-devices"
"""The group whose members the artifact definition renders (`.infrahub.yml`)."""

REPOSITORY = "fylgja"
"""The `CoreReadOnlyRepository` this repository is registered as."""

LOCATION = "/srv/fylgja"
"""Where the task workers mount the main checkout's `.git`, read-only (`infrahub/dev/compose.override.yml`)."""

DEFINITION = "device-config"
"""The artifact definition an import of this repository makes (`.infrahub.yml`)."""

SCHEMA_WAIT_S = 120
"""How long `main` is read for the library's kinds once the load has returned: the kinds were listed 14.9 s after
`infrahubctl` gave up on a first load the server finished (design/verified-facts.md, "Infrahub 1.11.11")."""

IMPORT_WAIT_S = 300
"""How long the registration is read until it settles: a first import read `online` 80.3 s after its create was
sent (design/verified-facts.md, "Infrahub 1.11.11")."""

PROJECT = "fylgja-core-infrahub"
"""The development Infrahub's Compose project (`scripts/infrahub_dev.py`'s `PROJECT`), whose task workers are read."""

GIT_DIRECTORY = "/opt/infrahub/git"
"""Where a task worker keeps its clones, one directory a registration, named by its id (the published Compose file's
`INFRAHUB_GIT_REPOSITORIES_DIRECTORY`)."""

CLONE_ASK_S = 30
"""Seconds between two imports asked while a worker lacks the commit's tree. A worker held the tree 1.7 to 2.8 s after
an import's or a pull's flow began on it, the first import's flow 17.1 to 20.8 s after it was asked or its target
began; after a new commit's import the other worker held it 8.7 s after the first (design/verified-facts.md,
"Infrahub 1.11.11")."""

CLONE_WAIT_S = 300
"""How long the trees are waited for once the registration has settled: no reading is begun at or past it."""

CLONE_POLL_S = 2.0
"""Seconds between two readings of the workers' clones."""

DOCKER_TIMEOUT_S = 30
"""Seconds each `docker` command is given."""

COMMIT_FORM = re.compile(r"[0-9a-f]{40}")

GROUP_COUNT = "query ($name: String!) { CoreStandardGroup(name__value: $name) { count } }"
GROUP_CREATE = "mutation ($name: String!) { CoreStandardGroupCreate(data: {name: {value: $name}}) { ok } }"
REPOSITORY_READ = """
query ($name: String!) {
  CoreReadOnlyRepository(name__value: $name) {
    count
    edges { node { id ref { value } commit { value } sync_status { value } operational_status { value } } }
  }
}
"""
DEFINITION_COUNT = "query ($name: String!) { CoreArtifactDefinition(name__value: $name) { count } }"
REPOSITORY_CREATE = """
mutation ($name: String!, $location: String!, $ref: String!) {
  CoreReadOnlyRepositoryCreate(data: {name: {value: $name}, location: {value: $location}, ref: {value: $ref}}) {
    ok
    object { id }
  }
}
"""
REPOSITORY_UPDATE = """
mutation ($id: String!, $ref: String!) { CoreReadOnlyRepositoryUpdate(data: {id: $id, ref: {value: $ref}}) { ok } }
"""
IMPORT = "mutation ($id: String!) { InfrahubReadOnlyRepositoryImportLastCommit(data: {id: $id}) { ok } }"


def say(line: str) -> None:
    print(f"register: {line}", flush=True)


@dataclass(frozen=True)
class Repository:
    """The registration as `main` reads it."""

    id: str
    ref: str | None
    commit: str | None
    sync_status: str | None
    operational_status: str | None


def file_kinds(path: Path) -> frozenset[str]:
    """Every kind the schema file `path` defines: the namespace and name of each entry of its `nodes` and
    `generics`."""
    content = yaml.safe_load(path.read_text()) or {}
    return frozenset(
        entry["namespace"] + entry["name"] for section in ("nodes", "generics") for entry in content.get(section) or []
    )


def library_kinds(schema: Path) -> tuple[str, ...]:
    """Every kind the library's files define, sorted: the namespace and name of each entry of their `nodes` and
    `generics`. Only the `.yml` files are read; the licence and `COMMIT` beside them are not schema."""
    return tuple(sorted({kind for path in sorted(schema.glob("*.yml")) for kind in file_kinds(path)}))


def main_kinds(hub: Hub) -> frozenset[str]:
    """Every kind `main`'s schema lists, nodes and generics, as the namespace and the name."""
    schema = hub.rest("GET", "/api/schema", params={"branch": "main"}).json()
    return frozenset(
        entry["namespace"] + entry["name"] for section in ("nodes", "generics") for entry in schema.get(section, [])
    )


@dataclass(frozen=True)
class Loaded:
    """A schema load on `main`: the kinds `main` listed once it listed every kind wanted, how long `infrahubctl` took
    to return after the load was sent, and how long `main` took to list them after that."""

    held: frozenset[str]
    returned_s: float
    listed_s: float


def load_schema(
    hub: Hub,
    path: Path,
    wanted: Sequence[str],
    *,
    what: str,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> Loaded:
    """`path`, a schema file or a directory of them, loaded on `main` by `infrahubctl`, and `main` read until it lists
    each of `wanted`, within `SCHEMA_WAIT_S`; a `HubError` naming `what` and the kinds not listed where it does not."""
    started = clock()
    hub.ctl("schema", "load", str(path), "--branch", "main")
    returned = clock()
    held = wait_until(
        lambda: main_kinds(hub),
        lambda held: [kind for kind in wanted if kind not in held],
        what=what,
        timeout_s=SCHEMA_WAIT_S,
        clock=clock,
        sleep=sleep,
    )
    return Loaded(held, returned - started, clock() - returned)


def load_library(hub: Hub, schema: Path, *, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
    wanted = library_kinds(schema)
    held = main_kinds(hub)
    missing = [kind for kind in wanted if kind not in held]
    if not missing:
        say(f"main holds the schema library's {len(wanted)} kinds already")
        return
    if len(missing) < len(wanted):
        raise HubError(
            f"main holds part of the schema library and lacks {', '.join(missing)}: no state this target makes; "
            "start from an empty instance with make infrahub-down PURGE=1 and make infrahub-up"
        )
    say(f"main holds none of the schema library's {len(wanted)} kinds; loading {schema}")
    loaded = load_schema(hub, schema, wanted, what="the schema library's kinds on main", clock=clock, sleep=sleep)
    say(
        f"the schema library's {len(wanted)} kinds are on main: infrahubctl returned {loaded.returned_s:.0f} s "
        f"after the load was sent, and main listed them {loaded.listed_s:.0f} s after that"
    )


def ensure_group(hub: Hub) -> None:
    if hub.gql("main", GROUP_COUNT, {"name": GROUP})["CoreStandardGroup"]["count"]:
        say(f"main holds the group {GROUP} already")
        return
    done(hub.gql("main", GROUP_CREATE, {"name": GROUP}), "CoreStandardGroupCreate", f"making the group {GROUP}")
    say(f"made the group {GROUP}")


def done(data: dict[str, object], mutation: str, what: str) -> dict[str, object]:
    answer = data.get(mutation)
    if not isinstance(answer, dict) or answer.get("ok") is not True:
        raise HubError(f"{what}: {mutation} answered no ok")
    return answer


def repository(hub: Hub) -> Repository | None:
    edges = hub.gql("main", REPOSITORY_READ, {"name": REPOSITORY})["CoreReadOnlyRepository"]["edges"]
    if not edges:
        return None
    node = edges[0]["node"]
    return Repository(
        id=node["id"],
        ref=node["ref"]["value"],
        commit=node["commit"]["value"],
        sync_status=node["sync_status"]["value"],
        operational_status=node["operational_status"]["value"],
    )


Clones = Callable[[str, str], dict[str, bool]]
"""Each running task worker, by its container's name, and whether it holds the tree of the commit it is given of the
registration whose id it is given."""


def docker(argv: list[str], run: Run) -> subprocess.CompletedProcess[str]:
    """One `docker` command, its output captured; one not answered within `DOCKER_TIMEOUT_S` is a `HubError`."""
    try:
        return run(argv, capture_output=True, text=True, check=False, timeout=DOCKER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise HubError(f"`{' '.join(argv[:3])}` did not answer within {DOCKER_TIMEOUT_S} s") from None


def worker_clones(repository_id: str, commit: str, *, run: Run = subprocess.run) -> dict[str, bool]:
    """The Compose project's running task workers, by their labels, each with whether
    `GIT_DIRECTORY/<repository_id>/commits/<commit>` is a directory in it; a `docker` command that fails is a
    `HubError`."""
    listed = docker(
        [
            "docker", "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--filter", "label=com.docker.compose.service=task-worker", "--format", "{{.Names}}",
        ],
        run,
    )
    if listed.returncode != 0:
        raise HubError(f"`docker ps` exited {listed.returncode}, so the task workers' clones cannot be read")
    held: dict[str, bool] = {}
    for worker in sorted(listed.stdout.split()):
        tree = f"{GIT_DIRECTORY}/{repository_id}/commits/{commit}"
        found = docker(["docker", "exec", worker, "test", "-d", tree], run)
        if found.returncode not in (0, 1):
            raise HubError(f"`docker exec {worker}` exited {found.returncode}, so its clone cannot be read")
        held[worker] = found.returncode == 0
    return held


def cloned(
    hub: Hub,
    repository_id: str,
    commit: str,
    *,
    asked: bool,
    clones: Clones,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    """Each task worker holding the tree of `commit`, the import asked while one lacks it, as the module says; `asked`
    where this run has sent an import or a create already, whose own trees are waited for first."""
    started = clock()
    last = started if asked else None
    imports = 0
    at = f"{REPOSITORY} at {short(commit)}"
    while True:
        held = clones(repository_id, commit)
        if not held:
            raise HubError(
                f"no task worker of the Compose project {PROJECT} is running: start it with make infrahub-up"
            )
        lacking = [worker for worker, has in held.items() if not has]
        if not lacking:
            say(f"each of the {len(held)} task workers holds the tree of {at}, {clock() - started:.0f} s on")
            return
        waited = clock() - started
        if waited + CLONE_POLL_S >= CLONE_WAIT_S:
            raise HubError(
                f"{', '.join(lacking)} held no tree of {at} within {CLONE_WAIT_S} s, {imports} imports asked: "
                f"read {GIT_DIRECTORY} in {'it' if len(lacking) == 1 else 'each'} and Infrahub's task log; "
                "run make infrahub-register again"
            )
        if last is None or clock() - last >= CLONE_ASK_S:
            answer = hub.gql("main", IMPORT, {"id": repository_id})
            done(answer, "InfrahubReadOnlyRepositoryImportLastCommit", "importing")
            imports += 1
            last = clock()
            say(
                f"{', '.join(lacking)} {'holds' if len(lacking) == 1 else 'hold'} no tree of {at}: asked an import, "
                "which gives it to the worker that runs it"
            )
        sleep(CLONE_POLL_S)


def definitions(hub: Hub) -> int:
    count: int = hub.gql("main", DEFINITION_COUNT, {"name": DEFINITION})["CoreArtifactDefinition"]["count"]
    return count


def register(
    hub: Hub,
    *,
    ref: str,
    commit: str,
    schema: Path,
    clones: Clones,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """The library, the group and the registration on `main`, the registration settled at `commit` of `ref` and its
    tree on each task worker `clones` reads."""
    load_library(hub, schema, clock=clock, sleep=sleep)
    ensure_group(hub)
    found = repository(hub)
    started = clock()
    asked = True
    if found is None:
        answer = done(
            hub.gql("main", REPOSITORY_CREATE, {"name": REPOSITORY, "location": LOCATION, "ref": ref}),
            "CoreReadOnlyRepositoryCreate",
            f"registering {REPOSITORY}",
        )
        made = answer.get("object")
        made_id = made.get("id") if isinstance(made, dict) else None
        say(f"registered {REPOSITORY} from {LOCATION} at {ref}, id {made_id}")
    elif found.ref != ref:
        done(
            hub.gql("main", REPOSITORY_UPDATE, {"id": found.id, "ref": ref}),
            "CoreReadOnlyRepositoryUpdate",
            f"moving {REPOSITORY} from {found.ref} to {ref}",
        )
        done(hub.gql("main", IMPORT, {"id": found.id}), "InfrahubReadOnlyRepositoryImportLastCommit", "importing")
        say(f"moved {REPOSITORY} from {found.ref} to {ref}, and asked its last commit's import")
    elif found.commit != commit:
        done(hub.gql("main", IMPORT, {"id": found.id}), "InfrahubReadOnlyRepositoryImportLastCommit", "importing")
        say(f"{REPOSITORY} reads {short(found.commit)}; asked the import of {ref}'s last commit")
    else:
        asked = False
        say(f"{REPOSITORY} reads {ref} at {short(commit)} already")

    def pending(reading: tuple[Repository | None, int]) -> list[str]:
        state, count = reading
        if state is None:
            return [f"no repository {REPOSITORY}"]
        if state.operational_status == "error":
            raise HubError(
                f"the repository {REPOSITORY} at {ref} reads operational_status error: read the import's task in "
                "Infrahub's task log"
            )
        reasons = []
        if state.commit != commit:
            reasons.append(f"commit {short(state.commit)}, not {short(commit)}")
        if state.sync_status != "in-sync":
            reasons.append(f"sync_status {state.sync_status}")
        if state.operational_status != "online":
            reasons.append(f"operational_status {state.operational_status}")
        if count != 1:
            reasons.append(f"{count} artifact definitions {DEFINITION}")
        return reasons

    settled, _ = wait_until(
        lambda: (repository(hub), definitions(hub)),
        pending,
        what=f"the repository {REPOSITORY} in sync at {ref}'s {short(commit)}",
        timeout_s=IMPORT_WAIT_S,
        clock=clock,
        sleep=sleep,
    )
    say(f"{REPOSITORY} reads {ref} at {short(commit)}, in-sync and online, {clock() - started:.0f} s on")
    assert settled is not None, "a settled reading names the repository"
    cloned(hub, settled.id, commit, asked=asked, clones=clones, clock=clock, sleep=sleep)


def short(commit: str | None) -> str:
    return commit[:7] if commit else "no commit"


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="register.py", description=(__doc__ or "").splitlines()[0])
    made.add_argument("--ref", required=True, help="the branch registered, as the mounted .git names it")
    made.add_argument("--commit", required=True, help="its commit, the 40 hex characters the import must read")
    made.add_argument("--schema", type=Path, required=True, help="the schema library's directory")
    made.add_argument("--ctl", type=Path, required=True, help="infrahubctl, in a venv of its own")
    return made


def main(argv: Sequence[str]) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    if not args.ref:
        print("register: --ref is empty", file=sys.stderr)
        return 2
    if not COMMIT_FORM.fullmatch(args.commit):
        print(f"register: --commit {args.commit!r} is not a commit's 40 hex characters", file=sys.stderr)
        return 2
    try:
        hub = connect(os.environ, ctl=args.ctl)
    except HubError as e:
        print(f"register: {e}", file=sys.stderr)
        return 2
    try:
        register(hub, ref=args.ref, commit=args.commit, schema=args.schema, clones=worker_clones)
    except (HubError, OSError, yaml.YAMLError) as e:
        print(f"register: {e}", file=sys.stderr)
        return 1
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
