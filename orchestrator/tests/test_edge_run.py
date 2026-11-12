"""The edge's settings and its wiring of the library, with no Prefect (D-085): the nine variables read once, every one
missing named at once and no value said; a plan and a rehearsal of a branch handed to the library as they are, the
rehearsal with its fixed limits and a draft refused before the core is asked. Held to the core's own server on its
fake runtime, over the fake change source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fylgja_core.client import Client
from harness import ROOT, Clock, Served
from sources import CHANGE, FIVE, SCOPE, FakeSource

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.edge import run, settings
from fylgja_orchestrator.infrahub import InfrahubSource, SourceError
from fylgja_orchestrator.rehearsal import Change, Limits, documents

# The seven a runner cannot do without, in plan 0's order; the two CAs may be left unset.
REQUIRED = (
    "FYLGJA_API_ADDRESS",
    "FYLGJA_API_TOKEN",
    "FYLGJA_INFRAHUB_ADDRESS",
    "FYLGJA_INFRAHUB_TOKEN",
    "FYLGJA_ORCHESTRATOR_SCOPE",
    "FYLGJA_ORCHESTRATOR_READER",
    "FYLGJA_ORCHESTRATOR_ROOT",
)
API_TOKEN = "api-test-token"
INFRAHUB_TOKEN = "infrahub-test-token"
READER = ROOT / "infrahub" / "seed" / "reader.yaml"
ENVIRON = {
    "FYLGJA_API_ADDRESS": "core.example:8443",
    "FYLGJA_API_TOKEN": API_TOKEN,
    "FYLGJA_INFRAHUB_ADDRESS": "infrahub.example:8000",
    "FYLGJA_INFRAHUB_TOKEN": INFRAHUB_TOKEN,
    "FYLGJA_ORCHESTRATOR_SCOPE": SCOPE,
    "FYLGJA_ORCHESTRATOR_READER": str(READER),
    "FYLGJA_ORCHESTRATOR_ROOT": "/var/lib/fylgja-orchestrator",
}
DRAFT = (f"{CHANGE.where} is a draft, and a draft is not rehearsed: mark it ready for review, then re-run its "
         "checks")


def test_settings_name_every_missing_variable_at_once_and_no_value() -> None:
    with pytest.raises(settings.Unset) as unset:
        settings.from_env({})
    assert unset.value.names == REQUIRED
    assert all(name in str(unset.value) for name in REQUIRED)

    partial = {name: value for name, value in ENVIRON.items() if name != "FYLGJA_ORCHESTRATOR_ROOT"}
    partial["FYLGJA_INFRAHUB_TOKEN"] = ""  # set and empty is unset
    with pytest.raises(settings.Unset) as unset:
        settings.from_env(partial)
    assert unset.value.names == ("FYLGJA_INFRAHUB_TOKEN", "FYLGJA_ORCHESTRATOR_ROOT")
    said = any(value in str(unset.value) for value in partial.values() if value)
    assert not said

    s = settings.from_env(ENVIRON)
    assert (s.api_address, s.infrahub_address, s.scope, s.reader, s.root) == (
        "core.example:8443", "infrahub.example:8000", SCOPE, READER, Path("/var/lib/fylgja-orchestrator"))
    assert (s.api_ca, s.infrahub_ca) == (None, None)
    held = (s.api_token, s.infrahub_token) == (API_TOKEN, INFRAHUB_TOKEN)
    assert held
    leaked = any(token in text for token in (API_TOKEN, INFRAHUB_TOKEN) for text in (str(s), repr(s)))
    assert not leaked

    cas = settings.from_env(ENVIRON | {"FYLGJA_API_CA": "/etc/fylgja/core-ca.pem", "FYLGJA_INFRAHUB_CA": ""})
    assert (cas.api_ca, cas.infrahub_ca) == (Path("/etc/fylgja/core-ca.pem"), None)


def test_opened_makes_the_source_and_the_core_and_asks_neither() -> None:
    source, core = run.opened(settings.from_env(ENVIRON))
    try:
        assert isinstance(source, InfrahubSource) and isinstance(core, Client)
        assert repr(core) == "Client('http://core.example:8443')"
    finally:
        source.close()
        core.close()


def test_plan_is_the_librarys_plan_of_the_branch(served: Served) -> None:
    lines: list[str] = []
    doc = run.plan(CHANGE.ref, SCOPE, source=FakeSource(CHANGE, FIVE), core=served.client, progress=lines.append)
    assert documents.validate("plan-1", doc) == []
    assert doc["status"] == "planned"
    expected = rehearsal.plan(FakeSource(CHANGE, FIVE), served.client, CHANGE.ref, SCOPE, now=lambda: doc["read_at"])
    assert doc == expected
    assert [line.split(":")[1] for line in lines] == [f" stage {k} of 5, {stage.label}" for k, (stage, _) in
                                                      enumerate(FIVE, 1)]


def test_a_draft_is_refused_before_the_core_is_asked(served: Served) -> None:
    source = FakeSource(CHANGE, FIVE, draft=True)
    with pytest.raises(run.DraftRefused) as refused:
        run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1")
    assert str(refused.value) == DRAFT
    assert (source.reads, source.posted) == ([], [])
    assert served.driver.calls == [] and served.other.list_twins() == []


def test_rehearse_passes_the_run_id_and_the_fixed_limits(served: Served, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def recorder(*args: Any, **kwargs: Any) -> dict[str, Any]:
        asked.append((args, kwargs))
        return {"status": "passed"}

    monkeypatch.setattr(rehearsal, "rehearse", recorder)
    source, clock, lines = FakeSource(CHANGE, FIVE), Clock(), list[str]()
    doc = run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1", progress=lines.append,
                       clock=clock.now, sleep=clock.sleep)
    assert doc == {"status": "passed"}
    ((args, kwargs),) = asked
    assert args == (source, served.client, CHANGE.ref, SCOPE)
    assert kwargs == {"run_id": "r1", "limits": Limits(), "progress": lines.append, "clock": clock.now,
                      "sleep": clock.sleep}
    assert Limits() == Limits(settle_s=180.0, limit_s=3600.0)


class Refusing(FakeSource):
    """A source whose token Infrahub refuses at its first call."""

    def change(self, ref: str) -> Change:
        raise SourceError("the change source's token was refused (HTTP 401) by a read of the proposed change at "
                          "http://infrahub.example:8000")


def test_a_refused_token_of_the_source_is_raised_on_before_the_core_is_asked(served: Served) -> None:
    source = Refusing(CHANGE, FIVE)
    with pytest.raises(SourceError, match="token was refused"):
        run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1")
    with pytest.raises(SourceError, match="token was refused"):
        run.plan(CHANGE.ref, SCOPE, source=source, core=served.client)
    assert (source.reads, source.posted) == ([], [])
    assert served.driver.calls == [] and served.other.list_twins() == []
