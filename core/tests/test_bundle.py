"""Bundle 1's manifest (formats/bundle-1.schema.json): the model encodes to a document the
schema accepts and reads back, the manifest's bytes are JCS, and the bundle id is the one
the schema's by-hand recipe computes."""

from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from fylgja_core import blueprint, bundle, documents
from fylgja_core.bundle import RULE_INVALID, RULE_VERSION, File, Manifest, Node, Row
from fylgja_core.documents import Problem, Rejected

ID_A, ID_B = "a" * 64, "b" * 64
MANIFEST = Manifest(
    blueprint_id=ID_A,
    nodes=(
        Node(name="n1", platform="nokia_srlinux", config=File(file="configs/n1.cfg", sha256=ID_B)),
        Node(name="n2", platform="arista_eos", config=File(file="configs/n2.cfg", sha256=ID_B)),
    ),
    mapping=(
        Row(device="n1", interface="ethernet-1/1", rule="ethernet", enabled=True, disposition="cabled",
            node_name="ethernet-1/1"),
        Row(device="n1", interface="ethernet-1/59", rule="ethernet", enabled=True, disposition="omitted",
            omission="out_of_range"),
        Row(device="n1", interface="mgmt0", rule="management", enabled=True, disposition="management",
            node_name="mgmt0"),
        Row(device="n2", interface="Ethernet1", rule="ethernet", enabled=False, disposition="cabled",
            node_name="Ethernet1"),
        Row(device="n2", interface="Port-Channel1", enabled=True, disposition="omitted", omission="no_rule"),
    ),
    links=(
        blueprint.Link(a=blueprint.Endpoint(device="n1", interface="ethernet-1/1"),
                       b=blueprint.Endpoint(device="n2", interface="Ethernet1")),
    ),
    probes=(),
)


def doc() -> dict[str, Any]:
    encoded: dict[str, Any] = documents.encode(MANIFEST)
    return copy.deepcopy(encoded)


def test_a_manifest_encodes_to_a_valid_document_and_decodes_back() -> None:
    assert bundle.validate(doc()) == []
    assert bundle.decode(doc()) == MANIFEST


def test_an_omitted_row_carries_its_omission_and_no_node_name() -> None:
    rows = doc()["mapping"]
    assert rows[1] == {"device": "n1", "interface": "ethernet-1/59", "rule": "ethernet", "enabled": True,
                       "disposition": "omitted", "omission": "out_of_range"}
    assert "rule" not in rows[4] and "node_name" not in rows[4]


def test_another_version_is_refused_first() -> None:
    other = {**doc(), "bundle_version": "2"}
    assert bundle.validate(other) == [Problem("/bundle_version", RULE_VERSION, "version '2'; this core reads 1")]


def test_a_schema_fault_is_reported_with_its_pointer_and_decode_refuses_it() -> None:
    bad = doc()
    bad["nodes"][0]["config"]["file"] = "n1.cfg"
    bad["mapping"][0]["omission"] = "no_rule"
    found = bundle.validate(bad)
    assert {p.rule for p in found} == {RULE_INVALID}
    assert {p.pointer for p in found} == {"/nodes/0/config/file", "/mapping/0"}
    with pytest.raises(Rejected):
        bundle.decode(bad)


def test_the_manifest_bytes_are_jcs_with_no_trailing_newline() -> None:
    assert bundle.manifest_bytes(MANIFEST) == rfc8785.dumps(doc())
    assert not bundle.manifest_bytes(MANIFEST).endswith(b"\n")


def test_the_bundle_id_is_what_the_schema_computes_by_hand(tmp_path: Path) -> None:
    if shutil.which("sha256sum") is None:
        pytest.skip("sha256sum is not installed")
    files = {"manifest.json": bundle.manifest_bytes(MANIFEST), "configs/n2.cfg": b"hostname n2\n",
             "configs/n1.cfg": b"set / system name host-name n1\n"}
    for path, content in files.items():
        (tmp_path / path).parent.mkdir(exist_ok=True)
        (tmp_path / path).write_bytes(content)
    recipe = "find . -type f | sed 's|^\\./||' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1"
    by_hand = subprocess.run(["sh", "-c", recipe], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert bundle.bundle_id(files) == by_hand.stdout.strip()
    assert bundle.bundle_id(dict(reversed(files.items()))) == bundle.bundle_id(files)
