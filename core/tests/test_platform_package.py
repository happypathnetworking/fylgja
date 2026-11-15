"""Platform package 1's loader: the shipped packages load to their model, and each rejection
fixture under testdata/packages/invalid/platform/ is refused for its fault alone."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fakes import with_image

from fylgja_core import documents, platform_package
from fylgja_core.documents import Rejected
from fylgja_core.platform_package import (
    RULE_IMAGES_COVERAGE,
    RULE_INVALID,
    RULE_MANAGEMENT_RULE,
    RULE_PLACEHOLDERS,
    RULE_RANGES,
    RULE_RENAME_COVERAGE,
    RULE_RULE_NAME,
    RULE_VERSION,
    RULE_VERSIONS_NAME,
    RULE_VERSIONS_SEVERAL,
    Image,
    Resources,
    Rule,
    ValueAt,
    Version,
)

ROOT = Path(__file__).resolve().parents[2]
PSP = ROOT / "psp"
CHASSISOS = ROOT / "testdata" / "packages" / "chassisos.yaml"
SHIPPED = [*sorted(PSP.glob("*.yaml")), CHASSISOS]
INVALID = ROOT / "testdata" / "packages" / "invalid" / "platform"
SOURCE = ROOT / "core" / "src" / "fylgja_core"
SCHEMA = ROOT / "formats" / "platform-package-1.schema.json"

# Every rejection fixture, and the (pointer, rule) pairs the loader must report for it:
# exactly these, so a fixture with one fault yields one fault. several.yaml carries five;
# versions-name-duplicate.yaml yields two, since a second version is refused whatever its
# name, and schema-versions-of-text.yaml two, one for each member whose shape changed.
REJECTED: dict[str, set[tuple[str, str]]] = {
    "version-unknown.yaml": {("/platform_package_version", RULE_VERSION)},
    "schema-tls-not-boolean.yaml": {("/gnmi/tls", RULE_INVALID)},
    "schema-rename-with-alias.yaml": {("/runtime/containerlab", RULE_INVALID)},
    "management-rule-with-match.yaml": {("/interfaces/rules/2", RULE_INVALID)},
    "rule-name-duplicate.yaml": {("/interfaces/rules/1/name", RULE_RULE_NAME)},
    "management-rule-missing.yaml": {("/interfaces/rules", RULE_MANAGEMENT_RULE)},
    "management-rule-twice.yaml": {("/interfaces/rules/3", RULE_MANAGEMENT_RULE)},
    "node-name-placeholders.yaml": {("/interfaces/rules/0/node_name", RULE_PLACEHOLDERS)},
    "management-node-name-placeholders.yaml": {("/interfaces/rules/2/node_name", RULE_PLACEHOLDERS)},
    "match-captures-twice.yaml": {("/interfaces/rules/0/match", RULE_PLACEHOLDERS)},
    "range-unknown-placeholder.yaml": {("/interfaces/rules/0/ranges/lane", RULE_RANGES)},
    "rename-placeholders-disagree.yaml": {("/runtime/containerlab/rename/0/port", RULE_PLACEHOLDERS)},
    "rename-missing.yaml": {("/runtime/containerlab/rename", RULE_RENAME_COVERAGE)},
    "rename-unknown-rule.yaml": {("/runtime/containerlab/rename/2/rule", RULE_RENAME_COVERAGE)},
    "rename-management-rule.yaml": {("/runtime/containerlab/rename/2/rule", RULE_RENAME_COVERAGE)},
    "rename-twice.yaml": {("/runtime/containerlab/rename/2/rule", RULE_RENAME_COVERAGE)},
    "several.yaml": {
        ("/interfaces/rules/2/name", RULE_RULE_NAME),
        ("/interfaces/rules", RULE_MANAGEMENT_RULE),
        ("/interfaces/rules/0/node_name", RULE_PLACEHOLDERS),
        ("/interfaces/rules/0/ranges/lane", RULE_RANGES),
        ("/runtime/containerlab/rename", RULE_RENAME_COVERAGE),
    },
    "versions-name-duplicate.yaml": {("/versions/1/name", RULE_VERSIONS_NAME), ("/versions/1", RULE_VERSIONS_SEVERAL)},
    "versions-several.yaml": {("/versions/1", RULE_VERSIONS_SEVERAL)},
    "version-without-image.yaml": {("/runtime/containerlab/images", RULE_IMAGES_COVERAGE)},
    "image-for-unlisted-version.yaml": {("/runtime/containerlab/images/1", RULE_IMAGES_COVERAGE)},
    "schema-versions-of-text.yaml": {("/versions/0", RULE_INVALID), ("/runtime/containerlab", RULE_INVALID)},
}

# An image a test's package names: the synthetic reference the rejection fixtures hold.
IMAGE = {"ref": "example.invalid/testos:0"}


def listing(versions: Any, images: Any) -> dict[str, Any]:
    """The synthetic chassisos with these `versions` and these `images`, every other member as
    its file holds it."""
    doc: dict[str, Any] = yaml.safe_load(CHASSISOS.read_text())
    doc["versions"] = versions
    doc["runtime"]["containerlab"]["images"] = images
    return doc


def faults(doc: Any) -> set[tuple[str, str, str]]:
    return {(p.pointer, p.rule, p.detail) for p in platform_package.validate(doc)}


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_each_package_loads_to_its_model_and_encodes_back_unchanged(path: Path) -> None:
    package = platform_package.load(path)
    assert package.id == path.stem
    assert documents.encode(package) == yaml.safe_load(path.read_text())


def test_the_sr_linux_package_reads_as_written() -> None:
    package = platform_package.load(PSP / "nokia_srlinux.yaml")
    assert package.push.delivery == "json_rpc" and package.push.port == 443
    assert package.gnmi.tls is True and package.gnmi.port == 57400
    assert package.interfaces.rules[0] == Rule(
        name="ethernet", match="ethernet-{slot}/{port}", ranges={"slot": (1, 1), "port": (1, 58)}
    )
    assert package.interfaces.rules[-1].management is True and package.interfaces.rules[-1].node_name == "mgmt0"
    assert package.runtime.containerlab.alias is True and package.runtime.containerlab.rename is None
    assert package.runtime.containerlab.resources == Resources(cpu=0.5, memory_mb=2048)
    assert package.versions == (Version(name="24.7.1"),)
    assert package.runtime.containerlab.images == {"24.7.1": Image(ref="ghcr.io/nokia/srlinux:24.7.1")}
    assert package.conformance.port.discovering is not None
    assert package.conformance.port.discovering.absent is None


def test_the_eos_package_renames_every_data_rule() -> None:
    package = platform_package.load(PSP / "arista_eos.yaml")
    containerlab = package.runtime.containerlab
    assert containerlab.alias is False and containerlab.rename is not None
    assert [r.rule for r in containerlab.rename] == ["ethernet", "modular", "breakout"]
    assert package.versions == (Version(name="4.32.0.2F"),)
    assert containerlab.images["4.32.0.2F"] == Image(ref="ceos:4.32.0.2F", pull_secret="arista-ceos")
    assert list(containerlab.images) == ["4.32.0.2F"] and containerlab.hot_add_ports is False
    assert package.conformance.port.discovering is not None
    assert package.conformance.port.discovering.absent == "true"


def test_a_package_without_port_discovering_loads_with_none() -> None:
    """No code reads the path that says LLDP runs on a port, so a package may leave it out: it
    is valid, and its model holds None there and every other member as the file gives it."""
    whole = platform_package.load(CHASSISOS)
    assert whole.conformance.port.discovering is not None
    doc = yaml.safe_load(CHASSISOS.read_text())
    del doc["conformance"]["port"]["discovering"]
    assert platform_package.validate(doc) == []
    package = platform_package.decode(doc)
    assert package.conformance.port.discovering is None
    assert package.conformance.port.enabled == whole.conformance.port.enabled == ValueAt(
        path="/interfaces/interface[name={node_name}]/state/admin-status", value="UP"
    )
    assert package.conformance.port.neighbor == whole.conformance.port.neighbor
    assert package.conformance.port.neighbor.path == "/lldp/interfaces/interface[name={node_name}]/neighbors/neighbor"
    assert documents.encode(package) == doc


def test_the_schema_requires_a_ports_enabled_and_neighbor_alone() -> None:
    port = json.loads(SCHEMA.read_text())["properties"]["conformance"]["properties"]["port"]
    assert port["required"] == ["enabled", "neighbor"]
    assert port["properties"]["discovering"]["$ref"] == "#/$defs/value_at"


def test_the_image_of_a_package_is_its_one_versions() -> None:
    srl = platform_package.load(PSP / "nokia_srlinux.yaml")
    assert platform_package.image(srl) == Image(ref="ghcr.io/nokia/srlinux:24.7.1")
    eos = platform_package.load(PSP / "arista_eos.yaml")
    assert platform_package.image(eos) == Image(ref="ceos:4.32.0.2F", pull_secret="arista-ceos")
    assert platform_package.image(with_image(srl, ref="x")) == Image(ref="x")


def test_placeholders_are_the_braced_names_of_a_pattern_in_order() -> None:
    assert platform_package.placeholders("Ethernet{slot}/{port}/{sub}") == ["slot", "port", "sub"]
    assert platform_package.placeholders("mgmt0") == []
    assert platform_package.placeholders("eth{port}_{port}") == ["port", "port"]


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_each_rejection_fixture_is_refused_for_its_fault_alone(name: str) -> None:
    doc = yaml.safe_load((INVALID / name).read_text())
    found = platform_package.validate(doc)
    assert {(p.pointer, p.rule) for p in found} == REJECTED[name], found
    with pytest.raises(Rejected) as caught:
        platform_package.load(INVALID / name)
    assert caught.value.subject == str(INVALID / name)


def test_every_rejection_fixture_has_a_row() -> None:
    assert {p.name for p in INVALID.glob("*.yaml")} == set(REJECTED)


def test_each_fault_of_the_versions_says_what_is_wrong() -> None:
    several = ("/versions/1", RULE_VERSIONS_SEVERAL, "2 versions; this build runs one version a package")
    assert faults(listing([{"name": "0"}, {"name": "0"}], {"0": IMAGE})) == {
        ("/versions/1/name", RULE_VERSIONS_NAME, "'0' is version 0's name too"), several}
    assert faults(listing([{"name": "0"}], {})) == {
        ("/runtime/containerlab/images", RULE_IMAGES_COVERAGE, "version '0' has no image")}
    assert faults(listing([{"name": "0"}], {"0": IMAGE, "1": IMAGE})) == {
        ("/runtime/containerlab/images/1", RULE_IMAGES_COVERAGE, "'1' is no version the package lists")}
    assert faults(listing([{"name": "0"}, {"name": "1"}], {"0": IMAGE, "1": IMAGE})) == {several}
    assert (RULE_VERSIONS_NAME, RULE_IMAGES_COVERAGE, RULE_VERSIONS_SEVERAL) == (
        "package.versions.name", "package.images.coverage", "package.versions.several")


def test_every_fault_of_the_versions_is_reported_in_one_pass() -> None:
    doc = listing([{"name": "a"}, {"name": "a"}, {"name": "b"}], {"a": IMAGE, "c": IMAGE})
    found = platform_package.validate(doc)
    assert [(p.pointer, p.rule, p.detail) for p in found] == [
        ("/runtime/containerlab/images", RULE_IMAGES_COVERAGE, "version 'b' has no image"),
        ("/runtime/containerlab/images/c", RULE_IMAGES_COVERAGE, "'c' is no version the package lists"),
        ("/versions/1", RULE_VERSIONS_SEVERAL, "3 versions; this build runs one version a package"),
        ("/versions/1/name", RULE_VERSIONS_NAME, "'a' is version 0's name too"),
    ]
    with pytest.raises(Rejected) as caught:
        platform_package.decode(doc)
    assert caught.value.problems == tuple(found)


def test_an_image_keyed_by_a_yaml_number_is_not_the_version_of_that_text() -> None:
    """YAML reads an unquoted 0 or 4.32 as a number, which is no version's name: a name is quoted,
    as a key and as a value, and a package that leaves one bare is refused, never read by guessing
    that the number was meant as its text."""
    doc = listing(yaml.safe_load('[{name: "0"}]'), yaml.safe_load("{0: {ref: example.invalid/testos:0}}"))
    assert list(doc["runtime"]["containerlab"]["images"]) == [0]
    assert faults(doc) == {
        ("/runtime/containerlab/images", RULE_IMAGES_COVERAGE, "version '0' has no image"),
        ("/runtime/containerlab/images/0", RULE_IMAGES_COVERAGE, "0 is no version the package lists"),
    }
    with pytest.raises(Rejected):
        platform_package.decode(doc)
    doc = listing(yaml.safe_load("[{name: 4.32}]"), yaml.safe_load('{"4.32": {ref: example.invalid/testos:0}}'))
    assert doc["versions"] == [{"name": 4.32}]
    assert {(p.pointer, p.rule) for p in platform_package.validate(doc)} == {("/versions/0/name", RULE_INVALID)}
    with pytest.raises(Rejected):
        platform_package.decode(doc)


def test_a_versions_name_is_the_releases_text() -> None:
    for name in ("24.7.1", "4.32.0.2F", "0", "v1_2-rc.3"):
        doc = listing([{"name": name}], {name: IMAGE})
        assert platform_package.validate(doc) == [], name
        loaded = platform_package.decode(doc)
        assert loaded.versions == (Version(name=name),) and platform_package.image(loaded) == Image(**IMAGE)
    for name in ("", "-1", "a/b", "a b"):
        found = platform_package.validate(listing([{"name": name}], {name: IMAGE}))
        assert {(p.pointer, p.rule) for p in found} == {("/versions/0/name", RULE_INVALID)}, name


def attributes(path: Path) -> set[str]:
    """Every attribute name `path`'s code reads or writes."""
    return {node.attr for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Attribute)}


def test_versions_and_images_are_read_by_the_package_module_alone() -> None:
    """No code branches on a version or names a release (D-014): outside the package's own module
    nothing of the core reads a package's `versions` or a runtime section's `images`. Each asks
    `platform_package.image`."""
    modules = sorted(SOURCE.rglob("*.py"))
    assert SOURCE / "platform_package.py" in modules and len(modules) > 40
    assert {"versions", "images"} <= attributes(SOURCE / "platform_package.py")  # the walk is not blind
    readers = {str(m.relative_to(SOURCE)): attributes(m) & {"versions", "images"} for m in modules}
    assert {m: found for m, found in readers.items() if found} == {"platform_package.py": {"versions", "images"}}


def test_a_ports_discovering_given_as_null_is_refused() -> None:
    """`discovering` may be left out, not given as nothing: its type is an object."""
    doc: dict[str, Any] = yaml.safe_load(CHASSISOS.read_text())
    doc["conformance"]["port"]["discovering"] = None
    assert {(p.pointer, p.rule) for p in platform_package.validate(doc)} == {
        ("/conformance/port/discovering", RULE_INVALID)
    }


def _descriptions(node: Any) -> list[str]:
    """Every description and comment text of a schema, at any depth."""
    if isinstance(node, dict):
        own = [v for k, v in node.items() if k in ("description", "$comment") and isinstance(v, str)]
        return own + [text for v in node.values() for text in _descriptions(v)]
    if isinstance(node, list):
        return [text for v in node for text in _descriptions(v)]
    return []


def test_every_rule_a_package_format_names_is_one_the_core_files() -> None:
    """A description that says a rule follows an event names a `RULE_*` value of `core/src`, so the
    formats promise no finding that no module files."""
    filed = {
        value
        for module in SOURCE.rglob("*.py")
        for value in re.findall(r'^\s*RULE_[A-Z_]+ = "([a-z_.]+)"', module.read_text(), re.M)
    }
    named: set[str] = set()
    for name in ("platform-package-1", "probe-package-1"):
        schema = json.loads((ROOT / "formats" / f"{name}.schema.json").read_text())
        for text in _descriptions(schema):
            named |= set(re.findall(r"\b(?:rule|records?|fails with)\s+\(?([a-z_]+(?:\.[a-z_]+)+)(?![\w.\[])", text))
    assert {"push.timeout", "readiness.timeout"} <= named  # the walk is not blind
    assert named - filed == set()
