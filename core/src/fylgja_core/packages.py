"""The packages the server loads once at start: platform packages and probe packages.

Every `*.yaml` under each directory is a package of the kind its version member names
(`platform_package_version` or `probe_package_version`). Two packages with one id, or one
probe format, are refused here: the registry-level rule core.md leaves to the server.

`shipped()` answers the two directories of packages an install carries (D-106): the wheel's, beside the
package, or a checkout's `psp/` and `probes/`. They are what `FYLGJA_PACKAGES` means unset.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fylgja_core import documents, platform_package, probe_package
from fylgja_core.documents import Problem, Rejected
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

SHIPPED = "shipped"
PLATFORMS_DIR = "psp"
PROBES_DIR = "probes"

# Rule ids. Clients and tests match on them.
RULE_UNKNOWN = "package.invalid"
RULE_DUPLICATE = "package.id.duplicate"


@dataclass(frozen=True)
class Loaded:
    """The packages loaded: platform packages by id, probe packages by format."""

    platforms: Mapping[str, PlatformPackage]
    probes: Mapping[str, ProbePackage]


def shipped(package: str = "fylgja_core") -> tuple[Path, Path]:
    """The directories of platform packages and of probe packages `package` carries: `shipped/psp` and
    `shipped/probes` beside the package, where its wheel put them; else, for a package under a checkout's `src/`, the
    first directory above that `src/` holding `psp/` and `probes/`, the repository's; else `FileNotFoundError`, never
    a pair that merely lies above an installed package, as `schemas.formats_dir` answers for the formats. A name that
    is no installed package is `ModuleNotFoundError`."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ModuleNotFoundError(f"no installed package {package}", name=package)
    here = Path(next(iter(spec.submodule_search_locations))).resolve()
    beside = here / SHIPPED
    if (beside / PLATFORMS_DIR).is_dir() and (beside / PROBES_DIR).is_dir():
        return beside / PLATFORMS_DIR, beside / PROBES_DIR
    if here.parent.name == "src":
        for above in here.parent.parents:
            if (above / PLATFORMS_DIR).is_dir() and (above / PROBES_DIR).is_dir():
                return above / PLATFORMS_DIR, above / PROBES_DIR
    raise FileNotFoundError(
        f"the package {package} carries no packages: none at {beside}, and no checkout's"
    )


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
