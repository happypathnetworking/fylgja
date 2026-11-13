"""The example's two documents (D-086): a plan 1 document, what each stage of a change built, and a rehearsal 1
document, what each came to on the twin. Each is a plain JSON value, as the library writes it and its caller reads it;
this module validates one against its format and makes the findings both hold.

The two formats are the example's, carried by its wheel beside its package and not by the core's (D-084,
formats/README.md, note 23), and read through the core's registry, which holds the core's formats beside them.
"""

from __future__ import annotations

from typing import Any, Literal

from fylgja_core import schemas
from fylgja_core.documents import pointer

PACKAGE = "fylgja_orchestrator"


def validate(name: Literal["plan-1", "rehearsal-1"], doc: Any) -> list[str]:
    """Every way `doc` violates the format `name`, one `<pointer>: <message>` a violation, sorted and unique; empty
    when it is valid. The pointer is RFC 6901's, the document itself `/`, as the core's `Rejected` says it."""
    errors = schemas.validator(name, PACKAGE).iter_errors(doc)
    return sorted({f"{pointer(e.absolute_path) or '/'}: {e.message}" for e in errors})


def finding(rule: str, severity: str, message: str, object: str | None = None) -> dict[str, Any]:
    """A finding as both documents hold it, in the order of the core's findings: its rule, its severity, what it is
    about where it names something, and its message."""
    made: dict[str, Any] = {"rule": rule, "severity": severity}
    if object is not None:
        made["object"] = object
    made["message"] = message
    return made
