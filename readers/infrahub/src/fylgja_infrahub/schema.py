"""The schema check: the branch's schema held to the table of every kind and field the mapping reads (D-082).

A query of a kind or a field the branch lacks fails as `Cannot query field`, naming nothing an operator can act on, so
the read holds the branch's schema to `TABLE` first and reads nothing of the network where it differs. Infrahub
records no commit of a loaded schema, and a kind's hash is the instance's, not its file's (design/verified-facts.md,
"Infrahub 1.11.11"), so the check compares names and properties, never a hash: `COMMIT` is the mapping's claim of
the library's commit the table was written from, not a fact read of the instance, and every finding names it.
`GET /api/schema` has no time axis, so the schema checked is the branch's present one whatever time the read is pinned
to, and a pinned query is checked against that same present schema.

The table's properties are those Infrahub 1.11.11 answered on `main` for the library at `COMMIT`, where
`InterfacePhysical.status`, which has a default, reads optional though its file declares it required
(design/verified-facts.md, "Infrahub 1.11.11").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fylgja_core.findings import Finding, order

from fylgja_infrahub.rows import Attribute, Kind, Relationship, Schema

# Rule ids. Callers and tests match on them (rules.md).
RULE_KIND_MISSING = "schema.kind.missing"
RULE_FIELD_MISSING = "schema.field.missing"
RULE_FIELD_MISMATCH = "schema.field.mismatch"
RULE_CHOICE_MISSING = "schema.choice.missing"
RULE_USED_BY_MISSING = "schema.used_by.missing"

READER = "infrahub-dcim"
"""The envelope's `mapping.reader`: the mapping's name."""

MODEL = "opsmill/schema-library"
"""The envelope's `mapping.model`: the model the table was written from."""

COMMIT = "26336e9026dff1907f2c58e81dd6ae7b5c3f763e"
"""The envelope's `mapping.version`: the library's commit the table was written from, `infrahub/schema/dcim/COMMIT`,
which the development Infrahub loads. A literal, since the wheel carries no file of the tree; a test holds it to the
file."""


@dataclass(frozen=True)
class Table:
    """What the mapping reads of a branch's schema, in the rows' own terms (rows.py): its nodes and its generics by
    kind, each with the attributes and relationships the mapping reads. An attribute's kind, a relationship's peer,
    kind and cardinality must be the branch's; `optional` false says the mapping requires the field, which the
    branch must then not read optional, and true that the mapping does without it, so the branch may read either.
    `choices` are the dropdown's choices the mapping reads, which the branch's must include, and a generic's
    `used_by` the kinds the mapping reaches through it, which the branch's must name."""

    nodes: Mapping[str, Kind]
    generics: Mapping[str, Kind]


TABLE = Table(
    nodes={
        "DcimDevice": Kind(
            {"name": Attribute("Text", optional=False)},
            {
                "tags": Relationship("BuiltinTag", "Attribute", "many", optional=True),
                "platform": Relationship("DcimPlatform", "Attribute", "one", optional=True),
                "interfaces": Relationship("DcimInterface", "Component", "many", optional=True),
                # From CoreArtifactTarget: the device's configuration is one of these.
                "artifacts": Relationship("CoreArtifact", "Generic", "many", optional=True),
            },
        ),
        "DcimPlatform": Kind(
            {"name": Attribute("Text", optional=False)},
            {"manufacturer": Relationship("OrganizationManufacturer", "Attribute", "one", optional=True)},
        ),
        "OrganizationManufacturer": Kind({"name": Attribute("Text", optional=False)}, {}),
        "InterfacePhysical": Kind(
            {
                "name": Attribute("Text", optional=False),
                "role": Attribute("Dropdown", optional=True, choices=("management",)),
                "status": Attribute("Dropdown", optional=True, choices=("disabled",)),
            },
            {
                "device": Relationship("DcimGenericDevice", "Parent", "one", optional=False),
                "connector": Relationship("DcimConnector", "Attribute", "one", optional=True),
                # The stamps of a port's addresses are read under it.
                "ip_addresses": Relationship("IpamIPAddress", "Attribute", "many", optional=True),
            },
        ),
        "IpamIPAddress": Kind(
            {"address": Attribute("IPHost", optional=False)},
            {"interface": Relationship("InterfaceLayer3", "Attribute", "one", optional=True)},
        ),
        "DcimCable": Kind(
            # The label names every cable a read omits.
            {"label": Attribute("Text", optional=True)},
            {"connected_endpoints": Relationship("DcimEndpoint", "Attribute", "many", optional=True)},
        ),
    },
    generics={
        # The ports query selects a connector's ends on the generic, outside the DcimCable fragment, so DcimCable
        # declaring them alone does not serve.
        "DcimConnector": Kind(
            {},
            {"connected_endpoints": Relationship("DcimEndpoint", "Attribute", "many", optional=True)},
            ("DcimCable",),
        ),
        # A port's device is a DcimGenericDevice, a device's interfaces DcimInterfaces, a cable's ends DcimEndpoints.
        # The stale rule's cable stamps read selects a cable end's name and its device on DcimInterface (P3-33), and
        # that device's name on DcimGenericDevice (P3-34).
        "DcimGenericDevice": Kind({"name": Attribute("Text", optional=False)}, {}, ("DcimDevice",)),
        "DcimInterface": Kind(
            {"name": Attribute("Text", optional=False)},
            {"device": Relationship("DcimGenericDevice", "Parent", "one", optional=False)},
            ("InterfacePhysical",),
        ),
        "DcimEndpoint": Kind({}, {}, ("InterfacePhysical",)),
        # The stale rule's stamps read selects an interface's addresses on the generic (P3-32). The mapping requires a
        # physical port's alone; a virtual interface's are read where the branch has the kind (P3-35).
        "InterfaceLayer3": Kind(
            {},
            {"ip_addresses": Relationship("IpamIPAddress", "Attribute", "many", optional=True)},
            ("InterfacePhysical",),
        ),
    },
)
"""The six node kinds the mapping reads, and the five generics it reads a field of or reaches a kind through."""


def check(schema: Schema, *, branch: str) -> tuple[Finding, ...]:
    """Every way the present schema of `branch` differs from `TABLE`, in one pass and in a result's order
    (findings.order); none where it holds every kind, field, choice and user the table names as the table has them.
    A kind absent, a node or a generic, is named once, and neither its fields nor its place among a generic's users
    beside it; a field is one finding however many of its properties differ; nothing the table does not name is
    reported."""
    absent = {kind for kind in TABLE.nodes if kind not in schema.nodes}
    absent |= {kind for kind in TABLE.generics if kind not in schema.generics}
    found: list[Finding] = []
    for wanted, held, what in ((TABLE.nodes, schema.nodes, "kind"), (TABLE.generics, schema.generics, "generic")):
        for kind, want in wanted.items():
            got = held.get(kind)
            if got is None:
                found.append(_finding(RULE_KIND_MISSING, kind, branch, f"has no {what} {kind}"))
                continue
            found.extend(_fields(kind, want, got, branch))
            users = [user for user in want.used_by if user not in got.used_by and user not in absent]
            if users:
                said = f"does not list {' and '.join(users)} in the used_by of the generic {kind}"
                reads = f"through which the mapping reads {'them' if len(users) > 1 else 'it'}"
                found.append(_finding(RULE_USED_BY_MISSING, kind, branch, said, reads))
    return order(found)


def _fields(kind: str, want: Kind, got: Kind, branch: str) -> list[Finding]:
    """What differs of the fields of `kind` the table names: at most one finding a field."""
    found = [
        _attribute(kind, name, wanted, got.attributes.get(name), branch) for name, wanted in want.attributes.items()
    ]
    found += [
        _relationship(kind, name, wanted, got.relationships.get(name), branch)
        for name, wanted in want.relationships.items()
    ]
    return [finding for finding in found if finding is not None]


def _attribute(kind: str, name: str, wanted: Attribute, held: Attribute | None, branch: str) -> Finding | None:
    """The attribute's one finding: missing; else a mismatch of its kind or optionality; else a choice missing."""
    field = f"{kind}.{name}"
    if held is None:
        return _finding(RULE_FIELD_MISSING, field, branch, f"gives {kind} no attribute {name}")
    differs = _differences(("kind", wanted.kind, held.kind), *_optional(wanted.optional, held.optional))
    if differs:
        return _finding(RULE_FIELD_MISMATCH, field, branch, f"differs at the attribute {field} ({differs})")
    lacking = [choice for choice in wanted.choices if choice not in held.choices]
    if lacking:
        said = f"gives the dropdown {field} no choice {' or '.join(lacking)}"
        return _finding(RULE_CHOICE_MISSING, field, branch, said)
    return None


def _relationship(kind: str, name: str, wanted: Relationship, held: Relationship | None, branch: str) -> Finding | None:
    """The relationship's one finding: missing; else a mismatch of its peer, kind, cardinality or optionality."""
    field = f"{kind}.{name}"
    if held is None:
        return _finding(RULE_FIELD_MISSING, field, branch, f"gives {kind} no relationship {name}")
    differs = _differences(
        ("peer", wanted.peer, held.peer),
        ("kind", wanted.kind, held.kind),
        ("cardinality", wanted.cardinality, held.cardinality),
        *_optional(wanted.optional, held.optional),
    )
    if differs:
        return _finding(RULE_FIELD_MISMATCH, field, branch, f"differs at the relationship {field} ({differs})")
    return None


def _optional(wanted: bool, held: bool) -> tuple[tuple[str, str, str], ...]:
    """Optionality as a property that differs only where the table requires the field and the branch does not."""
    return (("optional", "false", "true"),) if not wanted and held else ()


def _differences(*properties: tuple[str, str, str]) -> str:
    """Each property whose value differs, the table's first (`kind Text, found Number`), joined by `; `."""
    return "; ".join(f"{name} {wanted}, found {held}" for name, wanted, held in properties if wanted != held)


def _finding(rule: str, what: str, branch: str, said: str, reads: str = "which the mapping reads") -> Finding:
    message = f"Branch {branch}'s present schema {said}, {reads} as it is at {MODEL}@{COMMIT}."
    return Finding(rule=rule, severity="error", object=what, message=message)
