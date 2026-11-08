"""The credential provider: logins come from the environment, and the password is never shown."""

from __future__ import annotations

import logging

import pytest

from fylgja_core import credentials
from fylgja_core.credentials import Credential, Malformed, Missing, Provider, PullCredential, key

ENV = {
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "s3cret",
    "FYLGJA_CREDENTIAL_MY_EOS_USERNAME": "u",
    "FYLGJA_CREDENTIAL_MY_EOS_PASSWORD": "p",
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "registry.example:5443/arista",
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_USERNAME": "puller",
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_PASSWORD": "s3cret-pull",
    "FYLGJA_CREDENTIAL_LAB_REGISTRY": "registry.example",
    # No registry: an empty value, a login's variable, and a key ending in `_`, whose pull
    # secret would be `fylgja-pull-a-`, a name Kubernetes refuses.
    "FYLGJA_CREDENTIAL_EMPTY_REGISTRY": "",
    "FYLGJA_CREDENTIAL_A_REGISTRY_USERNAME": "u",
    "FYLGJA_CREDENTIAL_A__REGISTRY": "registry.example",
}


def test_a_login_is_read_from_the_two_variables_of_its_name() -> None:
    assert Provider(ENV).login("srlinux") == Credential(username="admin", password="s3cret")
    assert Provider(ENV).login("my-eos") == Credential(username="u", password="p")
    assert credentials.variable("my-eos", "PASSWORD") == "FYLGJA_CREDENTIAL_MY_EOS_PASSWORD"


def test_a_missing_variable_is_refused_by_name_and_the_present_value_is_never_shown() -> None:
    with pytest.raises(Missing) as e:
        Provider({"FYLGJA_CREDENTIAL_EOS_USERNAME": "admin"}).login("eos")
    assert e.value.variable == "FYLGJA_CREDENTIAL_EOS_PASSWORD" and e.value.rule == "credential.missing"
    assert "admin" not in str(e.value)


@pytest.mark.parametrize("part", ["USERNAME", "PASSWORD"])
def test_an_empty_variable_counts_as_missing(part: str) -> None:
    env = {**ENV, f"FYLGJA_CREDENTIAL_SRLINUX_{part}": ""}
    with pytest.raises(Missing) as e:
        Provider(env).login("srlinux")
    assert e.value.variable == f"FYLGJA_CREDENTIAL_SRLINUX_{part}" and "s3cret" not in str(e.value)
    assert str(e.value).endswith("is not set, or is empty")


def test_the_password_never_appears_in_a_repr_or_a_log(caplog: pytest.LogCaptureFixture) -> None:
    c = Credential(username="admin", password="s3cret")
    assert "s3cret" not in repr(c) and "s3cret" not in str(c) and "***" in repr(c)
    with caplog.at_level(logging.DEBUG):
        Provider(ENV).login("srlinux")
    assert "s3cret" not in caplog.text and "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD" in caplog.text


def test_a_key_is_a_credentials_name_as_the_variables_write_it() -> None:
    assert key("arista-ceos") == "ARISTA_CEOS" == key("ARISTA_CEOS")
    assert credentials.variable("arista-ceos", "REGISTRY") == "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"


def test_the_registries_held_are_listed_by_key_in_key_order() -> None:
    assert list(Provider(ENV).registries().items()) == [
        ("ARISTA_CEOS", "registry.example:5443/arista"),
        ("LAB", "registry.example"),
    ]


def test_a_pull_credential_is_read_and_its_password_is_never_shown(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        c = Provider(ENV).pull("arista-ceos")
    assert c == PullCredential("registry.example:5443/arista", "puller", "s3cret-pull")
    assert "s3cret-pull" not in repr(c) and "s3cret-pull" not in str(c) and "password='***'" in repr(c)
    assert "s3cret-pull" not in caplog.text and "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY" in caplog.text


@pytest.mark.parametrize("part", ["REGISTRY", "USERNAME", "PASSWORD"])
def test_a_pull_credential_missing_a_variable_is_refused_by_its_name(part: str) -> None:
    env = {k: v for k, v in ENV.items() if k != f"FYLGJA_CREDENTIAL_ARISTA_CEOS_{part}"}
    with pytest.raises(Missing) as e:
        Provider(env).pull("arista-ceos")
    assert e.value.variable == f"FYLGJA_CREDENTIAL_ARISTA_CEOS_{part}"


@pytest.mark.parametrize(
    "value",
    [
        "https://registry.example:5443",
        "registry.example:5443/",
        "registry.example:5443/Arista",
        " registry.example",
        "registry.example:port",
    ],
)
def test_a_registry_that_is_no_image_prefix_is_refused_by_its_variable_and_never_shown(value: str) -> None:
    env = {**ENV, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": value}
    for call in (lambda: Provider(env).registries(), lambda: Provider(env).pull("arista-ceos")):
        with pytest.raises(Malformed) as e:
            call()
        assert e.value.variable == "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"
        assert e.value.rule == "credential.malformed" and value not in str(e.value)


@pytest.mark.parametrize("value", ["192.0.2.10:5443", "registry.example/a/b-c.d"])
def test_an_address_and_a_path_are_image_prefixes(value: str) -> None:
    env = {**ENV, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": value}
    assert Provider(env).registries()["ARISTA_CEOS"] == value
    assert Provider(env).pull("arista-ceos").registry == value
