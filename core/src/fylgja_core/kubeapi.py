"""The core's Kubernetes client, made in one module above the seam (D-064).

`client()` builds lightkube's client from the service account when the core runs as a pod, and
from the file `KUBECONFIG` names otherwise; never from lightkube's own default,
`~/.kube/config`. What keeps it from making one is `Unconfigured`, naming the variable at
fault. It names no runtime: the clabernetes driver's reach into Kubernetes
(`fylgja_core.clabernetes.kube`) and the Lease (`fylgja_core.lease`) make their clients here.
Every behaviour it relies on was read (verified-facts.md, lightkube 1.0.1).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import httpx2
import yaml
from lightkube import AsyncClient, ConfigError, KubeConfig

FIELD_MANAGER = "fylgja-core"
"""The field manager of every server-side apply and patch the core makes."""

REQUEST_TIMEOUT_S = 30.0
"""One API request's budget; a watch's read has none, and an exec's is its own."""

SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
"""Where Kubernetes mounts a pod's service account: its token, its namespace and the cluster's CA."""

SERVICE_VARIABLES = ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT")
"""The API server's address, which Kubernetes sets in every pod and lightkube reads beside the
service account."""

CONFIG_FAILURES = (ConfigError, OSError, yaml.YAMLError, AttributeError, KeyError, TypeError, ValueError)
"""What lightkube raises making a client from a kubeconfig or a service account it cannot use, each
read (verified-facts.md, lightkube 1.0.1): `ConfigError` for a file missing or a current context
naming no context, `KeyError` for a context naming a cluster or user that is not there,
`FileNotFoundError` or `ssl.SSLError` for a certificate missing or not one, `AttributeError` or
`TypeError` for YAML not shaped as a kubeconfig, and `binascii.Error`, a `ValueError`, for data
that is not base64."""


class Unconfigured(Exception):
    """The core can reach no cluster, `variable` the one at fault: off the cluster, `KUBECONFIG`
    not set or naming a file that is not a kubeconfig it can read; in a pod,
    `KUBERNETES_SERVICE_HOST` or `KUBERNETES_SERVICE_PORT` not set, or `KUBECONFIG` for a
    service account it cannot read (`client`)."""

    def __init__(self, variable: str, message: str) -> None:
        super().__init__(message)
        self.variable = variable


def client(environ: Mapping[str, str] = os.environ, service_account: Path | None = None) -> AsyncClient:
    """lightkube's client: from the service account `service_account` (`SERVICE_ACCOUNT`, looked
    up when called, when None) if its token is a file, the core running as a pod; else from the
    file `environ["KUBECONFIG"]` names. No request is made.

    Whatever keeps a client from being made is `Unconfigured`, naming a variable. In a pod:
    `KUBERNETES_SERVICE_HOST` or `KUBERNETES_SERVICE_PORT` not set, which Kubernetes sets in
    every pod and lightkube reads from the process's environment; and `KUBECONFIG` for any other
    fault of the service account (a token with no `namespace` file beside it, say). Off the
    cluster, `KUBECONFIG`: not set, or naming a file no client can be made from (missing, not a
    kubeconfig, a current context naming no context, a certificate or key file missing). The
    error's text may quote the file, and a file holds credentials: a message carries the
    variable, a path and the error's type, never what a file holds."""
    account = SERVICE_ACCOUNT if service_account is None else service_account
    if (account / "token").is_file():
        for variable in SERVICE_VARIABLES:
            if not environ.get(variable):
                raise Unconfigured(variable, f"{variable} is not set, or is empty, and the core runs with the service "
                                             f"account at {account}: Kubernetes sets it in every pod")
        try:
            return _client(KubeConfig.from_service_account(account))
        except CONFIG_FAILURES as e:
            held = "is set and not read beside a service account" if environ.get("KUBECONFIG") else "is not set"
            raise Unconfigured("KUBECONFIG", f"KUBECONFIG {held}, and the pod's service account at {account} could "
                                             f"not be read ({type(e).__name__})") from None
    path = environ.get("KUBECONFIG")
    if not path:
        raise Unconfigured("KUBECONFIG", f"KUBECONFIG is not set, or is empty, and there is no service account "
                                         f"at {account}: the core can reach no cluster")
    try:
        return _client(KubeConfig.from_file(path))
    except CONFIG_FAILURES as e:
        raise Unconfigured("KUBECONFIG", f"KUBECONFIG names {path}, which cannot be read as a kubeconfig "
                                         f"({type(e).__name__})") from None


def _client(config: KubeConfig) -> AsyncClient:
    return AsyncClient(config=config, field_manager=FIELD_MANAGER, timeout=httpx2.Timeout(REQUEST_TIMEOUT_S))


def core_namespace(service_account: Path | None = None) -> str | None:
    """The namespace the core runs in, from the service account `service_account`
    (`SERVICE_ACCOUNT`, looked up when called, when None); None off the cluster."""
    path = (SERVICE_ACCOUNT if service_account is None else service_account) / "namespace"
    return (path.read_text().strip() or None) if path.is_file() else None
