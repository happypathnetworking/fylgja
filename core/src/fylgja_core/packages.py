"""The packages the server loads once at start: platform packages and probe packages.

Every `*.yaml` under each directory is a package of the kind its version member names
(`platform_package_version` or `probe_package_version`). Two packages with one id, or one
probe format, are refused here: the registry-level rule core.md leaves to the server.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fylgja_core import documents, platform_package, probe_package
from fylgja_core.documents import Problem, Rejected
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

# Rule ids. Clients and tests match on them.
RULE_UNKNOWN = "package.invalid"
RULE_DUPLICATE = "package.id.duplicate"


@dataclass(frozen=True)
class Loaded:
    """The packages loaded: platform packages by id, probe packages by format."""

    platforms: Mapping[str, PlatformPackage]
    probes: Mapping[str, ProbePackage]


def load(dirs: Sequence[Path]) -> Loaded:
    """Every package under `dirs`, or `Rejected` naming the file at fault."""
    platforms: dict[str, PlatformPackage] = {}
    probes: dict[str, ProbePackage] = {}
    origin: dict[tuple[str, str], Path] = {}
    for directory in dirs:
        for path in sorted(directory.glob("*.yaml")):
            try:
                doc = documents.read(path)
            except documents.Malformed as e:
                raise Rejected([Problem("", RULE_UNKNOWN, str(e))], str(path)) from e
            if not isinstance(doc, dict) or not ({"platform_package_version", "probe_package_version"} & doc.keys()):
                raise Rejected(
                    [Problem("", RULE_UNKNOWN, "neither platform_package_version nor probe_package_version")],
                    str(path),
                )
            if "platform_package_version" in doc:
                platform = platform_package.load(path)
                _claim(origin, "platform", platform.id, path)
                platforms[platform.id] = platform
            else:
                probe = probe_package.load(path)
                _claim(origin, "probe", probe.format, path)
                probes[probe.format] = probe
    return Loaded(platforms, probes)


def _claim(origin: dict[tuple[str, str], Path], kind: str, key: str, path: Path) -> None:
    """Record that `path` holds the package `key`, or refuse it when an earlier file does."""
    if (kind, key) in origin:
        problem = Problem("", RULE_DUPLICATE, f"{kind} package {key!r} is also in {origin[kind, key]}")
        raise Rejected([problem], str(path))
    origin[kind, key] = path
