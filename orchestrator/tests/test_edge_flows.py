"""The edge's two flows (D-085): each a thin wrap of the library, adding the run's id, its logger and the document's
artifact, and after a cancel or a time limit nothing at all. A decorated flow is never called here, since a call with
no server starts one (verified-facts.md, "Prefect 3.9.2"): each body runs as `.fn`, with Prefect's run context, the
settings, the source and the core replaced, and the artifact recorded rather than made."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from harness import Served, Wrapped
from prefect.client.schemas.objects import FlowRun
from sources import CHANGE, FIVE, SCOPE, FakeSource

from fylgja_orchestrator.edge import flows, run, settings
from fylgja_orchestrator.rehearsal import Limits

RUN = uuid.UUID("6c1e0a52-3f4b-4c8e-9d27-1a5e7b0c9f31")
SETTINGS = settings.Settings(
    api_address="core.example:8443",
    api_token="api-test-token",
    api_ca=None,
    source="infrahub",
    source_address="infrahub.example:8000",
    source_token="infrahub-test-token",
    source_ca=None,
    scope=SCOPE,
    reader=Path("reader.yaml"),
    root=Path("records"),
)
# Each flow, the call of `run` it wraps, and a document of its that is not its format's passing one.
FLOWS = [
    (flows.stage_plan, "plan", {"format": "plan-1", "status": "refused"}),
    (flows.twin_rehearse, "rehearse", {"format": "rehearsal-1", "status": "not_rehearsed"}),
]


@dataclass
class Artifacts:
    """`Artifact` replaced: each artifact made is recorded by its members when it is created, and nothing is sent;
    `create` raises `fail` instead where it is set, as where Prefect's API is away."""

    created: list[dict[str, Any]] = field(default_factory=list)
    fail: Exception | None = None

    def __call__(self, **members: Any) -> SimpleNamespace:
        return SimpleNamespace(create=lambda: self._create(members))

    def _create(self, members: dict[str, Any]) -> None:
        if self.fail is not None:
            raise self.fail
        self.created.append(members)


@dataclass
class Opened:
    """What `run.opened` answered the flow: a fake source of `CHANGE`, and the served core with its `close` the
    test's, each call of which is counted in `core_closed`."""

    source: FakeSource
    core: Wrapped
    core_closed: list[None] = field(default_factory=list)

    def closed(self) -> tuple[bool, int]:
        """Whether the source was closed, and how many times the core was."""
        return self.source.closed, len(self.core_closed)


class Cut(BaseException):
    """The test's own stand-in for what a cancel or a time limit gives the flow's body: a `BaseException`."""


@pytest.fixture
def artifacts(monkeypatch: pytest.MonkeyPatch) -> Artifacts:
    recorded = Artifacts()
    monkeypatch.setattr(flows, "Artifact", recorded)
    return recorded


@pytest.fixture
def opened(served: Served, monkeypatch: pytest.MonkeyPatch) -> Opened:
    """A flow run of the test's: its run context `RUN`, the settings `SETTINGS` read from any environment, and
    `run.opened` answering an `Opened`."""
    made = Opened(FakeSource(CHANGE, FIVE), Wrapped(served.client))
    made.core.close = lambda: made.core_closed.append(None)  # type: ignore[method-assign]
    context = SimpleNamespace(flow_run=FlowRun(id=RUN, flow_id=uuid.uuid4(), name="a-test-run"), flow=None)
    monkeypatch.setattr(flows, "FlowRunContext", SimpleNamespace(get=lambda: context))
    monkeypatch.setattr(settings, "from_env", lambda environ: SETTINGS)
    monkeypatch.setattr(run, "opened", lambda given: (made.source, made.core) if given is SETTINGS else None)
    return made


def test_the_flows_names_parameters_and_time_limits() -> None:
    assert (flows.STAGE_PLAN, flows.TWIN_REHEARSE, flows.DEPLOYMENT) == ("stage-plan", "twin-rehearse", "main")
    assert (flows.stage_plan.name, flows.twin_rehearse.name) == ("stage-plan", "twin-rehearse")
    assert flows.stage_plan.timeout_seconds == flows.PLAN_TIMEOUT_S == 600
    assert flows.twin_rehearse.timeout_seconds == flows.REHEARSE_TIMEOUT_S == 3900
    assert flows.REHEARSE_TIMEOUT_S > Limits().limit_s == 3600.0
    assert [set(each.parameters.properties) for each in (flows.stage_plan, flows.twin_rehearse)] == [{"branch"}] * 2


def test_the_document_is_filed_under_the_runs_key(artifacts: Artifacts) -> None:
    assert flows.key("twin-rehearse", "6c1e") == "fylgja-twin-rehearse-6c1e"
    document = {"format": "rehearsal-1", "status": "passed"}
    flows.filed("twin-rehearse", "6c1e", document)
    assert artifacts.created == [{"type": "fylgja-document", "key": "fylgja-twin-rehearse-6c1e", "data": document}]
    assert flows.ARTIFACT_TYPE == "fylgja-document"


@pytest.mark.parametrize(("flow", "call", "document"), FLOWS, ids=lambda each: getattr(each, "name", None))
def test_a_flow_cut_short_files_nothing_adds_no_request_and_closes_both(
    flow: Any,
    call: str,
    document: dict[str, Any],
    opened: Opened,
    artifacts: Artifacts,
    served: Served,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def cut(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise Cut

    monkeypatch.setattr(run, call, cut)
    with pytest.raises(Cut):
        flow.fn(CHANGE.ref)
    assert artifacts.created == []
    assert (opened.source.reads, opened.source.posted) == ([], [])
    assert served.driver.calls == [] and served.other.list_twins() == []
    assert opened.closed() == (True, 1)


@pytest.mark.parametrize(("flow", "call", "document"), FLOWS, ids=lambda each: getattr(each, "name", None))
def test_a_flow_that_ends_files_its_document_whatever_its_status_and_closes_both(
    flow: Any,
    call: str,
    document: dict[str, Any],
    opened: Opened,
    artifacts: Artifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def ended(*args: Any, **kwargs: Any) -> dict[str, Any]:
        asked.append((args, kwargs))
        return document

    monkeypatch.setattr(run, call, ended)
    assert flow.fn(CHANGE.ref) == document
    ((args, kwargs),) = asked  # asked once: D-086's "ask again" is the checks run again, never a retry
    assert args == (CHANGE.ref, SCOPE)
    assert (kwargs.pop("source"), kwargs.pop("core")) == (opened.source, opened.core)
    if call == "rehearse":
        assert kwargs.pop("run_id") == str(RUN)
    progress: Callable[[str], None] = kwargs.pop("progress")
    assert kwargs == {}
    assert progress.__self__.extra["flow_run_id"] == str(RUN)  # type: ignore[attr-defined]
    assert artifacts.created == [{"type": "fylgja-document", "key": f"fylgja-{flow.name}-{RUN}", "data": document}]
    assert opened.closed() == (True, 1)


@pytest.mark.parametrize(("flow", "call", "document"), FLOWS, ids=lambda each: getattr(each, "name", None))
def test_a_filing_that_fails_still_closes_both(
    flow: Any,
    call: str,
    document: dict[str, Any],
    opened: Opened,
    artifacts: Artifacts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts.fail = ConnectionError("Prefect's API is away")
    monkeypatch.setattr(run, call, lambda *args, **kwargs: document)
    with pytest.raises(ConnectionError):
        flow.fn(CHANGE.ref)
    assert artifacts.created == []
    assert opened.closed() == (True, 1)
