"""The checks' glue (`infrahub/checks/fylgja_api.py`, data-model §9, R-12) and the two checks over
it, against a stub of the orchestrator's platform: Prefect's API as research §1.3, §1.4 and §5.21
read it, served through httpx's MockTransport. The glue is imported by its path, as Infrahub's
task worker imports it from the repository, and needs nothing of the orchestrator's; the checks
import it relatively, as a package of their directory (015's research §1.2)."""

import asyncio
import base64
import importlib
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import httpx
import pytest

from fylgja_orchestrator.documents.findings import Document
from fylgja_orchestrator.flows import common, stage_plan, twin_rehearse

CHECKS = Path(__file__).resolve().parents[3] / "infrahub" / "checks"
GOLDEN = Path(__file__).resolve().parents[1] / "golden"


def _package():
    """infrahub/checks/ as the package fylgja_checks, its modules imported by path."""
    if "fylgja_checks" not in sys.modules:
        package = types.ModuleType("fylgja_checks")
        package.__path__ = [str(CHECKS)]
        sys.modules["fylgja_checks"] = package
    return (
        importlib.import_module("fylgja_checks.fylgja_api"),
        importlib.import_module("fylgja_checks.fylgja_step"),
        importlib.import_module("fylgja_checks.fylgja_twin"),
    )


api, step, twin = _package()

ADDRESS = "platform.test:4200"
AUTH = ("fylgja", "sentinel-password")


def by_path():
    """fylgja_api.py loaded alone by its path, as a task worker's import of it needs no package."""
    spec = importlib.util.spec_from_file_location("fylgja_api_alone", CHECKS / "fylgja_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """No wait of the glue's is waited in a test."""
    monkeypatch.setattr(api, "POLL_S", 0.0)
    monkeypatch.setattr(api, "RETRY_503_S", 0.0)
    monkeypatch.setattr(api, "LOG_SETTLE_S", 0.0)
    monkeypatch.setattr(twin, "RETRY_S", 0)


class FakeRun:
    def __init__(self, flow, parameters, states, document, logs):
        self.flow = flow
        self.parameters = parameters
        self.states = list(states)
        self.document = document
        self.logs = logs
        self.reads = 0
        self.cancels = []

    def state(self):
        s = self.states[min(self.reads, len(self.states) - 1)]
        self.reads += 1
        return s


class FakePlatform:
    """The platform's API: the deployments it serves, each run's scripted states (a string, or
    a dict of type, name and message), its document (filed as an artifact whose data is the
    JSON string, as Prefect answers it) and its log records. Every request is kept."""

    def __init__(self, deployments=("stage-plan", "twin-rehearse")):
        self.deployments = set(deployments)
        self.script = []  # (states, document, logs) for each run created, in order
        self.runs: dict[str, FakeRun] = {}
        self.requests: list[httpx.Request] = []
        self.answers: dict[str, list] = {}  # path -> statuses or exceptions to answer first
        self.cancel_status = "ACCEPT"

    def plan(self, states, document=None, logs=()):
        self.script.append((states, document, list(logs)))
        return self

    def transport(self):
        return httpx.MockTransport(self.handle)

    def platform(self, address=ADDRESS, auth=AUTH):
        return api.Platform(address, auth, transport=self.transport())

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        queued = self.answers.get(path)
        if queued:
            answer = queued.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return httpx.Response(answer, json={"detail": "queued"})
        body = json.loads(request.content) if request.content else None
        if path.startswith("/api/deployments/name/"):
            flow = path.split("/")[4]
            if flow not in self.deployments:
                return httpx.Response(404, json={"detail": "Deployment not found"})
            return httpx.Response(200, json={"id": f"dep-{flow}", "name": "main"})
        if path.startswith("/api/deployments/") and path.endswith("/create_flow_run"):
            flow = path.split("/")[3].removeprefix("dep-")
            states, document, logs = self.script.pop(0)
            run_id = f"run-{len(self.runs) + 1}"
            self.runs[run_id] = FakeRun(flow, body["parameters"], states, document, logs)
            return httpx.Response(201, json={"id": run_id, "state": {"type": "SCHEDULED"}})
        if path.startswith("/api/flow_runs/") and path.endswith("/set_state"):
            run = self.runs.get(path.split("/")[3])
            if run is None:
                return httpx.Response(404, json={"detail": "Flow run not found"})
            run.cancels.append(body)
            return httpx.Response(201, json={"status": self.cancel_status, "details": {}})
        if path.startswith("/api/flow_runs/"):
            run = self.runs.get(path.split("/")[3])
            if run is None:
                return httpx.Response(404, json={"detail": "Flow run not found"})
            s = run.state()
            if isinstance(s, str):
                s = {"type": s, "name": s.title()}
            return httpx.Response(200, json={"id": path.split("/")[3], "state": s})
        if path == "/api/artifacts/filter":
            run = self.runs[body["artifacts"]["flow_run_id"]["any_"][0]]
            if run.document is None:
                return httpx.Response(200, json=[])
            data = run.document if isinstance(run.document, str) else json.dumps(run.document)
            return httpx.Response(200, json=[{"key": f"fylgja-{run.flow}-x", "type": "fylgja-findings", "data": data}])
        if path == "/api/logs/filter":
            run = self.runs[body["logs"]["flow_run_id"]["any_"][0]]
            records = run.logs[body["offset"] : body["offset"] + body["limit"]]
            return httpx.Response(200, json=records)
        return httpx.Response(500)

    def of(self, path_part):
        return [r for r in self.requests if path_part in r.url.path]


def out(message):
    return {"name": api.OUT_LOGGER, "level": 20, "message": message}


def engine(message):
    return {"name": "prefect.flow_runs", "level": 20, "message": message}


def doc(status, findings=(), **blocks):
    return {"findings_version": "1", "operation": "x", "status": status, **blocks, "findings": list(findings)}


def finding(severity, rule, obj, message, step=""):
    f = {"severity": severity, "rule": rule, "object": obj, "message": message}
    if step:
        f["step"] = step
    return f


SCOPE_EMPTY = finding("rejection", "scope.empty", "tag:fylgja", "scope tag:fylgja selects no device", "read")
BRANCH_POINT = {"at_source": "branch_point", "findings": [SCOPE_EMPTY]}


def run_async(coro):
    return asyncio.run(coro)


# The glue alone.


def test_the_glue_imports_by_its_path_alone():
    alone = by_path()
    assert alone.ENV_ADDRESS == "FYLGJA_ORCHESTRATOR_ADDRESS"
    assert alone.ENV_AUTH == "FYLGJA_ORCHESTRATOR_AUTH"
    source = (CHECKS / "fylgja_api.py").read_text()
    assert "prefect" not in {line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert "/v1/" not in source and "post_comment" not in source


def test_the_glue_names_what_the_orchestrator_files_and_serves():
    assert api.ARTIFACT_TYPE == common.ARTIFACT_TYPE
    assert api.OUT_LOGGER == "prefect.flow_runs." + common.OUT_SUFFIX
    assert api.FLOW_STAGE_PLAN == stage_plan.FLOW
    assert api.FLOW_TWIN_REHEARSE == twin_rehearse.FLOW


def test_the_twin_check_outlasts_the_flow_it_triggers():
    # Its own deadline is the flow's timeout, and its retry budgets the flow's own (R-10).
    assert twin.FylgjaTwin.timeout == 4260
    assert twin.FylgjaTwin.timeout - twin.DEADLINE_MARGIN_S == twin_rehearse.TIMEOUT_S
    assert twin.ALLOWANCE_S == twin_rehearse.ALLOWANCE_S
    assert twin.DESTROY_S == twin_rehearse.DESTROY_S
    # The wait after a cancellation covers the runner's grace, in which the flow files its document.
    assert twin.DEADLINE_MARGIN_S - api.CLOSE_MARGIN_S > twin_rehearse.GRACE_S
    assert step.FylgjaStep.timeout == 300


@pytest.mark.parametrize(
    ("env", "fault"),
    [
        ({}, "FYLGJA_ORCHESTRATOR_ADDRESS is not set"),
        ({"FYLGJA_ORCHESTRATOR_ADDRESS": ADDRESS}, "FYLGJA_ORCHESTRATOR_AUTH is not set"),
        ({"FYLGJA_ORCHESTRATOR_ADDRESS": ADDRESS, "FYLGJA_ORCHESTRATOR_AUTH": "nocolon"}, "is not user:password"),
        ({"FYLGJA_ORCHESTRATOR_ADDRESS": ADDRESS, "FYLGJA_ORCHESTRATOR_AUTH": "u:secret\r"}, "a character"),
    ],
)
def test_variables_name_the_variable_and_never_its_value(monkeypatch, env, fault):
    for name in ("FYLGJA_ORCHESTRATOR_ADDRESS", "FYLGJA_ORCHESTRATOR_AUTH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(api.Fault) as raised:
        api.variables()
    assert fault in str(raised.value)
    assert "secret" not in str(raised.value) and "nocolon" not in str(raised.value)


def test_variables_split_the_credential(monkeypatch):
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_AUTH", "fylgja:pa:ss")
    assert api.variables() == (ADDRESS, ("fylgja", "pa:ss"))


def test_trigger_reads_the_deployment_then_creates_a_run_with_basic_auth():
    fake = FakePlatform().plan(["COMPLETED"])
    run_id = run_async(fake.platform().trigger("stage-plan", {"branch": "b"}))
    assert run_id == "run-1"
    assert [r.url.path for r in fake.requests] == [
        "/api/deployments/name/stage-plan/main",
        "/api/deployments/dep-stage-plan/create_flow_run",
    ]
    assert json.loads(fake.requests[1].content) == {"parameters": {"branch": "b"}}
    for r in fake.requests:
        assert str(r.url).startswith("http://platform.test:4200/api/")
        assert r.headers["authorization"] == "Basic " + base64.b64encode(b"fylgja:sentinel-password").decode()


@pytest.mark.parametrize(
    "path", ["/api/deployments/name/stage-plan/main", "/api/deployments/dep-stage-plan/create_flow_run"]
)
def test_trigger_asks_once_more_on_a_503(path):
    fake = FakePlatform().plan(["COMPLETED"])
    fake.answers[path] = [503]
    assert run_async(fake.platform().trigger("stage-plan", {"branch": "b"})) == "run-1"
    assert len(fake.of(path.rsplit("/", 1)[-1])) == 2


def test_trigger_asks_no_third_time():
    fake = FakePlatform().plan(["COMPLETED"])
    fake.answers["/api/deployments/dep-stage-plan/create_flow_run"] = [503, 503]
    with pytest.raises(api.Unexpected, match="503 Service Unavailable to a run of deployment stage-plan/main"):
        run_async(fake.platform().trigger("stage-plan", {"branch": "b"}))
    assert not fake.runs


def test_trigger_names_a_deployment_not_served():
    fake = FakePlatform(deployments=())
    with pytest.raises(api.NoDeployment, match="serves no deployment twin-rehearse/main"):
        run_async(fake.platform().trigger("twin-rehearse", {"branch": "b"}))


def test_a_refused_credential_is_named_and_never_carried():
    fake = FakePlatform()
    fake.answers["/api/deployments/name/stage-plan/main"] = [401]
    with pytest.raises(api.CredentialRefused) as raised:
        run_async(fake.platform().trigger("stage-plan", {"branch": "b"}))
    assert "FYLGJA_ORCHESTRATOR_AUTH" in str(raised.value) and "sentinel-password" not in str(raised.value)


def test_nothing_answering_is_unreachable():
    fake = FakePlatform()
    fake.answers["/api/deployments/name/stage-plan/main"] = [httpx.ConnectError("[Errno 111] Connection refused")]
    with pytest.raises(api.Unreachable, match=r"platform at platform.test:4200 cannot be reached: \[Errno 111\]"):
        run_async(fake.platform().trigger("stage-plan", {"branch": "b"}))


def _created(fake, states, document=None, logs=()):
    fake.plan(states, document, logs)
    return run_async(fake.platform().trigger("twin-rehearse", {"branch": "b"}))


def test_wait_polls_to_an_ended_state():
    fake = FakePlatform()
    run_id = _created(fake, ["SCHEDULED", "PENDING", "RUNNING", "RUNNING", "COMPLETED"])
    state = run_async(fake.platform().wait(run_id, time.monotonic() + 60))
    assert state == api.State("COMPLETED", "Completed")
    assert state.ended and fake.runs[run_id].reads == 5


@pytest.mark.parametrize("ended", ["COMPLETED", "FAILED", "CANCELLED", "CRASHED"])
def test_each_terminal_state_ends_the_wait(ended):
    fake = FakePlatform()
    run_id = _created(fake, ["RUNNING", ended])
    assert run_async(fake.platform().wait(run_id, time.monotonic() + 60)).type == ended


def test_wait_returns_the_last_state_once_its_deadline_has_passed():
    fake = FakePlatform()
    run_id = _created(fake, ["RUNNING"])
    state = run_async(fake.platform().wait(run_id, time.monotonic() - 1))
    assert state.type == "RUNNING" and not state.ended
    assert fake.runs[run_id].reads == 1


def test_wait_asks_again_after_a_read_that_cannot_reach_the_platform():
    fake = FakePlatform()
    run_id = _created(fake, ["COMPLETED"])
    fake.answers[f"/api/flow_runs/{run_id}"] = [httpx.ReadTimeout("timed out"), httpx.ConnectError("refused")]
    assert run_async(fake.platform().wait(run_id, time.monotonic() + 60)).type == "COMPLETED"


def test_wait_is_unreachable_when_its_last_read_failed():
    fake = FakePlatform()
    run_id = _created(fake, ["RUNNING"])
    fake.answers[f"/api/flow_runs/{run_id}"] = [httpx.ConnectError("refused")]
    with pytest.raises(api.Unreachable, match="refused"):
        run_async(fake.platform().wait(run_id, time.monotonic() - 1))


def test_wait_names_a_run_the_platform_does_not_hold():
    with pytest.raises(api.Fault, match="holds no flow run run-9"):
        run_async(FakePlatform().platform().wait("run-9", time.monotonic() + 60))


def test_a_state_reads_its_name_and_message():
    state = api.State("FAILED", "TimedOut", "Flow run exceeded timeout of 4020.0 second(s)")
    assert str(state) == "FAILED (TimedOut): Flow run exceeded timeout of 4020.0 second(s)"
    assert str(api.State("COMPLETED", "Completed")) == "COMPLETED"


def test_document_parses_the_artifact_data():
    fake = FakePlatform()
    run_id = _created(fake, ["COMPLETED"], doc("ok", [finding("info", "a.b", "n1", "m")]))
    got = run_async(fake.platform().document(run_id))
    assert got["status"] == "ok" and got["findings"][0]["rule"] == "a.b"
    body = json.loads(fake.of("/artifacts/filter")[0].content)
    assert body["artifacts"] == {"flow_run_id": {"any_": [run_id]}, "type": {"any_": ["fylgja-findings"]}}


def test_document_is_none_when_the_run_filed_none():
    fake = FakePlatform()
    run_id = _created(fake, ["CRASHED"])
    assert run_async(fake.platform().document(run_id)) is None


@pytest.mark.parametrize(("data", "said"), [("{not json", "data is not JSON"), ('"a string"', "not a document")])
def test_document_refuses_data_that_is_no_document(data, said):
    fake = FakePlatform()
    run_id = _created(fake, ["COMPLETED"], data)
    with pytest.raises(api.Unexpected, match=said):
        run_async(fake.platform().document(run_id))


def test_lines_are_the_out_loggers_alone_in_order(monkeypatch):
    monkeypatch.setattr(api, "LOG_PAGE", 2)
    logs = [engine("Beginning flow run"), out("plan of b (2 stages)"), out("  step one"), out("b/head: x"),
            engine("Finished in state Completed()")]
    fake = FakePlatform()
    run_id = _created(fake, ["COMPLETED"], doc("ok"), logs)
    assert run_async(fake.platform().lines(run_id)) == ["plan of b (2 stages)", "  step one", "b/head: x"]


def test_lines_are_read_until_two_reads_agree():
    fake = FakePlatform()
    run_id = _created(fake, ["COMPLETED"], doc("ok"), [out("one")])
    pages = iter([[], [out("one")], [out("one"), out("two")], [out("one"), out("two")]])
    original = fake.handle

    def landing(request):
        if request.url.path == "/api/logs/filter":
            fake.requests.append(request)
            return httpx.Response(200, json=next(pages))
        return original(request)

    platform = api.Platform(ADDRESS, AUTH, transport=httpx.MockTransport(landing))
    assert run_async(platform.lines(run_id)) == ["one", "two"]
    assert len(fake.of("/logs/filter")) == 4


def test_cancel_asks_cancelling_without_force():
    fake = FakePlatform()
    run_id = _created(fake, ["RUNNING"])
    assert fake.platform().cancel(run_id) is None
    assert fake.runs[run_id].cancels == [{"state": {"type": "CANCELLING"}}]


@pytest.mark.parametrize("status", ["ACCEPT", "REJECT", "ABORT"])
def test_cancel_takes_a_run_cancelled_or_already_ended_as_delivered(status):
    fake = FakePlatform()
    fake.cancel_status = status
    assert fake.platform().cancel(_created(fake, ["RUNNING"])) is None


def test_cancel_says_why_it_was_not_delivered_and_never_raises():
    fake = FakePlatform()
    assert "holds no flow run run-7" in fake.platform().cancel("run-7")
    run_id = _created(fake, ["RUNNING"])
    fake.answers[f"/api/flow_runs/{run_id}/set_state"] = [httpx.ConnectError("refused"), 401]
    assert "cannot be reached: refused" in fake.platform().cancel(run_id)
    refused = fake.platform().cancel(run_id)
    assert "refused this check's credential" in refused and "sentinel-password" not in refused


def test_run_reads_an_ended_run_its_document_and_lines():
    fake = FakePlatform().plan(["RUNNING", "COMPLETED"], doc("ok"), [out("a line")])
    ran = run_async(api.run(fake.platform(), "stage-plan", {"branch": "b"}, time.monotonic() + 60))
    got = (ran.flow_run_id, ran.state.type, ran.document["status"], ran.lines)
    assert got == ("run-1", "COMPLETED", "ok", ["a line"])
    assert not ran.cancelled and not fake.runs["run-1"].cancels
    assert ran.heading() == "flow run run-1 of stage-plan/main: COMPLETED"


def test_run_cancels_at_its_deadline_then_waits_until_close_by():
    fake = FakePlatform().plan(["RUNNING", "CANCELLING", "CANCELLED"], doc("error"), [out("cancelled")])
    now = time.monotonic()
    ran = run_async(api.run(fake.platform(), "twin-rehearse", {"branch": "b"}, now - 1, now + 60))
    assert ran.cancelled and ran.cancel_failure is None
    assert fake.runs["run-1"].cancels == [{"state": {"type": "CANCELLING"}}]
    assert ran.state.type == "CANCELLED" and ran.document["status"] == "error" and ran.lines == ["cancelled"]


def test_run_not_ended_by_close_by_has_no_document():
    fake = FakePlatform().plan(["RUNNING"], doc("ok"))
    now = time.monotonic()
    ran = run_async(api.run(fake.platform(), "twin-rehearse", {"branch": "b"}, now - 1, now - 1))
    assert ran.cancelled and not ran.state.ended and ran.document is None
    assert not fake.of("/artifacts/filter")


def test_run_lost_once_triggered_goes_on_uncancelled():
    fake = FakePlatform().plan(["RUNNING"])
    fake.answers["/api/flow_runs/run-1"] = [403]
    with pytest.raises(api.Lost, match="flow run run-1 of twin-rehearse/main was triggered, then .* answered 403"):
        run_async(api.run(fake.platform(), "twin-rehearse", {"branch": "b"}, time.monotonic() + 60))
    assert not fake.runs["run-1"].cancels


def test_run_cancelled_by_infrahub_cancels_its_run_and_goes_on():
    fake = FakePlatform().plan(["RUNNING"])
    platform = fake.platform()

    async def cut():
        task = asyncio.ensure_future(api.run(platform, "twin-rehearse", {"branch": "b"}, time.monotonic() + 60))
        while not fake.runs or fake.runs["run-1"].reads < 2:
            await asyncio.sleep(0)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        run_async(cut())
    assert fake.runs["run-1"].cancels == [{"state": {"type": "CANCELLING"}}]


def test_findings_text_is_the_documents_text():
    for name in ("plan.json", "rehearsal.json", "stages.json"):
        document = json.loads((GOLDEN / name).read_text())
        text = api.findings_text(document)
        assert (text + "\n" if text else "") == Document.from_dict(document).text(), name
    assert api.findings_text(doc("ok")) == ""
    located = {**finding("warning", "r.x", "n1", "m", "compile"), "location": {"file": "a.yaml", "line": 3}}
    assert api.findings_text(doc("ok", [located])).splitlines()[0] == "warning r.x [step compile] a.yaml:3 (n1): m"


# The checks over it.


class Node:
    def __init__(self, value):
        self.value = value


class Change:
    def __init__(self, draft):
        self.id = "pc-1"
        self.name = Node("b")
        self.is_draft = Node(draft)


class FakeInfrahub:
    def __init__(self, draft=False, none=False):
        self.draft = draft
        self.none = none
        self.writes = 0

    async def filters(self, **kwargs):
        assert kwargs == {"kind": "CoreProposedChange", "branch": "main", "source_branch__value": "b",
                          "state__value": "open"}
        return [] if self.none else [Change(self.draft)]

    def create(self, **kwargs):
        self.writes += 1
        raise AssertionError("a check writes nothing to Infrahub")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_ORCHESTRATOR_AUTH", ":".join(AUTH))


def checked(module, cls, fake, infrahub, monkeypatch, timeout=None):
    monkeypatch.setattr(module, "Platform", lambda address, auth: api.Platform(address, auth, fake.transport()))
    check = cls(branch="b", client=infrahub)
    if timeout is not None:
        check.timeout = timeout
    run_async(check.validate({}))
    return check


def levels(check):
    return [(log["level"], log["message"]) for log in check.logs]


def test_the_step_check_logs_the_plan_and_passes_a_plan_the_branch_point_alone_refuses(env, monkeypatch):
    plan = doc("rejected", [SCOPE_EMPTY], plan={"stages": [BRANCH_POINT]})
    fake = FakePlatform().plan(["COMPLETED"], plan, [out("plan of b (4 stages)"), out("step b/a → b/head:")])
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(), monkeypatch)
    assert fake.runs["run-1"].parameters == {"branch": "b"} and fake.runs["run-1"].flow == "stage-plan"
    assert not check.errors
    assert levels(check)[0] == ("INFO", "flow run run-1 of stage-plan/main: COMPLETED\nplan of b (4 stages)\n"
                                        "step b/a → b/head:")
    assert "scope.empty [step read] tag:fylgja" in levels(check)[1][1]


def test_the_step_check_fails_a_stale_mark(env, monkeypatch):
    stale = finding("rejection", "stage.artifact.stale", "n1", "n1's artifact is stale", "read")
    plan = doc("rejected", [SCOPE_EMPTY, stale], plan={"stages": [BRANCH_POINT, {"findings": [stale]}]})
    check = checked(step, step.FylgjaStep, FakePlatform().plan(["COMPLETED"], plan), FakeInfrahub(), monkeypatch)
    assert len(check.errors) == 1 and "rejection stage.artifact.stale [step read] n1: " in check.errors[0]["message"]


@pytest.mark.parametrize("status", ["error", "failed"])
def test_the_step_check_fails_every_status_but_ok_and_rejected(env, monkeypatch, status):
    fake = FakePlatform().plan(["FAILED"], doc(status, [finding("rejection", "operation.failed", "b", "m")]))
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(), monkeypatch)
    assert "operation.failed" in check.errors[0]["message"]


def test_the_step_check_fails_a_run_that_filed_no_document(env, monkeypatch):
    fake = FakePlatform().plan([{"type": "CRASHED", "name": "Crashed", "message": "the process exited"}])
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(), monkeypatch)
    assert check.errors[0]["message"] == (
        "flow run run-1 of stage-plan/main: CRASHED: the process exited, and it filed no document"
    )


def test_the_step_check_cancels_a_plan_past_its_own_deadline(env, monkeypatch):
    fake = FakePlatform().plan(["RUNNING"])
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(), monkeypatch, timeout=api.CLOSE_MARGIN_S)
    assert fake.runs["run-1"].cancels
    message = check.errors[0]["message"]
    assert message.startswith("the stage plan did not answer by this check's own deadline, 0 s after it began")
    assert "it was asked to cancel: nothing was started" in message


def test_the_step_check_names_a_platform_it_cannot_reach(env, monkeypatch):
    fake = FakePlatform(deployments=())
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(), monkeypatch)
    assert "serves no deployment stage-plan/main" in check.errors[0]["message"]


def test_the_step_check_with_no_open_change_asks_nothing(env, monkeypatch):
    fake = FakePlatform()
    check = checked(step, step.FylgjaStep, fake, FakeInfrahub(none=True), monkeypatch)
    assert "no open proposed change has source branch b" in check.errors[0]["message"] and not fake.requests


def test_the_twin_check_skips_a_draft_reading_no_variable(monkeypatch):
    monkeypatch.delenv("FYLGJA_ORCHESTRATOR_ADDRESS", raising=False)
    fake = FakePlatform()
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(draft=True), monkeypatch)
    assert levels(check) == [("INFO", "skipped: proposed change pc-1 is a draft; "
                                      "mark it ready for review and re-run the checks to rehearse it")]
    assert not fake.requests


def test_the_twin_check_concludes_from_the_status_and_writes_nothing(env, monkeypatch):
    infrahub = FakeInfrahub()
    fake = FakePlatform().plan(["RUNNING", "COMPLETED"], doc("ok", rehearsal={"stages": []}), [out("rehearsal")])
    check = checked(twin, twin.FylgjaTwin, fake, infrahub, monkeypatch)
    assert not check.errors and infrahub.writes == 0
    assert fake.runs["run-1"].flow == "twin-rehearse" and fake.runs["run-1"].parameters == {"branch": "b"}
    assert levels(check) == [("INFO", "flow run run-1 of twin-rehearse/main: COMPLETED\nrehearsal")]


def test_the_twin_check_fails_a_status_not_ok(env, monkeypatch):
    bad = finding("rejection", "rehearsal.stage.failed", "b/x", "the stage failed")
    fake = FakePlatform().plan(["COMPLETED"], doc("failed", [bad], rehearsal={"stages": []}))
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch)
    assert check.errors[0]["message"].startswith("rejection rehearsal.stage.failed b/x: the stage failed")


def _held(rule="host.twin.present"):
    held = finding("rejection", rule, "fylgja", "the host holds a twin", "start")
    return doc("rejected", [SCOPE_EMPTY, held], rehearsal={"stages": [BRANCH_POINT], "deadline_s": 600})


def test_the_twin_check_asks_again_while_the_host_is_held(env, monkeypatch):
    fake = (FakePlatform().plan(["COMPLETED"], _held(), [out("held")]).plan(["COMPLETED"], _held(), [out("held")])
            .plan(["COMPLETED"], doc("ok", rehearsal={"stages": []})))
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch)
    assert len(fake.runs) == 3 and not check.errors
    retried = [m for level, m in levels(check) if m.endswith("the host is held; asking again every 0 s")]
    assert len(retried) == 1, "a retried refusal is logged once while it says the same"


def test_the_twin_check_stops_asking_once_its_deadline_no_longer_covers_the_run(env, monkeypatch):
    fake = FakePlatform().plan(["COMPLETED"], _held("run.in_flight"))
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch, timeout=twin.DEADLINE_MARGIN_S + 900)
    assert len(fake.runs) == 1
    message = check.errors[0]["message"]
    assert message.startswith("the host was still held by run.in_flight fylgja after 1 ask")
    assert "does not cover the rehearsal's deadline of 600 s, the destroy's 120 s and the 300 s allowed" in message


def test_the_twin_check_cancels_a_run_past_its_own_deadline_and_reads_its_document(env, monkeypatch):
    cut = finding("rejection", "run.cancelled", "fylgja-rehearse", "cancelled")
    fake = FakePlatform().plan(["RUNNING", "CANCELLED"], doc("error", [cut], rehearsal={"stages": []}))
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch, timeout=twin.DEADLINE_MARGIN_S)
    assert fake.runs["run-1"].cancels
    message = check.errors[0]["message"]
    assert message.startswith("this check's own deadline, 0 s after it began, passed with flow run run-1 of "
                              "twin-rehearse/main still running: it was asked to cancel\n")
    assert "run.cancelled" in message


def test_the_twin_check_says_a_cancelled_run_goes_on_when_it_does_not_end(env, monkeypatch):
    fake = FakePlatform().plan(["RUNNING"])
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch, timeout=api.CLOSE_MARGIN_S)
    message = check.errors[0]["message"]
    assert "it was asked to cancel; it had still not ended 120 s before this check's timeout" in message
    assert message.endswith(twin.GOES_ON)


def test_the_twin_check_says_a_lost_platform_leaves_the_run_going_on(env, monkeypatch):
    fake = FakePlatform().plan(["RUNNING"])
    fake.answers["/api/flow_runs/run-1"] = [403]
    check = checked(twin, twin.FylgjaTwin, fake, FakeInfrahub(), monkeypatch)
    message = check.errors[0]["message"]
    assert message.startswith("flow run run-1 of twin-rehearse/main was triggered, then ")
    assert message.endswith(twin.GOES_ON)


def test_the_holders_pass_the_branch_point_over_and_nothing_else():
    ran = api.Ran("twin-rehearse", "run-1", document=_held())
    assert twin.holders(ran) == ["host.twin.present fylgja"]
    ran.cancelled = True
    assert twin.holders(ran) == []
    other = doc("rejected", [SCOPE_EMPTY, finding("rejection", "stage.artifact.stale", "n1", "m")],
                rehearsal={"stages": [BRANCH_POINT]})
    assert twin.holders(api.Ran("twin-rehearse", "run-1", document=other)) == []
    assert twin.holders(api.Ran("twin-rehearse", "run-1", document=doc("error"))) == []
