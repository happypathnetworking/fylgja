"""The support packages' `platform.matches` (PSP 0.7; FR-013), as `internal/psp`'s
registry joins them: a device's package is the one naming its manufacturer and platform
pair, both compared exactly, letter case and spacing included.

The adapter reads only each package's `platform` (its id, NOS and pairs). The packages are
the core's: it validates them, and compiles with them, so a package this module reads
and the core refuses fails at the core's compile. Where they are read from (research
§5.10):

- the shipped packages, `psp/*.yaml` at the repository root, found from this module's own
  path when the package is installed from the tree (`pip install -e`, as
  `make orchestrator-venv` installs it), or from `FYLGJA_PSP_SHIPPED` when it is installed
  elsewhere;
- then `FYLGJA_PSP_DIR`, the core's override variable, whose packages shadow a shipped one
  of the same NOS, as `--psp-dir` does in the core.

The survivors are held to sharing no platform id and no pair, as the core's registry is
(`psp.identity.duplicate`, `psp.matches.duplicate`), so a device's pair never has two
packages.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from fylgja_orchestrator.documents.findings import Findings, quote

ENV_SHIPPED = "FYLGJA_PSP_SHIPPED"
ENV_OVERRIDE = "FYLGJA_PSP_DIR"

RULE_PLATFORM_UNMATCHED = "platform.unmatched"
RULE_IDENTITY_DUPLICATE = "psp.identity.duplicate"
RULE_MATCHES_DUPLICATE = "psp.matches.duplicate"

ORIGIN_SHIPPED = "shipped"
ORIGIN_OVERRIDE = "override"


def repository_psp_dir() -> Path:
    """`psp/` at the repository root this module sits in (src/fylgja_orchestrator/
    adapters/infrahub/ under orchestrator/)."""
    return Path(__file__).resolve().parents[5] / "psp"


@dataclass(frozen=True)
class Match:
    """One manufacturer and platform name pair a package is."""

    manufacturer: str
    platform: str

    def __str__(self) -> str:
        """As the findings name a pair, both quoted, so a trailing space or a letter's case
        is visible."""
        return f"manufacturer {quote(self.manufacturer)}, platform {quote(self.platform)}"


@dataclass(frozen=True)
class Package:
    id: str
    nos: str
    matches: tuple[Match, ...]
    path: str
    origin: str


class PackageError(Exception):
    """The packages cannot be read, or two of them name one id or one pair. `findings`
    holds the latter's rejections, under the core's rules, at the override's file."""

    def __init__(self, message: str, findings: Findings | None = None):
        super().__init__(message)
        self.findings = findings or Findings()


def _parse(path: Path, origin: str) -> Package:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise PackageError(f"reading support package {path}: {e}") from None
    platform = (doc or {}).get("platform") if isinstance(doc, dict) else None
    if not isinstance(platform, dict):
        raise PackageError(f"{path}: no platform")
    matches = tuple(
        Match(str(m.get("manufacturer") or ""), str(m.get("platform") or ""))
        for m in platform.get("matches") or []
        if isinstance(m, dict)
    )
    return Package(
        id=str(platform.get("id") or ""),
        nos=str(platform.get("nos") or ""),
        matches=matches,
        path=str(path),
        origin=origin,
    )


def _from_dir(directory: Path, origin: str) -> list[Package]:
    return [_parse(p, origin) for p in sorted(directory.glob("*.yaml"))]


class Registry:
    """The packages that survived shadowing, joined by id and by pair."""

    def __init__(self, packages: list[Package]):
        by_nos: dict[str, Package] = {}
        for p in packages:
            by_nos[p.nos] = p
        self.packages = [by_nos[nos] for nos in sorted(by_nos)]
        self._by_id: dict[str, Package] = {}
        self._by_match: dict[Match, Package] = {}
        for p in self.packages:
            self._by_id.setdefault(p.id, p)
            for m in p.matches:
                self._by_match.setdefault(m, p)
        held = [p for p in self.packages if p.origin == ORIGIN_SHIPPED]
        held += [p for p in self.packages if p.origin != ORIGIN_SHIPPED]
        found = Findings()
        _check_duplicate_identity(held, found)
        _check_duplicate_match(held, found)
        if found.rejected:
            parts = "; ".join(f"{f.object}: {f.rule}: {f.message}" for f in found)
            raise PackageError("invalid support package: " + parts, found)

    def ids(self) -> list[str]:
        """The packages' platform ids, sorted: what a CTM's platform.package may name."""
        return sorted(self._by_id)

    def lookup_id(self, package_id: str) -> Package | None:
        return self._by_id.get(package_id)

    def match(self, manufacturer: str, platform: str) -> Package | None:
        """The package naming the pair exactly, or None."""
        return self._by_match.get(Match(manufacturer, platform))

    def package_matches(self) -> str:
        """Every package with its pairs, in id order, as platform.unmatched names them:
        `arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]`, both names as they
        must be written."""
        parts = []
        for package_id in self.ids():
            pairs = ", ".join(f"{m.manufacturer} / {m.platform}" for m in self._by_id[package_id].matches)
            parts.append(f"{package_id} [{pairs}]")
        return ", ".join(parts)

    def unmatched(self, device: str, manufacturer: str, platform: str) -> tuple[str, str, str]:
        """The rule, object and message refusing a device whose pair no package names."""
        return (
            RULE_PLATFORM_UNMATCHED,
            device,
            f"device {device}: {Match(manufacturer, platform)}; the packages match: {self.package_matches()}",
        )


def _check_duplicate_identity(packages: list[Package], found: Findings) -> None:
    seen: dict[str, str] = {}
    for p in packages:
        if not p.id:
            continue
        if p.id in seen:
            found.reject(RULE_IDENTITY_DUPLICATE, p.id, f"platform {quote(p.id)} is already declared by {seen[p.id]}")
            continue
        seen[p.id] = p.path


def _check_duplicate_match(packages: list[Package], found: Findings) -> None:
    first: dict[Match, Package] = {}
    for p in packages:
        for m in p.matches:
            if not m.manufacturer or not m.platform:
                continue
            prior = first.setdefault(m, p)
            if prior is p:
                continue
            found.reject(
                RULE_MATCHES_DUPLICATE,
                p.path,
                f"{m} is matched by package {prior.id} ({prior.path}) and by package {p.id} ({p.path}); "
                "a device of that pair would have two packages",
            )


def shipped_dir() -> Path:
    """Where the shipped packages are: FYLGJA_PSP_SHIPPED when set, else the repository's
    `psp/`."""
    named = os.environ.get(ENV_SHIPPED, "")
    return Path(named) if named else repository_psp_dir()


def load(override_dir: str | None = None, shipped: str | Path | None = None) -> Registry:
    """The registry: the shipped packages, then those of the override directory
    (FYLGJA_PSP_DIR when none is given), shadowing a shipped one of the same NOS."""
    shipped_path = Path(shipped) if shipped else shipped_dir()
    packages = _from_dir(shipped_path, ORIGIN_SHIPPED)
    if not packages:
        raise PackageError(
            f"no support package under {shipped_path}: set {ENV_SHIPPED} to the shipped psp/ directory "
            "when the orchestrator is installed outside its repository"
        )
    if override_dir is None:
        override_dir = os.environ.get(ENV_OVERRIDE, "")
    if override_dir:
        directory = Path(override_dir)
        if not directory.is_dir():
            raise PackageError(f"support package override directory: {directory} is not a directory")
        packages += _from_dir(directory, ORIGIN_OVERRIDE)
    return Registry(packages)
