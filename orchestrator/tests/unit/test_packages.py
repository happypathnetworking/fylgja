"""The packages' `platform.matches` as the core's registry joins them (`internal/psp`'s
load.go, `internal/intent`'s completeness.go): the shipped pairs, a pair no package names,
and the override and shipped directories by their variables."""

import shutil
from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import packages
from fylgja_orchestrator.adapters.infrahub.packages import Match, PackageError

REPO = Path(__file__).resolve().parents[3]
SHIPPED = "arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv(packages.ENV_OVERRIDE, raising=False)
    monkeypatch.delenv(packages.ENV_SHIPPED, raising=False)
    return monkeypatch


def package(directory: Path, name: str, id: str, nos: str, *pairs: tuple[str, str]) -> Path:
    lines = [f"platform:\n  id: {id}\n  nos: {nos}\n  matches:\n"]
    lines += [f"    - manufacturer: {m}\n      platform: {p}\n" for m, p in pairs]
    path = directory / f"{name}.yaml"
    path.write_text('psp_version: "0.7"\n' + "".join(lines))
    return path


def test_the_shipped_packages_are_the_repository_s(env):
    assert packages.repository_psp_dir() == REPO / "psp"
    reg = packages.load()
    assert reg.ids() == ["arista_eos", "nokia_srlinux"]
    assert reg.match("Nokia", "SR Linux").id == "nokia_srlinux"
    assert reg.match("Arista", "EOS").id == "arista_eos"
    assert reg.package_matches() == SHIPPED
    assert all(p.origin == packages.ORIGIN_SHIPPED for p in reg.packages)


@pytest.mark.parametrize(
    "manufacturer,platform",
    [("nokia", "SR Linux"), ("Nokia", "SR-Linux"), ("Nokia", "SR Linux "), ("", "SR Linux"), ("Arista", "")],
)
def test_a_pair_is_matched_exactly(env, manufacturer, platform):
    assert packages.load().match(manufacturer, platform) is None


def test_an_unmatched_platform_names_the_pair_and_every_package_s(env):
    reg = packages.load()
    assert reg.unmatched("n1", "nokia", "SR-Linux") == (
        "platform.unmatched",
        "n1",
        f'device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: {SHIPPED}',
    )
    assert reg.unmatched("n5", "", "SR Linux")[2] == (
        f'device n5: manufacturer "", platform "SR Linux"; the packages match: {SHIPPED}'
    )


def test_a_pair_is_named_as_go_quotes_it():
    assert str(Match('Ac"me', "OS\t1")) == 'manufacturer "Ac\\"me", platform "OS\\t1"'


def test_the_override_shadows_a_shipped_package_of_its_nos(env, tmp_path):
    package(tmp_path, "srl", "nokia_srlinux", "srlinux", ("Nokia", "SR Linux"), ("Nokia", "7220 IXR"))
    package(tmp_path, "acme", "acme_os", "acmeos", ("Acme", "AcmeOS"))
    env.setenv(packages.ENV_OVERRIDE, str(tmp_path))
    reg = packages.load()
    assert reg.ids() == ["acme_os", "arista_eos", "nokia_srlinux"]
    assert reg.match("Nokia", "7220 IXR").origin == packages.ORIGIN_OVERRIDE
    assert reg.match("Acme", "AcmeOS").id == "acme_os"
    assert reg.package_matches() == (
        "acme_os [Acme / AcmeOS], arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux, Nokia / 7220 IXR]"
    )


def test_an_override_given_beats_the_variable(env, tmp_path):
    env.setenv(packages.ENV_OVERRIDE, str(tmp_path / "absent"))
    assert packages.load(override_dir="").ids() == ["arista_eos", "nokia_srlinux"]


def test_an_override_directory_that_is_absent_is_refused(env, tmp_path):
    with pytest.raises(PackageError, match="is not a directory"):
        packages.load(override_dir=str(tmp_path / "absent"))


def test_an_override_naming_a_shipped_pair_is_refused(env, tmp_path):
    path = package(tmp_path, "dup", "other_srl", "othersrl", ("Nokia", "SR Linux"))
    with pytest.raises(PackageError) as raised:
        packages.load(override_dir=str(tmp_path))
    (finding,) = raised.value.findings
    assert (finding.rule, finding.object) == ("psp.matches.duplicate", str(path))
    assert finding.message == (
        f'manufacturer "Nokia", platform "SR Linux" is matched by package nokia_srlinux '
        f"({REPO / 'psp' / 'nokia_srlinux.yaml'}) and by package other_srl ({path}); "
        "a device of that pair would have two packages"
    )


def test_an_override_naming_a_shipped_id_is_refused(env, tmp_path):
    package(tmp_path, "dup", "nokia_srlinux", "othersrl", ("Other", "SRL"))
    with pytest.raises(PackageError) as raised:
        packages.load(override_dir=str(tmp_path))
    (finding,) = raised.value.findings
    assert (finding.rule, finding.object) == ("psp.identity.duplicate", "nokia_srlinux")
    assert finding.message == f'platform "nokia_srlinux" is already declared by {REPO / "psp" / "nokia_srlinux.yaml"}'


def test_the_shipped_directory_is_named_when_installed_elsewhere(env, tmp_path):
    shipped = tmp_path / "psp"
    shipped.mkdir()
    shutil.copy(REPO / "psp" / "nokia_srlinux.yaml", shipped)
    env.setenv(packages.ENV_SHIPPED, str(shipped))
    reg = packages.load()
    assert reg.ids() == ["nokia_srlinux"]
    assert reg.lookup_id("nokia_srlinux").path == str(shipped / "nokia_srlinux.yaml")


def test_no_shipped_package_says_which_variable_to_set(env, tmp_path):
    env.setenv(packages.ENV_SHIPPED, str(tmp_path))
    with pytest.raises(PackageError, match="set FYLGJA_PSP_SHIPPED"):
        packages.load()
