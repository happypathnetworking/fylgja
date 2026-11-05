"""Every API problem is a problem 1 document, answered as application/problem+json."""

from __future__ import annotations

import json

import pytest
from starlette.responses import Response

from fylgja_core import schemas
from fylgja_core.documents import Problem, Rejected
from fylgja_core.findings import Finding
from fylgja_core.server import problems


def body(response: Response) -> dict[str, object]:
    raw = response.body
    assert isinstance(raw, bytes)
    doc = json.loads(raw)
    assert isinstance(doc, dict)
    return doc


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 412, 422, 500, 501, 503, 418])
def test_each_problem_validates_and_carries_the_media_type(status: int) -> None:
    r = problems.problem(status, "request.invalid", "a fact", instance="/v1/x")
    assert r.status_code == status
    assert r.media_type == "application/problem+json"
    assert r.headers["content-type"].startswith("application/problem+json")
    doc = body(r)
    assert list(schemas.validator("problem-1").iter_errors(doc)) == []
    assert doc["status"] == status
    assert doc["rule"] == "request.invalid"
    assert doc["instance"] == "/v1/x"


def test_titles_and_types_per_status() -> None:
    assert body(problems.problem(401, "auth.token.missing", "d"))["title"] == "Unauthenticated"
    assert body(problems.problem(412, "twin.precondition", "d"))["title"] == "Precondition failed"
    assert body(problems.problem(501, "x.y", "d"))["title"] == "Not Implemented"  # no title of its own since phase 5
    assert body(problems.problem(418, "x.y", "d"))["title"] == "I'm a Teapot"
    assert body(problems.problem(404, "x.y", "d"))["type"].endswith("/core/problems/not-found")  # type: ignore[attr-defined]
    assert body(problems.problem(412, "x.y", "d"))["type"] == "about:blank"


def test_findings_and_a_missing_instance() -> None:
    f = Finding(rule="blueprint.unsorted", severity="error", object="/devices", message="out of order")
    doc = body(problems.problem(422, "bundle.rejected", "d", findings=[f]))
    assert doc["findings"] == [
        {"rule": "blueprint.unsorted", "severity": "error", "object": "/devices", "message": "out of order"}
    ]
    assert "instance" not in doc
    assert "findings" not in body(problems.problem(400, "request.invalid", "d"))


def test_from_rejected_reports_every_problem() -> None:
    e = Rejected([Problem("/a", "blueprint.invalid", "bad a"), Problem("", "blueprint.duplicate", "bad doc")])
    r = problems.from_rejected(422, e)
    doc = body(r)
    assert list(schemas.validator("problem-1").iter_errors(doc)) == []
    assert doc["rule"] == "blueprint.invalid"
    assert [f["rule"] for f in doc["findings"]] == ["blueprint.invalid", "blueprint.duplicate"]  # type: ignore[attr-defined]
