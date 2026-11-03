import dataclasses
import typing

from fylgja_core import containerlab, documents, schemas
from fylgja_core.driver import Capabilities, Inspection, NodeState


def test_the_local_drivers_capabilities_are_what_the_api_lists() -> None:
    doc = {"name": containerlab.NAME, "default": True, "capabilities": documents.encode(containerlab.CAPABILITIES)}
    assert list(schemas.api_validator("Driver").iter_errors(doc)) == []
    without = {**doc, "capabilities": {k: v for k, v in doc["capabilities"].items() if k != "isolation"}}
    assert not schemas.api_validator("Driver").is_valid(without)
    expected = Capabilities(nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names")
    assert expected == containerlab.CAPABILITIES


def test_an_inspection_is_one_of_three_states_beside_the_nodes() -> None:
    assert typing.get_args(typing.get_type_hints(Inspection)["state"]) == ("absent", "present", "residue")
    assert [f.name for f in dataclasses.fields(Inspection)] == ["state", "nodes"]
    node = NodeState(name="n1", handle="clab-t-n1", incarnation="2026-11-03T12:00:00Z", address="172.20.1.2",
                     running=True)
    assert Inspection(state="present", nodes=(node,)).nodes == (node,)
    assert Inspection(state="residue", nodes=()).state == "residue"
