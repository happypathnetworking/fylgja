"""API 1's application (formats/api-1.openapi.yaml, D-025, D-039): the routes over the store, the
compiler, the drivers and the reconcile loop.

Each route validates its request body against its format's schema and answers the documents
Fylgja versions, with no model layer of the framework's (D-039). Anything malformed, refused or
conflicting is a problem document (`problems`) with a stable rule; a fault is logged with its
traceback and answered `500 server.error`, naming nothing of it. The reconcile loop starts and
stops with the application's lifespan, so it runs on the event loop that serves the API.

A twin is written by compare-and-set (D-025): a client writes `spec` and asks for deletion, and
the loop alone writes `status`. Every write names its principal in the audit log and in the run
it queues, and kicks the loop. A route reads, checks and writes with no `await` between, on the
event loop's one thread, where the loop makes its own writes too, so no write of the loop's lands
between a route's check and its write. The compare-and-set still guards each one: a write that
fails withdraws the run queued for it, and one lost to another is answered `412`.

A twin or the list of twins is watched, and a run's events followed, as server-sent events
(`sse`), asked by `watch=true` or by an Accept of text/event-stream.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fylgja_core import (
    blueprint,
    bundle,
    clock,
    compiler,
    deployment,
    documents,
    findings,
    logs,
    platform_package,
    probe_package,
    reconcile,
    schemas,
    store,
    twin_record,
)
from fylgja_core import run as runs
from fylgja_core.documents import Rejected
from fylgja_core.driver import Driver, Unplannable
from fylgja_core.findings import Finding, Subject, Verdict
from fylgja_core.packages import Loaded
from fylgja_core.reconcile import Reconciler
from fylgja_core.run import Event, Run
from fylgja_core.server import problems, sse
from fylgja_core.server.auth import AuthMiddleware, Tokens
from fylgja_core.twin_record import Spec, Status, TwinRecord

# Rule ids of the problems the API answers; the catalogue is docs/rules.md.
RULE_INVALID = "request.invalid"
RULE_NOT_FOUND = "request.not_found"
RULE_METHOD = "request.method"
RULE_BLUEPRINT_NOT_FOUND = "blueprint.not_found"
RULE_BUNDLE_NOT_FOUND = "bundle.not_found"
RULE_BUNDLE_REJECTED = reconcile.RULE_BUNDLE_REJECTED
RULE_PLAN_REJECTED = reconcile.RULE_PLAN_REJECTED
RULE_TWIN_NOT_FOUND = "twin.not_found"
RULE_RUN_NOT_FOUND = "run.not_found"
RULE_CONFLICT = "twin.conflict"
RULE_EXISTS = "twin.exists"
RULE_DRIVER_FIXED = "twin.driver.fixed"
RULE_DRIVER_UNKNOWN = reconcile.RULE_DRIVER_UNKNOWN
RULE_DELETING = reconcile.REASON_DELETING
RULE_RUN_ENDED = "run.ended"
RULE_UNBUILT = "api.unbuilt"
RULE_SERVER = "server.error"

API = "1"

_log = logging.getLogger("fylgja.server")

Endpoint = Callable[[Request], Awaitable[Response]]


class _Refused(Exception):
    """A request answered with a problem: raised where the fault is found, answered as it is."""

    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(response.status_code)


def _refuse(request: Request, status: int, rule: str, detail: str, **kw: Any) -> _Refused:
    return _Refused(problems.problem(status, rule, detail, instance=request.url.path, **kw))


def _json(doc: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> Response:
    return JSONResponse(doc, status_code=status, headers=headers)


def _constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


async def _body(request: Request) -> Any:
    """The request's body as a JSON value, or `400 request.invalid`: RFC 8259 JSON alone, so no
    NaN or Infinity."""
    raw = await request.body()
    try:
        return json.loads(raw, parse_constant=_constant)
    except (ValueError, RecursionError):  # a JSONDecodeError, or bytes that are no Unicode text
        raise _refuse(request, 400, RULE_INVALID, "The request body is not a JSON document.") from None


def _held(request: Request, validator: Any, doc: Any, what: str) -> None:
    """`400 request.invalid` with a finding per violation when `doc` is not valid by `validator`."""
    errors = sorted(validator.iter_errors(doc), key=lambda e: (documents.pointer(e.absolute_path), e.message))
    if errors:
        found = [Finding(rule=RULE_INVALID, severity="error", object=documents.pointer(e.absolute_path) or "/",
                         message=e.message) for e in errors]
        raise _refuse(request, 400, RULE_INVALID, f"The body is not {what}.", findings=found)


def _flag(request: Request, key: str) -> bool | None:
    """A boolean query parameter, None when absent, or `400 request.invalid`."""
    raw = request.query_params.get(key)
    if raw is None:
        return None
    if raw not in ("true", "false"):
        raise _refuse(request, 400, RULE_INVALID, f"The query parameter {key} is true or false.")
    return raw == "true"


def _cursor(request: Request, raw: str | None, what: str) -> int | None:
    """A cursor (a revision, a sequence number) from a parameter, None when absent, or `400`."""
    if raw is None:
        return None
    try:
        if raw.isascii() and raw.isdigit():
            return int(raw)
    except ValueError:  # more digits than an int is parsed from
        pass
    raise _refuse(request, 400, RULE_INVALID, f"{what} is an integer of 0 or more.")


def _streams(request: Request) -> bool:
    """Whether the request asks for server-sent events: `watch=true`, or, with no `watch`, an
    Accept of text/event-stream."""
    watch = _flag(request, "watch")
    return _accepts_events(request) if watch is None else watch


def _accepts_events(request: Request) -> bool:
    ranges = request.headers.get("accept", "").split(",")
    return any(r.partition(";")[0].strip().lower() == sse.MEDIA_TYPE for r in ranges)


def _twin_name(request: Request, value: str, status: int) -> str:
    """A twin name, or the answer for one that is none: `400 request.invalid` where the request
    names a twin to make or a filter, `404 twin.not_found` where it names one to read."""
    try:
        return store.check_twin_name(value)
    except ValueError:
        if status == 400:
            raise _refuse(request, 400, RULE_INVALID,
                          "A twin name is a DNS-1123 label of at most 40 characters.") from None
        raise _refuse(request, 404, RULE_TWIN_NOT_FOUND,
                      "No twin has that name: a twin name is a DNS-1123 label of at most 40 characters.") from None


def _etag(record: TwinRecord) -> str:
    return f'"{record.revision}"'


def _matches(if_match: str, record: TwinRecord) -> bool:
    """Whether an If-Match header holds the record's ETag, or `*` (RFC 9110's strong comparison)."""
    tags = [tag.strip() for tag in if_match.split(",")]
    return "*" in tags or _etag(record) in tags


def _record(record: TwinRecord, status: int = 200, headers: Mapping[str, str] | None = None) -> Response:
    return _json(documents.encode(record), status, {"ETag": _etag(record), **(headers or {})})


def _id(request: Request, key: str, rule: str, what: str) -> str:
    """The content-addressed id in the path, or the resource's `404`: a malformed id names nothing."""
    value: str = request.path_params[key]
    try:
        return store.check_id(value)
    except ValueError:
        raise _refuse(request, 404, rule, f"No {what} has that id: an id is 64 lowercase hex digits.") from None


class _Api:
    """The routes' state: the store and what the server loaded, the drivers and the loop."""

    def __init__(
        self,
        store: store.Store,
        loaded: Loaded,
        drivers: Mapping[str, Driver],
        default_driver: str,
        reconciler: Reconciler,
        build: str,
        closing: threading.Event,
    ) -> None:
        self.store = store
        self.loaded = loaded
        self.drivers = drivers
        self.default_driver = default_driver
        self.reconciler = reconciler
        self.closing = closing
        self.version_doc = {
            "api": API,
            "build": build,
            "formats": {
                "blueprint": blueprint.VERSION,
                "bundle": bundle.VERSION,
                "deployment": deployment.VERSION,
                "twin_record": twin_record.VERSION,
                "findings": findings.VERSION,
                "problem": "1",  # RFC 9457's shape is the version: the format states none
                "platform_package": platform_package.VERSION,
                "probe_package": probe_package.VERSION,
            },
        }

    # meta and drivers

    async def version(self, request: Request) -> Response:
        return _json(self.version_doc)

    async def list_drivers(self, request: Request) -> Response:
        listed = [{"name": name, "default": name == self.default_driver,
                   "capabilities": documents.encode(self.drivers[name].capabilities())}
                  for name in sorted(self.drivers)]
        return _json({"drivers": listed})

    # blueprints

    async def put_blueprint(self, request: Request) -> Response:
        doc = await _body(request)
        found = blueprint.validate(doc)
        if found:
            raise _Refused(problems.from_rejected(400, Rejected(found), instance=request.url.path))
        blueprint_id, created = self.store.put_blueprint(doc)
        if created:
            return _json({"id": blueprint_id}, 201, {"Location": f"/v1/blueprints/{blueprint_id}"})
        return _json({"id": blueprint_id})

    def _blueprint(self, request: Request, blueprint_id: str) -> dict[str, Any]:
        try:
            return self.store.get_blueprint(blueprint_id)
        except store.NotFound:
            raise _refuse(request, 404, RULE_BLUEPRINT_NOT_FOUND, f"No blueprint {blueprint_id} is filed.") from None

    async def get_blueprint(self, request: Request) -> Response:
        return _json(self._blueprint(request, _id(request, "blueprint_id", RULE_BLUEPRINT_NOT_FOUND, "blueprint")))

    # bundles

    async def build_bundle(self, request: Request) -> Response:
        doc = await _body(request)
        _held(request, schemas.api_body_validator("/v1/bundles", "post"), doc, "a bundle request")
        blueprint_id: str = doc["blueprint_id"]
        bp = blueprint.decode(self._blueprint(request, blueprint_id))
        try:
            compiled = compiler.compile(bp, self.loaded.platforms, self.loaded.probes)
        except compiler.Uncompilable as e:
            raise _refuse(request, 422, RULE_BUNDLE_REJECTED, f"Blueprint {blueprint_id} does not compile.",
                          findings=e.findings) from None
        created = self.store.put_bundle(compiled.id, compiled.files)
        result = {"id": compiled.id, "manifest": documents.encode(compiled.manifest),
                  "fidelity": documents.encode(compiled.fidelity), "findings": documents.encode(compiled.findings)}
        if created:
            return _json(result, 201, {"Location": f"/v1/bundles/{compiled.id}"})
        return _json(result)

    async def get_bundle(self, request: Request) -> Response:
        bundle_id = _id(request, "bundle_id", RULE_BUNDLE_NOT_FOUND, "bundle")
        try:
            files = self.store.get_bundle(bundle_id)
        except store.NotFound:
            raise _refuse(request, 404, RULE_BUNDLE_NOT_FOUND, f"No bundle {bundle_id} is filed.") from None
        return _json({"id": bundle_id, "manifest": json.loads(files["manifest.json"])})

    async def diff_bundles(self, request: Request) -> Response:
        raise _refuse(request, 501, RULE_UNBUILT, "The bundle diff is built in phase 5, with steps.")

    # packages

    async def validate_package(self, request: Request) -> Response:
        doc = await _body(request)
        if not isinstance(doc, dict) or set(doc) != {"package"} or not isinstance(doc["package"], dict):
            raise _refuse(request, 400, RULE_INVALID, 'The body is {"package": <a platform or probe package>}.')
        package = doc["package"]
        if "platform_package_version" in package:
            found = platform_package.validate(package)
        elif "probe_package_version" in package:
            found = probe_package.validate(package)
        else:
            raise _refuse(request, 400, RULE_INVALID,
                          "The package states neither platform_package_version nor probe_package_version.")
        verdict = Verdict(operation="packages.validate", status="rejected" if found else "ok", subject=Subject(),
                          findings=findings.order(problems.findings_of(found)))
        return _json(documents.encode(verdict))

    # twins: reads

    def _twin(self, request: Request, name: str) -> TwinRecord:
        try:
            return self.store.get_twin(name)
        except store.NotFound:
            raise _refuse(request, 404, RULE_TWIN_NOT_FOUND, f"No twin is named {name}.") from None

    async def list_twins(self, request: Request) -> Response:
        since = _cursor(request, request.query_params.get("since_revision"), "since_revision")
        if _streams(request):
            return sse.EventStream(sse.twin_stream(self.store, None, since, closing=self.closing))
        return _json({"twins": [documents.encode(record) for record in self.store.list_twins()]})

    async def get_twin(self, request: Request) -> Response:
        name = _twin_name(request, request.path_params["name"], 404)
        since = _cursor(request, request.query_params.get("since_revision"), "since_revision")
        if _streams(request):
            try:
                return sse.EventStream(sse.twin_stream(self.store, name, since, closing=self.closing))
            except store.NotFound:
                raise _refuse(request, 404, RULE_TWIN_NOT_FOUND, f"No twin is named {name}.") from None
        return _record(self._twin(request, name))

    # twins: writes

    def _filed(self, request: Request, given: Mapping[str, Any]) -> None:
        """`404` for a spec naming a blueprint or bundle the store does not hold."""
        if "blueprint_id" in given:
            self._blueprint(request, given["blueprint_id"])
            return
        try:
            self.store.get_bundle(given["bundle_id"])
        except store.NotFound:
            raise _refuse(request, 404, RULE_BUNDLE_NOT_FOUND, f"No bundle {given['bundle_id']} is filed.") from None

    def _spec(
        self,
        request: Request,
        name: str,
        given: Mapping[str, Any],
        record: TwinRecord | None,
        if_match: str | None,
        create_only: bool,
    ) -> Spec:
        """The whole spec a partial one asks for, the server filling what is absent (the twin's
        driver, or the configured one for a new twin; no restart), once the request's
        preconditions hold of `record` and nothing about the twin refuses it."""
        if record is None:
            if if_match is not None:
                raise _refuse(request, 412, RULE_CONFLICT, f"Twin {name} does not exist, so If-Match holds of nothing.")
            driver = given.get("driver", self.default_driver)
        else:
            if create_only:
                raise _refuse(request, 412, RULE_EXISTS, f"Twin {name} exists, and If-None-Match asks for a create.")
            if if_match is not None and not _matches(if_match, record):
                raise _refuse(request, 412, RULE_CONFLICT,
                              f"Twin {name} is at revision {record.revision}, which If-Match does not name.")
            if record.deletion_requested_at is not None:
                raise _refuse(request, 409, RULE_DELETING, f"Twin {name} is being deleted.")
            driver = given.get("driver", record.spec.driver)
            if driver != record.spec.driver:
                raise _refuse(request, 409, RULE_DRIVER_FIXED,
                              f"Twin {name} runs on {record.spec.driver}, fixed when it was created.")
        spec = Spec(blueprint_id=given.get("blueprint_id"), bundle_id=given.get("bundle_id"), driver=driver,
                    allow_restart=given.get("allow_restart", False))
        if record is not None and spec != record.spec:
            raise _refuse(request, 501, RULE_UNBUILT, "A change of an existing twin's spec is a step, which phase 5 "
                                                      "builds; phase 4 creates and deletes twins.")
        return spec

    async def put_twin(self, request: Request) -> Response:
        name = _twin_name(request, request.path_params["name"], 400)
        dry_run = _flag(request, "dry_run") is True
        if_match, if_none_match = request.headers.get("if-match"), request.headers.get("if-none-match")
        if if_none_match is not None and if_none_match.strip() != "*":
            raise _refuse(request, 400, RULE_INVALID, 'If-None-Match takes "*" alone.')
        doc = await _body(request)
        _held(request, schemas.api_validator("TwinApply"), doc, "a TwinApply document")
        given: dict[str, Any] = doc["spec"]
        if "driver" in given and given["driver"] not in self.drivers:
            raise _refuse(request, 400, RULE_DRIVER_UNKNOWN,
                          f"This core serves no driver {given['driver']}; it serves {', '.join(sorted(self.drivers))}.")
        self._filed(request, given)
        try:
            record: TwinRecord | None = self.store.get_twin(name)
        except store.NotFound:
            record = None
        spec = self._spec(request, name, given, record, if_match, if_none_match is not None)
        if dry_run:
            return await self._dry_run(request, name, spec)
        principal: str = request.state.principal
        if record is not None:
            logs.audit(principal, "put", name, revision=record.revision, changed=False)
            return _record(record)
        run = runs.queued(name, "create", principal)
        self.store.create_run(run)  # before the record: a pass between the two takes this run and makes none
        created = TwinRecord(name=name, revision=1, generation=1, spec=spec,
                             status=Status(observed_generation=0, conditions=(), nodes=()))
        try:
            self.store.create_twin(created)
        except Exception as e:
            lost = isinstance(e, store.Conflict)
            self._withdraw(run, "another request created the twin first" if lost else "its record could not be written")
            if lost:
                raise _refuse(request, 412, RULE_EXISTS,
                              f"Twin {name} was created by another request meanwhile.") from None
            raise
        self.reconciler.kick(name)
        logs.audit(principal, "put", name, run=run.id, revision=1, generation=1)
        return _record(created, 201, {"Location": f"/v1/twins/{name}"})

    async def _dry_run(self, request: Request, name: str, spec: Spec) -> Response:
        """The plan a create of `spec` would make, written nowhere. What refuses it is a `422`
        problem: a compile (`bundle.rejected`), the driver's plan (`plan.rejected`), or admission,
        under the refusal's own rule, since a refusal reserves nothing to plan with."""
        try:
            planned, verdict = await self.reconciler.dry_run(name, spec)
        except compiler.Uncompilable as e:
            raise _refuse(request, 422, RULE_BUNDLE_REJECTED, "The spec's blueprint does not compile.",
                          findings=e.findings) from None
        except Unplannable as e:
            raise _refuse(request, 422, RULE_PLAN_REJECTED, f"The driver {spec.driver} has no plan for the bundle.",
                          findings=e.findings) from None
        if planned is None:
            refusal = verdict.findings[0]
            raise _refuse(request, 422, refusal.rule, refusal.message, findings=verdict.findings)
        return _json({"deployment": documents.encode(planned), "verdict": documents.encode(verdict)})

    async def delete_twin(self, request: Request) -> Response:
        name = _twin_name(request, request.path_params["name"], 404)
        if_match = request.headers.get("if-match")
        principal: str = request.state.principal
        record = self._twin(request, name)
        if if_match is not None and not _matches(if_match, record):
            raise _refuse(request, 412, RULE_CONFLICT,
                          f"Twin {name} is at revision {record.revision}, which If-Match does not name.")
        if record.deletion_requested_at is not None:  # asked already: its destroy run is the loop's
            self.reconciler.kick(name)
            logs.audit(principal, "delete", name, revision=record.revision, changed=False)
            return _json(documents.encode(record), 202)
        waiting = [r for r in self.store.list_runs(name) if r.operation == "destroy" and r.state == "queued"]
        run = waiting[0] if waiting else runs.queued(name, "destroy", principal)
        if not waiting:
            self.store.create_run(run)  # before the record, as a create's is
        asked = replace(record, deletion_requested_at=clock.now(), generation=record.generation + 1)
        try:
            written = self.store.update_twin(asked, record.revision)
        except Exception as e:
            lost = isinstance(e, store.Conflict)
            if not waiting:
                self._withdraw(run, "the twin moved before its deletion was written" if lost
                               else "the deletion could not be written")
            if lost:
                raise _refuse(request, 412, RULE_CONFLICT, f"Twin {name} moved while its deletion was asked.") from None
            raise
        self._cancel_in_flight(written)
        self.reconciler.kick(name)
        logs.audit(principal, "delete", name, run=run.id, revision=written.revision, generation=written.generation)
        return _json(documents.encode(written), 202)

    def _cancel_in_flight(self, record: TwinRecord) -> None:
        """Mark the create run the record names `cancelling`, if it has not ended, so the loop
        stops it where it is (a call on the runtime in flight included); a `Conflict` is read
        again once. A create run the record does not name never started: the loop ends it."""
        if record.status.run_id is None:
            return
        try:
            run = self.store.get_run(record.status.run_id)
        except store.NotFound:
            return
        for _ in range(2):
            if run.operation != "create" or run.state not in ("queued", "running"):
                return
            try:
                self._mark_cancelling(run)
                return
            except store.Conflict:
                run = self.store.get_run(run.id)

    def _mark_cancelling(self, run: Run) -> Run:
        """The run marked `cancelling` by compare-and-set on the state it was read in."""
        cancelling = replace(run, state="cancelling")
        self.store.update_run(cancelling, run.state)
        return cancelling

    def _withdraw(self, run: Run, why: str) -> None:
        """End a run this request queued and could not hand to the loop, as the loop ends a create
        it cancels before it started: `failed` with `run.cancelled`, then its cancel events. Best
        effort: the write that failed may be the store's own, and this one is logged if it fails
        too, so the request's own failure is the one answered."""
        finding = Finding(rule=reconcile.RULE_CANCELLED, severity="error", object=run.twin,
                          message=f"The run was cancelled before it started: {why}.")
        verdict = Verdict(operation=run.operation, status="failed", subject=Subject(twin=run.twin, run_id=run.id),
                          findings=(finding,))
        try:
            self.store.update_run(runs.ended(run, verdict), "queued")
            self.store.append_event(run.id, Event(seq=0, at=clock.now(), phase="cancel", outcome="started"))
            self.store.append_event(run.id, Event(seq=0, at=clock.now(), phase="cancel", outcome="done",
                                                  duration_s=0.0, rule=reconcile.RULE_CANCELLED))
        except Exception:
            _log.exception("%s: run %s could not be withdrawn", run.twin, run.id,
                           **logs.fields(twin=run.twin, run=run.id))
            return
        _log.info("%s: run %s withdrawn: %s", run.twin, run.id, why, **logs.fields(twin=run.twin, run=run.id))

    async def verify_twin(self, request: Request) -> Response:
        raise _refuse(request, 501, RULE_UNBUILT, "Verify is built in phase 5.")

    # runs

    def _run(self, request: Request) -> Run:
        run_id: str = request.path_params["run_id"]
        try:
            return self.store.get_run(store.check_run_id(run_id))
        except ValueError:
            raise _refuse(request, 404, RULE_RUN_NOT_FOUND, "No run has that id: a run id is a ULID.") from None
        except store.NotFound:
            raise _refuse(request, 404, RULE_RUN_NOT_FOUND, f"No run {run_id} is in the store.") from None

    async def list_runs(self, request: Request) -> Response:
        twin = request.query_params.get("twin")
        if twin is not None:
            _twin_name(request, twin, 400)
        return _json({"runs": [documents.encode(run) for run in self.store.list_runs(twin)]})

    async def get_run(self, request: Request) -> Response:
        return _json(documents.encode(self._run(request)))

    async def run_events(self, request: Request) -> Response:
        """The run's events after the cursor: an EventPage, or a stream that `Last-Event-ID`
        resumes. The run is read before its events, so `ended` means none will follow."""
        run = self._run(request)
        after = _cursor(request, request.query_params.get("after"), "after") or 0
        if _accepts_events(request):
            last = _cursor(request, request.headers.get("last-event-id"), "Last-Event-ID") or 0
            stream = sse.run_events_stream(self.store, run.id, max(after, last), closing=self.closing)
            return sse.EventStream(stream)
        events = self.store.events(run.id, after)
        return _json({"events": [documents.encode(e) for e in events], "next": events[-1].seq if events else after,
                      "ended": run.state == "ended"})

    async def cancel_run(self, request: Request) -> Response:
        """Mark the run `cancelling`; the loop stops it where it is, cleans up and ends it (a
        destroy run completes all the same). A lost write is read again once."""
        run = self._run(request)
        if run.state not in ("ended", "cancelling"):
            try:
                run = self._mark_cancelling(run)
            except store.Conflict:
                run = self.store.get_run(run.id)
                if run.state not in ("ended", "cancelling"):
                    run = self._mark_cancelling(run)
        if run.state == "ended":
            assert run.verdict is not None
            raise _refuse(request, 409, RULE_RUN_ENDED, f"Run {run.id} has ended {run.verdict.status}.")
        principal: str = request.state.principal
        self.reconciler.kick(run.twin)
        logs.audit(principal, "cancel", run.twin, run=run.id)
        return _json(documents.encode(run), 202)


def _by_method(handlers: Mapping[str, Endpoint]) -> Endpoint:
    """One endpoint for a path's methods, so the router's `405` names every method the path takes."""

    async def endpoint(request: Request) -> Response:
        return await handlers["GET" if request.method == "HEAD" else request.method](request)

    return endpoint


def _routes(api: _Api) -> list[Route]:
    table: dict[str, dict[str, Endpoint]] = {
        "/v1/version": {"GET": api.version},
        "/v1/blueprints": {"POST": api.put_blueprint},
        "/v1/blueprints/{blueprint_id}": {"GET": api.get_blueprint},
        "/v1/bundles": {"POST": api.build_bundle},
        "/v1/bundles/{bundle_id}": {"GET": api.get_bundle},
        "/v1/bundles/{bundle_id}/diff/{to_bundle_id}": {"GET": api.diff_bundles},
        "/v1/packages:validate": {"POST": api.validate_package},
        "/v1/drivers": {"GET": api.list_drivers},
        "/v1/twins": {"GET": api.list_twins},
        "/v1/twins/{name}": {"GET": api.get_twin, "PUT": api.put_twin, "DELETE": api.delete_twin},
        "/v1/twins/{name}/verifications": {"POST": api.verify_twin},
        "/v1/runs": {"GET": api.list_runs},
        "/v1/runs/{run_id}": {"GET": api.get_run},
        "/v1/runs/{run_id}/events": {"GET": api.run_events},
        "/v1/runs/{run_id}/cancel": {"POST": api.cancel_run},
    }
    return [Route(path, _by_method(handlers), methods=list(handlers)) for path, handlers in table.items()]


def _answer_refused(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, _Refused)
    return exc.response


def _answer_http(request: Request, exc: Exception) -> Response:
    """The router's own refusals, as problems: a path API 1 lacks, a method a path does not take."""
    assert isinstance(exc, HTTPException)
    if exc.status_code == 404:
        rule, detail = RULE_NOT_FOUND, "API 1 has no such path."
    elif exc.status_code == 405:
        rule, detail = RULE_METHOD, f"The path does not take {request.method}."
    else:
        rule, detail = RULE_INVALID, exc.detail
    response = problems.problem(exc.status_code, rule, detail, instance=request.url.path)
    response.headers.update(exc.headers or {})
    return response


class _Faults:
    """A pure ASGI middleware: any exception a route raises is logged with its traceback and
    answered `500 server.error`, naming nothing of the fault. Once a response has begun (a
    stream), the fault is logged and the response cut short. A client gone before its request
    was read is no fault, and is left unanswered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except ClientDisconnect:
            _log.info("%s %s: the client left before its request was read", scope["method"], scope["path"],
                      **logs.fields(method=scope["method"], path=scope["path"]))
        except Exception:
            _log.exception("%s %s failed", scope["method"], scope["path"],
                           **logs.fields(method=scope["method"], path=scope["path"]))
            if not started:
                response = problems.problem(500, RULE_SERVER, "The server failed to answer; its log holds the fault.",
                                            instance=scope["path"])
                await response(scope, receive, send)


def create_app(
    *,
    store: store.Store,
    loaded: Loaded,
    drivers: Mapping[str, Driver],
    default_driver: str,
    reconciler: Reconciler,
    tokens: Tokens,
    build: str,
    closing: threading.Event | None = None,
) -> Starlette:
    """API 1 over `store`, the packages `loaded`, the `drivers` by name (`default_driver` among
    them) and `reconciler`, which its lifespan starts and stops: one reconciler per lifespan.
    Every open stream ends once `closing` is set, as the server begins to shut down."""
    if default_driver not in drivers:
        raise ValueError(f"the default driver {default_driver!r} is not one of the drivers given")
    api = _Api(store, loaded, drivers, default_driver, reconciler, build, closing or threading.Event())

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await reconciler.start()
        try:
            yield
        finally:
            await reconciler.stop()

    app = Starlette(
        routes=_routes(api),
        middleware=[Middleware(_Faults), Middleware(AuthMiddleware, tokens=tokens)],
        exception_handlers={_Refused: _answer_refused, HTTPException: _answer_http},
        lifespan=lifespan,
    )
    app.router.redirect_slashes = False  # a path with a slash too many is no path of API 1: 404, not a 307
    return app
