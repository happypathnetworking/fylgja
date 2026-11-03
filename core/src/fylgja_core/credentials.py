"""The credential provider: node logins, read from the environment (Constitution X, D-042).

A platform package names a credential; the provider reads `FYLGJA_CREDENTIAL_<NAME>_USERNAME`
and `FYLGJA_CREDENTIAL_<NAME>_PASSWORD`, with `<NAME>` upper-cased and dashes as underscores.
A password never reaches a repr, a message or a log line: logs name variables, never values.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

RULE_MISSING = "credential.missing"

_log = logging.getLogger("fylgja.credentials")


@dataclass(frozen=True)
class Credential:
    """A node login. Its repr and str hide the password."""

    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return f"Credential(username={self.username!r}, password='***')"

    __str__ = __repr__


class Missing(Exception):
    """A credential variable is not set; it is named, and nothing present is shown."""

    rule = RULE_MISSING

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"{RULE_MISSING}: the environment variable {variable} is not set")


def variable(name: str, part: Literal["USERNAME", "PASSWORD"]) -> str:
    """The environment variable holding `part` of the credential called `name`."""
    return f"FYLGJA_CREDENTIAL_{name.upper().replace('-', '_')}_{part}"


class Provider:
    """Reads logins from an environment mapping."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    def login(self, name: str) -> Credential:
        """The credential called `name`; `Missing` names the first variable that is not set."""
        values: dict[str, str] = {}
        for part in ("USERNAME", "PASSWORD"):
            var = variable(name, part)
            if var not in self._environ:
                raise Missing(var)
            _log.debug("read %s", var)
            values[part] = self._environ[var]
        return Credential(username=values["USERNAME"], password=values["PASSWORD"])
