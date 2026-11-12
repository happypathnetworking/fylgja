"""The seam to a change source is four calls and one attribute (D-085), over three frozen values a source makes and
the report the library posts to it; a rehearsal's twin is named from the change and the run (D-086)."""

from __future__ import annotations

import dataclasses
import re
import typing
from hashlib import sha256
from typing import Any

import pytest
from fylgja_core.findings import Finding

from fylgja_orchestrator.rehearsal import (
    Change,
    ChangeSource,
    Read,
    Report,
    Stage,
    twin_name,
    twin_prefix,
)

CHANGE = Change("third-link", "pc-1", "third link", 'Change "third link"')

# A twin's name as the core takes it: a DNS-1123 label of at most 40 characters.
TWIN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$")


def test_a_twins_name_is_the_change_and_the_run_hashed() -> None:
    name = twin_name(CHANGE, "run-1")
    assert name == "rh-" + sha256(b"pc-1").hexdigest()[:8] + "-" + sha256(b"run-1").hexdigest()[:8]
    assert twin_prefix(CHANGE) == name[:12]

    long = dataclasses.replace(CHANGE, id="p" * 300)
    odd = twin_name(long, "run/1 é")
    assert len(odd) == 20
    assert TWIN.match(odd), odd
    assert odd.startswith(twin_prefix(long))

    other = dataclasses.replace(CHANGE, id="pc-2")
    assert twin_prefix(other) != twin_prefix(CHANGE)


# Each value's fields, in order, with their types: plan 0's.
FIELDS: list[tuple[type, dict[str, Any]]] = [
    (Change, {"ref": str, "id": str, "name": str, "where": str}),
    (Stage, {"label": str, "description": str, "where": str, "pin": object}),
    (Read, {"blueprint": dict[str, Any] | None, "findings": tuple[Finding, ...], "empty": bool}),
    (Report, {"status": str, "headline": str, "summary": str, "detail": str}),
]


def test_the_seam_is_four_calls_and_the_comment_limit() -> None:
    assert typing.get_protocol_members(ChangeSource) == {"change", "stages", "read", "post", "comment_limit"}
    assert typing.get_type_hints(ChangeSource)["comment_limit"] == int | None

    for cls, expected in FIELDS:
        names = [f.name for f in dataclasses.fields(cls)]
        assert names == list(expected), cls.__name__
        assert typing.get_type_hints(cls) == expected, cls.__name__
        value = cls(*(None for _ in names))
        for name in names:
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(value, name, None)
