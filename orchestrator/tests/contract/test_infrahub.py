"""The venv's SDK reaches the Infrahub tier 2 reads, with the token, at the pinned version."""

import importlib.metadata
import os

import httpx
import pytest

pytestmark = pytest.mark.contract


def test_the_sdk_is_the_pinned_one():
    assert importlib.metadata.version("infrahub-sdk") == "1.23.2"


def test_infrahub_answers_with_the_token(infrahub_address):
    headers = {"X-INFRAHUB-KEY": os.environ["INFRAHUB_API_TOKEN"]}
    response = httpx.post(
        f"{infrahub_address}/graphql/main",
        json={"query": "{ Branch { name } }"},
        headers=headers,
        timeout=30,
    )
    assert response.status_code == 200
    names = {b["name"] for b in response.json()["data"]["Branch"]}
    assert "main" in names
