"""Settings come from FYLGJA_* variables; a missing or malformed one is refused by name."""

from __future__ import annotations

from pathlib import Path

import pytest

from fylgja_core import config

FULL = {
    "FYLGJA_STORE": "/var/lib/fylgja",
    "FYLGJA_TOKENS": "/etc/fylgja/tokens",
    "FYLGJA_PACKAGES": "/opt/psp:/opt/probes",
    "FYLGJA_LISTEN": "0.0.0.0:9000",
    "FYLGJA_DRIVER": "containerlab",
    "FYLGJA_WORKERS": "2",
}
REQUIRED = ("FYLGJA_STORE", "FYLGJA_TOKENS", "FYLGJA_PACKAGES")


def test_settings_from_a_full_environment() -> None:
    assert config.from_environ(FULL) == config.Settings(
        store=Path("/var/lib/fylgja"),
        listen=("0.0.0.0", 9000),
        driver="containerlab",
        workers=2,
        packages=(Path("/opt/psp"), Path("/opt/probes")),
        tokens=Path("/etc/fylgja/tokens"),
    )


def test_defaults() -> None:
    env = {k: FULL[k] for k in REQUIRED}
    s = config.from_environ(env)
    assert (s.listen, s.driver, s.workers) == (("127.0.0.1", 7650), "containerlab", 4)


@pytest.mark.parametrize("variable", REQUIRED)
def test_each_missing_required_variable_is_named(variable: str) -> None:
    env = {k: v for k, v in FULL.items() if k != variable}
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ(env)
    assert e.value.variable == variable
    assert variable in str(e.value)


def test_an_empty_required_variable_counts_as_missing() -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_STORE": ""})
    assert e.value.variable == "FYLGJA_STORE"


@pytest.mark.parametrize("workers", ["x", "0", "-1", "2.5"])
def test_workers_must_be_an_integer_of_one_or_more(workers: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_WORKERS": workers})
    assert e.value.variable == "FYLGJA_WORKERS"
    assert workers not in str(e.value)


@pytest.mark.parametrize("listen", ["7650", "h1:", "h1:abc", "h1:0", "h1:70000", ":80"])
def test_listen_must_be_host_and_port(listen: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_LISTEN": listen})
    assert e.value.variable == "FYLGJA_LISTEN"
    assert listen not in str(e.value)
