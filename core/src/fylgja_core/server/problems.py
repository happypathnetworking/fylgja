"""The API's one error answer: an RFC 9457 problem document (formats/problem-1.schema.json).

Bodies are built with `ProblemDocument` and `documents.encode`, so a problem has one
representation. `type` is the problem class of the status (problem-1's `$comment`), `rule` the
stable id clients match on.
"""

from __future__ import annotations

import http
import json
from collections.abc import Sequence

from starlette.responses import Response

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected
from fylgja_core.findings import Finding
from fylgja_core.problem import ProblemDocument

MEDIA_TYPE = "application/problem+json"
_CLASS_BASE = "https://github.com/happypathnetworking/fylgja/core/problems/"

# The short title of each status the API answers with.
TITLES: dict[int, str] = {
    400: "Malformed request",
    401: "Unauthenticated",
    403: "Forbidden",
    404: "Not found",
    409: "Conflict",
    412: "Precondition failed",
    422: "Unprocessable",
    500: "Server error",
}
# No route answers 501 since phase 5 built the step (formats/README.md, note 19); a status with no
# title of its own takes HTTP's phrase.

# The problem class of each status that has one; any other status is `about:blank`.
CLASSES: dict[int, str] = {
    400: "invalid",
    401: "unauthenticated",
    403: "forbidden",
    404: "not-found",
    409: "conflict",
    422: "unprocessable",
    500: "internal",
    503: "unavailable",
}


def problem(
    status: int,
    rule: str,
    detail: str,
    *,
    findings: Sequence[Finding] = (),
    instance: str | None = None,
) -> Response:
    """The problem response for `status`: a document with `rule`, `detail` and every finding."""
    cls = CLASSES.get(status)
    doc = ProblemDocument(
        type=_CLASS_BASE + cls if cls else "about:blank",
        title=TITLES.get(status) or http.HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=instance,
        rule=rule,
        findings=tuple(findings) or None,
    )
    return Response(json.dumps(documents.encode(doc)), status_code=status, media_type=MEDIA_TYPE)


def findings_of(found: Sequence[Problem]) -> list[Finding]:
    """A loader's problems as findings: each an error at its pointer (`/` for the whole document)."""
    return [Finding(rule=p.rule, severity="error", object=p.pointer or "/", message=p.detail) for p in found]


def from_rejected(status: int, e: Rejected, *, instance: str | None = None) -> Response:
    """The problem response for a refused document: its first problem's rule and detail, and
    every problem as a finding at its pointer."""
    first = e.problems[0]
    return problem(status, first.rule, first.detail, findings=findings_of(e.problems), instance=instance)
