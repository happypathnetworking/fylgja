"""The object store's S3 client: AWS Signature Version 4 and four calls, written here (D-061).

The store makes four S3 calls (D-064) and needs none of an S3 library's reach, so the
signer is a pure function held to botocore's answers by `testdata/s3/sigv4.json`.

What is signed: `host`, `x-amz-date`, `x-amz-content-sha256` and every header the caller
passes, lower-cased and sorted. The payload hash is always the SHA-256 of the body sent,
never `UNSIGNED-PAYLOAD`: the request crosses the cluster network without TLS. `host`
carries the port unless it is the scheme's default, as httpx sends it. A URL is signed
exactly as it is sent, so `request_url` encodes once and `sign` takes the URL as given.

The four calls are `get`, `put`, `delete` and `list` of `S3`. An answer is read three ways:
a 2xx is the answer; a refused condition (412, or the 409 a racing write answers) is
`PreconditionFailed`; anything else is `S3Error`, an `OSError`, so the loop backs off on it
as on a disk failure. An error's text holds the method, the key, the status and the
endpoint's `Code`, never its `Message`, a header or a credential. No call is repeated here.
"""

from __future__ import annotations

import builtins
import datetime
import hashlib
import hmac
import ssl
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

_ALGORITHM = "AWS4-HMAC-SHA256"
_DEFAULT_PORTS = {"http": 80, "https": 443}

TIMEOUT_S = 10.0
SKEW_CODES = frozenset({"RequestTimeTooSkewed"})


def request_url(
    endpoint: str, bucket: str, key: str = "", query: Mapping[str, str] | None = None
) -> str:
    """The path-style URL: a key encoded segment by segment, a query sorted by name.

    Both keep `A-Za-z0-9-_.~`; the key keeps its `/` and the query encodes it. A space is
    `%20`, never `+`. `endpoint` has no trailing slash.
    """
    url = f"{endpoint}/{quote(bucket, safe='~')}"
    if key:
        url += "/" + quote(key, safe="/~")
    if query:
        url += "?" + "&".join(
            f"{quote(name, safe='~')}={quote(value, safe='~')}"
            for name, value in sorted(query.items())
        )
    return url


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    at: datetime.datetime,
) -> dict[str, str]:
    """The headers to send: `headers` lower-cased, plus the three SigV4 adds.

    `host` is signed and not returned, httpx sends it. `url` is taken as already encoded, and
    its host is a name or an IPv4 address: an IPv6 one would be signed without the brackets
    httpx sends. `at` must be timezone-aware; it is converted to UTC.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(parts.scheme):
        host = f"{host}:{parts.port}"

    moment = at.astimezone(datetime.UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    payload = hashlib.sha256(body).hexdigest()

    out = {name.lower(): value for name, value in headers.items()}
    out["x-amz-date"] = stamp
    out["x-amz-content-sha256"] = payload

    canonical = sorted(
        (name, " ".join(value.split())) for name, value in {**out, "host": host}.items()
    )
    signed_headers = ";".join(name for name, _ in canonical)
    pairs = sorted(
        tuple(pair.partition("=")[::2]) for pair in parts.query.split("&") if pair
    )
    request = "\n".join(
        [
            method,
            parts.path or "/",
            "&".join(f"{name}={value}" for name, value in pairs),
            "".join(f"{name}:{value}\n" for name, value in canonical),
            signed_headers,
            payload,
        ]
    )
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(
        [_ALGORITHM, stamp, scope, hashlib.sha256(request.encode()).hexdigest()]
    )
    derived = f"AWS4{secret_key}".encode()
    for piece in (day, region, "s3", "aws4_request"):
        derived = _hmac(derived, piece)
    signature = hmac.new(derived, to_sign.encode(), hashlib.sha256).hexdigest()
    out["authorization"] = (
        f"{_ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out


class S3Error(OSError):
    """The endpoint refused a call, or could not be reached (`status` None, `code` "")."""

    def __init__(self, message: str, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class NoSuchKey(S3Error):
    """The key holds no object: a 404 whose code is `NoSuchKey`. Any other 404 is an `S3Error`,
    since a 404 from something that is not the endpoint says nothing of the key."""


class PreconditionFailed(S3Error):
    """A condition was refused. `settled` is True for a 412: the key holds an object, or
    another version of it. A 409 is False: another write to the key was in flight, and
    its outcome is unknown."""

    def __init__(self, message: str, status: int | None = None, code: str = "", *, settled: bool = True) -> None:
        super().__init__(message, status, code)
        self.settled = settled


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _local(tag: str) -> str:
    return tag.rpartition("}")[2]


def _error_code(body: bytes) -> str:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return ""
    for element in root.iter():
        if _local(element.tag) == "Code":
            return (element.text or "").strip()
    return ""


class S3:
    """One bucket on one endpoint, path-style. An ETag is a token: kept as the endpoint
    gave it, quotes included, and sent back the same."""

    def __init__(
        self,
        http: httpx.Client,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        *,
        now: Callable[[], datetime.datetime] = _utc_now,
        page: int = 1000,
    ) -> None:
        self._http = http
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._now = now
        self._page = page

    @classmethod
    def connect(
        cls,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        ca: Path | None = None,
    ) -> S3:
        """A client over a connection pool of its own. Its trust is built here: the bundle `ca`,
        or the system's when `ca` is None, never httpx's own. httpx reads nothing from the
        environment, so no proxy variable is honoured, as in the package's other clients. A `ca`
        that cannot be read raises as `ssl` does, an `OSError`: `FileNotFoundError` when it does
        not exist, `ssl.SSLError` when it holds no certificate."""
        trust = ssl.create_default_context(cafile=str(ca) if ca else None)
        http = httpx.Client(timeout=TIMEOUT_S, verify=trust, trust_env=False)
        return cls(http, endpoint, bucket, access_key, secret_key, region)

    def __repr__(self) -> str:
        return f"S3(endpoint={self._endpoint!r}, bucket={self._bucket!r})"

    def close(self) -> None:
        self._http.close()

    def _send(
        self,
        method: str,
        label: str,
        key: str = "",
        query: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> httpx.Response:
        """One request, signed as sent; the answer if it is 2xx, else the matching error."""
        url = request_url(self._endpoint, self._bucket, key, query)
        signed = sign(
            method,
            url,
            headers or {},
            body,
            access_key=self._access_key,
            secret_key=self._secret_key,
            region=self._region,
            at=self._now(),
        )
        try:
            response = self._http.request(method, url, headers=signed, content=body)
        except httpx.RequestError as error:
            raise S3Error(f"{method} {label}: the endpoint could not be reached ({type(error).__name__})") from error
        status = response.status_code
        if 200 <= status < 300:
            return response
        code = _error_code(response.content)
        if status == 412 or (status == 409 and code == "ConditionalRequestConflict"):
            raise PreconditionFailed(
                f"{method} {label}: the endpoint answered {status} {code}",
                status,
                code,
                settled=status == 412,
            )
        if code in SKEW_CODES:
            raise S3Error(
                f"{method} {label}: the endpoint refused the request's time ({code}): "
                "this host's clock and the endpoint's differ by more than it allows",
                status,
                code,
            )
        message = f"{method} {label}: the endpoint answered {status} {code}"
        if status == 404 and code == "NoSuchKey":
            raise NoSuchKey(message, status, code)
        raise S3Error(message, status, code)

    @staticmethod
    def _etag(method: str, label: str, response: httpx.Response) -> str:
        etag: str | None = response.headers.get("etag")
        if etag is None:
            raise S3Error(
                f"{method} {label}: the endpoint answered {response.status_code} with no ETag",
                response.status_code,
            )
        return etag

    def get(self, key: str) -> tuple[bytes, str]:
        response = self._send("GET", key, key)
        return response.content, self._etag("GET", key, response)

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_none_match: bool = False,
        if_match: str | None = None,
    ) -> str:
        if if_none_match and if_match is not None:
            raise ValueError("a put takes if_none_match or if_match, not both")
        headers: dict[str, str] = {}
        if if_none_match:
            headers["if-none-match"] = "*"
        if if_match is not None:
            headers["if-match"] = if_match
        response = self._send("PUT", key, key, headers=headers, body=body)
        return self._etag("PUT", key, response)

    def delete(self, key: str, *, if_match: str | None = None) -> None:
        headers = {"if-match": if_match} if if_match is not None else {}
        self._send("DELETE", key, key, headers=headers)

    def list(self, prefix: str, start_after: str = "") -> builtins.list[str]:
        """Every key under `prefix` after `start_after`, in the endpoint's order.

        `start-after` goes on the first page alone; later pages carry the token.
        """
        keys: builtins.list[str] = []
        token = ""
        while True:
            query = {"list-type": "2", "max-keys": str(self._page), "prefix": prefix}
            if token:
                query["continuation-token"] = token
            elif start_after:
                query["start-after"] = start_after
            response = self._send("GET", prefix, query=query)
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as error:
                raise S3Error(
                    f"GET {prefix}: the endpoint answered {response.status_code} with a listing that is not XML",
                    response.status_code,
                ) from error
            truncated, token = False, ""
            for element in root.iter():
                name = _local(element.tag)
                if name == "Key":
                    keys.append(element.text or "")
                elif name == "IsTruncated":
                    truncated = (element.text or "").strip() == "true"
                elif name == "NextContinuationToken":
                    token = element.text or ""
            if not truncated:
                return keys
            if not token:
                raise S3Error(
                    f"GET {prefix}: the endpoint truncated a listing with no token",
                    response.status_code,
                )
