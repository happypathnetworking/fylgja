"""`scripts/nautobot_dev.py`: the development Nautobot's lines in `local/.env`, its Compose project and its waits.

No test here opens a socket or starts a process but `make -n`, which prints a recipe and runs none of it: `run`,
`health`, `info`, `clock` and `sleep` are fakes, `urllib.request.urlopen` is replaced where the real requests are read,
and every file is under `tmp_path`.
"""

from __future__ import annotations

import email.message
import io
import json
import os
import re
import stat
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import nautobot_dev
import netbox_dev
import pytest
from nautobot_dev import ADDRESS, NAMES, SECRETS, WRITE_TOKEN, Refused, Status, Versions

ROOT = Path(__file__).resolve().parents[2]
V = Versions("3.2.8", "3.0.8", "3.14")
RIGHT = Status("3.2.8", "3.0.8", 1)
BUILD = ["build", "nautobot"]
UP = ["up", "-d", "--quiet-pull"]
TOKEN = "0123456789abcdef0123456789abcdef01234567"
"""A token of the form Nautobot's superuser's is: 40 lowercase hex characters."""


def dev(local: Path) -> Path:
    return local / "dev"


def assignments(path: Path) -> dict[str, str]:
    """The file's `NAME=value` lines, as a shell reads them unquoted."""
    found: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            found[name] = value
    return found


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


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


KEPT = (
    "FYLGJA_NAUTOBOT_VERSION",
    "FYLGJA_GOLDEN_CONFIG_VERSION",
    "FYLGJA_NAUTOBOT_PYTHON",
    "FYLGJA_NAUTOBOT_DEV",
    "FYLGJA_NAUTOBOT_GIT",
)
"""The variables of Compose's environment the tests read; the fake keeps the names of the rest and no value."""


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from an environment of its own, `PATH` alone, so none holds the developer's (a shell may
    have `local/.env` loaded) where an assertion or a local could show it."""
    path = os.environ.get("PATH", "")
    for name in list(os.environ):
        if name != "PYTEST_CURRENT_TEST":
            monkeypatch.delenv(name)
    monkeypatch.setenv("PATH", path)


class Run:
    """Compose's fake: each call's arguments, the values of `KEPT` and the names of the rest of its environment, and
    its statuses answered in turn (0 where none are left)."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.names: list[list[str]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.calls.append((list(argv), {name: env[name] for name in KEPT if name in env}))
        self.names.append(sorted(env))
        return self.statuses.pop(0) if self.statuses else 0

    def verbs(self) -> list[list[str]]:
        return [argv[len(nautobot_dev.compose(Path("l"), Path("d"))) :] for argv, _ in self.calls]


class Health:
    """`/health/`'s fake: None until `quiet`, 503 until `ready`, 200 from it, by the clock; the addresses asked."""

    def __init__(self, clock: Clock, quiet: float = 0.0, ready: float = 0.0) -> None:
        self.clock = clock
        self.quiet, self.ready = quiet, ready
        self.addresses: list[str] = []

    def __call__(self, address: str) -> int | None:
        self.addresses.append(address)
        if self.clock.now < self.quiet:
            return None
        return 503 if self.clock.now < self.ready else 200


class Info:
    """`/api/status/`'s fake: answers in turn (the last kept), `Refused` for a token of `refused`, and the tokens
    asked with."""

    def __init__(self, *answers: Status | None, refused: Sequence[str] = ()) -> None:
        self.answers = list(answers) or [RIGHT]
        self.refused = set(refused)
        self.tokens: list[str] = []
        self.addresses: list[str] = []

    def __call__(self, address: str, token: str) -> Status | None:
        self.addresses.append(address)
        self.tokens.append(token)
        if token in self.refused or "*" in self.refused:
            raise Refused(f"{address} refuses the token")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def never(*args: object) -> None:
    raise AssertionError("called where nothing may be")


def start(
    local: Path,
    run: Run,
    *,
    health: Callable[[str], int | None] | None = None,
    info: Callable[[str, str], Status | None] | None = None,
    clock: Clock | None = None,
) -> int:
    clock = clock or Clock()
    return nautobot_dev.up(
        local,
        V,
        dev=dev(local),
        run=run,
        health=health or Health(clock),
        info=info or Info(),
        clock=clock,
        sleep=clock.sleep,
    )


def seeded(local: Path, *extra: str) -> bytes:
    """`local/.env` holding the five names, then `extra`'s lines; its bytes."""
    env = local / ".env"
    nautobot_dev.write_env(env)
    if extra:
        env.write_bytes(env.read_bytes() + "".join(f"{line}\n" for line in extra).encode())
    return env.read_bytes()


def test_a_fresh_file_holds_the_five_names_at_0600(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert nautobot_dev.write_env(env) == list(NAMES)
    assert mode(env) == 0o600
    lines = assignments(env)
    assert list(lines) == list(NAMES)
    assert lines["FYLGJA_NAUTOBOT_ADDRESS"] == ADDRESS
    assert NAMES[:4] == SECRETS and NAMES[3] == WRITE_TOKEN
    for name in SECRETS[:3]:
        assert re.fullmatch(r"[A-Za-z0-9_-]{64}", lines[name]), name
    assert re.fullmatch(r"[0-9a-f]{40}", lines[WRITE_TOKEN])
    assert len({lines[name] for name in SECRETS}) == len(SECRETS)


def test_every_line_present_is_kept_and_only_missing_names_are_added(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    kept = b"FYLGJA_API_TOKEN=abc\n# note\nFYLGJA_NAUTOBOT_DB_PASSWORD=kept\n"
    env.write_bytes(kept)
    env.chmod(0o644)
    added = nautobot_dev.write_env(env)
    assert added == [name for name in NAMES if name != "FYLGJA_NAUTOBOT_DB_PASSWORD"]
    written = env.read_bytes()
    assert written.startswith(kept)
    assert assignments(env)["FYLGJA_NAUTOBOT_DB_PASSWORD"] == "kept"
    assert mode(env) == 0o600
    assert nautobot_dev.write_env(env) == []
    assert env.read_bytes() == written

    unended = tmp_path / "unended.env"
    unended.write_bytes(b"FYLGJA_API_TOKEN=abc")
    nautobot_dev.write_env(unended)
    assert unended.read_bytes().startswith(b"FYLGJA_API_TOKEN=abc\n")
    assert assignments(unended)["FYLGJA_API_TOKEN"] == "abc"


@pytest.mark.parametrize("value", ["", '""', " # note"], ids=["empty", "quotes", "a-comment"])
def test_a_name_held_with_no_value_is_refused_before_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """A shell reads `NAME= # note` as empty; Compose would read it as the text `# note`."""
    env = tmp_path / ".env"
    held = f"FYLGJA_API_TOKEN=abc\nFYLGJA_NAUTOBOT_SECRET_KEY={value}\n".encode()
    env.write_bytes(held)
    env.chmod(0o644)
    run = Run()
    assert start(tmp_path, run, health=never, info=never) == 2
    assert env.read_bytes() == held and mode(env) == 0o644
    assert run.calls == []
    assert not (tmp_path / "nautobot").exists()
    err = capsys.readouterr().err
    assert "FYLGJA_NAUTOBOT_SECRET_KEY" in err and "abc" not in err
    assert nautobot_dev.main(["env", "--local", str(tmp_path)]) == 2
    assert env.read_bytes() == held
    assert "FYLGJA_NAUTOBOT_SECRET_KEY" in capsys.readouterr().err


def test_the_env_files_rules_are_netbox_devs() -> None:
    """Each script runs alone under `python3 -I` and imports no other, so `nautobot_dev.py` holds its own copy of
    `netbox_dev.py`'s rules for reading `local/.env`; the one file is read by both, and the copies are held equal
    here, so that neither changes alone. The same lines parse alike."""
    for rule in ("ASSIGNMENT", "QUOTED", "COMMENT"):
        ours, theirs = getattr(nautobot_dev, rule), getattr(netbox_dev, rule)
        assert (ours.pattern, ours.flags) == (theirs.pattern, theirs.flags), rule
    assert nautobot_dev.EMPTY == netbox_dev.EMPTY
    held = (
        b"A=1\nexport B='two words' # note\n  C = 3\nD=4 # note\nE=\"q\"\n# F=6\nG=7\nG=8\nH=\nI=a#b\n"
        b"export J=\"\"\nbad line\n"
    )
    assert nautobot_dev.assignments(held) == netbox_dev.assignments(held)


def test_the_env_step_prints_names_and_no_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert nautobot_dev.main(["env", "--local", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    printed = out + err
    for name in NAMES:
        assert name in printed
    for name, value in assignments(tmp_path / ".env").items():
        if value != ADDRESS:
            assert value not in printed, name


def test_every_compose_command_names_the_project_the_directory_and_the_file(tmp_path: Path) -> None:
    local, where = tmp_path / "local", tmp_path / "dev"
    assert nautobot_dev.compose(local, where) == [
        "docker",
        "compose",
        "-p",
        "fylgja-core-nautobot",
        "--project-directory",
        str(local / "nautobot"),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(where / "compose.yml"),
    ]
    assert nautobot_dev.DEV == ROOT / "nautobot" / "dev"


def test_the_versions_and_the_directories_are_set_over_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    where, git = tmp_path / "dev", tmp_path / "git"
    base = {"FYLGJA_NAUTOBOT_VERSION": "9", "FYLGJA_NAUTOBOT_DB_PASSWORD": "x", "PATH": "/bin"}
    assert nautobot_dev.compose_env(V, where, git, base) == {
        "FYLGJA_NAUTOBOT_VERSION": "3.2.8",
        "FYLGJA_GOLDEN_CONFIG_VERSION": "3.0.8",
        "FYLGJA_NAUTOBOT_PYTHON": "3.14",
        "FYLGJA_NAUTOBOT_DEV": str(where),
        "FYLGJA_NAUTOBOT_GIT": str(git),
        "PATH": "/bin",
    }
    for name in NAMES:
        monkeypatch.setenv(name, "exported-in-the-shell")
    monkeypatch.setenv("FYLGJA_NAUTOBOT_VERSION", "9")
    monkeypatch.setenv("FYLGJA_GOLDEN_CONFIG_VERSION", "9")
    run = Run()
    assert start(tmp_path, run) == 0
    for (_, given), names in zip(run.calls, run.names, strict=True):
        assert given == {
            "FYLGJA_NAUTOBOT_VERSION": "3.2.8",
            "FYLGJA_GOLDEN_CONFIG_VERSION": "3.0.8",
            "FYLGJA_NAUTOBOT_PYTHON": "3.14",
            "FYLGJA_NAUTOBOT_DEV": str(dev(tmp_path)),
            "FYLGJA_NAUTOBOT_GIT": str(tmp_path / "nautobot" / "git"),
        }
        assert not set(names) & set(NAMES)


def test_up_makes_the_served_directory_and_builds_before_it_starts(tmp_path: Path) -> None:
    run = Run()
    assert start(tmp_path, run) == 0
    assert run.verbs()[:2] == [BUILD, UP]
    assert (tmp_path / "nautobot" / "git").is_dir()
    prefix = nautobot_dev.compose(tmp_path, dev(tmp_path))
    assert all(argv[: len(prefix)] == prefix for argv, _ in run.calls)

    run = Run(1)
    assert start(tmp_path, run, health=never, info=never) == 1
    assert run.verbs() == [BUILD]

    run = Run(0, 1)
    assert start(tmp_path, run, health=never, info=never) == 1
    assert run.verbs() == [BUILD, UP]


def test_up_waits_for_health_from_the_host_and_never_asks_docker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    run, health = Run(), Health(clock, quiet=300, ready=600)
    assert start(tmp_path, run, health=health, clock=clock) == 0
    assert len(health.addresses) > 3 and set(health.addresses) == {ADDRESS}
    assert 600 <= clock.now <= 600 + nautobot_dev.POLL_S
    assert set(clock.slept) == {nautobot_dev.POLL_S}
    assert all("ps" not in verb and "inspect" not in verb for verb in run.verbs())

    clock = Clock()
    run = Run()
    assert start(tmp_path, run, health=Health(clock, ready=10_000), clock=clock, info=never) == 1
    assert nautobot_dev.UP_WAIT_S == 1200
    assert 1200 <= clock.now <= 1200 + nautobot_dev.POLL_S
    assert run.verbs() == [BUILD, UP]
    err = capsys.readouterr().err
    assert "1200 s" in err and "docker compose -p fylgja-core-nautobot logs nautobot" in err


@pytest.mark.parametrize(
    ("status", "named"),
    [
        (Status("3.2.7", "3.0.8", 1), ("3.2.7", "3.2.8", "3.0.8")),
        (Status("3.2.8", "3.1.0", 1), ("3.1.0", "3.0.8", "3.2.8")),
        (Status("3.2.8", None, 1), ("nautobot_golden_config", "nautobot_config.py")),
    ],
    ids=["another-nautobot", "another-golden-config", "no-golden-config"],
)
def test_up_fails_on_another_version_no_golden_config_and_no_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status: Status, named: tuple[str, ...]
) -> None:
    clock = Clock()
    assert start(tmp_path, Run(), info=Info(status), clock=clock) == 1
    assert clock.slept == []
    err = capsys.readouterr().err
    for text in named:
        assert text in err

    clock = Clock()
    assert start(tmp_path, Run(), info=Info(Status("3.2.8", "3.0.8", 0)), clock=clock) == 1
    assert 60 <= clock.now <= 60 + nautobot_dev.POLL_S
    assert "worker" in capsys.readouterr().err

    clock = Clock()
    assert start(tmp_path, Run(), info=Info(None, None, RIGHT), clock=clock) == 0
    assert clock.slept == [nautobot_dev.POLL_S, nautobot_dev.POLL_S]

    clock = Clock()
    assert start(tmp_path, Run(), info=Info(None), clock=clock) == 1
    assert nautobot_dev.STATUS_WAIT_S == 60
    assert 60 <= clock.now <= 60 + nautobot_dev.POLL_S
    assert "did not answer" in capsys.readouterr().err


def test_a_token_nautobot_refuses_ends_with_the_purge_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The entrypoint takes the line's token at each start, so a refusal is something else: no second try, nothing
    written, and the remedy is a purge."""
    before = seeded(tmp_path, "FYLGJA_API_TOKEN=abc")
    info = Info(refused=["*"])
    assert start(tmp_path, Run(), info=info) == 1
    assert len(info.tokens) == 1
    assert info.tokens == [assignments(tmp_path / ".env")[WRITE_TOKEN]]
    assert "make nautobot-down PURGE=1" in capsys.readouterr().err
    assert (tmp_path / ".env").read_bytes() == before


def test_up_asks_with_the_token_the_file_holds(tmp_path: Path) -> None:
    before = seeded(tmp_path, f"{WRITE_TOKEN}={TOKEN}", "FYLGJA_API_TOKEN=abc")
    info = Info()
    assert start(tmp_path, Run(), info=info) == 0
    assert set(info.tokens) == {TOKEN} and set(info.addresses) == {ADDRESS}
    assert (tmp_path / ".env").read_bytes() == before


def test_no_output_of_up_holds_a_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = Clock()
    assert start(tmp_path, Run(), health=Health(clock, ready=30), clock=clock, info=Info(None, RIGHT)) == 0
    out, err = capsys.readouterr()
    printed = out + err
    assert out
    held = assignments(tmp_path / ".env")
    for name in SECRETS:
        assert held[name] not in printed, name

    local = tmp_path / "refused"
    seeded(local)
    assert start(local, Run(), info=Info(refused=["*"])) == 1
    out, err = capsys.readouterr()
    for name in SECRETS:
        assert assignments(local / ".env")[name] not in out + err, name


class Answer(io.BytesIO):
    """A response of urlopen's: its body and its status."""

    def __init__(self, body: bytes, status: int) -> None:
        super().__init__(body)
        self.status = status


def refusal(url: str, code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "Forbidden", email.message.Message(), io.BytesIO(body))


def test_the_status_is_read_with_the_token_and_a_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/api/status/` names the versions, the apps and `celery-workers-running`; it answers 403 without a token or
    with one Nautobot never made (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8")."""
    asked: list[urllib.request.Request] = []
    answers: list[Answer | urllib.error.HTTPError | OSError] = [
        Answer(
            json.dumps(
                {
                    "nautobot-version": "3.2.8",
                    "nautobot-apps": {"nautobot_golden_config": "3.0.8", "nautobot_plugin_nornir": "3.4.0"},
                    "celery-workers-running": 1,
                }
            ).encode(),
            200,
        ),
        Answer(
            json.dumps({"nautobot-version": "3.2.8", "nautobot-apps": {}, "celery-workers-running": 0}).encode(), 200
        ),
        Answer(b"<html>", 200),
        OSError("connection reset"),
        refusal("status", 502, b"Bad Gateway"),
        refusal("status", 403, b'{"detail": "Invalid token"}'),
    ]

    def urlopen(request: urllib.request.Request, timeout: float) -> Answer:
        asked.append(request)
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert nautobot_dev.ask_status(ADDRESS, TOKEN) == RIGHT
    assert nautobot_dev.ask_status(ADDRESS, TOKEN) == Status("3.2.8", None, 0)
    assert nautobot_dev.ask_status(ADDRESS, TOKEN) is None
    assert nautobot_dev.ask_status(ADDRESS, TOKEN) is None
    assert nautobot_dev.ask_status(ADDRESS, TOKEN) is None
    with pytest.raises(Refused) as refused:
        nautobot_dev.ask_status(ADDRESS, TOKEN)
    assert TOKEN not in str(refused.value)
    assert {request.full_url for request in asked} == {ADDRESS + "/api/status/"}
    assert {request.get_header("Authorization") for request in asked} == {f"Token {TOKEN}"}


def test_the_health_is_the_status_of_a_get_and_none_where_nothing_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    answers: list[Answer | urllib.error.HTTPError | OSError] = [
        Answer(b"{}", 200),
        refusal("health", 503, b"unhealthy"),
        OSError("connection reset"),
    ]

    def urlopen(url: str, timeout: float) -> Answer:
        asked.append(url)
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert [nautobot_dev.ask_health(ADDRESS) for _ in range(3)] == [200, 503, None]
    assert set(asked) == {ADDRESS + "/health/"}


def test_down_stops_and_only_purge_1_removes_the_volumes(tmp_path: Path) -> None:
    where, env = dev(tmp_path), tmp_path / ".env"
    env.write_text("FYLGJA_API_TOKEN=abc\n")

    run = Run()
    assert nautobot_dev.down(tmp_path, V, dev=where, purge=False, run=run) == 0
    [(argv, given)] = run.calls
    assert argv == [*nautobot_dev.compose(tmp_path, where), "stop", "--timeout", "60"]
    assert nautobot_dev.STOP_TIMEOUT_S == 60
    assert given["FYLGJA_NAUTOBOT_DEV"] == str(where)

    run = Run()
    assert nautobot_dev.down(tmp_path, V, dev=where, purge=True, run=run) == 0
    [(argv, _)] = run.calls
    assert argv == [*nautobot_dev.compose(tmp_path, where), "down", "-v"]
    assert env.read_text() == "FYLGJA_API_TOKEN=abc\n"

    assert nautobot_dev.down(tmp_path, V, dev=where, purge=False, run=Run(1)) == 1
    assert nautobot_dev.down(tmp_path, V, dev=where, purge=True, run=Run(1)) == 1


@pytest.mark.parametrize(("purge", "purges"), [("1", True), ("0", False), ("true", False), (None, False)])
def test_only_purge_1_purges(tmp_path: Path, purge: str | None, purges: bool) -> None:
    """`make -n` prints `nautobot-down`'s recipe and runs none of it."""
    argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), "nautobot-down", f"LOCAL={tmp_path}"]
    done = subprocess.run(
        [*argv, *([f"PURGE={purge}"] if purge is not None else [])],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    [recipe] = [line for line in done.stdout.splitlines() if "nautobot_dev.py down" in line]
    assert ("--purge" in recipe.split()) is purges
    for flag in ("--nautobot 3.2.8", "--golden-config 3.0.8", "--python 3.14"):
        assert flag in recipe


def test_main_hands_down_its_versions_and_purge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    given: list[tuple[Path, Versions, bool]] = []

    def down(local: Path, versions: Versions, *, dev: Path, purge: bool, run: object) -> int:
        assert dev == nautobot_dev.DEV
        given.append((local, versions, purge))
        return 1

    monkeypatch.setattr(nautobot_dev, "down", down)
    flags = ["--local", str(tmp_path), "--nautobot", "3.2.8", "--golden-config", "3.0.8", "--python", "3.14"]
    assert nautobot_dev.main(["down", *flags, "--purge"]) == 1
    assert nautobot_dev.main(["down", *flags]) == 1
    assert given == [(tmp_path, V, True), (tmp_path, V, False)]


FLAGS = ["--local", "l", "--golden-config", "3.0.8", "--python", "3.14"]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["start"],
        ["env"],
        ["up", *FLAGS],
        ["up", "--local", "l", "--nautobot", "3.2.8", "--golden-config", "3.0.8", "--python", "latest"],
        ["up", "--local", "l", "--nautobot", "3.2.8", "--golden-config", "3", "--python", "3.14"],
        ["up", *FLAGS, "--nautobot", "3.2.8", "--purge"],
    ],
    ids=[
        "no-verb",
        "an-unknown-verb",
        "env-without-local",
        "up-without-nautobot",
        "python-latest",
        "golden-config-3",
        "up-with-purge",
    ],
)
def test_a_command_line_that_is_not_understood_is_exit_2(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: object, **kwargs: object) -> int:
        raise AssertionError("a command line not understood reached a verb")

    for verb in ("write_env", "up", "down"):
        monkeypatch.setattr(nautobot_dev, verb, refused)
    assert nautobot_dev.main(argv) == 2
