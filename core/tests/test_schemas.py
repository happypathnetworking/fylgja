import json
from pathlib import Path

import pytest

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
