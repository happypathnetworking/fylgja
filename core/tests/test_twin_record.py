"""Twin record 1 (formats/twin-record-1.schema.json): the twin resource as a model, which
encodes to a document the schema accepts and reads back."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from fylgja_core import documents, twin_record
from fylgja_core.documents import Problem, Rejected
from fylgja_core.twin_record import (
    RULE_INVALID,
    RULE_VERSION,
    Condition,
    LastStep,
    Node,
    Spec,
    Status,
    TwinRecord,
)

ID_A, ID_B, ID_C = "a" * 64, "b" * 64, "c" * 64
RUN = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
RECORD = TwinRecord(
    name="three-node",
    revision=4,
    generation=2,
    spec=Spec(blueprint_id=ID_A, driver="containerlab", allow_restart=False),
    status=Status(
        observed_generation=2,
        conditions=(Condition(type="Ready", status="True", since="2026-11-03T10:00:00Z"),
                    Condition(type="Stepping", status="False", reason="step.done")),
        phase="flows",
        blueprint_id=ID_A,
        bundle_id=ID_B,
        deployment_id=ID_C,
        nodes=(Node(name="n1", handle="clab-three-node-n1", address="172.20.20.11", holds=ID_B,
                    incarnation="2026-11-03T09:58:01.123456789Z"),
               Node(name="n1-loop-a", handle="clab-three-node-n1-loop-a", address="172.20.20.21")),
        last_step=LastStep(outcome="stepped", from_=ID_B, to=ID_B, phase="flows", run_id=RUN),
    ),
)


def doc() -> dict[str, Any]:
    encoded: dict[str, Any] = documents.encode(RECORD)
    return copy.deepcopy(encoded)


def test_a_record_encodes_to_a_valid_document_and_decodes_back() -> None:
    assert twin_record.validate(doc()) == []
    assert twin_record.decode(doc()) == RECORD


def test_the_last_step_names_the_bundles_from_and_to() -> None:
    assert doc()["status"]["last_step"] == {"outcome": "stepped", "from": ID_B, "to": ID_B, "phase": "flows",
                                            "run_id": RUN}


def test_a_new_record_encodes_without_what_it_does_not_know_yet() -> None:
    fresh = TwinRecord(name="t", revision=1, generation=1, spec=Spec(bundle_id=ID_B, driver="clabernetes",
                                                                     allow_restart=True),
                       status=Status(observed_generation=0, conditions=(), nodes=()))
    encoded = documents.encode(fresh)
    assert twin_record.validate(encoded) == []
    assert encoded["status"] == {"observed_generation": 0, "conditions": [], "nodes": []}
    assert "deletion_requested_at" not in encoded and "blueprint_id" not in encoded["spec"]


def test_another_version_is_refused_first() -> None:
    other = {**doc(), "record_version": "2"}
    assert twin_record.validate(other) == [Problem("/record_version", RULE_VERSION, "version '2'; this core reads 1")]


def test_a_spec_naming_both_a_blueprint_and_a_bundle_is_a_schema_fault() -> None:
    bad = doc()
    bad["spec"]["bundle_id"] = ID_B
    bad["name"] = "Three-Node"
    found = twin_record.validate(bad)
    assert {p.rule for p in found} == {RULE_INVALID}
    assert {p.pointer for p in found} == {"/spec", "/name"}
    with pytest.raises(Rejected):
        twin_record.decode(bad)


def test_a_record_carries_the_allocation_admit_reserved() -> None:
    allocated = TwinRecord(
        name="t", revision=2, generation=1, spec=Spec(bundle_id=ID_B, driver="containerlab", allow_restart=False),
        status=Status(observed_generation=1, conditions=(), nodes=(),
                      allocation={"lab": "t", "mgmt_subnet": "172.20.1.0/24"}))
    encoded = documents.encode(allocated)
    assert encoded["status"]["allocation"] == {"lab": "t", "mgmt_subnet": "172.20.1.0/24"}
    assert twin_record.validate(encoded) == []
    assert twin_record.decode(encoded) == allocated


def test_an_empty_allocation_is_a_schema_fault() -> None:
    bad = doc()
    bad["status"]["allocation"] = {}
    assert {p.pointer for p in twin_record.validate(bad)} == {"/status/allocation"}
