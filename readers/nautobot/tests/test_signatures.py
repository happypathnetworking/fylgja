"""Plan 3 is typed against the reader's names from the start, so the package exports plan 0's ten names, and `redact`
beside them, and each call, model and error has plan 0's signature: its parameters' names, kinds, defaults and
annotations, and its return's (local/plans' phase 11 plan 0, "Plan 2"). So do the names beside them that the reader's
other modules are typed against: the rows a `Source` answers and a `Source`'s members, and `Nautobot`'s attributes."""

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding

import fylgja_nautobot
from fylgja_nautobot import document
from fylgja_nautobot.document import Match, ReaderDocument
from fylgja_nautobot.read import Result, check, read
from fylgja_nautobot.rows import (
    Cable,
    Change,
    Context,
    Device,
    End,
    Group,
    Listing,
    Manufacturer,
    Platform,
    Port,
    Rendered,
    Repository,
    Setting,
    Source,
    Tag,
)
from fylgja_nautobot.transport import SUPPORTED, Nautobot, NautobotError, connect, redact

EMPTY = inspect.Parameter.empty
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD
KEYWORD = inspect.Parameter.KEYWORD_ONLY

NAMES = [
    "SUPPORTED",
    "Match",
    "Nautobot",
    "NautobotError",
    "ReaderDocument",
    "Result",
    "Source",
    "check",
    "connect",
    "read",
]

BESIDE = ["redact"]
"""The names the package exports beside those: `redact`, with which a caller hides a token as the reader does."""

Parameter = tuple[str, inspect._ParameterKind, object, object]

SELF = ("self", POSITIONAL, EMPTY, EMPTY)

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
        Nautobot,
    ),
    (
        "read",
        read,
        [
            ("conn", POSITIONAL, EMPTY, Source),
            ("scope", KEYWORD, EMPTY, str),
            ("document", KEYWORD, EMPTY, ReaderDocument),
        ],
        Result,
    ),
    ("check", check, [("conn", POSITIONAL, EMPTY, Source)], tuple[Finding, ...]),
    ("redact", redact, [("text", POSITIONAL, EMPTY, str), ("token", POSITIONAL, EMPTY, str)], str),
    ("document.load", document.load, [("path", POSITIONAL, EMPTY, Path)], ReaderDocument),
    ("document.validate", document.validate, [("doc", POSITIONAL, EMPTY, Any)], list[Problem]),
    ("document.decode", document.decode, [("doc", POSITIONAL, EMPTY, Any)], ReaderDocument),
    (
        "ReaderDocument.package",
        ReaderDocument.package,
        [SELF, ("manufacturer", POSITIONAL, EMPTY, str), ("platform", POSITIONAL, EMPTY, str)],
        str | None,
    ),
    (
        "NautobotError",
        NautobotError.__init__,
        [SELF, ("message", POSITIONAL, EMPTY, str), ("status", POSITIONAL, EMPTY, int | None)],
        None,
    ),
]

SOURCE: list[tuple[str, list[Parameter], object]] = [
    ("tags", [SELF, ("name", POSITIONAL, EMPTY, str)], Listing[Tag]),
    ("devices", [SELF, ("tag", POSITIONAL, EMPTY, Tag)], Listing[Device]),
    ("platforms", [SELF, ("ids", POSITIONAL, EMPTY, Sequence[str])], Listing[Platform]),
    ("manufacturers", [SELF, ("ids", POSITIONAL, EMPTY, Sequence[str])], Listing[Manufacturer]),
    ("ports", [SELF, ("devices", POSITIONAL, EMPTY, Sequence[str])], Listing[Port]),
    ("cables", [SELF, ("ids", POSITIONAL, EMPTY, Sequence[str])], Listing[Cable]),
    ("contexts", [SELF, ("name", POSITIONAL, EMPTY, str)], Listing[Context]),
    ("render", [SELF, ("device", POSITIONAL, EMPTY, str)], Rendered),
    ("newest", [SELF], tuple[int, Change | None]),
    ("settings", [SELF], Listing[Setting]),
    ("repositories", [SELF, ("ids", POSITIONAL, EMPTY, Sequence[str])], Listing[Repository]),
    ("groups", [SELF, ("ids", POSITIONAL, EMPTY, Sequence[str])], Listing[Group]),
    (
        "stored",
        [SELF, ("group", POSITIONAL, EMPTY, str), ("devices", POSITIONAL, EMPTY, Sequence[str])],
        Listing[str],
    ),
    (
        "matching",
        [
            SELF,
            ("filter", POSITIONAL, EMPTY, Sequence[tuple[str, str]]),
            ("devices", POSITIONAL, EMPTY, Sequence[str]),
            ("group", POSITIONAL, None, str | None),
        ],
        Listing[Device],
    ),
]
"""Every call of a `Source` so far, by its name, its parameters and its return; later tasks add theirs."""

ATTRIBUTES = {"version": str, "golden_config": str | None, "unverified": Finding | None}
"""A `Source`'s attributes, which `Nautobot` declares the same."""

MODELS: list[tuple[type[Any], list[tuple[str, object]]]] = [
    (Match, [("manufacturer", str), ("platform", str), ("package", str)]),
    (ReaderDocument, [("platforms", tuple[Match, ...]), ("probes", str | None)]),
    (Result, [("blueprint", dict[str, Any] | None), ("findings", tuple[Finding, ...]), ("empty", bool)]),
    (Tag, [("id", str), ("name", str)]),
    (Device, [("id", str), ("name", str | None), ("platform", str | None)]),
    (Platform, [("id", str), ("name", str), ("manufacturer", str | None)]),
    (Manufacturer, [("id", str), ("name", str)]),
    (
        Port,
        [
            ("id", str),
            ("device", str),
            ("name", str),
            ("type", str),
            ("enabled", bool),
            ("mgmt_only", bool),
            ("cable", str | None),
        ],
    ),
    (End, [("kind", str), ("id", str), ("display", str | None)]),
    (Cable, [("id", str), ("label", str | None), ("a", tuple[End, ...]), ("b", tuple[End, ...])]),
    (Context, [("id", str), ("name", str), ("active", bool), ("data", Any)]),
    (Rendered, [("status", int), ("text", str | None), ("detail", str | None)]),
    (Change, [("id", str), ("time", str)]),
    (
        Setting,
        [("id", str), ("name", str), ("weight", int), ("repository", str | None), ("group", str)],
    ),
    (Repository, [("id", str), ("name", str), ("head", str)]),
    (Group, [("id", str), ("name", str), ("kind", str), ("filter", Any)]),
]


def _parameters(call: Callable[..., Any]) -> tuple[list[Parameter], object]:
    signature = inspect.signature(call, eval_str=True)
    held = [(p.name, p.kind, p.default, p.annotation) for p in signature.parameters.values()]
    return held, signature.return_annotation


def test_the_package_exports_plan_0s_names() -> None:
    assert sorted(fylgja_nautobot.__all__) == sorted(NAMES + BESIDE)
    for name in NAMES + BESIDE:
        assert hasattr(fylgja_nautobot, name), name
    assert fylgja_nautobot.redact is redact


def test_each_call_has_plan_0s_signature() -> None:
    for name, call, parameters, returned in CALLS:
        assert _parameters(call) == (parameters, returned), name
    for model, fields in MODELS:
        assert dataclasses.is_dataclass(model), model.__name__
        assert model.__dataclass_params__.frozen, model.__name__  # type: ignore[attr-defined]
        hints = inspect.get_annotations(model, eval_str=True)
        assert [(f.name, hints[f.name]) for f in dataclasses.fields(model)] == fields, model.__name__
    assert issubclass(NautobotError, Exception)
    assert [n for n in ("version", "golden_config", "unverified") if n in inspect.get_annotations(Nautobot)] == [
        "version",
        "golden_config",
        "unverified",
    ]
    assert callable(Nautobot.close)
    assert callable(Nautobot.__enter__)
    assert SUPPORTED == (("3.2.8", "3.0.8"),)


def test_a_source_has_the_calls_the_read_makes_so_far() -> None:
    assert inspect.get_annotations(Source, eval_str=True) == ATTRIBUTES
    assert inspect.get_annotations(Nautobot, eval_str=True) == ATTRIBUTES
    calls = sorted(n for n, member in vars(Source).items() if inspect.isfunction(member) and not n.startswith("_"))
    assert calls == sorted(name for name, _, _ in SOURCE)
    for name, parameters, returned in SOURCE:
        assert _parameters(getattr(Source, name)) == (parameters, returned), name
