"""The edge's settings: the nine variables a runner or a command reads, once, from the environment it is given.

The core is reached at `FYLGJA_API_ADDRESS` with `FYLGJA_API_TOKEN`, and Infrahub at `FYLGJA_INFRAHUB_ADDRESS` with
`FYLGJA_INFRAHUB_TOKEN`, each verified against its `_CA` file where one is named; the stages are read under
`FYLGJA_ORCHESTRATOR_SCOPE` with the reader document at `FYLGJA_ORCHESTRATOR_READER`, and the commands keep their
records under `FYLGJA_ORCHESTRATOR_ROOT`. A variable set and empty is unset, and only the two CAs may be. The values
are taken as given: the client and the source refuse an address, a token or a CA by their own rules when they are
made (`run.opened`), and `refused` judges them by those rules first, for a command and the runner to name each fault
before anything is made.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, bearer, trust

API_ADDRESS = "FYLGJA_API_ADDRESS"
API_TOKEN = "FYLGJA_API_TOKEN"
API_CA = "FYLGJA_API_CA"
INFRAHUB_ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
INFRAHUB_TOKEN = "FYLGJA_INFRAHUB_TOKEN"
INFRAHUB_CA = "FYLGJA_INFRAHUB_CA"
SCOPE = "FYLGJA_ORCHESTRATOR_SCOPE"
READER = "FYLGJA_ORCHESTRATOR_READER"
ROOT = "FYLGJA_ORCHESTRATOR_ROOT"

NAMES = (API_ADDRESS, API_TOKEN, API_CA, INFRAHUB_ADDRESS, INFRAHUB_TOKEN, INFRAHUB_CA, SCOPE, READER, ROOT)
"""The nine, in plan 0's order."""

OPTIONAL = (API_CA, INFRAHUB_CA)
"""The two that may be unset: the system's trust is then the one verified against."""


@dataclass(frozen=True)
class Settings:
    """What the edge reads, a field a variable. Neither token is in its text."""

    api_address: str
    api_token: str = field(repr=False)
    api_ca: Path | None
    infrahub_address: str
    infrahub_token: str = field(repr=False)
    infrahub_ca: Path | None
    scope: str
    reader: Path
    root: Path


class Unset(Exception):
    """Variables a runner cannot do without are unset: `names`, every one of them in plan 0's order, and never a
    value."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names
        super().__init__(f"{', '.join(names)} {'is' if len(names) == 1 else 'are'} not set")


def from_env(environ: Mapping[str, str]) -> Settings:
    """The settings `environ` holds; `Unset` naming every required variable it does not."""
    missing = tuple(name for name in NAMES if name not in OPTIONAL and not environ.get(name))
    if missing:
        raise Unset(missing)

    def ca(name: str) -> Path | None:
        value = environ.get(name)
        return Path(value) if value else None

    return Settings(
        api_address=environ[API_ADDRESS],
        api_token=environ[API_TOKEN],
        api_ca=ca(API_CA),
        infrahub_address=environ[INFRAHUB_ADDRESS],
        infrahub_token=environ[INFRAHUB_TOKEN],
        infrahub_ca=ca(INFRAHUB_CA),
        scope=environ[SCOPE],
        reader=Path(environ[READER]),
        root=Path(environ[ROOT]),
    )


# The variables the clients' rules judge, each by the rule that raises its predicate.
_RULES: dict[str, Callable[[str], object]] = {
    API_ADDRESS: base_url,
    API_TOKEN: bearer,
    API_CA: lambda value: trust(Path(value)),
    INFRAHUB_ADDRESS: base_url,
    INFRAHUB_TOKEN: bearer,
    INFRAHUB_CA: lambda value: trust(Path(value)),
}


def refused(environ: Mapping[str, str]) -> tuple[str, ...]:
    """A line for each variable `environ` leaves unset that a runner cannot do without, and for each set that the
    clients' rules refuse (`InvalidAddress`, `InvalidToken`, `InvalidCA`), in `NAMES`' order, each naming the variable
    and never its value; none where `from_env` would read every one and the clients take each."""
    lines: list[str] = []
    for name in NAMES:
        value = environ.get(name)
        if not value:
            if name not in OPTIONAL:
                lines.append(f"{name} is not set")
        elif name in _RULES:
            try:
                _RULES[name](value)
            except (InvalidAddress, InvalidToken, InvalidCA) as e:
                lines.append(f"{name} {e}")
    return tuple(lines)
