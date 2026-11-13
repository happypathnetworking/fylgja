"""The reader document, netbox-reader 1 (D-095): what NetBox cannot hold, given to each read. It says which
manufacturer and platform pair is which platform package, and the name of the configuration context that declares the
probes, or none, and holds no address and no credential (D-042). `document.load` reads it from a YAML or JSON file, or
raises `Rejected` naming the file with every problem found in one pass; its format is in `formats/` and travels in the
reader's wheel alone (D-084)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from fylgja_core import schemas
from fylgja_core.documents import Rejected

from fylgja_netbox import Match, ReaderDocument, document

ROOT = Path(__file__).resolve().parents[3]

FIXTURE: dict[str, Any] = {
    "reader_version": "1",
    "platforms": [{"manufacturer": "Nokia", "platform": "SR Linux", "package": "nokia_srlinux"}],
    "probes": "fylgja-probes",
}
EXPECTED = ReaderDocument((Match("Nokia", "SR Linux", "nokia_srlinux"),), "fylgja-probes")


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_the_fixtures_document_decodes(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"reader{suffix}"
    path.write_text(json.dumps(FIXTURE) if suffix == ".json" else yaml.safe_dump(FIXTURE))
    loaded = document.load(path)
    assert loaded == EXPECTED
    assert loaded.package("Nokia", "SR Linux") == "nokia_srlinux"
    assert loaded.package("nokia", "SR Linux") is None


def test_no_probes_is_null(tmp_path: Path) -> None:
    path = tmp_path / "reader.yaml"
    path.write_text(yaml.safe_dump({**FIXTURE, "probes": None}))
    assert document.load(path).probes is None


def test_the_seeds_document_decodes() -> None:
    assert document.load(ROOT / "netbox" / "seed" / "reader.yaml") == EXPECTED


def _second_row(package: str) -> Callable[[dict[str, Any]], object]:
    """A fault: a second row of the fixture's pair, naming `package`."""
    return lambda d: d["platforms"].append({"manufacturer": "Nokia", "platform": "SR Linux", "package": package})


# Each fault, made in the fixture's document, the problems it is refused with, each as its pointer and its rule. A
# missing or an unknown member is reported at the object that lacks or holds it (`""` here, ruling C3), a wrong type or
# an empty value at the member itself.
FAULTS: list[tuple[str, Callable[[dict[str, Any]], object], list[tuple[str, str]]]] = [
    ("version 2", lambda d: d.update(reader_version="2"), [("/reader_version", "reader.version.unsupported")]),
    ("no platform", lambda d: d.update(platforms=[]), [("/platforms", "reader.invalid")]),
    ("no probes", lambda d: d.pop("probes"), [("", "reader.invalid")]),
    ("probes empty", lambda d: d.update(probes=""), [("/probes", "reader.invalid")]),
    ("probes a boolean", lambda d: d.update(probes=True), [("/probes", "reader.invalid")]),
    ("a member artifact", lambda d: d.update(artifact="device-config"), [("", "reader.invalid")]),
    ("a member address", lambda d: d.update(address="https://netbox.example"), [("", "reader.invalid")]),
    (
        "a package in capitals",
        lambda d: d["platforms"][0].update(package="Nokia-SRL"),
        [("/platforms/0/package", "reader.invalid")],
    ),
    ("one pair, two packages", _second_row("arista_eos"), [("/platforms/1", "reader.platform.duplicate")]),
    ("one pair twice", _second_row("nokia_srlinux"), [("/platforms/1", "reader.platform.duplicate")]),
]


@pytest.mark.parametrize(("fault", "make", "expected"), FAULTS, ids=[row[0] for row in FAULTS])
def test_each_fault_is_its_rule_at_its_pointer(
    fault: str, make: Callable[[dict[str, Any]], object], expected: list[tuple[str, str]]
) -> None:
    doc = copy.deepcopy(FIXTURE)
    make(doc)
    problems = document.validate(doc)
    assert [(p.pointer, p.rule) for p in problems] == expected
    with pytest.raises(Rejected) as refused:
        document.decode(doc)
    assert refused.value.problems == tuple(problems)


@pytest.mark.parametrize(("name", "text"), [("reader.yaml", "platforms: [unclosed\n"), ("reader.json", "{not json")])
def test_a_file_that_is_no_document_is_rejected_naming_the_file(tmp_path: Path, name: str, text: str) -> None:
    path = tmp_path / name
    path.write_text(text)
    with pytest.raises(Rejected) as refused:
        document.load(path)
    assert refused.value.subject == str(path)
    assert [(p.pointer, p.rule) for p in refused.value.problems] == [("", "reader.invalid")]
    assert str(refused.value).startswith(f"{path}: ")


def _refs(value: Any) -> list[str]:
    """Every `$ref` in a schema, at any depth."""
    if isinstance(value, dict):
        own = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
        return own + [ref for member in value.values() for ref in _refs(member)]
    if isinstance(value, list):
        return [ref for member in value for ref in _refs(member)]
    return []


def test_the_format_is_found_where_the_package_reads_it() -> None:
    found = schemas.formats_dir("fylgja_netbox") / "netbox-reader-1.schema.json"
    assert found.is_file()
    schema = json.loads(found.read_text())
    assert schema["$id"] == f"{schemas.ID_PREFIX}netbox-reader-1.schema.json"
    # The reader's wheel carries this file alone, so it refers to no other.
    assert [ref for ref in _refs(schema) if not ref.startswith("#")] == []
