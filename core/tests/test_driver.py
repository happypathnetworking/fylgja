import dataclasses
import typing
from pathlib import Path

import yaml

from fylgja_core import containerlab, documents
from fylgja_core.driver import Capabilities, Inspection, NodeState

ROOT = Path(__file__).resolve().parents[2]


def test_the_local_drivers_capabilities_are_what_the_api_lists() -> None:
    # Plan 1 (in flight beside this one) brings schemas.api_validator; until it lands, read the component by hand.
    spec = yaml.safe_load((ROOT / "formats/api-1.openapi.yaml").read_text())
    component = spec["components"]["schemas"]["Driver"]["properties"]["capabilities"]
    doc = documents.encode(containerlab.CAPABILITIES)
    assert set(doc) == set(component["required"]) == set(component["properties"])
    for key, value in doc.items():
        allowed = component["properties"][key].get("enum")
        assert allowed is None or value in allowed, (key, value)
    expected = Capabilities(nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names")
    assert expected == containerlab.CAPABILITIES


def test_an_inspection_is_one_of_three_states_beside_the_nodes() -> None:
    assert typing.get_args(typing.get_type_hints(Inspection)["state"]) == ("absent", "present", "residue")
    assert [f.name for f in dataclasses.fields(Inspection)] == ["state", "nodes"]
    node = NodeState(name="n1", handle="clab-t-n1", incarnation="2026-11-03T12:00:00Z", address="172.20.1.2",
                     running=True)
    assert Inspection(state="present", nodes=(node,)).nodes == (node,)
    assert Inspection(state="residue", nodes=()).state == "residue"
