"""`scripts/infrahub_dev.py`: the development Infrahub's lines in `local/.env`, its Compose project and its wait.

No test here opens a socket or starts a process but `make -n`, which prints a recipe and runs none of it: `run`,
`fetch`, `info`, `clock` and `sleep` are fakes, and every file is under `tmp_path`.
"""

from __future__ import annotations

import io
import ipaddress
import os
import re
import stat
import subprocess
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

import infrahub_dev
import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.11.11"
SECRETS = (
    "INFRAHUB_INITIAL_ADMIN_TOKEN",
    "INFRAHUB_INITIAL_AGENT_TOKEN",
    "INFRAHUB_INITIAL_ADMIN_PASSWORD",
    "INFRAHUB_SECURITY_SECRET_KEY",
)
TOKENS = ("INFRAHUB_INITIAL_ADMIN_TOKEN", "FYLGJA_INFRAHUB_WRITE_TOKEN", "FYLGJA_INFRAHUB_TOKEN")
UP = ["up", "-d", "--quiet-pull"]


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


KEPT = ("VERSION", "FYLGJA_INFRAHUB_REPO", "FYLGJA_INFRAHUB_REPOS")
"""The variables of Compose's environment the tests read; the fake keeps no other value of it."""


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
    """Compose's fake: each call's arguments, the values of `KEPT`, the names of `NAMES` and every other name
    beginning `INFRAHUB_` its environment held, and its statuses answered in turn."""

    def __init__(self, *statuses: int, seen: Callable[[], object] | None = None) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.names: list[list[str]] = []
        self.seen = seen
        self.first: object = None

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        if not self.calls and self.seen is not None:
            self.first = self.seen()
        self.calls.append((list(argv), {name: env[name] for name in KEPT if name in env}))
        self.names.append(sorted(name for name in env if name in infrahub_dev.NAMES or name.startswith("INFRAHUB_")))
        return self.statuses.pop(0)


class Fetch:
    """The published file's fake: the URLs asked kept, a file written, and an error raised after it where asked."""

    def __init__(self, *, fail: bool = False) -> None:
        self.urls: list[str] = []
        self.fail = fail

    def __call__(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        dest.write_bytes(b"services: {}\n")
        if self.fail:
            raise OSError("the connection was reset")


def answering(version: str | None, clock: Clock, *, from_s: float = 0.0) -> Callable[[str], str | None]:
    """`/api/info`'s fake: no answer before `from_s` on the clock, then `version`."""

    def info(address: str) -> str | None:
        return version if clock.now >= from_s else None

    return info


def start(
    local: Path,
    run: Run,
    *,
    fetch: Fetch | None = None,
    info: Callable[[str], str | None] | None = None,
    clock: Clock | None = None,
) -> int:
    clock = clock or Clock()
    return infrahub_dev.up(
        local,
        VERSION,
        local / "override.yml",
        local / "checkout" / ".git",
        run=run,
        fetch=fetch or Fetch(),
        info=info or answering(VERSION, clock),
        clock=clock,
        sleep=clock.sleep,
    )


def test_a_fresh_file_holds_the_eight_names_at_0600(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert infrahub_dev.write_env(env) == list(infrahub_dev.NAMES)
    assert mode(env) == 0o600
    lines = assignments(env)
    assert list(lines) == list(infrahub_dev.NAMES)
    assert lines["FYLGJA_INFRAHUB_ADDRESS"] == infrahub_dev.ADDRESS
    address = urlsplit(infrahub_dev.ADDRESS)
    assert address.scheme == "http" and address.port == 8000
    assert address.hostname is not None and ipaddress.ip_address(address.hostname).is_loopback
    assert lines["INFRAHUB_TELEMETRY_OPTOUT"] == "true"
    for name in SECRETS:
        assert re.fullmatch(r"[A-Za-z0-9_-]{16,}", lines[name]), name
    assert len({lines[name] for name in SECRETS}) == len(SECRETS)
    assert {lines[name] for name in TOKENS} == {lines["INFRAHUB_INITIAL_ADMIN_TOKEN"]}


def test_every_line_present_is_kept_and_only_missing_names_are_added(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    kept = b"FYLGJA_API_TOKEN=abc\n# note\nINFRAHUB_INITIAL_ADMIN_TOKEN=kept\n"
    env.write_bytes(kept)
    env.chmod(0o644)
    added = infrahub_dev.write_env(env)
    assert added == [name for name in infrahub_dev.NAMES if name != "INFRAHUB_INITIAL_ADMIN_TOKEN"]
    written = env.read_bytes()
    assert written.startswith(kept)
    lines = assignments(env)
    assert lines["FYLGJA_INFRAHUB_TOKEN"] == "kept"
    assert lines["FYLGJA_INFRAHUB_WRITE_TOKEN"] == "kept"
    assert mode(env) == 0o600
    assert infrahub_dev.write_env(env) == []
    assert env.read_bytes() == written


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("INFRAHUB_INITIAL_ADMIN_TOKEN", ""),
        ("FYLGJA_INFRAHUB_TOKEN", '""'),
        ("INFRAHUB_TELEMETRY_OPTOUT", "   "),
        ("INFRAHUB_SECURITY_SECRET_KEY", " # a note"),
        ("INFRAHUB_INITIAL_AGENT_TOKEN", '"" # a note'),
        ("FYLGJA_INFRAHUB_WRITE_TOKEN", "kept\nFYLGJA_INFRAHUB_WRITE_TOKEN="),
    ],
    ids=["empty", "quotes", "spaces", "a-comment", "quotes-and-a-comment", "the-last-of-two"],
)
def test_a_name_held_with_no_value_is_refused_before_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, value: str
) -> None:
    """A shell reads `NAME= # a note` as empty, and takes the last of two lines of one name."""
    env = tmp_path / ".env"
    held = f"FYLGJA_API_TOKEN=abc\n{name}={value}\n".encode()
    env.write_bytes(held)
    env.chmod(0o644)
    run, fetch = Run(), Fetch()
    assert start(tmp_path, run, fetch=fetch) == 2
    assert env.read_bytes() == held and mode(env) == 0o644
    assert run.calls == [] and fetch.urls == []
    assert not (tmp_path / "infrahub").exists()
    err = capsys.readouterr().err
    assert name in err and "delete" in err and "abc" not in err
    assert infrahub_dev.main(["env", "--local", str(tmp_path)]) == 2
    assert env.read_bytes() == held
    assert name in capsys.readouterr().err


def test_the_last_of_two_lines_of_a_name_holds_it_and_a_comment_is_no_value(tmp_path: Path) -> None:
    """A shell takes the last of two lines of one name, and ends an unquoted value where a `#` begins a word, which
    one inside a word does not."""
    env = tmp_path / ".env"
    kept = (
        b"INFRAHUB_INITIAL_ADMIN_TOKEN=first\n"
        b"INFRAHUB_INITIAL_ADMIN_TOKEN=last # the admin's\n"
        b"INFRAHUB_INITIAL_AGENT_TOKEN=\n"
        b"INFRAHUB_INITIAL_AGENT_TOKEN=agent#1\n"
    )
    env.write_bytes(kept)
    added = infrahub_dev.write_env(env)
    held = ("INFRAHUB_INITIAL_ADMIN_TOKEN", "INFRAHUB_INITIAL_AGENT_TOKEN")
    assert added == [name for name in infrahub_dev.NAMES if name not in held]
    assert env.read_bytes().startswith(kept)
    lines = assignments(env)
    assert lines["FYLGJA_INFRAHUB_WRITE_TOKEN"] == "last"
    assert lines["FYLGJA_INFRAHUB_TOKEN"] == "last"


def test_a_name_commented_out_is_lacking(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    held = b"# INFRAHUB_INITIAL_ADMIN_TOKEN=\n"
    env.write_bytes(held)
    assert infrahub_dev.write_env(env) == list(infrahub_dev.NAMES)
    assert env.read_bytes().startswith(held)
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,}", assignments(env)["INFRAHUB_INITIAL_ADMIN_TOKEN"])


def test_a_last_line_with_no_newline_is_kept_and_ended(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_bytes(b"FYLGJA_API_TOKEN=abc")
    infrahub_dev.write_env(env)
    assert env.read_bytes().startswith(b"FYLGJA_API_TOKEN=abc\n")
    assert assignments(env)["FYLGJA_API_TOKEN"] == "abc"


def test_the_env_step_prints_names_and_no_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert infrahub_dev.main(["env", "--local", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    printed = out + err
    for name in infrahub_dev.NAMES:
        assert name in printed
    for name, value in assignments(tmp_path / ".env").items():
        if value not in ("true", infrahub_dev.ADDRESS):
            assert value not in printed, name


def test_every_compose_command_names_the_project_the_directory_and_both_files(tmp_path: Path) -> None:
    local, override = tmp_path / "local", tmp_path / "override.yml"
    assert infrahub_dev.compose(local, VERSION, override) == [
        "docker",
        "compose",
        "-p",
        "fylgja-core-infrahub",
        "--project-directory",
        str(local / "infrahub"),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(local / "infrahub" / "docker-compose-1.11.11.yml"),
        "-f",
        str(override),
    ]


def test_the_version_and_the_mount_are_set_over_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, repos = tmp_path / "checkout" / ".git", tmp_path / "repos"
    assert infrahub_dev.compose_env(VERSION, repo, repos, {"VERSION": "9.9.9", "PATH": "/bin"}) == {
        "VERSION": VERSION,
        "FYLGJA_INFRAHUB_REPO": str(repo),
        "FYLGJA_INFRAHUB_REPOS": str(repos),
        "PATH": "/bin",
    }
    monkeypatch.setenv("VERSION", "9.9.9")
    made = tmp_path / "infrahub" / "repos"
    run = Run(0, seen=lambda: made.is_dir() and mode(made))
    assert start(tmp_path, run) == 0
    assert run.first == 0o700
    assert mode(made) == 0o700
    env = run.calls[0][1]
    assert env["VERSION"] == VERSION
    assert env["FYLGJA_INFRAHUB_REPOS"] == str(made)
    assert env["FYLGJA_INFRAHUB_REPO"] == str(tmp_path / "checkout" / ".git")


def test_compose_takes_the_eight_names_from_the_env_file_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name exported in the shell, with a value or empty, would win over `--env-file`'s line, and any other
    `INFRAHUB_*` the shell exports over the published file's default: `INFRAHUB_ADDRESS` set for a client on the
    host would be the task workers' address of Infrahub."""
    repo, repos = tmp_path / "checkout" / ".git", tmp_path / "repos"
    exported = {
        "INFRAHUB_INITIAL_ADMIN_TOKEN": "exported-in-the-shell",
        "FYLGJA_INFRAHUB_WRITE_TOKEN": "",
        "INFRAHUB_ADDRESS": infrahub_dev.ADDRESS,
    }
    assert infrahub_dev.compose_env(VERSION, repo, repos, {**exported, "VERSION": "9.9.9", "PATH": "/bin"}) == {
        "VERSION": VERSION,
        "FYLGJA_INFRAHUB_REPO": str(repo),
        "FYLGJA_INFRAHUB_REPOS": str(repos),
        "PATH": "/bin",
    }
    for name, value in exported.items():
        monkeypatch.setenv(name, value)
    run = Run(0, 0)
    assert start(tmp_path, run) == 0
    assert infrahub_dev.down(tmp_path, VERSION, tmp_path / "override.yml", repo, purge=False, run=run) == 0
    assert run.names == [[], []]
    assert [given["VERSION"] for _, given in run.calls] == [VERSION, VERSION]
    assert all(set(given) == set(KEPT) for _, given in run.calls)


def test_the_fake_compose_keeps_no_other_value_of_its_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FYLGJA_API_TOKEN", "a-value-no-test-may-hold")
    run = Run(0, 0)
    assert start(tmp_path, run) == 0
    assert infrahub_dev.down(tmp_path, VERSION, tmp_path / "override.yml", tmp_path / ".git", purge=False, run=run) == 0
    assert "a-value-no-test-may-hold" not in repr(vars(run))


def test_up_keeps_what_the_mirror_directory_holds(tmp_path: Path) -> None:
    held = tmp_path / "infrahub" / "repos" / "repo.git" / "HEAD"
    held.parent.mkdir(parents=True)
    held.write_text("ref: refs/heads/main\n")
    assert start(tmp_path, Run(0)) == 0
    assert held.read_text() == "ref: refs/heads/main\n"


def test_up_writes_the_missing_names_before_compose_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    run = Run(0, seen=lambda: list(assignments(env)))
    assert start(tmp_path, run) == 0
    assert run.first == list(infrahub_dev.NAMES)
    out, err = capsys.readouterr()
    for name, value in assignments(env).items():
        if value not in ("true", infrahub_dev.ADDRESS):
            assert value not in out + err, name


def test_up_fetches_the_versions_file_once(tmp_path: Path) -> None:
    fetch = Fetch()
    assert start(tmp_path, Run(0), fetch=fetch) == 0
    assert start(tmp_path, Run(0), fetch=fetch) == 0
    url = infrahub_dev.COMPOSE_URL.format(version=VERSION)
    assert fetch.urls == [url]
    assert urlsplit(url).scheme == "https" and urlsplit(url).path == f"/{VERSION}"
    assert (tmp_path / "infrahub" / "docker-compose-1.11.11.yml").read_bytes() == b"services: {}\n"

    local = tmp_path / "again"
    run = Run()
    assert start(local, run, fetch=Fetch(fail=True)) == 1
    assert list((local / "infrahub").glob("docker-compose-1.11.11.yml*")) == []
    assert run.calls == []


def test_the_fetch_names_itself_to_the_published_files_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The server refused urllib's own User-Agent with 403 (design/verified-facts.md, "Infrahub 1.11.11")."""
    asked: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        asked.append(request)
        return io.BytesIO(b"services: {}\n")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    url = infrahub_dev.COMPOSE_URL.format(version=VERSION)
    infrahub_dev.fetch_url(url, tmp_path / "published.yml")
    [request] = asked
    assert request.full_url == url
    agent = request.get_header("User-agent")
    assert agent == infrahub_dev.USER_AGENT and not agent.startswith("Python-urllib")
    assert (tmp_path / "published.yml").read_bytes() == b"services: {}\n"


def test_up_asks_compose_once_more_when_the_first_start_fails(tmp_path: Path) -> None:
    run = Run(1, 0)
    assert start(tmp_path, run) == 0
    assert [argv[-3:] for argv, _ in run.calls] == [UP, UP]
    assert run.calls[0][0][:-3] == infrahub_dev.compose(tmp_path, VERSION, tmp_path / "override.yml")

    run = Run(1, 1)
    asked: list[str] = []

    def info(address: str) -> str | None:
        asked.append(address)
        return VERSION

    assert start(tmp_path, run, info=info) == 1
    assert len(run.calls) == 2
    assert asked == []


def test_up_waits_for_the_version_and_ends_at_its_bound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    assert start(tmp_path, Run(0), info=answering(VERSION, clock, from_s=159), clock=clock) == 0
    assert 159 <= clock.now <= 159 + infrahub_dev.POLL_S
    assert set(clock.slept) == {infrahub_dev.POLL_S}
    capsys.readouterr()

    clock = Clock()
    assert start(tmp_path, Run(0), info=answering("1.11.2", clock), clock=clock) == 1
    assert clock.slept == []
    err = capsys.readouterr().err
    assert "1.11.2" in err and VERSION in err

    clock = Clock()
    assert start(tmp_path, Run(0), info=answering(None, clock), clock=clock) == 1
    assert infrahub_dev.UP_WAIT_S == 600
    assert 600 <= clock.now <= 600 + infrahub_dev.POLL_S
    assert "600 s" in capsys.readouterr().err


def test_down_stops_and_a_purge_removes_the_volumes_and_the_seed_file(tmp_path: Path) -> None:
    override, repo = tmp_path / "override.yml", tmp_path / "checkout" / ".git"
    fetched = tmp_path / "infrahub" / "docker-compose-1.11.11.yml"
    seed, env = tmp_path / "infrahub" / "seed.json", tmp_path / ".env"
    fetched.parent.mkdir(parents=True)
    for path in (fetched, seed, env):
        path.write_text("{}\n")

    run = Run(0)
    assert infrahub_dev.down(tmp_path, VERSION, override, repo, purge=False, run=run) == 0
    [(argv, given)] = run.calls
    assert argv[:-2] == [*infrahub_dev.compose(tmp_path, VERSION, override), "stop"]
    assert given["VERSION"] == VERSION and given["FYLGJA_INFRAHUB_REPO"] == str(repo)
    assert seed.exists()

    run = Run(0)
    assert infrahub_dev.down(tmp_path, VERSION, override, repo, purge=True, run=run) == 0
    [(argv, _)] = run.calls
    assert argv[-2:] == ["down", "-v"]
    assert not seed.exists()
    assert env.exists() and fetched.exists()


def test_the_stop_gives_each_service_the_stop_timeout(tmp_path: Path) -> None:
    """Compose's own grace of 10 s ended in Neo4j killed, 137 (design/verified-facts.md, "Infrahub 1.11.11")."""
    override, repo = tmp_path / "override.yml", tmp_path / ".git"
    run = Run(0)
    assert infrahub_dev.down(tmp_path, VERSION, override, repo, purge=False, run=run) == 0
    [(argv, _)] = run.calls
    timeout = infrahub_dev.STOP_TIMEOUT_S
    assert argv == [*infrahub_dev.compose(tmp_path, VERSION, override), "stop", "--timeout", str(timeout)]
    assert isinstance(timeout, int) and timeout > 10


@pytest.mark.parametrize(("purge", "purges"), [("1", True), ("0", False), ("true", False), (None, False)])
def test_only_purge_1_purges(tmp_path: Path, purge: str | None, purges: bool) -> None:
    """`make -n` prints `infrahub-down`'s recipe and runs none of it."""
    argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), "infrahub-down", f"LOCAL={tmp_path}"]
    done = subprocess.run(
        [*argv, *([f"PURGE={purge}"] if purge is not None else [])],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    [recipe] = [line for line in done.stdout.splitlines() if "infrahub_dev.py down" in line]
    assert ("--purge" in recipe.split()) is purges


def test_a_purge_that_compose_refuses_keeps_the_seed_file(tmp_path: Path) -> None:
    seed = tmp_path / "infrahub" / "seed.json"
    seed.parent.mkdir(parents=True)
    seed.write_text("{}\n")
    run = Run(1)
    assert infrahub_dev.down(tmp_path, VERSION, tmp_path / "o.yml", tmp_path / ".git", purge=True, run=run) == 1
    assert seed.exists()


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["start"],
        ["env"],
        ["up", "--local", "l", "--override", "o", "--repo", "r"],
        ["up", "--local", "l", "--version", "../1.11.11", "--override", "o", "--repo", "r"],
        ["up", "--local", "l", "--version", VERSION, "--override", "o", "--repo", "r", "--purge"],
    ],
)
def test_a_command_line_that_is_not_understood_is_exit_2(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: object, **kwargs: object) -> int:
        raise AssertionError("a command line not understood reached a verb")

    for verb in ("write_env", "up", "down"):
        monkeypatch.setattr(infrahub_dev, verb, refused)
    assert infrahub_dev.main(argv) == 2
