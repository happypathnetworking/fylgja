"""Plan 3 is typed against the reader's names from the start, so the package exports plan 0's ten names, and `redact`
beside them, and each call, model and error has plan 0's signature: its parameters' names, kinds, defaults and
annotations, and its return's (local/plans' phase 9 plan 0, "Plan 2"); `redact` has the signature the example's own
NetBox transport calls it by. So do the names plan 3 is typed against beside them: the rows a `Source` answers, a
`Source`'s members, `NetBox`'s attributes, and the bracket's `UNREAD`, `mark`, `close` and `branch_moved`, with the
`Mark` that passes between the two."""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding

import fylgja_netbox
from fylgja_netbox import bracket, document
from fylgja_netbox.bracket import Mark
from fylgja_netbox.document import Match, ReaderDocument
from fylgja_netbox.read import Result, check, read
from fylgja_netbox.rows import (
    Branch,
    Cable,
    Change,
    Context,
    Device,
    Listing,
    Platform,
    Port,
    Rendered,
    Source,
    Tag,
)
from fylgja_netbox.transport import SUPPORTED, NetBox, NetBoxError, connect, redact

EMPTY = inspect.Parameter.empty
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD
KEYWORD = inspect.Parameter.KEYWORD_ONLY

NAMES = [
    "SUPPORTED",
    "Match",
    "NetBox",
    "NetBoxError",
    "ReaderDocument",
    "Result",
    "Source",
    "check",
    "connect",
    "read",
]

BESIDE = ["redact"]
"""The names the package exports beside those: `redact`, with which the example's own NetBox transport hides a token
as the reader's does."""

Parameter = tuple[str, inspect._ParameterKind, object, object]

CALLS: list[tuple[str, Callable[..., Any], list[Parameter], object]] = [
    (
        "connect",
        connect,
        [
            ("address", POSITIONAL, EMPTY, str),
            ("token", POSITIONAL, EMPTY, str),
            ("ca", KEYWORD, None, Path | None),
            ("transport", KEYWORD, None, httpx.BaseTransport | None),
        ],
        NetBox,
    ),
    (
        "read",
        read,
        [
            ("conn", POSITIONAL, EMPTY, Source),
            ("branch", KEYWORD, EMPTY, str | None),
            ("scope", KEYWORD, EMPTY, str),
            ("document", KEYWORD, EMPTY, ReaderDocument),
        ],
        Result,
    ),
    (
        "check",
        check,
        [("conn", POSITIONAL, EMPTY, Source), ("branch", KEYWORD, EMPTY, str | None)],
        tuple[Finding, ...],
    ),
    ("redact", redact, [("text", POSITIONAL, EMPTY, str), ("token", POSITIONAL, EMPTY, str)], str),
    ("document.load", document.load, [("path", POSITIONAL, EMPTY, Path)], ReaderDocument),
    ("document.validate", document.validate, [("doc", POSITIONAL, EMPTY, Any)], list[Problem]),
    ("document.decode", document.decode, [("doc", POSITIONAL, EMPTY, Any)], ReaderDocument),
    (
        "ReaderDocument.package",
        ReaderDocument.package,
        [
            ("self", POSITIONAL, EMPTY, EMPTY),
            ("manufacturer", POSITIONAL, EMPTY, str),
            ("platform", POSITIONAL, EMPTY, str),
        ],
        str | None,
    ),
    (
        "NetBoxError",
        NetBoxError.__init__,
        [
            ("self", POSITIONAL, EMPTY, EMPTY),
            ("message", POSITIONAL, EMPTY, str),
            ("status", POSITIONAL, EMPTY, int | None),
        ],
        None,
    ),
    (
        "bracket.mark",
        bracket.mark,
        [("conn", POSITIONAL, EMPTY, Source), ("branch", POSITIONAL, EMPTY, Branch | None)],
        Mark,
    ),
    (
        "bracket.close",
        bracket.close,
        [
            ("conn", POSITIONAL, EMPTY, Source),
            ("opened", POSITIONAL, EMPTY, Branch | None),
            ("before", POSITIONAL, EMPTY, Mark),
        ],
        tuple[int | None, tuple[Finding, ...]],
    ),
    (
        "bracket.branch_moved",
        bracket.branch_moved,
        [("opened", POSITIONAL, EMPTY, Branch), ("found", POSITIONAL, EMPTY, Listing[Branch])],
        Finding | None,
    ),
]

SELF = ("self", POSITIONAL, EMPTY, EMPTY)
OPENED = ("branch", POSITIONAL, EMPTY, Branch | None)

SOURCE: list[tuple[str, list[Parameter], object]] = [
    ("branches", [SELF, ("name", POSITIONAL, EMPTY, str)], Listing[Branch]),
    ("tags", [SELF, OPENED, ("name", POSITIONAL, EMPTY, str)], Listing[Tag]),
    ("devices", [SELF, OPENED, ("tag", POSITIONAL, EMPTY, int)], Listing[Device]),
    ("platforms", [SELF, OPENED, ("ids", POSITIONAL, EMPTY, Sequence[int])], Listing[Platform]),
    ("ports", [SELF, OPENED, ("devices", POSITIONAL, EMPTY, Sequence[int])], Listing[Port]),
    ("cables", [SELF, OPENED, ("ids", POSITIONAL, EMPTY, Sequence[int])], Listing[Cable]),
    ("contexts", [SELF, OPENED, ("name", POSITIONAL, EMPTY, str)], Listing[Context]),
    ("render", [SELF, OPENED, ("device", POSITIONAL, EMPTY, int)], Rendered),
    ("latest", [SELF, OPENED], int | None),
    ("changes", [SELF, OPENED, ("after", POSITIONAL, EMPTY, int | None)], Listing[Change]),
    ("counted", [SELF, OPENED, ("upto", POSITIONAL, EMPTY, int)], int),
]
"""Every call of a `Source`, by its name, its parameters and its return."""

ATTRIBUTES = {"version": str, "branching": str | None, "unverified": Finding | None}
"""A `Source`'s attributes, which `NetBox` declares the same."""

MODELS: list[tuple[type[Any], list[tuple[str, object]]]] = [
    (Match, [("manufacturer", str), ("platform", str), ("package", str)]),
    (ReaderDocument, [("platforms", tuple[Match, ...]), ("probes", str | None)]),
    (Result, [("blueprint", dict[str, Any] | None), ("findings", tuple[Finding, ...]), ("empty", bool)]),
    (Branch, [("id", int), ("name", str), ("schema_id", str), ("status", str), ("last_sync", str | None)]),
    (Rendered, [("status", int), ("body", bytes), ("content_type", str | None)]),
    (Mark, [("id", int | None), ("below", int), ("schema_id", str | None)]),
]


def _parameters(call: Callable[..., Any]) -> tuple[list[Parameter], object]:
    signature = inspect.signature(call, eval_str=True)
    held = [(p.name, p.kind, p.default, p.annotation) for p in signature.parameters.values()]
    return held, signature.return_annotation


def test_the_package_exports_plan_0s_names() -> None:
    assert sorted(fylgja_netbox.__all__) == sorted(NAMES + BESIDE)
    for name in NAMES + BESIDE:
        assert hasattr(fylgja_netbox, name), name
    assert fylgja_netbox.redact is redact


def test_each_call_has_plan_0s_signature() -> None:
    for name, call, parameters, returned in CALLS:
        assert _parameters(call) == (parameters, returned), name
    for model, fields in MODELS:
        assert dataclasses.is_dataclass(model), model.__name__
        assert model.__dataclass_params__.frozen, model.__name__  # type: ignore[attr-defined]
        hints = inspect.get_annotations(model, eval_str=True)
        assert [(f.name, hints[f.name]) for f in dataclasses.fields(model)] == fields, model.__name__
    assert issubclass(NetBoxError, Exception)
    assert [name for name in ("version", "branching", "unverified") if name in inspect.get_annotations(NetBox)] == [
        "version",
        "branching",
        "unverified",
    ]
    assert callable(NetBox.close)
    assert SUPPORTED == (("4.7.5", "1.2.3"),)


def test_a_source_and_the_bracket_have_the_names_plan_3_is_typed_against() -> None:
    assert inspect.get_annotations(Source, eval_str=True) == ATTRIBUTES
    assert inspect.get_annotations(NetBox, eval_str=True) == ATTRIBUTES
    calls = sorted(n for n, member in vars(Source).items() if inspect.isfunction(member) and not n.startswith("_"))
    assert calls == sorted(name for name, _, _ in SOURCE)
    for name, parameters, returned in SOURCE:
        assert _parameters(getattr(Source, name)) == (parameters, returned), name
        assert _parameters(getattr(NetBox, name)) == (parameters, returned), f"NetBox.{name}"
    assert bracket.UNREAD == ("extras.journalentry", "netbox_branching.branch")
    assert inspect.get_annotations(bracket, eval_str=True)["UNREAD"] == tuple[str, ...]
