"""A fake of the part of Prefect's API the checks' glue asks (`infrahub/checks/fylgja_glue.py`), built here and never
recorded (D-034): an `httpx.MockTransport` handler over state a test sets, with a clock that only the glue's `sleep`
advances, and a fake of the check's own Infrahub client, which answers the open proposed changes of a branch.

The fake answers as Prefect 3.9.2 was read to (design/verified-facts.md, "Prefect 3.9.2"): a deployment by
`<flow>/main`, a run made `SCHEDULED` by `create_flow_run` (201), its state read by `GET /api/flow_runs/<id>`, a
cancel by `set_state` answering `ACCEPT`, a document as an artifact whose `data` is a JSON string, and 401 to every
request whose basic auth is not the one it accepts.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

ADDRESS = "prefect.example:4200"
USER = "fylgja-check-user"
PASSWORD = "fake-prefect-password-7f3a"
AUTH = f"{USER}:{PASSWORD}"
ENVIRON = {"FYLGJA_ORCHESTRATOR_ADDRESS": ADDRESS, "FYLGJA_ORCHESTRATOR_AUTH": AUTH}
"""The task worker's two variables, as the checks are given them."""

RUNNING = {"type": "RUNNING", "name": "Running", "message": ""}
COMPLETED = {"type": "COMPLETED", "name": "Completed", "message": ""}
CANCELLED = {"type": "CANCELLED", "name": "Cancelled", "message": "Flow run was cancelled successfully."}


@dataclass
class Clock:
    """The fake clock: `now` moves only when `sleep` is awaited, and `sleep` raises `raise_at` at that call, counting
    from one, where it is set."""

    now: float = 0.0
    slept: int = 0
    raise_at: tuple[int, BaseException] | None = None

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept += 1
        if self.raise_at is not None and self.raise_at[0] == self.slept:
            raise self.raise_at[1]
        self.now += seconds


@dataclass(frozen=True)
class Asked:
    """One request the fake was sent: its method, its path, its JSON body, and the clock's time when it came."""

    method: str
    path: str
    body: Any
    at: float


@dataclass
class FakePrefect:
    """Prefect's API as a test sets it.

    `deployments` maps each `<flow>/main` served to its id. Each run created follows `script`, a list of states: a
    read pops the next, the last repeating; once a cancel is logged, `after_cancel`, where it is set, replaces what is
    left. `documents` maps a run's id to the document it filed. `busy` maps `deployment`, `create` or `document` (the
    artifacts' filter) to how many 503s that request is answered first; `refuse_cancel`, where it is set, is the status
    a cancel is answered with, the run left as it was; `unreachable` makes every request fail to connect, and `fault`,
    where it is set, is called with each request before it is answered, to raise what a test needs. Every request is
    logged in `log`, in order."""

    clock: Clock = field(default_factory=Clock)
    deployments: dict[str, str] = field(
        default_factory=lambda: {"stage-plan/main": "deployment-plan", "twin-rehearse/main": "deployment-twin"}
    )
    script: list[dict[str, str]] = field(default_factory=lambda: [RUNNING, COMPLETED])
    after_cancel: list[dict[str, str]] | None = None
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    document: dict[str, Any] | None = None
    """Filed by every run, where `documents` names none for it."""
    busy: dict[str, int] = field(default_factory=dict)
    unreachable: bool = False
    refuse_cancel: int | None = None
    fault: Callable[[httpx.Request], None] | None = None
    accepts: str = AUTH
    log: list[Asked] = field(default_factory=list)
    runs: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def paths(self) -> list[str]:
        """Each request's method and path, in order."""
        return [f"{asked.method} {asked.path}" for asked in self.log]

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        self.log.append(Asked(request.method, request.url.path, body, self.clock.now))
        if self.unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        if self.fault is not None:
            self.fault(request)
        expected = "Basic " + base64.b64encode(self.accepts.encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"detail": "Unauthorized"})
        path = request.url.path.removeprefix("/api")
        parts = path.strip("/").split("/")
        match request.method, parts:
            case "GET", ["deployments", "name", flow, name]:
                if self._busy("deployment"):
                    return httpx.Response(503)
                found = self.deployments.get(f"{flow}/{name}")
                if found is None:
                    return httpx.Response(404, json={"detail": "Deployment not found"})
                return httpx.Response(200, json={"id": found, "name": name})
            case "POST", ["deployments", deployment, "create_flow_run"]:
                if self._busy("create"):
                    return httpx.Response(503)
                if deployment not in self.deployments.values():
                    return httpx.Response(404)
                run = f"run-{len(self.runs) + 1}"
                self.runs[run] = list(self.script)
                state = {"type": "SCHEDULED", "name": "Scheduled", "message": ""}
                return httpx.Response(201, json={"id": run, "state": state})
            case "GET", ["flow_runs", run]:
                if run not in self.runs:
                    return httpx.Response(404)
                script = self.runs[run]
                state = script.pop(0) if len(script) > 1 else script[0]
                return httpx.Response(200, json={"id": run, "state": state})
            case "POST", ["flow_runs", run, "set_state"]:
                if run not in self.runs:
                    return httpx.Response(404)
                if self.refuse_cancel is not None:
                    return httpx.Response(self.refuse_cancel, json={"detail": "refused"})
                if self.after_cancel is not None:
                    self.runs[run] = list(self.after_cancel)
                return httpx.Response(201, json={"status": "ACCEPT"})
            case "POST", ["artifacts", "filter"]:
                if self._busy("document"):
                    return httpx.Response(503)
                return httpx.Response(200, json=self._artifacts(body))
        return httpx.Response(404)

    def _busy(self, what: str) -> bool:
        left = self.busy.get(what, 0)
        if left:
            self.busy[what] = left - 1
        return bool(left)

    def _artifacts(self, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        [run] = body["artifacts"]["flow_run_id"]["any_"]
        [kind] = body["artifacts"]["type"]["any_"]
        document = self.documents.get(run, self.document)
        if run not in self.runs or kind != "fylgja-document" or document is None:
            return []
        return [{"key": f"fylgja-flow-{run}", "type": kind, "flow_run_id": run, "data": json.dumps(document)}]


def change(name: str = "Rehearse change-1", *, draft: bool = False, ident: str = "pc-1") -> dict[str, Any]:
    """One open proposed change as Infrahub answers it."""
    return {"id": ident, "name": {"value": name}, "is_draft": {"value": draft}}


@dataclass
class FakeInfrahub:
    """The check's own client, `self.client.execute_graphql` as the glue's `ask`: it answers `changes`, the open
    proposed changes of any branch asked, or `answer` whole where it is set, and logs each query and its variables."""

    changes: list[dict[str, Any]] = field(default_factory=lambda: [change()])
    asked: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: Exception | None = None
    answer: dict[str, Any] | None = None

    async def ask(self, query: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        self.asked.append((query, dict(variables)))
        await asyncio.sleep(0)
        if self.fail is not None:
            raise self.fail
        if self.answer is not None:
            return self.answer
        return {"CoreProposedChange": {"count": len(self.changes), "edges": [{"node": c} for c in self.changes]}}
