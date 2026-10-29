"""The default branch's proposed changes, stages and branches as the reader asks for them,
carried over from `internal/intent/stages_test.go`, each named as its Go test in snake case,
on the fake Infrahub of `conftest`, answered through the SDK's own transport."""

import json
import random

import pytest

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub import stage_reader as sr
from fylgja_orchestrator.adapters.infrahub.client import DefaultClient
from fylgja_orchestrator.adapters.infrahub.read import ReadError

from .conftest import ADDRESS, TOKEN


class Stages:
    """An Infrahub holding the stage kind (or not), open proposed changes with their marks,
    orphaned marks, branches and artifact validators, on the two unnamed endpoints."""

    def __init__(self, infrahub, attributes=None, no_relationship=False, no_extension=False):
        self.infrahub = infrahub
        self.proposed, self.orphans, self.branches, self.validators = [], [], [], []
        pc_rels = [{"name": "validations", "peer": "CoreValidator"}]
        if not no_extension:
            pc_rels.append({"name": sr.STAGE_EXTENSION, "peer": sr.STAGE_KIND})
        nodes = [
            {"kind": "DcimDevice", "attributes": [{"name": "name"}]},
            {"kind": sr.PROPOSED_CHANGE_KIND, "branch": "agnostic",
             "attributes": [{"name": "name"}, {"name": "source_branch"}], "relationships": pc_rels},
        ]
        if attributes is not None:
            rels = [{"name": "member_of_groups", "peer": "CoreGroup"}]
            if not no_relationship:
                rels.append({"name": sr.STAGE_RELATIONSHIP, "peer": sr.PROPOSED_CHANGE_KIND})
            nodes.append({"kind": sr.STAGE_KIND, "branch": "agnostic",
                          "attributes": [{"name": a} for a in attributes], "relationships": rels})
        infrahub.default_schema = {"main": "a8045729", "nodes": nodes}
        ops = infrahub.default_operations
        ops["ProposedChanges"] = self._proposed
        ops["OrphanStages"] = lambda v, q, b, p: {"data": {"FylgjaStage": page(self.orphans, v)}}
        ops["BranchPoint"] = lambda v, q, b, p: {
            "data": {"Branch": [x for x in self.branches if x["name"] == v["name"]]}}
        ops["ArtifactValidations"] = lambda v, q, b, p: {
            "data": {"CoreArtifactValidator": {"edges": [{"node": n} for n in self.validators]}}}
        self.reader = sr.StageReader(DefaultClient(ADDRESS, TOKEN, requester=infrahub))

    def _proposed(self, variables, query, branch, params):
        open_ = [pc for pc in self.proposed
                 if "branch" not in variables or pc["source_branch"]["value"] == variables["branch"]]
        return {"data": {"CoreProposedChange": page(open_, variables)}}


def page(nodes, variables):
    offset, limit = variables["offset"], variables["limit"]
    return {"count": len(nodes), "edges": [{"node": n} for n in nodes[offset:offset + limit]]}


def stage_node(id, label, written_at, at, description):
    """One mark as Infrahub's GraphQL answers it; at "" an unwritten as_of, answered null."""
    return {"id": id, "label": {"value": label, "updated_at": written_at},
            "as_of": {"value": at or None, "updated_at": written_at}, "description": {"value": description}}


def proposed_node(id, name, branch, draft, *marks):
    return {"id": id, "name": {"value": name}, "source_branch": {"value": branch},
            "destination_branch": {"value": "main"}, "state": {"value": "open"}, "is_draft": {"value": draft},
            "fylgja_stages": {"edges": [{"node": m} for m in marks]}}


def validator_node(completed_at):
    return {"completed_at": {"value": completed_at or None},
            "definition": {"node": {"name": {"value": "srlinux_device_config"}}}}


CHECKS = [
    ("present", ["description", "as_of", "label"], False, False, [], False, ""),
    ("absent", None, False, False, [], False, "the default branch's schema has no kind FylgjaStage"),
    ("description missing", ["label", "as_of"], False, False, ["description"], False,
     "kind FylgjaStage on the default branch lacks the attribute description, which this build reads"),
    ("two missing", ["as_of"], False, False, ["label", "description"], False,
     "kind FylgjaStage on the default branch lacks the attributes label, description, which this build reads"),
    ("relationship missing", list(sr.STAGE_FIELDS), True, False, ["proposed_change"], False,
     "kind FylgjaStage on the default branch lacks the relationship proposed_change, which this build reads"),
    ("extension missing", list(sr.STAGE_FIELDS), False, True, [], True,
     "kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds"),
    ("attribute and extension missing", ["label", "as_of"], False, True, ["description"], True,
     "kind FylgjaStage on the default branch lacks the attribute description, which this build reads; "
     "kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds"),
]


@pytest.mark.parametrize("name,attributes,no_relationship,no_extension,missing,extension,message", CHECKS,
                         ids=[c[0] for c in CHECKS])
def test_stage_reader_checks_the_kind(infrahub, name, attributes, no_relationship, no_extension, missing, extension,
                                      message):
    f = Stages(infrahub, attributes, no_relationship, no_extension)
    if not message:
        f.reader.check()
        return
    with pytest.raises(sr.StageKindError) as e:
        f.reader.check()
    assert e.value.missing == missing and e.value.extension is extension and str(e.value) == message


def test_stage_reader_lists_open_proposed_changes(infrahub):
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.proposed = [proposed_node(f"pc-{i:03d}", "change", f"change-{i:03d}", i % 2 == 0) for i in range(101)]
    random.Random(7).shuffle(f.proposed)

    every = f.reader.proposed_changes("")
    assert len(every) == 101
    assert [pc.branch for pc in every] == sorted(pc.branch for pc in every)
    asked = infrahub.served("ProposedChanges")
    assert all("branch" not in r["variables"] for r in asked)
    assert [r["variables"]["offset"] for r in asked] == [0, queries.PAGE_SIZE]

    infrahub.requests.clear()
    one = f.reader.proposed_changes("change-042")
    assert [(pc.id, pc.branch) for pc in one] == [("pc-042", "change-042")]
    asked = infrahub.served("ProposedChanges")
    assert len(asked) == 1 and asked[0]["variables"]["branch"] == "change-042"


def test_stage_reader_keeps_values_verbatim(infrahub):
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.proposed = [proposed_node(
        "pc-1", "rewire the leaves", "change-1", True,
        stage_node("st-2", "third-link", "2026-10-16T19:40:01.000002+00:00", "2026-10-16T19:39:00.5+02:00", ""),
        stage_node("st-1", "seeded", "2026-10-16T19:26:07.357145+00:00", "", "before the change"),
    )]
    got = f.reader.proposed_changes("change-1")
    assert got == [sr.ProposedChange("pc-1", "rewire the leaves", "change-1", "main", "open", True, (
        sr.Mark("st-1", "seeded", "2026-10-16T19:26:07.357145+00:00", None, "before the change"),
        sr.Mark("st-2", "third-link", "2026-10-16T19:40:01.000002+00:00", "2026-10-16T19:39:00.5+02:00", ""),
    ))]


def test_stage_reader_lists_orphans(infrahub):
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.orphans = [
        stage_node("st-9", "zeta", "2026-10-16T19:26:07.357145+00:00", "", ""),
        stage_node("st-8", "alpha", "2026-10-16T19:26:08.000001+00:00", "2026-10-16T19:00:00+00:00", ""),
    ]
    got = f.reader.orphans()
    assert got == [sr.Mark("st-8", "alpha", "2026-10-16T19:26:08.000001+00:00", "2026-10-16T19:00:00+00:00"),
                   sr.Mark("st-9", "zeta", "2026-10-16T19:26:07.357145+00:00", None)]
    assert len(infrahub.served("OrphanStages")) == 1


def test_stage_reader_reads_the_branch(infrahub):
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.branches = [{"name": "change-1", "branched_from": "2026-10-16T19:22:50.878965Z",
                   "created_at": "2026-10-16T19:22:50.878867Z"}]
    assert f.reader.branch("change-1") == sr.BranchInfo("change-1", "2026-10-16T19:22:50.878965Z",
                                                        "2026-10-16T19:22:50.878867Z")
    assert f.reader.branch("gone") is None


def test_stage_reader_reads_validations_pinned(infrahub):
    at = "2026-10-16T19:36:12.298111+00:00"
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.validators = [
        validator_node("2026-10-16T19:35:52.068456+00:00"),
        validator_node("2026-10-16T19:35:53.000000+01:00"),  # lexically after the first, an hour before it
        validator_node("2026-10-16T19:36:05.1Z"),
        validator_node(""),
    ]
    assert f.reader.validations("pc-1", at) == "2026-10-16T19:36:05.1Z"
    asked = infrahub.served("ArtifactValidations")
    assert len(asked) == 1
    assert asked[0]["raw_path"] == "/graphql" and "at=2026-10-16T19%3A36%3A12.298111%2B00%3A00" in asked[0]["url"]
    assert asked[0]["query"]["at"] == [at] and asked[0]["variables"]["id"] == "pc-1"

    f.validators = [validator_node("")]
    infrahub.requests.clear()
    assert f.reader.validations("pc-1", "") == ""
    asked = infrahub.served("ArtifactValidations")
    assert len(asked) == 1 and asked[0]["query"] == {}


def test_stage_reader_names_no_branch(infrahub):
    f = Stages(infrahub, list(sr.STAGE_FIELDS))
    f.reader.check()
    f.reader.proposed_changes("")
    f.reader.orphans()
    f.reader.branch("change-1")
    assert [r["path"] for r in infrahub.requests] == ["/api/schema", "/graphql", "/graphql", "/graphql"]
    for r in infrahub.requests:
        assert r["query"] == {} and r["headers"]["X-INFRAHUB-KEY"] == TOKEN


@pytest.mark.parametrize("status,want", [(401, "INFRAHUB_API_TOKEN"), (403, "INFRAHUB_API_TOKEN"),
                                         (500, "<redacted>")])
def test_stage_reader_keeps_the_credential_out(infrahub, status, want):
    """A refused credential and a non-200 carry no credential, even from a server that quotes
    the request's own header back; a refused credential names the variable to fix, and a
    pinned read names its instant."""
    def echo(url, method, headers, timeout, payload=None):
        import httpx

        body = json.dumps({"errors": [f"rejected key {headers.get('X-INFRAHUB-KEY')}"]}).encode()
        return httpx.Response(status, content=body, request=httpx.Request(method.value, url))

    reader = sr.StageReader(DefaultClient(ADDRESS, TOKEN, requester=echo))
    calls = {
        "Check": reader.check,
        "ProposedChanges": lambda: reader.proposed_changes("change-1"),
        "Orphans": reader.orphans,
        "Branch": lambda: reader.branch("change-1"),
        "Validations": lambda: reader.validations("pc-1", "2026-10-16T19:36:12.298111+00:00"),
    }
    for what, call in calls.items():
        with pytest.raises(ReadError) as e:
            call()
        assert TOKEN not in str(e.value), what
        assert want in str(e.value), what
        assert "(the default branch" in str(e.value), what
        if what == "Validations":
            assert "at 2026-10-16T19:36:12.298111+00:00" in str(e.value)
