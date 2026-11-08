"""The core's Kubernetes client (D-064), with no cluster: `client()` is built from the service
account or `KUBECONFIG` alone, and the core's namespace is the service account's. What each
fault of a kubeconfig or a service account is refused as, through the driver registry, is in
test_drivers.py."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
import pytest
import yaml
from lightkube import AsyncClient

from fylgja_core import kubeapi

KUBECONFIG = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{"name": "example", "cluster": {"server": "https://kube.example:6443"}}],
    "users": [{"name": "example", "user": {"token": "not-a-token"}}],
    "contexts": [{"name": "example", "context": {"cluster": "example", "user": "example"}}],
    "current-context": "example",
}


def test_a_client_with_neither_a_service_account_nor_kubeconfig_is_unconfigured(tmp_path: Path) -> None:
    with pytest.raises(kubeapi.Unconfigured) as raised:
        kubeapi.client({}, tmp_path)
    assert raised.value.variable == "KUBECONFIG"


def test_a_kubeconfig_naming_an_absent_file_is_unconfigured(tmp_path: Path) -> None:
    with pytest.raises(kubeapi.Unconfigured) as raised:
        kubeapi.client({"KUBECONFIG": str(tmp_path / "absent")}, tmp_path)
    assert raised.value.variable == "KUBECONFIG"


def test_a_client_is_built_from_the_file_kubeconfig_names(tmp_path: Path) -> None:
    path = tmp_path / "kubeconfig"
    path.write_text(yaml.safe_dump(KUBECONFIG))
    answered = kubeapi.client({"KUBECONFIG": str(path)}, tmp_path / "no-service-account")
    try:
        assert isinstance(answered, AsyncClient)
        assert answered.config.cluster.server == "https://kube.example:6443"
        # One request's budget, where lightkube's own is 10 s.
        assert answered._client._client.timeout == httpx2.Timeout(kubeapi.REQUEST_TIMEOUT_S)
    finally:
        asyncio.run(answered.close())


def test_the_core_namespace_is_the_service_accounts_and_none_off_the_cluster(tmp_path: Path) -> None:
    assert kubeapi.core_namespace(tmp_path) is None
    (tmp_path / "namespace").write_text("fylgja\n")
    assert kubeapi.core_namespace(tmp_path) == "fylgja"


def test_the_service_account_is_looked_up_when_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account = tmp_path / "service-account"
    account.mkdir()
    (account / "namespace").write_text("fylgja\n")
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", account)
    assert kubeapi.core_namespace() == "fylgja"
    with pytest.raises(kubeapi.Unconfigured) as raised:
        kubeapi.client({})  # no token there: off the cluster, and no KUBECONFIG
    assert raised.value.variable == "KUBECONFIG" and f"no service account at {account}" in str(raised.value)
