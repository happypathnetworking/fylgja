"""The server's settings, read from the process environment alone (D-042).

Configuration and credentials come from `FYLGJA_*` variables, never a file the core reads
for itself. A variable that is missing or malformed is refused by name: a message names the
variable, never a value (Constitution X).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Rule id. Clients and tests match on it.
RULE_MISSING = "config.missing"

DEFAULT_LISTEN = "127.0.0.1:7650"
DEFAULT_DRIVER = "containerlab"
DEFAULT_WORKERS = 4


class Misconfigured(Exception):
    """A setting is missing or malformed; `variable` names it."""

    def __init__(self, variable: str, message: str) -> None:
        self.variable = variable
        super().__init__(f"{variable}: {message}")


@dataclass(frozen=True)
class Settings:
    """What the server runs with."""

    store: Path
    listen: tuple[str, int]
    driver: str
    workers: int
    packages: tuple[Path, ...]
    tokens: Path


def _required(environ: Mapping[str, str], variable: str) -> str:
    value = environ.get(variable, "")
    if not value:
        raise Misconfigured(variable, "is not set")
    return value


def _listen(text: str) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise Misconfigured("FYLGJA_LISTEN", "is not host:port with a port from 1 to 65535")
    return host, int(port)


def _workers(text: str) -> int:
    if not text.isascii() or not text.isdigit() or int(text) < 1:
        raise Misconfigured("FYLGJA_WORKERS", "is not an integer of 1 or more")
    return int(text)


def from_environ(environ: Mapping[str, str]) -> Settings:
    """The `Settings` an environment holds, or `Misconfigured` naming the first fault."""
    store = _required(environ, "FYLGJA_STORE")
    tokens = _required(environ, "FYLGJA_TOKENS")
    packages = tuple(Path(p) for p in _required(environ, "FYLGJA_PACKAGES").split(":") if p)
    if not packages:
        raise Misconfigured("FYLGJA_PACKAGES", "names no directory")
    return Settings(
        store=Path(store),
        listen=_listen(environ.get("FYLGJA_LISTEN") or DEFAULT_LISTEN),
        driver=environ.get("FYLGJA_DRIVER") or DEFAULT_DRIVER,
        workers=_workers(environ.get("FYLGJA_WORKERS") or str(DEFAULT_WORKERS)),
        packages=packages,
        tokens=Path(tokens),
    )
