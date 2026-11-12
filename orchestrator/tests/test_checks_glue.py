"""The checks' glue (`infrahub/checks/fylgja_glue.py`, D-085) over a fake Prefect API built in `fake_prefect` and a
fake of the check's own Infrahub client: what it starts, how it waits, when it cancels and what it concludes. No check
runs on a task worker here, nor the worker's path to Prefect: plan 6's acceptance run is the first that does.

The glue is loaded by its path, as Infrahub's runtime loads it beside the check modules, and imports nothing of the
example's: the constants it shares with the edge's flows are compared here by value."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fake_prefect import (
    ADDRESS,
    AUTH,
    CANCELLED,
    COMPLETED,
    ENVIRON,
    PASSWORD,
    RUNNING,
    USER,
    FakeInfrahub,
    FakePrefect,
    change,
)

from fylgja_orchestrator.edge import flows
from fylgja_orchestrator.rehearsal import Limits

GLUE_PATH = Path(__file__).resolve().parents[2] / "infrahub" / "checks" / "fylgja_glue.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fylgja_glue_under_test", GLUE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass resolves its module's annotations through sys.modules
    spec.loader.exec_module(module)
    return module


glue = _load()

BRANCH = "change-1"
HEADLINE = "Rehearsal of change-1: passed.\nEvery stage was rehearsed on the twin and passed."
THREAD = "The report is in this proposed change's thread."

def rehearsal(status: str, headline: str = HEADLINE, version: str = "1") -> dict[str, Any]:
    return {"rehearsal_version": version, "status": status, "headline": headline}


def plan(status: str, headline: str = HEADLINE, version: str = "1") -> dict[str, Any]:
    return {"plan_version": version, "status": status, "headline": headline}


def checked(
    check: Callable[..., Coroutine[Any, Any, Any]],
    prefect: FakePrefect,
    infrahub: FakeInfrahub | None = None,
    *,
    environ: dict[str, str] | None = None,
    timeout: int | None = None,
) -> Any:
    """The outcome of `check`, the glue's `step` or `twin`, on `BRANCH` over the two fakes, its message read for any
    part of the auth: compared outside the assert, so that a failure prints no part of it."""
    infrahub = infrahub or FakeInfrahub()
    if timeout is None:
        timeout = glue.TWIN_TIMEOUT_S if check is glue.twin else glue.STEP_TIMEOUT_S
    outcome = asyncio.run(
        check(
            infrahub.ask,
            BRANCH,
            timeout=timeout,
            environ=ENVIRON if environ is None else environ,
            transport=prefect.transport(),
            sleep=prefect.clock.sleep,
            clock=prefect.clock,
        )
    )
    leaked = USER in outcome.message or PASSWORD in outcome.message
    assert not leaked, "the outcome's message holds a part of the auth"
    return outcome


def test_twin_passes_on_a_passed_document_and_says_where_the_report_is() -> None:
    prefect = FakePrefect(script=[RUNNING, RUNNING, COMPLETED], document=rehearsal("passed"))
    outcome = checked(glue.twin, prefect)
    assert outcome == glue.Outcome(True, f"{HEADLINE}\n{THREAD}")
    assert prefect.paths() == [
        "GET /api/deployments/name/twin-rehearse/main",
        "POST /api/deployments/deployment-twin/create_flow_run",
        "GET /api/flow_runs/run-1",
        "GET /api/flow_runs/run-1",
        "GET /api/flow_runs/run-1",
        "POST /api/artifacts/filter",
    ]
    assert prefect.log[1].body == {"parameters": {"branch": BRANCH}}
    asked = {"flow_run_id": {"any_": ["run-1"]}, "type": {"any_": [glue.ARTIFACT_TYPE]}}
    assert prefect.log[-1].body["artifacts"] == asked
    assert [asked.at for asked in prefect.log[2:5]] == [0.0, glue.POLL_S, 2 * glue.POLL_S]


def test_step_passes_on_a_planned_document() -> None:
    prefect = FakePrefect(document=plan("planned"))
    outcome = checked(glue.step, prefect)
    assert outcome == glue.Outcome(True, HEADLINE)
    assert prefect.paths()[0] == "GET /api/deployments/name/stage-plan/main"


@pytest.mark.parametrize(
    ("check", "document"),
    [
        *((glue.twin, rehearsal(status)) for status in ("failed", "not_rehearsed", "stopped", "surprise")),
        *((glue.step, plan(status)) for status in ("refused", "empty", "unfinished", "surprise")),
    ],
)
def test_every_other_status_fails_with_the_headline(
    check: Callable[..., Coroutine[Any, Any, Any]], document: dict[str, Any]
) -> None:
    prefect = FakePrefect(document=document)
    outcome = checked(check, prefect)
    assert outcome.passed is False
    assert outcome.message.startswith(HEADLINE)
    assert len(prefect.runs) == 1
    assert sum(path.endswith("/create_flow_run") for path in prefect.paths()) == 1


@pytest.mark.parametrize(
    ("check", "document"), [(glue.twin, rehearsal("passed", version="2")), (glue.step, plan("planned", version="2"))]
)
def test_a_document_of_another_version_fails_with_the_versions_sentence(
    check: Callable[..., Coroutine[Any, Any, Any]], document: dict[str, Any]
) -> None:
    outcome = checked(check, FakePrefect(document=document))
    assert outcome == glue.Outcome(False, "the run filed a document of version 2, which this check does not read")


def test_a_draft_passes_having_started_nothing_and_read_no_variable() -> None:
    prefect = FakePrefect(document=rehearsal("passed"))
    infrahub = FakeInfrahub(changes=[change("Rehearse change-1", draft=True)])
    outcome = checked(glue.twin, prefect, infrahub, environ={})
    assert outcome == glue.Outcome(
        True,
        'not rehearsed: proposed change "Rehearse change-1" is a draft. To rehearse it, mark it ready for review and '
        "re-run its checks; leaving draft starts nothing by itself.",
    )
    assert prefect.log == []
    assert [variables for _, variables in infrahub.asked] == [{"branch": BRANCH}]


def test_step_plans_a_draft() -> None:
    prefect = FakePrefect(document=plan("planned"))
    outcome = checked(glue.step, prefect, FakeInfrahub(changes=[change(draft=True)]))
    assert outcome == glue.Outcome(True, HEADLINE)
    assert len(prefect.runs) == 1


@pytest.mark.parametrize("check", [glue.step, glue.twin])
def test_no_open_proposed_change_fails_and_starts_nothing(check: Callable[..., Coroutine[Any, Any, Any]]) -> None:
    prefect = FakePrefect()
    outcome = checked(check, prefect, FakeInfrahub(changes=[]))
    assert outcome == glue.Outcome(False, f"no open proposed change has source branch {BRANCH}: nothing was started")
    assert prefect.log == []


@pytest.mark.parametrize("check", [glue.step, glue.twin])
def test_two_open_proposed_changes_fail_naming_both_and_start_nothing(
    check: Callable[..., Coroutine[Any, Any, Any]],
) -> None:
    prefect = FakePrefect()
    infrahub = FakeInfrahub(changes=[change("first", ident="pc-1"), change("second", ident="pc-2")])
    outcome = checked(check, prefect, infrahub)
    assert outcome.passed is False
    assert '"first" (pc-1)' in outcome.message
    assert '"second" (pc-2)' in outcome.message
    assert prefect.log == []


def test_a_proposed_change_infrahub_cannot_answer_fails_and_starts_nothing() -> None:
    prefect = FakePrefect()
    outcome = checked(glue.twin, prefect, FakeInfrahub(fail=RuntimeError("GraphQL error")))
    assert outcome.passed is False
    assert f"the open proposed change of branch {BRANCH} could not be read" in outcome.message
    assert prefect.log == []


@pytest.mark.parametrize(
    "answer",
    [{}, {"CoreProposedChange": None}, {"CoreProposedChange": {"edges": [{"node": {"id": "pc-1"}}]}}],
)
def test_an_answer_of_infrahub_with_no_proposed_change_in_it_fails_and_starts_nothing(answer: dict[str, Any]) -> None:
    prefect = FakePrefect()
    outcome = checked(glue.step, prefect, FakeInfrahub(answer=answer))
    assert outcome.passed is False
    assert outcome.message.startswith(f"Infrahub answered the open proposed changes of branch {BRANCH} with no ")
    assert prefect.log == []


@pytest.mark.parametrize(
    ("environ", "named"),
    [
        ({"FYLGJA_ORCHESTRATOR_AUTH": AUTH}, "FYLGJA_ORCHESTRATOR_ADDRESS"),
        ({**ENVIRON, "FYLGJA_ORCHESTRATOR_ADDRESS": ""}, "FYLGJA_ORCHESTRATOR_ADDRESS"),
        ({**ENVIRON, "FYLGJA_ORCHESTRATOR_ADDRESS": f"https://{ADDRESS}"}, "FYLGJA_ORCHESTRATOR_ADDRESS"),
        ({"FYLGJA_ORCHESTRATOR_ADDRESS": ADDRESS}, "FYLGJA_ORCHESTRATOR_AUTH"),
        ({**ENVIRON, "FYLGJA_ORCHESTRATOR_AUTH": PASSWORD}, "FYLGJA_ORCHESTRATOR_AUTH"),
        ({**ENVIRON, "FYLGJA_ORCHESTRATOR_AUTH": f":{PASSWORD}"}, "FYLGJA_ORCHESTRATOR_AUTH"),
        ({**ENVIRON, "FYLGJA_ORCHESTRATOR_AUTH": f"{USER}:"}, "FYLGJA_ORCHESTRATOR_AUTH"),
    ],
)
def test_an_unset_or_malformed_variable_fails_naming_it_and_sends_nothing(environ: dict[str, str], named: str) -> None:
    prefect = FakePrefect()
    outcome = checked(glue.twin, prefect, environ=environ)
    assert outcome.passed is False
    assert named in outcome.message
    assert prefect.log == []


@pytest.mark.parametrize("busy", ["deployment", "create"])
def test_a_503_is_asked_once_more_and_a_second_is_a_fault(busy: str) -> None:
    once = FakePrefect(script=[COMPLETED], document=rehearsal("passed"), busy={busy: 1})
    outcome = checked(glue.twin, once)
    assert outcome.passed is True
    assert once.clock.now == glue.RETRY_503_S
    assert len(once.runs) == 1

    twice = FakePrefect(script=[COMPLETED], document=rehearsal("passed"), busy={busy: 2})
    outcome = checked(glue.twin, twice)
    assert outcome.passed is False
    assert ADDRESS in outcome.message
    assert "503" in outcome.message
    asked = "GET /api/deployments/name/twin-rehearse/main"
    if busy == "create":
        asked = "POST /api/deployments/deployment-twin/create_flow_run"
    assert twice.paths().count(asked) == 2
    assert twice.runs == {}


@pytest.mark.parametrize(
    ("prefect", "said"),
    [
        (FakePrefect(accepts="someone:else"), "refused this check's credential (FYLGJA_ORCHESTRATOR_AUTH)"),
        (
            FakePrefect(deployments={}),
            "serves no deployment twin-rehearse/main: make orchestrator-serve starts its runner",
        ),
        (FakePrefect(unreachable=True), "could not be reached"),
    ],
)
def test_a_refused_credential_an_unserved_deployment_and_an_unreachable_address_each_name_the_address_and_never_the_auth(  # noqa: E501
    prefect: FakePrefect, said: str
) -> None:
    outcome = checked(glue.twin, prefect)
    assert outcome.passed is False
    assert ADDRESS in outcome.message
    assert said in outcome.message
    assert prefect.runs == {}


def test_the_checks_deadline_cancels_waits_and_concludes_from_the_state() -> None:
    cancelled = FakePrefect(script=[RUNNING], after_cancel=[CANCELLED])
    outcome = checked(glue.twin, cancelled)
    deadline = glue.TWIN_TIMEOUT_S - glue.DEADLINE_MARGIN_S
    [cancel] = [asked for asked in cancelled.log if asked.path.endswith("/set_state")]
    assert cancel.at == deadline == 4020
    assert cancel.body == {"state": {"type": "CANCELLING"}}
    assert outcome.passed is False
    assert outcome.message.startswith(
        f"this check's own deadline, {deadline} s after it began, passed: the run was asked to cancel\n"
    )
    assert "was stopped" in outcome.message
    assert cancelled.paths()[-1] == "POST /api/artifacts/filter"

    endless = FakePrefect(script=[RUNNING])
    outcome = checked(glue.twin, endless)
    close = glue.TWIN_TIMEOUT_S - glue.CLOSE_MARGIN_S
    assert outcome.passed is False
    assert outcome.message.startswith(f"this check's own deadline, {deadline} s after it began, passed")
    assert f"had not ended {close} s after this check began" in outcome.message
    assert "fylgja-core twin list" in outcome.message
    assert endless.log[-1].at < close == 4140
    assert [asked.path for asked in endless.log].count("/api/flow_runs/run-1/set_state") == 1
    assert "/api/artifacts/filter" not in [asked.path for asked in endless.log]


def test_steps_deadline_is_its_own() -> None:
    prefect = FakePrefect(script=[RUNNING], after_cancel=[CANCELLED])
    outcome = checked(glue.step, prefect)
    [cancel] = [asked for asked in prefect.log if asked.path.endswith("/set_state")]
    assert cancel.at == glue.STEP_TIMEOUT_S - glue.DEADLINE_MARGIN_S == 660
    assert outcome.passed is False
    assert "was stopped" in outcome.message


def test_a_state_unread_once_the_run_exists_is_asked_again_and_named_at_the_close() -> None:
    def away(request: httpx.Request) -> None:
        if request.method == "GET" and "/flow_runs/" in request.url.path:
            raise httpx.ConnectError("connection refused", request=request)

    prefect = FakePrefect(script=[RUNNING], fault=away)
    outcome = checked(glue.step, prefect)
    assert outcome.passed is False
    assert "had not ended" in outcome.message
    assert ADDRESS in outcome.message
    polls = [asked for asked in prefect.log if asked.method == "GET" and "/flow_runs/" in asked.path]
    assert len(polls) > 100


TIMED_OUT = {"type": "FAILED", "name": "TimedOut", "message": "Flow run exceeded timeout of 3900.0 second(s)"}
CRASHED = {"type": "CRASHED", "name": "Crashed", "message": "x" * 2000}


@pytest.mark.parametrize(
    ("state", "said"),
    [
        (
            CANCELLED,
            "the rehearsal was stopped (flow run run-1: CANCELLED), and its twin's deletion was asked; re-run the "
            "checks to rehearse again",
        ),
        (
            TIMED_OUT,
            "the rehearsal passed its time limit (flow run run-1: FAILED, TimedOut), and its twin's deletion was "
            "asked; re-run the checks to rehearse again",
        ),
        (CRASHED, f"flow run run-1 of twin-rehearse/main ended CRASHED: {'x' * 500}, and filed no document"),
        (COMPLETED, "flow run run-1 of twin-rehearse/main ended COMPLETED, and filed no document"),
    ],
)
def test_a_run_with_no_document_is_concluded_from_its_state(state: dict[str, str], said: str) -> None:
    prefect = FakePrefect(script=[RUNNING, state])
    outcome = checked(glue.twin, prefect)
    assert outcome == glue.Outcome(False, said)


class Cut(BaseException):
    """The test's stand-in for what cuts a check short once its run has ended: a `BaseException`."""


def test_a_cancelled_check_cancels_its_run_and_raises() -> None:
    prefect = FakePrefect(script=[RUNNING])
    prefect.clock.raise_at = (3, asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        checked(glue.twin, prefect)
    assert prefect.paths()[-1] == "POST /api/flow_runs/run-1/set_state"
    assert prefect.log[-1].body == {"state": {"type": "CANCELLING"}}
    assert prefect.paths().count("GET /api/flow_runs/run-1") == 3


def test_an_ended_run_is_not_cancelled_when_the_check_is() -> None:
    def cut(request: httpx.Request) -> None:
        if request.url.path.endswith("/artifacts/filter"):
            raise Cut

    prefect = FakePrefect(script=[COMPLETED], document=rehearsal("passed"), fault=cut)
    with pytest.raises(Cut):
        checked(glue.twin, prefect)
    assert "/api/flow_runs/run-1/set_state" not in [asked.path for asked in prefect.log]


def test_the_deadlines_stand_above_the_flows_time_limits() -> None:
    assert glue.TWIN_TIMEOUT_S - glue.DEADLINE_MARGIN_S == 4020 > flows.REHEARSE_TIMEOUT_S == 3900 > Limits().limit_s
    assert glue.STEP_TIMEOUT_S - glue.DEADLINE_MARGIN_S == 660 > flows.PLAN_TIMEOUT_S == 600
    assert glue.TWIN_TIMEOUT_S - glue.CLOSE_MARGIN_S == 4140
    assert glue.ARTIFACT_TYPE == flows.ARTIFACT_TYPE
    glued = (glue.STEP_FLOW, glue.TWIN_FLOW, glue.DEPLOYMENT)
    assert glued == (flows.STAGE_PLAN, flows.TWIN_REHEARSE, flows.DEPLOYMENT)
    assert (glue.POLL_S, glue.RETRY_503_S) == (5.0, 5.0)


def test_the_requests_are_bounded_and_ask_no_proxy() -> None:
    prefect = glue.Prefect(ADDRESS, (USER, PASSWORD))
    try:
        client = prefect._client
        assert client.timeout == httpx.Timeout(30.0, connect=5.0)
        assert client.trust_env is False
        assert str(client.base_url) == f"http://{ADDRESS}/api/"
    finally:
        asyncio.run(prefect.aclose())
    cancel = glue.CANCEL_TIMEOUT
    assert cancel == httpx.Timeout(10.0)


def test_a_503_twice_to_the_document_read_fails_saying_the_run_ended_and_not_that_nothing_started() -> None:
    once = FakePrefect(script=[COMPLETED], document=rehearsal("passed"), busy={"document": 1})
    assert checked(glue.twin, once).passed is True

    twice = FakePrefect(script=[COMPLETED], document=rehearsal("passed"), busy={"document": 2})
    outcome = checked(glue.twin, twice)
    assert outcome == glue.Outcome(
        False,
        f"flow run run-1 of twin-rehearse/main ended COMPLETED, then Prefect at {ADDRESS} answered 503 twice to the "
        "read of flow run run-1's document",
    )
    assert "nothing was started" not in outcome.message
    assert twice.paths().count("POST /api/artifacts/filter") == 2


def test_two_503s_to_the_start_say_no_run_was_read_as_started() -> None:
    outcome = checked(glue.twin, FakePrefect(busy={"create": 2}))
    assert outcome == glue.Outcome(
        False,
        f"Prefect at {ADDRESS} answered 503 twice to the start of a run of twin-rehearse/main: no run was read as "
        "started",
    )


DEADLINE = f"this check's own deadline, {glue.TWIN_TIMEOUT_S - glue.DEADLINE_MARGIN_S} s after it began, passed"


def test_a_cancel_prefect_refuses_is_said_refused_with_its_status() -> None:
    prefect = FakePrefect(script=[RUNNING], refuse_cancel=409)
    outcome = checked(glue.twin, prefect)
    assert outcome.message.startswith(
        f"{DEADLINE}: the run was asked to cancel, and Prefect at {ADDRESS} did not accept it (HTTP 409)\n"
    )
    assert outcome.passed is False


def test_a_cancel_prefect_does_not_answer_is_said_unanswered() -> None:
    def away(request: httpx.Request) -> None:
        if request.url.path.endswith("/set_state"):
            raise httpx.ConnectError("connection refused", request=request)

    outcome = checked(glue.twin, FakePrefect(script=[RUNNING], fault=away))
    said = f"{DEADLINE}: the run was asked to cancel, and Prefect at {ADDRESS} did not answer\n"
    assert outcome.message.startswith(said)
    assert outcome.passed is False
