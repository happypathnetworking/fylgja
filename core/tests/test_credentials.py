"""The credential provider: logins come from the environment, and the password is never shown."""

from __future__ import annotations

import logging

import pytest

from fylgja_core import credentials
from fylgja_core.credentials import Credential, Missing, Provider

ENV = {
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "s3cret",
    "FYLGJA_CREDENTIAL_MY_EOS_USERNAME": "u",
    "FYLGJA_CREDENTIAL_MY_EOS_PASSWORD": "p",
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
