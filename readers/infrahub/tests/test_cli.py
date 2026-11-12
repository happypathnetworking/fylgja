"""The command `fylgja-infrahub` (cli.py), with `connect` replaced by a function answering a `FakeSource` and the
environment set by `monkeypatch`: it exits 0 with the blueprint written to `--out` and its id printed, 1 on an error
finding with `--out` left as it was, and 2 on a failure of its own, each finding one line on stderr; and no stream it
prints holds the token, which the fixture `run` holds every test to, or a line of a configuration."""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import re
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fake import THREE_NODE, FakeSource, dcim_schema, listing, stamp, three_node
from fylgja_core import blueprint
from fylgja_core.findings import Finding

from fylgja_infrahub import InfrahubError, cli, schema

ADDRESS = "http://127.0.0.1:8000"
TOKEN = "fylgja-cli-token-5e1d0c9b"
"""The token the environment gives every test, which no stream may hold."""
AT = "2026-11-09T10:01:00.000000+00:00"
"""After every stamp of `three_node`."""
HEAD = "2026-11-09T10:00:01.000001+00:00"
"""`head` of `three_node`: a microsecond after its latest stamp, every artifact's checksum's at `fake.G`."""
LATER = "2026-11-09T10:00:05.000000+00:00"
"""A write after every artifact was generated."""
FIXTURE = json.loads(THREE_NODE.read_text())
FIXTURE_ID = blueprint.blueprint_id(FIXTURE)
CONFIGURED = {line.strip() for d in FIXTURE["network"]["devices"] for line in d["config"].splitlines() if line.strip()}
"""Every line of every configuration `three_node` holds."""
SUMMARY = re.compile(r"[0-9a-f]{64} 3 devices, 3 links, 0 probes\n")
UNVERIFIED = Finding(
    rule="infrahub.version.unverified",
    severity="warning",
    object="1.12.0",
    message="Infrahub is version 1.12.0, and this reader is verified on 1.11.11 alone.",
)


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
    held = sum(TOKEN in stream for stream in command.said)
    assert held == 0, "a stream the command printed held the token"


def reader(tmp_path: Path, **changed: Any) -> Path:
    """A reader document file mapping `three_node`'s platform and reading no probe, as `fake.DOCUMENT`, with `changed`
    over it."""
    doc = {
        "reader_version": "1",
        "platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": "nokia_srlinux"}],
        "artifact": "device-config",
        "probes": False,
        **changed,
    }
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(doc))
    return path


def read_args(tmp_path: Path, *more: str) -> list[str]:
    return [
        "read", "--branch", "main", "--scope", "tag:fylgja", "--reader", str(reader(tmp_path)),
        "--out", str(tmp_path / "blueprint.json"), *more,
    ]  # fmt: skip


def configured(said: Said) -> list[str]:
    """Each line of either stream that is a line of a configuration."""
    return [line for line in (said.out + said.err).splitlines() if line.strip() in CONFIGURED]


def stale_n1(source: FakeSource) -> None:
    """`n1` written at `LATER`, after its configuration was generated, so a read after both refuses it."""
    rows = [dataclasses.replace(d, own=stamp(LATER)) if d.name == "n1" else d for d in source.held_stamps.items]
    source.held_stamps = listing("DcimDevice", rows)


def renamed_n1(source: FakeSource) -> None:
    """`n1` named `N1` in Infrahub, which the blueprint names by its label, `n1`."""
    rows = [dataclasses.replace(d, name="N1") if d.name == "n1" else d for d in source.held_devices.items]
    source.held_devices = listing("DcimDevice", rows)


def test_read_writes_the_blueprint_and_prints_its_id(run: Command, tmp_path: Path) -> None:
    said = run(*read_args(tmp_path, "--at", AT))
    assert (said.code, said.err) == (0, "")
    doc = json.loads((tmp_path / "blueprint.json").read_text())
    assert blueprint.validate(doc) == []
    assert blueprint.blueprint_id(doc) == FIXTURE_ID
    assert SUMMARY.fullmatch(said.out)
    assert said.out == f"{FIXTURE_ID} 3 devices, 3 links, 0 probes\n"
    assert configured(said) == []
    assert run.connected == [(ADDRESS, TOKEN, None)]
    assert ("devices", "main", AT) in run.source.calls
    assert run.source.closed
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blueprint.json", "reader.json"], "no file left"
    assert stat.S_IMODE((tmp_path / "blueprint.json").stat().st_mode) == 0o600, "its owner's alone"


def test_a_write_that_fails_leaves_the_file_there_as_it_was(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--out` is written whole or not at all: the blueprint goes to a file of its own beside it, which takes its place
    only once it is written, so a write that fails before then leaves a file already there as it was, and no other
    (ruling P3-40)."""
    out = tmp_path / "blueprint.json"
    out.write_text("a file already there\n")

    def failed(source: str, target: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", failed)
        said = run(*read_args(tmp_path, "--at", AT))
    assert said == Said(2, "", f"{out}: No space left on device\n")
    assert out.read_text() == "a file already there\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["blueprint.json", "reader.json"]

    nowhere = tmp_path / "no-such-directory" / "blueprint.json"
    args = read_args(tmp_path, "--at", AT)
    args[args.index("--out") + 1] = str(nowhere)
    said = run(*args)
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith(f"{nowhere}: ") and len(said.err.splitlines()) == 1
    assert not nowhere.parent.exists()


def test_read_without_at_reads_at_the_head_and_says_so(run: Command, tmp_path: Path) -> None:
    said = run(*read_args(tmp_path))
    assert said.code == 0
    assert SUMMARY.fullmatch(said.out)
    assert len(said.err.splitlines()) == 1 and HEAD in said.err and "main" in said.err
    pinned = {at for name, _, at in run.source.calls if name in ("devices", "ports", "content")}
    assert pinned == {HEAD}
    doc = json.loads((tmp_path / "blueprint.json").read_text())
    assert doc["source"]["at"] == HEAD
    assert blueprint.blueprint_id(doc) == FIXTURE_ID


def test_a_generated_since_that_is_no_time_is_refused_before_head(run: Command, tmp_path: Path) -> None:
    said = run(*read_args(tmp_path, "--generated-since", "yesterday"))
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error at.invalid yesterday: ")
    assert run.source.calls == []
    assert not (tmp_path / "blueprint.json").exists()


@pytest.mark.parametrize("kept", [None, "a file already there\n"], ids=["absent", "present"])
def test_a_refused_read_exits_1_and_writes_nothing(run: Command, tmp_path: Path, kept: str | None) -> None:
    out = tmp_path / "blueprint.json"
    if kept is not None:
        out.write_text(kept)
    stale_n1(run.source)
    said = run(*read_args(tmp_path, "--at", AT))
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error artifact.stale n1: ")
    assert LATER in lines[0]
    assert configured(said) == []
    if kept is None:
        assert not out.exists()
    else:
        assert out.read_text() == kept
    assert run.source.closed


def test_an_info_finding_is_printed_and_the_read_still_succeeds(run: Command, tmp_path: Path) -> None:
    renamed_n1(run.source)
    said = run(*read_args(tmp_path, "--at", AT))
    assert said.code == 0
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("info device.name.renamed N1: ")
    assert SUMMARY.fullmatch(said.out)
    doc = json.loads((tmp_path / "blueprint.json").read_text())
    assert blueprint.validate(doc) == [] and blueprint.blueprint_id(doc) == FIXTURE_ID


def test_head_prints_the_time(run: Command) -> None:
    said = run("head", "--branch", "main", "--scope", "tag:fylgja")
    assert said == Said(0, f"{HEAD}\n", "")
    assert {at for _, _, at in run.source.calls} == {None}
    assert run.source.closed
    run.source.unverified = UNVERIFIED
    warned = run("head", "--branch", "main", "--scope", "tag:fylgja")
    assert (warned.code, warned.out) == (0, f"{HEAD}\n")
    assert warned.err == f"warning infrahub.version.unverified 1.12.0: {UNVERIFIED.message}\n"


def test_head_exits_1_on_scope_empty(run: Command) -> None:
    run.source.held_stamps = listing("DcimDevice", [])
    said = run("head", "--branch", "main", "--scope", "tag:fylgja")
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error scope.empty tag:fylgja: ")


@pytest.mark.parametrize("command", ["head", "read"])
def test_head_over_a_schema_that_differs_exits_1_naming_it(run: Command, tmp_path: Path, command: str) -> None:
    """`head`, and `read` without `--at`, which asks `head` first, print the schema check's findings and exit 1, with
    `--out` not written (P3-51)."""
    held = dcim_schema()
    run.source.held_schema = dataclasses.replace(held, nodes={k: v for k, v in held.nodes.items() if k != "DcimCable"})
    argv = read_args(tmp_path) if command == "read" else ["head", "--branch", "main", "--scope", "tag:fylgja"]
    said = run(*argv)
    assert (said.code, said.out) == (1, "")
    lines = said.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error schema.kind.missing DcimCable: ")
    assert [call[0] for call in run.source.calls] == ["schema"]
    assert not (tmp_path / "blueprint.json").exists()


def test_schema_check_prints_ok_or_the_faults(run: Command) -> None:
    said = run("schema-check", "--branch", "main")
    assert said == Said(0, f"ok: {schema.MODEL}@{schema.COMMIT}\n", "")
    held = dcim_schema()
    run.source.held_schema = dataclasses.replace(held, nodes={k: v for k, v in held.nodes.items() if k != "DcimCable"})
    faulted = run("schema-check", "--branch", "main")
    assert (faulted.code, faulted.out) == (1, "")
    lines = faulted.err.splitlines()
    assert len(lines) == 1 and lines[0].startswith("error schema.kind.missing DcimCable: ")


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
@pytest.mark.parametrize("name", [cli.ADDRESS, cli.TOKEN])
def test_a_variable_not_set_exits_2_naming_it(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    said = run(*read_args(tmp_path, "--at", AT))
    assert said == Said(2, "", f"{name} is not set\n")
    other = TOKEN if name == cli.ADDRESS else ADDRESS
    assert other not in said.out + said.err
    assert run.connected == []
    assert not (tmp_path / "blueprint.json").exists()


@pytest.mark.parametrize(
    ("name", "value", "predicate"),
    [
        (cli.ADDRESS, "ftp://infrahub.example", "is not an http(s):// URL or host:port"),
        (cli.TOKEN, "a token with spaces", "is not an RFC 6750 bearer token"),
        (cli.CA, "no-such-ca.pem", "names no file of CA certificates that can be read"),
    ],
)
def test_a_variable_it_cannot_use_exits_2_naming_it(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str, predicate: str
) -> None:
    """The variable named, then the predicate the client's rule gives (`InvalidAddress`, `InvalidToken`,
    `InvalidCA`), and never the value."""
    monkeypatch.setenv(name, str(tmp_path / value) if name == cli.CA else value)
    said = run("schema-check", "--branch", "main")
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith(f"{name} {predicate}") and len(said.err.splitlines()) == 1
    assert value not in said.err
    assert run.connected == []


def test_every_variable_at_fault_is_named_at_once(run: Command, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.ADDRESS)
    monkeypatch.setenv(cli.TOKEN, "a token with spaces")
    said = run("head", "--branch", "main", "--scope", "tag:fylgja")
    assert said.code == 2
    assert [line.split()[0] for line in said.err.splitlines()] == [cli.ADDRESS, cli.TOKEN]


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
def test_a_reader_document_refused_exits_2_with_its_problems(
    run: Command, tmp_path: Path, changed: dict[str, Any], problem: str
) -> None:
    args = read_args(tmp_path, "--at", AT)
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
    said = run("read", "--branch", "main", "--scope", "tag:fylgja", "--reader", str(missing), "--out",
               str(tmp_path / "blueprint.json"))  # fmt: skip
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith(f"{missing}: ") and len(said.err.splitlines()) == 1
    assert run.connected == []


@pytest.mark.parametrize("where", ["connect", "read"])
def test_an_infrahub_error_exits_2(run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str) -> None:
    message = f"reading Devices (branch main, at {AT}): HTTP 404: Branch: main not found."
    refusal = InfrahubError(message, 404)
    if where == "connect":
        run.refusal = refusal
    else:

        def refused(*args: object) -> None:
            raise refusal

        monkeypatch.setattr(run.source, "devices", refused)
    said = run(*read_args(tmp_path, "--at", AT))
    assert said == Said(2, "", f"{message}\n")
    assert not (tmp_path / "blueprint.json").exists()
    if where == "read":
        assert run.source.closed


def test_any_other_failure_is_one_line_without_the_token(
    run: Command, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failed(*args: object) -> None:
        raise RuntimeError(f"an answer quoting {TOKEN}")

    monkeypatch.setattr(run.source, "devices", failed)
    said = run(*read_args(tmp_path, "--at", AT))
    assert (said.code, said.out) == (2, "")
    assert said.err.startswith("RuntimeError: an answer quoting ") and len(said.err.splitlines()) == 1
    assert run.source.closed


def test_arguments_refused_exit_2_and_connect_nothing(run: Command) -> None:
    said = run("read", "--branch", "main")
    assert (said.code, said.out) == (2, "")
    assert "--scope" in said.err
    assert run.connected == []
    assert run("head", "--branch", "main", "--scope", "tag:fylgja", "--at", AT).code == 2
