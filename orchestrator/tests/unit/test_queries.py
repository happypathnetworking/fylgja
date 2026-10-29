"""The eleven queries against `internal/intent`'s readonly_test.go: every one a query, its
roots the mapping's or a named one of Fylgja's or Infrahub's own, its fragments on the
mapping's kinds or two of Infrahub's, and the scope's tag read by its filter alone. And,
while the Go reader stands, each held to `internal/intent/queries.graphql` token by token
(the comparison is removed with the Go reader, T035)."""

import re

import pytest

from fylgja_orchestrator.adapters.infrahub import queries

from .dcim import REPO

GO_QUERIES = REPO / "internal" / "intent" / "queries.graphql"

_TOKEN = re.compile(r"\.\.\.|[_A-Za-z][_0-9A-Za-z]*|\$[_A-Za-z][_0-9A-Za-z]*|\"[^\"]*\"|[{}()\[\]:!,=@]|-?\d+")


def tokens(doc: str) -> list[str]:
    """A document's tokens, its comments dropped (genqlient's directives among them)."""
    return _TOKEN.findall(re.sub(r"#[^\n]*", "", doc))


def definitions(doc: str) -> dict[str, list[str]]:
    """Each top-level definition of a document by its name, as its tokens."""
    out = {}
    toks = tokens(doc)
    i = 0
    while i < len(toks):
        kind, name = toks[i], toks[i + 1]
        assert kind in ("query", "fragment"), f"a definition begins {kind!r}"
        j = toks.index("{", i)
        depth = 0
        while True:
            if toks[j] == "{":
                depth += 1
            elif toks[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out[name] = toks[i : j + 1]
        i = j + 1
    return out


def roots(doc: str) -> list[str]:
    """The fields a document's query selects at its top level."""
    toks = definitions(doc)
    (query,) = [d for d in toks.values() if d[0] == "query"]
    start = query.index("{", query.index(")") if ")" in query else 0)
    out, depth, j = [], 0, start
    while j < len(query):
        t = query[j]
        if t in "{(":
            depth += 1
        elif t in "})":
            depth -= 1
        elif depth == 1 and re.fullmatch(r"[_A-Za-z]\w*", t):
            out.append(t)
        j += 1
    return out


def test_the_eleven_are_every_operation_and_each_names_its_own():
    assert len(queries.ALL) == 11
    for name, doc in queries.ALL.items():
        defs = definitions(doc)
        assert [d for d in defs if defs[d][0] == "query"] == [name]
        toks = defs[name]
        spread = {toks[k + 1] for k, t in enumerate(toks) if t == "..." and toks[k + 1] != "on"}
        assert {d for d in defs if defs[d][0] == "fragment"} == spread, f"{name} carries a fragment it does not spread"


@pytest.mark.skipif(not GO_QUERIES.exists(), reason="the Go reader's queries.graphql is gone (T035)")
@pytest.mark.parametrize("name", sorted(queries.ALL))
def test_each_query_is_the_go_readers(name):
    """Token for token, but `__typename`, which genqlient added itself to every abstract
    selection and the adapter writes where it reads it."""
    go = definitions(GO_QUERIES.read_text())
    for definition, toks in definitions(queries.ALL[name]).items():
        want = [t for t in go[definition] if t != "__typename"]
        assert [t for t in toks if t != "__typename"] == want, f"{name}'s {definition} differs from queries.graphql"


def test_the_event_query_reads_the_events_type():
    assert "__typename" in tokens(queries.INTENT_EVENTS)


def test_every_operation_is_a_query():
    for name, doc in queries.ALL.items():
        kinds = re.findall(r"(?m)^\s*(query|mutation|subscription)\b", doc)
        assert kinds == ["query"], f"operation {name}: {kinds}"
        assert "mutation" not in doc.lower()


MAPPING_ROOTS = {"DcimDevice": {"Devices", "IntentStamps"}, "InterfacePhysical": {"Ports", "PortStamps"}}
OWNED_ROOTS = {
    "FylgjaStage": "OrphanStages",
    "FylgjaProbe": "Probes",
    "CoreProposedChange": "ProposedChanges",
    "CoreArtifactValidator": "ArtifactValidations",
    "Branch": "BranchPoint",
    "InfrahubEvent": "IntentEvents",
    "CoreGraphQLQueryGroup": "QueryGroups",
}


def test_query_roots_are_the_mappings():
    for name, doc in queries.ALL.items():
        found = roots(doc)
        assert found, f"operation {name} selects no root"
        for r in found:
            if r in MAPPING_ROOTS:
                assert name in MAPPING_ROOTS[r]
            else:
                assert OWNED_ROOTS.get(r) == name, f"operation {name} selects {r}"
    for root, readers in MAPPING_ROOTS.items():
        for op in readers:
            assert root in roots(queries.ALL[op])
    for root, op in OWNED_ROOTS.items():
        assert root in roots(queries.ALL[op])


FRAGMENT_TARGETS = {"DcimDevice", "DcimPlatform", "InterfacePhysical", "DcimCable", "CoreArtifactTarget",
                    "NodeMutatedEvent"}


def test_fragment_targets_are_the_mappings():
    used = set()
    for name, doc in queries.ALL.items():
        for target in re.findall(r"(?:\bfragment\s+\w+|\.\.\.)\s+on\s+(\w+)", doc):
            used.add(target)
            assert target in FRAGMENT_TARGETS, f"operation {name} has a fragment on {target}"
    assert {"CoreArtifactTarget", "NodeMutatedEvent"} <= used


def test_the_tag_is_read_by_its_filter_alone():
    for name, doc in queries.ALL.items():
        assert "BuiltinTag" not in doc
        found = re.findall(r"\btags\w*", doc)
        assert all(f == "tags__name__value" for f in found)
        assert ("tags__name__value" in found) == (name in {"Devices", "IntentStamps"})
