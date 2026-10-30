"""The adapter's client against the core's (`internal/intent`'s at_test.go and
errors_test.go): the environment, `at`'s precision and its form on the wire, the branch in
the path, the schema endpoint first and with no `at`, and every refusal in Infrahub's words,
naming the (branch, at) asked for and never the credential. The SDK runs whole, answered
through its own transport hook."""

import pytest

from fylgja_orchestrator.adapters.infrahub import client as infrahub_client
from fylgja_orchestrator.adapters.infrahub.client import (
    ClientError,
    Config,
    ConfigError,
    check_at_precision,
    explain_status,
    from_env,
    redact,
    startup_line,
)

from .conftest import TOKEN


@pytest.fixture
def env(monkeypatch):
    for name in ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_from_env_reads_the_address_and_the_token(env):
    env.setenv("INFRAHUB_ADDRESS", "http://h:8000//")
    env.setenv("INFRAHUB_API_TOKEN", "sekrit")
    cfg = from_env("b1", "2026-09-08T12:00:00Z")
    assert (cfg.address, cfg.token, cfg.branch, cfg.at) == ("http://h:8000", "sekrit", "b1", "2026-09-08T12:00:00Z")
    assert "sekrit" not in repr(cfg)


@pytest.mark.parametrize(
    "address,token,branch,want",
    [
        ("", "t", "b", "INFRAHUB_ADDRESS is not set"),
        ("http://h", "", "b", "INFRAHUB_API_TOKEN is not set"),
        ("http://h", "t", "", "no branch given"),
    ],
)
def test_from_env_refuses_what_is_missing(env, address, token, branch, want):
    if address:
        env.setenv("INFRAHUB_ADDRESS", address)
    if token:
        env.setenv("INFRAHUB_API_TOKEN", token)
    with pytest.raises(ConfigError, match=want):
        from_env(branch)


@pytest.mark.parametrize(
    "at,digits",
    [
        ("", 0),
        ("2026-09-08T19:37:02Z", 0),
        ("2026-09-08T19:37:02.1Z", 0),
        ("2026-09-08T19:37:02.123456Z", 0),
        ("2026-09-08T19:37:02.1234567Z", 7),
        ("2026-09-08T19:37:02.123456789Z", 9),
    ],
)
def test_at_precision_guard(at, digits):
    msg = check_at_precision(at)
    if not digits:
        assert msg == ""
        return
    assert msg == (
        f"at {at} carries {digits} fractional digits; Infrahub honours at most 6 (microseconds). "
        "Re-run with a coarser --at."
    )


@pytest.mark.parametrize("at", ["2026-09-08T19:37:02+00:00", "2026-09-08T19:37:02.123456+02:00", "yesterday"])
def test_at_precision_ignores_the_rest_of_the_format(at):
    assert check_at_precision(at) == ""


def test_graphql_goes_to_the_branch_s_path_with_the_key_and_no_at(infrahub, client_for):
    infrahub.graphql = {"data": {"DcimDevice": {"edges": []}}}
    data = client_for("fylgja-fixture").graphql("query { DcimDevice { edges { node { id } } } }", {"a": 1})
    assert data == {"DcimDevice": {"edges": []}}
    (request,) = infrahub.requests
    assert request["url"] == "http://infrahub.test/graphql/fylgja-fixture"
    assert request["headers"]["X-INFRAHUB-KEY"] == TOKEN
    assert request["payload"] == {"query": "query { DcimDevice { edges { node { id } } } }", "variables": {"a": 1}}


@pytest.mark.parametrize(
    "at,encoded",
    [
        # An unencoded "+" is read as a space and refused; the SDK would rewrite the value
        # into UTC with six digits, which is not what the operator asked for.
        ("2026-09-08T18:00:00+00:00", "at=2026-09-08T18%3A00%3A00%2B00%3A00"),
        ("2026-09-08T18:00:00.1Z", "at=2026-09-08T18%3A00%3A00.1Z"),
        ("yesterday", "at=yesterday"),
    ],
)
def test_at_is_sent_verbatim_and_encoded(infrahub, client_for, at, encoded):
    infrahub.branches.add("my-branch")
    client_for("my-branch", at=at).graphql("query { x }")
    (request,) = infrahub.requests
    assert request["url"] == f"http://infrahub.test/graphql/my-branch?{encoded}"
    assert request["query"]["at"] == [at]


def test_the_schema_endpoint_is_asked_with_no_at(infrahub, client_for):
    client_for("fylgja-fixture", at="2026-09-08T18:00:00Z").schema_document()
    (request,) = infrahub.requests
    assert request["url"] == "http://infrahub.test/api/schema?branch=fylgja-fixture"
    assert request["headers"]["X-INFRAHUB-KEY"] == TOKEN


def test_get_at_carries_the_at_and_get_none(infrahub, client_for):
    pinned = client_for("b", at="2026-09-08T18:00:00+00:00")
    pinned.get_at("/api/storage/object/x")
    pinned.get_at("/api/storage/object/x?a=1")
    client_for("b").get_at("/api/storage/object/x")
    assert [r["url"].removeprefix("http://infrahub.test") for r in infrahub.requests] == [
        "/api/storage/object/x?at=2026-09-08T18%3A00%3A00%2B00%3A00",
        "/api/storage/object/x?a=1&at=2026-09-08T18%3A00%3A00%2B00%3A00",
        "/api/storage/object/x",
    ]


@pytest.mark.parametrize(
    "status,want",
    [(401, "the credential in INFRAHUB_API_TOKEN was rejected by Infrahub"),
     (403, "the credential in INFRAHUB_API_TOKEN is not permitted to read this branch")],
)
def test_a_refused_credential_is_named(infrahub, client_for, status, want):
    infrahub.graphql_status = status
    infrahub.graphql = {"errors": [{"message": "Authentication is required"}]}
    with pytest.raises(ClientError) as raised:
        client_for("main").graphql("query { x }")
    assert str(raised.value) == f"querying (branch main): {want}"
    assert raised.value.credential_refused and not raised.value.branch_missing


def test_the_schema_endpoint_names_a_refused_credential(client_for):
    with pytest.raises(ClientError) as raised:
        client_for("main", token="wrong-token").schema_document()
    assert str(raised.value) == (
        "reading the schema (branch main): the credential in INFRAHUB_API_TOKEN was rejected by Infrahub"
    )
    assert raised.value.credential_refused


# The bodies the live instance returned on 2026-09-14 (errors_test.go).
REFUSALS = [
    ("unknown branch", 404, {"errors": ["Branch: does-not-exist not found."]}, "",
     "querying (branch does-not-exist): HTTP 404: Branch: does-not-exist not found.", True),
    ("at before the default branch", 422,
     {"data": None, "errors": [{"message": "Requested time '2020-01-01T00:00:00.000000Z' is before branch 'main' "
                                           "was created at '2026-09-08T18:05:22.715400Z'.",
                                "extensions": {"code": "UNDEFINED_ERROR", "http_status": 422}}]},
     "2020-01-01T00:00:00Z",
     "querying (branch does-not-exist, at 2020-01-01T00:00:00Z): HTTP 422: Requested time "
     "'2020-01-01T00:00:00.000000Z' is before branch 'main' was created at '2026-09-08T18:05:22.715400Z'.", False),
    ("unparseable at", 400,
     {"data": None, "errors": [{"message": "Invalid time format for yesterday",
                                "extensions": {"code": "UNDEFINED_ERROR", "http_status": 400}}]},
     "yesterday", "querying (branch does-not-exist, at yesterday): HTTP 400: Invalid time format for yesterday", False),
    ("422 naming the branch", 422, {"errors": [{"message": "Branch: does-not-exist not found."}]}, "",
     "querying (branch does-not-exist): HTTP 422: Branch: does-not-exist not found.", False),
    ("errors under 200", 200, {"data": None, "errors": [{"message": "Cannot query field 'x'"}, {"message": "second"}]},
     "", "querying (branch does-not-exist): Cannot query field 'x'; second", False),
]


@pytest.mark.parametrize("name,status,body,at,want,missing", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_infrahub_s_refusals_are_surfaced_with_the_reference(infrahub, client_for, name, status, body, at, want,
                                                             missing):
    infrahub.branches.add("does-not-exist")
    if status == 404:
        infrahub.branches.discard("does-not-exist")
    infrahub.graphql_status, infrahub.graphql = status, body
    with pytest.raises(ClientError) as raised:
        client_for("does-not-exist", at=at).graphql("query { x }")
    assert str(raised.value) == want
    assert raised.value.branch_missing is missing
    assert TOKEN not in str(raised.value)


def test_an_unknown_branch_says_so_and_never_the_credential(infrahub, client_for):
    # The server quotes the credential back, as a debug-mode server or a proxy would.
    infrahub.schema_status = 400
    infrahub.schema_body = (
        '{"data":null,"errors":[{"message":"Branch: nope not found.","detail":"key ' + TOKEN + '"},'
        '{"message":"rejected key ' + TOKEN + '"}]}'
    ).encode()
    with pytest.raises(ClientError) as raised:
        client_for("nope").schema_document()
    assert str(raised.value) == (
        "reading the schema (branch nope): HTTP 400: Branch: nope not found.; rejected key <redacted>"
    )
    assert raised.value.branch_missing


@pytest.mark.parametrize(
    "status,body,missing",
    [
        (400, b'{"data":null,"errors":[{"message":"Branch: gone not found.","extensions":{"code":400}}]}', True),
        (400, b'{"errors":[{"message":"Branch: other not found."}]}', False),
        (400, b'{"errors":[{"message":"bad request"}]}', False),
        (500, b"<html>oops</html>", False),
    ],
)
def test_only_a_missing_branch_is_marked_not_found(infrahub, client_for, status, body, missing):
    infrahub.schema_status, infrahub.schema_body = status, body
    with pytest.raises(ClientError) as raised:
        client_for("gone").schema_document()
    assert raised.value.branch_missing is missing


def test_a_branch_infrahub_lacks_is_answered_by_the_schema_endpoint_first(client_for):
    with pytest.raises(ClientError) as raised:
        client_for("nope").schema_document()
    assert str(raised.value) == "reading the schema (branch nope): HTTP 400: Branch: nope not found."
    assert raised.value.branch_missing


def test_an_unreachable_infrahub_is_reported_without_the_credential():
    cfg = Config(address="http://127.0.0.1:9", token="sentinel-token", branch="fylgja-fixture")
    with pytest.raises(ClientError) as raised:
        infrahub_client.Client(cfg).schema_document()
    message = str(raised.value)
    assert message.startswith("reading the schema (branch fylgja-fixture): ")
    assert "sentinel-token" not in message
    assert not raised.value.branch_missing and not raised.value.credential_refused


def test_a_schema_document_without_a_hash_is_refused(infrahub, client_for):
    infrahub.schema = {"nodes": [], "generics": []}
    with pytest.raises(ClientError, match=r"reading the schema \(branch fylgja-fixture\): no schema hash reported"):
        client_for().schema_document()


@pytest.mark.parametrize(
    "status,body,want",
    [
        (400, '{"data":null,"errors":[{"message":"Branch: nope not found.","extensions":{"code":400}}]}',
         "HTTP 400: Branch: nope not found."),
        (400, '{"errors":["Branch: nope not found."]}', "HTTP 400: Branch: nope not found."),
        (422, '{"errors":[{"message":"first"},{"message":"second"}]}', "HTTP 422: first; second"),
        (502, "<html><body>Bad Gateway</body></html>", "HTTP 502"),
        (500, "", "HTTP 500"),
        (400, '{"errors":[]}', "HTTP 400"),
    ],
)
def test_explain_status_surfaces_infrahub_s_words(status, body, want):
    assert explain_status(status, body) == want


def test_redact_removes_the_token():
    assert redact("dial failed with key sekrit-token", "sekrit-token") == "dial failed with key <redacted>"
    assert redact("nothing here", "") == "nothing here"


def test_the_startup_line_names_the_reader_and_never_the_token():
    line = startup_line("http://localhost:8000", "infrahub-dcim", "26336e9", "tag:fylgja")
    assert line == "fylgja-infrahub: reading http://localhost:8000 as infrahub-dcim@26336e9, scope tag:fylgja"


def test_no_infrahub_setting_in_the_environment_moves_the_client(env, infrahub, client_for):
    # The SDK's settings read INFRAHUB_*; a username there would turn on password login.
    env.setenv("INFRAHUB_USERNAME", "admin")
    env.setenv("INFRAHUB_PASSWORD", "pw")
    env.setenv("INFRAHUB_RETRY_ON_FAILURE", "true")
    client_for("main").graphql("query { x }")
    assert [r["path"] for r in infrahub.requests] == ["/graphql/main"]
