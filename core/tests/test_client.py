"""The client library of API 1: each call's request as the OpenAPI document declares it (the
fake server checks every one), its answer as a document, a refusal as a `ProblemError`
carrying the server's problem document, what happened to the client a `TransportError`, and a
twin's or a run's server-sent events parsed."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator

import httpx
import pytest
from fake_api import (
    ADDRESS,
    BLUEPRINT,
    BLUEPRINT_ID,
    BUNDLE,
    BUNDLE_ID,
    COMPILE_RESULT,
    DRIVERS,
    EVENTS,
    NOT_HELD,
    PLAN,
    RUN_ID,
    TOKEN,
    TWIN,
    VERSION,
    FakeAPI,
    event_stream,
    ok,
    record,
    refuse,
    run,
    step_plan,
    unreachable,
    verification,
    watch,
)

from fylgja_core import documents
from fylgja_core.client import (
    EVENT_STREAM,
    JSON_TYPES,
    TIMEOUT_S,
    VERIFY_TIMEOUT,
    Client,
    InvalidAddress,
    InvalidToken,
    Message,
    ProblemError,
    TransportError,
    UnsupportedVersion,
    base_url,
    bearer,
    messages,
)
from fylgja_core.findings import Finding

TWIN_PATH = f"/v1/twins/{TWIN}"
SPEC = {"blueprint_id": BLUEPRINT_ID, "driver": "containerlab", "allow_restart": False}


def connect(api: FakeAPI) -> Client:
    return Client(ADDRESS, TOKEN, transport=api.transport)


def raw(answers: dict[str, httpx.Response] | None = None, *, transport: httpx.MockTransport | None = None) -> Client:
    """A client of a server the OpenAPI document does not hold: it answers the version, then
    each path from `answers`."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/version":
            return httpx.Response(200, json=VERSION)
        return (answers or {})[request.url.path]

    return Client(ADDRESS, TOKEN, transport=transport or httpx.MockTransport(handle))


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
    api = FakeAPI().on("GET", TWIN_PATH, watch(first, second))
    assert list(connect(api).watch_twin(TWIN, since_revision=1)) == [
        {"type": "MODIFIED", "object": first},
        {"type": "MODIFIED", "object": second},
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
    api = FakeAPI().on("GET", f"/v1/runs/{RUN_ID}/events", event_stream(*EVENTS[1:]))
    assert list(connect(api).watch_run(RUN_ID, after=1)) == EVENTS[1:]
    sent = api.last("GET", f"/v1/runs/{RUN_ID}/events")
    assert sent.headers["accept"] == EVENT_STREAM and sent.headers["last-event-id"] == "1"
    assert sent.url.params.multi_items() == [("after", "1")]
    list(connect(api).watch_run(RUN_ID))
    sent = api.last("GET", f"/v1/runs/{RUN_ID}/events")
    assert "last-event-id" not in sent.headers and sent.url.params.multi_items() == [("after", "0")]


def test_a_refused_watch_is_a_problem_error() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, refuse(404, "twin.not_found", "No twin is named three-node."))
    with pytest.raises(ProblemError, match=r"^404 twin.not_found: No twin is named three-node.$"):
        list(connect(api).watch_twin(TWIN))


def test_a_watch_answered_as_json_is_a_transport_error() -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(record(), headers={"ETag": '"1"'}))
    with pytest.raises(TransportError, match=f"answered application/json, not {EVENT_STREAM}"):
        list(connect(api).watch_twin(TWIN))


def test_a_stream_cut_off_is_a_transport_error_after_what_arrived() -> None:
    def chunks() -> Iterator[bytes]:
        yield f"id: 1\ndata: {json.dumps(EVENTS[0])}\n\n".encode()
        raise httpx.ReadError("connection reset")

    api = FakeAPI().on(
        "GET", f"/v1/runs/{RUN_ID}/events",
        lambda request: httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=chunks()),
    )
    seen = []
    with pytest.raises(TransportError, match="connection reset"):
        for e in connect(api).watch_run(RUN_ID):
            seen.append(e)
    assert seen == [EVENTS[0]]


def test_an_event_whose_data_is_no_json_document_is_a_transport_error() -> None:
    answer = httpx.Response(200, headers={"content-type": EVENT_STREAM}, content=b"data: [1]\n\n")
    with pytest.raises(TransportError, match="no JSON document"):
        list(raw({f"/v1/runs/{RUN_ID}/events": answer}).watch_run(RUN_ID))
