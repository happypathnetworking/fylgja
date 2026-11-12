"""The example's two documents, the plan and the rehearsal, each a format of its own in `formats/` (D-086). A check
concludes from a document's status alone and the report is rendered from the rehearsal's document alone (D-087), so
every member is there for the report, a check or a command and for nothing else (Constitution XII). The example's
wheel carries the two files and no other (D-084), and each `$ref`s nothing outside them, so that wheel resolves them
alone (formats/README.md, note 23)."""

from __future__ import annotations

import ast
import json
import re
import typing
from collections.abc import Callable, Iterator
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import pytest
from fylgja_core import schemas

from fylgja_orchestrator.rehearsal import Change, documents, rules, twin_name, twin_prefix
from fylgja_orchestrator.rehearsal.documents import finding

ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "formats"
Name = Literal["plan-1", "rehearsal-1"]
NAMES: tuple[Name, ...] = ("plan-1", "rehearsal-1")

CHANGE = Change("third-link", "pc-1", "third link", 'Change "third link"')
TWIN = twin_name(CHANGE, "run-1")
RUN = "01JC0Z8X4M3T5V6W7Y8Z9A0B1C"


def _id(text: str) -> str:
    """A content address that looks like the core's."""
    return sha256(text.encode()).hexdigest()


def minimal_plan() -> dict[str, Any]:
    """A plan of a change with no stage: the members every plan has, and no other."""
    return {
        "plan_version": "1",
        "status": "empty",
        "headline": "Nothing to plan\nNo stage of the change selects a device in scope tag:fylgja, so there is "
        "nothing to build. Check the scope the checks run with.",
        "change": {"id": CHANGE.id, "where": CHANGE.where},
        "scope": "tag:fylgja",
        "read_at": "2026-11-09T10:15:11Z",
        "findings": [
            finding(
                rules.STAGES_NONE,
                "error",
                "No stage of the change selects a device in scope tag:fylgja, so there is nothing to build. "
                "Check the scope the checks run with.",
            )
        ],
        "stages": [],
    }


def _built(label: str, changed: str, *, unchanged: bool = False) -> dict[str, Any]:
    """A stage built, with every member a built stage has."""
    return {
        "label": label,
        "where": f"{label}, as of 2026-11-09T10:00:00Z",
        "outcome": "built",
        "blueprint_id": _id(f"blueprint {label}"),
        "bundle_id": _id(f"bundle {label}"),
        "changed": changed,
        "unchanged": unchanged,
        "findings": [],
        "omitted": [],
        "approximations": [],
    }


def full_plan() -> dict[str, Any]:
    """A plan of five stages that every member of the format appears in."""
    seeded = _built("seeded", "baseline: 2 nodes, 1 link")
    seeded["findings"] = [finding("stage.main.moved", "warning", "The main branch moved after the branch point.")]
    seeded["omitted"] = [{"device": "n1", "interface": "ethernet-1/99", "omission": "no_rule"}]
    seeded["approximations"] = [{"package": "nokia_srlinux", "text": "The twin's ports run at one speed."}]
    return minimal_plan() | {
        "status": "planned",
        "headline": "Plan: 4 of 5 stages build\nThe baseline is stage 2, seeded; 3 stages follow it.",
        "findings": [],
        "stages": [
            {
                "label": "branch-point",
                "where": "branch-point, as of 2026-11-09T09:00:00Z",
                "outcome": "empty",
                "findings": [finding("scope.empty", "error", "The scope selects no device.", "tag:fylgja")],
            },
            seeded,
            _built("third-node", "1 node added (n3); 1 link added (n1 to n3)"),
            _built("third-link", "1 link added (n2 to n3)"),
            _built("head", "nothing", unchanged=True),
        ],
    }


def minimal_rehearsal() -> dict[str, Any]:
    """A rehearsal that ended before its plan began, so its plan is null: the members every rehearsal has."""
    held = "rh-" + "0" * 8 + "-" + "1" * 8
    return {
        "rehearsal_version": "1",
        "status": "not_rehearsed",
        "headline": "Not rehearsed: an earlier twin is still there\nAn earlier rehearsal's twin, "
        f"{held}, was not removed within 120 s, so this rehearsal did not start. Remove it with "
        f"fylgja-core twin destroy {held}, then run the checks again.",
        "plan": None,
        "twin": TWIN,
        "run_id": "run-1",
        "took_s": 120.4,
        "stages": [],
        "already_failing": [],
        "reclaimed": [],
        "findings": [
            finding(
                rules.TWIN_HELD,
                "error",
                f"An earlier rehearsal's twin, {held}, was not removed within 120 s, so this rehearsal did not "
                f"start. Remove it with fylgja-core twin destroy {held}, then run the checks again.",
            )
        ],
    }


def full_rehearsal() -> dict[str, Any]:
    """A rehearsal that failed at stage 4, with every member of the format present, as no one rehearsal would hold
    them all: a baseline whose wait expired, a room read and a twin reclaimed beside it."""
    counts = {"held": 9, "failed": 0, "skipped": 1}
    unread = finding("verify.node.unread", "error", "n1 could not be read over gNMI.", "n1")
    port = finding("verify.port.enabled", "error", "n3's ethernet-1/2 is down.", "n3:ethernet-1/2")
    cause = (
        "Verify found 1 failure at stage 4, third-link, that the baseline did not have, the first n3:ethernet-1/2: "
        "n3's ethernet-1/2 is down (verify.port.enabled)."
    )
    return minimal_rehearsal() | {
        "status": "failed",
        "headline": f"Rehearsal failed at stage 4 of 5: third-link\n{cause} Stages 2 and 3 passed. Stage 5 was not "
        "reached.",
        "plan": full_plan(),
        "took_s": 75.2,
        "stages": [
            {"result": "empty"},
            {
                "result": "created",
                "counts": counts,
                "run_id": RUN,
                "took_s": 41.0,
                "wait": {"budget_s": 180, "after_s": 180.0},
            },
            {"result": "passed", "counts": counts, "run_id": RUN, "took_s": 12.5},
            {
                "result": "failed",
                "counts": counts | {"failed": 1},
                "failures": [port],
                "run_id": RUN,
                "took_s": 13.1,
            },
            {"result": "not_reached"},
        ],
        "already_failing": [unread],
        "room": ["fake: 8 of 8 CPUs and 16384 of 16384 MiB free", "pending: 0 nodes, 0 CPUs, 0 MiB"],
        "reclaimed": [twin_prefix(CHANGE) + "00000000"],
        "findings": [
            finding(rules.STAGE_FAILED, "error", cause),
            finding(
                rules.TWIN_RECLAIMED,
                "warning",
                f"The twin {twin_prefix(CHANGE)}00000000, left by an earlier rehearsal of this change, was removed "
                "before this one started.",
            ),
        ],
    }


DOCUMENTS: dict[str, Callable[[], dict[str, Any]]] = {
    "a minimal plan": minimal_plan,
    "a full plan": full_plan,
    "a minimal rehearsal": minimal_rehearsal,
    "a full rehearsal": full_rehearsal,
}


@pytest.mark.parametrize("made", DOCUMENTS)
def test_a_minimal_and_a_full_document_of_each_format_validate(made: str) -> None:
    name: Name = "plan-1" if "plan" in made else "rehearsal-1"
    assert documents.validate(name, DOCUMENTS[made]()) == []


# Each fault, the document it is made in, and the one pointer it is refused at.
Fault = Callable[[dict[str, Any]], object]
REFUSED: list[tuple[str, Name, Fault, str]] = [
    ("an unknown member", "rehearsal-1", lambda d: d.update(colour="red"), "/"),
    ("an unknown member of a stage", "plan-1", lambda d: d["stages"][1].update(colour="red"), "/stages/1"),
    ("a plan of status ok", "plan-1", lambda d: d.update(status="ok"), "/status"),
    ("a rehearsal of status ok", "rehearsal-1", lambda d: d.update(status="ok"), "/status"),
    ("a stage's result refused", "rehearsal-1", lambda d: d["stages"][3].update(result="refused"), "/stages/3/result"),
    ("a finding with no rule", "rehearsal-1", lambda d: d["findings"][0].pop("rule"), "/findings/0"),
    (
        "a finding of its plan with no rule",
        "rehearsal-1",
        lambda d: d["plan"]["stages"][0]["findings"][0].pop("rule"),
        "/plan/stages/0/findings/0",
    ),
    ("plan_version 2", "plan-1", lambda d: d.update(plan_version="2"), "/plan_version"),
    ("its plan's plan_version 2", "rehearsal-1", lambda d: d["plan"].update(plan_version="2"), "/plan/plan_version"),
    ("a plan neither a plan nor null", "rehearsal-1", lambda d: d.update(plan="planned"), "/plan"),
    ("a built stage with no bundle", "plan-1", lambda d: d["stages"][1].pop("bundle_id"), "/stages/1"),
]


@pytest.mark.parametrize(("fault", "name", "make", "at"), REFUSED, ids=[r[0] for r in REFUSED])
def test_each_fault_is_refused_at_its_pointer(fault: str, name: Name, make: Fault, at: str) -> None:
    doc = full_plan() if name == "plan-1" else full_rehearsal()
    make(doc)
    assert [problem.partition(": ")[0] for problem in documents.validate(name, doc)] == [at]


def test_each_violation_is_its_pointer_and_its_message_sorted() -> None:
    found = documents.validate("plan-1", {})
    assert found[0] == "/: 'change' is a required property"
    assert found == sorted(found)
    assert len(found) == 8


def test_a_finding_leaves_out_an_object_it_names_none_of() -> None:
    assert finding(rules.TWIN_LEFT, "warning", "The twin t may still be there.") == {
        "rule": "rehearsal.twin.left",
        "severity": "warning",
        "message": "The twin t may still be there.",
    }
    assert list(finding("push.refused", "error", "n3 refused it.", "n3")) == ["rule", "severity", "object", "message"]


def _schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FORMATS / f"{name}.schema.json").read_text())
    return loaded


def _walk(schema: Any, at: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every subschema of `schema` with its pointer, but those under `if`: a condition, which holds no member."""
    if not isinstance(schema, dict):
        return
    yield at, schema
    for key, value in schema.items():
        if key in ("properties", "$defs"):
            for member, sub in value.items():
                yield from _walk(sub, f"{at}/{key}/{member}")
        elif key in ("items", "then", "else", "not"):
            yield from _walk(value, f"{at}/{key}")
        elif key in ("allOf", "anyOf", "oneOf"):
            for i, sub in enumerate(value):
                yield from _walk(sub, f"{at}/{key}/{i}")


CONSUMER = re.compile(r"report|check|command")


def test_every_member_names_its_consumer() -> None:
    walked: list[str] = []
    for name in NAMES:
        for at, schema in _walk(_schema(name)):
            walked.append(f"{name}{at}")
            if schema.get("type") == "object" or "properties" in schema:
                assert schema.get("additionalProperties") is False, f"{name}{at}"
            for member, sub in schema.get("properties", {}).items():
                assert CONSUMER.search(sub.get("description", "")), f"{name}{at}/properties/{member}"
    assert "plan-1/$defs/stage/properties/bundle_id" in walked, "the walk is blind"
    assert "rehearsal-1/$defs/stage/properties/wait/properties/after_s" in walked, "the walk is blind"


def _refs(value: Any) -> list[str]:
    """Every `$ref` in a document, at any depth."""
    if isinstance(value, dict):
        own = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
        return own + [ref for member in value.values() for ref in _refs(member)]
    if isinstance(value, list):
        return [ref for member in value for ref in _refs(member)]
    return []


def test_the_two_schemas_reference_nothing_else() -> None:
    found = {name: _refs(_schema(name)) for name in NAMES}
    assert "plan-1.schema.json" in found["rehearsal-1"], "the scan is blind"
    outside = [f"{n}: {r}" for n, refs in found.items() for r in refs if not r.startswith(("#/", "plan-1.schema.json"))]
    assert outside == []
    assert [_schema(n)["$id"] for n in NAMES] == [f"{schemas.ID_PREFIX}{n}.schema.json" for n in NAMES]


def test_the_wheel_would_carry_exactly_the_two() -> None:
    setup = ROOT / "orchestrator" / "setup.py"
    (listed,) = [
        ast.literal_eval(statement.value)
        for statement in ast.parse(setup.read_text(), str(setup)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ORCHESTRATOR_FORMATS" for t in statement.targets)
    ]
    read = typing.get_args(typing.get_type_hints(documents.validate)["name"])
    assert read == NAMES
    assert listed == tuple(f"{n}.schema.json" for n in NAMES)
