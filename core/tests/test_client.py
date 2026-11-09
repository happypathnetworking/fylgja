"""The client library of API 1: each call's request as the OpenAPI document declares it (the
fake server checks every one), its answer as a document, a refusal as a `ProblemError`
carrying the server's problem document, what happened to the client a `TransportError`, a
twin's or a run's server-sent events parsed, a watch the server ends early resumed, and an
https:// address verified against the CA given or the system's trust."""

from __future__ import annotations

import json
import re
import socket
import ssl
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import tls
from fake_api import (
    ADDRESS,
    BLUEPRINT,
    BLUEPRINT_ID,
    BUNDLE,
    BUNDLE_ID,
    CAPACITY,
    COMPILE_RESULT,
    DRIVERS,
    EVENTS,
    NOT_HELD,
    PLAN,
    RUN_ID,
    TOKEN,
    TWIN,
    UNTRUSTED,
    VERSION,
    Answer,
    FakeAPI,
    application,
    cut,
    event_stream,
    ok,
    record,
    refuse,
    run,
    sse,
    step_plan,
    unreachable,
    untrusted,
    verification,
    watch,
)

from fylgja_core import documents, drivers, schemas
from fylgja_core.client import (
    EVENT_STREAM,
    JSON_TYPES,
    RECONNECTS,
    TIMEOUT_S,
    VERIFY_TIMEOUT,
    Client,
    InvalidAddress,
    InvalidCA,
    InvalidToken,
    Message,
    ProblemError,
    TransportError,
    UnsupportedVersion,
    Untrusted,
    base_url,
    bearer,
    messages,
    reconnect_delay,
    trust,
)
from fylgja_core.findings import Finding

TWIN_PATH = f"/v1/twins/{TWIN}"
EVENTS_PATH = f"/v1/runs/{RUN_ID}/events"
SPEC = {"blueprint_id": BLUEPRINT_ID, "driver": "containerlab", "allow_restart": False}


def connect(api: FakeAPI, sleeps: list[float] | None = None, notices: list[str] | None = None) -> Client:
    """A client of the fake server: the waits before its watches reconnect kept in `sleeps` and
    never slept, what it says of a reconnect in `notices`."""
    return Client(ADDRESS, TOKEN, transport=api.transport, sleep=(sleeps if sleeps is not None else []).append,
                  notice=None if notices is None else notices.append)


def raw(
    answers: dict[str, httpx.Response | list[httpx.Response]] | None = None,
    *,
    transport: httpx.MockTransport | None = None,
    sleeps: list[float] | None = None,
    notices: list[str] | None = None,
) -> Client:
    """A client of a server the OpenAPI document does not hold: it answers the version, then
    each path from `answers`, a list in turn; its waits and notices kept as `connect` keeps them."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/version":
            return httpx.Response(200, json=VERSION)
        answer = (answers or {})[request.url.path]
        return answer.pop(0) if isinstance(answer, list) else answer

    return Client(ADDRESS, TOKEN, transport=transport or httpx.MockTransport(handle),
                  sleep=(sleeps if sleeps is not None else []).append,
                  notice=None if notices is None else notices.append)


def streams(api: FakeAPI, path: str) -> list[httpx.Request]:
    """The requests for a stream of `path`, in order; a run's event page is not one."""
    return [r for r in api.requests if r.url.path == path and r.headers["accept"] == EVENT_STREAM]


# The address and the connection.


@pytest.mark.parametrize(
    ("address", "url"),
    [
        ("127.0.0.1:7650", "http://127.0.0.1:7650"),
        ("core.example:443", "http://core.example:443"),
        ("https://core.example/", "https://core.example"),
        ("https://core.example/fylgja", "https://core.example/fylgja"),
        ("http://[::1]:7650", "http://[::1]:7650"),
    ],
)
def test_an_address_is_an_http_url_or_host_and_port(address: str, url: str) -> None:
    assert base_url(address) == url


@pytest.mark.parametrize(
    "address",
    ["", "ftp://core.example", "http://", "https://admin:s3cret@core.example", "a b:80", "a%20b:80", "http://[::1",
     "http://core.example:x", "http://core.example:99999", "http://core.example:0", "core..example:80"],
)
def test_an_address_that_is_not_one_is_refused_without_repeating_it(address: str) -> None:
    with pytest.raises(InvalidAddress) as e:
        base_url(address)
    assert isinstance(e.value, ValueError)
    assert "s3cret" not in str(e.value) and "admin" not in str(e.value) and "core" not in str(e.value)


@pytest.mark.parametrize("token", ["q83vEjRWeJA=", "a.b-c_d~e+f/g==", TOKEN])
def test_a_bearer_token_is_rfc_6750s_b64token(token: str) -> None:
    assert bearer(token) == f"Bearer {token}"


@pytest.mark.parametrize(
    "token",
    ["sekrit\r\nX-Evil: 1", "sekrit\r", "sekrit\n", "sekrit\x00", "sekrit-t\u00f6k", "sekrit with space", "sekrit=x",
     ""],
    ids=["crlf", "cr", "lf", "nul", "non-ascii", "space", "inner-equals", "empty"],
)
def test_a_token_that_is_no_bearer_token_is_refused_before_any_request_without_repeating_it(token: str) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=VERSION)

    with pytest.raises(InvalidToken) as e:
        Client(ADDRESS, token, transport=httpx.MockTransport(handle))
    assert isinstance(e.value, ValueError)
    assert "sekrit" not in str(e.value) and str(e.value).startswith("is not an RFC 6750 bearer token")
    assert seen == []


def test_every_request_carries_the_token_and_asks_for_json() -> None:
    api = FakeAPI().on("GET", "/v1/twins", ok({"twins": []}))
    assert connect(api).list_twins() == []
    assert [r.url.path for r in api.requests] == ["/v1/version", "/v1/twins"]
    for r in api.requests:
        assert (r.url.scheme, r.url.host, r.url.port) == ("http", "127.0.0.1", 7650)
        assert r.headers["authorization"] == f"Bearer {TOKEN}"
        assert r.headers["accept"] == JSON_TYPES


def test_the_version_is_read_once_before_the_first_call() -> None:
    api = FakeAPI().on("GET", "/v1/drivers", ok(DRIVERS))
    c = connect(api)
    assert c.list_drivers() == DRIVERS["drivers"]
    assert c.list_drivers() == DRIVERS["drivers"]
    assert [r.url.path for r in api.requests] == ["/v1/version", "/v1/drivers", "/v1/drivers"]
    assert c.version() == VERSION


def test_a_server_of_another_api_is_refused_before_anything_else() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={**VERSION, "api": "2"})

    with pytest.raises(UnsupportedVersion, match="API '2'") as e:
        Client(ADDRESS, TOKEN, transport=httpx.MockTransport(handle)).list_twins()
    assert isinstance(e.value, ValueError)
    assert seen == ["/v1/version"]


def test_the_client_closes_as_a_context_manager_and_its_repr_holds_no_token() -> None:
    with connect(FakeAPI()) as c:
        assert TOKEN not in repr(c) and repr(c) == "Client('http://127.0.0.1:7650')"
    with pytest.raises(RuntimeError):
        c.version()


# An https:// address, and the CA it is verified against.


@pytest.mark.parametrize("fault", ["missing", "prose", "directory"])
def test_a_ca_file_that_cannot_be_read_is_refused_without_its_path_or_content(tmp_path: Path, fault: str) -> None:
    ca = tmp_path / "ca.pem"
    if fault == "prose":
        ca.write_text("sekrit prose, and no certificate\n")
    elif fault == "directory":
        ca.mkdir()
    with pytest.raises(InvalidCA) as e:
        trust(ca)
    assert isinstance(e.value, ValueError)
    assert str(e.value) == "names no file of CA certificates that can be read"
    with pytest.raises(InvalidCA):  # a client made with it, too
        Client(ADDRESS, TOKEN, ca=ca)


def test_an_https_address_is_verified_against_the_ca_file_given(tmp_path: Path) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    with tls.served(application({}), (cert, key)) as port, Client(f"https://127.0.0.1:{port}", TOKEN, ca=cert) as c:
        assert c.version() == VERSION


def test_a_certificate_the_system_does_not_trust_is_untrusted_naming_the_call_and_not_the_token(
    tmp_path: Path,
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    with tls.served(application({}), (cert, key)) as port, Client(f"https://127.0.0.1:{port}", TOKEN) as c, \
            pytest.raises(Untrusted) as e:
        c.version()
    assert isinstance(e.value, TransportError)
    said = str(e.value)
    assert said == (f"GET https://127.0.0.1:{port}/v1/version failed: the server's certificate is not trusted: "
                    f"{UNTRUSTED}")
    assert TOKEN not in said and "Traceback" not in said


@pytest.mark.parametrize(
    "call", [lambda c: c.watch_twin(TWIN), lambda c: c.watch_run(RUN_ID)], ids=["twin", "run"],
)
def test_a_watch_of_a_server_whose_certificate_is_not_trusted_ends_at_once(
    tmp_path: Path, call: Callable[[Client], Iterator[dict[str, Any]]]
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    sleeps: list[float] = []
    notices: list[str] = []
    with tls.served(application({}), (cert, key)) as port, \
            Client(f"https://127.0.0.1:{port}", TOKEN, sleep=sleeps.append, notice=notices.append) as c, \
            pytest.raises(Untrusted):
        list(call(c))
    assert sleeps == [] and notices == []  # no reconnect: a certificate not trusted does not become trusted


# Blueprints, bundles and drivers.


def test_put_blueprint_posts_the_document_and_answers_its_id() -> None:
    api = FakeAPI().on("POST", "/v1/blueprints",
                       ok({"id": BLUEPRINT_ID}, 201, {"Location": f"/v1/blueprints/{BLUEPRINT_ID}"}))
    assert connect(api).put_blueprint(BLUEPRINT) == BLUEPRINT_ID
    sent = api.last("POST", "/v1/blueprints")
    assert sent.headers["content-type"] == "application/json"
    assert json.loads(sent.content) == BLUEPRINT


def test_reads_of_a_blueprint_a_bundle_and_the_drivers() -> None:
    api = (
        FakeAPI()
        .on("GET", f"/v1/blueprints/{BLUEPRINT_ID}", ok(BLUEPRINT))
        .on("POST", "/v1/bundles", ok(COMPILE_RESULT, 201, {"Location": f"/v1/bundles/{BUNDLE_ID}"}))
        .on("GET", f"/v1/bundles/{BUNDLE_ID}", ok(BUNDLE))
        .on("GET", "/v1/drivers", ok(DRIVERS))
    )
    c = connect(api)
    assert c.get_blueprint(BLUEPRINT_ID) == BLUEPRINT
    assert c.build_bundle(BLUEPRINT_ID) == COMPILE_RESULT
    assert json.loads(api.last("POST", "/v1/bundles").content) == {"blueprint_id": BLUEPRINT_ID}
    assert c.get_bundle(BUNDLE_ID) == BUNDLE
    assert c.list_drivers() == DRIVERS["drivers"]


def test_reads_the_capacity() -> None:
    api = FakeAPI().on("GET", "/v1/capacity", ok(CAPACITY))
    doc = connect(api).capacity()
    assert doc == CAPACITY
    assert list(schemas.api_validator("Capacity").iter_errors(doc)) == []


def test_a_capacity_read_the_server_refuses_is_a_problem_error() -> None:
    api = FakeAPI().on("GET", "/v1/capacity", refuse(503, "capacity.unread", "The runtime cannot be read."))
    with pytest.raises(ProblemError) as e:
        connect(api).capacity()
    assert (e.value.status, e.value.problem.rule) == (503, "capacity.unread")


def test_the_canned_drivers_declare_what_each_real_driver_declares() -> None:
    # The fake server's listing stands for a real core's, so each entry carries its driver's own capabilities.
    assert {d["name"]: d["capabilities"] for d in DRIVERS["drivers"]} == {
        name: documents.encode(drivers.capabilities(name)) for name in drivers.NAMES}


def test_diff_bundles_reads_the_diff_of_two_bundles() -> None:
    other = "b" * 64
    diff = {"from": BUNDLE_ID, "to": other, "unchanged": True,
            "nodes": {"added": [], "removed": [], "changed": []},
            "links": {"added": [], "removed": []}, "probes": {"added": [], "removed": []}}
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}/diff/{other}", ok(diff))
    assert connect(api).diff_bundles(BUNDLE_ID, other) == diff


# Twins.


def test_get_twin_answers_the_record_and_its_etag() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(record(4, 1, 1, nodes=True), headers={"ETag": '"4"'}))
    assert connect(api).get_twin(TWIN) == (record(4, 1, 1, nodes=True), '"4"')
    assert api.last("GET", TWIN_PATH).url.params.multi_items() == []


def test_a_record_answered_without_its_etag_is_a_transport_error() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(record()))
    with pytest.raises(TransportError, match="no ETag"):
        connect(api).get_twin(TWIN)


def test_a_path_parameter_stays_one_segment_for_the_server_to_judge() -> None:
    seen: list[bytes] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(200, json=VERSION)

    with pytest.raises(TransportError, match="no ETag"):
        raw(transport=httpx.MockTransport(handle)).get_twin("a/b")
    assert seen == [b"/v1/version", b"/v1/twins/a%2Fb"]


@pytest.mark.parametrize(
    ("if_match", "if_none_match", "headers"),
    [(None, None, {}), (None, "*", {"if-none-match": "*"}), ('"3"', None, {"if-match": '"3"'})],
    ids=["none", "create-only", "revision"],
)
def test_apply_twin_puts_the_spec_with_its_preconditions(
    if_match: str | None, if_none_match: str | None, headers: dict[str, str]
) -> None:
    created = record(run_id=RUN_ID)
    api = FakeAPI().on("PUT", TWIN_PATH, ok(created, 201, {"Location": TWIN_PATH, "ETag": '"1"'}))
    assert connect(api).apply_twin(TWIN, SPEC, if_match=if_match, if_none_match=if_none_match) == (created, '"1"')
    sent = api.last("PUT", TWIN_PATH)
    assert json.loads(sent.content) == {"spec": SPEC}
    assert {k: v for k, v in sent.headers.items() if k.startswith("if-")} == headers
    assert sent.url.params.multi_items() == []


def test_a_dry_run_asks_by_query_and_answers_the_plan() -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, ok(PLAN))
    assert connect(api).apply_twin(TWIN, SPEC, dry_run=True) == (PLAN, None)
    assert api.last("PUT", TWIN_PATH).url.params.multi_items() == [("dry_run", "true")]


def test_a_new_spec_on_a_twin_that_exists_answers_the_record_and_its_dry_run_the_changes() -> None:
    written = record(5, 2, 1, ready=("True", "twin.ready"))
    api = FakeAPI().on("PUT", TWIN_PATH, ok(written, headers={"ETag": '"5"'}))
    assert connect(api).apply_twin(TWIN, SPEC, if_match='"4"') == (written, '"5"')
    api.on("PUT", TWIN_PATH, ok(step_plan("rejected")))
    assert connect(api).apply_twin(TWIN, SPEC, dry_run=True) == (step_plan("rejected"), None)


def test_delete_twin_answers_the_record_deletion_requested() -> None:
    deleting = record(5, 2, 1, deleting=True, run_id=RUN_ID)
    api = FakeAPI().on("DELETE", TWIN_PATH, ok(deleting, 202))
    assert connect(api).delete_twin(TWIN, if_match='"4"') == deleting
    assert api.last("DELETE", TWIN_PATH).headers["if-match"] == '"4"'
    assert connect(api).delete_twin(TWIN) == deleting
    assert "if-match" not in api.last("DELETE", TWIN_PATH).headers


def test_verify_twin_posts_and_answers_the_verdict() -> None:
    verdict = verification("nonconforming", [NOT_HELD], (6, 1, 0))
    api = FakeAPI().on("POST", f"{TWIN_PATH}/verifications", ok(verdict))
    assert connect(api).verify_twin(TWIN) == verdict
    assert api.last("POST", f"{TWIN_PATH}/verifications").content == b""
    api.on("POST", f"{TWIN_PATH}/verifications", refuse(409, "twin.not_running", "No applied deployment."))
    with pytest.raises(ProblemError) as raised:
        connect(api).verify_twin(TWIN)
    assert (raised.value.status, raised.value.problem.rule) == (409, "twin.not_running")


def test_verify_twin_waits_longer_for_its_answer_than_any_other_call() -> None:
    api = (FakeAPI().on("POST", f"{TWIN_PATH}/verifications", ok(verification()))
           .on("GET", "/v1/twins", ok({"twins": [record()]})))
    c = connect(api)
    c.verify_twin(TWIN)
    c.list_twins()
    # The reads and the bursts, one after another, outlast the client's 30 s; the read is still bounded.
    verifying = api.last("POST", f"{TWIN_PATH}/verifications").extensions["timeout"]
    assert verifying == VERIFY_TIMEOUT.as_dict() == {"connect": 30.0, "read": 300.0, "write": 30.0, "pool": 30.0}
    for path in ("/v1/version", "/v1/twins"):
        assert api.last("GET", path).extensions["timeout"] == httpx.Timeout(TIMEOUT_S).as_dict()


def test_list_twins_answers_the_records() -> None:
    api = FakeAPI().on("GET", "/v1/twins", ok({"twins": [record()]}))
    assert connect(api).list_twins() == [record()]
    assert api.last("GET", "/v1/twins").url.params.multi_items() == []


# Runs.


def test_runs_are_listed_read_paged_and_cancelled() -> None:
    page = {"events": EVENTS[2:], "next": 3, "ended": True}
    api = (
        FakeAPI()
        .on("GET", "/v1/runs", ok({"runs": [run()]}))
        .on("GET", f"/v1/runs/{RUN_ID}", ok(run()))
        .on("GET", f"/v1/runs/{RUN_ID}/events", ok(page))
        .on("POST", f"/v1/runs/{RUN_ID}/cancel", ok(run(state="cancelling"), 202))
    )
    c = connect(api)
    assert c.list_runs(twin=TWIN) == [run()]
    assert api.last("GET", "/v1/runs").url.params.multi_items() == [("twin", TWIN)]
    assert c.list_runs() == [run()]
    assert api.last("GET", "/v1/runs").url.params.multi_items() == []
    assert c.get_run(RUN_ID) == run()
    assert c.run_events(RUN_ID, after=2) == page
    assert api.last("GET", f"/v1/runs/{RUN_ID}/events").url.params.multi_items() == [("after", "2")]
    c.run_events(RUN_ID)
    assert api.last("GET", f"/v1/runs/{RUN_ID}/events").url.params.multi_items() == [("after", "0")]
    assert c.cancel_run(RUN_ID) == run(state="cancelling")
    assert api.last("POST", f"/v1/runs/{RUN_ID}/cancel").content == b""


# Refusals and failures.


@pytest.mark.parametrize(
    ("method", "path", "status", "rule", "call"),
    [
        ("GET", "/v1/twins", 401, "auth.token.unknown", lambda c: c.list_twins()),
        ("GET", TWIN_PATH, 404, "twin.not_found", lambda c: c.get_twin(TWIN)),
        ("PUT", TWIN_PATH, 412, "twin.exists", lambda c: c.apply_twin(TWIN, SPEC, if_none_match="*")),
        ("PUT", TWIN_PATH, 409, "twin.driver.fixed", lambda c: c.apply_twin(TWIN, SPEC)),
        ("POST", f"/v1/runs/{RUN_ID}/cancel", 409, "run.ended", lambda c: c.cancel_run(RUN_ID)),
    ],
    ids=["unauthenticated", "not-found", "exists", "conflict", "ended"],
)
def test_a_refusal_is_a_problem_error_holding_the_servers_document(
    method: str, path: str, status: int, rule: str, call: Callable[[Client], object]
) -> None:
    api = FakeAPI().on(method, path, refuse(status, rule, "One plain sentence of the facts."))
    with pytest.raises(ProblemError) as e:
        call(connect(api))
    assert e.value.status == status
    p = e.value.problem
    assert (p.rule, p.status, p.detail, p.instance) == (rule, status, "One plain sentence of the facts.", path)
    assert str(e.value) == f"{status} {rule}: One plain sentence of the facts."


def test_a_problems_findings_are_decoded_and_round_trip() -> None:
    faults = [Finding(rule="platform.unsupported", severity="error", object="n1", message="No such platform."),
              Finding(rule="probe.interface.cabled", severity="error", object="n1-loop/a", message="Cabled.")]
    answer = refuse(422, "bundle.rejected", "The blueprint does not compile.", faults)
    api = FakeAPI().on("POST", "/v1/bundles", answer)
    with pytest.raises(ProblemError) as e:
        connect(api).build_bundle(BLUEPRINT_ID)
    assert e.value.problem.findings == tuple(faults)
    sent = api.last("POST", "/v1/bundles")
    assert documents.encode(e.value.problem) == json.loads(answer(sent).content)


def test_a_problem_with_no_detail_is_worded_by_its_title() -> None:
    body = {"type": "about:blank", "title": "Precondition failed", "status": 412, "rule": "twin.conflict"}
    c = raw({"/v1/twins": httpx.Response(412, json=body, headers={"content-type": "application/problem+json"})})
    with pytest.raises(ProblemError, match=r"^412 twin.conflict: Precondition failed$"):
        c.list_twins()


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(502, text="<html>Bad gateway</html>", headers={"content-type": "text/html"}),
        httpx.Response(500, json={"error": "boom"}),
        httpx.Response(404, json={"type": "about:blank", "title": "Not found", "status": 404}),
    ],
    ids=["html", "not-a-problem", "problem-without-rule"],
)
def test_a_refusal_with_no_problem_document_is_a_transport_error(answer: httpx.Response) -> None:
    with pytest.raises(TransportError, match=f"GET /v1/twins answered {answer.status_code} with no problem document"):
        raw({"/v1/twins": answer}).list_twins()


@pytest.mark.parametrize(
    ("path", "body", "call", "missing"),
    [
        ("/v1/twins", {"twns": []}, lambda c: c.list_twins(), "twins list"),
        ("/v1/runs", {"runs": {}}, lambda c: c.list_runs(), "runs list"),
        ("/v1/drivers", {}, lambda c: c.list_drivers(), "drivers list"),
        ("/v1/blueprints", {"id": 5}, lambda c: c.put_blueprint(BLUEPRINT), "id str"),
    ],
    ids=["twins", "runs", "drivers", "id"],
)
def test_a_success_missing_a_member_the_client_answers_is_a_transport_error(
    path: str, body: dict[str, object], call: Callable[[Client], object], missing: str
) -> None:
    with pytest.raises(TransportError, match=f"answered a document with no {missing}$"):
        call(raw({path: httpx.Response(200, json=body)}))


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(200, text="ok", headers={"content-type": "text/plain"}), httpx.Response(200, json=[1, 2])],
    ids=["text", "array"],
)
def test_a_success_with_no_json_document_is_a_transport_error(answer: httpx.Response) -> None:
    with pytest.raises(TransportError, match="GET /v1/twins answered 200 with no JSON document"):
        raw({"/v1/twins": answer}).list_twins()


def test_an_unreachable_server_is_a_transport_error_naming_the_call_and_not_the_token() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, unreachable)
    with pytest.raises(TransportError) as e:
        connect(api).get_twin(TWIN)
    assert str(e.value) == f"GET http://127.0.0.1:7650{TWIN_PATH} failed: [Errno 111] Connection refused"
    assert isinstance(e.value.__cause__, httpx.ConnectError)
    with pytest.raises(TransportError, match=re.escape("GET http://127.0.0.1:7650/v1/version failed")) as e:
        raw(transport=httpx.MockTransport(unreachable)).list_twins()
    assert TOKEN not in str(e.value)


def test_a_local_protocol_error_is_named_by_its_type_and_never_quoted() -> None:
    # The library's refusal of a header quotes the header, and that may be the Authorization one.
    def refuse_header(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {TOKEN}\\r\\n'")

    with pytest.raises(TransportError) as e:
        raw(transport=httpx.MockTransport(refuse_header)).list_twins()
    assert str(e.value) == "GET http://127.0.0.1:7650/v1/version failed: LocalProtocolError"


def test_a_transport_error_with_no_text_is_named_by_its_type() -> None:
    def silent(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    with pytest.raises(TransportError, match=r"/v1/version failed: ReadTimeout$"):
        raw(transport=httpx.MockTransport(silent)).list_twins()


# Server-sent events.


def test_the_event_stream_format_is_read_as_the_html_standard_has_it() -> None:
    lines = [
        ": a comment, and a keep-alive",
        "event: ADDED",
        "id: 1",
        "data: {",
        'data:"a": 1}',
        "",
        "",
        "data: second",
        "",
        "event: no-data",
        "",
        "id",
        "data",
        "",
        "data: unfinished",
    ]
    assert list(messages(lines)) == [
        Message("ADDED", "1", '{\n"a": 1}'),
        Message(None, "1", "second"),
        Message(None, "", ""),
    ]


def test_watch_twin_asks_for_a_stream_and_yields_each_watch_event() -> None:
    first, second = record(2, 1, 0, phase="compiled", run_id=RUN_ID), record(3, 1, 1, ready=("True", None))
    api = FakeAPI().on("GET", TWIN_PATH, watch(first, second, deleted=True))
    assert list(connect(api).watch_twin(TWIN, since_revision=1)) == [
        {"type": "MODIFIED", "object": first},
        {"type": "MODIFIED", "object": second},
        {"type": "DELETED", "object": second},
    ]
    sent = api.last("GET", TWIN_PATH)
    assert sent.headers["accept"] == EVENT_STREAM
    assert sent.url.params.multi_items() == [("watch", "true"), ("since_revision", "1")]
    list(connect(api).watch_twin(TWIN))
    assert api.last("GET", TWIN_PATH).url.params.multi_items() == [("watch", "true")]


def test_watch_twin_ends_after_deleted_and_reads_no_further() -> None:
    gone = record(6, 2, 1, deleting=True)
    pulled: list[str] = []

    def chunks() -> Iterator[bytes]:
        pulled.append("modified")
        modified = json.dumps({"type": "MODIFIED", "object": record(5, 2, 1, deleting=True)})
        yield f"event: MODIFIED\r\ndata: {modified[:20]}".encode()
        yield f"{modified[20:]}\r\n\r\n".encode()
        pulled.append("deleted")
        yield f"event: DELETED\ndata: {json.dumps({'type': 'DELETED', 'object': gone})}\n\n".encode()
        pulled.append("after")
        yield b"event: ADDED\ndata: {}\n\n"

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=chunks())

    api = FakeAPI().on("GET", TWIN_PATH, answer)
    events = list(connect(api).watch_twin(TWIN, since_revision=4))
    assert [e["type"] for e in events] == ["MODIFIED", "DELETED"]
    assert events[1]["object"] == gone
    assert pulled == ["modified", "deleted"]


def test_watch_run_streams_events_after_the_cursor_resuming_by_last_event_id() -> None:
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS[1:]))
    assert list(connect(api).watch_run(RUN_ID, after=1)) == EVENTS[1:]
    sent = streams(api, EVENTS_PATH)[-1]
    assert sent.headers["last-event-id"] == "1"
    assert sent.url.params.multi_items() == [("after", "1")]
    list(connect(api).watch_run(RUN_ID))
    sent = streams(api, EVENTS_PATH)[-1]
    assert "last-event-id" not in sent.headers and sent.url.params.multi_items() == [("after", "0")]


def test_a_refused_watch_is_a_problem_error() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, refuse(404, "twin.not_found", "No twin is named three-node."))
    with pytest.raises(ProblemError, match=r"^404 twin.not_found: No twin is named three-node.$"):
        list(connect(api).watch_twin(TWIN))


def test_a_watch_answered_as_json_is_a_transport_error() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(record(), headers={"ETag": '"1"'}))
    with pytest.raises(TransportError, match=f"answered application/json, not {EVENT_STREAM}"):
        list(connect(api).watch_twin(TWIN))


def test_an_event_whose_data_is_no_json_document_is_a_transport_error() -> None:
    answer = httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=b"data: [1]\n\n")
    with pytest.raises(TransportError, match="no JSON document"):
        list(raw({f"/v1/runs/{RUN_ID}/events": answer}).watch_run(RUN_ID))


@pytest.mark.parametrize(
    ("path", "data", "call", "said"),
    [
        (TWIN_PATH, {"type": "MODIFIED", "object": {"revision": "2"}}, lambda c: c.watch_twin(TWIN),
         "sent a WatchEvent with no object revision"),
        (TWIN_PATH, {"type": "MODIFIED"}, lambda c: c.watch_twin(TWIN), "sent a WatchEvent with no object revision"),
        (EVENTS_PATH, {"at": "2026-11-03T10:00:00.000000Z", "phase": "compile"}, lambda c: c.watch_run(RUN_ID),
         "sent an Event with no seq"),
        (EVENTS_PATH, {"seq": True}, lambda c: c.watch_run(RUN_ID), "sent an Event with no seq"),
    ],
    ids=["revision-text", "no-object", "no-seq", "seq-boolean"],
)
def test_an_event_with_no_integer_cursor_is_a_transport_error_and_not_resumed(
    path: str, data: dict[str, Any], call: Callable[[Client], Iterator[dict[str, Any]]], said: str
) -> None:
    sleeps: list[float] = []
    body = f"data: {json.dumps(data)}\n\n".encode()
    answer = httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=body)
    with pytest.raises(TransportError, match=f"^GET {path} {said}$"):
        list(call(raw({path: answer}, sleeps=sleeps)))
    assert sleeps == []


# A watch the server ends early.

R2 = record(2, 1, 0, phase="compiled", run_id=RUN_ID)
R3 = record(3, 1, 1, ready=("True", None))
WATCHED = [{"type": "MODIFIED", "object": R2}, {"type": "MODIFIED", "object": R3}, {"type": "DELETED", "object": R3}]
"""What a watch of the twin yields, at revisions 2 and 3 and then deleted, however its streams end."""
ENDED_EARLY = f"GET http://127.0.0.1:7650{TWIN_PATH} ended before its end"


def changed(r: dict[str, Any]) -> tuple[str, None, dict[str, Any]]:
    """A twin watch's message of a record MODIFIED, for `cut`."""
    return "MODIFIED", None, {"type": "MODIFIED", "object": r}


def deleted(r: dict[str, Any]) -> bytes:
    """A twin watch's stream body of a record DELETED."""
    return f"event: DELETED\ndata: {json.dumps({'type': 'DELETED', 'object': r})}\n\n".encode()


def test_the_wait_before_a_reconnect_doubles_from_half_a_second_to_ten() -> None:
    assert [reconnect_delay(n) for n in (1, 5, 6, 15)] == [0.5, 8.0, 10.0, 10.0]
    # About two minutes of waits, which outlasts a pod replaced under a 15 s Lease; the tries take up to 5 s each.
    assert sum(reconnect_delay(n) for n in range(1, RECONNECTS + 1)) == 115.5


def test_a_twin_watch_the_server_ends_early_is_resumed_after_the_last_revision_seen() -> None:
    sleeps: list[float] = []
    notices: list[str] = []
    api = FakeAPI().on("GET", TWIN_PATH, watch(R2), watch(R3, deleted=True))
    assert list(connect(api, sleeps, notices).watch_twin(TWIN, since_revision=1)) == WATCHED
    first, second = streams(api, TWIN_PATH)
    assert first.url.params.multi_items() == [("watch", "true"), ("since_revision", "1")]
    assert second.url.params.multi_items() == [("watch", "true"), ("since_revision", "2")]
    assert sleeps == [0.5]
    assert notices == [f"{ENDED_EARLY}; reconnecting"]


def test_a_twin_watch_cut_off_and_then_unreachable_backs_off_and_says_so_once() -> None:
    sleeps: list[float] = []
    notices: list[str] = []
    api = FakeAPI().on("GET", TWIN_PATH, cut("WatchEvent", [changed(R2)]), unreachable, unreachable,
                       watch(R3, deleted=True))
    assert list(connect(api, sleeps, notices).watch_twin(TWIN, since_revision=1)) == WATCHED
    assert [r.url.params["since_revision"] for r in streams(api, TWIN_PATH)] == ["1", "2", "2", "2"]
    assert sleeps == [0.5, 1.0, 2.0]
    assert notices == [f"GET http://127.0.0.1:7650{TWIN_PATH} failed: connection reset; reconnecting"]


def test_an_event_yielded_starts_the_count_of_early_ends_again() -> None:
    sleeps: list[float] = []
    api = FakeAPI().on("GET", TWIN_PATH, cut("WatchEvent", [changed(R2)]), cut("WatchEvent", [changed(R3)]),
                       sse("WatchEvent", [("DELETED", None, {"type": "DELETED", "object": R3})]))
    assert list(connect(api, sleeps).watch_twin(TWIN, since_revision=1)) == WATCHED
    assert sleeps == [0.5, 0.5]


def test_a_twin_watch_ended_early_for_ever_is_given_up_after_fifteen_reconnects_naming_the_call() -> None:
    sleeps: list[float] = []
    seen = []
    api = FakeAPI().on("GET", TWIN_PATH, watch(R2), watch())
    with pytest.raises(TransportError, match=r"ended before its end; not resumed after 15 reconnects$") as e:
        for event in connect(api, sleeps).watch_twin(TWIN, since_revision=1):
            seen.append(event)
    assert str(e.value) == f"{ENDED_EARLY}; not resumed after 15 reconnects"
    assert seen == [{"type": "MODIFIED", "object": R2}]
    assert sleeps == [0.5, 1.0, 2.0, 4.0, 8.0] + [10.0] * 10
    assert len(streams(api, TWIN_PATH)) == 16


@pytest.mark.parametrize(
    ("path", "call"),
    [(TWIN_PATH, lambda c: c.watch_twin(TWIN)), (EVENTS_PATH, lambda c: c.watch_run(RUN_ID))],
    ids=["twin", "run"],
)
def test_a_server_unreachable_from_the_first_open_is_given_up_on_and_a_wrong_address_at_once(
    path: str, call: Callable[[Client], Iterator[dict[str, Any]]]
) -> None:
    sleeps: list[float] = []
    with pytest.raises(TransportError, match=r"Connection refused; not resumed after 15 reconnects$"):
        list(call(connect(FakeAPI().on("GET", path, unreachable), sleeps)))
    assert len(sleeps) == 15
    sleeps.clear()
    # The version check of a client that has not yet spoken is made once, before any stream.
    api = FakeAPI().on("GET", "/v1/version", unreachable)
    with pytest.raises(TransportError) as e:
        list(call(connect(api, sleeps)))
    assert str(e.value) == "GET http://127.0.0.1:7650/v1/version failed: [Errno 111] Connection refused"
    assert sleeps == [] and len(api.requests) == 1


@pytest.mark.parametrize(
    ("path", "call"),
    [(TWIN_PATH, lambda c: c.watch_twin(TWIN)), (EVENTS_PATH, lambda c: c.watch_run(RUN_ID))],
    ids=["twin", "run"],
)
def test_each_reconnect_of_a_watch_is_given_five_seconds_to_connect(
    path: str, call: Callable[[Client], Iterator[dict[str, Any]]]
) -> None:
    """A LoadBalancer address with no ready pod behind it drops what is sent to it, and one open waited out the
    client's 30 s to connect (verified-facts.md): fifteen such opens would hold a watch for ten minutes. The first
    open is given the client's own `TIMEOUT_S`, as every other call is; each reconnect's open 5 s to connect, the TLS
    handshake within it, and its read, as every stream's, no bound."""
    api = FakeAPI().on("GET", path, unreachable)
    with pytest.raises(TransportError, match=r"not resumed after 15 reconnects$"):
        list(call(connect(api, [])))
    first, *again = streams(api, path)
    assert first.extensions["timeout"] == {"connect": 30.0, "read": None, "write": 30.0, "pool": 30.0}
    assert len(again) == 15
    assert all(r.extensions["timeout"] == {"connect": 5.0, "read": None, "write": 30.0, "pool": 30.0} for r in again)


def test_a_run_watchs_page_read_after_its_stream_ends_is_given_five_seconds_to_connect() -> None:
    """The page a run's watch reads once its stream has ended, as the server goes away, meets the address as a
    reconnect's open does: 5 s to connect, its read bounded as every call's."""
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS[:1]), ok({"events": [], "next": 1, "ended": False}),
                       event_stream(*EVENTS[1:]), ok({"events": [], "next": len(EVENTS), "ended": True}))
    assert list(connect(api, []).watch_run(RUN_ID)) == EVENTS
    pages = [r for r in api.requests if r.url.path == EVENTS_PATH and r.headers["accept"] != EVENT_STREAM]
    assert len(pages) == 2
    assert all(r.extensions["timeout"] == {"connect": 5.0, "read": 30.0, "write": 30.0, "pool": 30.0} for r in pages)


def test_a_twin_deleted_between_two_streams_is_the_servers_refusal_with_no_deleted_made_up() -> None:
    sleeps: list[float] = []
    seen = []
    api = FakeAPI().on("GET", TWIN_PATH, watch(R2), refuse(404, "twin.not_found", "No twin is named three-node."))
    with pytest.raises(ProblemError, match=r"^404 twin.not_found: No twin is named three-node.$"):
        for event in connect(api, sleeps).watch_twin(TWIN, since_revision=1):
            seen.append(event)
    assert seen == [{"type": "MODIFIED", "object": R2}]
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    ("path", "first", "call"),
    [
        (TWIN_PATH, [watch(R2)], lambda c: c.watch_twin(TWIN, since_revision=1)),
        (EVENTS_PATH, [event_stream(*EVENTS[:1]), ok({"events": [], "next": 1, "ended": False})],
         lambda c: c.watch_run(RUN_ID)),
    ],
    ids=["twin", "run"],
)
def test_a_reconnect_that_meets_a_certificate_not_trusted_ends_the_watch_at_once(
    path: str, first: list[Answer], call: Callable[[Client], Iterator[dict[str, Any]]]
) -> None:
    # The server came back with a certificate the client does not trust: no wait mends that.
    sleeps: list[float] = []
    api = FakeAPI().on("GET", path, *first, untrusted)
    c = Client("https://core.example", TOKEN, transport=api.transport, sleep=sleeps.append)
    with pytest.raises(Untrusted) as e:
        list(call(c))
    assert str(e.value) == (f"GET https://core.example{path} failed: the server's certificate is not trusted: "
                            f"{UNTRUSTED}")
    assert sleeps == [0.5] and len(streams(api, path)) == 2


def test_a_failed_verification_that_carries_no_message_is_untrusted_all_the_same() -> None:
    # `ssl` sets `verify_message` on the error it raises; one made by another hand need not carry it.
    def unverified(request: httpx.Request) -> httpx.Response:
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        except ssl.SSLCertVerificationError:
            raise httpx.ConnectError("the handshake failed", request=request) from None

    api = FakeAPI().on("GET", "/v1/version", unverified)
    with pytest.raises(Untrusted) as e:
        Client("https://core.example", TOKEN, transport=api.transport).version()
    assert str(e.value) == ("GET https://core.example/v1/version failed: the server's certificate is not trusted: "
                            "certificate verify failed")


def test_a_tls_failure_other_than_a_verification_is_an_early_end_and_the_watch_reconnects() -> None:
    # A handshake the server's TLS ended with an alert may go through at the next open, unlike one whose certificate
    # is not trusted.
    def alerted(request: httpx.Request) -> httpx.Response:
        try:
            raise ssl.SSLError(1, "[SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error (_ssl.c:1010)")
        except ssl.SSLError as failure:
            raise httpx.ConnectError(str(failure), request=request) from None

    sleeps: list[float] = []
    api = FakeAPI().on("GET", TWIN_PATH, cut("WatchEvent", [changed(R2)]), alerted, watch(R3, deleted=True))
    assert list(connect(api, sleeps).watch_twin(TWIN, since_revision=1)) == WATCHED
    assert sleeps == [0.5, 1.0] and len(streams(api, TWIN_PATH)) == 3


def test_a_reconnect_answered_as_json_is_a_transport_error_and_not_resumed() -> None:
    sleeps: list[float] = []
    api = FakeAPI().on("GET", TWIN_PATH, watch(R2), ok(record(), headers={"ETag": '"2"'}))
    with pytest.raises(TransportError, match=f"answered application/json, not {EVENT_STREAM}"):
        list(connect(api, sleeps).watch_twin(TWIN, since_revision=1))
    assert api.calls() == [f"GET {TWIN_PATH}"] * 2
    assert sleeps == [0.5]


def test_a_proxys_5xx_with_no_problem_document_is_an_early_end_and_a_4xx_is_not() -> None:
    sleeps: list[float] = []
    notices: list[str] = []
    away = httpx.Response(502, text="Bad gateway", headers={"content-type": "text/plain"})
    gone = httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=deleted(R3))
    c = raw({TWIN_PATH: [away, gone]}, sleeps=sleeps, notices=notices)
    assert list(c.watch_twin(TWIN)) == [{"type": "DELETED", "object": R3}]
    assert sleeps == [0.5]
    assert notices == [f"GET {TWIN_PATH} answered 502 with no problem document; reconnecting"]
    sleeps.clear()
    not_found = httpx.Response(404, text="Not found", headers={"content-type": "text/plain"})
    with pytest.raises(TransportError, match=f"^GET {TWIN_PATH} answered 404 with no problem document$"):
        list(raw({TWIN_PATH: not_found}, sleeps=sleeps).watch_twin(TWIN))
    assert sleeps == []


def test_a_run_watch_reads_the_page_once_the_stream_ends_to_know_the_run_has_ended() -> None:
    sleeps: list[float] = []
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS))
    assert list(connect(api, sleeps).watch_run(RUN_ID)) == EVENTS
    assert sleeps == []
    stream, page = api.requests[1:]
    assert stream.headers["accept"] == EVENT_STREAM and stream.url.params.multi_items() == [("after", "0")]
    assert page.headers["accept"] == JSON_TYPES and page.url.params.multi_items() == [("after", "3")]


def test_the_events_a_server_stopped_as_the_run_ended_never_sent_come_from_the_page() -> None:
    sleeps: list[float] = []
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS[:2]), ok({"events": [EVENTS[2]], "next": 3,
                                                                           "ended": True}))
    assert list(connect(api, sleeps).watch_run(RUN_ID)) == EVENTS
    assert api.last("GET", EVENTS_PATH).url.params.multi_items() == [("after", "2")]
    assert sleeps == []


def test_a_run_stream_that_ends_with_the_run_still_running_is_resumed_after_the_last_event() -> None:
    sleeps: list[float] = []
    notices: list[str] = []
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS[:1]), ok({"events": [], "next": 1, "ended": False}),
                       event_stream(*EVENTS[1:]))
    assert list(connect(api, sleeps, notices).watch_run(RUN_ID)) == EVENTS
    _, second = streams(api, EVENTS_PATH)
    assert second.url.params.multi_items() == [("after", "1")] and second.headers["last-event-id"] == "1"
    assert sleeps == [0.5]
    assert notices == [f"GET http://127.0.0.1:7650{EVENTS_PATH} ended before its end; reconnecting"]


def test_a_run_stream_cut_off_is_resumed_after_what_arrived() -> None:
    sleeps: list[float] = []
    notices: list[str] = []
    api = FakeAPI().on("GET", EVENTS_PATH, cut("Event", [(None, "1", EVENTS[0])]), event_stream(*EVENTS[1:]))
    assert list(connect(api, sleeps, notices).watch_run(RUN_ID)) == EVENTS
    assert streams(api, EVENTS_PATH)[1].headers["last-event-id"] == "1"
    assert sleeps == [0.5]
    assert notices == [f"GET http://127.0.0.1:7650{EVENTS_PATH} failed: connection reset; reconnecting"]


@pytest.mark.parametrize("sent", [3, 2], ids=["every-event-sent", "one-never-sent"])
def test_a_page_read_that_meets_a_server_gone_is_an_early_end_and_each_event_arrives_once(sent: int) -> None:
    # A server stopped as the run ended: its stream ended cleanly, with or without the last event, and
    # the page that would say the run ended meets it gone. The reconnect brings what it never sent.
    sleeps: list[float] = []
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(*EVENTS[:sent]), unreachable, event_stream(*EVENTS[sent:]))
    assert list(connect(api, sleeps).watch_run(RUN_ID)) == EVENTS
    assert [r.url.params["after"] for r in api.requests[1:]] == ["0", str(sent), str(sent), "3"]
    assert sleeps == [0.5]


def test_a_run_whose_page_never_says_it_ended_is_given_up_on() -> None:
    sleeps: list[float] = []
    api = FakeAPI().on("GET", EVENTS_PATH, event_stream(ended=False))
    with pytest.raises(TransportError, match=r"ended before its end; not resumed after 15 reconnects$"):
        list(connect(api, sleeps).watch_run(RUN_ID))
    assert len(sleeps) == 15


def test_a_connection_closed_mid_chunk_is_an_early_end() -> None:
    """A server killed with a watch open closes the socket in the middle of a chunked body, with
    no last chunk: over a real socket, the client reads that as an early end and resumes, each
    event once."""
    first = f"event: MODIFIED\ndata: {json.dumps(changed(R2)[2])}\n\n".encode()
    rest = f"event: MODIFIED\ndata: {json.dumps(changed(R3)[2])}\n\n".encode() + deleted(R3)
    version = json.dumps(VERSION).encode()
    answers = [
        b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nconnection: close\r\n"
        b"content-length: %d\r\n\r\n%s" % (len(version), version),
        b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n"
        b"%x\r\n%s\r\n" % (len(first), first),
        b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\nconnection: close\r\n"
        b"content-length: %d\r\n\r\n%s" % (len(rest), rest),
    ]
    asked: list[bytes] = []
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(10)

    def serve() -> None:
        # Each answer on a connection of its own, the socket closed once it is sent; the listening
        # socket closed however this ends, so a client left waiting is refused rather than held.
        with server:
            for answer in answers:
                connection, _ = server.accept()
                with connection:
                    request = b""
                    while b"\r\n\r\n" not in request and (chunk := connection.recv(4096)):
                        request += chunk
                    asked.append(request.partition(b"\r\n")[0])
                    connection.sendall(answer)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    sleeps: list[float] = []
    notices: list[str] = []
    address = f"127.0.0.1:{server.getsockname()[1]}"
    with Client(address, TOKEN, sleep=sleeps.append, notice=notices.append) as c:
        assert list(c.watch_twin(TWIN, since_revision=1)) == WATCHED
    thread.join(10)
    assert asked == [b"GET /v1/version HTTP/1.1",
                     f"GET {TWIN_PATH}?watch=true&since_revision=1 HTTP/1.1".encode(),
                     f"GET {TWIN_PATH}?watch=true&since_revision=2 HTTP/1.1".encode()]
    assert sleeps == [0.5]
    assert len(notices) == 1 and notices[0].endswith("; reconnecting"), notices
