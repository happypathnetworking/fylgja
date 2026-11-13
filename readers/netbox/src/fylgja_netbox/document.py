"""The reader document, netbox-reader 1 (D-095).

NetBox's platform names no platform package, and the probes are a configuration context of the installation's own
naming, so each read is given both as a document: the pairs of manufacturer and platform with the package of each,
and the name of the context that declares the probes, or None where none are read. It holds no address and no
credential (D-042): those are `FYLGJA_NETBOX_ADDRESS` and `FYLGJA_NETBOX_TOKEN`.

`validate` reports every problem in one pass (Constitution III): the version first, then the schema
(formats/netbox-reader-1.schema.json), then the rule the schema cannot state, that a pair of manufacturer and platform
is in one row; `decode` builds the `ReaderDocument` or raises `Rejected`; `load` reads a YAML or JSON file and decodes
it, a `Rejected` naming the file. The format is the reader's, carried by its wheel and read through the core's
registry (D-084).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

PACKAGE = "fylgja_netbox"
FORMAT = "netbox-reader-1"
VERSION = "1"

# Rule ids. Callers and tests match on them (rules.md).
RULE_VERSION = "reader.version.unsupported"
RULE_INVALID = "reader.invalid"
RULE_PLATFORM_DUPLICATE = "reader.platform.duplicate"


@dataclass(frozen=True)
class Match:
    """One row of the document's platforms: a device whose platform's manufacturer and platform, in NetBox, are this
    pair, compared exactly, letter case and spacing included, is the platform package `package`."""

    manufacturer: str
    platform: str
    package: str


@dataclass(frozen=True)
class ReaderDocument:
    """A reader document as a model: its platforms in the document's order, and the name of the configuration context
    that declares the probes, None where no probe is read. Its version is not kept: the model is version 1's."""

    platforms: tuple[Match, ...]
    probes: str | None

    def package(self, manufacturer: str, platform: str) -> str | None:
        """The platform package of the pair, compared exactly; None where no row holds it."""
        for match in self.platforms:
            if (match.manufacturer, match.platform) == (manufacturer, platform):
                return match.package
        return None


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a reader document, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "reader_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    problems = documents.schema_problems(FORMAT, doc, RULE_INVALID, PACKAGE)
    if problems:
        return problems
    first: dict[tuple[str, str], int] = {}
    for i, row in enumerate(doc["platforms"]):
        pair = (row["manufacturer"], row["platform"])
        if pair in first:
            detail = (
                f"manufacturer {pair[0]!r} and platform {pair[1]!r} are /platforms/{first[pair]}'s pair too: "
                "a pair is in one row, and names one package"
            )
            problems.append(Problem(f"/platforms/{i}", RULE_PLATFORM_DUPLICATE, detail))
        first.setdefault(pair, i)
    return sorted(problems)


def decode(doc: Any) -> ReaderDocument:
    """The `ReaderDocument` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    matches = tuple(Match(row["manufacturer"], row["platform"], row["package"]) for row in doc["platforms"])
    return ReaderDocument(matches, doc["probes"])


def load(path: Path) -> ReaderDocument:
    """The `ReaderDocument` in a YAML or JSON file, or `Rejected` naming the file."""
    return documents.load(path, RULE_INVALID, decode)
