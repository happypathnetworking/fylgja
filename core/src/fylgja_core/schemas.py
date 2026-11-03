"""The current formats' JSON Schemas (`formats/`), resolvable by `$id` from one another, and
the API's OpenAPI components (`formats/api-1.openapi.yaml`) validated against them."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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


@cache
def api_validator(name: str) -> Any:
    """A validator for the component `name` of the API's OpenAPI document. Its `$ref`s inside
    the document and to the format schemas resolve; an unknown component is a `KeyError`."""
    document = yaml.safe_load((formats_dir() / "api-1.openapi.yaml").read_text())
    if name not in document["components"]["schemas"]:
        raise KeyError(name)
    api_id = f"{ID_PREFIX}api-1.openapi.yaml"
    registry = _registry().with_resource(api_id, Resource.from_contents(document, default_specification=DRAFT202012))
    cls = jsonschema.Draft202012Validator
    schema = {"$ref": f"{api_id}#/components/schemas/{name}"}
    return cls(schema, registry=registry, format_checker=cls.FORMAT_CHECKER)
