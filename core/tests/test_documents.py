"""What every format module shares: the codec between a model type and its document, reading
a file, and how a rejection is carried."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected


@dataclass(frozen=True, kw_only=True)
class Inner:
    kind: Literal["a", "b"]
    cpu: float
    bounds: tuple[int, int]


@dataclass(frozen=True, kw_only=True)
class Outer:
    version: str = "1"
    name: str
    from_: str = field(metadata={"key": "from"})
    note: str | None = None
    inner: Inner
    items: tuple[Inner, ...]
    ranges: Mapping[str, tuple[int, int]] | None = None
    opaque: Mapping[str, Any] | None = None


SAMPLE = Outer(
    name="x",
    from_="y",
    inner=Inner(kind="a", cpu=1.5, bounds=(1, 2)),
    items=(Inner(kind="b", cpu=2.0, bounds=(3, 4)),),
    ranges={"port": (1, 58)},
    opaque={"any": [1, {"thing": None}]},
)
DOC: dict[str, Any] = {
    "version": "1",
    "name": "x",
    "from": "y",
    "inner": {"kind": "a", "cpu": 1.5, "bounds": [1, 2]},
    "items": [{"kind": "b", "cpu": 2.0, "bounds": [3, 4]}],
    "ranges": {"port": [1, 58]},
    "opaque": {"any": [1, {"thing": None}]},
}


def test_encode_writes_the_document_with_absent_fields_left_out() -> None:
    assert documents.encode(SAMPLE) == DOC


def test_decode_reads_the_document_back() -> None:
    assert documents.decode(Outer, DOC) == SAMPLE


def test_decode_reads_an_integer_into_a_float_field_and_fills_defaults() -> None:
    doc = {"name": "x", "from": "y", "inner": {"kind": "a", "cpu": 1, "bounds": [0, 0]}, "items": []}
    outer = documents.decode(Outer, doc)
    assert outer.inner.cpu == 1.0 and isinstance(outer.inner.cpu, float)
    assert outer.version == "1" and outer.note is None and outer.ranges is None


def test_read_parses_json_by_suffix_and_yaml_otherwise(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"yes": "no"}')
    (tmp_path / "a.yaml").write_text("yes: no\n")
    assert documents.read(tmp_path / "a.json") == {"yes": "no"}
    assert documents.read(tmp_path / "a.yaml") == {True: False}


@pytest.mark.parametrize(("name", "text"), [("a.json", "{"), ("a.yaml", "a: [\n")])
def test_read_refuses_a_file_that_is_not_a_document(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text)
    with pytest.raises(documents.Malformed):
        documents.read(tmp_path / name)


def test_load_reports_a_malformed_file_as_a_problem_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("a: [\n")
    with pytest.raises(Rejected) as caught:
        documents.load(path, "x.invalid", lambda doc: doc)
    assert caught.value.subject == str(path)
    assert [p.rule for p in caught.value.problems] == ["x.invalid"]


def test_load_names_the_file_on_a_rejection_the_decoder_raised(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{}")

    def refuse(doc: Any) -> Any:
        raise Rejected([Problem("/a", "x.rule", "bad")])

    with pytest.raises(Rejected) as caught:
        documents.load(path, "x.invalid", refuse)
    assert caught.value.subject == str(path)
    assert caught.value.problems == (Problem("/a", "x.rule", "bad"),)
    assert "x.rule at /a: bad" in str(caught.value)


def test_a_schema_violation_is_a_problem_with_its_pointer() -> None:
    found = documents.schema_problems("probes-1", {"probes_version": "1", "probes": [{"name": "n"}]}, "probes.invalid")
    assert found and all(p.rule == "probes.invalid" for p in found)
    assert {p.pointer for p in found} == {"/probes/0"}


def test_another_version_is_one_problem() -> None:
    assert documents.unsupported_version({"v": "2"}, "v", "1", "x.version") == [
        Problem("/v", "x.version", "version '2'; this core reads 1")
    ]
    assert documents.unsupported_version({"v": "1"}, "v", "1", "x.version") == []
    assert documents.unsupported_version("not a document", "v", "1", "x.version") == []
