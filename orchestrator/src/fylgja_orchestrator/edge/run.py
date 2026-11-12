"""The library wired to the edge's settings, once, with no Prefect (D-085): what a flow and a command both call.

`opened` makes the Infrahub change source and the core's client from the settings, asking neither anything. `plan`
and `rehearse` hand a branch to the library's own, the source taken as `EdgeSource`, the library's seam with the
draft flag; `rehearse` refuses a draft before anything is asked of the core, and gives the library its fixed limits.
Whatever the source raises is raised on, its refused token among it (P5-41), and so is whatever the library raises.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from fylgja_core.client import Client
from fylgja_infrahub import document

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.edge.settings import Settings
from fylgja_orchestrator.infrahub import InfrahubSource
from fylgja_orchestrator.rehearsal import Change, ChangeSource, Limits


class EdgeSource(ChangeSource, Protocol):
    """The library's seam, and what only the edge asks of a source: whether a change is a draft, and its connections
    closed once the edge is done with it."""

    def is_draft(self, change: Change) -> bool: ...

    def close(self) -> None: ...


class DraftRefused(Exception):
    """The change is a draft, and a draft is not rehearsed (D-085)."""


def opened(settings: Settings) -> tuple[InfrahubSource, Client]:
    """The change source over Infrahub, with the reader document `settings.reader` names, and the core's client; made
    with no request. The document's refusal, and the client's or the source's of an address, a token or a CA, are
    raised, the source closed where the client is refused."""
    reading = document.load(settings.reader)
    source = InfrahubSource(settings.infrahub_address, settings.infrahub_token, reading, ca=settings.infrahub_ca)
    try:
        core = Client(settings.api_address, settings.api_token, ca=settings.api_ca)
    except BaseException:
        source.close()
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
    rehearsal 1 document. `DraftRefused` where the change is a draft, before the core is asked anything. `clock` and
    `sleep` are the library's, for tests."""
    change = source.change(branch)
    if source.is_draft(change):
        raise DraftRefused(
            f"{change.where} is a draft, and a draft is not rehearsed: mark it ready for review, then re-run its checks"
        )
    return rehearsal.rehearse(source, core, branch, scope, run_id=run_id, limits=Limits(), progress=progress,
                              clock=clock, sleep=sleep)
