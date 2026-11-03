"""Bundle 1: the manifest of a runtime-neutral bundle (formats/bundle-1.schema.json, D-010,
D-011).

A bundle is a set of files in the state store, addressed by its id: `manifest.json`, this
document as RFC 8785 (JCS) bytes with no trailing newline, and `configs/<node>.cfg`, each
device's configuration verbatim. `Manifest` is the document's model, `manifest_bytes`
renders it, and `bundle_id` is the content address of a bundle's files, as the schema's
$comment defines it. Nothing here belongs to one twin: a driver's plan binds a bundle to a
twin and a runtime (deployment.py).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fylgja_core import blueprint, documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "bundle.invalid"
RULE_VERSION = "bundle.version.unsupported"


@dataclass(frozen=True, kw_only=True)
class File:
    """A configuration file in the bundle, by path and SHA-256."""

    file: str
    sha256: str


@dataclass(frozen=True, kw_only=True)
class Node:
    """One twin node, from one blueprint device."""

    name: str
    platform: str
    config: File


@dataclass(frozen=True, kw_only=True)
class Row:
    """One mapping row: what the twin makes of one blueprint interface."""

    device: str
    interface: str
    rule: str | None = None
    enabled: bool
    disposition: Literal["cabled", "uncabled", "management", "omitted"]
    node_name: str | None = None
    omission: Literal["out_of_range", "no_rule"] | None = None


@dataclass(frozen=True, kw_only=True)
class Manifest:
    """A bundle 1 manifest as a model."""

    bundle_version: str = VERSION
    blueprint_id: str
    nodes: tuple[Node, ...]
    mapping: tuple[Row, ...]
    links: tuple[blueprint.Link, ...]
    probes: tuple[blueprint.Probe, ...]


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a manifest, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "bundle_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    return documents.schema_problems("bundle-1", doc, RULE_INVALID)


def decode(doc: Any) -> Manifest:
    """The `Manifest` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(Manifest, doc)


def manifest_bytes(manifest: Manifest) -> bytes:
    """The bytes of `manifest.json`: the manifest as RFC 8785 (JCS), with no trailing newline."""
    return blueprint.canonical(documents.encode(manifest))


def bundle_id(files: Mapping[str, bytes]) -> str:
    """The bundle's id: the SHA-256 of a listing of every file, one line
    '<sha256 of the bytes>  <path>' per file in byte-wise path order, as sha256sum writes it."""
    listing = "".join(
        f"{hashlib.sha256(files[path]).hexdigest()}  {path}\n" for path in sorted(files, key=lambda p: p.encode())
    )
    return hashlib.sha256(listing.encode()).hexdigest()
