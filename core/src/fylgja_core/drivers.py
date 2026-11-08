"""The driver registry: the drivers this core serves, by name (Constitution XIII, D-017, D-046).

This is the one module above the seam that names a runtime, and it is the registry, not a
branch: the server lists `NAMES` (GET /v1/drivers), makes the driver `FYLGJA_DRIVER` names
through `make` and closes it through `close`, the settings require what that driver `needs` and
a store with a directory when it `needs_directory`, and everything else reaches a runtime
through the seam alone, branching at most on a declared capability. A driver is added here and
nowhere else above the seam. The clabernetes driver's cluster is reached through its `kube`
module alone, the driver's one module that imports lightkube, over the client
`fylgja_core.kubeapi` makes (D-064).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fylgja_core import clabernetes, containerlab, kubeapi
from fylgja_core.clabernetes import kube
from fylgja_core.clabernetes.driver import ClabernetesDriver
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.credentials import Provider
from fylgja_core.driver import Capabilities, Driver

NAMES: tuple[str, ...] = (clabernetes.NAME, containerlab.NAME)
"""Every driver this core serves, sorted."""

_CAPABILITIES: Mapping[str, Capabilities] = {
    clabernetes.NAME: clabernetes.CAPABILITIES,
    containerlab.NAME: containerlab.CAPABILITIES,
}
_NEEDS: Mapping[str, tuple[str, ...]] = {
    clabernetes.NAME: ("FYLGJA_CLABERNETES_NAMESPACE", "FYLGJA_POD_CIDR"),
    containerlab.NAME: (),
}
_NEEDS_DIRECTORY: Mapping[str, bool] = {
    clabernetes.NAME: False,
    containerlab.NAME: True,
}


class Unmakeable(Exception):
    """The driver cannot be made in this environment: `variable` names the variable at fault,
    `KUBECONFIG` when the core runs off the cluster and can reach none, and in a pod
    `KUBERNETES_SERVICE_HOST` or `KUBERNETES_SERVICE_PORT` when one is unset."""

    def __init__(self, variable: str, message: str) -> None:
        super().__init__(message)
        self.variable = variable


def make(
    name: str,
    *,
    root: Path | None,
    credentials: Provider,
    clabernetes_namespace: str | None = None,
    pod_cidr: str | None = None,
) -> Driver:
    """The driver `name`, made from what it needs. The containerlab driver keeps its working
    files under `root`, the store's directory. The clabernetes driver reaches the cluster
    through lightkube's client, from the service account in a pod and from `KUBECONFIG` off the
    cluster, with no request made until it acts; it makes its pull secrets from `credentials`,
    and reserves clabernetes' namespace `clabernetes_namespace`, the pod CIDR `pod_cidr` and the
    core's own namespace when the core runs as a pod (D-057).

    A value the driver needs that is not given is a `ValueError`; a cluster the core cannot
    reach is `Unmakeable`, naming the variable at fault; a name this core does not serve is a
    `KeyError`."""
    served = _served(name)
    if served == containerlab.NAME:
        if root is None:
            raise ValueError("the containerlab driver needs a root, the store's directory")
        return ContainerlabDriver(root)
    if served == clabernetes.NAME:
        if clabernetes_namespace is None or pod_cidr is None:
            raise ValueError("the clabernetes driver needs clabernetes' namespace and the pod CIDR")
        try:
            client = kubeapi.client()
        except kubeapi.Unconfigured as e:
            raise Unmakeable(e.variable, str(e)) from e
        return ClabernetesDriver(kube.LightKube(client), credentials, controller_namespace=clabernetes_namespace,
                                 pod_cidr=pod_cidr, core_namespace=kubeapi.core_namespace())
    raise AssertionError(name)  # a name in NAMES with no branch here: never made as another driver


async def close(driver: Driver) -> None:
    """Close what `make` opened for `driver`: the clabernetes driver's client and its
    connections. The containerlab driver holds nothing open between its calls, and a driver
    `make` did not make is left as it is."""
    if isinstance(driver, ClabernetesDriver) and isinstance(driver.kube, kube.LightKube):
        await driver.kube.close()


def capabilities(name: str) -> Capabilities:
    """What the driver `name` declares of its runtime, without making it; `KeyError` as `make`."""
    return _CAPABILITIES[_served(name)]


def needs(name: str) -> tuple[str, ...]:
    """The `FYLGJA_*` variables the driver `name` is made from beyond those every driver reads,
    each required when it is the driver (D-057); `KeyError` as `make`."""
    return _NEEDS[_served(name)]


def needs_directory(name: str) -> bool:
    """Whether the driver `name` keeps its working files under the store's directory, the `root`
    `make` gives it, so that an object store, which has none, cannot serve it (D-061); `KeyError`
    as `make`."""
    return _NEEDS_DIRECTORY[_served(name)]


def _served(name: str) -> str:
    if name not in NAMES:
        raise KeyError(f"no driver {name!r}; this core serves {', '.join(NAMES)}")
    return name
