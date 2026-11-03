"""API 1's application (formats/api-1.openapi.yaml, D-025, D-039): the routes over the store, the
compiler, the drivers and the reconcile loop.

Each route validates its request body against its format's schema and answers the documents
Fylgja versions, with no model layer of the framework's (D-039). Anything malformed, refused or
conflicting is a problem document (`problems`) with a stable rule; a fault is logged with its
traceback and answered `500 server.error`, naming nothing of it. The reconcile loop starts and
stops with the application's lifespan, so it runs on the event loop that serves the API.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fylgja_core import (
    blueprint,
    bundle,
    compiler,
    deployment,
    documents,
    findings,
    logs,
    platform_package,
    probe_package,
    schemas,
    store,
    twin_record,
)
from fylgja_core.documents import Rejected
from fylgja_core.driver import Driver
from fylgja_core.findings import Subject, Verdict
from fylgja_core.packages import Loaded
from fylgja_core.reconcile import Reconciler
from fylgja_core.server import problems
from fylgja_core.server.auth import AuthMiddleware, Tokens

# Rule ids of the problems the API answers; the catalogue is docs/rules.md.
RULE_INVALID = "request.invalid"
RULE_NOT_FOUND = "request.not_found"
RULE_METHOD = "request.method"
RULE_BLUEPRINT_NOT_FOUND = "blueprint.not_found"
RULE_BUNDLE_NOT_FOUND = "bundle.not_found"
RULE_BUNDLE_REJECTED = "bundle.rejected"
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
        found = [findings.Finding(rule=RULE_INVALID, severity="error", object=documents.pointer(e.absolute_path) or "/",
                                  message=e.message) for e in errors]
        raise _refuse(request, 400, RULE_INVALID, f"The body is not {what}.", findings=found)


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
    ) -> None:
        self.store = store
        self.loaded = loaded
        self.drivers = drivers
        self.default_driver = default_driver
        self.reconciler = reconciler
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
    stream), the fault is logged and the response cut short."""

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
) -> Starlette:
    """API 1 over `store`, the packages `loaded`, the `drivers` by name (`default_driver` among
    them) and `reconciler`, which its lifespan starts and stops: one reconciler per lifespan."""
    if default_driver not in drivers:
        raise ValueError(f"the default driver {default_driver!r} is not one of the drivers given")
    api = _Api(store, loaded, drivers, default_driver, reconciler, build)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await reconciler.start()
        try:
            yield
        finally:
            await reconciler.stop()

    return Starlette(
        routes=_routes(api),
        middleware=[Middleware(_Faults), Middleware(AuthMiddleware, tokens=tokens)],
        exception_handlers={_Refused: _answer_refused, HTTPException: _answer_http},
        lifespan=lifespan,
    )
