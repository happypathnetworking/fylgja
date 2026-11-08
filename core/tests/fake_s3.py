"""A fake S3 endpoint for the pure tier: one bucket, the conditions enforced, every
request's signature checked (D-061).

It answers as Versity S3 Gateway v1.10.0 was read to (`design/verified-facts.md`), and the
live tier holds its answers at the edges the store meets to the gateway's
(`tests/live/test_object_store_live.py`). One bound is assumed, not read: a request whose
`x-amz-date` is more than 900 s from `now()` is `403 RequestTimeTooSkewed` (the gateway was
read refusing one 20 minutes behind).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, unquote
from xml.sax.saxutils import escape

import httpx

from fylgja_core import s3

SKEW_S = 900
TOKEN_PREFIX = "+/="
S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _error(status: int, code: str) -> httpx.Response:
    body = f"<?xml version='1.0'?><Error><Code>{code}</Code><Message>fake</Message></Error>"
    return httpx.Response(status, content=body.encode())


class FakeS3:
    def __init__(
        self,
        bucket: str = "fylgja-test",
        access_key: str = "AKIDEXAMPLE",
        secret_key: str = "fixture-secret-not-a-credential",
    ) -> None:
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.page = 1000
        self.ignore: set[str] = set()
        self.forced: list[tuple[int, str]] = []
        self.before: Callable[[httpx.Request], None] | None = None
        self.after: Callable[[httpx.Request], None] | None = None
        self.now: Callable[[], datetime.datetime] = _utc_now
        self._lock = threading.Lock()

    def etag(self, key: str) -> str:
        return '"' + hashlib.md5(self.objects[key]).hexdigest() + '"'

    def client(self, **overrides: Any) -> s3.S3:
        args: dict[str, Any] = {
            "endpoint": "http://s3.test:7070",
            "bucket": self.bucket,
            "access_key": self.access_key,
            "secret_key": self.secret_key,
        }
        for name in ("bucket", "access_key", "secret_key"):
            if name in overrides:
                args[name] = overrides.pop(name)
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return s3.S3(
            http,
            args["endpoint"],
            args["bucket"],
            args["access_key"],
            args["secret_key"],
            **overrides,
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.before is not None:
            self.before(request)
        with self._lock:
            self.requests.append(request)
            response = _error(*self.forced.pop(0)) if self.forced else self._handle(request)
        if self.after is not None:
            self.after(request)
        return response

    def _signature_ok(self, request: httpx.Request, authorization: str) -> bool:
        fields = dict(part.strip().partition("=")[::2] for part in authorization.partition(" ")[2].split(","))
        signed = fields.get("SignedHeaders", "").split(";")
        sent = {name.lower() for name in request.headers}
        required = {"host", "x-amz-date", "x-amz-content-sha256"} | {
            name for name in sent if name in ("if-match", "if-none-match")
        }
        if not required <= set(signed):
            return False
        body = request.content
        if request.headers.get("x-amz-content-sha256") != hashlib.sha256(body).hexdigest():
            return False
        try:
            at = datetime.datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=datetime.UTC
            )
        except KeyError, ValueError:
            return False
        url = f"{request.url.scheme}://{request.url.netloc.decode()}{request.url.raw_path.decode()}"
        extra = {
            name: request.headers[name] for name in signed if name not in ("host", "x-amz-date", "x-amz-content-sha256")
        }
        expected = s3.sign(
            request.method,
            url,
            extra,
            body,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region="us-east-1",
            at=at,
        )
        return expected["authorization"] == authorization

    def _handle(self, request: httpx.Request) -> httpx.Response:
        authorization = request.headers.get("authorization")
        if authorization is None:
            return _error(403, "AccessDenied")
        try:
            stamp = datetime.datetime.strptime(request.headers.get("x-amz-date", ""), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=datetime.UTC
            )
        except ValueError:
            return _error(403, "SignatureDoesNotMatch")
        if abs((self.now() - stamp).total_seconds()) > SKEW_S:
            return _error(403, "RequestTimeTooSkewed")
        if not self._signature_ok(request, authorization):
            return _error(403, "SignatureDoesNotMatch")

        bucket, _, key = unquote(request.url.raw_path.decode().partition("?")[0]).lstrip("/").partition("/")
        if bucket != self.bucket:
            return _error(404, "NoSuchBucket")
        method = request.method
        if method == "GET" and not key:
            return self._list(request)
        if method == "GET":
            if key not in self.objects:
                return _error(404, "NoSuchKey")
            return httpx.Response(200, content=self.objects[key], headers={"ETag": self.etag(key)})
        if method == "PUT":
            return self._put(request, key)
        if method == "DELETE":
            return self._delete(request, key)
        return _error(405, "MethodNotAllowed")

    @staticmethod
    def _same(sent: str, held: str) -> bool:
        return sent.strip('"') == held.strip('"')

    def _put(self, request: httpx.Request, key: str) -> httpx.Response:
        none_match = request.headers.get("if-none-match")
        if_match = request.headers.get("if-match")
        if none_match == "*" and "if-none-match" not in self.ignore and key in self.objects:
            return _error(412, "PreconditionFailed")
        if if_match is not None and "if-match-put" not in self.ignore:
            if key not in self.objects:
                return _error(404, "NoSuchKey")
            if not self._same(if_match, self.etag(key)):
                return _error(412, "PreconditionFailed")
        self.objects[key] = request.content
        return httpx.Response(200, headers={"ETag": self.etag(key)})

    def _delete(self, request: httpx.Request, key: str) -> httpx.Response:
        if_match = request.headers.get("if-match")
        if if_match is not None and "if-match-delete" not in self.ignore:
            if key not in self.objects:
                return _error(404, "NoSuchKey")
            if not self._same(if_match, self.etag(key)):
                return _error(412, "PreconditionFailed")
        self.objects.pop(key, None)
        return httpx.Response(204)

    def _list(self, request: httpx.Request) -> httpx.Response:
        query = dict(parse_qsl(request.url.query.decode(), keep_blank_values=True))
        if "start-after" in query and "continuation-token" in query:
            return _error(400, "InvalidArgument")
        prefix = query.get("prefix", "")
        after = query.get("start-after", "")
        if "continuation-token" in query:
            token = query["continuation-token"]
            if not token.startswith(TOKEN_PREFIX):
                return _error(400, "InvalidArgument")
            after = base64.b64decode(token[len(TOKEN_PREFIX) :]).decode()
        size = min(self.page, int(query.get("max-keys", self.page)))
        keys = sorted(k for k in self.objects if k.startswith(prefix) and k > after)
        shown, truncated = keys[:size], len(keys) > size
        contents = "".join(f"<Contents><Key>{escape(k)}</Key></Contents>" for k in shown)
        more = ""
        if truncated:
            token = TOKEN_PREFIX + base64.b64encode(shown[-1].encode()).decode()
            more = f"<NextContinuationToken>{escape(token)}</NextContinuationToken>"
        body = (
            f"<?xml version='1.0'?><ListBucketResult xmlns='{S3_NS}'>"
            f"<Name>{self.bucket}</Name><Prefix>{escape(prefix)}</Prefix>"
            f"<KeyCount>{len(shown)}</KeyCount><MaxKeys>{size}</MaxKeys>"
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
            f"{more}{contents}</ListBucketResult>"
        )
        return httpx.Response(200, content=body.encode())
