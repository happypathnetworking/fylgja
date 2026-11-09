"""The server's settings, read from the process environment alone (D-042).

Configuration and credentials come from `FYLGJA_*` variables, never a file the core reads
for itself. A variable that is missing or malformed is refused by name: a message names the
variable, never a value (Constitution X). A variable a driver needs (the registry says which)
is required when it is the driver, and read whenever it is set (D-057).

`FYLGJA_STORE` names a directory, or an object store as `s3://<bucket>[/<prefix>]`, whose
endpoint and keys are `FYLGJA_S3_*` variables read for it alone (D-061). The scheme is read in
any case, and any other value that begins `s3:` is refused, never taken for a directory.

`FYLGJA_LEASE` names the Lease that holds the store for one core (D-062), and `FYLGJA_TLS_CERT`
and `FYLGJA_TLS_KEY` the certificate and key the server serves TLS with, set together or not at
all (D-063). What one setting rules out of another `check` refuses, after each is read alone: an
object store has no directory to lock or to keep a driver's files in, so it takes a Lease and a
driver that needs no directory.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from ipaddress import IPv4Network
from pathlib import Path

from fylgja_core import drivers
from fylgja_core.store import check_file_key

# Rule id. Clients and tests match on it.
RULE_MISSING = "settings.missing"

DEFAULT_LISTEN = "127.0.0.1:7650"
DEFAULT_DRIVER = "containerlab"
DEFAULT_WORKERS = 8
DEFAULT_STEP_WAIT_S = 180
DEFAULT_RESYNC_S = 300
DEFAULT_S3_REGION = "us-east-1"

_S3 = "s3://"
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")  # Versity refuses a name under three characters
_FOR_S3 = "is not set, and FYLGJA_STORE names an object store"
_NOT_AN_ENDPOINT = "is not an http:// or https:// URL of a host and an optional port"

_LABEL = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
"""A DNS-1123 label of at most 63 characters, a namespace's name."""

_SUBDOMAIN = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*")
"""A DNS-1123 subdomain, the name of a Kubernetes object such as a Lease, held to `_NAME_MAX`
characters apart."""
_NAME_MAX = 253


class Misconfigured(Exception):
    """A setting is missing or malformed, or set to what another setting rules out; `variable`
    names it."""

    def __init__(self, variable: str, message: str) -> None:
        self.variable = variable
        self.rule = RULE_MISSING
        super().__init__(f"{variable}: {message}")


@dataclass(frozen=True)
class S3Location:
    """An object store (D-061): a bucket on an S3 endpoint, the prefix its keys are under, and
    what its requests are signed with. Neither key is in its repr or its str."""

    bucket: str
    prefix: str  # no leading or trailing `/`; "" for none
    endpoint: str  # `scheme://host[:port]`, no trailing `/`
    region: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    ca: Path | None  # the bundle an https:// endpoint's certificate is checked against; None, the system's

    def __str__(self) -> str:
        return f"{_S3}{self.bucket}/{self.prefix}" if self.prefix else f"{_S3}{self.bucket}"


@dataclass(frozen=True)
class Settings:
    """What the server runs with."""

    store: Path | S3Location
    listen: tuple[str, int]
    driver: str
    workers: int
    step_wait_s: int
    resync_s: int
    """Seconds between the loop's resyncs, `FYLGJA_RESYNC_S`, each queueing every twin again (D-023)."""
    packages: tuple[Path, ...]
    tokens: Path
    clabernetes_namespace: str | None = None
    """clabernetes' namespace, `FYLGJA_CLABERNETES_NAMESPACE`; required by that driver."""
    pod_cidr: str | None = None
    """The cluster's pod network, `FYLGJA_POD_CIDR`; required by the clabernetes driver."""
    lease: str | None = None
    """The name of the Lease in the core's namespace that holds the store for one core,
    `FYLGJA_LEASE` (D-062); required by an object store."""
    tls: tuple[Path, Path] | None = None
    """The certificate and its key the server serves TLS with, `FYLGJA_TLS_CERT` and
    `FYLGJA_TLS_KEY`, set together or not at all; None, it serves HTTP (D-063)."""


def _required(environ: Mapping[str, str], variable: str, unset: str = "is not set") -> str:
    value = environ.get(variable, "")
    if not value:
        raise Misconfigured(variable, unset)
    return value


def _listen(text: str) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise Misconfigured("FYLGJA_LISTEN", "is not host:port with a port from 1 to 65535")
    return host, int(port)


def _positive_int(variable: str, text: str) -> int:
    """`text`, the value of `variable`, as an integer of 1 or more, written in ASCII digits alone."""
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        raise Misconfigured(variable, "is not an integer of 1 or more")
    return int(text)


def _driver(name: str) -> str:
    if name not in drivers.NAMES:
        raise Misconfigured("FYLGJA_DRIVER", f"is not a driver this build serves: {', '.join(drivers.NAMES)}")
    return name


def _is_prefix(text: str) -> bool:
    """Whether `text` is a prefix of keys: a file key, no segment of it empty, `.` or `..`."""
    try:
        check_file_key(text)
    except ValueError:
        return False
    return True


def _endpoint(text: str) -> str:
    """`scheme://host[:port]`, from an http:// or https:// URL of a host and an optional port, a
    path of `/` dropped. The host is a name or an IPv4 address: one in brackets, an IPv6
    address, is refused, since `s3.sign` signs the host by its name or IPv4 address alone."""
    try:
        url = urllib.parse.urlsplit(text)
        host, port = url.hostname, url.port
    except ValueError:  # an IPv6 address left open, or a port that is no number from 0 to 65535
        raise Misconfigured("FYLGJA_S3_ENDPOINT", _NOT_AN_ENDPOINT) from None
    if (url.scheme not in ("http", "https") or not host or "[" in url.netloc or port == 0
            or url.username is not None or url.password is not None or url.path not in ("", "/") or url.query
            or url.fragment):
        raise Misconfigured("FYLGJA_S3_ENDPOINT", _NOT_AN_ENDPOINT)
    return f"{url.scheme}://{host}" if port is None else f"{url.scheme}://{host}:{port}"


def _s3_location(store: str, environ: Mapping[str, str]) -> S3Location:
    """The object store `store` names (`s3://<bucket>[/<prefix>]`, the scheme in any case, one
    trailing `/` allowed), with its endpoint, keys, region and CA bundle from the `FYLGJA_S3_*`
    variables."""
    scheme, rest = store[: len(_S3)], store[len(_S3) :]
    bucket, slash, prefix = rest.removesuffix("/").partition("/")
    if scheme.lower() != _S3 or not _BUCKET.fullmatch(bucket) or (slash and not _is_prefix(prefix)):
        raise Misconfigured("FYLGJA_STORE", "is not a directory or s3://<bucket>[/<prefix>]")
    ca = environ.get("FYLGJA_S3_CA")
    return S3Location(
        bucket=bucket,
        prefix=prefix,
        endpoint=_endpoint(_required(environ, "FYLGJA_S3_ENDPOINT", _FOR_S3)),
        region=environ.get("FYLGJA_S3_REGION") or DEFAULT_S3_REGION,
        access_key=_required(environ, "FYLGJA_S3_ACCESS_KEY", _FOR_S3),
        secret_key=_required(environ, "FYLGJA_S3_SECRET_KEY", _FOR_S3),
        ca=Path(ca) if ca else None,
    )


def _namespace(text: str) -> str:
    if not _LABEL.fullmatch(text):
        raise Misconfigured("FYLGJA_CLABERNETES_NAMESPACE", "is not a namespace name")
    return text


def _pod_cidr(text: str) -> str:
    try:
        if "/" not in text:  # a bare address reads as one, a /32, and would keep almost no pod out, as in `plan`
            raise ValueError(text)
        return str(IPv4Network(text))
    except ValueError:
        raise Misconfigured("FYLGJA_POD_CIDR", "is not an IPv4 network in CIDR form") from None


def _needed(environ: Mapping[str, str], variable: str, driver: str, read: Callable[[str], str]) -> str | None:
    """The variable a driver needs, read by `read` whenever it is set; None when it is not and
    `driver` does not need it."""
    text = environ.get(variable, "")
    if text:
        return read(text)
    if variable in drivers.needs(driver):
        raise Misconfigured(variable, f"is not set, and FYLGJA_DRIVER={driver} needs it")
    return None


def _lease(text: str) -> str:
    if len(text) > _NAME_MAX or not _SUBDOMAIN.fullmatch(text):
        raise Misconfigured("FYLGJA_LEASE", "is not a Kubernetes object name: lower-case letters, digits, - and .")
    return text


def _tls(environ: Mapping[str, str]) -> tuple[Path, Path] | None:
    """The certificate and key `FYLGJA_TLS_CERT` and `FYLGJA_TLS_KEY` name; None when neither is
    set, and the one not set named when the other is."""
    cert, key = environ.get("FYLGJA_TLS_CERT", ""), environ.get("FYLGJA_TLS_KEY", "")
    if cert and key:
        return Path(cert), Path(key)
    if cert or key:
        unset, other = ("FYLGJA_TLS_KEY", "FYLGJA_TLS_CERT") if cert else ("FYLGJA_TLS_CERT", "FYLGJA_TLS_KEY")
        raise Misconfigured(unset, f"is not set, and {other} is: the two are set together or not at all")
    return None


def check(settings: Settings) -> None:
    """Refuse what one of `settings` rules out of another, `Misconfigured` naming the variable at
    fault. An object store has no directory to lock, so it is held for one core by a Lease alone
    (D-061, D-062), and none to keep a driver's working files in, so it serves no driver that
    needs one (`drivers.needs_directory`). A directory store takes either driver, with or without
    a Lease.

    `from_environ` calls it last, and the server first, before it opens anything."""
    if isinstance(settings.store, S3Location):
        if settings.lease is None:
            raise Misconfigured("FYLGJA_LEASE", "is not set, and an s3:// store is held for one core by a Lease alone")
        if drivers.needs_directory(settings.driver):
            raise Misconfigured("FYLGJA_DRIVER", "names a driver that keeps its files in the store's directory, "
                                                 "and FYLGJA_STORE names none")


def from_environ(environ: Mapping[str, str]) -> Settings:
    """The `Settings` an environment holds, or `Misconfigured` naming the first fault: each
    setting read alone, then what one rules out of another (`check`)."""
    store = _required(environ, "FYLGJA_STORE")
    tokens = _required(environ, "FYLGJA_TOKENS")
    packages = tuple(Path(p) for p in _required(environ, "FYLGJA_PACKAGES").split(":") if p)
    if not packages:
        raise Misconfigured("FYLGJA_PACKAGES", "names no directory")
    listen = _listen(environ.get("FYLGJA_LISTEN") or DEFAULT_LISTEN)
    driver = _driver(environ.get("FYLGJA_DRIVER") or DEFAULT_DRIVER)
    lease = environ.get("FYLGJA_LEASE", "")
    settings = Settings(
        store=_s3_location(store, environ) if store.lower().startswith("s3:") else Path(store),
        listen=listen,
        driver=driver,
        workers=_positive_int("FYLGJA_WORKERS", environ.get("FYLGJA_WORKERS") or str(DEFAULT_WORKERS)),
        step_wait_s=_positive_int("FYLGJA_STEP_WAIT_S", environ.get("FYLGJA_STEP_WAIT_S") or str(DEFAULT_STEP_WAIT_S)),
        resync_s=_positive_int("FYLGJA_RESYNC_S", environ.get("FYLGJA_RESYNC_S") or str(DEFAULT_RESYNC_S)),
        packages=packages,
        tokens=Path(tokens),
        clabernetes_namespace=_needed(environ, "FYLGJA_CLABERNETES_NAMESPACE", driver, _namespace),
        pod_cidr=_needed(environ, "FYLGJA_POD_CIDR", driver, _pod_cidr),
        lease=_lease(lease) if lease else None,
        tls=_tls(environ),
    )
    check(settings)
    return settings
