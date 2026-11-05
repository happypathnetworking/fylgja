"""A fake API 1 server for the client's and the CLI's tests: an `httpx.MockTransport` handler
answering canned documents. It holds every request, and every answer it gives, to the OpenAPI
document (formats/api-1.openapi.yaml), the authority for each shape: the operation, its path,
query and header parameters, its request body, and the status, media type and body of the
answer. Problems are shaped by the server's own `problems.problem`, so the client reads what
the server writes."""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from fylgja_core import blueprint, compiler, documents, platform_package, probe_package, schemas, twin_record
from fylgja_core.findings import Finding
from fylgja_core.server import problems

ROOT = Path(__file__).resolve().parents[2]
API_ID = f"{schemas.ID_PREFIX}api-1.openapi.yaml"
EVENT_STREAM = "text/event-stream"

# What the tests set FYLGJA_API_ADDRESS and FYLGJA_API_TOKEN to; the token is distinctive so a
# test can look for it in every output.
ADDRESS = "127.0.0.1:7650"
TOKEN = "tok-7f3c9e1d-never-shown"

Answer = Callable[[httpx.Request], httpx.Response]


# The OpenAPI document as the authority.


@cache
def openapi() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((schemas.formats_dir() / "api-1.openapi.yaml").read_text())
    return doc


@cache
def _registry() -> Registry[Any]:
    formats = [json.loads(p.read_text()) for p in sorted(schemas.formats_dir().glob("*.schema.json"))]
    resources = [(contents["$id"], Resource.from_contents(contents)) for contents in formats]
    resources.append((API_ID, Resource.from_contents(openapi(), default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@cache
def _validator(parts: tuple[str, ...]) -> Any:
    fragment = "/".join(urllib.parse.quote(p.replace("~", "~0").replace("/", "~1"), safe="~") for p in parts)
    cls = jsonschema.Draft202012Validator
    return cls({"$ref": f"{API_ID}#/{fragment}"}, registry=_registry(), format_checker=cls.FORMAT_CHECKER)


def check(parts: tuple[str, ...], instance: Any) -> None:
    """Assert that `instance` is valid against the schema at `parts` in the OpenAPI document."""
    errors = sorted(f"{list(e.absolute_path)}: {e.message}" for e in _validator(parts).iter_errors(instance))
    assert errors == [], f"{'/'.join(parts)}: {errors}"


def check_component(name: str, instance: Any) -> None:
    """Assert that `instance` is valid as the component schema `name`."""
    check(("components", "schemas", name), instance)


@cache
def _templates() -> list[tuple[re.Pattern[str], str]]:
    found = []
    for template in openapi()["paths"]:
        parts = re.split(r"\{([a-z_]+)\}", template)
        pattern = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^/]+)" for i, p in enumerate(parts))
        found.append((re.compile(f"^{pattern}$"), template))
    return found


def operation(request: httpx.Request) -> tuple[str, str]:
    """The path template and the method, lowercase, of the API 1 operation a request names; its
    parameters and body unchecked, so a test of a malformed request can hold the answer to it."""
    template, _ = _operation(request)
    return template, request.method.lower()


def _operation(request: httpx.Request) -> tuple[str, dict[str, str]]:
    raw = request.url.raw_path.decode().partition("?")[0]
    for pattern, template in _templates():
        match = pattern.match(raw)
        if match:
            return template, {k: urllib.parse.unquote(v) for k, v in match.groupdict().items()}
    raise AssertionError(f"{request.method} {raw} is no path of API 1")


def _parameters(template: str, method: str) -> dict[tuple[str, str], tuple[dict[str, Any], tuple[str, ...]]]:
    """Each parameter an operation declares, by (in, name), with the pointer to its schema."""
    item = openapi()["paths"][template]
    found: dict[tuple[str, str], tuple[dict[str, Any], tuple[str, ...]]] = {}
    for where, declared in (
        (("paths", template), item.get("parameters", [])),
        (("paths", template, method), item[method].get("parameters", [])),
    ):
        for i, p in enumerate(declared):
            if "$ref" in p:
                name = p["$ref"].rsplit("/", 1)[1]
                p, pointer = openapi()["components"]["parameters"][name], ("components", "parameters", name, "schema")
            else:
                pointer = (*where, "parameters", str(i), "schema")
            found[(p["in"], p["name"])] = (p, pointer)
    return found


def _value(schema: Mapping[str, Any], raw: str) -> Any:
    """A parameter's raw text as the JSON value its schema types."""
    if schema.get("type") == "boolean":
        assert raw in ("true", "false"), f"{raw!r} is no boolean"
        return raw == "true"
    if schema.get("type") == "integer":
        assert re.fullmatch(r"-?[0-9]+", raw), f"{raw!r} is no integer"
        return int(raw)
    return raw


def check_request(request: httpx.Request) -> tuple[str, str]:
    """Assert that a request is an operation of API 1 as the document declares it; its path
    template and method."""
    template, path_values = _operation(request)
    method = request.method.lower()
    assert method in openapi()["paths"][template], f"{request.method} {template} is no operation"
    declared = _parameters(template, method)
    for name, raw in path_values.items():
        p, pointer = declared[("path", name)]
        check(pointer, _value(p["schema"], raw))
    for name, raw in request.url.params.multi_items():
        assert ("query", name) in declared, f"{request.method} {template} has no query parameter {name}"
        p, pointer = declared[("query", name)]
        check(pointer, _value(p["schema"], raw))
    for (where, name), (_, pointer) in declared.items():
        if where == "header" and name in request.headers:
            check(pointer, request.headers[name])
    operation = openapi()["paths"][template][method]
    if "requestBody" in operation:
        assert request.headers.get("content-type") == "application/json"
        check(("paths", template, method, "requestBody", "content", "application/json", "schema"),
              json.loads(request.content))
    else:
        assert request.content == b"", f"{request.method} {template} takes no body"
    return template, method


def check_response(template: str, method: str, response: httpx.Response) -> None:
    """Assert that an answer is one the operation declares: its status, its media type and,
    for JSON, its body. A stream's events are checked where they are made (`sse`)."""
    status = str(response.status_code)
    responses = openapi()["paths"][template][method]["responses"]
    assert status in responses, f"{method.upper()} {template} declares no {status}"
    declared = responses[status]
    base: tuple[str, ...] = ("paths", template, method, "responses", status)
    if "$ref" in declared:
        name = declared["$ref"].rsplit("/", 1)[1]
        declared, base = openapi()["components"]["responses"][name], ("components", "responses", name)
    media = response.headers.get("content-type", "").partition(";")[0].strip()
    assert media in declared.get("content", {}), f"{method.upper()} {template} {status} declares no {media}"
    if media != EVENT_STREAM:
        check((*base, "content", media, "schema"), json.loads(response.content))


# The fake server.


class FakeAPI:
    """Answers each request from the answers given for its method and path, in turn, the last
    one repeated; every request carries the test token. A check that fails is raised and also
    kept in `failures`, since the CLI turns anything a transport raises into an exit code."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.failures: list[str] = []
        self._answers: dict[tuple[str, str], list[Answer]] = {}
        self.on("GET", "/v1/version", ok(VERSION))

    def on(self, method: str, path: str, *answers: Answer) -> FakeAPI:
        self._answers[(method, path)] = list(answers)
        return self

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        try:
            return self._answer(request)
        except AssertionError as e:
            self.failures.append(str(e))
            raise

    def _answer(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == f"Bearer {TOKEN}"
        template, method = check_request(request)
        answers = self._answers.get((request.method, request.url.path))
        assert answers, f"no answer for {request.method} {request.url.path}"
        response = (answers.pop(0) if len(answers) > 1 else answers[0])(request)
        check_response(template, method, response)
        return response

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def calls(self) -> list[str]:
        """Each request's method and path, the version check left out."""
        return [f"{r.method} {r.url.path}" for r in self.requests if r.url.path != "/v1/version"]

    def last(self, method: str, path: str) -> httpx.Request:
        return [r for r in self.requests if (r.method, r.url.path) == (method, path)][-1]


def ok(doc: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> Answer:
    """An answer with a JSON document."""
    return lambda request: httpx.Response(status, json=doc, headers=headers)


def refuse(status: int, rule: str, detail: str, findings: Iterable[Finding] = ()) -> Answer:
    """An answer with the problem document the server writes."""

    def answer(request: httpx.Request) -> httpx.Response:
        r = problems.problem(status, rule, detail, findings=list(findings), instance=request.url.path)
        return httpx.Response(status, headers={"content-type": r.headers["content-type"]}, content=bytes(r.body))

    return answer


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


def sse(component: str, messages: Iterable[tuple[str | None, str | None, Mapping[str, Any]]]) -> Answer:
    """A stream answer of messages (event, id, data); each data is checked as `component`."""
    body = b""
    for event, id_, data in messages:
        check_component(component, data)
        lines = ([f"event: {event}"] if event else []) + ([f"id: {id_}"] if id_ else []) + [f"data: {json.dumps(data)}"]
        body += ("\n".join(lines) + "\n\n").encode()
    return lambda request: httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=body)


def watch(*records: Mapping[str, Any], deleted: bool = False) -> Answer:
    """A twin watch: each record MODIFIED (ADDED at revision 1), then the last DELETED if asked."""
    events: list[dict[str, Any]] = [
        {"type": "ADDED" if r["revision"] == 1 else "MODIFIED", "object": r} for r in records
    ]
    if deleted:
        events.append({"type": "DELETED", "object": records[-1]})
    return sse("WatchEvent", [(e["type"], None, e) for e in events])


def event_stream(*events: Mapping[str, Any]) -> Answer:
    """A run's event stream: each event with its seq as id."""
    return sse("Event", [(None, str(e["seq"]), e) for e in events])


# Canned documents.

AT = "2026-11-03T10:00:00.000000Z"
ENDED_AT = "2026-11-03T10:04:30.000000Z"
TWIN = "three-node"
RUN_ID = "01JB8Z5Y3V4W6X7Y8Z9A0B1C2D"
DESTROY_RUN_ID = "01JB8Z9K3V4W6X7Y8Z9A0B1C2E"

VERSION: dict[str, Any] = {
    "api": "1",
    "build": "0.0.0 (test)",
    "formats": {k: "1" for k in ["blueprint", "bundle", "deployment", "twin_record", "findings", "problem",
                                 "platform_package", "probe_package"]},
}

BLUEPRINT_FILE = ROOT / "testdata" / "blueprint" / "three-node.json"
BLUEPRINT: dict[str, Any] = json.loads(BLUEPRINT_FILE.read_text())
BLUEPRINT_ID = blueprint.blueprint_id(BLUEPRINT)

_PLATFORMS = {p.id: p for p in map(platform_package.load, sorted((ROOT / "psp").glob("*.yaml")))}
_PROBES = {p.format: p for p in map(probe_package.load, sorted((ROOT / "probes").glob("*.yaml")))}
_COMPILED = compiler.compile(blueprint.decode(BLUEPRINT), _PLATFORMS, _PROBES)
BUNDLE_ID = _COMPILED.id
MANIFEST: dict[str, Any] = documents.encode(_COMPILED.manifest)
COMPILE_RESULT: dict[str, Any] = {
    "id": BUNDLE_ID,
    "manifest": MANIFEST,
    "fidelity": documents.encode(_COMPILED.fidelity),
    "findings": [],
}
BUNDLE: dict[str, Any] = {"id": BUNDLE_ID, "manifest": MANIFEST}
DEPLOYMENT: dict[str, Any] = json.loads(
    (ROOT / "testdata" / "deployment" / "containerlab" / "three-node" / "deployment.json").read_text()
)

DRIVERS: dict[str, Any] = {
    "drivers": [
        {"name": "clabernetes", "default": False,
         "capabilities": {"nodes": "provisions", "relink": False, "forwarding": "software", "access": "direct",
                          "isolation": "network"}},
        {"name": "containerlab", "default": True,
         "capabilities": {"nodes": "provisions", "relink": True, "forwarding": "software", "access": "direct",
                          "isolation": "names"}},
    ]
}

NODES = [
    {"name": "n1", "handle": "clab-three-node-n1", "address": "172.20.1.11", "holds": BUNDLE_ID},
    {"name": "n2", "handle": "clab-three-node-n2", "address": "172.20.1.12", "access": "bastion.example",
     "holds": BUNDLE_ID},
    {"name": "n3", "handle": "clab-three-node-n3"},
]


def record(
    revision: int = 1,
    generation: int = 1,
    observed: int = 0,
    *,
    phase: str | None = None,
    run_id: str | None = None,
    ready: tuple[str, str | None] | None = None,
    nodes: bool = False,
    deleting: bool = False,
    spec: Mapping[str, Any] | None = None,
    diverged: str | None = None,
    last_step: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A twin record of the three-node twin; `diverged` adds the Diverged condition True for that
    reason, after Ready and Stepping."""
    status: dict[str, Any] = {"observed_generation": observed, "conditions": [], "nodes": []}
    if ready is not None:
        condition = {"type": "Ready", "status": ready[0], "since": AT}
        if ready[1] is not None:
            condition["reason"] = ready[1]
        status["conditions"] = [condition, {"type": "Stepping", "status": "False"}]
    if diverged is not None:
        status["conditions"].append({"type": "Diverged", "status": "True", "reason": diverged, "since": AT})
    if last_step is not None:
        status["last_step"] = dict(last_step)
    if phase is not None:
        status["phase"] = phase
    if run_id is not None:
        status["run_id"] = run_id
    if nodes:
        status.update(blueprint_id=BLUEPRINT_ID, bundle_id=BUNDLE_ID, deployment_id="d" * 64, nodes=NODES)
    doc: dict[str, Any] = {
        "record_version": "1",
        "name": TWIN,
        "revision": revision,
        "generation": generation,
        "spec": dict(spec or {"blueprint_id": BLUEPRINT_ID, "driver": "containerlab", "allow_restart": False}),
        "status": status,
    }
    if deleting:
        doc["deletion_requested_at"] = ENDED_AT
    assert twin_record.validate(doc) == []
    return doc


def verdict(operation: str, status: str = "ok", findings: Iterable[Mapping[str, Any]] = (),
            run_id: str = RUN_ID) -> dict[str, Any]:
    return {"findings_version": "1", "operation": operation, "status": status,
            "subject": {"twin": TWIN, "run_id": run_id}, "findings": list(findings)}


def verification(status: str = "ok", findings: Iterable[Mapping[str, Any]] = (),
                 counts: tuple[int, int, int] = (7, 0, 0)) -> dict[str, Any]:
    """The verdict of a verify of the three-node twin: its subject the bundle and deployment, with counts."""
    doc: dict[str, Any] = {"findings_version": "1", "operation": "verify", "status": status,
                           "subject": {"twin": TWIN, "bundle_id": BUNDLE_ID, "deployment_id": DEPLOYMENT["id"]},
                           "counts": {"held": counts[0], "failed": counts[1], "skipped": counts[2]},
                           "findings": list(findings)}
    assert list(schemas.validator("findings-1").iter_errors(doc)) == []
    return doc


def run(operation: str = "create", state: str = "ended", status: str = "ok",
        findings: Iterable[Mapping[str, Any]] = (), run_id: str = RUN_ID) -> dict[str, Any]:
    """A run of the three-node twin; ended ones carry a verdict."""
    doc: dict[str, Any] = {"id": run_id, "twin": TWIN, "operation": operation, "state": state, "principal": "alice",
                           "created_at": AT}
    if state == "ended":
        doc.update(ended_at=ENDED_AT, verdict=verdict(operation, status, findings, run_id))
    check_component("Run", doc)
    return doc


PUSH_REFUSED = {"rule": "push.refused", "severity": "error", "object": "n1",
                "message": "The node refused the configuration: commit failed."}
NOT_HELD = {"rule": "verify.host_name", "severity": "error", "object": "n1", "message": "n1 reports no host name."}
EVENTS: list[dict[str, Any]] = [
    {"seq": 1, "at": AT, "phase": "compile", "outcome": "started"},
    {"seq": 2, "at": AT, "phase": "compile", "outcome": "done", "duration_s": 0.25},
    {"seq": 3, "at": ENDED_AT, "phase": "push", "outcome": "failed", "node": "n1", "duration_s": 1.5,
     "rule": "push.refused"},
]
PLAN: dict[str, Any] = {
    "deployment": DEPLOYMENT,
    "verdict": {"findings_version": "1", "operation": "plan", "status": "ok",
                "subject": {"twin": TWIN, "bundle_id": BUNDLE_ID}, "findings": []},
}

# A step of the three-node twin to another bundle.

STEP_TO = "5e" * 32


def last_step(outcome: str = "stepped", phase: str = "flows", run_id: str = RUN_ID) -> dict[str, Any]:
    """The record's last step, from the three-node bundle to `STEP_TO`."""
    return {"outcome": outcome, "from": BUNDLE_ID, "to": STEP_TO, "phase": phase, "run_id": run_id}


STEP_CHANGES: dict[str, Any] = {
    "nodes": [{"node": "n1", "action": "kept", "reasons": []},
              {"node": "n2", "action": "recabled", "reasons": ["links"]},
              {"node": "n3", "action": "recreated", "reasons": ["image", "links"]}],
    "links_added": [["n2:e1-2", "n3:eth1"]],
    "links_removed": [["n2:e1-2", "n3:e1-1"]],
}
RESTART_REQUIRED = {"rule": "step.restart.required", "severity": "error", "object": "n3",
                    "message": "n3 would be recreated (image, links), and the spec does not allow a restart: set "
                               "allow_restart to step it."}


def step_plan(status: str = "ok") -> dict[str, Any]:
    """A dry run's plan of a step to `STEP_TO`: the deployment, the verdict (`rejected` with the
    restart the spec does not allow) and the changes."""
    doc: dict[str, Any] = {
        "deployment": DEPLOYMENT,
        "verdict": {"findings_version": "1", "operation": "plan", "status": status,
                    "subject": {"twin": TWIN, "bundle_id": STEP_TO, "deployment_id": DEPLOYMENT["id"]},
                    "findings": [RESTART_REQUIRED] if status != "ok" else []},
        "changes": STEP_CHANGES,
    }
    check_component("Plan", doc)
    return doc
