"""`fylgja-cli` and the runner (T027; FR-020, R-02, R-08): each command's flags reaching its
flow as the flow's parameters, with the flows stubbed; what is printed where in text, under
--json and under --markdown, and the exit by the document's status; a command line refused as
the command's document, an unknown command a line and exit 2; the platform asked first and
`platform.unreachable` when it does not answer; a document filed before a flow raised still
printed; `stage list`'s twin row from the orchestrator's record, the golden's bytes; and
`fylgja-orchestrator serve`'s six deployments and its start-up line."""

import io
import json

import httpx
import pytest

from fylgja_orchestrator import cli, record, serve
from fylgja_orchestrator.adapters.infrahub import __main__ as tool
from fylgja_orchestrator.core import CoreFailure
from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents.findings import (
    INFO,
    OP_STAGE_LIST,
    OP_TWIN_CREATE,
    OP_TWIN_REHEARSE,
    REJECTION,
    WARNING,
    Document,
    Finding,
    Findings,
)
from fylgja_orchestrator.flows import common, stage_list, twin_rehearse
from fylgja_orchestrator.record import ChangeRef, StageRef, Store, new_record

from .test_flows import FakeCore, show_of
from .test_stages import GOLDEN, serve_recorded

SCOPE = "tag:fylgja"
ENVIRON = {"FYLGJA_DEFAULT_SCOPE": SCOPE}


def doc_of(op: str, status: str = "ok", *found: Finding) -> Document:
    return Document(op, status, {"branch": "b"}, Findings(found))


class Flows(dict):
    """The runners by flow name, each recording its parameters and answering with `doc`
    after printing `lines` through the out sink, as a flow's out_line does."""

    def __init__(self, doc: Document | None = None, lines=(), markdown: str = "", raises: BaseException | None = None,
                 files: bool = False):
        super().__init__()
        self.calls = []
        for _, flow in cli.COMMANDS.values():
            self[flow] = self._runner(flow, doc, lines, markdown, raises, files)

    def _runner(self, flow, doc, lines, markdown, raises, files):
        def run(**kw):
            self.calls.append((flow, kw))
            for line in lines:
                common.OUT.get()(line)
            if markdown and kw.get("markdown"):
                (twin_rehearse.MARKDOWN.get() or common.OUT.get())(markdown)
            if files:
                common.publish(flow, doc)
            if raises is not None:
                raise raises
            return doc
        return run


def run_cli(argv, flows=None, environ=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out, err, dict(ENVIRON if environ is None else environ), flows)
    return code, out.getvalue(), err.getvalue()


# The flags.


@pytest.mark.parametrize("argv, flow, params", [
    (["intent", "read", "--branch", "b", "--out", "s.json"], "intent-read",
     {"branch": "b", "at": "", "stage": None, "scope": None, "probes_path": None, "out": "s.json"}),
    (["intent", "read", "--stage", "b/l", "--scope", "tag:x", "--probes", "p.json", "--at", "t", "--out", "o"],
     "intent-read", {"branch": "", "at": "t", "stage": "b/l", "scope": "tag:x", "probes_path": "p.json", "out": "o"}),
    (["stage", "list"], "stage-list", {"branch": None, "scope": None}),
    (["stage", "list", "--branch", "b", "--scope", "tag:x"], "stage-list", {"branch": "b", "scope": "tag:x"}),
    (["stage", "plan", "--branch", "b", "--probes", "p"], "stage-plan",
     {"branch": "b", "scope": None, "probes_path": "p"}),
    (["twin", "create", "--branch", "b"], "twin-create",
     {"branch": "b", "stage": None, "scope": None, "probes_path": None, "dry_run": False}),
    (["twin", "create", "--stage", "b/l", "--scope", "tag:x", "--probes", "p", "--dry-run"], "twin-create",
     {"branch": "", "stage": "b/l", "scope": "tag:x", "probes_path": "p", "dry_run": True}),
    (["twin", "step"], "twin-step",
     {"stage": None, "scope": None, "probes_path": None, "allow_restart": False, "wait": None, "dry_run": False}),
    (["twin", "step", "--stage", "b/l", "--allow-restart", "--wait", "30s", "--dry-run", "--probes", "p"], "twin-step",
     {"stage": "b/l", "scope": None, "probes_path": "p", "allow_restart": True, "wait": "30s", "dry_run": True}),
    (["twin", "rehearse", "--branch", "b"], "twin-rehearse",
     {"branch": "b", "scope": None, "probes_path": None, "markdown": False}),
    (["schema", "check", "--branch", "b"], "schema-check", {"branch": "b"}),
])
def test_each_commands_flags_are_its_flows_parameters(argv, flow, params):
    flows = Flows(doc_of("x"))
    code, _, _ = run_cli(argv, flows)
    assert code == 0
    assert flows.calls == [(flow, params)]


def test_an_empty_flag_given_is_sent_as_given():
    """--stage= and --scope= are values given, which the flows refuse, never flags left out."""
    flows = Flows(doc_of("x"))
    run_cli(["twin", "create", "--stage=", "--scope="], flows)
    assert flows.calls[0][1]["stage"] == "" and flows.calls[0][1]["scope"] == ""


@pytest.mark.parametrize("argv", [["--json", "twin", "create", "--branch", "b"],
                                  ["twin", "create", "--branch", "b", "--json"]])
def test_json_on_the_root_or_the_command(argv):
    code, stdout, _ = run_cli(argv, Flows(doc_of(OP_TWIN_CREATE)))
    assert code == 0 and json.loads(stdout)["operation"] == OP_TWIN_CREATE


def test_every_command_runs_its_flow():
    assert {flow for _, flow in cli.COMMANDS.values()} == {
        "intent-read", "stage-list", "stage-plan", "twin-create", "twin-step", "twin-rehearse", "schema-check"}
    runners = cli.runners()
    assert set(runners) == {flow for _, flow in cli.COMMANDS.values()}
    for name, runner in runners.items():
        if name != "stage-list":
            assert runner.name == name


# What is printed, and the exit.


def test_text_the_out_lines_on_stdout_the_findings_on_stderr():
    doc = doc_of(OP_TWIN_CREATE, "rejected", Finding(REJECTION, "host.twin.present", "host", "a twin stands"),
                 Finding(WARNING, "host.memory.low", "host", "short"))
    code, stdout, stderr = run_cli(["twin", "create", "--branch", "b"], Flows(doc, ["one", "two"]))
    assert code == 1
    assert stdout == "one\ntwo\n"
    assert stderr == doc.text()


@pytest.mark.parametrize("status, code", [("ok", 0), ("rejected", 1), ("error", 2), ("failed", 3), ("unclean", 4),
                                          ("diverged", 4), ("nonconforming", 5)])
def test_the_exit_is_the_documents_status(status, code):
    assert run_cli(["twin", "step"], Flows(doc_of("twin.step", status)))[0] == code


def test_json_the_document_alone_on_stdout():
    doc = doc_of(OP_TWIN_CREATE, "ok", Finding(INFO, "run.done", "r", "done"))
    code, stdout, stderr = run_cli(["twin", "create", "--branch", "b", "--json"], Flows(doc, ["one"]))
    assert (code, stdout, stderr) == (0, doc.json(), "")


def test_markdown_the_report_alone_on_stdout():
    doc = doc_of(OP_TWIN_REHEARSE, "nonconforming", Finding(REJECTION, "verify.link.down", "n1", "down"))
    flows = Flows(doc, ["planned", "ran"], markdown="## report\n\n| stage |")
    code, stdout, stderr = run_cli(["twin", "rehearse", "--branch", "b", "--markdown"], flows)
    assert code == 5
    assert stdout == "## report\n\n| stage |\n"
    assert stderr == "planned\nran\n" + doc.text()
    assert flows.calls[0][1]["markdown"] is True


def test_markdown_beside_json_is_refused():
    flows = Flows(doc_of(OP_TWIN_REHEARSE))
    code, stdout, _ = run_cli(["twin", "rehearse", "--branch", "b", "--markdown", "--json"], flows)
    doc = json.loads(stdout)
    assert code == 2 and doc["operation"] == OP_TWIN_REHEARSE and not flows.calls
    findings.validate(doc)


def test_a_document_filed_before_the_flow_raised_is_printed():
    """The rehearse flow files its document, then raises the timeout that reached it."""
    doc = doc_of(OP_TWIN_REHEARSE, "error", Finding(REJECTION, "rehearsal.deadline.cut", "b", "cut"))
    code, stdout, stderr = run_cli(["twin", "rehearse", "--branch", "b"],
                                   Flows(doc, raises=TimeoutError("timed out"), files=True))
    assert (code, stdout, stderr) == (2, "", doc.text())


@pytest.mark.parametrize("raised, why", [(RuntimeError("the server did not start"), "the server did not start"),
                                         (KeyboardInterrupt(), "interrupted")])
def test_a_flow_that_ended_with_no_document(raised, why):
    code, stdout, _ = run_cli(["twin", "create", "--branch", "b", "--json"], Flows(None, raises=raised))
    doc = json.loads(stdout)
    findings.validate(doc)
    assert code == 2 and doc["operation"] == OP_TWIN_CREATE
    [f] = doc["findings"]
    assert f["rule"] == "operation.failed" and why in f["message"] and "fylgja twin show" in f["message"]


def test_the_sinks_are_put_back():
    run_cli(["twin", "rehearse", "--branch", "b", "--markdown"], Flows(doc_of(OP_TWIN_REHEARSE)))
    assert common.OUT.get() is common._print
    assert common.FILED.get() is None and twin_rehearse.MARKDOWN.get() is None


# The command line refused.


def test_an_unknown_command_is_a_line_and_exit_2():
    flows = Flows(doc_of("x"))
    code, stdout, stderr = run_cli(["nope"], flows)
    assert code == 2 and stdout == "" and stderr.startswith("fylgja-cli: ") and "nope" in stderr
    code, _, stderr = run_cli(["twin", "nope"], flows)
    assert code == 2 and stderr.startswith("fylgja-cli: ")
    assert not flows.calls


@pytest.mark.parametrize("argv", [["twin", "create", "--nope"], ["twin", "create", "extra"],
                                  ["twin", "step", "--allow-restart=yes"]])
def test_a_commands_flag_refused_is_its_document(argv):
    code, stdout, stderr = run_cli(argv, Flows(doc_of("x")))
    assert code == 2 and stdout == ""
    assert stderr.startswith(f"rejection operation.failed {'.'.join(argv[:2])}: ")
    code, stdout, _ = run_cli(argv + ["--json"], Flows(doc_of("x")))
    doc = json.loads(stdout)
    findings.validate(doc)
    assert code == 2 and doc["operation"] == ".".join(argv[:2]) and doc["status"] == "error"


@pytest.mark.parametrize("argv", [[], ["twin"], ["stage"]])
def test_no_command_prints_the_help(argv):
    code, stdout, stderr = run_cli(argv, Flows(doc_of("x")))
    assert code == 0 and stdout.startswith("usage: fylgja-cli") and stderr == ""


def test_help_and_version():
    code, _, _ = run_cli(["twin", "create", "--help"], Flows(doc_of("x")))
    assert code == 0
    code, _, _ = run_cli(["--version"], Flows(doc_of("x")))
    assert code == 0


# The platform.


def test_a_platform_that_does_not_answer_is_refused_before_the_flow():
    flows = Flows(doc_of("x"))
    env = {**ENVIRON, "PREFECT_API_URL": "http://127.0.0.1:9/api", "PREFECT_API_AUTH_STRING": "fylgja:sentinel-auth"}
    code, stdout, _ = run_cli(["twin", "create", "--branch", "b", "--json"], flows, env)
    doc = json.loads(stdout)
    findings.validate(doc)
    assert code == 2 and not flows.calls
    [f] = doc["findings"]
    assert (f["rule"], f["object"]) == ("platform.unreachable", "http://127.0.0.1:9/api")
    assert "sentinel-auth" not in stdout


def test_stage_list_asks_no_platform():
    flows = Flows(doc_of(OP_STAGE_LIST))
    env = {**ENVIRON, "PREFECT_API_URL": "http://127.0.0.1:9/api"}
    assert run_cli(["stage", "list"], flows, env)[0] == 0 and flows.calls


def platform(status: int):
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={})
    return httpx.MockTransport(answer), seen


def test_the_platform_check_asks_version_with_the_credential():
    transport, seen = platform(200)
    env = {"PREFECT_API_URL": "http://prefect.test/api/", "PREFECT_API_AUTH_STRING": "fylgja:sentinel-auth"}
    record.check_platform(env, transport)
    [req] = seen
    assert str(req.url) == "http://prefect.test/api/version"
    assert req.headers["authorization"] == httpx.BasicAuth("fylgja", "sentinel-auth")._auth_header


def test_the_platform_check_refuses_a_credential_it_does_not_take():
    transport, _ = platform(401)
    env = {"PREFECT_API_URL": "http://prefect.test/api", "PREFECT_API_AUTH_STRING": "fylgja:sentinel-auth"}
    with pytest.raises(CoreFailure) as e:
        record.check_platform(env, transport)
    assert e.value.rule == "platform.unreachable" and "401" in e.value.message
    assert "PREFECT_API_AUTH_STRING" in e.value.message and "sentinel-auth" not in e.value.message


def test_the_platform_check_with_no_platform_asks_nothing():
    transport, seen = platform(500)
    record.check_platform({}, transport)
    assert not seen


def test_prepare_gives_prefects_settings_defaults_and_keeps_what_is_set():
    env = {"PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS": "60"}
    cli.prepare(env)
    assert env == {"PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS": "60",
                   "PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL": "CRITICAL"}


# stage list's twin row (FR-021, US6 scenarios 1 and 2).

GOLDEN_BRANCH = "fylgja-test-golden-41263"
GOLDEN_PC = "18e3127c-025b-f488-33be-c5158cf576c3"
SEEDED_AT = "2026-10-29T18:11:38.471611+00:00"
SNAPSHOT = "5" * 64


def listing_deps(tmp_path, infrahub, core):
    lines = []
    env = {**ENVIRON, "INFRAHUB_ADDRESS": "http://infrahub.test", "INFRAHUB_API_TOKEN": "sentinel-token"}
    deps = common.Deps(core=core, store=Store(tmp_path / "orchestrator"), environ=env, out=lines.append)
    deps.stage_list = lambda b, s, _, rec: tool.stage_list(b, s, tool.Env(environ=env, requester=infrahub), rec)
    return deps, lines


def seeded(deps):
    deps.store.write_record(new_record(StageRef(GOLDEN_BRANCH, "seeded", SEEDED_AT),
                                       ChangeRef(GOLDEN_PC, GOLDEN_BRANCH), SNAPSHOT, "run-0", record.FLOW_CREATE))


def test_stage_list_marks_the_records_stage_while_trusted(tmp_path, infrahub):
    """The record names a mark and no at's source: the listing's own, `written`, as the
    golden captured from `fylgja stage list` with its twin has it, byte for byte."""
    serve_recorded(infrahub, "golden.json")
    deps, lines = listing_deps(tmp_path, infrahub, FakeCore([show_of(SNAPSHOT, state="ready")]))
    seeded(deps)

    doc = stage_list.run(deps, GOLDEN_BRANCH)

    assert doc.json() == (GOLDEN / "stages-with-twin.json").read_text()
    assert "".join(line + "\n" for line in lines) == (GOLDEN / "stages-with-twin.txt").read_text()


def test_stage_list_with_the_record_distrusted_marks_no_row(tmp_path, infrahub):
    serve_recorded(infrahub, "golden.json")
    deps, lines = listing_deps(tmp_path, infrahub, FakeCore([show_of("6" * 64)]))
    seeded(deps)

    doc = stage_list.run(deps, GOLDEN_BRANCH)

    got = json.loads(doc.json())
    stale = got["findings"].pop(0)
    assert got == json.loads((GOLDEN / "stages.json").read_text())
    assert (stale["severity"], stale["rule"]) == (INFO, "record.twin.stale")
    assert stale["object"] == str(deps.store.record_path)
    assert "6666" in stale["message"] and "no stage is marked" in stale["message"]
    assert "".join(line + "\n" for line in lines) == (GOLDEN / "stages.txt").read_text()


def test_stage_list_with_no_record_asks_no_core(tmp_path, infrahub):
    serve_recorded(infrahub, "golden.json")
    core = FakeCore()
    deps, _ = listing_deps(tmp_path, infrahub, core)
    doc = stage_list.run(deps, GOLDEN_BRANCH)
    assert doc.json() == (GOLDEN / "stages.json").read_text() and not core.calls


def test_stage_list_with_a_record_and_the_core_unreachable(tmp_path, infrahub):
    class Down(FakeCore):
        def show(self):
            raise CoreFailure("api.unreachable", "127.0.0.1:7650", "the API at 127.0.0.1:7650 cannot be reached")

    deps, lines = listing_deps(tmp_path, infrahub, Down())
    seeded(deps)
    doc = stage_list.run(deps, GOLDEN_BRANCH)
    assert doc.exit_code == 2 and [f.rule for f in doc.findings] == ["api.unreachable"] and not lines


@pytest.mark.parametrize("branch, scope, rule", [("bad branch", None, "stage.ref.invalid"),
                                                 (None, "nope", "scope.invalid")])
def test_stage_list_guards_before_the_record(tmp_path, infrahub, branch, scope, rule):
    deps, _ = listing_deps(tmp_path, infrahub, FakeCore())
    deps.store.record_path.parent.mkdir(parents=True)
    deps.store.record_path.write_text("not a record")
    doc = stage_list.run(deps, branch, scope)
    assert [f.rule for f in doc.findings] == [rule] and doc.exit_code == 2


# The runner.


def test_serve_needs_the_platform():
    out, err = io.StringIO(), io.StringIO()
    assert serve.main(["serve"], out, err, {}, serve=lambda *d: None) == 2
    assert "PREFECT_API_URL is not set" in err.getvalue() and out.getvalue() == ""

    err = io.StringIO()
    env = {"PREFECT_API_URL": "http://127.0.0.1:9/api", "PREFECT_API_AUTH_STRING": "fylgja:sentinel-auth"}
    assert serve.main(["serve"], out, err, env, serve=lambda *d: None) == 2
    assert "did not answer" in err.getvalue() and "sentinel-auth" not in err.getvalue()


def test_serve_serves_the_six_deployments(monkeypatch):
    monkeypatch.setattr(serve, "check_platform", lambda environ: None)
    served = []
    out, err = io.StringIO(), io.StringIO()
    env = {"PREFECT_API_URL": "http://172.17.0.1:4200/api", "PREFECT_API_AUTH_STRING": "fylgja:sentinel-auth"}

    assert serve.main(["serve"], out, err, env, serve=lambda *d: served.extend(d)) == 0

    assert [(d.flow_name, d.name) for d in served] == [
        ("intent-read", "main"), ("twin-create", "main"), ("twin-step", "main"), ("stage-plan", "main"),
        ("twin-rehearse", "main"), ("schema-check", "main")]
    assert [d.entrypoint for d in served] == [
        "fylgja_orchestrator.flows.intent_read.intent_read", "fylgja_orchestrator.flows.twin_create.twin_create",
        "fylgja_orchestrator.flows.twin_step.twin_step", "fylgja_orchestrator.flows.stage_plan.stage_plan",
        "fylgja_orchestrator.flows.twin_rehearse.twin_rehearse",
        "fylgja_orchestrator.flows.schema_check.schema_check"]
    assert out.getvalue() == ("fylgja-orchestrator: serving intent-read/main, twin-create/main, twin-step/main, "
                              "stage-plan/main, twin-rehearse/main, schema-check/main on the platform at "
                              "http://172.17.0.1:4200/api\n")
    assert "sentinel-auth" not in out.getvalue() + err.getvalue()


def test_serve_refuses_another_command():
    assert serve.main(["nope"], io.StringIO(), io.StringIO(), {}) == 2
