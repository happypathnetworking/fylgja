from pathlib import Path

import pytest

from fylgja_core import schemas

ROOT = Path(__file__).resolve().parents[2]


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


def test_an_installed_package_reads_the_formats_beside_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "site-packages" / "fylgja_core"
    (package / "formats").mkdir(parents=True)
    monkeypatch.setattr(schemas, "__file__", str(package / "schemas.py"))
    assert schemas.formats_dir() == package / "formats"
    monkeypatch.setattr(schemas, "__file__", str(tmp_path / "a" / "b" / "c" / "schemas.py"))
    assert schemas.formats_dir() == tmp_path / "formats"
