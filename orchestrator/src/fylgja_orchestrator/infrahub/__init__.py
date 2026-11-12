"""The example's Infrahub change source (D-085, D-088): the rehearsal library's seam answered by Infrahub, a proposed
change found by its branch, its stages read through the reader (D-082) and its report posted as a thread.

It imports the reader, the core, httpx and, of the library, the seam and the report alone, never the example's edge.
The source is `source.InfrahubSource`, over its own transport, `transport.Transport`, which speaks the six GraphQL
documents under `queries/`; its rules are the `RULE_*` constants, catalogued in `orchestrator/rules.md`.
"""

from fylgja_orchestrator.infrahub.source import (
    BRANCH_POINT,
    COMMENT_LIMIT,
    HEAD,
    RULE_AT_UNRESOLVED,
    RULE_LABEL_RESERVED,
    RULE_MAIN_MOVED,
    RULE_VALIDATION_ABSENT,
    RULE_VALIDATION_UNFINISHED,
    SEVERITY,
    THREAD_LABEL,
    VALIDATION_APPEAR_S,
    VALIDATION_POLL_S,
    VALIDATION_WAIT_S,
    InfrahubSource,
    Mark,
    NoChange,
    Pin,
    mark_time,
    stages_of,
    validated,
)
from fylgja_orchestrator.infrahub.transport import SourceError, Transport

__all__ = [
    "BRANCH_POINT",
    "COMMENT_LIMIT",
    "HEAD",
    "RULE_AT_UNRESOLVED",
    "RULE_LABEL_RESERVED",
    "RULE_MAIN_MOVED",
    "RULE_VALIDATION_ABSENT",
    "RULE_VALIDATION_UNFINISHED",
    "SEVERITY",
    "THREAD_LABEL",
    "VALIDATION_APPEAR_S",
    "VALIDATION_POLL_S",
    "VALIDATION_WAIT_S",
    "InfrahubSource",
    "Mark",
    "NoChange",
    "Pin",
    "SourceError",
    "Transport",
    "mark_time",
    "stages_of",
    "validated",
]
