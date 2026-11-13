"""The library wired to the edge's settings, once, with no Prefect (D-085): what a flow and a command both call.

`opened` makes the change source the settings name, Infrahub's or NetBox's, and the core's client, asking neither
anything. `plan` and `rehearse` hand a branch to the library's own, the source taken as `EdgeSource`, the library's
seam with what only the edge asks of a source; `rehearse` refuses a draft before anything is asked of the core, then
has the source take the request (`claim`), and gives the library its fixed limits (D-097). Whatever the source raises
is raised on, its refused token among it, and so is whatever the library raises.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from fylgja_core.client import Client
from fylgja_infrahub import document as infrahub_document
from fylgja_netbox import document as netbox_document

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.edge.settings import Settings, UnknownSource
from fylgja_orchestrator.infrahub import InfrahubSource
from fylgja_orchestrator.netbox import NetBoxSource
from fylgja_orchestrator.rehearsal import Change, ChangeSource, Limits


class EdgeSource(ChangeSource, Protocol):
    """The library's seam, and what only the edge asks of a source: whether a change is a draft, the request that
    started the rehearsal taken, so that it is used once, and its connections closed once the edge is done with it."""

    def is_draft(self, change: Change) -> bool: ...

    def claim(self, change: Change) -> None: ...

    def close(self) -> None: ...


class DraftRefused(Exception):
    """The change is a draft, and a draft is not rehearsed (D-085)."""


def opened(settings: Settings) -> tuple[EdgeSource, Client]:
    """The change source `settings.source` names, with the reader document `settings.reader` names, and the core's
    client; made with no request. The document's refusal, and the client's or the source's of an address, a token or a
    CA, are raised. Infrahub's source is made first, and closed where the client is refused; NetBox's is given the
    client, which keeps its marks' blueprints, so the client is made first, and closed where the source is refused."""
    if settings.source == "infrahub":
        return _infrahub(settings)
    if settings.source == "netbox":
        return _netbox(settings)
    raise UnknownSource()


def _infrahub(settings: Settings) -> tuple[InfrahubSource, Client]:
    reading = infrahub_document.load(settings.reader)
    source = InfrahubSource(settings.source_address, settings.source_token, reading, ca=settings.source_ca)
    try:
        core = Client(settings.api_address, settings.api_token, ca=settings.api_ca)
    except BaseException:
        source.close()
        raise
    return source, core


def _netbox(settings: Settings) -> tuple[NetBoxSource, Client]:
    reading = netbox_document.load(settings.reader)
    core = Client(settings.api_address, settings.api_token, ca=settings.api_ca)
    try:
        source = NetBoxSource(settings.source_address, settings.source_token, reading, core, ca=settings.source_ca)
    except BaseException:
        core.close()
        raise
    return source, core


def plan(
    branch: str,
    scope: str,
    *,
    source: ChangeSource,
    core: Client,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The library's plan of the change `branch` names, its stages read under `scope`: a plan 1 document."""
    return rehearsal.plan(source, core, branch, scope, progress=progress)


def rehearse(
    branch: str,
    scope: str,
    *,
    source: EdgeSource,
    core: Client,
    run_id: str,
    progress: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """The library's rehearsal of the change `branch` names, on the twin `run_id` names with it, within `Limits()`: a
    rehearsal 1 document. `DraftRefused` where the change is a draft, before the core is asked anything. Then the
    source takes the request (`claim`), before the library starts, so that a request is used once whatever the
    rehearsal comes to; a refusal of the claim is raised with nothing asked of the core. `clock` and `sleep` are the
    library's, for tests."""
    change = source.change(branch)
    if source.is_draft(change):
        raise DraftRefused(
            f"{change.where} is a draft, and a draft is not rehearsed: mark it ready for review, then re-run its checks"
        )
    source.claim(change)
    return rehearsal.rehearse(source, core, branch, scope, run_id=run_id, limits=Limits(), progress=progress,
                              clock=clock, sleep=sleep)
