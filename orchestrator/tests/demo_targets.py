"""The make targets a demonstration runs, faked beside the fake host: `Targets`, which answers each target on a
`demo_host.FakeHost` by what the real one leaves, with the core's start, its CLI, `edge_dev.py` and Prefect's
deployments; `first`, a host on which no demonstration has run; and the names and helpers they and the tests of
`scripts/demo.py` share. Nothing here starts a process, opens a socket or sleeps. What a target writes into
`local/.env` is written by its own development script's function, each script loaded by its path, as `make` runs
it; every other secret is the tests' own."""

from __future__ import annotations

import copy
import functools
import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from demo_host import (
    MAIN,
    NODE_PASSWORD,
    NODE_USER,
    ROOT,
    FakeHost,
    Ran,
    Started,
    demo,
    is_a_core,
    meminfo,
    passing,
    same,
)
from test_formats import full_plan, full_rehearsal, minimal_rehearsal

SHELL = {"PATH": "/usr/bin", "HOME": "/srv/example/home"}
"""The shell's environment, which `local/.env` is laid over."""


def by_path(name: str) -> ModuleType:
    """Another development script, loaded by its path as `make` runs it, to hold this one's values to."""
    spec = importlib.util.spec_from_file_location(f"{name}_beside_demo", ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PYTHON = str(demo.VENV / "bin" / "python3")
"""The venv's interpreter, which `/proc` shows first for each of the venv's commands, a `#!` script."""

CORE, CLI = str(demo.CORE), str(demo.CLI)
RUNNER = str(demo.VENV / "bin" / "fylgja-orchestrator")
BIND = "192.0.2.1"
API = f"http://{BIND}:4200/api"
SERVING = f"fylgja-orchestrator: serving stage-plan/main, twin-rehearse/main at {API}\n"
"""The line `fylgja-orchestrator serve` prints once it serves, as `edge/serve.py` prints it."""


EDGE_DEV = by_path("edge_dev")
"""`scripts/edge_dev.py`, loaded by its path: what makes the runner's environment and names Prefect's home."""

INFRAHUB_DEV, NETBOX_DEV = by_path("infrahub_dev"), by_path("netbox_dev")
"""`scripts/infrahub_dev.py` and `scripts/netbox_dev.py`, each loaded by its path: what writes each source's lines into
`local/.env`."""


def hashed(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def loaded_env(local: Path, host: FakeHost) -> dict[str, str]:
    """The loaded environment of `local`, read here so that an assert that fails shows none of it."""
    env: dict[str, str] = demo.loaded(local, SHELL, host)
    return env


def becomes(host: FakeHost, pid: int, process: Any, log: Path | None = None) -> None:
    """Process `pid` is `process` from now on, as after its `execve`, and where `log` is given the runner's line is
    in it, as `serve` prints it."""
    host.processes[pid] = process
    if log is not None:
        log.write_text(SERVING)


def exits_at_its_signal(host: FakeHost) -> None:
    """Every process of `host` exits at the first signal it is sent, as the core and the runner were read to."""

    def exit_(pid: int, number: int) -> None:
        host.exit(pid)

    host.on_signal = exit_


PROJECT_NETWORKS = {
    "infrahub": ("fylgja-core-infrahub_default", ["172.19.0.0/16"]),
    "netbox": ("fylgja-core-netbox_default", ["198.51.100.0/24"]),
}
"""The network each source's Compose project makes, as read on the development host: the development NetBox's at its
override's range, and Infrahub's a /16 Docker chose, outside the lab pool there."""

NETBOX_SUPERUSER = "nbt_TheTestsKey.TheTestsSuperusersToken"
NETBOX_ACCOUNTS = {
    "FYLGJA_NETBOX_TOKEN": "nbt_TheTestsKey.TheTestsReadersToken",
    "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN": "nbt_TheTestsKey.TheTestsExamplesToken",
}
INFRAHUB_ACCOUNT = "the-tests-examples-own-infrahub-token"
"""The tokens the fakes of the targets write as the sources would make them, each the tests' own."""

MAKE_FAILED = 2
"""make's own exit status where a command of a recipe fails, whatever status the command gave: what a make step that
fails answers the script."""

SIDE_EFFECTS_FIRST = ("infrahub-up", "prefect-up")
"""Targets a test fails only after what they leave is left, as each was read to fail: `infrahub-up` with its lines
written and its containers running while the database is still unhealthy, and `prefect-up` at the end of its wait
with the server it started still up and recorded."""


DEPLOYMENT_IDS = {
    "stage-plan/main": "0b6f3c2a-5d1e-4c8f-9a70-2e4d6b8f1a01",
    "twin-rehearse/main": "7c2e9a14-3b5f-4d60-8e21-9f0a1c3d5e02",
}
"""Each deployment's id as the fake Prefect answers it: one each, the same at every ask, as the two were read to keep
theirs at every start of the runner (design/verified-facts.md, "Prefect 3.9.2", 2026-11-14)."""

APPEARS_S = {"infrahub": 113.8, "netbox": 1.0}
"""Seconds from the step that opens the change returning to the change's flow run of `twin-rehearse/main` made, as
each was read: 116.4 and 113.8 s after `make infrahub-seed PROPOSED_CHANGE=1` returned ("Infrahub 1.11.11",
2026-11-14), the second here, and 0.94 to 1.03 s after the tag's `PATCH` ("NetBox 4.7.5 with netbox-branching
1.2.3")."""

PLAN_AHEAD_S = 4.6
"""Seconds by which Infrahub's change made its run of `stage-plan/main` before its run of `twin-rehearse/main`, by
their `created` in the second reading of 2026-11-14 (109.4 and 114.0 s after the proposed change's creation, a
derivation); its check `fylgja-step` starts it, and NetBox's webhook starts none."""

COURSE = (("PENDING", "Pending", 1.0), ("RUNNING", "Running", 3.0), ("COMPLETED", "Completed", 420.0))
"""A run's states after it is made `SCHEDULED`, each with its seconds since it was made, in the order a rehearsal's run
was read to go them (Scheduled, Pending, Running, then its end); the seconds are the fake's own, shorter than the
14.1 s to `Running` and 563.1 s to `Completed` read on 2026-11-14."""

EPOCH = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
"""The wall time the fake host's clock starts at, for the timestamps Prefect writes."""


def stamp(now: float) -> str:
    """A timestamp as Prefect writes one, in UTC, `now` seconds of the fake clock after `EPOCH`."""
    return (EPOCH + timedelta(seconds=now)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def rehearsal(status: str) -> dict[str, Any]:
    """A rehearsal 1 document of `status`, valid by `formats/rehearsal-1.schema.json` (a test holds each so): a passed
    rehearsal of five stages, the failed one of `test_formats`, and its minimal one as not rehearsed and as stopped."""
    if status == "failed":
        return full_rehearsal()
    if status == "passed":
        failed = full_rehearsal()
        passed = {**failed["stages"][2]}
        held = {key: value for key, value in failed.items() if key != "room"}
        return held | {
            "status": "passed",
            "headline": "Rehearsal passed: 5 stages\nEvery stage was rehearsed on the twin and passed.",
            "took_s": 412.6,
            "stages": [{"result": "empty"}, failed["stages"][1], passed, passed, passed],
            "already_failing": [],
            "reclaimed": [],
            "findings": [],
        }
    headline = {"not_rehearsed": minimal_rehearsal()["headline"], "stopped": "Stopped\nThe rehearsal was stopped."}
    return minimal_rehearsal() | {"status": status, "headline": headline[status]}


def flow_run(ident: str, deployment_id: str, branch: str, now: float) -> dict[str, Any]:
    """A row of `POST /api/flow_runs/filter` for a run made `now` by the fake clock, `SCHEDULED`: the members of the 36
    a row was read to hold that the script or a reader of it might ask for (design/verified-facts.md, "Prefect 3.9.2",
    2026-11-14), its `parameters` `{"branch": <branch>}` as a check or the webhook starts it."""
    row: dict[str, Any] = {
        "id": ident,
        "created": stamp(now),
        "updated": stamp(now),
        "name": f"fake-run-{ident[-4:]}",
        "flow_id": "5a8d0e3c-1f2b-4c6d-8e9f-0a1b2c3d4e05",
        "deployment_id": deployment_id,
        "parameters": {"branch": branch},
        "expected_start_time": stamp(now),
        "start_time": None,
        "end_time": None,
    }
    moved(row, "SCHEDULED", "Scheduled", now)
    return row


def moved(row: dict[str, Any], kind: str, name: str, now: float) -> None:
    """`row`'s run in the state `kind` named `name` from `now` by the fake clock: its `state`, with its seven members,
    and its `state_type` and `state_name`."""
    message = "" if kind != "CRASHED" else "Flow run infrastructure exited with non-zero status code 1."
    row["state"] = {
        "id": hashlib.sha256(f"{row['id']} {kind} {now}".encode()).hexdigest()[:32],
        "type": kind,
        "name": name,
        "message": message,
        "timestamp": stamp(now),
        "data": None,
        "state_details": {"flow_run_id": row["id"]},
    }
    row["state_type"], row["state_name"], row["updated"] = kind, name, stamp(now)
    if kind == "RUNNING":
        row["start_time"] = stamp(now)
    if kind in ("COMPLETED", "FAILED", "CANCELLED", "CRASHED"):
        row["end_time"] = stamp(now)


SORTS = (
    "ID_DESC", "START_TIME_ASC", "START_TIME_DESC", "EXPECTED_START_TIME_ASC", "EXPECTED_START_TIME_DESC", "NAME_ASC",
    "NAME_DESC", "NEXT_SCHEDULED_START_TIME_ASC", "END_TIME_DESC",
)  # fmt: skip
"""The sorts Prefect 3.9.2 takes for flow runs, `prefect.server.schemas.sorting.FlowRunSort` of the package the venv
holds; any other is refused, 422, as a body Prefect does not read is."""

LIMIT = 200
"""The largest `limit` a filter takes: 201 was answered 422 (design/verified-facts.md, "Prefect 3.9.2", 2026-11-14)."""


def read_by_make(argv: Sequence[str], env: Mapping[str, str]) -> tuple[dict[str, str], str]:
    """The variables and the flags a `make` run by `argv` under `env` holds, as make takes them: a variable from its
    command line, else from the words `MAKEFLAGS` and `GNUMAKEFLAGS` hand on, with or without `--` before them,
    else from its environment; a flag from either of the two. So read with `make -n` of this checkout's `Makefile`
    on the development host (GNU Make 4.4.1, 2026-11-14): `PURGE=1` in the environment, in `MAKEFLAGS` or in
    `GNUMAKEFLAGS` gave `infrahub-down` its `--purge`, and `PURGE=` on the command line took it away from all
    three; `MAKEOVERRIDES` and `MFLAGS` alone carried nothing. `MAKEFILES` is not read here: `answered` refuses a
    child that is given it."""
    variables = dict(env)
    flags = ""
    for handed in (env.get("GNUMAKEFLAGS", ""), env.get("MAKEFLAGS", "")):
        for word in handed.split():
            if "=" in word:
                variables[word.partition("=")[0]] = word.partition("=")[2]
            else:
                flags += word.strip("-")
    for word in argv[1:]:
        if "=" in word and not word.startswith("-"):
            variables[word.partition("=")[0]] = word.partition("=")[2]
    return variables, flags


class Targets:
    """The make targets a demonstration runs and the core it starts, on a `FakeHost` over a `local/` of the test's
    own: each answered by what the real one leaves, and refused where the real one would refuse what the script gave
    it. Nothing is run: what a target writes into `local/.env` is written by its own script's function, loaded by its
    path, the secrets it makes among it.

    - A target is answered by its name (`make --no-print-directory <target> LOCAL=<local> <variables…>`), kept in
      `asked` with the variables of its command line. It exits 0, or `MAKE_FAILED` where a name it reads from its
      environment is not there as `local/.env` holds it now (each says `Load local/.env first`), where what it
      needs is not up, and for each ask a test lists in `fails`, by the target and the count of its asks from 1.
    - **A make variable is read as make reads it** (`read_by_make`): from the command line, else from `MAKEFLAGS`
      or `GNUMAKEFLAGS`, else from the child's environment, else the `Makefile`'s own value. So a `PURGE`, a
      `SOURCE` or a branch the script let through from its caller's environment acts here as it would on the
      host. `LOCAL` must be the test's own whatever gives it; a child given `MAKEFILES` is refused outright, since
      what another makefile would do is not known here; and under the flag `i` a target that fails exits 0, as
      make ignores a recipe's errors.
    - `infrahub-up` and `netbox-up` write their names, `netbox-up` the superuser's token too, and bring the source
      up: its project's containers running, its network standing, its port listened on at loopback by a process
      of another user's, as Docker's proxy is, and its memory taken from what `/proc/meminfo` says is available.
      The two `down` targets stop it, the memory given back, and where `PURGE` is `1` remove the network, the
      source then listed in `purged`.
    - `orchestrator-env` is `edge_dev.py env`: its lines by `edge_dev.env_lines`, the runner's token's hash appended
      to the file `FYLGJA_TOKENS` names, and exit 2 with nothing written where that is not set or names no file;
      then, but where `SOURCE` is `netbox`, the example's Infrahub token's line, which needs Infrahub up and the
      admin's token; a `SOURCE` that is neither source is make's own error.
    - `built` lists each branch a seed built: `SEED_BRANCH`'s by `infrahub-seed` and `NETBOX_BRANCH`'s by
      `netbox-change`, each `third-link` where the variable is not given.
    - `prefect-up` starts a Prefect server under `local/prefect/`, given the basic auth, records it in `server.pid`
      and listens on port 4200 of the bind; one of its own up already is left. `prefect-down` ends that one.
    - `netbox-seed` writes the two accounts' tokens; `netbox-hook` needs Prefect answering the auth it was given and
      a runner having made the deployments; `netbox-change` marks each step through the core with the runner's
      token, so it needs a core that admits it, and with `NETBOX_TAG=1` the tag, which `netbox-hook` makes.
      `infrahub-register` needs a `REF`; `infrahub-seed` the registration, and writes `local/infrahub/seed.json`.
    - The core reads its token file at its start alone: one started over a file that is not there, or that lists a
      hash twice, exits a second on and never listens; any other admits the tokens whose hashes the file held
      then. Its CLI lists `twins`, and destroys one, only through a core that admits the token it was given.
    - `edge_dev.py serve` becomes the runner a second on, under the environment `edge_dev.runner_env` makes of the
      one it was started with, its line then in its log; it exits where a name it needs is not set or no Prefect
      server is up. `edge_dev.py api` prints `API`.
    - Prefect answers a deployment by its name only while its server is up: 401 to another auth than its own, 404
      until a runner has made the deployments, `READY` from then on. The core's version is answered where a core
      listens.
    - `opened` holds, for each change opened, by `infrahub-seed` with `PROPOSED_CHANGE=1` or `netbox-change` with
      `NETBOX_TAG=1`, whether a runner served Prefect then: opened with none serving, Infrahub's check fails and
      NetBox's request is lost. Opened while one serves, it starts a run of `twin-rehearse/main` with the branch as
      its parameter, made `APPEARS_S` of the source's after the step, which is after the step returned: so `sleep`,
      the script's wait, alone brings it about. The run then goes the states of `COURSE`, or of `course` where a test
      sets it, and at its end files `verdict`'s document where that is a status, as `filed`, its data a JSON string
      or, with `as_object`, an object; with `verdict` None it files none. With `starts_runs` False no run is made.
    - Prefect lists a deployment's runs, `POST /api/flow_runs/filter`, from `runs`, rows as `flow_run` makes them:
      401 to another auth than its server's, 422 to a body it does not read (a `limit` over `LIMIT`, a sort not of
      `SORTS`), nothing answered while no server is up, and else 200 with the rows of the deployments the body names,
      newest first by `expected_start_time` with `EXPECTED_START_TIME_DESC`, and in an order neither so nor reversed
      with none, at most `limit` of them. It answers a run's document, `POST /api/artifacts/filter`, as the glue asks
      for it: a list of the one artifact of the type asked that the run filed, or an empty one. A test lists answers
      of its own before these in `host.replies`, which the first that matches answers.
    - `by_hand` is a target as a person ran it before the demonstration, with `local/.env` loaded."""

    def __init__(self, host: FakeHost, local: Path) -> None:
        self.host, self.local, self.env_file = host, local, local / ".env"
        self.asked: list[list[str]] = []
        self.fails: dict[str, set[int]] = {}
        self.done: set[str] = set()
        self.served = False
        self.opened: list[bool] = []
        self.purged: list[str] = []
        self.built: list[str] = []
        self.listed: dict[int, str] = {}
        self.twins: list[str] = []
        self.runs: list[dict[str, Any]] = []
        self.filed: dict[str, Any] = {}
        self.starts_runs = True
        self.course: tuple[tuple[str, str, float], ...] = COURSE
        self.verdict: str | None = "passed"
        self.as_object = False
        for target in (
            "infrahub-up",
            "infrahub-down",
            "infrahub-register",
            "infrahub-seed",
            "netbox-up",
            "netbox-down",
            "netbox-seed",
            "netbox-hook",
            "netbox-change",
            "orchestrator-env",
            "prefect-up",
            "prefect-down",
        ):
            host.answers[("make", "--no-print-directory", target)] = self.answered
        host.answers[(CLI, "twin", "list", "--json")] = self.twin_list
        host.answers[(CLI, "twin", "destroy")] = self.twin_destroy
        host.answer(*demo.api_argv(local, MAIN)[:4], out=f"{API}\n")
        host.replies.append(("GET", "http://127.0.0.1:", self.version))
        host.replies.append(("GET", f"{API}/deployments/name/", self.deployment))
        host.replies.append(("POST", f"{API}/flow_runs/filter", self.flow_runs))
        host.replies.append(("POST", f"{API}/artifacts/filter", self.artifacts))
        host.on_start = self.started

    def answered(self, ran: Ran) -> Any:
        target, env = ran.argv[2], ran.env or {}
        assert ran.cwd == ROOT and not ran.capture and ran.timeout is None
        assert "MAKEFILES" not in env, "a make child was given MAKEFILES, and reads other makefiles first"
        variables, flags = read_by_make(ran.argv, env)
        assert variables.get("LOCAL") == str(self.local), "a make child's LOCAL is not the test's own"
        self.asked.append([target, *ran.argv[4:]])
        fails = sum(1 for words in self.asked if words[0] == target) in self.fails.get(target, ())
        passed = False
        if not fails or target in SIDE_EFFECTS_FIRST:
            passed = getattr(self, target.replace("-", "_"))(env, variables)
        if passed and not fails:
            self.done.add(target)
        return demo.Done(0 if (passed and not fails) or "i" in flags else MAKE_FAILED, "")

    def by_hand(self, target: str, *variables: str) -> None:
        """`target` as a person ran it before the demonstration, `local/.env` loaded first as its runbook says: what
        it leaves is left, and it is not among the targets the script asked."""
        env = loaded_env(self.local, self.host)
        given = read_by_make(["make", target, *variables], {})[0]
        passed: bool = getattr(self, target.replace("-", "_"))(env, given)
        assert passed, target
        self.done.add(target)

    def serving(self) -> bool:
        """Whether a runner serves this `local/`'s Prefect now."""
        runs = any(demo.is_runner(process, self.local) for process in self.host.processes.values())
        return runs and self.prefect() is not None

    def held(self, name: str) -> str | None:
        """What `local/.env` holds for `name` now, as a shell reads it."""
        held: str | None = NETBOX_DEV.held(self.env_file, name)
        return held

    def given(self, env: Mapping[str, str], *names: str) -> bool:
        """Whether a target's child was given each of `names` as `local/.env` holds it now."""
        return all(bool(env.get(name)) and same(env.get(name), self.held(name)) for name in names)

    def memory(self, mib: int) -> None:
        """`mib` more MiB of memory is available on the host, or with a negative `mib` less."""
        held = self.host.files[Path("/proc/meminfo")]
        self.host.files[Path("/proc/meminfo")] = meminfo(demo.available_mb(held) + mib)

    def brought_up(self, source: str) -> None:
        """`source` as its `up` target leaves it."""
        if not self.is_up(source):
            self.memory(-demo.SOURCE_MB[source])
        self.host.up.add(demo.PROJECTS[source])
        if PROJECT_NETWORKS[source] not in self.host.networks:
            self.host.networks.append(PROJECT_NETWORKS[source])
        served = (f"127.0.0.1:{demo.PORTS[source]}", None, "")
        if served not in self.host.listening:
            self.host.listening.append(served)

    def taken_down(self, source: str, variables: Mapping[str, str]) -> bool:
        if self.is_up(source):
            self.memory(demo.SOURCE_MB[source])
        self.host.up.discard(demo.PROJECTS[source])
        self.host.listening = [held for held in self.host.listening if held[0] != f"127.0.0.1:{demo.PORTS[source]}"]
        if variables.get("PURGE") == "1":
            self.host.networks = [held for held in self.host.networks if held != PROJECT_NETWORKS[source]]
            self.purged.append(source)
        return True

    def is_up(self, source: str) -> bool:
        return demo.PROJECTS[source] in self.host.up

    def infrahub_up(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        INFRAHUB_DEV.write_env(self.env_file)
        self.brought_up("infrahub")
        return True

    def infrahub_down(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        return self.taken_down("infrahub", variables)

    def infrahub_register(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        named = variables.get("REF", "the-branch-checked-out")
        return self.is_up("infrahub") and bool(named) and self.given(env, "FYLGJA_INFRAHUB_WRITE_TOKEN")

    def infrahub_seed(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        if not (
            self.is_up("infrahub")
            and "infrahub-register" in self.done
            and self.given(env, "FYLGJA_INFRAHUB_WRITE_TOKEN", "FYLGJA_INFRAHUB_TOKEN")
        ):
            return False
        branch = variables.get("SEED_BRANCH", "third-link")
        proposed = variables.get("PROPOSED_CHANGE") == "1"
        change = {"id": "the-proposed-changes-id", "name": f"Rehearse {branch}"}
        seeded: dict[str, Any] = {
            "branch": branch,
            "scope": "tag:fylgja",
            "stages": [],
            "marks": [],
            "proposed_change": change if proposed else None,
        }
        (self.local / "infrahub").mkdir(exist_ok=True)
        (self.local / "infrahub" / "seed.json").write_text(json.dumps(seeded))
        self.built.append(branch)
        if proposed:
            self.opened.append(self.serving())
            self.rehearsed("infrahub", branch)
        return True

    def netbox_up(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        NETBOX_DEV.write_env(self.env_file)
        if not self.held(NETBOX_DEV.WRITE_TOKEN):
            NETBOX_DEV.set_line(self.env_file, NETBOX_DEV.WRITE_TOKEN, NETBOX_SUPERUSER)
        self.brought_up("netbox")
        return True

    def netbox_down(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        return self.taken_down("netbox", variables)

    def netbox_seed(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        if not (self.is_up("netbox") and self.given(env, "FYLGJA_NETBOX_ADDRESS", NETBOX_DEV.WRITE_TOKEN)):
            return False
        for name, token in NETBOX_ACCOUNTS.items():
            if not self.held(name):
                NETBOX_DEV.set_line(self.env_file, name, token)
        return True

    def netbox_hook(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        server = self.prefect()
        return (
            self.is_up("netbox")
            and self.given(env, NETBOX_DEV.WRITE_TOKEN, EDGE_DEV.AUTH)
            and server is not None
            and same(env.get(EDGE_DEV.AUTH), self.host.processes[server].environ["PREFECT_SERVER_API_AUTH_STRING"])
            and self.served
        )

    def netbox_change(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        if not (self.is_up("netbox") and self.given(env, NETBOX_DEV.WRITE_TOKEN)):
            return False
        tagged = variables.get("NETBOX_TAG") == "1"
        if tagged and "netbox-hook" not in self.done:
            return False
        try:
            marks_under = EDGE_DEV.source_env(env, "netbox")
        except EDGE_DEV.Missing:
            return False
        if not self.admits(marks_under):
            return False
        self.built.append(variables.get("NETBOX_BRANCH", "third-link"))
        if tagged:
            self.opened.append(self.serving())
            self.rehearsed("netbox", self.built[-1])
        return True

    def orchestrator_env(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        source = variables.get("SOURCE", "infrahub")
        if source not in demo.SOURCES:
            return False
        lines = EDGE_DEV.env_lines(EDGE_DEV.held_names(self.env_file), MAIN, "tag:fylgja")
        added = dict(lines)
        tokens = env.get(EDGE_DEV.TOKENS, "")
        if EDGE_DEV.API_TOKEN in added and not (tokens and Path(tokens).is_file()):
            return False
        if lines:
            EDGE_DEV.append(self.env_file, [f"{name}={value}" for name, value in lines])
        if EDGE_DEV.API_TOKEN in added:
            EDGE_DEV.append(Path(tokens), [f"{EDGE_DEV.hashed(added[EDGE_DEV.API_TOKEN])} {EDGE_DEV.PRINCIPAL}"])
        if source == "netbox":
            return True
        if not (self.is_up("infrahub") and self.given(env, "FYLGJA_INFRAHUB_ADDRESS", "FYLGJA_INFRAHUB_WRITE_TOKEN")):
            return False
        if not self.held(EDGE_DEV.INFRAHUB_TOKEN):
            EDGE_DEV.append(self.env_file, [f"{EDGE_DEV.INFRAHUB_TOKEN}={INFRAHUB_ACCOUNT}"])
        return True

    def prefect(self) -> int | None:
        """The pid of this `local/`'s Prefect server where it is up, as `make prefect-up` itself reads it."""
        pid: int | None = EDGE_DEV.running(self.local, read=self.host.process)
        return pid

    def prefect_up(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        if self.prefect() is not None:
            return True
        auth = env.get(EDGE_DEV.AUTH, "")
        if not auth or any(address.rpartition(":")[2] == "4200" for address, _, _ in self.host.listening):
            return False
        home = EDGE_DEV.home_of(self.local)
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        pid = self.host.next_pid
        self.host.next_pid += 1
        given = {name: env[name] for name in ("PATH", "HOME") if name in env}
        given |= {"PREFECT_HOME": str(home), "PREFECT_SERVER_API_AUTH_STRING": auth, **EDGE_DEV.ANALYTICS_OFF}
        words = [PYTHON, str(EDGE_DEV.PREFECT), "server", "start", "--host", BIND, "--port", "4200", "--no-ui"]
        self.host.processes[pid] = demo.Process(words, given)
        self.host.listening.append((f"{BIND}:4200", pid, "prefect"))
        EDGE_DEV.pid_file(self.local).write_text(f"{pid}\n")
        return True

    def prefect_down(self, env: Mapping[str, str], variables: Mapping[str, str]) -> bool:
        pid = self.prefect()
        if pid is not None:
            del self.host.processes[pid]
            self.host.listening = [held for held in self.host.listening if held[1] != pid]
        EDGE_DEV.pid_file(self.local).unlink(missing_ok=True)
        return True

    def core_at(self, address: str | None) -> int | None:
        """The pid of the core that listens at `address`; None where none does."""
        for pid, process in sorted(self.host.processes.items()):
            listens = process.environ.get("FYLGJA_LISTEN") or "127.0.0.1:7650"
            if is_a_core(process) and pid not in self.host.not_listening and listens == address:
                return pid
        return None

    def admits(self, env: Mapping[str, str]) -> bool:
        """Whether the core at `env`'s `FYLGJA_API_ADDRESS` admits its `FYLGJA_API_TOKEN`: one listens there, and its
        token file held the token's hash when it started."""
        pid = self.core_at(env.get("FYLGJA_API_ADDRESS"))
        token = env.get("FYLGJA_API_TOKEN", "")
        return pid is not None and bool(token) and hashed(token) in self.listed.get(pid, "").split()

    def twin_list(self, ran: Ran) -> Any:
        if not self.admits(ran.env or {}):
            return demo.Done(1, "")
        records = [
            {"name": name, "generation": 1, "status": {"observed_generation": 1, "phase": "pushed"}}
            for name in self.twins
        ]
        return demo.Done(0, json.dumps(records, indent=2) + "\n")

    def twin_destroy(self, ran: Ran) -> Any:
        if not self.admits(ran.env or {}) or ran.argv[-1] not in self.twins:
            return demo.Done(1, "")
        self.twins.remove(ran.argv[-1])
        return demo.Done(0, "")

    def started(self, child: Started) -> None:
        host = self.host
        if child.argv == [CORE]:
            tokens = Path(child.env.get("FYLGJA_TOKENS", ""))
            held = tokens.read_text() if tokens.is_file() else ""
            hashes = [line.split()[0] for line in held.splitlines() if line.split()]
            self.listed[child.pid] = " ".join(hashes)
            if not tokens.is_file() or len(hashes) != len(set(hashes)):
                host.not_listening.add(child.pid)
                host.at(host.now + 1.0, lambda: host.exit(child.pid))
        elif child.argv[:4] == demo.serve_argv("netbox", self.local, MAIN)[:4]:
            host.at(host.now + 1.0, lambda: self.becomes_the_runner(child))

    def becomes_the_runner(self, child: Started) -> None:
        source = child.argv[child.argv.index("--source") + 1]
        try:
            environ = EDGE_DEV.runner_env(child.env, BIND, home=EDGE_DEV.home_of(self.local), source=source)
        except EDGE_DEV.Missing:
            environ = None
        if environ is None or self.prefect() is None:
            self.host.exit(child.pid)
            return
        becomes(self.host, child.pid, demo.Process([PYTHON, RUNNER, "serve"], environ), child.log)
        self.served = True

    def version(self, asked: Any) -> Any:
        address = asked.url.removeprefix("http://").partition("/")[0]
        return demo.Answer(200, {"api": "1", "build": "0.0.0"}) if self.core_at(address) else demo.Answer(None, None)

    def deployment(self, asked: Any) -> Any:
        server = self.prefect()
        if server is None:
            return demo.Answer(None, None)
        if not same(asked.auth, self.host.processes[server].environ["PREFECT_SERVER_API_AUTH_STRING"]):
            return demo.Answer(401, {"detail": "Unauthorized"})
        if not self.served:
            return demo.Answer(404, {"detail": "Deployment not found"})
        named = asked.url.removeprefix(f"{API}/deployments/name/")
        ident = DEPLOYMENT_IDS.get(named)
        if ident is None:
            return demo.Answer(404, {"detail": "Deployment not found"})
        return demo.Answer(200, {"id": ident, "name": "main", "status": "READY", "paused": False})

    def refused(self, asked: Any) -> Any:
        """Nothing answered while no server is up, and 401 to an auth that is not its server's; None where neither."""
        server = self.prefect()
        if server is None:
            return demo.Answer(None, None)
        if not same(asked.auth, self.host.processes[server].environ["PREFECT_SERVER_API_AUTH_STRING"]):
            return demo.Answer(401, {"detail": "Unauthorized"})
        return None

    def rehearsed(self, source: str, branch: str) -> None:
        """The change opened while a runner serves starts a run of `twin-rehearse/main` (`Targets`, `opened`), and,
        Infrahub's, a run of `stage-plan/main` `PLAN_AHEAD_S` before it."""
        if not (self.starts_runs and self.serving()):
            return
        appears = self.host.now + APPEARS_S[source]
        if source == "infrahub":
            planned = appears - PLAN_AHEAD_S
            self.host.at(planned, lambda: self.made(branch, deployment="stage-plan/main", when=planned))
        self.host.at(appears, lambda: self.made(branch, when=appears))

    def made(
        self,
        branch: str,
        *,
        course: tuple[tuple[str, str, float], ...] | None = None,
        deployment: str = "twin-rehearse/main",
        when: float | None = None,
    ) -> dict[str, Any]:
        """A run of `deployment` made `when`, by the fake clock, or now, `SCHEDULED`, that goes `course` from there,
        `self.course` where none is given, and files its document at its end; its row. A `sleep` brings the clock past
        `when` before it is made, so its `created` is the time it was due, as Prefect writes the time it made it."""
        now = self.host.now if when is None else when
        ident = f"0f1e2d3c-4b5a-4697-8a8b-{len(self.runs) + 1:012x}"
        row = flow_run(ident, DEPLOYMENT_IDS[deployment], branch, now)
        self.runs.append(row)
        for kind, name, after in self.course if course is None else course:
            self.host.at(now + after, functools.partial(self.goes, row, kind, name))
        return row

    def goes(self, row: dict[str, Any], kind: str, name: str) -> None:
        """`row`'s run moves to `kind` now; where that is `COMPLETED` it files its document first, as a flow files it
        before it returns: a plan's, `planned`, for a run of `stage-plan/main`, and for one of `twin-rehearse/main` the
        rehearsal `verdict` names, where it names one."""
        twin = row["deployment_id"] == DEPLOYMENT_IDS["twin-rehearse/main"]
        if kind == "COMPLETED" and (self.verdict is not None or not twin):
            document = rehearsal(self.verdict) if twin and self.verdict is not None else full_plan()
            self.filed[row["id"]] = document if self.as_object else json.dumps(document)
        moved(row, kind, name, self.host.now)

    def flow_runs(self, asked: Any) -> Any:
        refused = self.refused(asked)
        if refused is not None:
            return refused
        body = asked.body if isinstance(asked.body, dict) else {}
        limit, sort = body.get("limit", LIMIT), body.get("sort")
        if not isinstance(limit, int) or not 0 <= limit <= LIMIT:
            return demo.Answer(422, {"detail": f"Invalid limit: must be less than or equal to {LIMIT}."})
        if sort is not None and sort not in SORTS:
            return demo.Answer(422, {"detail": "Invalid request received."})
        named = body.get("flow_runs", {}).get("deployment_id", {}).get("any_")
        rows = [row for row in self.runs if named is None or row["deployment_id"] in named]
        if sort == "EXPECTED_START_TIME_DESC":
            rows.sort(key=lambda row: row["expected_start_time"], reverse=True)
        elif len(rows) > 2:
            rows = [*rows[1:], rows[0]]
        return demo.Answer(200, copy.deepcopy(rows[:limit]))

    def artifacts(self, asked: Any) -> Any:
        refused = self.refused(asked)
        if refused is not None:
            return refused
        body = asked.body if isinstance(asked.body, dict) else {}
        runs = body.get("artifacts", {}).get("flow_run_id", {}).get("any_", [])
        kinds = body.get("artifacts", {}).get("type", {}).get("any_", [])
        found = []
        for row in self.runs:
            if row["id"] in runs and row["id"] in self.filed and "fylgja-document" in kinds:
                when = row["end_time"]
                found.append(
                    {
                        "id": hashlib.sha256(row["id"].encode()).hexdigest()[:32],
                        "key": f"fylgja-twin-rehearse-{row['id']}",
                        "type": "fylgja-document",
                        "data": copy.deepcopy(self.filed[row["id"]]),
                        "description": None,
                        "metadata_": None,
                        "flow_run_id": row["id"],
                        "task_run_id": None,
                        "created": when,
                        "updated": when,
                    }
                )
        return demo.Answer(200, found[: body.get("limit", LIMIT)])


def first(tmp_path: Path) -> tuple[Path, Any, FakeHost, Targets]:
    """A host on which no demonstration has run and neither source is up, every check passing, with a `local/` of the
    test's own as a person makes one: `.env.example` copied, mode 0600, and the node login filled in, so every
    other name there is held with no value. Its records, the host, which reads `local/` as the real one would, and
    the targets it runs. Every process exits at its first signal."""
    local = tmp_path / "local"
    local.mkdir(parents=True)
    example = (ROOT / ".env.example").read_text()
    for name, value in zip(demo.LOGIN, (NODE_USER, NODE_PASSWORD), strict=True):
        assert example.count(f"\n{name}=\n") == 1
        example = example.replace(f"\n{name}=\n", f"\n{name}={value}\n")
    (local / ".env").write_text(example)
    (local / ".env").chmod(0o600)
    host = passing(local, disk=tmp_path)
    exits_at_its_signal(host)
    return local, demo.records(local), host, Targets(host, local)
