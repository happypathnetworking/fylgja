"""The command `fylgja-nautobot` (cli.py), with `connect` replaced by a function answering a `FakeSource` and the
environment set by `monkeypatch`: it exits 0 with the blueprint written to `--out` and its id printed, 1 on an error
finding with `--out` left as it was, and 2 on a failure of its own, each finding one line on stderr; and no stream it
prints holds the token, which the fixture `run` holds every test to, or a line of a configuration."""

from __future__ import annotations

import errno
import json
import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake import CHANGE, ROOT, THREE_NODE, FakeSource, listing, three_node
from fylgja_core import blueprint, release
from fylgja_core.findings import Finding

from fylgja_nautobot import NautobotError, cli, transport
from fylgja_nautobot.rows import Change, Rendered

ADDRESS = "http://127.0.0.1:8810"
TOKEN = "0123456789abcdef0123456789abcdef01234567"
"""The token the environment gives every test, of Nautobot's shape, which no stream may hold."""
SCOPE = "tag:fylgja"
FIXTURE = json.loads(THREE_NODE.read_text())
FIXTURE_ID = blueprint.blueprint_id(FIXTURE)
CONFIGURED = {line.strip() for d in FIXTURE["network"]["devices"] for line in d["config"].splitlines() if line.strip()}
"""Every line of every configuration `three_node` holds."""
FAILED = "Error rendering Jinja template: Subtask: GENERATE CONFIG (failed)"
UNVERIFIED = Finding(
    rule="nautobot.version.unverified",
    severity="warning",
    object="3.2.9/3.0.8",
    message="Nautobot is version 3.2.9 with Golden Config 3.0.8, and this reader is verified on 3.2.8 alone.",
)


LATER = Change("change-2", "2026-11-19T21:00:07.000001Z")
"""A row written during a read."""


def moving(conn: FakeSource) -> FakeSource:
    """`conn` whose changelog moves after the open: its first `newest` answers the open's row, each later `LATER`."""
    answers = [(66, CHANGE)]

    def newest() -> tuple[int, Change | None]:
        conn.calls.append("newest")
        return answers.pop(0) if answers else (67, LATER)

    conn.newest = newest  # type: ignore[method-assign]
    return conn


@dataclass(frozen=True)
class Said:
    """What one run of the command did: its exit code and its two streams."""

    code: int
    out: str
    err: str


class Command:
    """`cli.main`, its `connect` answering `source` and recording what it was given, or raising `refusal`; every stream
    a run printed is kept in `said`."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self.source = three_node()
        self.refusal: Exception | None = None
        self.connected: list[tuple[str, str, Path | None]] = []
        self.said: list[str] = []

    def connect(self, address: str, token: str, *, ca: Path | None = None) -> FakeSource:
        self.connected.append((address, token, ca))
        if self.refusal is not None:
            raise self.refusal
        return self.source

    def __call__(self, *argv: str) -> Said:
        code = cli.main(list(argv))
        out, err = self._capsys.readouterr()
        self.said += [out, err]
        return Said(code, out, err)


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Iterator[Command]:
    """The command with the address and the token set and no CA, which fails the test where a stream it printed holds
    the token."""
    monkeypatch.setenv(cli.ADDRESS, ADDRESS)
    monkeypatch.setenv(cli.TOKEN, TOKEN)
    monkeypatch.delenv(cli.CA, raising=False)
    command = Command(capsys)
    monkeypatch.setattr(cli, "connect", command.connect)
    yield command
    assert not any(TOKEN in stream for stream in command.said), "a stream the command printed held the token"


def reader(tmp_path: Path, **changed: Any) -> Path:
    """A reader document file mapping `three_node`'s platform and naming no probes' context, with `changed` over it."""
    doc = {
        "reader_version": "1",
        "platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": "nokia_srlinux"}],
        "probes": None,
        **changed,
    }
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(doc))
    return path


def read_args(tmp_path: Path) -> list[str]:
    return ["read", "--scope", SCOPE, "--reader", str(reader(tmp_path)), "--out", str(tmp_path / "blueprint.json")]


def configured(said: Said) -> list[str]:
    """Each line of either stream that is a line of a configuration."""
    return [line for line in (said.out + said.err).splitlines() if line.strip() in CONFIGURED]


def test_version_names_the_version_and_the_commit(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr() == (f"fylgja-nautobot {release.build('fylgja-nautobot', 'fylgja_nautobot')}\n", "")


def test_read_writes_the_blueprint_and_prints_its_id(run: Command, tmp_path: Path) -> None:
    said = run(*read_args(tmp_path))
    assert (said.code, said.err) == (0, "")
    doc = json.loads((tmp_path / "blueprint.json").read_text())
    assert blueprint.validate(doc) == []
    assert blueprint.blueprint_id(doc) == FIXTURE_ID
    assert said.out == f"{FIXTURE_ID} 3 devices, 3 links, 0 probes\n"
    assert configured(said) == []
    assert run.connected == [(ADDRESS, TOKEN, None)]
    assert run.source.closed
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blueprint.json", "reader.json"], "no file left"
    assert stat.S_IMODE((tmp_path / "blueprint.json").stat().st_mode) == 0o600, "its owner's alone"


def test_the_seeds_reader_document_reads_the_probe(run: Command, tmp_path: Path) -> None:
    """The reader document is read from the path as given: here the development Nautobot's, which names the context
    `three_node` holds."""
    out = tmp_path / "blueprint.json"
    seeded = ROOT / "nautobot" / "seed" / "reader.yaml"
    said = run("read", "--scope", SCOPE, "--reader", str(seeded), "--out", str(out))
    assert (said.code, said.err) == (0, "")
    assert said.out.endswith(" 3 devices, 3 links, 1 probes\n")
    assert [probe["name"] for probe in json.loads(out.read_text())["probes"]] == ["n1-loop"]


@pytest.mark.parametrize("kept", [None, "a file already there\n"], ids=["absent", "present"])
def test_a_refused_read_exits_1_and_writes_nothing(run: Command, tmp_path: Path, kept: str | None) -> None:
    out = tmp_path / "blueprint.json"
    if kept is not None:
        out.write_text(kept)
    run.source.renders["device-2"] = Rendered(400, None, FAILED)
    said = run(*read_args(tmp_path))
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error render.failed n2: ")
    assert configured(said) == []
    if kept is None:
        assert not out.exists()
    else:
        assert out.read_text() == kept
    assert {path.name for path in tmp_path.iterdir()} <= {"blueprint.json", "reader.json"}, "no file left"
    assert run.source.closed


def test_a_read_moved_exits_1(run: Command, tmp_path: Path) -> None:
    run.source = moving(three_node())
    said = run(*read_args(tmp_path))
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error read.moved extras.objectchange: ")
    assert LATER.id in lines[0] and "read again" in lines[0]
    assert not (tmp_path / "blueprint.json").exists()


def test_an_info_finding_is_printed_and_the_read_still_succeeds(run: Command, tmp_path: Path) -> None:
    held = [replace(d, name="N1") if d.name == "n1" else d for d in run.source.held_devices.items]
    run.source.held_devices = listing("dcim.device", held)
    said = run(*read_args(tmp_path))
    assert said.code == 0
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("info device.name.renamed N1: ")
    doc = json.loads((tmp_path / "blueprint.json").read_text())
    assert blueprint.validate(doc) == [] and blueprint.blueprint_id(doc) == FIXTURE_ID


def test_a_write_that_fails_leaves_the_file_there_as_it_was(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--out` is written whole or not at all: the blueprint goes to a file of its own beside it, which takes its place
    only once it is written, so a write that fails before then leaves a file already there as it was, and no other."""
    out = tmp_path / "blueprint.json"
    out.write_text("a file already there\n")

    def failed(source: str, target: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", failed)
        said = run(*read_args(tmp_path))
    assert said == Said(2, "", f"{out}: No space left on device\n")
    assert out.read_text() == "a file already there\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blueprint.json", "reader.json"]


def test_a_nautobot_without_golden_config_exits_1(run: Command, tmp_path: Path) -> None:
    run.source.golden_config = None
    said = run(*read_args(tmp_path))
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error golden_config.absent nautobot_golden_config: ")
    assert run.source.calls == [], "nothing more is sent"
    assert not (tmp_path / "blueprint.json").exists()
    said = run("check")
    assert (said.code, said.out) == (1, "")
    assert said.err.startswith("error golden_config.absent nautobot_golden_config: ")


def test_check_prints_ok_or_the_faults(run: Command) -> None:
    said = run("check")
    assert said == Said(0, "ok: Nautobot 3.2.8, Golden Config 3.0.8\n", "")
    assert run.source.calls == [], "nothing is asked beyond the connect"
    assert run.source.closed

    run.source = three_node()
    run.source.version, run.source.unverified = "3.2.9", UNVERIFIED
    said = run("check")
    assert said == Said(
        0,
        "ok: Nautobot 3.2.9, Golden Config 3.0.8\n",
        f"warning {UNVERIFIED.rule} {UNVERIFIED.object}: {UNVERIFIED.message}\n",
    )

    run.source = three_node()
    run.source.golden_config = None
    said = run("check")
    assert (said.code, said.out) == (1, "")
    assert [line.split()[1] for line in said.err.splitlines()] == ["golden_config.absent"]


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
@pytest.mark.parametrize("name", [cli.ADDRESS, cli.TOKEN])
def test_a_variable_not_set_exits_2_naming_it(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    said = run(*read_args(tmp_path))
    assert said == Said(2, "", f"{name} is not set\n")
    other = TOKEN if name == cli.ADDRESS else ADDRESS
    assert other not in said.out + said.err
    assert run.connected == []
    assert not (tmp_path / "blueprint.json").exists()


@pytest.mark.parametrize(
    ("name", "value", "predicate"),
    [
        (cli.ADDRESS, "ftp://nautobot.example", "is not an http(s):// URL or host:port"),
        (cli.TOKEN, "a token with spaces", "is not an RFC 6750 bearer token"),
        (cli.CA, "no-such-ca.pem", "names no file of CA certificates that can be read"),
    ],
)
def test_a_variable_it_cannot_use_exits_2_naming_it(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str, predicate: str
) -> None:
    """The variable named, then the predicate the client's rule gives, and never the value."""
    monkeypatch.setenv(name, str(tmp_path / value) if name == cli.CA else value)
    said = run("check")
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith(f"{name} {predicate}") and len(said.err.splitlines()) == 1
    assert value not in said.err
    assert run.connected == []


def test_every_fault_before_nautobot_is_named_at_once(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(cli.ADDRESS)
    monkeypatch.setenv(cli.TOKEN, "a token with spaces")
    args = read_args(tmp_path)
    reader(tmp_path, reader_version="2")
    said = run(*args)
    assert said.code == 2
    assert [line.split()[0] for line in said.err.splitlines()[:3]] == [cli.ADDRESS, cli.TOKEN, args[4]]
    assert run.connected == []


@pytest.mark.parametrize(
    ("changed", "problem"),
    [
        ({"reader_version": "2"}, "reader.version.unsupported at /reader_version"),
        (
            {"platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": p} for p in ("a", "b")]},
            "reader.platform.duplicate at /platforms/1",
        ),
    ],
    ids=["version", "duplicate"],
)
def test_a_reader_document_refused_exits_2(run: Command, tmp_path: Path, changed: dict[str, Any], problem: str) -> None:
    args = read_args(tmp_path)
    path = reader(tmp_path, **changed)
    said = run(*args)
    assert (said.code, said.out) == (2, "")
    lines = said.err.splitlines()
    assert len(lines) == 2 and str(path) in lines[0]
    assert lines[1].strip().startswith(f"{problem}: ")
    assert run.connected == []
    assert not (tmp_path / "blueprint.json").exists()


def test_a_reader_document_not_read_exits_2_naming_it(run: Command, tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    said = run("read", "--scope", SCOPE, "--reader", str(missing), "--out", str(tmp_path / "blueprint.json"))
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith(f"{missing}: ") and len(said.err.splitlines()) == 1
    assert run.connected == []


@pytest.mark.parametrize("where", ["connect", "read"])
def test_a_nautobot_error_exits_2(run: Command, tmp_path: Path, where: str) -> None:
    message = "reading dcim.device: HTTP 403: Nautobot refused the token FYLGJA_NAUTOBOT_TOKEN holds"
    refusal = NautobotError(message, 403)
    if where == "connect":
        run.refusal = refusal
    else:
        run.source.raising = {"devices": refusal}
    said = run(*read_args(tmp_path))
    assert said == Said(2, "", f"{message}\n")
    assert not (tmp_path / "blueprint.json").exists()
    if where != "connect":
        assert run.source.closed


def test_any_other_failure_is_one_line_without_the_token(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failed(*args: object) -> None:
        raise RuntimeError(f"an answer quoting {TOKEN}")

    monkeypatch.setattr(run.source, "devices", failed)
    said = run(*read_args(tmp_path))
    assert said == Said(2, "", "RuntimeError: an answer quoting <redacted>\n")
    assert run.source.closed


def echoing(answer: Callable[[httpx.Request], httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
    """A Nautobot over `httpx.MockTransport`: its status, Nautobot 3.2.8 with Golden Config 3.0.8, and every other
    request `answer`."""

    def served(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/status/":
            info = {"nautobot-version": "3.2.8", "nautobot-apps": {"nautobot_golden_config": "3.0.8"}}
            return httpx.Response(200, json=info)
        return answer(request)

    return served


@pytest.mark.parametrize(("where", "status"), [("connect", 500), ("read", 500), ("read", 400), ("read", 403)])
def test_a_body_that_echoes_the_token_reaches_no_stream_and_no_file(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str, status: int
) -> None:
    """The command over the real `connect` and transport, on an `httpx.MockTransport` whose refusal echoes the token and
    the request's own `Authorization` header: the run exits 2 with one line, and neither stream (the fixture `run`),
    that line nor any file under `tmp_path` holds the token."""

    def echoed(request: httpx.Request) -> httpx.Response:
        said = f"Refused {TOKEN}, sent as {request.headers['Authorization']}"
        return httpx.Response(status, text=said, headers={"Content-Type": "text/plain"})

    def served(request: httpx.Request) -> httpx.Response:
        return echoed(request) if where == "connect" else echoing(echoed)(request)

    def connect(address: str, token: str, *, ca: Path | None = None) -> transport.Nautobot:
        return transport.connect(address, token, ca=ca, transport=httpx.MockTransport(served))

    monkeypatch.setattr(cli, "connect", connect)
    out = tmp_path / "blueprint.json"
    out.write_text("a file already there\n")
    said = run(*read_args(tmp_path))
    assert (said.code, said.out) == (2, "")
    assert len(said.err.splitlines()) == 1 and f"HTTP {status}" in said.err
    assert out.read_text() == "a file already there\n"
    for path in tmp_path.rglob("*"):
        held = path.read_text() if path.is_file() else ""
        assert TOKEN not in held, f"{path.name} held the token"


def test_arguments_refused_exit_2_and_connect_nothing(run: Command, tmp_path: Path) -> None:
    said = run("read", "--reader", str(reader(tmp_path)))
    assert (said.code, said.out) == (2, "")
    assert "--scope" in said.err
    assert run.connected == []
    assert run("check", "--scope", SCOPE).code == 2
    assert run("read", "--branch", "main").code == 2
    assert run.connected == []
