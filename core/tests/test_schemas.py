import pytest

from fylgja_core import schemas


def test_an_api_component_validates_a_document_and_resolves_format_refs() -> None:
    v = schemas.api_validator("Created")
    assert v.is_valid({"id": "a" * 64}) and not v.is_valid({"id": "nope"})


def test_an_unknown_component_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        schemas.api_validator("NoSuchThing")
