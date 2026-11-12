"""The Infrahub change source against the seeded development Infrahub, with the example's account's token and the
seed's reader document: the proposed change found by its branch with its draft flag, its stages in order, each read to
a blueprint, the head read while the proposed change's artifact validation runs, and the report posted as one thread
of two comments by the account, which may write nothing else (D-085, D-088).

The module's proposed change and its mark are the writer's, deleted at their end. Two paths are the pure tier's alone
(P5-25): a mark given a `generated_since` of a completion in force at its time, since the seed marks every stage before
any proposed change exists, and a branch whose proposed change has no artifact validator, since the seed's branch
changes devices.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fylgja_core.blueprint import blueprint_id
from fylgja_infrahub import ReaderDocument, Result
from fylgja_infrahub import read as reader_read

import fylgja_orchestrator.infrahub.source as source_module
from fylgja_orchestrator.infrahub import (
    RULE_MAIN_MOVED,
    InfrahubSource,
    NoChange,
    Pin,
    SourceError,
)
from fylgja_orchestrator.rehearsal.report import Report

from .conftest import ADDRESS, Proposal, Proposals, Secret, Writer, ca

MARK_CREATE = (
    "mutation ($branch: String!, $label: String!) { FylgjaStageCreate(data: {branch: {value: $branch}, label: {value: "
    '$label}, description: {value: "a mark of the contract tier, with no as_of"}}) { ok object { id } } }'
)
MARK_READ = (
    "query ($id: ID!) { FylgjaStage(ids: [$id]) { edges { node { id } node_metadata { created_at } } } }"
)
MARK_DELETE = "mutation ($id: String!) { FylgjaStageDelete(data: {id: $id}) { ok } }"
CUT_READ = "query ($name: String!) { Branch(name: $name) { name branched_from } }"
ACCOUNT = "query { AccountProfile { id name { value } } }"
TAG_CREATE = "mutation ($name: String!) { BuiltinTagCreate(data: {name: {value: $name}}) { ok object { id } } }"
TAG_READ = "query ($name: String!) { BuiltinTag(name__value: $name) { count edges { node { id } } } }"
TAG_DELETE = "mutation ($id: String!) { BuiltinTagDelete(data: {id: $id}) { ok } }"

LIMIT = 4092
"""The bytes of one part of a report Infrahub takes (`COMMENT_LIMIT`)."""


@pytest.fixture(scope="module")
def source(document: ReaderDocument, example_token: Secret) -> Iterator[InfrahubSource]:
    """The change source with the example's account's token and the seed's reader document."""
    made = InfrahubSource(os.environ[ADDRESS], example_token.value, document, ca=ca())
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="module")
def proposal(proposals: Proposals) -> Proposal:
    """The module's proposed change of the seed's branch, not a draft, made at the first test that asks for it: the
    head's read at its creation."""
    return proposals.make(draft=False)


def test_the_head_read_at_the_proposed_changes_creation_waits_for_the_validation(
    source: InfrahubSource,
    proposal: Proposal,
    writer: Writer,
    seed: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First of the module, so that no proposed change of its own is queued ahead of this one's validation: one queued
    # behind another's was read to appear 70.5 s after its create, against 25 s on a quiet instance.
    asked: list[dict[str, Any]] = []
    real = reader_read  # the source's own `read`, the reader's

    def spied(conn: Any, **kwargs: Any) -> Result:
        asked.append(kwargs)
        return real(conn, **kwargs)

    monkeypatch.setattr(source_module, "read", spied)
    branch, scope = seed["branch"], seed["scope"]
    change = source.change(branch)
    head = source.stages(change)[-1]
    since_made = time.monotonic() - proposal.made
    before = writer.validators(proposal.id)
    began = time.monotonic()
    got = source.read(head, scope)
    waited = time.monotonic() - began
    after = writer.validators(proposal.id)
    print(f"the head was read {since_made:.1f} s after the proposed change's create was answered, its validators "
          f"then {[row['state'] for row in before]}; the read returned {waited:.1f} s on, its validators then "
          f"{[(row['state'], row['completed_at']) for row in after]}")
    assert since_made < 15.0
    assert before == [] or any(row["state"] != "completed" for row in before)
    assert got.blueprint is not None
    rules = {finding.rule for finding in got.findings}
    assert rules & {"artifact.stale", "artifact.unready", "stage.validation.unfinished"} == set()
    [validator] = after
    assert validator["state"] == "completed"
    assert [call["generated_since"] for call in asked] == [validator["completed_at"]]


def test_the_change_is_found_by_its_branch_with_its_draft_flag(
    source: InfrahubSource, proposal: Proposal, proposals: Proposals, seed: dict[str, Any]
) -> None:
    # The module's own proposed change, made a draft and then not: Infrahub keeps one open a branch.
    branch = seed["branch"]
    proposals.set_draft(proposal.id, True)
    try:
        change = source.change(branch)
        assert (change.ref, change.id, change.name) == (branch, proposal.id, proposal.name)
        assert source.is_draft(change) is True
    finally:
        proposals.set_draft(proposal.id, False)
    assert source.is_draft(source.change(branch)) is False
    with pytest.raises(NoChange):
        source.change("p5-none")


def test_the_stages_are_the_branch_point_the_seeds_marks_in_order_and_the_head(
    source: InfrahubSource, proposal: Proposal, writer: Writer, seed: dict[str, Any]
) -> None:
    branch = seed["branch"]
    change = source.change(branch)
    stages = source.stages(change)
    assert [stage.label for stage in stages] == ["branch-point", *seed["marks"], "head"]
    [cut] = [listed["branched_from"] for listed in writer.gql(CUT_READ, {"name": branch})["Branch"]]
    assert stages[0].pin == Pin("branch-point", "main", cut, proposal.id)
    # Each mark's as_of is the seed's time as written (P5-12).
    assert [stage.pin for stage in stages[1:-1]] == [
        Pin("mark", branch, stage["at"], proposal.id) for stage in seed["stages"]
    ]
    assert stages[-1].pin == Pin("head", branch, "", proposal.id)

    label = f"p5-contract-{secrets.token_hex(4)}"
    made = writer.gql(MARK_CREATE, {"branch": branch, "label": label})["FylgjaStageCreate"]
    assert made["ok"] is True
    mark = made["object"]["id"]
    try:
        [edge] = writer.gql(MARK_READ, {"id": mark})["FylgjaStage"]["edges"]
        again = source.stages(change)
        assert [stage.label for stage in again] == ["branch-point", *seed["marks"], label, "head"]
        assert again[-2].pin == Pin("mark", branch, edge["node_metadata"]["created_at"], proposal.id)
    finally:
        assert writer.gql(MARK_DELETE, {"id": mark})["FylgjaStageDelete"]["ok"] is True


def test_a_report_is_posted_as_one_thread_of_two_comments_by_the_examples_account(
    source: InfrahubSource, proposal: Proposal, writer: Writer, example_token: Secret, seed: dict[str, Any]
) -> None:
    change = source.change(seed["branch"])
    account = writer.gql(ACCOUNT, token=example_token)["AccountProfile"]
    assert account["name"]["value"] == "fylgja-orchestrator"
    before = writer.threads(proposal.id)

    source.post(change, Report("passed", "A contract tier's report.", "The summary, **first**.", "The detail, second."))
    after = writer.threads(proposal.id)
    [thread] = set(after) - set(before)
    assert len(after) == len(before) + 1
    comments = writer.comments(thread)
    assert [text for text, _, _ in comments] == ["The summary, **first**.", "The detail, second."]
    assert {author for _, _, author in comments} == {account["id"]}

    source.post(change, Report("passed", "At the limit.", "s" * LIMIT, "d"))
    at_limit = writer.threads(proposal.id)
    [thread] = set(at_limit) - set(after)
    assert [len(text.encode()) for text, _, _ in writer.comments(thread)] == [LIMIT, 1]

    with pytest.raises(SourceError, match=f"is {LIMIT + 1} bytes"):
        source.post(change, Report("passed", "Past the limit.", "s" * (LIMIT + 1), "d"))
    assert writer.threads(proposal.id) == at_limit


def test_the_examples_account_writes_nothing_else(writer: Writer, example_token: Secret) -> None:
    name = f"p5-contract-{secrets.token_hex(4)}"
    answer, status = writer.ask(TAG_CREATE, {"name": name}, token=example_token)
    try:
        errors = answer.get("errors") if isinstance(answer, dict) else None
        statuses = [error.get("extensions", {}).get("http_status") for error in errors or []]
        print(f"BuiltinTagCreate with the example's token: HTTP {status}, http_status {statuses}")
        assert status == 403 or 403 in statuses
        assert writer.gql(TAG_READ, {"name": name})["BuiltinTag"]["count"] == 0
    finally:
        for edge in writer.gql(TAG_READ, {"name": name})["BuiltinTag"]["edges"]:
            writer.gql(TAG_DELETE, {"id": edge["node"]["id"]})


def test_every_stage_reads_to_a_blueprint_and_the_head_twice_gives_one_id(
    source: InfrahubSource, proposal: Proposal, seed: dict[str, Any]
) -> None:
    # Last of the module: after its proposed changes, its mark and its threads, each a write to main (P5-28).
    change = source.change(seed["branch"])
    stages = source.stages(change)
    ids = []
    for stage in stages:
        got = source.read(stage, seed["scope"])
        assert got.blueprint is not None, stage.label
        assert [finding.rule for finding in got.findings if finding.severity == "error"] == [], stage.label
        assert RULE_MAIN_MOVED not in {finding.rule for finding in got.findings}, stage.label
        ids.append(blueprint_id(got.blueprint))
    again = source.read(stages[-1], seed["scope"])
    assert again.blueprint is not None
    assert blueprint_id(again.blueprint) == ids[-1]
    print(f"the stages {[stage.label for stage in stages]} read to {[found[:8] for found in ids]}")
