"""The current formats' JSON Schemas (`formats/`), resolvable by `$id` from one another."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

ID_PREFIX = "https://github.com/happypathnetworking/fylgja/schemas/"


def formats_dir() -> Path:
    """The repository's `formats/`, which holds every current schema."""
    return Path(__file__).resolve().parents[3] / "formats"


@cache
def _registry() -> Registry[Any]:
    resources = []
    for path in sorted(formats_dir().glob("*.schema.json")):
        contents = json.loads(path.read_text())
        resources.append((contents["$id"], Resource.from_contents(contents)))
    return Registry().with_resources(resources)


@cache
def validator(name: str) -> Any:
    """A validator for one format, by its file's stem, such as `blueprint-1`."""
    schema = _registry().contents(f"{ID_PREFIX}{name}.schema.json")
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema, registry=_registry(), format_checker=cls.FORMAT_CHECKER)
