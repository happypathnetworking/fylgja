"""`scripts/netbox_dev.py`: the development NetBox's lines in `local/.env`, its Compose project and its waits.

No test here opens a socket or starts a process but `make -n`, which prints a recipe and runs none of it: `run`,
`fetch`, `network`, `health`, `info`, `provision`, `clock` and `sleep` are fakes, `urllib.request.urlopen` is replaced
where the real requests are read and `subprocess.run` where the real network's inspection is, and every file is under
`tmp_path`.
"""

from __future__ import annotations

import email.message
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import account
import infrahub_dev
import netbox_dev
import pytest
from netbox_dev import Refused, Status, Versions

ROOT = Path(__file__).resolve().parents[2]
V = Versions("4.7.5", "5.1.1", "1.2.3")
RIGHT = Status("4.7.5", "1.2.3", 1)
BUILD = ["build", "netbox"]
UP = ["up", "-d", "--quiet-pull"]
DOWN = ["down", "--timeout", "60"]
OTHER = "192.0.2.0/24"
"""A subnet that is not the override's, as the project's network stood before the override named one."""
TOKEN = "nbt_abcdefghijkl." + "0123456789abcdefghijABCDEFGHIJ0123456789"
"""A token of the form NetBox presents: `nbt_`, a key of 12, a dot and a token of 40."""
PASSWORD = "FYLGJA_NETBOX_SUPERUSER_PASSWORD"
WRITE = "FYLGJA_NETBOX_WRITE_TOKEN"


def release(local: Path) -> Path:
    return local / "netbox" / "netbox-docker-5.1.1"


def override(local: Path) -> Path:
    return local / "dev" / "compose.override.yml"


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
    "FYLGJA_NETBOX_VERSION",
    "FYLGJA_NETBOX_DOCKER_VERSION",
    "FYLGJA_NETBOX_BRANCHING_VERSION",
    "FYLGJA_NETBOX_DEV",
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
    """Compose's fake: each call's arguments, the values of `KEPT` and the names of the rest of its environment, the
    clock's reading at each call, and its statuses answered in turn."""

    def __init__(self, *statuses: int, clock: Clock | None = None) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.names: list[list[str]] = []
        self.at: list[float] = []
        self.clock = clock

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> int:
        self.calls.append((list(argv), {name: env[name] for name in KEPT if name in env}))
        self.names.append(sorted(env))
        self.at.append(self.clock.now if self.clock else 0.0)
        return self.statuses.pop(0)

    def verbs(self) -> list[list[str]]:
        return [argv[len(netbox_dev.compose(Path("l"), V, Path("o"))) :] for argv, _ in self.calls]


class Fetch:
    """The release's fake: the URLs asked kept, a directory written, and an error raised after it where asked."""

    def __init__(self, *, fail: bool = False) -> None:
        self.urls: list[str] = []
        self.fail = fail

    def __call__(self, url: str, dest: Path) -> None:
        self.urls.append(url)
        dest.mkdir(parents=True)
        (dest / "docker-compose.yml").write_text("services: {}\n")
        if self.fail:
            raise OSError("the connection was reset")


def healthy_from(clock: Clock, at_s: float = 0.0) -> Callable[[Sequence[str], Mapping[str, str]], str | None]:
    """Docker's word on `netbox`: `starting`, then `unhealthy` from 120 s, until `at_s`; `healthy` from it."""

    def health(argv: Sequence[str], env: Mapping[str, str]) -> str | None:
        if clock.now >= at_s:
            return "healthy"
        return "starting" if clock.now < 120 else "unhealthy"

    return health


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
        if token in self.refused:
            raise Refused(f"{address} refuses the token")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Provision:
    """Provisioning's fake: each call kept, the token or None answered."""

    def __init__(self, answer: str | None = TOKEN) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, address: str, user: str, password: str) -> str | None:
        self.calls.append((address, user, password))
        return self.answer


class Network:
    """The project's network's fake: the subnets it answers, the override's where none are given, None where no
    network stands, or `Uninspected` raised with `unread` where it could not be read; and the names asked."""

    def __init__(self, *subnets: str, absent: bool = False, unread: str | None = None) -> None:
        self.subnets = list(subnets)
        self.absent = absent
        self.unread = unread
        self.names: list[str] = []

    def __call__(self, name: str) -> list[str] | None:
        self.names.append(name)
        if self.unread is not None:
            raise netbox_dev.Uninspected(self.unread)
        if self.absent:
            return None
        return self.subnets or [netbox_dev.SUBNET]


def never(*args: object) -> None:
    raise AssertionError("called where nothing may be")


def start(
    local: Path,
    run: Run,
    *,
    fetch: Callable[[str, Path], None] | None = None,
    network: Callable[[str], list[str] | None] | None = None,
    health: Callable[[Sequence[str], Mapping[str, str]], str | None] | None = None,
    info: Callable[[str, str], Status | None] | None = None,
    provision: Callable[[str, str, str], str | None] | None = None,
    clock: Clock | None = None,
    over: Path | None = None,
) -> int:
    clock = clock or Clock()
    return netbox_dev.up(
        local,
        V,
        over or override(local),
        run=run,
        fetch=fetch or Fetch(),
        network=network or Network(),
        health=health or healthy_from(clock),
        info=info or Info(),
        provision=provision or Provision(),
        clock=clock,
        sleep=clock.sleep,
    )


def seeded(local: Path, *extra: str) -> bytes:
    """`local/.env` holding the four names, then `extra`'s lines; its bytes."""
    env = local / ".env"
    netbox_dev.write_env(env)
    if extra:
        env.write_bytes(env.read_bytes() + "".join(f"{line}\n" for line in extra).encode())
    return env.read_bytes()


def test_a_fresh_file_holds_the_four_names_at_0600(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert netbox_dev.write_env(env) == list(netbox_dev.NAMES)
    assert mode(env) == 0o600
    lines = assignments(env)
    assert list(lines) == list(netbox_dev.NAMES)
    assert lines["FYLGJA_NETBOX_ADDRESS"] == netbox_dev.ADDRESS
    for name in netbox_dev.SECRETS:
        assert re.fullmatch(r"[A-Za-z0-9_-]{64}", lines[name]), name
    assert len({lines[name] for name in netbox_dev.SECRETS}) == len(netbox_dev.SECRETS)
    assert WRITE not in env.read_text()


def test_every_line_present_is_kept_and_only_missing_names_are_added(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    kept = b"FYLGJA_API_TOKEN=abc\n# note\nFYLGJA_NETBOX_API_TOKEN_PEPPER=kept\n"
    env.write_bytes(kept)
    env.chmod(0o644)
    added = netbox_dev.write_env(env)
    assert added == [name for name in netbox_dev.NAMES if name != "FYLGJA_NETBOX_API_TOKEN_PEPPER"]
    written = env.read_bytes()
    assert written.startswith(kept)
    assert assignments(env)["FYLGJA_NETBOX_API_TOKEN_PEPPER"] == "kept"
    assert mode(env) == 0o600
    assert netbox_dev.write_env(env) == []
    assert env.read_bytes() == written

    unended = tmp_path / "unended.env"
    unended.write_bytes(b"FYLGJA_API_TOKEN=abc")
    netbox_dev.write_env(unended)
    assert unended.read_bytes().startswith(b"FYLGJA_API_TOKEN=abc\n")
    assert assignments(unended)["FYLGJA_API_TOKEN"] == "abc"


@pytest.mark.parametrize("value", ["", '""', " # note"], ids=["empty", "quotes", "a-comment"])
def test_a_name_held_with_no_value_is_refused_before_anything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    """A shell reads `NAME= # note` as empty; Compose would read it as the text `# note`."""
    env = tmp_path / ".env"
    held = f"FYLGJA_API_TOKEN=abc\nFYLGJA_NETBOX_SECRET_KEY={value}\n".encode()
    env.write_bytes(held)
    env.chmod(0o644)
    run, fetch = Run(), Fetch()
    assert start(tmp_path, run, fetch=fetch, health=never, info=never, provision=never) == 2
    assert env.read_bytes() == held and mode(env) == 0o644
    assert run.calls == [] and fetch.urls == []
    assert not (tmp_path / "netbox").exists()
    err = capsys.readouterr().err
    assert "FYLGJA_NETBOX_SECRET_KEY" in err and "abc" not in err
    assert netbox_dev.main(["env", "--local", str(tmp_path)]) == 2
    assert env.read_bytes() == held
    assert "FYLGJA_NETBOX_SECRET_KEY" in capsys.readouterr().err


def test_the_env_files_rules_are_infrahub_devs() -> None:
    """Each script runs alone under `python3 -I` and imports no other, so `netbox_dev.py` holds its own copy of
    `infrahub_dev.py`'s rules for reading `local/.env`, and `netbox/seed/account.py` its own of `ASSIGNMENT` and
    `COMMENT`, beside a `QUOTED` of another form, `infrahub/seed/account.py`'s; the one file is read by all three,
    and the copies are held equal here, so that none changes alone."""
    for rule in ("ASSIGNMENT", "QUOTED", "COMMENT"):
        ours, theirs = getattr(netbox_dev, rule), getattr(infrahub_dev, rule)
        assert (ours.pattern, ours.flags) == (theirs.pattern, theirs.flags), rule
    for rule in ("ASSIGNMENT", "COMMENT"):
        accounts, theirs = getattr(account, rule), getattr(infrahub_dev, rule)
        assert (accounts.pattern, accounts.flags) == (theirs.pattern, theirs.flags), rule
    assert netbox_dev.EMPTY == infrahub_dev.EMPTY


def test_the_env_step_prints_names_and_no_value(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert netbox_dev.main(["env", "--local", str(tmp_path)]) == 0
    out, err = capsys.readouterr()
    printed = out + err
    for name in netbox_dev.NAMES:
        assert name in printed
    for name, value in assignments(tmp_path / ".env").items():
        if value != netbox_dev.ADDRESS:
            assert value not in printed, name


def test_every_compose_command_names_the_project_the_release_and_both_files(tmp_path: Path) -> None:
    local, over = tmp_path / "local", tmp_path / "override.yml"
    found = release(local)
    assert netbox_dev.compose(local, V, over) == [
        "docker",
        "compose",
        "-p",
        "fylgja-core-netbox",
        "--project-directory",
        str(found),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(found / "docker-compose.yml"),
        "-f",
        str(over),
    ]
    assert netbox_dev.release(local, V) == found


def test_the_versions_and_the_directory_are_set_over_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = tmp_path / "dev"
    base = {"FYLGJA_NETBOX_VERSION": "9.9.9", "FYLGJA_NETBOX_SECRET_KEY": "x", "PATH": "/bin"}
    assert netbox_dev.compose_env(V, dev, base) == {
        "FYLGJA_NETBOX_VERSION": "4.7.5",
        "FYLGJA_NETBOX_DOCKER_VERSION": "5.1.1",
        "FYLGJA_NETBOX_BRANCHING_VERSION": "1.2.3",
        "FYLGJA_NETBOX_DEV": str(dev),
        "PATH": "/bin",
    }
    for name in netbox_dev.SECRETS:
        monkeypatch.setenv(name, "exported-in-the-shell")
    monkeypatch.setenv("FYLGJA_NETBOX_VERSION", "9.9.9")
    monkeypatch.chdir(tmp_path)
    run = Run(0, 0)
    assert start(tmp_path, run, over=Path("dev") / "compose.override.yml") == 0
    for (_, given), names in zip(run.calls, run.names, strict=True):
        assert given == {
            "FYLGJA_NETBOX_VERSION": "4.7.5",
            "FYLGJA_NETBOX_DOCKER_VERSION": "5.1.1",
            "FYLGJA_NETBOX_BRANCHING_VERSION": "1.2.3",
            "FYLGJA_NETBOX_DEV": str(dev),
        }
        assert not set(names) & set(netbox_dev.SECRETS)


def test_up_fetches_the_release_once(tmp_path: Path) -> None:
    fetch = Fetch()
    assert start(tmp_path, Run(0, 0), fetch=fetch) == 0
    assert start(tmp_path, Run(0, 0), fetch=fetch) == 0
    assert fetch.urls == [netbox_dev.RELEASE_URL.format(version="5.1.1")]
    assert (release(tmp_path) / "docker-compose.yml").read_text() == "services: {}\n"

    local = tmp_path / "again"
    run = Run()
    assert start(local, run, fetch=Fetch(fail=True)) == 1
    assert list((local / "netbox").glob("netbox-docker-5.1.1*")) == []
    assert run.calls == []


def test_up_builds_before_it_starts(tmp_path: Path) -> None:
    run = Run(0, 0)
    assert start(tmp_path, run) == 0
    assert run.verbs()[:2] == [BUILD, UP]
    prefix = netbox_dev.compose(tmp_path, V, override(tmp_path))
    assert all(argv[: len(prefix)] == prefix for argv, _ in run.calls)

    run = Run(1)
    assert start(tmp_path, run, health=never, info=never, provision=never) == 1
    assert run.verbs() == [BUILD]


def test_up_recreates_a_network_of_another_subnet_and_keeps_the_volumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Docker gave the project the local driver's whole lab pool before the override named a range, and the script
    recreated that network on the kept volumes (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
    1.2.3"); what Compose's `up` alone does to it was not read: the containers and the network are removed, the
    volumes kept, and the start goes on."""
    network, run = Network(OTHER), Run(0, 0, 0)
    assert start(tmp_path, run, network=network) == 0
    assert network.names == ["fylgja-core-netbox_default"]
    assert run.verbs() == [DOWN, BUILD, UP]
    prefix = netbox_dev.compose(tmp_path, V, override(tmp_path))
    assert all(argv[: len(prefix)] == prefix for argv, _ in run.calls)
    for verb in run.verbs():
        assert not {"-v", "--volumes"} & set(verb) and not any("volume" in word for word in verb), verb
    said = [line for line in capsys.readouterr().out.splitlines() if OTHER in line]
    assert len(said) == 1 and netbox_dev.SUBNET in said[0] and "volumes kept" in said[0]


@pytest.mark.parametrize(
    "subnets",
    [(), ("198.51.100.0/24", "2001:db8::/64")],
    ids=["the-overrides", "with-an-ipv6-subnet-beside-it"],
)
def test_up_leaves_a_network_of_the_right_subnet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], subnets: tuple[str, ...]
) -> None:
    run = Run(0, 0)
    assert start(tmp_path, run, network=Network(*subnets)) == 0
    assert run.verbs() == [BUILD, UP]
    assert "volumes kept" not in capsys.readouterr().out


def test_up_leaves_no_network_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A network that does not stand is said nothing of: the start makes it."""
    network, run = Network(absent=True), Run(0, 0)
    assert start(tmp_path, run, network=network) == 0
    assert network.names == ["fylgja-core-netbox_default"]
    assert run.verbs() == [BUILD, UP]
    out, err = capsys.readouterr()
    assert "fylgja-core-netbox_default" not in out + err


def test_up_says_a_network_it_could_not_inspect_and_goes_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not read is not absent: one line names the network, why it was not read and the override's range, and `up`
    goes on as for a network that does not stand, nothing removed."""
    network, run = Network(unread="`docker network inspect` did not answer within 60 s"), Run(0, 0)
    assert start(tmp_path, run, network=network) == 0
    assert run.verbs() == [BUILD, UP]
    out, err = capsys.readouterr()
    said = [line for line in (out + err).splitlines() if "fylgja-core-netbox_default" in line]
    assert len(said) == 1
    assert "could not be inspected" in said[0] and "within 60 s" in said[0] and netbox_dev.SUBNET in said[0]


def test_a_start_that_fails_after_the_recreate_names_the_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old network is gone by then, and a range another network holds is not read: the start's failure names the
    override's range, which no start that follows no recreate does."""
    clock = Clock()
    run = Run(0, 0, 1, clock=clock)
    health = healthy_from(clock, at_s=10_000)
    assert start(tmp_path, run, network=Network(OTHER), health=health, clock=clock, provision=never) == 1
    assert run.verbs() == [DOWN, BUILD, UP]
    out, err = capsys.readouterr()
    failed = [line for line in (out + err).splitlines() if "first start" in line]
    assert len(failed) == 1 and netbox_dev.SUBNET in failed[0] and "docker network ls" in failed[0]

    clock = Clock()
    run = Run(0, 1, clock=clock)
    assert start(tmp_path, run, health=healthy_from(clock, at_s=10_000), clock=clock, provision=never) == 1
    out, err = capsys.readouterr()
    assert netbox_dev.SUBNET not in out + err


def test_a_down_that_fails_ends_up_with_its_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing is built or started after it."""
    run = Run(3)
    assert start(tmp_path, run, network=Network(OTHER), health=never, info=never, provision=never) == 1
    assert run.verbs() == [DOWN]
    err = capsys.readouterr().err
    assert "docker compose down --timeout 60" in err and "exited 3" in err


def test_up_waits_for_health_and_asks_compose_again_where_the_first_start_failed(tmp_path: Path) -> None:
    """The first start exits 1 while NetBox migrates, and leaves the worker created and not started
    (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3")."""
    clock = Clock()
    run = Run(0, 1, 0, clock=clock)
    health = healthy_from(clock, at_s=650)
    assert start(tmp_path, run, health=health, clock=clock) == 0
    assert run.verbs() == [BUILD, UP, UP]
    assert run.at[2] >= 650
    assert set(clock.slept) == {netbox_dev.POLL_S}

    run = Run(0, 0)
    assert start(tmp_path, run) == 0
    assert run.verbs() == [BUILD, UP]

    run = Run(0, 1, 1)
    assert start(tmp_path, run, info=never, provision=never) == 1
    assert run.verbs() == [BUILD, UP, UP]


def test_up_ends_at_its_bound_naming_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = Clock()
    run = Run(0, 1)
    assert start(tmp_path, run, health=healthy_from(clock, at_s=10_000), clock=clock, provision=never) == 1
    assert netbox_dev.UP_WAIT_S == 1200
    assert 1200 <= clock.now <= 1200 + netbox_dev.POLL_S
    assert run.verbs() == [BUILD, UP]
    err = capsys.readouterr().err
    assert "1200 s" in err and "docker compose -p fylgja-core-netbox logs netbox" in err


def test_up_keeps_a_token_netbox_takes_and_provisions_where_it_is_refused_or_absent(tmp_path: Path) -> None:
    held = "nbt_heldheldheld." + "h" * 40
    local = tmp_path / "taken"
    before = seeded(local, f"{WRITE}={held}", "FYLGJA_API_TOKEN=abc")
    info = Info()
    assert start(local, Run(0, 0), info=info, provision=never) == 0
    assert (local / ".env").read_bytes() == before
    assert set(info.tokens) == {held}

    local = tmp_path / "absent"
    before = seeded(local, "FYLGJA_API_TOKEN=abc")
    password = assignments(local / ".env")[PASSWORD]
    provision, info = Provision(), Info()
    assert start(local, Run(0, 0), info=info, provision=provision) == 0
    assert provision.calls == [(netbox_dev.ADDRESS, "admin", password)]
    assert (local / ".env").read_bytes() == before + f"{WRITE}={TOKEN}\n".encode()
    assert set(info.tokens) == {TOKEN}
    assert mode(local / ".env") == 0o600

    local = tmp_path / "refused"
    before = seeded(local, f"{WRITE}={held}", "FYLGJA_API_TOKEN=abc")
    password = assignments(local / ".env")[PASSWORD]
    provision, info = Provision(), Info(refused=[held])
    assert start(local, Run(0, 0), info=info, provision=provision) == 0
    assert provision.calls == [(netbox_dev.ADDRESS, "admin", password)]
    assert (local / ".env").read_bytes() == before.replace(f"{WRITE}={held}\n".encode(), f"{WRITE}={TOKEN}\n".encode())
    assert info.tokens[0] == held and set(info.tokens[1:]) == {TOKEN}


def test_a_password_netbox_refuses_ends_with_the_purge_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The volumes were made with another password: only a purge gives a superuser this file's."""
    before = seeded(tmp_path, "FYLGJA_API_TOKEN=abc")
    provision = Provision(None)
    assert start(tmp_path, Run(0, 0), provision=provision, info=never) == 1
    assert len(provision.calls) == 1
    assert "make netbox-down PURGE=1" in capsys.readouterr().err
    assert (tmp_path / ".env").read_bytes() == before


@pytest.mark.parametrize(
    ("status", "named"),
    [
        (Status("4.7.4", "1.2.3", 1), ("4.7.4", "4.7.5", "1.2.3")),
        (Status("4.7.5", "1.2.2", 1), ("4.7.5", "1.2.2", "1.2.3")),
        (Status("4.7.5", None, 1), ("netbox_branching", "plugins.py")),
    ],
    ids=["another-netbox", "another-plugin", "no-plugin"],
)
def test_up_fails_on_another_version_a_missing_plugin_and_no_worker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status: Status, named: tuple[str, ...]
) -> None:
    clock = Clock()
    assert start(tmp_path, Run(0, 0), info=Info(status), clock=clock) == 1
    assert clock.slept == []
    err = capsys.readouterr().err
    for text in named:
        assert text in err

    clock = Clock()
    assert start(tmp_path, Run(0, 0), info=Info(Status("4.7.5", "1.2.3", 0)), clock=clock) == 1
    assert 60 <= clock.now <= 60 + netbox_dev.POLL_S
    assert "netbox-worker" in capsys.readouterr().err

    clock = Clock()
    assert start(tmp_path, Run(0, 0), info=Info(None, None, RIGHT), clock=clock) == 0
    assert clock.slept == [netbox_dev.POLL_S, netbox_dev.POLL_S]


def test_up_ends_at_the_status_bound_where_netbox_never_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = Clock()
    assert start(tmp_path, Run(0, 0), info=Info(None), clock=clock) == 1
    assert netbox_dev.STATUS_WAIT_S == 60
    assert 60 <= clock.now <= 60 + netbox_dev.POLL_S
    assert "did not answer" in capsys.readouterr().err


def test_no_output_of_up_holds_a_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = Clock()
    assert start(tmp_path, Run(0, 1, 0), health=healthy_from(clock, at_s=30), clock=clock) == 0
    out, err = capsys.readouterr()
    printed = out + err
    assert out
    held = assignments(tmp_path / ".env")
    assert held[WRITE] == TOKEN
    for secret in (TOKEN, *(held[name] for name in netbox_dev.SECRETS)):
        assert secret not in printed

    local = tmp_path / "refused"
    stale = "nbt_stalestalest." + "s" * 40
    seeded(local, f"{WRITE}={stale}")
    assert start(local, Run(0, 0), info=Info(refused=[stale])) == 0
    out, err = capsys.readouterr()
    assert "refuses" in out and assignments(local / ".env")[WRITE] == TOKEN
    for secret in (stale, TOKEN):
        assert secret not in out + err


class Answer(io.BytesIO):
    """A response of urlopen's: its body and its status."""

    def __init__(self, body: bytes, status: int) -> None:
        super().__init__(body)
        self.status = status


def refusal(url: str, code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "Forbidden", email.message.Message(), io.BytesIO(body))


def test_provisioning_posts_the_password_and_says_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Provisioning answers 201 with the token's `key` and `token` (design/verified-facts.md, "NetBox 4.7.5 with
    netbox-branching 1.2.3"), and a wrong password 403."""
    key, secret = "abcdefghijkl", "0123456789abcdefghijABCDEFGHIJ0123456789"
    asked: list[urllib.request.Request] = []
    url = netbox_dev.ADDRESS + "/api/users/tokens/provision/"

    def urlopen(request: urllib.request.Request, timeout: float) -> Answer:
        asked.append(request)
        return Answer(json.dumps({"id": 1, "key": key, "token": secret, "version": 2}).encode(), 201)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert netbox_dev.provision_token(netbox_dev.ADDRESS, "admin", "a-password") == f"nbt_{key}.{secret}"
    [request] = asked
    assert request.get_method() == "POST" and request.full_url == url
    assert isinstance(request.data, bytes)
    assert json.loads(request.data) == {"username": "admin", "password": "a-password"}
    assert request.get_header("Content-type") == "application/json"

    def refused(request: urllib.request.Request, timeout: float) -> Answer:
        raise refusal(request.full_url, 403, b'{"detail": "Invalid username/password"}')

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    assert netbox_dev.provision_token(netbox_dev.ADDRESS, "admin", "a-password") is None
    out, err = capsys.readouterr()
    assert out == err == ""


def test_the_status_is_read_with_the_token_and_a_refusal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/api/status/` names the versions and `rq-workers-running`; a token NetBox never made is 403 `Invalid v2
    token` (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3")."""
    asked: list[urllib.request.Request] = []
    answers: list[Answer | urllib.error.HTTPError | OSError] = [
        Answer(
            json.dumps(
                {
                    "netbox-version": "4.7.5",
                    "netbox-full-version": "4.7.5-Docker-5.1.1",
                    "plugins": {"netbox_branching": "1.2.3"},
                    "rq-workers-running": 1,
                }
            ).encode(),
            200,
        ),
        Answer(json.dumps({"netbox-version": "4.7.5", "plugins": {}, "rq-workers-running": 0}).encode(), 200),
        Answer(b"<html>", 200),
        OSError("connection reset"),
        refusal("status", 502, b"Bad Gateway"),
        refusal("status", 403, b'{"detail": "Invalid v2 token"}'),
    ]

    def urlopen(request: urllib.request.Request, timeout: float) -> Answer:
        asked.append(request)
        answer = answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN) == RIGHT
    assert netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN) == Status("4.7.5", None, 0)
    assert netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN) is None
    assert netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN) is None
    assert netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN) is None
    with pytest.raises(Refused) as refused:
        netbox_dev.ask_status(netbox_dev.ADDRESS, TOKEN)
    assert TOKEN not in str(refused.value)
    assert {request.full_url for request in asked} == {netbox_dev.ADDRESS + "/api/status/"}
    assert {request.get_header("Authorization") for request in asked} == {f"Bearer {TOKEN}"}


@pytest.mark.parametrize(
    "printed",
    [
        '[{"Service": "postgres", "Health": "healthy"}, {"Service": "netbox", "Health": "starting"}]',
        '{"Service": "postgres", "Health": "healthy"}\n{"Service": "netbox", "Health": "starting"}\n',
    ],
    ids=["array", "lines"],
)
def test_the_health_is_netbox_rows_and_none_without_it(printed: str) -> None:
    """`ps --format json` prints a row a container, each with `Service` and `Health`
    (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3")."""
    assert netbox_dev.health_of(printed) == "starting"
    assert netbox_dev.health_of(printed.replace('"netbox"', '"netbox-worker"')) is None
    assert netbox_dev.health_of("") is None
    assert netbox_dev.health_of("not json") is None


def inspected(
    monkeypatch: pytest.MonkeyPatch, *, stdout: str = "", stderr: str = "", status: int = 0, late: bool = False
) -> list[list[str]]:
    """`subprocess.run` replaced by a fake of `docker network inspect`'s answer; the commands asked."""
    asked: list[list[str]] = []

    def run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        asked.append(list(argv))
        if late:
            raise subprocess.TimeoutExpired(list(argv), netbox_dev.INSPECT_TIMEOUT_S)
        return subprocess.CompletedProcess(list(argv), status, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return asked


@pytest.mark.parametrize(
    ("stdout", "subnets"),
    [
        ('[{"Subnet":"198.51.100.0/24","Gateway":"198.51.100.1"}]\n', ["198.51.100.0/24"]),
        (
            '[{"Subnet":"192.0.2.0/24"},{"Subnet":"2001:db8::/64"},{"Gateway":"192.0.2.1"}]\n',
            ["192.0.2.0/24", "2001:db8::/64"],
        ),
        ("[]\n", []),
        ("null\n", []),
    ],
    ids=["one", "two-and-one-without", "none", "null"],
)
def test_the_network_is_read_by_its_ipam_configuration(
    monkeypatch: pytest.MonkeyPatch, stdout: str, subnets: list[str]
) -> None:
    asked = inspected(monkeypatch, stdout=stdout)
    assert netbox_dev.network_subnets("fylgja-core-netbox_default") == subnets
    name = "fylgja-core-netbox_default"
    assert asked == [["docker", "network", "inspect", "--format", "{{json .IPAM.Config}}", name]]


@pytest.mark.parametrize(
    "stderr",
    [
        "Error response from daemon: network fylgja-core-netbox_default not found\n",
        "Error: No such network: fylgja-core-netbox_default\n",
    ],
    ids=["not-found", "no-such-network"],
)
def test_a_network_docker_does_not_find_is_absent(monkeypatch: pytest.MonkeyPatch, stderr: str) -> None:
    inspected(monkeypatch, stderr=stderr, status=1)
    assert netbox_dev.network_subnets("fylgja-core-netbox_default") is None


@pytest.mark.parametrize(
    ("stdout", "stderr", "status", "late", "said"),
    [
        ("", "", 0, True, "within 60 s"),
        ("", "Cannot connect to the Docker daemon. Is the docker daemon running?\n", 1, False, "exited 1"),
        ("not json\n", "", 0, False, "did not read"),
        ('{"Subnet": "198.51.100.0/24"}\n', "", 0, False, "did not read"),
    ],
    ids=["late", "another-error", "unreadable", "no-list"],
)
def test_a_network_that_could_not_be_inspected_is_not_absent(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, status: int, late: bool, said: str
) -> None:
    inspected(monkeypatch, stdout=stdout, stderr=stderr, status=status, late=late)
    with pytest.raises(netbox_dev.Uninspected) as unread:
        netbox_dev.network_subnets("fylgja-core-netbox_default")
    assert said in str(unread.value)


def test_ipv4_keeps_a_subnet_that_does_not_read_and_drops_ipv6() -> None:
    assert netbox_dev.ipv4([]) == []
    assert netbox_dev.ipv4(["2001:db8::/64"]) == []
    assert netbox_dev.ipv4(["2001:db8::/64", "198.51.100.0/24", "no subnet"]) == ["198.51.100.0/24", "no subnet"]


def test_the_fetch_unpacks_the_archive_without_its_top_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub's archive of a tag holds one directory, `netbox-docker-<tag>/` (design/verified-facts.md)."""
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as tar:
        for name, body in (("docker-compose.yml", b"services: {}\n"), ("env/netbox.env", b"SKIP_SUPERUSER=true\n")):
            entry = tarfile.TarInfo(f"netbox-docker-5.1.1/{name}")
            entry.size = len(body)
            tar.addfile(entry, io.BytesIO(body))
    asked: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> Answer:
        asked.append(request)
        return Answer(packed.getvalue(), 200)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    url = netbox_dev.RELEASE_URL.format(version="5.1.1")
    dest = tmp_path / "netbox-docker-5.1.1.part"
    netbox_dev.fetch_release(url, dest)
    assert [request.full_url for request in asked] == [url]
    assert (dest / "docker-compose.yml").read_bytes() == b"services: {}\n"
    assert (dest / "env" / "netbox.env").read_bytes() == b"SKIP_SUPERUSER=true\n"
    assert sorted(path.name for path in dest.iterdir()) == ["docker-compose.yml", "env"]


def test_down_stops_and_only_purge_1_removes_the_volumes(tmp_path: Path) -> None:
    over, env = override(tmp_path), tmp_path / ".env"
    found = release(tmp_path)
    found.mkdir(parents=True)
    (found / "docker-compose.yml").write_text("services: {}\n")
    env.write_text("FYLGJA_API_TOKEN=abc\n")

    run = Run(0)
    assert netbox_dev.down(tmp_path, V, over, purge=False, run=run) == 0
    [(argv, given)] = run.calls
    assert argv == [*netbox_dev.compose(tmp_path, V, over), "stop", "--timeout", "60"]
    assert netbox_dev.STOP_TIMEOUT_S == 60
    assert given["FYLGJA_NETBOX_DEV"] == str(over.parent)

    run = Run(0)
    assert netbox_dev.down(tmp_path, V, over, purge=True, run=run) == 0
    [(argv, _)] = run.calls
    assert argv == [*netbox_dev.compose(tmp_path, V, over), "down", "-v"]
    assert env.read_text() == "FYLGJA_API_TOKEN=abc\n"
    assert (found / "docker-compose.yml").exists()

    assert netbox_dev.down(tmp_path, V, over, purge=False, run=Run(1)) == 1
    assert netbox_dev.down(tmp_path, V, over, purge=True, run=Run(1)) == 1


@pytest.mark.parametrize(("purge", "purges"), [("1", True), ("0", False), ("true", False), (None, False)])
def test_only_purge_1_purges(tmp_path: Path, purge: str | None, purges: bool) -> None:
    """`make -n` prints `netbox-down`'s recipe and runs none of it."""
    argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), "netbox-down", f"LOCAL={tmp_path}"]
    done = subprocess.run(
        [*argv, *([f"PURGE={purge}"] if purge is not None else [])],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    [recipe] = [line for line in done.stdout.splitlines() if "netbox_dev.py down" in line]
    assert ("--purge" in recipe.split()) is purges
    for flag in ("--netbox 4.7.5", "--docker 5.1.1", "--branching 1.2.3", "--override netbox/dev/compose.override.yml"):
        assert flag in recipe


def test_main_hands_down_its_versions_and_purge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    given: list[tuple[Path, Versions, Path, bool]] = []

    def down(local: Path, versions: Versions, over: Path, *, purge: bool, run: object) -> int:
        given.append((local, versions, over, purge))
        return 1

    monkeypatch.setattr(netbox_dev, "down", down)
    flags = ["--local", str(tmp_path), "--netbox", "4.7.5", "--docker", "5.1.1", "--branching", "1.2.3"]
    assert netbox_dev.main(["down", *flags, "--override", "o.yml", "--purge"]) == 1
    assert netbox_dev.main(["down", *flags, "--override", "o.yml"]) == 1
    assert given == [
        (tmp_path, V, Path("o.yml").absolute(), True),
        (tmp_path, V, Path("o.yml").absolute(), False),
    ]


FLAGS = ["--local", "l", "--docker", "5.1.1", "--branching", "1.2.3", "--override", "o"]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["start"],
        ["env"],
        ["up", *FLAGS],
        ["up", *FLAGS, "--netbox", "latest"],
        ["up", *FLAGS, "--netbox", "4.7.5", "--purge"],
    ],
    ids=["no-verb", "an-unknown-verb", "env-without-local", "up-without-netbox", "netbox-latest", "up-with-purge"],
)
def test_a_command_line_that_is_not_understood_is_exit_2(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: object, **kwargs: object) -> int:
        raise AssertionError("a command line not understood reached a verb")

    for verb in ("write_env", "up", "down"):
        monkeypatch.setattr(netbox_dev, verb, refused)
    assert netbox_dev.main(argv) == 2
