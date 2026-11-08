"""The SigV4 signer against botocore's frozen answers (D-061)."""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import http.server
import json
import re
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from fake_s3 import FakeS3

from fylgja_core import s3

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "testdata" / "s3" / "sigv4.json").read_text())
CASES: dict[str, dict[str, Any]] = {case["name"]: case for case in FIXTURE["cases"]}


def at(case: dict[str, Any]) -> datetime.datetime:
    return datetime.datetime.strptime(case["at"], "%Y%m%dT%H%M%SZ").replace(
        tzinfo=datetime.UTC
    )


def signed(case: dict[str, Any], when: datetime.datetime | None = None) -> dict[str, str]:
    return s3.sign(
        case["method"],
        case["url"],
        case["headers"],
        case["body"].encode(),
        access_key=FIXTURE["access_key"],
        secret_key=FIXTURE["secret_key"],
        region=FIXTURE["region"],
        at=when or at(case),
    )


@pytest.mark.parametrize("name", list(CASES))
def test_every_known_answer_is_reproduced(name: str) -> None:
    case = CASES[name]
    url = s3.request_url(case["endpoint"], case["bucket"], case["key"], case["query"])
    assert url == case["url"]
    assert signed(case)["authorization"] == case["authorization"]


def test_the_fixture_names_its_source() -> None:
    source = FIXTURE["source"]
    assert source["signer"] == "botocore.auth.S3SigV4Auth"
    assert re.fullmatch(r"\d+\.\d+\.\d+", source["botocore"])
    assert len(FIXTURE["cases"]) == 9


def test_botocore_is_no_dependency() -> None:
    assert "botocore" not in (ROOT / "core" / "pyproject.toml").read_text()


def test_the_payload_hash_is_the_bodys() -> None:
    put = signed(CASES["put-create"])
    assert put["x-amz-content-sha256"] == hashlib.sha256(b'{"rev":1}').hexdigest()
    assert signed(CASES["get"])["x-amz-content-sha256"] == hashlib.sha256(b"").hexdigest()


def test_sign_returns_no_host_and_no_secret() -> None:
    result = signed(CASES["put-replace"])
    assert "host" not in result
    assert all(FIXTURE["secret_key"] not in value for value in result.values())
    assert {"x-amz-date", "x-amz-content-sha256", "authorization", "if-match"} <= set(result)


def test_a_time_in_another_zone_signs_as_utc() -> None:
    case = CASES["put-create"]
    zone = datetime.timezone(datetime.timedelta(hours=2))
    assert (
        signed(case, at(case).astimezone(zone))["authorization"] == case["authorization"]
    )


# --- the four calls, over the fake endpoint ---------------------------------------------


def query_of(request: httpx.Request) -> dict[str, str]:
    return dict(parse_qsl(request.url.query.decode()))


def test_a_put_then_a_get_answers_the_body_and_the_quoted_etag() -> None:
    fake = FakeS3()
    client = fake.client()
    etag = client.put("twins/a.json", b"one")
    body, got = client.get("twins/a.json")
    assert body == b"one"
    assert got == etag
    assert etag.startswith('"') and etag.endswith('"')


def test_a_create_over_an_object_is_refused_and_leaves_it() -> None:
    fake = FakeS3()
    client = fake.client()
    client.put("k", b"one", if_none_match=True)
    with pytest.raises(s3.PreconditionFailed) as refused:
        client.put("k", b"two", if_none_match=True)
    assert refused.value.settled is True
    assert fake.objects["k"] == b"one"


def test_a_replace_and_a_delete_at_an_earlier_etag_are_refused() -> None:
    fake = FakeS3()
    client = fake.client()
    first = client.put("k", b"one")
    client.put("k", b"two", if_match=first)
    with pytest.raises(s3.PreconditionFailed):
        client.put("k", b"three", if_match=first)
    with pytest.raises(s3.PreconditionFailed):
        client.delete("k", if_match=first)
    assert fake.objects["k"] == b"two"
    client.delete("k", if_match=fake.etag("k"))
    assert "k" not in fake.objects


def test_the_etag_goes_back_as_it_came() -> None:
    fake = FakeS3()
    client = fake.client()
    client.put("k", b"one")
    _, etag = client.get("k")
    client.put("k", b"two", if_match=etag)
    assert fake.requests[-1].headers["if-match"] == etag


def test_a_409_conditional_request_conflict_is_a_refusal_not_settled() -> None:
    fake = FakeS3()
    client = fake.client()
    fake.forced = [(409, "ConditionalRequestConflict")]
    with pytest.raises(s3.PreconditionFailed) as refused:
        client.put("k", b"one", if_none_match=True)
    assert refused.value.settled is False
    fake.forced = [(409, "OperationAborted")]
    with pytest.raises(s3.S3Error) as plain:
        client.put("k", b"one", if_none_match=True)
    assert not isinstance(plain.value, s3.PreconditionFailed)


def test_a_missing_key_is_no_such_key_and_a_missing_bucket_is_not() -> None:
    fake = FakeS3()
    with pytest.raises(s3.NoSuchKey):
        fake.client().get("missing")
    with pytest.raises(s3.S3Error) as error:
        fake.client(bucket="other").get("missing")
    assert not isinstance(error.value, s3.NoSuchKey)
    assert "NoSuchBucket" in str(error.value)


@pytest.mark.parametrize(("body", "code"), [(b"<Error><Code>NotFound</Code></Error>", "NotFound"),
                                            (b"404 page not found\n", "")], ids=["another-code", "no-xml"])
def test_a_404_whose_code_is_not_no_such_key_is_no_missing_key(body: bytes, code: str) -> None:
    # Something in front of the endpoint, or an endpoint that is not S3, can answer 404 for a
    # key that holds an object.
    http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404, content=body)))
    client = s3.S3(http, "http://s3.test:7070", "fylgja-test", "AKIDEXAMPLE", "fixture-secret-not-a-credential")
    with pytest.raises(s3.S3Error) as error:
        client.get("k")
    assert not isinstance(error.value, s3.NoSuchKey)
    assert (error.value.status, error.value.code) == (404, code)
    assert str(error.value).startswith(f"GET k: the endpoint answered 404 {code}".rstrip())


def test_a_listing_pages_with_start_after_on_the_first_page_alone() -> None:
    fake = FakeS3()
    client = fake.client()
    fake.page = 2
    for i in range(7):
        client.put(f"p/{i}", b"x")
    client.put("q/0", b"x")
    assert client.list("p/", "p/1") == [f"p/{i}" for i in range(2, 7)]
    queries = [query_of(r) for r in fake.requests[-3:]]
    assert "start-after" in queries[0] and "continuation-token" not in queries[0]
    for later in queries[1:]:
        assert "continuation-token" in later and "start-after" not in later
    assert all(q["prefix"] == "p/" for q in queries)


def test_a_key_and_a_token_that_need_encoding_are_signed_as_sent() -> None:
    fake = FakeS3()
    client = fake.client()
    fake.page = 1
    keys = ["p/a b+c=é~x.cfg", "p/b b.cfg"]
    for key in keys:
        client.put(key, key.encode())
    assert client.list("p/") == sorted(keys)
    assert any("continuation-token" in query_of(r) for r in fake.requests)
    for key in keys:
        assert client.get(key)[0] == key.encode()


def test_a_skewed_clock_is_named() -> None:
    fake = FakeS3()
    behind = fake.client(now=lambda: datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=16))
    with pytest.raises(s3.S3Error) as error:
        behind.get("k")
    assert "clock" in str(error.value)
    assert error.value.code == "RequestTimeTooSkewed"


def test_a_wrong_secret_is_refused_without_naming_it() -> None:
    fake = FakeS3()
    wrong = "wrong-fixture-secret-not-a-credential"
    client = fake.client(secret_key=wrong)
    with pytest.raises(s3.S3Error) as error:
        client.get("k")
    assert error.value.status == 403
    for text in (str(error.value), repr(client)):
        assert wrong not in text and fake.access_key not in text
    assert "secret_key" not in repr(client)


def test_a_lost_answer_is_an_error_after_one_request() -> None:
    fake = FakeS3()

    def lose(request: httpx.Request) -> None:
        raise httpx.ReadTimeout("lost")

    fake.after = lose
    with pytest.raises(s3.S3Error) as error:
        fake.client().put("k", b"one", if_none_match=True)
    assert error.value.status is None
    assert "k" in fake.objects
    assert len(fake.requests) == 1


def test_a_5xx_is_an_oserror() -> None:
    fake = FakeS3()
    fake.forced = [(503, "SlowDown")]
    with pytest.raises(OSError):
        fake.client().get("k")


def test_both_conditions_at_once_are_a_value_error() -> None:
    with pytest.raises(ValueError):
        FakeS3().client().put("k", b"x", if_none_match=True, if_match='"a"')


def test_close_closes_the_client_and_twice_is_harmless() -> None:
    client = FakeS3().client()
    client.close()
    client.close()
    with pytest.raises(RuntimeError):
        client.get("k")


@contextlib.contextmanager
def listening() -> Iterator[tuple[str, list[str]]]:
    """An HTTP server on a free port of 127.0.0.1 that answers every GET `404 NoSuchKey`: its
    URL, and the request line of each request it was sent."""
    lines: list[str] = []

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            lines.append(self.requestline)
            body = b"<Error><Code>NoSuchKey</Code></Error>"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            """Nothing on stderr."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", lines
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_connect_takes_no_proxy_from_the_environment_and_close_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    with listening() as (endpoint, reached), listening() as (proxy, proxied):
        for name in ("http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.setenv(name, proxy)
            monkeypatch.setenv(name.upper(), proxy)
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
        client = s3.S3.connect(endpoint, "fylgja-test", "AKIDEXAMPLE", "fixture-secret-not-a-credential")
        with pytest.raises(s3.NoSuchKey):
            client.get("k")
        client.close()
        with pytest.raises(RuntimeError):  # the client is closed: no request is sent
            client.get("k")
    assert (reached, proxied) == (["GET /fylgja-test/k HTTP/1.1"], [])


@pytest.mark.parametrize(("content", "raised"), [(None, FileNotFoundError), (b"no certificate\n", ssl.SSLError)],
                         ids=["missing", "no-bundle"])
def test_a_ca_that_cannot_be_read_is_an_oserror_at_connect(
    tmp_path: Path, content: bytes | None, raised: type[OSError]
) -> None:
    ca = tmp_path / "ca.pem"
    if content is not None:
        ca.write_bytes(content)
    with pytest.raises(OSError) as error:
        s3.S3.connect("https://s3.example.internal", "fylgja-test", "AKIDEXAMPLE", "fixture-secret-not-a-credential",
                      ca=ca)
    assert type(error.value) is raised


def test_a_redirect_is_an_error_after_one_request() -> None:
    fake = FakeS3()
    fake.forced = [(301, "PermanentRedirect")]
    with pytest.raises(s3.S3Error) as error:
        fake.client().get("k")
    assert error.value.status == 301
    assert "301 PermanentRedirect" in str(error.value)
    assert len(fake.requests) == 1


def test_a_request_error_that_is_no_transport_error_is_an_s3_error() -> None:
    fake = FakeS3()

    def garble(request: httpx.Request) -> None:
        raise httpx.DecodingError("garbled")

    fake.before = garble
    with pytest.raises(s3.S3Error) as error:
        fake.client().get("k")
    assert error.value.status is None
    assert "DecodingError" in str(error.value)
