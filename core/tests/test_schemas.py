import functools
import json
import operator
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_bundle
import test_findings
import test_twin_record
import yaml

from fylgja_core import schemas

ROOT = Path(__file__).resolve().parents[2]

# Another package's format: its one property a `$ref` to a core format.
THING = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": f"{schemas.ID_PREFIX}thing-1.schema.json",
    "type": "object",
    "required": ["device"],
    "properties": {"device": {"$ref": "blueprint-1.schema.json#/$defs/device_name"}},
}


def test_an_api_component_validates_a_document_and_resolves_format_refs() -> None:
    v = schemas.api_validator("Created")
    assert v.is_valid({"id": "a" * 64}) and not v.is_valid({"id": "nope"})


def test_an_unknown_component_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        schemas.api_validator("NoSuchThing")


def test_an_operations_inline_request_body_validates() -> None:
    v = schemas.api_body_validator("/v1/bundles", "post")
    assert v.is_valid({"blueprint_id": "a" * 64})
    assert not v.is_valid({"blueprint_id": "a" * 64, "extra": 1}) and not v.is_valid({})


def test_an_operation_with_no_body_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        schemas.api_body_validator("/v1/version", "get")


def test_in_a_checkout_the_formats_are_the_repositorys() -> None:
    assert schemas.formats_dir() == ROOT / "formats"
    # A copy in the source tree would shadow the root's.
    assert not (Path(schemas.__file__).parent / "formats").exists()


def _package(where: Path, name: str) -> Path:
    """An empty package `name` in the directory `where`, which the test puts on `sys.path`."""
    package = where / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    return package


def test_an_installed_package_reads_the_formats_beside_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site = tmp_path / "site"
    (_package(site, "pkg_a") / "formats").mkdir()
    monkeypatch.syspath_prepend(site)
    assert schemas.formats_dir("pkg_a") == site / "pkg_a" / "formats"


def test_a_package_in_a_checkout_reads_the_repositorys_formats_however_deep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "formats").mkdir(parents=True)
    _package(repo / "readers" / "x" / "src", "pkg_b")
    _package(repo / "core" / "src", "pkg_c")
    monkeypatch.syspath_prepend(repo / "readers" / "x" / "src")
    monkeypatch.syspath_prepend(repo / "core" / "src")
    assert schemas.formats_dir("pkg_b") == repo / "formats"
    assert schemas.formats_dir("pkg_c") == repo / "formats"


def test_an_installed_package_without_formats_reads_no_directory_above_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    top = tmp_path / "top"
    (top / "formats").mkdir(parents=True)
    _package(top / "site", "pkg_d")
    monkeypatch.syspath_prepend(top / "site")
    with pytest.raises(FileNotFoundError, match="pkg_d"):
        schemas.formats_dir("pkg_d")


def test_a_package_that_is_not_installed_is_a_module_not_found_error() -> None:
    with pytest.raises(ModuleNotFoundError):
        schemas.formats_dir("pkg_installed_nowhere")


def test_another_packages_validator_resolves_its_own_format_and_the_cores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    formats = _package(tmp_path / "site", "pkg_e") / "formats"
    formats.mkdir()
    (formats / "thing-1.schema.json").write_text(json.dumps(THING))
    monkeypatch.syspath_prepend(tmp_path / "site")
    thing = schemas.validator("thing-1", "pkg_e")
    assert thing.is_valid({"device": "n1"}) and not thing.is_valid({"device": "N 1"})
    blueprint = json.loads((ROOT / "testdata" / "blueprint" / "three-node.json").read_text())
    assert list(schemas.validator("blueprint-1", "pkg_e").iter_errors(blueprint)) == []
    with pytest.raises(LookupError):
        schemas.validator("thing-1")


def test_a_patterns_dollar_is_the_end_of_the_text() -> None:
    assert schemas.ecma("^a$") == r"^a\Z"
    # An escaped `$`, a `$` in a class and a pattern with no `$` keep their own reading.
    assert schemas.ecma(r"^a\$$") == r"^a\$\Z"
    assert schemas.ecma("^[$]$") == r"^[$]\Z"
    assert schemas.ecma("^[^$]+$") == r"^[^$]+\Z"
    assert schemas.ecma("^/") == "^/"
    v = schemas.Validator({"pattern": "^a$"})
    assert v.is_valid("a")
    assert [e.message for e in v.iter_errors("a\n")] == [r"'a\n' does not match '^a$'"]


def _patterns(value: Any) -> list[str]:
    """Every `pattern` keyword's value in a document, at any depth."""
    if isinstance(value, dict):
        own = [value["pattern"]] if isinstance(value.get("pattern"), str) else []
        return own + [p for member in value.values() for p in _patterns(member)]
    if isinstance(value, list):
        return [p for member in value for p in _patterns(member)]
    return []


def _formats() -> dict[str, Any]:
    """Every format's document by its file's stem, the API's among them."""
    files = sorted((ROOT / "formats").glob("*.schema.json"))
    loaded: dict[str, Any] = {path.name.removesuffix(".schema.json"): json.loads(path.read_text()) for path in files}
    loaded["api-1"] = yaml.safe_load((ROOT / "formats" / "api-1.openapi.yaml").read_text())
    return loaded


def _file(*parts: str) -> Callable[[], Any]:
    """A document of the tree, JSON or YAML by its suffix."""
    path = ROOT.joinpath(*parts)
    return lambda: (json.loads if path.suffix == ".json" else yaml.safe_load)(path.read_text())


def _plan() -> dict[str, Any]:
    """A plan of a change with no stage: the members every plan has."""
    return {
        "plan_version": "1", "status": "empty", "headline": "Nothing to plan\nNo stage selects a device.",
        "change": {"id": "pc-1", "where": 'Change "third link"'}, "scope": "tag:fylgja",
        "read_at": "2026-11-09T10:15:11Z",
        "findings": [{"rule": "stages.none", "severity": "error", "message": "No stage selects a device."}],
        "stages": [],
    }


def _rehearsal() -> dict[str, Any]:
    """A rehearsal that ended before its plan began: the members every rehearsal has."""
    return {
        "rehearsal_version": "1", "status": "not_rehearsed", "headline": "Not rehearsed\nA twin is still there.",
        "plan": None, "twin": "rh-00000000-11111111", "run_id": "run-1", "took_s": 120.4, "stages": [],
        "already_failing": [], "reclaimed": [],
        "findings": [{"rule": "twin.held", "severity": "error", "message": "A twin is still there."}],
    }


# Each format holding a `$`-ended pattern: a valid document of it, and the pointer of one patterned string member.
DOLLAR_ENDED: list[tuple[str, str, Callable[[], Any], str]] = [
    ("blueprint-1", "testdata/blueprint/three-node.json", _file("testdata", "blueprint", "three-node.json"),
     "/network/devices/0/name"),
    ("bundle-1", "test_bundle.doc", test_bundle.doc, "/blueprint_id"),
    ("deployment-1", "testdata/deployment/containerlab/three-node/deployment.json",
     _file("testdata", "deployment", "containerlab", "three-node", "deployment.json"), "/files/0/path"),
    ("findings-1", "test_findings.doc", test_findings.doc, "/findings/0/rule"),
    ("infrahub-reader-1", "infrahub/seed/reader.yaml", _file("infrahub", "seed", "reader.yaml"),
     "/platforms/0/package"),
    ("netbox-reader-1", "netbox/seed/reader.yaml", _file("netbox", "seed", "reader.yaml"), "/platforms/0/package"),
    ("plan-1", "_plan", _plan, "/read_at"),
    ("platform-package-1", "psp/nokia_srlinux.yaml", _file("psp", "nokia_srlinux.yaml"), "/id"),
    ("probe-package-1", "probes/ping.yaml", _file("probes", "ping.yaml"), "/format"),
    ("rehearsal-1", "_rehearsal", _rehearsal, "/twin"),
    ("twin-record-1", "test_twin_record.doc", test_twin_record.doc, "/status/last_step/run_id"),
]


def test_the_rows_are_every_format_with_a_dollar_ended_pattern() -> None:
    ended = {name: [p for p in _patterns(doc) if p.endswith("$")] for name, doc in _formats().items()}
    assert {name for name, found in ended.items() if found} == {row[0] for row in DOLLAR_ENDED}
    assert sum(len(found) for found in ended.values()) == 31


@pytest.mark.parametrize(("name", "source", "made", "pointer"), DOLLAR_ENDED, ids=[row[0] for row in DOLLAR_ENDED])
def test_every_dollar_ended_pattern_refuses_a_text_ending_in_a_newline(
    name: str, source: str, made: Callable[[], Any], pointer: str
) -> None:
    doc = made()
    v = schemas.validator(name)
    assert list(v.iter_errors(doc)) == [], source
    *path, last = (int(p) if p.isdigit() else p for p in pointer.split("/")[1:])
    parent = functools.reduce(operator.getitem, path, doc)
    assert isinstance(parent[last], str)
    parent[last] += "\n"
    errors = list(v.iter_errors(doc))
    assert ["/" + "/".join(str(p) for p in e.absolute_path) for e in errors] == [pointer]
    assert errors[0].validator == "pattern"


def test_no_pattern_uses_a_class_python_reads_otherwise() -> None:
    # Python's `\d`, `\w` and `\s` take Unicode where ECMA-262's take ASCII or another set, and `\b` follows `\w`;
    # and each keyword below holds a pattern the extended class would not read.
    for name, doc in _formats().items():
        for pattern in _patterns(doc):
            assert not re.search(r"\\[dwsbDWSB]", pattern), (name, pattern)
            assert "[]" not in pattern and "[^]" not in pattern, (name, pattern)
            assert "." not in re.sub(r"\\.|\[[^\]]*\]", "", pattern), (name, pattern)
        text = json.dumps(doc)
        for keyword in ("patternProperties", "propertyNames", "unevaluatedProperties"):
            assert f'"{keyword}"' not in text, (name, keyword)


def test_a_request_body_is_held_the_same() -> None:
    v = schemas.api_body_validator("/v1/blueprints", "post")
    blueprint = _file("testdata", "blueprint", "three-node.json")()
    assert v.is_valid(blueprint)
    blueprint["network"]["devices"][0]["name"] += "\n"
    assert [e.validator for e in v.iter_errors(blueprint)] == ["pattern"]


LATER = {"member": 1}
"""A member a later minor release's answer might carry, which no format of this one names."""


def test_an_answers_validator_passes_over_a_member_and_nothing_else() -> None:
    answer, closed = schemas.answer_validator("findings-1"), schemas.validator("findings-1")
    doc = test_findings.doc()
    doc["later"] = LATER
    doc["findings"][0]["later"] = LATER
    assert [e.json_path for e in closed.iter_errors(doc)] == ["$", "$.findings[0]"]
    assert list(answer.iter_errors(doc)) == []
    # What a reader uses must still be there and of its kind, and a pattern is still ECMA-262's.
    lacking = {k: v for k, v in doc.items() if k != "status"}
    assert [e.validator for e in answer.iter_errors(lacking)] == ["required"]
    doc["findings"][0]["rule"] += "\n"
    assert [e.validator for e in answer.iter_errors(doc)] == ["pattern"]
    # A map of names is typed by its additionalProperties, which an answer's validator still holds it to.
    record = test_twin_record.doc()
    record["status"]["allocation"] = {"lab": 1}
    assert [e.json_path for e in schemas.answer_validator("twin-record-1").iter_errors(record)] == [
        "$.status.allocation.lab"]
    # What a user writes is still held whole.
    blueprint = _file("testdata", "blueprint", "three-node.json")()
    blueprint["later"] = LATER
    assert [e.validator for e in schemas.validator("blueprint-1").iter_errors(blueprint)] == ["additionalProperties"]
    assert schemas.answer_validator("findings-1") is answer
