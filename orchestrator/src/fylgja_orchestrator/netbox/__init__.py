"""The example's NetBox change source (D-085, D-097): the rehearsal library's seam answered by NetBox, a change found
as a branch by its name, its stages `main`, its marks and its head, `main` and the head read through the reader
(D-095) and a mark's blueprint read back from the core, and the report filed as one journal entry on the branch.

It imports the reader, the core and, of the library, the seam and the report alone, never the example's edge or the
Infrahub source; httpx is its transport's alone. The source is `source.NetBoxSource`, over its own transport,
`transport.Transport`; its rules are the `RULE_*` constants, catalogued in `orchestrator/rules.md`.
"""

from fylgja_orchestrator.netbox.source import (
    HEAD,
    KIND,
    LABEL,
    MAIN,
    MARK_PREFIX,
    MOVED_READS,
    READY,
    RULE_MAIN_GAINED,
    RULE_MARK_DUPLICATE,
    RULE_MARK_MALFORMED,
    RULE_MARK_SCOPE,
    RULE_MARK_UNHELD,
    SEVERITY,
    TAG,
    Mark,
    Marked,
    NetBoxSource,
    NoChange,
    Pin,
    Unready,
    mark_text,
    marks_of,
    spaced,
    stages_of,
)
from fylgja_orchestrator.netbox.transport import REFUSED, SourceError, Transport

__all__ = [
    "HEAD",
    "KIND",
    "LABEL",
    "MAIN",
    "MARK_PREFIX",
    "MOVED_READS",
    "READY",
    "REFUSED",
    "RULE_MAIN_GAINED",
    "RULE_MARK_DUPLICATE",
    "RULE_MARK_MALFORMED",
    "RULE_MARK_SCOPE",
    "RULE_MARK_UNHELD",
    "SEVERITY",
    "TAG",
    "Mark",
    "Marked",
    "NetBoxSource",
    "NoChange",
    "Pin",
    "SourceError",
    "Transport",
    "Unready",
    "mark_text",
    "marks_of",
    "spaced",
    "stages_of",
]
