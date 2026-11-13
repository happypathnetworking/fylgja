"""The edge's settings and its wiring of the library, with no Prefect (D-085, D-097): the source a setting, Infrahub's
where it is unset, and its nine variables read once, every one missing named at once and no value said; a plan and a
rehearsal of a branch handed to the library as they are, the rehearsal with its fixed limits, a draft refused before
the core is asked, and the request taken by the source after the draft question and before the library. Held to the
core's own server on its fake runtime, over the fake change source."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import httpx
import pytest
from fylgja_core.client import Client, InvalidToken
from fylgja_infrahub import document as infrahub_document
from harness import ROOT, Clock, Served
from sources import CHANGE, FIVE, SCOPE, FakeSource

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.edge import run, settings
from fylgja_orchestrator.infrahub import InfrahubSource, SourceError
from fylgja_orchestrator.netbox import NetBoxSource, NoChange, Unready
from fylgja_orchestrator.netbox import SourceError as NetBoxSourceError
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
    assert (s.api_address, s.source_address, s.scope, s.reader, s.root) == (
        "core.example:8443", "infrahub.example:8000", SCOPE, READER, Path("/var/lib/fylgja-orchestrator"))
    assert (s.api_ca, s.source_ca) == (None, None)
    held = (s.api_token, s.source_token) == (API_TOKEN, INFRAHUB_TOKEN)
    assert held
    leaked = any(token in text for token in (API_TOKEN, INFRAHUB_TOKEN) for text in (str(s), repr(s)))
    assert not leaked

    cas = settings.from_env(ENVIRON | {"FYLGJA_API_CA": "/etc/fylgja/core-ca.pem", "FYLGJA_INFRAHUB_CA": ""})
    assert (cas.api_ca, cas.source_ca) == (Path("/etc/fylgja/core-ca.pem"), None)


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


# The seven a runner of the NetBox source cannot do without, in `settings.names`' order; the two CAs may be left unset.
NETBOX_REQUIRED = (
    "FYLGJA_API_ADDRESS",
    "FYLGJA_API_TOKEN",
    "FYLGJA_NETBOX_ADDRESS",
    "FYLGJA_NETBOX_TOKEN",
    "FYLGJA_ORCHESTRATOR_SCOPE",
    "FYLGJA_ORCHESTRATOR_READER",
    "FYLGJA_ORCHESTRATOR_ROOT",
)
NETBOX_TOKEN = "nbt_AbCdEf012345.0123456789abcdefABCDEF0123456789abcdefAB"
NETBOX_READER = ROOT / "netbox" / "seed" / "reader.yaml"
NETBOX = {
    "FYLGJA_ORCHESTRATOR_SOURCE": "netbox",
    "FYLGJA_API_ADDRESS": "core.example:8443",
    "FYLGJA_API_TOKEN": API_TOKEN,
    "FYLGJA_NETBOX_ADDRESS": "netbox.example:8800",
    "FYLGJA_NETBOX_TOKEN": NETBOX_TOKEN,
    "FYLGJA_ORCHESTRATOR_SCOPE": SCOPE,
    "FYLGJA_ORCHESTRATOR_READER": str(NETBOX_READER),
    "FYLGJA_ORCHESTRATOR_ROOT": "/var/lib/fylgja-orchestrator",
}
UNKNOWN = "FYLGJA_ORCHESTRATOR_SOURCE is neither infrahub nor netbox"


def test_the_source_is_infrahub_where_the_setting_is_unset_and_netbox_where_it_says_so() -> None:
    for given in ({}, {"FYLGJA_ORCHESTRATOR_SOURCE": ""}, {"FYLGJA_ORCHESTRATOR_SOURCE": "infrahub"}):
        assert settings.from_env(ENVIRON | given).source == "infrahub", given
    assert settings.names("infrahub") == settings.NAMES
    assert settings.names("netbox") == (
        "FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN", "FYLGJA_API_CA", "FYLGJA_NETBOX_ADDRESS", "FYLGJA_NETBOX_TOKEN",
        "FYLGJA_NETBOX_CA", "FYLGJA_ORCHESTRATOR_SCOPE", "FYLGJA_ORCHESTRATOR_READER", "FYLGJA_ORCHESTRATOR_ROOT")

    # Under netbox, NetBox's variables are required and Infrahub's are not.
    with pytest.raises(settings.Unset) as unset:
        settings.from_env({"FYLGJA_ORCHESTRATOR_SOURCE": "netbox"})
    assert unset.value.names == NETBOX_REQUIRED
    s = settings.from_env(NETBOX)
    assert (s.source, s.source_address, s.source_ca, s.scope, s.reader) == (
        "netbox", "netbox.example:8800", None, SCOPE, NETBOX_READER)
    held = s.source_token == NETBOX_TOKEN
    assert held
    leaked = any(token in text for token in (API_TOKEN, NETBOX_TOKEN) for text in (str(s), repr(s)))
    assert not leaked
    assert settings.refused(NETBOX) == ()
    ca = settings.from_env(NETBOX | {"FYLGJA_NETBOX_CA": "/etc/fylgja/netbox-ca.pem"})
    assert ca.source_ca == Path("/etc/fylgja/netbox-ca.pem")
    # And under infrahub, NetBox's are not read.
    both = settings.from_env(ENVIRON | {"FYLGJA_NETBOX_ADDRESS": "netbox.example:8800"})
    assert both.source_address == "infrahub.example:8000"

    unknown = ENVIRON | {"FYLGJA_ORCHESTRATOR_SOURCE": "nautobot"}
    with pytest.raises(settings.UnknownSource) as caught:
        settings.from_env(unknown)
    assert str(caught.value) == UNKNOWN
    assert settings.refused(unknown) == (UNKNOWN,)
    assert settings.refused({"FYLGJA_ORCHESTRATOR_SOURCE": "nautobot"}) == (UNKNOWN,)


def test_opened_makes_the_netbox_source_and_the_core_and_asks_neither() -> None:
    source, core = run.opened(settings.from_env(NETBOX))
    try:
        assert isinstance(source, NetBoxSource) and isinstance(core, Client)
        assert repr(core) == "Client('http://core.example:8443')"
    finally:
        source.close()
        core.close()


def test_opened_closes_the_core_where_the_netbox_source_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[None] = []

    class Counted(Client):
        def close(self) -> None:
            closed.append(None)
            super().close()

    monkeypatch.setattr(run, "Client", Counted)
    given = dataclasses.replace(settings.from_env(NETBOX), source_token="two words")
    with pytest.raises(InvalidToken):
        run.opened(given)
    assert closed == [None]


def test_rehearse_claims_after_the_draft_question_and_before_the_library(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered: list[list[str]] = []

    def recorder(seam: FakeSource, *args: Any, **kwargs: Any) -> dict[str, Any]:
        entered.append(list(seam.calls))
        return {"status": "passed"}

    monkeypatch.setattr(rehearsal, "rehearse", recorder)
    source = FakeSource(CHANGE, FIVE)
    assert run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1") == {"status": "passed"}
    assert entered == [["change", "is_draft", "claim"]]
    assert source.claimed == [CHANGE.ref]


def test_a_draft_is_refused_and_never_claimed(served: Served) -> None:
    source = FakeSource(CHANGE, FIVE, draft=True)
    with pytest.raises(run.DraftRefused):
        run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1")
    assert (source.calls, source.claimed) == (["change", "is_draft"], [])


class Gone(FakeSource):
    """A source whose `change` refuses the branch as NetBox's does: `error`."""

    def __init__(self, error: Exception) -> None:
        super().__init__(CHANGE, FIVE)
        self.error = error

    def change(self, ref: str) -> Change:
        self.calls.append("change")
        raise self.error


MERGED = "branch third-link is merged, and only a ready branch is rehearsed"


@pytest.mark.parametrize("error", [NoChange("no branch is named third-link"), Unready(MERGED)])
def test_a_change_the_source_refuses_is_raised_before_any_claim_and_the_core_is_unasked(
    error: Exception, served: Served
) -> None:
    source = Gone(error)
    with pytest.raises(type(error)):
        run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1")
    assert (source.calls, source.claimed, source.reads, source.posted) == (["change"], [], [], [])
    assert served.driver.calls == [] and served.other.list_twins() == []


class Unclaimed(FakeSource):
    """A source that refuses to take the request: its tag write refused, as NetBox's source raises it."""

    def claim(self, change: Change) -> None:
        self.calls.append("claim")
        raise NetBoxSourceError("PATCH /api/plugins/branching/branches/271/: HTTP 500: boom", status=500)


def test_a_claim_the_source_refuses_is_raised_before_the_library_starts(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[None] = []
    monkeypatch.setattr(rehearsal, "rehearse", lambda *args, **kwargs: started.append(None))
    source = Unclaimed(CHANGE, FIVE)
    with pytest.raises(NetBoxSourceError):
        run.rehearse(CHANGE.ref, SCOPE, source=source, core=served.client, run_id="r1")
    assert (source.calls, started, source.reads, source.posted) == (["change", "is_draft", "claim"], [], [], [])
    assert served.driver.calls == [] and served.other.list_twins() == []


def test_plan_claims_nothing(served: Served) -> None:
    source = FakeSource(CHANGE, FIVE)
    assert run.plan(CHANGE.ref, SCOPE, source=source, core=served.client)["status"] == "planned"
    assert source.claimed == [] and "claim" not in source.calls


def test_the_infrahub_source_takes_a_request_by_doing_nothing() -> None:
    asked: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(500)

    reading = infrahub_document.load(READER)
    source = InfrahubSource("infrahub.example:8000", INFRAHUB_TOKEN, reading, transport=httpx.MockTransport(handler))
    try:
        source.claim(CHANGE)
    finally:
        source.close()
    assert asked == []
