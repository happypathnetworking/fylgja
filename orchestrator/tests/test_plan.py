"""The plan (D-086): each stage of a change read from its source, filed and built by the core, and diffed against the
stage built before it, into a plan 1 document; what changed said in words, for the report's table (D-087). Held to
the core's own server on its fake runtime, over a fake change source."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from fylgja_core.client import Client, ProblemError
from fylgja_core.findings import Finding
from harness import Served
from sources import BLUEPRINTS, CHANGE, FIVE, SCOPE, TESTDATA, FakeSource, built, empty, refused

from fylgja_orchestrator.rehearsal import Change, Read, Stage, documents, plan, planning, rules

NOW = "2026-11-09T10:15:11Z"
STALE = Finding(rule="artifact.stale", severity="error", object="n1",
                message="n1's configuration is older than its intent.")
NONE_IN_SCOPE = ("No stage of the change selects a device in scope tag:fylgja, so there is nothing to build. Check the "
                 "scope the checks run with.")


def now() -> str:
    return NOW


def planned(
    served: Served, stages: Sequence[tuple[Stage, Read | Exception]], lines: list[str] | None = None
) -> tuple[dict[str, Any], FakeSource]:
    """The plan of `CHANGE` over `stages`, once it validates, and the source it read; its progress put in `lines`."""
    source = FakeSource(CHANGE, stages)
    doc = plan(source, served.client, CHANGE.ref, SCOPE, now=now, progress=None if lines is None else lines.append)
    assert documents.validate("plan-1", doc) == []
    return doc, source


def outcomes(doc: dict[str, Any]) -> list[str]:
    return [stage["outcome"] for stage in doc["stages"]]


def test_the_plan_reads_files_builds_and_diffs_every_stage(served: Served) -> None:
    lines: list[str] = []
    doc, source = planned(served, FIVE, lines)
    stages = doc["stages"]
    assert (doc["status"], doc["findings"]) == ("planned", [])
    assert outcomes(doc) == ["empty", "built", "built", "built", "built"]
    assert [s.get("changed") for s in stages] == [
        None,
        "baseline: 2 nodes, 1 link",
        "1 node added (n3); 1 link added (n1 to n3)",
        "1 link added (n2 to n3)",
        "nothing",
    ]
    assert [s.get("unchanged") is True for s in stages] == [False, False, False, False, True]
    assert [s["bundle_id"] for s in stages[1:]] == [served.other.build_bundle(s["blueprint_id"])["id"]
                                                    for s in stages[1:]]
    assert doc["headline"] == "Plan: 4 of 5 stages build\nThe baseline is stage 2, seeded; 3 stages follow it."
    assert (doc["change"], doc["scope"], doc["read_at"]) == ({"id": "pc-1", "where": CHANGE.where}, SCOPE, NOW)
    assert source.reads == ["branch-point", "seeded", "third-node", "third-link", "head"]
    assert lines == [f"plan: stage {k} of 5, {s['label']}: {s['outcome']}" for k, s in enumerate(stages, 1)]
    assert served.client.list_twins() == []


def test_a_stage_the_source_refuses_ends_the_plan_there(served: Served) -> None:
    lines: list[str] = []
    doc, source = planned(served, [*FIVE[:2], refused("third-node", STALE), *FIVE[3:]], lines)
    assert doc["status"] == "refused"
    assert outcomes(doc) == ["empty", "built", "refused", "not_read", "not_read"]
    assert source.reads == ["branch-point", "seeded", "third-node"]
    assert lines[-1] == "plan: stage 3 of 5, third-node: refused" and len(lines) == 3
    assert doc["stages"][2]["findings"] == [documents.finding("artifact.stale", "error", STALE.message, "n1")]
    assert doc["stages"][3] == {"label": "third-link", "where": FIVE[3][0].where, "outcome": "not_read"}
    (cause,) = doc["findings"]
    assert (cause["rule"], cause["severity"], cause["object"]) == ("stage.refused", "error", "third-node")
    assert doc["headline"] == (
        "Plan refused at stage 3 of 5: third-node\nStage 3, third-node, could not be built: n1: n1's configuration "
        "is older than its intent (artifact.stale). Nothing was rehearsed."
    )
    assert doc["headline"].partition("\n")[2] == cause["message"]


def test_a_stage_the_compiler_refuses_is_refused_with_its_findings(served: Served) -> None:
    unsupported = TESTDATA / "compiler" / "rejected" / "platform-unsupported.json"
    doc, _ = planned(served, [FIVE[1], built("unsupported", unsupported), FIVE[4]])
    assert (doc["status"], outcomes(doc)) == ("refused", ["built", "refused", "not_read"])
    stage = doc["stages"][1]
    assert "platform.unsupported" in [f["rule"] for f in stage["findings"]]
    assert "blueprint_id" in stage and "bundle_id" not in stage
    first = next(f for f in stage["findings"] if f["severity"] == "error")
    assert doc["findings"][0]["message"] == (
        f"Stage 2, unsupported, could not be built: {rules.quote(first)}. Nothing was rehearsed."
    )


def test_a_stage_with_no_device_after_the_baseline_is_refused(served: Served) -> None:
    doc, source = planned(served, [FIVE[1], empty("emptied"), FIVE[4]])
    assert (doc["status"], outcomes(doc)) == ("refused", ["built", "refused", "not_read"])
    assert source.reads == ["seeded", "emptied"]
    assert doc["headline"] == (
        "Plan refused at stage 2 of 3: emptied\nStage 2, emptied, could not be built: tag:fylgja: The scope selects "
        "no device (scope.empty). Nothing was rehearsed."
    )


def test_a_change_whose_stages_are_all_empty_or_none_plans_nothing(served: Served) -> None:
    for stages, expected in (([empty("branch-point"), empty("head")], ["empty", "empty"]), ([], [])):
        doc, _ = planned(served, stages)
        assert (doc["status"], outcomes(doc)) == ("empty", expected)
        assert [(f["rule"], f["message"]) for f in doc["findings"]] == [("rehearsal.stages.none", NONE_IN_SCOPE)]
        assert doc["headline"] == f"Nothing to plan\n{NONE_IN_SCOPE}"
    assert served.driver.calls == []


def test_a_fault_that_is_no_stages_leaves_plan_and_stops_read(served: Served) -> None:
    fault = RuntimeError("the source is away")
    stages: list[tuple[Stage, Read | Exception]] = [*FIVE[:2], (FIVE[2][0], fault), *FIVE[3:]]
    with pytest.raises(RuntimeError) as raised:
        plan(FakeSource(CHANGE, stages), served.client, CHANGE.ref, SCOPE, now=now)
    assert raised.value is fault

    source = FakeSource(CHANGE, stages)
    doc, met = planning.read(source, served.client, CHANGE, SCOPE, now=now)
    assert met is fault and documents.validate("plan-1", doc) == []
    assert (doc["status"], doc["headline"], doc["findings"]) == ("unfinished", "Plan not finished", [])
    assert outcomes(doc) == ["empty", "built", "not_read", "not_read", "not_read"]
    assert source.reads == ["branch-point", "seeded", "third-node"]


class Halt(Exception):
    """What a test's source or `before` raises."""


class Away(FakeSource):
    """A source whose stages cannot be read."""

    def stages(self, change: Change) -> Sequence[Stage]:
        raise Halt("the stages are away")


def test_a_fault_of_the_source_the_core_or_before_stops_read_where_it_is_met(served: Served) -> None:
    doc, met = planning.read(Away(CHANGE, FIVE), served.client, CHANGE, SCOPE, now=now)
    assert isinstance(met, Halt) and documents.validate("plan-1", doc) == []
    assert (doc["status"], doc["stages"]) == ("unfinished", [])

    asked: list[int] = []

    # Ahead of the stages, two reads, the second stage's filing and build and the third's read; the 7th, its filing.
    def before() -> None:
        asked.append(len(asked) + 1)
        if len(asked) == 7:
            raise Halt("the limit")

    source = FakeSource(CHANGE, FIVE)
    doc, met = planning.read(source, served.client, CHANGE, SCOPE, now=now, before=before)
    assert isinstance(met, Halt) and documents.validate("plan-1", doc) == []
    assert outcomes(doc) == ["empty", "built", "not_read", "not_read", "not_read"]
    assert source.reads == ["branch-point", "seeded", "third-node"]

    with Client(served.address, "nobody-test-token") as stranger:
        doc, met = planning.read(FakeSource(CHANGE, FIVE), stranger, CHANGE, SCOPE, now=now)
    assert isinstance(met, ProblemError) and met.status == 401 and documents.validate("plan-1", doc) == []
    assert (doc["status"], outcomes(doc)) == ("unfinished", ["empty", "not_read", "not_read", "not_read", "not_read"])


def diffed(served: Served, before: str, after: str) -> dict[str, Any]:
    """The diff the served core answers from the blueprint `before` to `after`, each filed and built."""
    built_ids = [served.client.build_bundle(served.client.put_blueprint(json.loads((BLUEPRINTS / name).read_text())))
                 ["id"] for name in (before, after)]
    return served.client.diff_bundles(*built_ids)


def test_what_changed_is_said_in_words(served: Served) -> None:
    words = planning.changed_words
    assert words(diffed(served, "three-node.json", "steps/three-node-n1-disabled.json")) == "ports of n1"
    assert words(diffed(served, "three-node.json", "three-node-unmanaged.json")) == "configuration of n2"
    assert words(diffed(served, "three-node.json", "steps/three-node-n3-eos.json")) == (
        "2 links added (n1 to n3, n2 to n3); 2 links removed (n1 to n3, n2 to n3); platform of n3; configuration of n3"
    )
    assert words(diffed(served, "three-node-probed.json", "steps/three-node-probed-moved.json")).startswith(
        "probe n1-loop moved"
    )
    assert words(diffed(served, "three-node.json", "three-node.json")) == "nothing"
    five = {"unchanged": False, "nodes": {"added": ["a", "b", "c", "d", "e"], "removed": [], "changed": []},
            "links": {"added": [], "removed": []}, "probes": {"added": [], "removed": []}}
    assert words(five) == "5 nodes added (a, b, c and 2 more)"

    probed = served.client.build_bundle(
        served.client.put_blueprint(json.loads((BLUEPRINTS / "three-node-probed.json").read_text())))
    assert planning.baseline_words(probed["manifest"]) == "baseline: 3 nodes, 3 links, 1 probe"
