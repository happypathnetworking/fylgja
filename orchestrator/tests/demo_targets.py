"""The make targets a demonstration runs, faked beside the fake host: `Targets`, which answers each target on a
`demo_host.FakeHost` by what the real one leaves, with the core's start, its CLI, `edge_dev.py` and Prefect's
deployments; `first`, a host on which no demonstration has run; and the names and helpers they and the tests of
`scripts/demo.py` share. Nothing here starts a process, opens a socket or sleeps. What a target writes into
`local/.env` is written by its own development script's function, each script loaded by its path, as `make` runs
it; every other secret is the tests' own."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
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
      NetBox's request is lost.
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
        return demo.Answer(200, {"id": "a-deployments-id", "name": "main", "status": "READY", "paused": False})


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
