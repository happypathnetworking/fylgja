"""Conformance: a branch's schema against the mapping's table (Constitution III; FR-012),
ported from `internal/intent`'s schemainfo.go and conformance.go.

It reads the schema endpoint, never a failed query: on a branch without the library a
query of its kinds fails as "cannot query field", naming nothing an operator can act on,
while the endpoint answers which kind, which field and which property differs.

Every finding is a rejection naming the commit, and all come in one pass, so one run shows
an operator setting a branch up everything that differs. A kind absent is named once:
neither its fields nor the generics it should implement are named again beside it. A
generic the table reads a field of is named by its used_by when absent, and by its field
when present without it. Nothing beyond the table is reported.
"""

from dataclasses import dataclass, field

from fylgja_orchestrator.adapters.infrahub import mapping
from fylgja_orchestrator.documents.findings import Findings

RULE_KIND_MISSING = "schema.kind.missing"
RULE_FIELD_MISSING = "schema.field.missing"
RULE_FIELD_MISMATCH = "schema.field.mismatch"
RULE_CHOICE_MISSING = "schema.choice.missing"
RULE_USED_BY_MISSING = "schema.used_by.missing"

AS_THE_LIBRARY = f"as {mapping.MODEL}@{mapping.VERSION} has it"
READS_IT = "; the mapping reads it " + AS_THE_LIBRARY
"""What ends every finding but used_by's: the commit an operator compares their schema with."""


@dataclass(frozen=True)
class AttributeSchema:
    """An attribute as the endpoint reports it. `optional` is the endpoint's, true for any
    attribute with a default whatever its file says; `choices` a dropdown's names."""

    kind: str
    optional: bool
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipSchema:
    peer: str
    kind: str
    cardinality: str
    optional: bool


@dataclass
class NodeSchema:
    """A node kind or a generic, its inherited fields merged in, as the endpoint reports it."""

    attributes: dict[str, AttributeSchema] = field(default_factory=dict)
    relationships: dict[str, RelationshipSchema] = field(default_factory=dict)


@dataclass
class SchemaInfo:
    """What the schema endpoint says of a branch: its hash (the envelope's schema_hash, the
    branch's at the read's time even for a pinned read, since the endpoint has no time
    axis), which kinds implement each generic, and each node's and generic's fields."""

    hash: str
    used_by: dict[str, list[str]] = field(default_factory=dict)
    nodes: dict[str, NodeSchema] = field(default_factory=dict)
    generics: dict[str, NodeSchema] = field(default_factory=dict)

    def implementers(self, generic: str) -> list[str]:
        """The kinds implementing a generic, sorted."""
        return sorted(self.used_by.get(generic) or [])


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _node(doc: dict) -> NodeSchema:
    node = NodeSchema()
    for a in doc.get("attributes") or []:
        choices = tuple(_str(c.get("name")) for c in a.get("choices") or [] if isinstance(c, dict))
        node.attributes[_str(a.get("name"))] = AttributeSchema(_str(a.get("kind")), bool(a.get("optional")), choices)
    for r in doc.get("relationships") or []:
        node.relationships[_str(r.get("name"))] = RelationshipSchema(
            _str(r.get("peer")), _str(r.get("kind")), _str(r.get("cardinality")), bool(r.get("optional"))
        )
    return node


def parse(doc: dict) -> SchemaInfo:
    """A `GET /api/schema` document as SchemaInfo. The caller has held it to name a hash."""
    info = SchemaInfo(hash=_str(doc.get("main")))
    for g in doc.get("generics") or []:
        kind = _str(g.get("kind"))
        info.used_by[kind] = list(g.get("used_by") or [])
        info.generics[kind] = _node(g)
    for n in doc.get("nodes") or []:
        info.nodes[_str(n.get("kind"))] = _node(n)
    return info


def schema_info(client) -> SchemaInfo:
    """The branch's schema, read with no `at`."""
    return parse(client.schema_document())


@dataclass
class Conformance:
    """What a check verified: the branch's schema hash, the model and commit the table was
    written against, and every kind of the table with its fields, in its order."""

    schema_hash: str
    model: str = mapping.MODEL
    version: str = mapping.VERSION
    kinds: list[tuple[str, list[str]]] = field(default_factory=list)

    def verified(self) -> dict:
        """A schema check's success detail, as the core's `findings.Verified` shapes it."""
        return {
            "model": self.model,
            "version": self.version,
            "kinds": [{"kind": k, "fields": list(f)} for k, f in self.kinds],
        }


class ConformanceError(Exception):
    """A branch whose schema does not hold what the mapping reads, found before a stamps
    read of it, whose queries would fail naming nothing of the table. The stages file its
    findings as the command's refusal, exit 1."""

    def __init__(self, branch: str, findings: Findings):
        self.branch = branch
        self.findings = findings
        what = ", ".join(f"{f.rule} {f.object}" for f in findings)
        super().__init__(f"branch {branch} does not conform to {mapping.MODEL}@{mapping.VERSION}: {what}")


def check_conformance(client) -> tuple[Conformance, Findings]:
    """Compares the branch's schema with the table before any intent is read."""
    info = schema_info(client)
    conf = Conformance(schema_hash=info.hash, kinds=[(k.kind, k.fields()) for k in mapping.TABLES])
    return conf, conformance_findings(info)


def _differences(pairs) -> str:
    """Each property that differs, expected first (`kind Text, found Number`), joined by
    "; ", so one field is one finding however many of its properties differ."""
    return "; ".join(f"{prop} {want}, found {got}" for prop, want, got in pairs if want != got)


def attribute_differs(want: mapping.AttributeWant, got: AttributeSchema) -> str:
    """A required attribute must read optional false; one the table leaves optional may
    read either."""
    pairs = [("kind", want.kind, got.kind)]
    if want.required and got.optional:
        pairs.append(("optional", "false", "true"))
    return _differences(pairs)


def relationship_differs(want: mapping.RelationshipWant, got: RelationshipSchema) -> str:
    pairs = [
        ("peer", want.peer, got.peer),
        ("kind", want.kind, got.kind),
        ("cardinality", want.cardinality, got.cardinality),
    ]
    if want.required and got.optional:
        pairs.append(("optional", "false", "true"))
    return _differences(pairs)


def conformance_findings(info: SchemaInfo) -> Findings:
    """The table walked against one branch's schema: every difference, in the table's order
    and then the generics'."""
    found = Findings()
    absent = set()
    for k in mapping.TABLES:
        if k.generic:
            # Absent, it is the one schema.used_by.missing below, not named twice.
            node = info.generics.get(k.kind)
            if node is None:
                continue
        else:
            node = info.nodes.get(k.kind)
            if node is None:
                absent.add(k.kind)
                found.reject(RULE_KIND_MISSING, k.kind, f"the branch's schema has no kind {k.kind}{READS_IT}")
                continue
        for want in k.attributes:
            name = f"{k.kind}.{want.name}"
            got = node.attributes.get(want.name)
            if got is None:
                found.reject(RULE_FIELD_MISSING, name, f"{k.kind} has no attribute {want.name}{READS_IT}")
                continue
            differs = attribute_differs(want, got)
            if differs:
                found.reject(RULE_FIELD_MISMATCH, name, differs + READS_IT)
                continue
            for choice in want.choices:
                if choice not in got.choices:
                    found.reject(RULE_CHOICE_MISSING, name, f"the dropdown has no choice {choice}{READS_IT}")
        for want in k.relationships:
            name = f"{k.kind}.{want.name}"
            got = node.relationships.get(want.name)
            if got is None:
                found.reject(RULE_FIELD_MISSING, name, f"{k.kind} has no relationship {want.name}{READS_IT}")
                continue
            differs = relationship_differs(want, got)
            if differs:
                found.reject(RULE_FIELD_MISMATCH, name, differs + READS_IT)
    for want in mapping.USED_BY:
        if want.implementer in absent or want.implementer in (info.used_by.get(want.generic) or []):
            continue
        through = f"; the mapping reads {want.implementer} through it {AS_THE_LIBRARY}"
        if want.generic not in info.used_by:
            message = f"the branch's schema has no generic {want.generic}{through}"
        else:
            message = f"{want.implementer} does not implement {want.generic}{through}"
        found.reject(RULE_USED_BY_MISSING, want.generic, message)
    return found
