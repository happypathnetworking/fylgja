"""The example's stage kind, `infrahub/schema/fylgja-stage.yml`: one node, `FylgjaStage`, branch-agnostic, naming its
branch as text and holding no relationship, so a mark is written before any proposed change exists (D-088)."""

from __future__ import annotations

from pathlib import Path

import yaml

KIND_FILE = Path(__file__).resolve().parents[2] / "infrahub" / "schema" / "fylgja-stage.yml"


def test_the_stage_kind_names_its_branch_as_text_and_no_proposed_change() -> None:
    document = yaml.safe_load(KIND_FILE.read_text())
    assert sorted(document) == ["nodes", "version"]
    [node] = document["nodes"]
    assert (node["namespace"], node["name"], node["branch"]) == ("Fylgja", "Stage", "agnostic")
    assert node["uniqueness_constraints"] == [["branch__value", "label__value"]]
    assert "relationships" not in node
    attributes = [(found["name"], found["kind"], found["optional"]) for found in node["attributes"]]
    assert attributes == [
        ("branch", "Text", False),
        ("label", "Text", False),
        ("as_of", "DateTime", True),
        ("description", "Text", True),
    ]
