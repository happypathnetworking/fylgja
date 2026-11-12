"""What Infrahub is given from this repository, read as files: the schema library's DCIM at its commit, and the
registration, `.infrahub.yml` with its queries, its template and its two checks.

Nothing here renders the template: Infrahub's own workers do, from the commit they fetch.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "infrahub" / "schema" / "dcim"
QUERY = ROOT / "infrahub" / "queries" / "device_config.gql"
TEMPLATE = ROOT / "infrahub" / "templates" / "device_config.j2"

COMMIT = "26336e9026dff1907f2c58e81dd6ae7b5c3f763e"
SHA256 = {
    "dcim.yml": "81df2eb8cc0a58c496c3292c6349591695048bf1a036b1ccef5190842bc16c9e",
    "ipam.yml": "6d31dc0307f9053c334e028b57c2d6fca1fa51741a18cfebfbfd3ac35a9fe588",
    "location.yml": "afef7a770c05a8110295bd8e6d7f12348cf260851b9f3da828edb6ae8c53f926",
    "organization.yml": "082e8536f389d5ad971f2808068234a3dab6c48249230db9ec1aa308124e5fff",
    "cable.yml": "3196073cdd490350e514c2bc777e27a647b1e7dbaf6c29fa9e3abc524e943041",
    "location_minimal.yml": "cf148227aa191f13a77e2758aa9639e8312c61fae9538762d3b63bfb044b15c3",
    "LICENSE.txt": "71d4aed1ad1acd6b90246d50984276bf0d5a3a27c2bb06feb91b96058c67399d",
}
"""Each file of the library at `COMMIT`, by its SHA-256: six from `base/` and `extensions/`, and its licence."""

REGISTRATION = {
    "queries": [
        {"name": "device_config", "file_path": "infrahub/queries/device_config.gql"},
        {"name": "fylgja_branch", "file_path": "infrahub/queries/fylgja_branch.gql"},
    ],
    "jinja2_transforms": [
        {
            "name": "device_config",
            "description": "One device's SR Linux configuration, from the schema library's DCIM.",
            "query": "device_config",
            "template_path": "infrahub/templates/device_config.j2",
        },
    ],
    "artifact_definitions": [
        {
            "name": "device-config",
            "artifact_name": "device-config",
            "parameters": {"device": "name__value"},
            "content_type": "text/plain",
            "targets": "fylgja-devices",
            "transformation": "device_config",
        },
    ],
    "check_definitions": [
        {"name": "fylgja-step", "file_path": "infrahub/checks/fylgja_step.py", "class_name": "FylgjaStep"},
        {"name": "fylgja-twin", "file_path": "infrahub/checks/fylgja_twin.py", "class_name": "FylgjaTwin"},
    ],
}

READ = {
    "name",
    "description",
    "platform",
    "manufacturer",
    "interfaces",
    "status",
    "role",
    "ip_addresses",
    "address",
    "connector",
    "connected_endpoints",
    "device",
}
"""What the template reads of the device and of its interfaces."""


def defined_kinds() -> set[str]:
    """Every kind the six files define: each `nodes` and `generics` entry's namespace and name."""
    kinds: set[str] = set()
    for name in SHA256:
        if name.endswith(".yml"):
            schema = yaml.safe_load((LIBRARY / name).read_text())
            for section in ("nodes", "generics"):
                kinds |= {entry["namespace"] + entry["name"] for entry in schema.get(section, [])}
    return kinds


def selections(query: str) -> tuple[set[str], set[str], set[str]]:
    """The query's root fields, every field it selects at any depth, and every kind a fragment names (`... on`)."""
    roots: set[str] = set()
    fields: set[str] = set()
    kinds: set[str] = set()
    depth = arguments = 0
    previous = ""
    for token in re.findall(r"\.\.\.|\$?\w+|[{}()]", re.sub(r"#[^\n]*", "", query)):
        if token in ("{", "}"):
            depth += 1 if token == "{" else -1
        elif token in ("(", ")"):
            arguments += 1 if token == "(" else -1
        elif previous == "on":
            kinds.add(token)
        elif depth and not arguments and token not in ("...", "on"):
            fields.add(token)
            if depth == 1:
                roots.add(token)
        previous = token
    return roots, fields, kinds


def reads(template: str) -> set[str]:
    """Each name the template's code reads below a variable: a dotted attribute, a subscript by a string, or a step
    of a filter's `attribute` path. The variable itself and an index are no name read."""
    uncommented = re.sub(r"\{#.*?#\}", "", template, flags=re.S)
    code = " ".join("".join(parts) for parts in re.findall(r"\{\{(.*?)\}\}|\{%(.*?)%\}", uncommented, re.S))
    names: set[str] = set()
    for path in re.findall(r"attribute='([\w.]+)'", code):
        names |= set(path.split("."))
    for chain in re.findall(r"\w+(?:\.\w+|\[\d+\]|\['\w+'\])+", re.sub(r"attribute='[\w.]+'", "", code)):
        names |= {attribute or key for attribute, key in re.findall(r"\.(\w+)|\['(\w+)'\]", chain)}
    return names


def test_the_library_is_the_pinned_commit() -> None:
    """The six files and the licence are the library's bytes at the commit `COMMIT` names, and nothing else is there."""
    assert (LIBRARY / "COMMIT").read_bytes() == f"{COMMIT}\n".encode()
    assert {path.name for path in LIBRARY.iterdir()} == {*SHA256, "COMMIT"}
    assert {name: hashlib.sha256((LIBRARY / name).read_bytes()).hexdigest() for name in SHA256} == SHA256


def test_the_registration_is_two_queries_one_transform_one_artifact_definition_and_two_checks() -> None:
    """An import loads the two queries, the transform, the artifact definition and the two check definitions, each
    global: no schema and no object."""
    registration = yaml.safe_load((ROOT / ".infrahub.yml").read_text())
    assert registration == REGISTRATION
    paths = [query["file_path"] for query in registration["queries"]]
    paths += [transform["template_path"] for transform in registration["jinja2_transforms"]]
    paths += [check["file_path"] for check in registration["check_definitions"]]
    assert [path for path in paths if not (ROOT / path).is_file()] == []


def test_the_query_names_only_kinds_the_library_defines() -> None:
    """Its root and every fragment's kind are among the six files' nodes and generics."""
    roots, _, kinds = selections(QUERY.read_text())
    assert roots == {"DcimDevice"}
    assert kinds
    assert (roots | kinds) - defined_kinds() == set()


def test_the_template_asks_for_nothing_the_query_does_not_select() -> None:
    """Every name the template reads is a field the query selects, and it renders the SR Linux dialect alone."""
    template = TEMPLATE.read_text()
    _, fields, _ = selections(QUERY.read_text())
    read = reads(template)
    assert READ - read == set()
    assert read - fields == set()
    assert "EOS" not in template
    assert "hostname" not in template
