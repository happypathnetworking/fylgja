"""`make infrahub-register`'s work as the development Infrahub's `main` holds it, and a second registration's."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import register
from hub import Hub

SCHEMA = Path(__file__).resolve().parents[2] / "schema" / "dcim"

MAIN = """
query ($group: String!, $repository: String!) {
  CoreStandardGroup(name__value: $group) { count edges { node { id } } }
  CoreReadOnlyRepository(name__value: $repository) {
    edges { node { id ref { value } commit { value } sync_status { value } operational_status { value } } }
  }
  CoreGraphQLQuery { edges { node { name { value } } } }
  CoreTransformJinja2 { edges { node { name { value } query { node { name { value } } } } } }
  CoreArtifactDefinition {
    edges { node { name { value } artifact_name { value } targets { node { id } } } }
  }
  CoreCheckDefinition {
    edges { node { name { value } file_path { value } class_name { value } timeout { value } } }
  }
}
"""

KINDS = (
    "CoreStandardGroup",
    "CoreGraphQLQuery",
    "CoreTransformJinja2",
    "CoreArtifactDefinition",
    "CoreCheckDefinition",
)
"""The objects the group's making and the import put on `main`, besides the repository."""

IDS = "{ " + " ".join(f"{kind} {{ edges {{ node {{ id }} }} }}" for kind in KINDS) + " }"


def names(data: dict[str, Any], kind: str) -> list[str]:
    return [edge["node"]["name"]["value"] for edge in data[kind]["edges"]]


def test_main_holds_the_library_the_group_and_the_registration_in_sync(hub: Hub) -> None:
    assert set(register.library_kinds(SCHEMA)) - register.main_kinds(hub) == set()
    data = hub.gql("main", MAIN, {"group": register.GROUP, "repository": register.REPOSITORY})
    assert data["CoreStandardGroup"]["count"] == 1
    group = data["CoreStandardGroup"]["edges"][0]["node"]["id"]
    [repository] = [edge["node"] for edge in data["CoreReadOnlyRepository"]["edges"]]
    assert repository["sync_status"]["value"] == "in-sync"
    assert repository["operational_status"]["value"] == "online"
    assert re.fullmatch(r"[0-9a-f]{40}", repository["commit"]["value"])
    assert sorted(names(data, "CoreGraphQLQuery")) == ["device_config", "fylgja_branch"]
    assert names(data, "CoreTransformJinja2") == ["device_config"]
    assert data["CoreTransformJinja2"]["edges"][0]["node"]["query"]["node"]["name"]["value"] == "device_config"
    [definition] = [edge["node"] for edge in data["CoreArtifactDefinition"]["edges"]]
    assert definition["name"]["value"] == "device-config"
    assert definition["artifact_name"]["value"] == "device-config"
    assert definition["targets"]["node"]["id"] == group
    checks = sorted(
        (node["name"]["value"], node["file_path"]["value"], node["class_name"]["value"], node["timeout"]["value"])
        for node in (edge["node"] for edge in data["CoreCheckDefinition"]["edges"])
    )
    assert checks == [
        ("fylgja-step", "infrahub/checks/fylgja_step.py", "FylgjaStep", 900),
        ("fylgja-twin", "infrahub/checks/fylgja_twin.py", "FylgjaTwin", 4260),
    ]


def snapshot(hub: Hub) -> tuple[dict[str, set[str]], dict[str, Any]]:
    """The ids of every object of `KINDS` on `main`, and the repository's id, ref and commit."""
    data = hub.gql("main", IDS)
    ids = {kind: {edge["node"]["id"] for edge in data[kind]["edges"]} for kind in KINDS}
    found = register.repository(hub)
    assert found is not None
    return ids, {"id": found.id, "ref": found.ref, "commit": found.commit}


def test_registering_again_changes_nothing(hub: Hub) -> None:
    ids, repository = snapshot(hub)
    register.register(
        hub, ref=repository["ref"], commit=repository["commit"], schema=SCHEMA, clones=register.worker_clones
    )
    assert snapshot(hub) == (ids, repository)
