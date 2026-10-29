"""The mapping's conformance table (specs/017-dcim-reader/contracts/mapping.md §3), ported
from `internal/intent/mapping.go`: every kind the reader reads, with every field it reads,
as the pinned commit of the schema library has them. This module is the one place in the
adapter that knows the library's kinds; `schema.py` compares a branch's schema with it,
field by field, and names the commit in every finding.

The table is what Infrahub 1.11.2's schema endpoint answered for the commit's six files,
not their YAML's text: an attribute with a default reads optional whatever its file says,
so a field the mapping does not require is never held to its optionality. Nothing beyond
the table is checked, so a branch may carry any kind or field of its own beside it.
"""

from dataclasses import dataclass

READER = "infrahub-dcim"
"""The envelope's mapping.reader."""

MODEL = "opsmill/schema-library"
"""The envelope's mapping.model: the model the table was written against."""

VERSION = "26336e9"
"""The envelope's mapping.version: the commit every conformance finding names."""


@dataclass(frozen=True)
class AttributeWant:
    """An attribute as the mapping reads it: its kind (Text, Dropdown, …); whether the
    mapping requires it, so the branch must read optional false; and, for a dropdown, the
    choices the mapping reads, which the branch's must include."""

    name: str
    kind: str
    required: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipWant:
    """A relationship as the mapping reads it: its peer, its kind (Attribute, Component,
    Parent, Generic), its cardinality, and whether the mapping requires it."""

    name: str
    peer: str
    kind: str
    cardinality: str
    required: bool = False


@dataclass(frozen=True)
class KindTable:
    """A kind the mapping reads, with the attributes and relationships it reads. `generic`
    marks a generic the mapping reads a field of through its GraphQL interface, outside any
    inline fragment, so the field must be the generic's and not only an implementer's. A
    generic absent is named by its used_by (USED_BY), never here."""

    kind: str
    attributes: tuple[AttributeWant, ...] = ()
    relationships: tuple[RelationshipWant, ...] = ()
    generic: bool = False

    def fields(self) -> list[str]:
        """The table's fields, attributes first, in the table's order: what `schema check`
        says it verified of the kind."""
        return [a.name for a in self.attributes] + [r.name for r in self.relationships]


@dataclass(frozen=True)
class UsedByWant:
    """A generic the mapping reaches a kind through, and the kind its used_by must name: a
    port's device is a DcimGenericDevice, its connector a DcimConnector, a cable's ends
    DcimEndpoints."""

    generic: str
    implementer: str


TABLES: tuple[KindTable, ...] = (
    KindTable(
        "DcimDevice",
        attributes=(AttributeWant("name", "Text", required=True),),
        relationships=(
            RelationshipWant("tags", "BuiltinTag", "Attribute", "many"),
            RelationshipWant("platform", "DcimPlatform", "Attribute", "one"),
            RelationshipWant("interfaces", "DcimInterface", "Component", "many"),
            # From CoreArtifactTarget: the device's configuration is one of these.
            RelationshipWant("artifacts", "CoreArtifact", "Generic", "many"),
        ),
    ),
    KindTable(
        "DcimPlatform",
        attributes=(AttributeWant("name", "Text", required=True),),
        relationships=(RelationshipWant("manufacturer", "OrganizationManufacturer", "Attribute", "one"),),
    ),
    KindTable("OrganizationManufacturer", attributes=(AttributeWant("name", "Text", required=True),)),
    KindTable(
        "InterfacePhysical",
        attributes=(
            AttributeWant("name", "Text", required=True),
            AttributeWant("role", "Dropdown", choices=("management",)),
            AttributeWant("status", "Dropdown", choices=("disabled",)),
        ),
        relationships=(
            RelationshipWant("device", "DcimGenericDevice", "Parent", "one", required=True),
            RelationshipWant("connector", "DcimConnector", "Attribute", "one"),
        ),
    ),
    KindTable(
        "DcimCable",
        # The Ports query selects the label, which names every cable the read omits.
        attributes=(AttributeWant("label", "Text"),),
        relationships=(RelationshipWant("connected_endpoints", "DcimEndpoint", "Attribute", "many"),),
    ),
    # The Ports query selects a port's connector's connected_endpoints on the generic,
    # outside the DcimCable fragment, so DcimCable declaring it alone does not serve.
    KindTable(
        "DcimConnector",
        generic=True,
        relationships=(RelationshipWant("connected_endpoints", "DcimEndpoint", "Attribute", "many"),),
    ),
)
"""The five kinds the mapping reads, and the one generic it reads a field of, in the order
`schema check` names them."""

USED_BY: tuple[UsedByWant, ...] = (
    UsedByWant("DcimGenericDevice", "DcimDevice"),
    UsedByWant("DcimInterface", "InterfacePhysical"),
    UsedByWant("DcimEndpoint", "InterfacePhysical"),
    UsedByWant("DcimConnector", "DcimCable"),
)
"""The implementers the mapping relies on."""
