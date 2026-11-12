"""The schema check: a branch's schema held to the table of what the mapping reads, each difference a named finding,
all in one pass, each naming the branch and the commit the table was written from (D-082)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest
from fake import dcim_schema

from fylgja_infrahub import schema
from fylgja_infrahub.rows import Attribute, Kind, Relationship, Schema
from fylgja_infrahub.schema import (
    COMMIT,
    MODEL,
    READER,
    RULE_CHOICE_MISSING,
    RULE_FIELD_MISMATCH,
    RULE_FIELD_MISSING,
    RULE_KIND_MISSING,
    RULE_USED_BY_MISSING,
    TABLE,
    check,
)

ROOT = Path(__file__).resolve().parents[3]
BRANCH = "fc-branch"

S = dcim_schema()
ROLE = S.nodes["InterfacePhysical"].attributes["role"]


def node(schema: Schema, kind: str, changed: Kind) -> Schema:
    """`schema` with its node `kind` set to `changed`."""
    return dataclasses.replace(schema, nodes={**schema.nodes, kind: changed})


def generic(schema: Schema, kind: str, used_by: tuple[str, ...]) -> Schema:
    """`schema` with its generic `kind` used by `used_by` alone."""
    changed = dataclasses.replace(schema.generics[kind], used_by=used_by)
    return dataclasses.replace(schema, generics={**schema.generics, kind: changed})


def without(schema: Schema, kind: str) -> Schema:
    """`schema` with no node and no generic `kind`."""
    nodes = {key: value for key, value in schema.nodes.items() if key != kind}
    generics = {key: value for key, value in schema.generics.items() if key != kind}
    return dataclasses.replace(schema, nodes=nodes, generics=generics)


def attribute(schema: Schema, kind: str, name: str, held: Attribute | None) -> Schema:
    """`schema` with the attribute `name` of the node `kind` set to `held`, or removed where it is None."""
    was = schema.nodes[kind]
    attributes = {key: value for key, value in was.attributes.items() if key != name}
    changed = dataclasses.replace(was, attributes=attributes if held is None else {**attributes, name: held})
    return node(schema, kind, changed)


def relationship(schema: Schema, kind: str, name: str, held: Relationship | None) -> Schema:
    """`schema` with the relationship `name` of the node `kind` set to `held`, or removed where it is None."""
    was = schema.nodes[kind]
    relationships = {key: value for key, value in was.relationships.items() if key != name}
    changed = dataclasses.replace(was, relationships=relationships if held is None else {**relationships, name: held})
    return node(schema, kind, changed)


def found(schema: Schema) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in check(schema, branch=BRANCH)]


def test_the_commit_is_the_one_the_seed_loads() -> None:
    assert (ROOT / "infrahub" / "schema" / "dcim" / "COMMIT").read_text().strip() == COMMIT
    assert (MODEL, READER) == ("opsmill/schema-library", "infrahub-dcim")


def test_the_librarys_schema_conforms() -> None:
    assert check(dcim_schema(), branch=BRANCH) == ()


def test_the_table_names_what_the_mapping_reads() -> None:
    fields = {
        kind: (sorted(want.attributes), sorted(want.relationships), want.used_by)
        for kind, want in {**TABLE.nodes, **TABLE.generics}.items()
    }
    assert fields == {
        "DcimDevice": (["name"], ["artifacts", "interfaces", "platform", "tags"], ()),
        "DcimPlatform": (["name"], ["manufacturer"], ()),
        "OrganizationManufacturer": (["name"], [], ()),
        "InterfacePhysical": (["name", "role", "status"], ["connector", "device", "ip_addresses"], ()),
        "IpamIPAddress": (["address"], ["interface"], ()),
        "DcimCable": (["label"], ["connected_endpoints"], ()),
        "DcimConnector": ([], ["connected_endpoints"], ("DcimCable",)),
        "DcimGenericDevice": (["name"], [], ("DcimDevice",)),
        "DcimInterface": (["name"], ["device"], ("InterfacePhysical",)),
        "DcimEndpoint": ([], [], ("InterfacePhysical",)),
        "InterfaceLayer3": ([], ["ip_addresses"], ("InterfacePhysical",)),
    }
    # The stale rule's cable stamps read selects a cable end's name and its device on the generic (P3-33), and that
    # device's name on its own generic (P3-34).
    interface = TABLE.generics["DcimInterface"]
    assert interface.attributes["name"] == Attribute("Text", optional=False)
    assert interface.relationships["device"] == Relationship("DcimGenericDevice", "Parent", "one", optional=False)
    assert TABLE.generics["DcimGenericDevice"].attributes["name"] == Attribute("Text", optional=False)
    physical = TABLE.nodes["InterfacePhysical"]
    assert physical.attributes["role"].choices == ("management",)
    assert physical.attributes["status"].choices == ("disabled",)
    assert physical.relationships["ip_addresses"] == Relationship("IpamIPAddress", "Attribute", "many", optional=True)
    # The stale rule's stamps read selects an interface's addresses on the generic, both kinds inheriting it (P3-32).
    layer3 = TABLE.generics["InterfaceLayer3"].relationships["ip_addresses"]
    assert layer3 == Relationship("IpamIPAddress", "Attribute", "many", optional=True)


DIFFERENCES: dict[str, tuple[Callable[[], Schema], tuple[str, str]]] = {
    "a kind removed": (lambda: without(S, "DcimCable"), (RULE_KIND_MISSING, "DcimCable")),
    "an attribute removed": (
        lambda: attribute(S, "DcimCable", "label", None),
        (RULE_FIELD_MISSING, "DcimCable.label"),
    ),
    "an attribute of another kind, and optional": (
        lambda: attribute(S, "DcimPlatform", "name", Attribute("Number", optional=True)),
        (RULE_FIELD_MISMATCH, "DcimPlatform.name"),
    ),
    "a dropdown without a choice": (
        lambda: attribute(S, "InterfacePhysical", "role", dataclasses.replace(ROLE, choices=("core", "access"))),
        (RULE_CHOICE_MISSING, "InterfacePhysical.role"),
    ),
    "a generic's users without a kind": (
        lambda: generic(S, "DcimConnector", used_by=()),
        (RULE_USED_BY_MISSING, "DcimConnector"),
    ),
    "a relationship removed": (
        lambda: relationship(S, "InterfacePhysical", "device", None),
        (RULE_FIELD_MISSING, "InterfacePhysical.device"),
    ),
    "a relationship to another peer, and optional": (
        lambda: relationship(
            S, "InterfacePhysical", "device", Relationship("DcimDevice", "Parent", "one", optional=True)
        ),
        (RULE_FIELD_MISMATCH, "InterfacePhysical.device"),
    ),
    "a generic removed": (lambda: without(S, "DcimConnector"), (RULE_KIND_MISSING, "DcimConnector")),
    "a kind removed, and from its generic's users": (
        lambda: generic(without(S, "DcimCable"), "DcimConnector", used_by=()),
        (RULE_KIND_MISSING, "DcimCable"),
    ),
    "a node held as a generic alone": (
        lambda: dataclasses.replace(
            without(S, "DcimDevice"), generics={**S.generics, "DcimDevice": S.nodes["DcimDevice"]}
        ),
        (RULE_KIND_MISSING, "DcimDevice"),
    ),
}


@pytest.mark.parametrize("difference", list(DIFFERENCES))
def test_each_difference_is_its_rule(difference: str) -> None:
    make, expected = DIFFERENCES[difference]
    findings = check(make(), branch=BRANCH)
    assert [(finding.rule, finding.object) for finding in findings] == [expected]
    (finding,) = findings
    assert finding.severity == "error"
    assert finding.message.startswith(f"Branch {BRANCH}'s present schema ")
    assert finding.message.endswith(f" {MODEL}@{COMMIT}.")


def test_a_generics_users_missing_are_named_in_one_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every generic of the table has one user, so a table of a generic with two stands in for one to come."""
    interface = dataclasses.replace(TABLE.generics["DcimInterface"], used_by=("InterfacePhysical", "InterfaceVirtual"))
    table = dataclasses.replace(TABLE, generics={**TABLE.generics, "DcimInterface": interface})
    monkeypatch.setattr(schema, "TABLE", table)
    (finding,) = check(generic(S, "DcimInterface", used_by=()), branch=BRANCH)
    assert (finding.rule, finding.object) == (RULE_USED_BY_MISSING, "DcimInterface")
    assert finding.message == (
        f"Branch {BRANCH}'s present schema does not list InterfacePhysical and InterfaceVirtual in the used_by of the "
        f"generic DcimInterface, through which the mapping reads them as it is at {MODEL}@{COMMIT}."
    )


def test_a_field_is_one_finding_however_many_of_its_properties_differ() -> None:
    (finding,) = check(attribute(S, "DcimPlatform", "name", Attribute("Number", optional=True)), branch=BRANCH)
    assert "kind Text, found Number; optional false, found true" in finding.message

    held = Relationship("DcimDevice", "Component", "many", optional=True)
    (finding,) = check(relationship(S, "InterfacePhysical", "device", held), branch=BRANCH)
    expected = "peer DcimGenericDevice, found DcimDevice; kind Parent, found Component; cardinality one, found many; "
    assert expected + "optional false, found true" in finding.message

    text = attribute(S, "InterfacePhysical", "role", Attribute("Text", optional=True))
    assert found(text) == [(RULE_FIELD_MISMATCH, "InterfacePhysical.role")], "a mismatch, and no choice beside it"


def test_a_field_the_table_leaves_optional_may_read_required() -> None:
    schema = attribute(S, "DcimCable", "label", Attribute("Text", optional=False))
    platform = Relationship("DcimPlatform", "Attribute", "one", optional=False)
    assert found(relationship(schema, "DcimDevice", "platform", platform)) == []


def test_a_kind_absent_is_named_once() -> None:
    """Neither its fields nor its place among a generic's users are named beside it."""
    schema = without(S, "InterfacePhysical")
    schema = generic(generic(schema, "DcimInterface", used_by=()), "DcimEndpoint", used_by=())
    assert found(schema) == [(RULE_KIND_MISSING, "InterfacePhysical")]


def test_every_difference_comes_in_one_pass() -> None:
    schema = attribute(S, "DcimCable", "label", None)
    schema = attribute(schema, "DcimPlatform", "name", Attribute("Number", optional=True))
    schema = attribute(schema, "InterfacePhysical", "role", dataclasses.replace(ROLE, choices=()))
    assert found(schema) == [
        (RULE_CHOICE_MISSING, "InterfacePhysical.role"),
        (RULE_FIELD_MISMATCH, "DcimPlatform.name"),
        (RULE_FIELD_MISSING, "DcimCable.label"),
    ]


def test_what_the_table_does_not_name_is_not_reported() -> None:
    ours = Kind(
        {"note": Attribute("Text", optional=True)},
        {"device": Relationship("DcimDevice", "Attribute", "one", optional=True)},
    )
    schema = node(S, "FylgjaSiteNote", ours)
    schema = attribute(schema, "DcimDevice", "site_note", Attribute("Text", optional=True))
    schema = attribute(schema, "InterfacePhysical", "role", dataclasses.replace(ROLE, choices=("core", *ROLE.choices)))
    schema = generic(schema, "DcimInterface", used_by=("InterfacePhysical", "InterfaceVirtual"))
    assert check(schema, branch=BRANCH) == ()


def test_the_message_names_the_branch_and_the_commit() -> None:
    (finding,) = check(attribute(S, "InterfacePhysical", "role", dataclasses.replace(ROLE, choices=())), branch="third")
    assert finding.message == (
        "Branch third's present schema gives the dropdown InterfacePhysical.role no choice management, which the "
        f"mapping reads as it is at {MODEL}@{COMMIT}."
    )
