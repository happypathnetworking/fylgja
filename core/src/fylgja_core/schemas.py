"""The current formats' JSON Schemas (`formats/`), resolvable by `$id` from one another, and
the API's OpenAPI components (`formats/api-1.openapi.yaml`) validated against them."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ID_PREFIX = "https://github.com/happypathnetworking/fylgja/schemas/"
API_ID = f"{ID_PREFIX}api-1.openapi.yaml"


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
def _api_registry() -> tuple[dict[str, Any], Registry[Any]]:
    """The OpenAPI document and a registry holding it beside the format schemas."""
    document: dict[str, Any] = yaml.safe_load((formats_dir() / "api-1.openapi.yaml").read_text())
    resource = Resource.from_contents(document, default_specification=DRAFT202012)
    return document, _registry().with_resource(API_ID, resource)


def _api_at(parts: tuple[str, ...]) -> Any:
    """A validator for the schema at the JSON pointer `parts` into the OpenAPI document."""
    _, registry = _api_registry()
    fragment = "/".join(quote(p.replace("~", "~0").replace("/", "~1"), safe="~") for p in parts)
    cls = jsonschema.Draft202012Validator
    return cls({"$ref": f"{API_ID}#/{fragment}"}, registry=registry, format_checker=cls.FORMAT_CHECKER)


@cache
def api_validator(name: str) -> Any:
    """A validator for the component `name` of the API's OpenAPI document. Its `$ref`s inside
    the document and to the format schemas resolve; an unknown component is a `KeyError`."""
    document, _ = _api_registry()
    if name not in document["components"]["schemas"]:
        raise KeyError(name)
    return _api_at(("components", "schemas", name))


@cache
def api_body_validator(path: str, method: str) -> Any:
    """A validator for the JSON request body the operation `method` (lowercase) on the path
    template `path` declares inline; `KeyError` when the operation declares none."""
    document, _ = _api_registry()
    if "application/json" not in document["paths"][path][method].get("requestBody", {}).get("content", {}):
        raise KeyError(f"{method.upper()} {path}")
    return _api_at(("paths", path, method, "requestBody", "content", "application/json", "schema"))
