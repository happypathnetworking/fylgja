"""The driver registry: the one place above the seam that names a runtime (Constitution XIII)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import clabernetes, containerlab, drivers, kubeapi
from fylgja_core.clabernetes import kube
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.credentials import Provider
from fylgja_core.driver import Driver

KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"name": "example", "cluster": {"server": "https://kube.example:6443"}}],
    "users": [{"name": "example", "user": {"token": "not-a-token"}}],
    "contexts": [{"name": "example", "context": {"cluster": "example", "user": "example"}}],
    "current-context": "example",
}
"""A minimal kubeconfig, its server one no request could reach."""

TOKEN = "service-account-token"
"""What the tests' service accounts hold as their token, which no message may carry."""


@pytest.fixture(autouse=True)
def _off_the_cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No service account, whatever the host running the tests: a test that needs one sets its own."""
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", tmp_path / "no-service-account")


def kubeconfig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    """`config` written as YAML to a file `KUBECONFIG` names."""
    path = tmp_path / "kubeconfig"
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("KUBECONFIG", str(path))


def service_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *files: str) -> Path:
    """A service account holding a token and `files`, each a line of its own, where `kubeapi` looks."""
    account = tmp_path / "service-account"
    account.mkdir()
    (account / "token").write_text(TOKEN)
    for name in files:
        (account / name).write_text(f"{name}-content\n")
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", account)
    return account


def make_clabernetes() -> Driver:
    return drivers.make("clabernetes", root=None, credentials=Provider({}), clabernetes_namespace="c9s",
                        pod_cidr="10.244.0.0/16")


def test_the_registry_makes_the_local_driver_rooted_where_it_is_told(tmp_path: Path) -> None:
    driver = drivers.make("containerlab", root=tmp_path, credentials=Provider({}))
    assert driver.name == "containerlab"
    assert isinstance(driver, ContainerlabDriver) and driver.root == tmp_path


def test_the_local_driver_without_a_root_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="root"):
        drivers.make("containerlab", root=None, credentials=Provider({}))


def test_an_unknown_driver_is_a_key_error_naming_the_ones_served(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="no driver 'kubevirt'; this core serves clabernetes, containerlab"):
        drivers.make("kubevirt", root=tmp_path, credentials=Provider({}))
    with pytest.raises(KeyError, match="no driver 'kubevirt'"):
        drivers.capabilities("kubevirt")
    with pytest.raises(KeyError, match="no driver 'kubevirt'"):
        drivers.needs("kubevirt")
    with pytest.raises(KeyError, match="no driver 'kubevirt'"):
        drivers.needs_directory("kubevirt")


def test_a_name_served_without_its_branch_is_made_as_no_other_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kubeconfig(tmp_path, monkeypatch, KUBECONFIG)
    monkeypatch.setattr(drivers, "NAMES", (*drivers.NAMES, "kubevirt"))
    with pytest.raises(AssertionError, match="kubevirt"):
        drivers.make("kubevirt", root=tmp_path, credentials=Provider({}), clabernetes_namespace="c9s",
                     pod_cidr="10.244.0.0/16")


def test_the_names_are_sorted_and_each_has_its_capabilities() -> None:
    assert drivers.NAMES == ("clabernetes", "containerlab")
    assert list(drivers.NAMES) == sorted(drivers.NAMES)
    assert drivers.capabilities("clabernetes") == clabernetes.CAPABILITIES
    assert drivers.capabilities("containerlab") == containerlab.CAPABILITIES


def test_each_driver_names_the_settings_it_needs_set() -> None:
    assert drivers.needs("clabernetes") == ("FYLGJA_CLABERNETES_NAMESPACE", "FYLGJA_POD_CIDR")
    assert drivers.needs("containerlab") == ()


def test_the_local_driver_alone_keeps_its_files_in_the_stores_directory() -> None:
    # The settings refuse an object store for a driver that needs one (D-061), naming no runtime.
    assert drivers.needs_directory("containerlab") is True
    assert drivers.needs_directory("clabernetes") is False


def test_the_registry_makes_the_clabernetes_driver_from_kubeconfig_with_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kubeconfig(tmp_path, monkeypatch, KUBECONFIG)
    provider = Provider({})
    # `make` is synchronous and lightkube's client is asynchronous: a driver answered is one made
    # with no request, and none could reach kube.example.
    driver = drivers.make("clabernetes", root=None, credentials=provider, clabernetes_namespace="c9s",
                          pod_cidr="10.244.0.0/16")
    try:
        assert isinstance(driver, ClabernetesDriver) and driver.name == "clabernetes"
        assert isinstance(driver.kube, kube.LightKube)
        assert driver.credentials is provider
        assert (driver.controller_namespace, driver.pod_cidr, driver.core_namespace) == ("c9s", "10.244.0.0/16", None)
    finally:
        if isinstance(driver, ClabernetesDriver) and isinstance(driver.kube, kube.LightKube):
            asyncio.run(driver.kube.close())


def test_the_registry_gives_the_clabernetes_driver_the_namespace_the_core_runs_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # In a pod the service account names the core's namespace, which admit reserves (D-057).
    service_account(tmp_path, monkeypatch, "namespace")
    client = object()
    monkeypatch.setattr(kubeapi, "client", lambda: client)
    driver = make_clabernetes()
    assert isinstance(driver, ClabernetesDriver) and isinstance(driver.kube, kube.LightKube)
    assert driver.core_namespace == "namespace-content"


def test_the_clabernetes_driver_with_no_cluster_to_reach_is_unmakeable_naming_kubeconfig(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KUBECONFIG", raising=False)
    with pytest.raises(drivers.Unmakeable) as raised:
        make_clabernetes()
    assert raised.value.variable == "KUBECONFIG"
    assert "KUBECONFIG" in str(raised.value)


@pytest.mark.parametrize(("config", "error"), [
    ({**KUBECONFIG, "current-context": "absent"}, "ConfigError"),
    ({**KUBECONFIG, "contexts": [{"name": "example", "context": {"cluster": "absent", "user": "example"}}]},
     "KeyError"),
    ({**KUBECONFIG, "users": [{"name": "example", "user": {"client-certificate": "absent.crt",
                                                           "client-key": "absent.key"}}]},
     "FileNotFoundError"),
    ("a scalar, not a kubeconfig", "AttributeError"),
], ids=["context-missing", "cluster-missing", "certificate-missing", "not-a-mapping"])
def test_a_kubeconfig_no_client_can_be_made_from_is_unmakeable_naming_kubeconfig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: Any, error: str
) -> None:
    kubeconfig(tmp_path, monkeypatch, config)
    with pytest.raises(drivers.Unmakeable) as raised:
        make_clabernetes()
    assert raised.value.variable == "KUBECONFIG"
    message = str(raised.value)
    assert f"KUBECONFIG names {tmp_path / 'kubeconfig'}" in message and f"({error})" in message
    assert "not-a-token" not in message and "kube.example" not in message


@pytest.mark.parametrize(("set_", "held"), [
    (False, "is not set"),
    (True, "is set and not read beside a service account"),
], ids=["kubeconfig-unset", "kubeconfig-set"])
def test_a_service_account_with_no_namespace_file_is_unmakeable_naming_kubeconfig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, set_: bool, held: str
) -> None:
    account = service_account(tmp_path, monkeypatch, "ca.crt")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "192.0.2.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "6443")
    if set_:
        kubeconfig(tmp_path, monkeypatch, KUBECONFIG)  # a client could be made from it, and is not
    else:
        monkeypatch.delenv("KUBECONFIG", raising=False)
    with pytest.raises(drivers.Unmakeable) as raised:
        make_clabernetes()
    assert raised.value.variable == "KUBECONFIG"
    message = str(raised.value)
    assert message.startswith(f"KUBECONFIG {held}, and the pod's service account")
    assert str(account) in message and "(ConfigError)" in message
    assert TOKEN not in message and "ca.crt-content" not in message


@pytest.mark.parametrize("variable", ["KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"])
def test_a_service_account_without_the_api_servers_address_is_unmakeable_naming_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    service_account(tmp_path, monkeypatch, "namespace", "ca.crt")
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "192.0.2.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "6443")
    monkeypatch.delenv(variable)
    with pytest.raises(drivers.Unmakeable) as raised:
        make_clabernetes()
    assert raised.value.variable == variable
    assert str(raised.value).startswith(f"{variable} is not set") and TOKEN not in str(raised.value)


def test_close_closes_the_client_make_made_for_the_clabernetes_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        closed = 0

        async def close(self) -> None:
            self.closed += 1

    client = Client()
    monkeypatch.setattr(kubeapi, "client", lambda: client)
    driver = make_clabernetes()
    asyncio.run(drivers.close(driver))
    assert client.closed == 1


def test_close_has_nothing_to_close_for_the_local_driver(tmp_path: Path) -> None:
    driver = drivers.make("containerlab", root=tmp_path, credentials=Provider({}))
    asyncio.run(drivers.close(driver))  # no client, no command: nothing is open until it acts
    assert isinstance(driver, ContainerlabDriver) and driver.root == tmp_path


@pytest.mark.parametrize(("namespace", "cidr"), [(None, "10.244.0.0/16"), ("c9s", None), (None, None)])
def test_the_clabernetes_driver_without_its_namespace_or_pod_cidr_is_a_value_error(
    namespace: str | None, cidr: str | None
) -> None:
    with pytest.raises(ValueError, match="clabernetes' namespace and the pod CIDR"):
        drivers.make("clabernetes", root=None, credentials=Provider({}), clabernetes_namespace=namespace,
                     pod_cidr=cidr)
