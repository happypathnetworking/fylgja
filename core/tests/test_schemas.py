import pytest

from fylgja_core import schemas


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
