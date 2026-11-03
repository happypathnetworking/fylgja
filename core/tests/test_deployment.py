"""Deployment 1 (formats/deployment-1.schema.json): a driver plan's output as a model, which
encodes to a document the schema accepts and reads back."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from fylgja_core import deployment, documents
from fylgja_core.deployment import (
    RULE_INVALID,
    RULE_VERSION,
    Approximation,
    CompileFidelity,
    Demand,
    Deployment,
    Fidelity,
    File,
    Lossy,
    Omitted,
)
from fylgja_core.documents import Problem, Rejected

ID_A, ID_B, ID_C = "a" * 64, "b" * 64, "c" * 64
DEPLOYMENT = Deployment(
    id=ID_A,
    driver="containerlab",
    twin="three-node",
    allocation={"lab": "three-node", "mgmt_subnet": "172.20.20.0/24"},
    bundle_id=ID_B,
    files=(File(path="topology.clab.yml", sha256=ID_C),),
    demand=Demand(nodes=5, cpu=1.7, memory_mb=6208),
    fidelity=Fidelity(
        forwarding="software",
        approximations=(Approximation(package="nokia_srlinux", text="No linecard model"),
                        Approximation(package="ping", text="IPv4 only: ping and ip are run without -6.")),
        omitted=(Omitted(device="n1", interface="ethernet-1/59", omission="out_of_range"),),
        synthesized=("n1-loop-a", "n1-loop-b"),
        lossy=Lossy(mappings=0, shared_ports=0),
    ),
)


def doc() -> dict[str, Any]:
    encoded: dict[str, Any] = documents.encode(DEPLOYMENT)
    return copy.deepcopy(encoded)


def test_a_deployment_encodes_to_a_valid_document_and_decodes_back() -> None:
    assert deployment.validate(doc()) == []
    assert deployment.decode(doc()) == DEPLOYMENT


def test_the_allocation_is_carried_as_the_driver_shaped_it() -> None:
    assert doc()["allocation"] == {"lab": "three-node", "mgmt_subnet": "172.20.20.0/24"}


def test_the_compile_fidelity_is_the_runtime_independent_part() -> None:
    compile_fidelity = CompileFidelity(approximations=DEPLOYMENT.fidelity.approximations,
                                       omitted=DEPLOYMENT.fidelity.omitted, synthesized=DEPLOYMENT.fidelity.synthesized)
    encoded = documents.encode(compile_fidelity)
    assert set(encoded) == {"approximations", "omitted", "synthesized"}
    assert documents.decode(CompileFidelity, encoded) == compile_fidelity


def test_another_version_is_refused_first() -> None:
    other = {**doc(), "deployment_version": "2"}
    assert deployment.validate(other) == [
        Problem("/deployment_version", RULE_VERSION, "version '2'; this core reads 1")
    ]


def test_a_schema_fault_is_reported_with_its_pointer_and_decode_refuses_it() -> None:
    bad = doc()
    bad["demand"]["cpu"] = -1
    bad["files"] = []
    found = deployment.validate(bad)
    assert {p.rule for p in found} == {RULE_INVALID}
    assert {p.pointer for p in found} == {"/demand/cpu", "/files"}
    with pytest.raises(Rejected):
        deployment.decode(bad)
