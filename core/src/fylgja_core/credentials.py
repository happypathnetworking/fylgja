"""The credential provider: node logins and pull credentials, read from the environment (Constitution X, D-042).

A platform package names a credential; the provider reads `FYLGJA_CREDENTIAL_<NAME>_USERNAME`
and `FYLGJA_CREDENTIAL_<NAME>_PASSWORD`, with `<NAME>` upper-cased and dashes as underscores.
A variable set to the empty string counts as not set. A password never reaches a repr, a
message or a log line: logs name variables, never values.

A pull credential (D-057, D-062) adds `FYLGJA_CREDENTIAL_<NAME>_REGISTRY`: the image prefix a
gated image is pulled under, a host, an optional port and an optional path, with no scheme.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

RULE_MISSING = "credential.missing"
RULE_MALFORMED = "credential.malformed"

PREFIX = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*")
# A key begins and ends on a letter or a digit, so that its pull secret's name is one Kubernetes accepts.
_REGISTRY_VARIABLE = re.compile(r"FYLGJA_CREDENTIAL_([A-Z0-9](?:[A-Z0-9_]*[A-Z0-9])?)_REGISTRY")

_log = logging.getLogger("fylgja.credentials")


@dataclass(frozen=True)
class Credential:
    """A node login. Its repr and str hide the password."""

    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return f"Credential(username={self.username!r}, password='***')"

    __str__ = __repr__


@dataclass(frozen=True)
class PullCredential:
    """A registry's image prefix and login. Its repr and str hide the password."""

    registry: str
    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return f"PullCredential(registry={self.registry!r}, username={self.username!r}, password='***')"

    __str__ = __repr__


class Missing(Exception):
    """A credential variable is not set, or is empty; it is named, and nothing present is shown.

    An operator-environment fault (D-042): neither a retry nor a new spec clears it, only
    setting the variable where the core runs.
    """

    rule = RULE_MISSING

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(f"{RULE_MISSING}: the environment variable {variable} is not set, or is empty")


class Malformed(Exception):
    """A registry variable is not an image prefix; the variable is named, and its value never shown.

    An operator-environment fault, as `Missing` is.
    """

    rule = RULE_MALFORMED

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(
            f"{RULE_MALFORMED}: the environment variable {variable} is not an image prefix: "
            "a host, an optional port and an optional path, with no scheme and no trailing slash"
        )


def key(name: str) -> str:
    """A credential's name as its variables write it: upper-cased, dashes as underscores."""
    return name.upper().replace("-", "_")


def variable(name: str, part: Literal["USERNAME", "PASSWORD", "REGISTRY"]) -> str:
    """The environment variable holding `part` of the credential called `name`."""
    return f"FYLGJA_CREDENTIAL_{key(name)}_{part}"


class Provider:
    """Reads logins from an environment mapping."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    def login(self, name: str) -> Credential:
        """The credential called `name`; `Missing` names the first variable not set, or empty."""
        values: dict[str, str] = {}
        for part in ("USERNAME", "PASSWORD"):
            var = variable(name, part)
            if not self._environ.get(var):
                raise Missing(var)
            _log.debug("read %s", var)
            values[part] = self._environ[var]
        return Credential(username=values["USERNAME"], password=values["PASSWORD"])

    def registries(self) -> dict[str, str]:
        """Every registry prefix set and not empty, by key, in key order; `Malformed` for the first no prefix."""
        found: dict[str, str] = {}
        for var, value in self._environ.items():
            m = _REGISTRY_VARIABLE.fullmatch(var)
            if m and value:
                found[m.group(1)] = value
        held: dict[str, str] = {}
        for k in sorted(found):
            if not PREFIX.fullmatch(found[k]):
                raise Malformed(f"FYLGJA_CREDENTIAL_{k}_REGISTRY")
            held[k] = found[k]
        return held

    def pull(self, name: str) -> PullCredential:
        """The pull credential called `name`; `Missing` names the first variable not set, or empty."""
        values: dict[str, str] = {}
        for part in ("REGISTRY", "USERNAME", "PASSWORD"):
            var = variable(name, part)
            if not self._environ.get(var):
                raise Missing(var)
            _log.debug("read %s", var)
            values[part] = self._environ[var]
        if not PREFIX.fullmatch(values["REGISTRY"]):
            raise Malformed(variable(name, "REGISTRY"))
        return PullCredential(registry=values["REGISTRY"], username=values["USERNAME"], password=values["PASSWORD"])
