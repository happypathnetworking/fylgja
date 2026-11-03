"""What every format module shares (formats/README.md).

A document is a format's JSON value, as a file, a request or a stored object holds it. A
model type is its typed form: a frozen dataclass whose fields are the document's members,
so that `encode(decode(T, doc)) == doc`. A member the document leaves out is a field that
is None, and a document member whose name is not a Python name is declared with
`field(metadata={"key": ...})`.

Each format module follows one pattern: `validate(doc)` reports every problem in one pass
(Constitution III), the version first, then the schema, then the rules the schema cannot
state, each with a stable rule id and a JSON pointer; `decode(doc)` validates and builds the
model type, or raises `Rejected`; `load(path)` reads a file and decodes it.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from fylgja_core import schemas


@dataclass(frozen=True, order=True)
class Problem:
    """One reason a document is not a valid instance of its format."""

    pointer: str
    rule: str
    detail: str


class Rejected(Exception):
    """A document was refused, with every problem found in one pass."""

    def __init__(self, problems: Sequence[Problem], subject: str = "") -> None:
        self.problems = tuple(problems)
        self.subject = subject
        super().__init__(subject, self.problems)

    def __str__(self) -> str:
        lines = "; ".join(f"{p.rule} at {p.pointer or '/'}: {p.detail}" for p in self.problems)
        return f"{self.subject}: {lines}" if self.subject else lines


class Malformed(ValueError):
    """A file that is neither JSON nor YAML."""


def pointer(parts: Iterable[Any]) -> str:
    """An RFC 6901 JSON pointer from path parts."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def unsupported_version(doc: Any, key: str, version: str, rule: str) -> list[Problem]:
    """The one problem to report when `doc` states a version other than `version`, else none.
    A document that states no version, or is no object, is left to the schema."""
    if isinstance(doc, dict) and key in doc and doc[key] != version:
        return [Problem(f"/{key}", rule, f"version {doc[key]!r}; this core reads {version}")]
    return []


def schema_problems(name: str, doc: Any, rule: str) -> list[Problem]:
    """Every violation of the schema `name` (a file stem under formats/), sorted and unique,
    each under `rule` at its pointer."""
    errors = schemas.validator(name).iter_errors(doc)
    return sorted({Problem(pointer(e.absolute_path), rule, e.message) for e in errors})


def read(path: Path) -> Any:
    """The document in `path`: JSON for a `.json` file, YAML otherwise."""
    text = path.read_text()
    try:
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise Malformed(f"{path} is not a document: {e}") from e


def load[T](path: Path, rule: str, decode: Callable[[Any], T]) -> T:
    """`decode` the document in `path`; a `Rejected` names the file, and a file that is no
    document at all is one problem under `rule`."""
    try:
        doc = read(path)
    except Malformed as e:
        raise Rejected([Problem("", rule, str(e))], str(path)) from e
    try:
        return decode(doc)
    except Rejected as e:
        raise Rejected(e.problems, str(path)) from None


def decode[T](cls: type[T], doc: Any) -> T:
    """The model type `cls` built from a document that its format's `validate` passed."""
    return cast(T, _decode(cls, doc))


def encode(value: Any) -> Any:
    """The document of a model type: fields that are None are left out, tuples become lists,
    and a field's `key` metadata names its member."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        doc: dict[str, Any] = {}
        for f in dataclasses.fields(value):
            member = getattr(value, f.name)
            if member is not None:
                doc[f.metadata.get("key", f.name)] = encode(member)
        return doc
    if isinstance(value, list | tuple):
        return [encode(v) for v in value]
    if isinstance(value, Mapping):
        return {k: encode(v) for k, v in value.items()}
    return value


@cache
def _hints(cls: type[Any]) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def _decode(hint: Any, value: Any) -> Any:
    origin = typing.get_origin(hint)
    if origin is types.UnionType or origin is typing.Union:
        # Only `X | None` is used: None stays None, anything else is decoded as X.
        if value is None:
            return None
        (inner,) = [a for a in typing.get_args(hint) if a is not types.NoneType]
        return _decode(inner, value)
    if origin is Literal or hint is Any or hint in (str, int, bool):
        return value
    if hint is float:
        return float(value)
    if origin is tuple:
        args = typing.get_args(hint)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], v) for v in value)
        return tuple(_decode(a, v) for a, v in zip(args, value, strict=True))
    if origin is not None and issubclass(origin, Mapping):
        _, member = typing.get_args(hint)
        return {k: _decode(member, v) for k, v in value.items()}
    if dataclasses.is_dataclass(hint) and isinstance(hint, type):
        hints = _hints(hint)
        members = {}
        for f in dataclasses.fields(hint):
            key = f.metadata.get("key", f.name)
            if key in value:
                members[f.name] = _decode(hints[f.name], value[key])
        return hint(**members)
    raise TypeError(f"no decoding for {hint!r}")
