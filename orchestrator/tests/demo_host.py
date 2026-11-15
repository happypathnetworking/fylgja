"""The demonstration script's host, faked whole: `scripts/demo.py` loaded by its path, as `make` runs it, and a
`FakeHost` in the place of its `Real`, so that no test of the script starts a process, opens a socket, reads a file
of the host's or sleeps. Every secret here is the tests' own."""

from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
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
    - `heard` is `ss -Hltn` and `ss -Hltnp` as the host answers them while the processes of `processes` run: the
      lines of `SS`; a line for each listener of `listening`, a test's own; and one for each process that is a
      core (a word of its command line a path named `fylgja-core-server`) and not of `not_listening`, at its
      `FYLGJA_LISTEN`, or the core's default. Under `-p` a line names its process as `ss` names one this user runs,
      `users:(("<name>",pid=<pid>,fd=4))`, and names none for a listener whose pid is None, a process of another
      user's. A core listens from its start: the script asks who listens only before a start and after an answer.
      A core a test ends by `exit` keeps its listener for `lingers` seconds of the clock after it, with no process
      named for it, as a socket still closes for a moment after `/proc` has let its process go; the script reads
      that window by `ss -Hltn` alone.
    - `docker`'s reads of what Docker holds are answered from what a test says it holds, where `passing` lists them
      (the methods `containers`, `network_ids`, `networks_inspected`, `image_inspected` and `pulled`, each saying
      what the command prints): `up`, the Compose projects of which a container runs; `networks`, each Docker
      network by its name with its subnets; and `images`, the references Docker holds.
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
        self.listening: list[tuple[str, int | None, str]] = []
        self.not_listening: set[int] = set()
        self.lingers = 0.0
        self.closing: list[tuple[str, float]] = []
        self.interpreters: dict[str, str] = {}
        self.up: set[str] = set()
        self.networks: list[tuple[str, list[str]]] = []
        self.images: set[str] = set()
        self.on_start: Callable[[Started], None] | None = None
        self.later: list[tuple[float, Callable[[], object]]] = []
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

    def heard(self, ran: Ran) -> Any:
        """What `ss -Hltn` prints, and with `-p` among the words `ss -Hltnp`: the class says which listeners."""
        held = list(self.listening)
        held += [(address, None, "") for address, until in self.closing if self.now < until]
        for pid, process in sorted(self.processes.items()):
            if pid > 1 and pid not in self.not_listening and is_a_core(process):
                held.append((process.environ.get("FYLGJA_LISTEN") or "127.0.0.1:7650", pid, "fylgja-core-ser"))
        named = "-Hltnp" in ran.argv
        lines = [listener(address, pid if named else None, name) for address, pid, name in held]
        return demo.Done(0, "\n".join([SS, *lines]))

    def containers(self, ran: Ran) -> Any:
        """What `docker ps -q` prints: the short id, twelve hex digits, of each running container, a line each, and
        nothing where none runs. With `--filter label=com.docker.compose.project=<project>`, that project's alone:
        two where the project is of `up`, as a source's stack runs several."""
        named = [word.partition("com.docker.compose.project=")[2] for word in ran.argv if word.startswith("label=")]
        running = [project for project in sorted(self.up) if not named or project in named]
        ids = [short_id(f"{project}-{number}") for project in running for number in (1, 2)]
        return demo.Done(0, "".join(f"{each}\n" for each in ids))

    def network_ids(self, ran: Ran) -> Any:
        """What `docker network ls --format '{{.ID}}'` prints, the local driver's own question: each network's
        short id, twelve hex digits, a line each."""
        return demo.Done(0, "".join(f"{short_id(name)}\n" for name, _ in self.networks))

    def networks_inspected(self, ran: Ran) -> Any:
        """What `docker network inspect --format '{{json .Name}} {{json .IPAM.Config}}' <ids…>` prints: a line a
        network in the order of the ids, its name as a JSON string as Go writes one, no character above ASCII
        escaped, one space, and its IPAM config, a list of `{"Subnet", "Gateway"}` objects with no space in it, or
        `null` for a network with none, as `host` and `none` (design/verified-facts.md, Docker 29.8.1: the line read
        was `"fylgja-core-netbox_default" [{"Subnet":"198.51.100.0/24","Gateway":"198.51.100.1"}]`). An id no
        network has is exit 1, as read of a name no network has."""
        held = {short_id(name): (name, subnets) for name, subnets in self.networks}
        ids = ran.argv[ran.argv.index("--format") + 2 :]
        if any(each not in held for each in ids):
            return demo.Done(1, "")
        return demo.Done(0, "".join(f"{network_line(*held[each])}\n" for each in ids))

    def image_inspected(self, ran: Ran) -> Any:
        """What `docker image inspect --format '{{.Id}}' <ref>` does: prints the image's id, `sha256:` and 64 hex
        digits, exit 0, where Docker holds the reference; exit 1 having printed nothing on stdout where it holds
        none (design/verified-facts.md: `No such image`, on stderr)."""
        ref = ran.argv[-1]
        if ref not in self.images:
            return demo.Done(1, "")
        return demo.Done(0, f"sha256:{hashlib.sha256(ref.encode()).hexdigest()}\n")

    def pulled(self, ran: Ran) -> Any:
        """What `docker pull <ref>` leaves where it exits 0: Docker holds the reference. Its progress is printed to
        the terminal, and the script captures none of it."""
        self.images.add(ran.argv[-1])
        return demo.Done(0, "")

    def exit(self, pid: int) -> None:
        """Process `pid` exits now: it is no process from here on, and where it was a core that listened and
        `lingers` is set, its listener stays that long."""
        process = self.processes.pop(pid)
        if self.lingers > 0 and pid not in self.not_listening and is_a_core(process):
            address = process.environ.get("FYLGJA_LISTEN") or "127.0.0.1:7650"
            self.closing.append((address, self.now + self.lingers))

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

    def at(self, when: float, happen: Callable[[], object]) -> None:
        """`happen` is called once, when a `sleep` first brings the clock to `when` or past it."""
        self.later.append((when, happen))

    def secret(self) -> str:
        self.secrets.append(f"the-fake-hosts-secret-{len(self.secrets) + 1}")
        return self.secrets[-1]

    def lock(self, path: Path) -> bool:
        self.locked.append(path)
        return self.free


def is_a_core(process: Any) -> bool:
    """Whether a process of the tests' `/proc` is a core's server, whatever its store: a word of its command line
    is a path named `fylgja-core-server`."""
    return any(Path(word).name == "fylgja-core-server" for word in process.argv)


def short_id(name: str) -> str:
    """The short id Docker would print for a container or a network of the tests': twelve hex digits."""
    return hashlib.sha256(name.encode()).hexdigest()[:12]


def network_line(name: str, subnets: Sequence[str]) -> str:
    """One line of `docker network inspect`'s answer to `{{json .Name}} {{json .IPAM.Config}}` for the network
    `name` holding `subnets`, each with the gateway Docker gives it, the subnet's first address
    (`FakeHost.networks_inspected`)."""
    config = [
        {"Subnet": subnet, "Gateway": str(ipaddress.ip_network(subnet).network_address + 1)} for subnet in subnets
    ]
    held = json.dumps(config, separators=(",", ":")) if config else "null"
    return f"{json.dumps(name, ensure_ascii=False)} {held}"


def listener(address: str, pid: int | None = None, name: str = "python3") -> str:
    """One line of `ss -Hltn` for a listener at `address`, an address with its port; with `pid`, the line `ss
    -Hltnp` prints for a process this user runs, as read on the development host:
    `LISTEN 0      2048       127.0.0.1:7651 0.0.0.0:* users:(("fylgja-core-ser",pid=3163539,fd=4))`."""
    users = "" if pid is None else f' users:(("{name}",pid={pid},fd=4))'
    return f"LISTEN 0      2048       {address} {'[::]' if address.startswith('[') else '0.0.0.0'}:*{users}"


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
    the twin, no listener on a port the demonstration needs but a core's own where one runs (`FakeHost.heard`),
    `local/.env` with the node login, and a commit for any ref. Each of the venv's commands is a `#!` script of the
    venv's `python3`, as uv writes one. Docker holds what a host does where neither source has yet run: no
    container, the three networks Docker makes itself, of which the bridge alone has a subnet, and both images the
    seeded twin runs."""
    host = FakeHost(disk)
    host.on_path = {*demo.TOOLS, *(str(demo.ROOT / "core" / ".venv" / "bin" / name) for name in demo.COMMANDS)}
    host.interpreters = {
        str(demo.ROOT / "core" / ".venv" / "bin" / name): str(demo.ROOT / "core" / ".venv" / "bin" / "python3")
        for name in demo.COMMANDS
    }
    host.answer("docker", "info")
    host.answer("docker", "compose", "version")
    host.answers[("docker", "ps")] = host.containers
    host.answers[("docker", "network", "ls")] = host.network_ids
    host.answers[("docker", "network", "inspect")] = host.networks_inspected
    host.answers[("docker", "image", "inspect")] = host.image_inspected
    host.answers[("docker", "pull")] = host.pulled
    host.networks = [("bridge", ["172.17.0.0/16"]), ("host", []), ("none", [])]
    host.images = {"ghcr.io/nokia/srlinux:24.7.1", "alpine:3.24.2"}
    host.answer("containerlab", "version")
    host.answers[("ss", "-Hltn")] = host.heard
    host.answers[("ss", "-Hltnp")] = host.heard
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
