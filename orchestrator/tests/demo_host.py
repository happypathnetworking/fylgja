"""The demonstration script's host, faked whole: `scripts/demo.py` loaded by its path, as `make` runs it, and a
`FakeHost` in the place of its `Real`, so that no test of the script starts a process, opens a socket, reads a file
of the host's or sleeps. Every secret here is the tests' own."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "scripts" / "demo.py"

MAIN = Path("/srv/example/fylgja-core")
LOCAL = MAIN / "local"
"""A main checkout and its `local/` that are no directory of the host's: a `FakeHost` answers for what they hold."""


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_under_test", DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


demo = _load()


def same(a: object, b: object) -> bool:
    """`a == b` as a bool, so that a failure shows no secret (as `test_dev_plumbing.py`'s `same()`)."""
    return a == b


class Ran(NamedTuple):
    """One `run`: its words, the environment it was given, None where it was given none, and how it was run. It is
    shown by its words alone, so that an assert that fails shows no environment."""

    argv: list[str]
    env: dict[str, str] | None
    cwd: Path | None
    capture: bool
    timeout: float | None

    def __repr__(self) -> str:
        return f"Ran({self.argv!r})"


class Started(NamedTuple):
    """One `start`: its words, its whole environment, where it ran, its log and the pid it was answered. It is shown
    by its words and its pid alone."""

    argv: list[str]
    env: dict[str, str]
    cwd: Path
    log: Path
    pid: int

    def __repr__(self) -> str:
        return f"Started({self.argv!r}, pid={self.pid})"


class Asked(NamedTuple):
    """One `ask`: the request, and the auth it was given. It is shown by its method and its URL alone."""

    method: str
    url: str
    auth: str | None
    body: Any

    def __repr__(self) -> str:
        return f"Asked({self.method!r}, {self.url!r})"


class FakeHost:
    """`demo.Host`, answered from what a test lists and recording what it was asked.

    - `run` answers an argv by its leading words: the longest of `answers`' keys the argv begins with, a `Done` or a
      function of the `Ran` that gives one, its output answered only where the run was captured, as `Real` answers.
      An argv no key begins is the test's mistake, and raises.
    - `start` answers the next pid from `next_pid` and puts the process in `processes`, the `/proc` a test writes,
      as `/proc` shows a child just started: its words and its environment as given, and before its words, for a
      command of `interpreters`, a `#!` script, the interpreter the kernel runs it by. It then calls `on_start`
      where a test gives one, which says what the child does next. A test that says a command cannot be started
      raises from a `start` of its own what `Popen` raises.
    - `signal` answers whether `processes` holds the pid, and calls `on_signal` where a test gives one; a pid at
      or under 1 is no process to it or to `process`, as to `Real`, whatever `processes` holds; `pids` lists none
      under 1, as `/proc` has none, and a process with no command line is none to `process`, as to `Real`.
    - `ask` answers the first of `replies` whose method is the request's and whose URL begins it, an `Answer` or a
      function of the `Asked`; where none does, nothing answered.
    - `text` answers `files`, raises `PermissionError` for a path of `denied`, and reads a file under `disk`, a
      directory of the test's own, where one is given, its bytes decoded as `Real` decodes them and no line end
      translated; any other path is absent.
    - `sleep` advances `now`, which `clock` answers, and then lets happen, once each and in the order of their
      times, what a test said with `at` would happen on the host by then: a process that exits or becomes another
      by `execve`, a line that reaches a log.

    Every `run`, `start`, `signal`, `ask` and `lock` is kept, in order, in `ran`, `started`, `signalled`, `asked` and
    `locked`, and every `run`, `start` and `signal` in `acts` too, one list in the order they were made."""

    def __init__(self, disk: Path | None = None) -> None:
        self.disk = disk
        self.answers: dict[tuple[str, ...], Any] = {}
        self.replies: list[tuple[str, str, Any]] = []
        self.files: dict[Path, str] = {}
        self.denied: set[Path] = set()
        self.processes: dict[int, Any] = {}
        self.interpreters: dict[str, str] = {}
        self.on_start: Callable[[Started], None] | None = None
        self.later: list[tuple[float, Callable[[], None]]] = []
        self.acts: list[Any] = []
        self.on_path: set[str] = set()
        self.gids: dict[str, int] = {}
        self.held: set[int] = set()
        self.uid = 1000
        self.now = 0.0
        self.free = True
        self.next_pid = 5000
        self.on_signal: Callable[[int, int], None] | None = None
        self.ran: list[Ran] = []
        self.started: list[Started] = []
        self.signalled: list[tuple[int, int]] = []
        self.asked: list[Asked] = []
        self.locked: list[Path] = []
        self.slept: list[float] = []
        self.secrets: list[str] = []

    def answer(self, *words: str, status: int = 0, out: str = "") -> None:
        """An argv that begins `words` exits `status` having printed `out`."""
        self.answers[words] = demo.Done(status, out)

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        capture: bool = False,
        timeout: float | None = None,
    ) -> Any:
        ran = Ran(list(argv), None if env is None else dict(env), cwd, capture, timeout)
        self.ran.append(ran)
        self.acts.append(ran)
        for length in range(len(ran.argv), 0, -1):
            answer = self.answers.get(tuple(ran.argv[:length]))
            if answer is not None:
                done = answer(ran) if callable(answer) else answer
                return done if capture else demo.Done(done.status, "")
        raise AssertionError(f"the test lists no answer for {ran.argv}")

    def start(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: Path, log: Path) -> int:
        pid = self.next_pid
        self.next_pid += 1
        started = Started(list(argv), dict(env), cwd, log, pid)
        self.started.append(started)
        self.acts.append(started)
        by = [self.interpreters[started.argv[0]]] if started.argv[0] in self.interpreters else []
        self.processes[pid] = demo.Process([*by, *started.argv], dict(env))
        if self.on_start is not None:
            self.on_start(started)
        return pid

    def process(self, pid: int) -> Any:
        held = self.processes.get(pid) if pid > 1 else None
        return held if held is not None and held.argv else None

    def pids(self) -> list[int]:
        return sorted(pid for pid in self.processes if pid >= 1)

    def signal(self, pid: int, number: int) -> bool:
        self.signalled.append((pid, number))
        self.acts.append((pid, number))
        there = pid > 1 and pid in self.processes
        if there and self.on_signal is not None:
            self.on_signal(pid, number)
        return there

    def ask(self, method: str, url: str, *, auth: str | None = None, body: Any = None) -> Any:
        asked = Asked(method, url, auth, body)
        self.asked.append(asked)
        for verb, prefix, reply in self.replies:
            if verb == method and url.startswith(prefix):
                return reply(asked) if callable(reply) else reply
        return demo.Answer(None, None)

    def groups(self) -> set[int]:
        return set(self.held)

    def gid(self, name: str) -> int | None:
        return self.gids.get(name)

    def euid(self) -> int:
        return self.uid

    def which(self, name: str) -> str | None:
        if name not in self.on_path:
            return None
        return name if "/" in name else f"/usr/bin/{name}"

    def text(self, path: Path) -> str | None:
        if path in self.denied:
            raise PermissionError(13, "Permission denied", str(path))
        if path in self.files:
            return self.files[path]
        if self.disk is not None and path.is_relative_to(self.disk) and path.is_file():
            return path.read_bytes().decode("utf-8", "surrogateescape")
        return None

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        due = sorted((event for event in self.later if event[0] <= self.now), key=lambda event: event[0])
        self.later = [event for event in self.later if event[0] > self.now]
        for _, happen in due:
            happen()

    def at(self, when: float, happen: Callable[[], None]) -> None:
        """`happen` is called once, when a `sleep` first brings the clock to `when` or past it."""
        self.later.append((when, happen))

    def secret(self) -> str:
        self.secrets.append(f"the-fake-hosts-secret-{len(self.secrets) + 1}")
        return self.secrets[-1]

    def lock(self, path: Path) -> bool:
        self.locked.append(path)
        return self.free


NODE_USER = "the-tests-node-user"
NODE_PASSWORD = "the-tests-node-password"
CLIENT_TOKEN = "the-tests-clients-core-token"
RUNNER_TOKEN = "the-tests-runners-core-token"
AUTH = "fylgja:the-tests-prefect-password"

ENV = {
    "PATH": "/usr/bin",
    "HOME": "/srv/example/home",
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": NODE_USER,
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": NODE_PASSWORD,
    "FYLGJA_API_ADDRESS": "127.0.0.1:7650",
    "FYLGJA_API_TOKEN": CLIENT_TOKEN,
    "FYLGJA_ORCHESTRATOR_API_TOKEN": RUNNER_TOKEN,
    "FYLGJA_ORCHESTRATOR_AUTH": AUTH,
}
"""A loaded environment: the shell's two and `local/.env`'s lines, every secret the tests' own."""

SECRETS = (NODE_USER, NODE_PASSWORD, CLIENT_TOKEN, RUNNER_TOKEN, AUTH)

ENV_FILE = "".join(f"{name}={value}\n" for name, value in ENV.items() if name.startswith("FYLGJA_"))
"""`local/.env` as `ENV` was loaded from it."""

MIB = 1024
"""kB in a MiB, as `/proc/meminfo` counts."""


def meminfo(available_mib: int) -> str:
    """`/proc/meminfo` with `available_mib` MiB available."""
    return f"MemTotal:       32000000 kB\nMemFree:          500000 kB\nMemAvailable:   {available_mib * MIB} kB\n"


SS = "\n".join(
    [
        "LISTEN 0      4096       127.0.0.1:631        0.0.0.0:*",
        "LISTEN 0      4096       127.0.0.1:14200      0.0.0.0:*",
        "LISTEN 0      4096            [::]:22            [::]:*",
    ]
)
"""`ss -Hltn` on a host where nothing listens on a port the demonstration needs."""


def ss(*addresses: str) -> str:
    """`SS` and a listener at each of `addresses`."""
    return SS + "".join(f"\nLISTEN 0      4096       {address}       0.0.0.0:*" for address in addresses)


def passing(local: Path = LOCAL, disk: Path | None = None) -> FakeHost:
    """A host on which every check passes for either source, neither up: the venv's commands and the tools, Docker,
    Compose and containerlab answering, the user in both groups, the AppArmor widening made, memory for a source and
    the twin, no listener on a port the demonstration needs, `local/.env` with the node login, and a commit for any
    ref. Each of the venv's commands is a `#!` script of the venv's `python3`, as `pip` writes one."""
    host = FakeHost(disk)
    host.on_path = {*demo.TOOLS, *(str(demo.ROOT / "core" / ".venv" / "bin" / name) for name in demo.COMMANDS)}
    host.interpreters = {
        str(demo.ROOT / "core" / ".venv" / "bin" / name): str(demo.ROOT / "core" / ".venv" / "bin" / "python3")
        for name in demo.COMMANDS
    }
    host.answer("docker", "info")
    host.answer("docker", "compose", "version")
    host.answer("docker", "ps")
    host.answer("containerlab", "version")
    host.answer("ss", "-Hltn", out=SS)
    host.answer("git", "rev-parse")
    host.gids = {"docker": 998, "clab_admins": 997}
    host.held = {1000, 998, 997}
    host.files = {
        Path(demo.APPARMOR_PROFILE): "profile rsyslogd /usr/sbin/rsyslogd {\n}\n",
        Path(demo.APPARMOR_LOCAL): "/opt/srlinux/** mr,\n/run/srlinux/** rw,\n/run/syslogd.pid* rw,\n",
        Path("/proc/meminfo"): meminfo(16384),
    }
    if disk is None:
        host.files[local / ".env"] = ENV_FILE
    return host
