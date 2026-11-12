"""The command `fylgja-orchestrator` (D-085): each command calls the rehearsal library in its own process, with no
Prefect and no server, prints a document or its text and exits by it; a fault of its own, of a variable, of the source
or of the core is one line and exit 2, holding no token. `serve` refuses to start without the settings its flows would
fail on. Held to the core's own server on its fake runtime, over the fake change source; Prefect's `serve` is the
test's, and no runner is started."""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import prefect
import pytest
from fylgja_core import ulid
from fylgja_core.client import ProblemError
from fylgja_core.findings import Finding
from fylgja_core.problem import ProblemDocument
from fylgja_infrahub import InfrahubError, document
from harness import ROOT, Clock, Served, Wrapped
from sources import CHANGE, FIVE, SCOPE, FakeSource, empty, refused

from fylgja_orchestrator.edge import cli, run, settings
from fylgja_orchestrator.infrahub import InfrahubSource, SourceError
from fylgja_orchestrator.rehearsal import Change, documents, record, render, twin_name
from fylgja_orchestrator.rehearsal.record import Record

API_TOKEN = "api-test-token"
INFRAHUB_TOKEN = "infrahub-test-token"
ENVIRON = {
    "FYLGJA_API_ADDRESS": "core.example:8443",
    "FYLGJA_API_TOKEN": API_TOKEN,
    "FYLGJA_INFRAHUB_ADDRESS": "infrahub.example:8000",
    "FYLGJA_INFRAHUB_TOKEN": INFRAHUB_TOKEN,
    "FYLGJA_ORCHESTRATOR_SCOPE": SCOPE,
    "FYLGJA_ORCHESTRATOR_READER": str(ROOT / "infrahub" / "seed" / "reader.yaml"),
}
PREFECT_URL = "http://prefect.example:4200/api"
PREFECT_AUTH = "runner:prefect-test-secret"
STALE = Finding(rule="artifact.stale", severity="error", object="n1",
                message="n1's configuration is older than its intent.")
DRAFT = (f"{CHANGE.where} is a draft, and a draft is not rehearsed: mark it ready for review, then re-run its "
         "checks")
NOW = "2026-11-09T10:15:11Z"


@dataclass
class Opened:
    """What `run.opened` answered the command: `source`, which a test may replace before the command runs, and the
    served core with its `close` the test's, each call of which is counted in `core_closed`. `given` holds the
    settings each call of `run.opened` was handed."""

    source: FakeSource
    core: Wrapped
    core_closed: list[None] = field(default_factory=list)
    given: list[settings.Settings] = field(default_factory=list)

    def closed(self) -> tuple[bool, int]:
        """Whether the source was closed, and how many times the core was."""
        return self.source.closed, len(self.core_closed)


@pytest.fixture
def opened(served: Served, monkeypatch: pytest.MonkeyPatch) -> Opened:
    made = Opened(FakeSource(CHANGE, FIVE), Wrapped(served.client))
    made.core.close = lambda: made.core_closed.append(None)  # type: ignore[method-assign]

    def opening(given: settings.Settings) -> tuple[FakeSource, Wrapped]:
        made.given.append(given)
        return made.source, made.core

    monkeypatch.setattr(run, "opened", opening)
    return made


def environ(tmp_path: Path, **more: str) -> dict[str, str]:
    """The command's environment: `ENVIRON`, its records under `tmp_path`, and `more`."""
    return ENVIRON | {"FYLGJA_ORCHESTRATOR_ROOT": str(tmp_path / "records")} | more


def called(capsys: pytest.CaptureFixture[str], argv: Sequence[str], env: dict[str, str]) -> tuple[int, str, str]:
    """`fylgja-orchestrator argv` under `env`: its exit code, its stdout and its stderr."""
    code = cli.main(argv, environ=env)
    out, err = capsys.readouterr()
    return code, out, err


def clocked(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`run.rehearse` given the harness's clock and sleep, which never wait; each document it answers recorded, and
    each run id it was given, in the list answered, under `run_id`."""
    c, answered = Clock(), list[dict[str, Any]]()
    rehearse = functools.partial(run.rehearse, clock=c.now, sleep=c.sleep)

    def recorded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        doc = rehearse(*args, **kwargs)
        answered.append(doc)
        return doc

    monkeypatch.setattr(run, "rehearse", recorded)
    return answered


def test_stage_list_prints_a_line_a_stage_and_json_the_document(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    code, out, err = called(capsys, ["twin", "create", "--branch", CHANGE.ref, "--twin", "demo"], env)
    assert code == 0, err
    root = Path(env["FYLGJA_ORCHESTRATOR_ROOT"])
    record.write(root, Record("gone", CHANGE.id, CHANGE.ref, SCOPE, "seeded", "0" * 64, NOW))

    code, out, err = called(capsys, ["stage", "list", "--branch", CHANGE.ref], env)
    assert (code, err) == (0, "")
    stages = [stage for stage, _ in FIVE]
    assert out.splitlines() == [
        "1 branch-point: stage branch-point as pinned",
        "2 seeded: stage seeded as pinned; at it: demo",
        "3 third-node: stage third-node as pinned",
        "4 third-link: stage third-link as pinned",
        "5 head: stage head as pinned",
        "stale: gone",
    ]

    code, out, err = called(capsys, ["stage", "list", "--branch", CHANGE.ref, "--json"], env)
    assert (code, err) == (0, "")
    assert json.loads(out) == {
        "change": {"ref": CHANGE.ref, "id": CHANGE.id, "name": CHANGE.name, "where": CHANGE.where},
        "stages": [{"label": s.label, "description": s.description, "where": s.where} for s in stages],
        "at": {"demo": "seeded"},
        "stale": ["gone"],
    }
    assert opened.closed() == (True, 3)
    assert [given.root for given in opened.given] == [root] * 3


def test_twin_create_and_step_print_the_twin_its_stage_its_blueprint_and_the_verdict(
    opened: Opened, served: Served, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    code, out, err = called(capsys, ["twin", "create", "--branch", CHANGE.ref, "--twin", "demo"], env)
    twin, _ = served.other.get_twin("demo")
    assert code == 0
    assert out == f"demo: stage seeded, blueprint {twin['status']['blueprint_id']}, run ok\n"
    assert err.splitlines()[0] == "create: stage 2, seeded, as demo"

    code, out, err = called(capsys, ["twin", "step", "--branch", CHANGE.ref, "--twin", "demo", "--json"], env)
    assert code == 0
    made = json.loads(out)
    twin, _ = served.other.get_twin("demo")
    assert set(made) == {"twin", "stage", "blueprint_id", "run", "findings"}
    assert (made["twin"], made["stage"]["label"], made["blueprint_id"]) == ("demo", "third-node",
                                                                           twin["status"]["blueprint_id"])
    assert "pin" not in made["stage"] and made["findings"] == []
    assert (made["run"]["operation"], made["run"]["verdict"]["status"]) == ("step", "ok")

    # A step past the last stage is refused by the command's own finding: no run, exit 1.
    code, out, err = called(capsys, ["twin", "step", "--branch", CHANGE.ref, "--twin", "demo", "--stage", "nowhere"],
                            env)
    assert (code, out) == (1, "demo: no stage, no blueprint, no run\n")
    assert err == f"error step.target.unknown demo: {CHANGE.where} has no stage nowhere.\n"
    assert opened.closed() == (True, 3)


def test_stage_plan_exits_by_the_documents_status(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref, "--json"], env)
    assert code == 0
    doc = json.loads(out)
    assert documents.validate("plan-1", doc) == [] and doc["status"] == "planned"
    assert err.splitlines()[0] == "plan: stage 1 of 5, branch-point: empty"

    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref], env)
    assert code == 0
    lines = out.splitlines()
    head = doc["stages"][4]
    assert lines[:3] == [*doc["headline"].splitlines(), CHANGE.where]
    assert lines[3] == "1 branch-point: empty"
    assert lines[4] == f"2 seeded: built, {doc['stages'][1]['changed']}, bundle {doc['stages'][1]['bundle_id'][:12]}"
    assert lines[7] == f"5 head: built, {head['changed']} (unchanged), bundle {head['bundle_id'][:12]}"
    assert len(lines) == 8 and head["unchanged"] is True

    opened.source = FakeSource(CHANGE, (*FIVE[:4], refused("head", STALE)))
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref], env)
    assert code == 1
    assert out.splitlines()[-1] == "5 head: refused"
    # The plan's own finding first, then each stage's in order: the branch point's, then the head's.
    said = [line for line in err.splitlines() if line.startswith("error ")]
    assert [line.split(" ")[1] for line in said] == ["stage.refused", "scope.empty", "artifact.stale"]
    assert said[0].startswith("error stage.refused head: ")
    assert said[2] == f"error artifact.stale n1: {STALE.message}"

    opened.source = FakeSource(CHANGE, (empty("branch-point"), empty("head")))
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref, "--json", "--scope", "tag:other"], env)
    doc = json.loads(out)
    assert (code, doc["status"], doc["scope"]) == (1, "empty", "tag:other")
    assert opened.closed() == (True, 4)


def test_a_scope_given_stands_in_for_its_variable_and_stage_list_takes_none(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    del env["FYLGJA_ORCHESTRATOR_SCOPE"]
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref, "--scope", "tag:other", "--json"], env)
    assert (code, json.loads(out)["scope"]) == (0, "tag:other")
    assert [given.scope for given in opened.given] == ["tag:other"]

    code, out, err = called(capsys, ["stage", "list", "--branch", CHANGE.ref, "--scope", "tag:other"], env)
    assert (code, out) == (2, "")
    assert "unrecognized arguments: --scope tag:other" in err
    code, out, err = called(capsys, ["stage", "list", "--branch", CHANGE.ref], env)
    assert (code, err) == (2, "FYLGJA_ORCHESTRATOR_SCOPE is not set\n")


def test_twin_rehearse_prints_the_summary_then_the_detail_and_exits_0_when_passed_1_otherwise(
    opened: Opened, served: Served, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch
) -> None:
    answered = clocked(monkeypatch)
    env = environ(tmp_path)
    code, out, err = called(capsys, ["twin", "rehearse", "--branch", CHANGE.ref], env)
    (doc,) = answered
    assert (code, doc["status"]) == (0, "passed")
    whole = render(doc, limit=None)
    assert out == f"{whole.summary}\n\n{whole.detail}\n"
    assert err.splitlines()[0] == "plan: stage 1 of 5, branch-point: empty"
    prefix, _, made = doc["run_id"].partition("-")
    assert prefix == "cli" and ulid.PATTERN.match(made)
    assert doc["twin"] == twin_name(CHANGE, doc["run_id"])
    assert served.other.list_twins() == []

    opened.source = FakeSource(CHANGE, (empty("branch-point"), empty("head")))
    code, out, err = called(capsys, ["twin", "rehearse", "--branch", CHANGE.ref, "--json"], env)
    assert code == 1
    assert json.loads(out) == answered[1]
    assert answered[1]["status"] == "not_rehearsed" and answered[1]["run_id"] != doc["run_id"]
    assert opened.closed() == (True, 2)


def test_a_draft_is_one_line_and_exit_1(opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    opened.source = FakeSource(CHANGE, FIVE, draft=True)
    code, out, err = called(capsys, ["twin", "rehearse", "--branch", CHANGE.ref], environ(tmp_path))
    assert (code, out, err) == (1, "", f"{DRAFT}\n")
    assert opened.source.reads == [] and opened.closed() == (True, 1)


def test_a_variable_unset_is_named_and_exit_2(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    del env["FYLGJA_INFRAHUB_TOKEN"]
    code, out, err = called(capsys, ["stage", "list", "--branch", CHANGE.ref], env)
    assert (code, out, err) == (2, "", "FYLGJA_INFRAHUB_TOKEN is not set\n")

    code, out, err = called(capsys, ["twin", "rehearse", "--branch", CHANGE.ref], {})
    assert (code, out) == (2, "")
    assert err.splitlines() == [f"{name} is not set" for name in settings.NAMES if name not in settings.OPTIONAL]
    assert opened.given == []


def test_a_variable_the_clients_refuse_is_named_and_exit_2(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refused_token = "two words"
    env = environ(tmp_path, FYLGJA_API_ADDRESS="ftp://core.example", FYLGJA_INFRAHUB_TOKEN=refused_token,
                  FYLGJA_INFRAHUB_CA=str(tmp_path / "no-such-ca.pem"))
    del env["FYLGJA_ORCHESTRATOR_SCOPE"]
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref], env)
    assert (code, out) == (2, "")
    assert err.splitlines() == [
        "FYLGJA_API_ADDRESS is not an http(s):// URL or host:port",
        "FYLGJA_INFRAHUB_TOKEN is not an RFC 6750 bearer token: letters, digits and -._~+/ with trailing =",
        "FYLGJA_INFRAHUB_CA names no file of CA certificates that can be read",
        "FYLGJA_ORCHESTRATOR_SCOPE is not set",
    ]
    leaked = refused_token in err
    assert not leaked
    assert opened.given == []


class Failing(FakeSource):
    """A source whose `change` raises `error`."""

    def __init__(self, error: Exception) -> None:
        super().__init__(CHANGE, FIVE)
        self.error = error

    def change(self, ref: str) -> Change:
        raise self.error


def test_a_source_error_is_one_line_and_exit_2(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    errors: list[tuple[Exception, str]] = [
        (SourceError("no open proposed change has source branch third-link"),
         "no open proposed change has source branch third-link"),
        (InfrahubError("reading branch third-link: Infrahub was not reached", None),
         "reading branch third-link: Infrahub was not reached"),
        (RuntimeError(f"a fault quoting {INFRAHUB_TOKEN} and {API_TOKEN}"),
         "RuntimeError: a fault quoting <token> and <token>"),
    ]
    for error, line in errors:
        opened.source = Failing(error)
        for argv in (["stage", "list"], ["stage", "plan"], ["twin", "rehearse"],
                     ["twin", "create", "--twin", "demo"]):
            code, out, err = called(capsys, [*argv, "--branch", CHANGE.ref], env)
            assert (code, out, err) == (2, "", f"{line}\n"), argv
            assert opened.source.closed
    assert len(opened.core_closed) == 12


def forbidden(doc: dict[str, Any]) -> str:
    """The core's answer to a blueprint filed by a principal it does not allow, raised as the client raises it."""
    raise ProblemError(403, ProblemDocument(type="about:blank", title="Forbidden", status=403, rule="auth.forbidden",
                                            detail="the principal may not file a blueprint"))


def test_a_core_that_refuses_is_one_line_and_exit_2(
    opened: Opened, served: Served, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened.core = Wrapped(served.client, put_blueprint=forbidden)
    opened.core.close = lambda: opened.core_closed.append(None)  # type: ignore[method-assign]
    code, out, err = called(capsys, ["twin", "create", "--branch", CHANGE.ref, "--twin", "demo"], environ(tmp_path))
    assert (code, out, err) == (2, "", "403 auth.forbidden: the principal may not file a blueprint\n")
    assert opened.closed() == (True, 1)


def answering(status: int, body: dict[str, Any] | None = None) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body or {}))


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_of_the_source_names_the_variable_and_exit_2(
    status: int, opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch
) -> None:
    reading = document.load(Path(ENVIRON["FYLGJA_ORCHESTRATOR_READER"]))
    source = InfrahubSource("infrahub.example:8000", INFRAHUB_TOKEN, reading, transport=answering(status))
    monkeypatch.setattr(run, "opened", lambda given: (source, opened.core))
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref], environ(tmp_path))
    assert (code, out) == (2, "")
    (line,) = err.splitlines()
    sentence = ("the change source's token was refused" if status == 401
                else "the change source's account lacks a permission")
    assert sentence in line
    assert line.endswith("; the change source's token is the one in FYLGJA_INFRAHUB_TOKEN")
    leaked = INFRAHUB_TOKEN in err
    assert not leaked
    assert len(opened.core_closed) == 1


def test_the_variable_is_named_by_the_refusals_status_and_never_its_words(
    opened: Opened, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path)
    named = "; the change source's token is the one in FYLGJA_INFRAHUB_TOKEN"
    for error, line in [
        (SourceError("asked, and refused", status=401), f"asked, and refused{named}"),
        (SourceError("asked, and refused", status=403), f"asked, and refused{named}"),
        (SourceError("the change source's token was refused, it says"), "the change source's token was refused, it "
                                                                         "says"),
    ]:
        opened.source = Failing(error)
        code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref], env)
        assert (code, out, err) == (2, "", f"{line}\n")


def test_a_reader_document_refused_or_unread_names_its_variable_and_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    refused_reader = tmp_path / "refused.yaml"
    refused_reader.write_text("reader_version: '9'\n")
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref],
                            environ(tmp_path, FYLGJA_ORCHESTRATOR_READER=str(refused_reader)))
    said = err.splitlines()
    assert (code, out) == (2, "")
    assert said[0] == f"FYLGJA_ORCHESTRATOR_READER names {refused_reader}, which is not a valid reader document:"
    assert len(said) > 1 and all(line.startswith("  ") for line in said[1:])

    missing = tmp_path / "missing.yaml"
    code, out, err = called(capsys, ["stage", "plan", "--branch", CHANGE.ref],
                            environ(tmp_path, FYLGJA_ORCHESTRATOR_READER=str(missing)))
    assert (code, out, err) == (2, "", f"FYLGJA_ORCHESTRATOR_READER names {missing}: No such file or directory\n")


@dataclass
class Serving:
    """Prefect's `serve` replaced: each call's deployments and keywords recorded, and no runner started."""

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)
    fail: Exception | None = None

    def __call__(self, *deployments: Any, **keywords: Any) -> None:
        self.calls.append((deployments, keywords))
        if self.fail is not None:
            raise self.fail


@pytest.fixture
def serving(monkeypatch: pytest.MonkeyPatch) -> Serving:
    recorded = Serving()
    monkeypatch.setattr(prefect, "serve", recorded)
    return recorded


def test_serve_refuses_without_a_prefect_address(
    serving: Serving, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = called(capsys, ["serve"], environ(tmp_path))
    assert (code, out, err) == (2, "", "PREFECT_API_URL is not set: make orchestrator-serve sets it\n")
    assert serving.calls == []


def test_serve_refuses_with_a_setting_unset(
    serving: Serving, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path, PREFECT_API_URL=PREFECT_URL)
    del env["FYLGJA_ORCHESTRATOR_ROOT"]
    code, out, err = called(capsys, ["serve"], env)
    assert (code, out, err) == (2, "", "FYLGJA_ORCHESTRATOR_ROOT is not set\n")
    assert serving.calls == []


def test_serves_start_line_names_both_deployments_and_no_credential(
    serving: Serving, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path, PREFECT_API_URL=PREFECT_URL, PREFECT_API_AUTH_STRING=PREFECT_AUTH)
    code, out, err = called(capsys, ["serve"], env)
    assert (code, out, err) == (0, f"fylgja-orchestrator: serving stage-plan/main, twin-rehearse/main at "
                                   f"{PREFECT_URL}\n", "")
    leaked = any(secret in out + err for secret in (PREFECT_AUTH, API_TOKEN, INFRAHUB_TOKEN))
    assert not leaked
    ((deployments, keywords),) = serving.calls
    assert keywords == {"pause_on_shutdown": False, "print_starting_message": False}
    assert [(d.flow_name, d.name, d.entrypoint) for d in deployments] == [
        ("stage-plan", "main", "fylgja_orchestrator.edge.flows.stage_plan"),
        ("twin-rehearse", "main", "fylgja_orchestrator.edge.flows.twin_rehearse"),
    ]


def test_the_help_of_each_command_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    commands: list[list[str]] = [[], ["stage", "list"], ["stage", "plan"], ["twin", "create"], ["twin", "step"],
                                 ["twin", "rehearse"], ["serve"]]
    for argv in commands:
        assert cli.main([*argv, "--help"], environ={}) == 0, argv
    capsys.readouterr()
    assert cli.main(["twin", "create", "--branch", CHANGE.ref], environ={}) == 2  # --twin is required
    assert "--twin" in capsys.readouterr().err


def test_serve_refuses_a_variable_the_clients_refuse_in_one_line(
    serving: Serving, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = environ(tmp_path, PREFECT_API_URL=PREFECT_URL, FYLGJA_API_TOKEN="two words",
                  FYLGJA_INFRAHUB_ADDRESS="ftp://infrahub.example")
    code, out, err = called(capsys, ["serve"], env)
    assert (code, out) == (2, "")
    assert err == ("FYLGJA_API_TOKEN is not an RFC 6750 bearer token: letters, digits and -._~+/ with trailing =; "
                   "FYLGJA_INFRAHUB_ADDRESS is not an http(s):// URL or host:port\n")
    leaked = "two words" in err
    assert not leaked
    assert serving.calls == []


def test_a_fault_as_serving_begins_is_one_line_and_exit_2(
    serving: Serving, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    serving.fail = RuntimeError(f"no API at {PREFECT_URL} for {PREFECT_AUTH} with {API_TOKEN}")
    env = environ(tmp_path, PREFECT_API_URL=PREFECT_URL, PREFECT_API_AUTH_STRING=PREFECT_AUTH)
    code, out, err = called(capsys, ["serve"], env)
    assert code == 2 and out.startswith("fylgja-orchestrator: serving ")
    assert err == f"RuntimeError: no API at {PREFECT_URL} for <token> with <token>\n"
    assert len(serving.calls) == 1
