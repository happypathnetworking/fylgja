"""A run and its events: the API's own response shapes (formats/api-1.openapi.yaml, D-023,
D-025), kept by the local store.

They are built with the server in phase 4 (core.md, "Target shape"), so they are model types
here and not a format module of their own: `documents.encode` writes the API's `Run` and
`Event`, `documents.decode` reads them back, and `schemas.api_validator` holds both to the
OpenAPI document.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from fylgja_core import clock, ulid
from fylgja_core.findings import Verdict

Operation = Literal["create", "step", "destroy"]
State = Literal["queued", "running", "cancelling", "ended"]
Phase = Literal["compile", "admit", "plan", "apply", "ready", "push", "verify", "flows", "destroy", "cancel"]
Outcome = Literal["started", "done", "failed", "timed_out", "cancelled", "skipped"]


@dataclass(frozen=True, kw_only=True)
class Run:
    """One operation on a twin: queued, running, cancelling, then ended with its verdict."""

    id: str
    twin: str
    operation: Operation
    state: State
    principal: str
    created_at: str
    ended_at: str | None = None
    verdict: Verdict | None = None


@dataclass(frozen=True, kw_only=True)
class Event:
    """One transition of a run's phase or of one of its nodes; `seq` runs from 1 with no gaps."""

    seq: int
    at: str
    phase: Phase
    outcome: Outcome
    node: str | None = None
    duration_s: float | None = None
    rule: str | None = None


def queued(twin: str, operation: Operation, principal: str) -> Run:
    """A new run, queued by `principal` for `twin`, with a new ULID and the time it was made."""
    return Run(id=ulid.new(), twin=twin, operation=operation, state="queued", principal=principal,
               created_at=clock.now())


def ended(run: Run, verdict: Verdict) -> Run:
    """`run` as it ends, with its verdict and the time."""
    return replace(run, state="ended", ended_at=clock.now(), verdict=verdict)
