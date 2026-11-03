"""Platform package 1's loader: the shipped packages load to their model, and each rejection
fixture under testdata/packages/invalid/platform/ is refused for its fault alone."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fylgja_core import documents, platform_package
from fylgja_core.documents import Rejected
from fylgja_core.platform_package import (
    RULE_INVALID,
    RULE_MANAGEMENT_RULE,
    RULE_PLACEHOLDERS,
    RULE_RANGES,
    RULE_RENAME_COVERAGE,
    RULE_RULE_NAME,
    RULE_VERSION,
    Resources,
    Rule,
)

ROOT = Path(__file__).resolve().parents[2]
PSP = ROOT / "psp"
SHIPPED = [*sorted(PSP.glob("*.yaml")), ROOT / "testdata" / "packages" / "chassisos.yaml"]
INVALID = ROOT / "testdata" / "packages" / "invalid" / "platform"

# Every rejection fixture, and the (pointer, rule) pairs the loader must report for it:
# exactly these, so a fixture with one fault yields one fault. several.yaml carries five.
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
}


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
    assert package.runtime.containerlab.image.pull_secret is None
    assert package.conformance.port.discovering.absent is None


def test_the_eos_package_renames_every_data_rule() -> None:
    package = platform_package.load(PSP / "arista_eos.yaml")
    containerlab = package.runtime.containerlab
    assert containerlab.alias is False and containerlab.rename is not None
    assert [r.rule for r in containerlab.rename] == ["ethernet", "modular", "breakout"]
    assert containerlab.image.pull_secret == "arista-ceos" and containerlab.hot_add_ports is False
    assert package.conformance.port.discovering.absent == "true"


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
