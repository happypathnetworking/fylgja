"""The edge's settings: the change source a runner or a command opens, and the nine variables of that source, read
once from the environment it is given.

`FYLGJA_ORCHESTRATOR_SOURCE` names the source, `infrahub` or `netbox`, and is `infrahub` where it is unset or empty, so
that a runner set up for Infrahub alone needs no new variable (D-097). The core is reached at `FYLGJA_API_ADDRESS` with
`FYLGJA_API_TOKEN`, and the source at its own address with its own token, Infrahub's `FYLGJA_INFRAHUB_ADDRESS` and
`FYLGJA_INFRAHUB_TOKEN` or NetBox's `FYLGJA_NETBOX_ADDRESS` and `FYLGJA_NETBOX_TOKEN`, each verified against its `_CA`
file where one is named; the stages are read under `FYLGJA_ORCHESTRATOR_SCOPE` with the reader document at
`FYLGJA_ORCHESTRATOR_READER`, and the commands keep their records under `FYLGJA_ORCHESTRATOR_ROOT`. Only the chosen
source's three are read, and the other's are neither required nor judged. A variable set and empty is unset, and only
the CAs may be. The values are taken as given: the client and the source refuse an address, a token or a CA by their
own rules when they are made (`run.opened`), and `refused` judges them by those rules first, for a command and the
runner to name each fault before anything is made.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, bearer, trust

API_ADDRESS = "FYLGJA_API_ADDRESS"
API_TOKEN = "FYLGJA_API_TOKEN"
API_CA = "FYLGJA_API_CA"
INFRAHUB_ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
INFRAHUB_TOKEN = "FYLGJA_INFRAHUB_TOKEN"
INFRAHUB_CA = "FYLGJA_INFRAHUB_CA"
NETBOX_ADDRESS = "FYLGJA_NETBOX_ADDRESS"
NETBOX_TOKEN = "FYLGJA_NETBOX_TOKEN"
NETBOX_CA = "FYLGJA_NETBOX_CA"
SCOPE = "FYLGJA_ORCHESTRATOR_SCOPE"
READER = "FYLGJA_ORCHESTRATOR_READER"
ROOT = "FYLGJA_ORCHESTRATOR_ROOT"
SOURCE = "FYLGJA_ORCHESTRATOR_SOURCE"

SOURCES = ("infrahub", "netbox")
"""The change sources the edge opens; the first where `SOURCE` is unset."""


class Reached(NamedTuple):
    """The three variables a change source is reached by: its address, its token and its CA."""

    address: str
    token: str
    ca: str


OF: Mapping[str, Reached] = {
    "infrahub": Reached(INFRAHUB_ADDRESS, INFRAHUB_TOKEN, INFRAHUB_CA),
    "netbox": Reached(NETBOX_ADDRESS, NETBOX_TOKEN, NETBOX_CA),
}
"""Each source's three, by its name in `SOURCES`."""


class UnknownSource(Exception):
    """`SOURCE` names neither source; its value is never said."""

    def __init__(self) -> None:
        super().__init__(f"{SOURCE} is neither {' nor '.join(SOURCES)}")


def chosen(environ: Mapping[str, str]) -> str:
    """The source `environ` names: `SOURCE`'s value, or the first of `SOURCES` where it is unset or empty. Any other
    value is answered as it is, for `from_env` and `refused` to refuse."""
    return environ.get(SOURCE) or SOURCES[0]


def names(source: str) -> tuple[str, ...]:
    """The nine variables of `source`, in order: the core's three, the source's three, then the scope, the reader
    document and the root; `UnknownSource` for a source that is neither."""
    if source not in OF:
        raise UnknownSource()
    return (API_ADDRESS, API_TOKEN, API_CA, *OF[source], SCOPE, READER, ROOT)


NAMES = names("infrahub")
"""The nine of the Infrahub source, in `names`' order."""

OPTIONAL = (API_CA, INFRAHUB_CA, NETBOX_CA)
"""The three that may be unset: the system's trust is then the one verified against."""


@dataclass(frozen=True)
class Settings:
    """What the edge reads, a field a variable: the source's name, and its own three as `source_address`,
    `source_token` and `source_ca`. Neither token is in its text."""

    api_address: str
    api_token: str = field(repr=False)
    api_ca: Path | None
    source: str
    source_address: str
    source_token: str = field(repr=False)
    source_ca: Path | None
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
    """The settings `environ` holds; `UnknownSource` where it names neither source, and `Unset` naming every required
    variable of the source it names that it does not hold."""
    source = chosen(environ)
    own = names(source)
    missing = tuple(name for name in own if name not in OPTIONAL and not environ.get(name))
    if missing:
        raise Unset(missing)

    def ca(name: str) -> Path | None:
        value = environ.get(name)
        return Path(value) if value else None

    reached = OF[source]
    return Settings(
        api_address=environ[API_ADDRESS],
        api_token=environ[API_TOKEN],
        api_ca=ca(API_CA),
        source=source,
        source_address=environ[reached.address],
        source_token=environ[reached.token],
        source_ca=ca(reached.ca),
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
    NETBOX_ADDRESS: base_url,
    NETBOX_TOKEN: bearer,
    NETBOX_CA: lambda value: trust(Path(value)),
}


def refused(environ: Mapping[str, str]) -> tuple[str, ...]:
    """A line for each variable of the source `environ` names that it leaves unset and a runner cannot do without,
    and for each set that the clients' rules refuse (`InvalidAddress`, `InvalidToken`, `InvalidCA`), in the order of
    that source's `names`, each naming the variable and never its value; the one line of `UnknownSource` where it
    names neither source; none where `from_env` would read every one and the clients take each."""
    try:
        own = names(chosen(environ))
    except UnknownSource as e:
        return (str(e),)
    lines: list[str] = []
    for name in own:
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
