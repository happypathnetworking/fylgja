"""The current formats' JSON Schemas, resolvable by `$id` from one another, and the API's
OpenAPI components (`api-1.openapi.yaml`) validated against them.

Each distribution's wheel carries the formats its own code reads, beside its package (D-084),
and `formats/` at the repository's root holds every one of them (D-066). A package reads the
core's formats and its own: installed, those the core's wheel and its own carry; in a
checkout, the repository's. The API's document is the core's.

Every validator is made from `Validator`, draft 2020-12 with one keyword mended: JSON Schema reads
a `pattern` as ECMA-262 does, where `$` is the end of the text, and Python's `re`, which jsonschema
reads it with, lets `$` match before a final newline too.
"""

from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jsonschema
import yaml
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ID_PREFIX = "https://github.com/happypathnetworking/fylgja/schemas/"
API_ID = f"{ID_PREFIX}api-1.openapi.yaml"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def ecma(pattern: str) -> str:
    """`pattern` written so that Python's `re` reads it as ECMA-262 reads `pattern`: each `$`
    neither escaped nor inside a character class becomes `\\Z`, the end of the text; all else is
    unchanged."""
    out: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "$":
            c = r"\Z"
        out.append(c)
        i += 1
    return "".join(out)


def _pattern(validator: Any, pattern: str, instance: Any, schema: Any) -> Iterator[ValidationError]:
    """The `pattern` keyword, `$` read as ECMA-262 reads it; the message names the pattern as written."""
    if validator.is_type(instance, "string") and not re.search(ecma(pattern), instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


Validator: Any = jsonschema.validators.extend(jsonschema.Draft202012Validator, {"pattern": _pattern})


def formats_dir(package: str = "fylgja_core") -> Path:
    """The directory holding `package`'s formats: `formats/` beside the package, where its wheel
    put them; else, for a package under a checkout's `src/`, the first `formats/` above that
    `src/`, the repository's; else `FileNotFoundError`, never a `formats/` that merely lies above
    an installed package. A name that is no installed package is `ModuleNotFoundError`."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ModuleNotFoundError(f"no installed package {package}", name=package)
    here = Path(next(iter(spec.submodule_search_locations))).resolve()
    if (here / "formats").is_dir():
        return here / "formats"
    if here.parent.name == "src":
        for above in here.parent.parents:
            if (above / "formats").is_dir():
                return above / "formats"
    raise FileNotFoundError(f"the package {package} has no formats: none at {here / 'formats'}, and no checkout's")


def _resource(contents: dict[str, Any], where: Path) -> Resource[Any]:
    """A format as a draft 2020-12 resource, its `$schema` left out: where a `$ref` enters a schema
    that names its dialect, jsonschema validates it with that dialect's stock class, so a format
    naming none is validated by `Validator` throughout. A format of another dialect is a
    `ValueError`."""
    if contents.get("$schema") != DIALECT:
        raise ValueError(f"{where} is not a draft 2020-12 schema")
    return DRAFT202012.create_resource({key: value for key, value in contents.items() if key != "$schema"})


@cache
def _registry(package: str = "fylgja_core") -> Registry[Any]:
    """The core's schemas and `package`'s, one resource an `$id`: the core's where both hold one."""
    resources: dict[str, Any] = {}
    for directory in dict.fromkeys((formats_dir(), formats_dir(package))):
        for path in sorted(directory.glob("*.schema.json")):
            contents = json.loads(path.read_text())
            resources.setdefault(contents["$id"], _resource(contents, path))
    return Registry().with_resources(resources.items())


@cache
def validator(name: str, package: str = "fylgja_core") -> Any:
    """A validator for one format, by its file's stem, such as `blueprint-1`, among the core's
    formats and `package`'s; a name neither holds is a `LookupError`."""
    registry = _registry(package)
    schema = registry.contents(f"{ID_PREFIX}{name}.schema.json")
    return Validator(schema, registry=registry, format_checker=Validator.FORMAT_CHECKER)


@cache
def _api_registry() -> tuple[dict[str, Any], Registry[Any]]:
    """The OpenAPI document and a registry holding it beside the format schemas."""
    document: dict[str, Any] = yaml.safe_load((formats_dir() / "api-1.openapi.yaml").read_text())
    resource = Resource.from_contents(document, default_specification=DRAFT202012)
    return document, _registry("fylgja_core").with_resource(API_ID, resource)


def _api_at(parts: tuple[str, ...]) -> Any:
    """A validator for the schema at the JSON pointer `parts` into the OpenAPI document."""
    _, registry = _api_registry()
    fragment = "/".join(quote(p.replace("~", "~0").replace("/", "~1"), safe="~") for p in parts)
    return Validator({"$ref": f"{API_ID}#/{fragment}"}, registry=registry, format_checker=Validator.FORMAT_CHECKER)


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
