"""Writes `sigv4.json`, the SigV4 signer's known answers, from botocore's own signer.

The core signs its own S3 requests (D-061) and botocore is never a dependency, so this
script runs once, in a throwaway virtual environment outside the tree, and its output is
committed. `sigv4.json` is never edited by hand; regenerate it with:

    python3 -m venv "$(mktemp -d)/venv"            # note the directory it prints or keep it
    <venv>/bin/pip install botocore && <venv>/bin/python testdata/s3/generate.py > testdata/s3/sigv4.json

It imports nothing of `fylgja_core`.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
from typing import Any

import botocore
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.utils import percent_encode

ACCESS_KEY = "AKIDEXAMPLE"
SECRET_KEY = "fixture-secret-not-a-credential"
REGION = "us-east-1"

LOCAL = "http://127.0.0.1:7070"
TLS = "https://s3.example.internal:9000"
DEFAULT = "https://s3.example.internal:443"
BUCKET = "fylgja"
RUN = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
ETAG = {"if-match": '"0123456789abcdef0123456789abcdef"'}
LISTING = {
    "list-type": "2",
    "max-keys": "1000",
    "prefix": f"p/events/{RUN}/",
    "start-after": f"p/events/{RUN}/0000000005.json",
}

# name, method, endpoint, key, query, headers, body
CASES: list[tuple[str, str, str, str, dict[str, str] | None, dict[str, str], str]] = [
    ("put-create", "PUT", LOCAL, "twins/a.json", None, {"if-none-match": "*"}, '{"rev":1}'),
    ("put-replace", "PUT", TLS, "p/twins/a.json", None, ETAG, '{"rev":2}'),
    ("put-empty", "PUT", TLS, "p/empty", None, {}, ""),
    ("get", "GET", TLS, f"p/runs/{RUN}.json", None, {}, ""),
    ("delete", "DELETE", TLS, "p/twins/a.json", None, ETAG, ""),
    ("key-encoded", "PUT", TLS, f"p/bundles/{'a' * 64}/configs/a b+c=é~x.cfg", None, {}, "x"),
    ("list-first", "GET", TLS, "", LISTING, {}, ""),
    (
        "list-next",
        "GET",
        TLS,
        "",
        {
            **{k: v for k, v in LISTING.items() if k != "start-after"},
            "continuation-token": "+/=abc+/=",
        },
        {},
        "",
    ),
    ("default-port", "GET", DEFAULT, "p/twins/a.json", None, {}, ""),
]


def url_for(endpoint: str, key: str, query: dict[str, str] | None) -> str:
    path = f"/{BUCKET}" + (f"/{percent_encode(key, safe='/~')}" if key else "")
    url = endpoint + path
    if query:
        url += "?" + "&".join(
            f"{percent_encode(k, safe='~')}={percent_encode(v, safe='~')}"
            for k, v in sorted(query.items())
        )
    return url


def case(spec: tuple[str, str, str, str, dict[str, str] | None, dict[str, str], str]) -> dict[str, Any]:
    name, method, endpoint, key, query, headers, body = spec
    url = url_for(endpoint, key, query)
    data = body.encode()
    request = AWSRequest(method=method, url=url, headers=dict(headers), data=data)
    request.headers["x-amz-content-sha256"] = hashlib.sha256(data).hexdigest()
    S3SigV4Auth(Credentials(ACCESS_KEY, SECRET_KEY), "s3", REGION).add_auth(request)
    return {
        "name": name,
        "method": method,
        "endpoint": endpoint,
        "bucket": BUCKET,
        "key": key,
        "query": query,
        "headers": headers,
        "body": body,
        "at": request.context["timestamp"],
        "url": url,
        "authorization": request.headers["Authorization"],
    }


def main() -> None:
    document = {
        "source": {
            "signer": "botocore.auth.S3SigV4Auth",
            "encoder": "botocore.utils.percent_encode",
            "botocore": botocore.__version__,
            "python": platform.python_version(),
            "generated": datetime.date.today().isoformat(),
            "by": "testdata/s3/generate.py",
        },
        "access_key": ACCESS_KEY,
        "secret_key": SECRET_KEY,
        "region": REGION,
        "cases": [case(spec) for spec in CASES],
    }
    print(json.dumps(document, sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
