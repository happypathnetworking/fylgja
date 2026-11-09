"""The kustomize base under `deploy/` as the tree states it (D-062, D-071): the core as one pod in the namespace
`fylgja` under its Lease, its roles, its Service, and its store, Versity S3 Gateway over a `local-path` volume (D-061),
shut to every pod but the core's. The base names what is the same at every site and nothing a site decides: no Secret
and no ConfigMap, no address, no host with a port but the store's endpoint and the core's listen address, and no
variable that is not a setting `.env.example` names. The roles' rules are tables here, so a rule changes with its test.
The site's overlay, under `local/deploy/`, is `deploy/README.md`'s example, which makes exactly the Secrets and the
ConfigMap the base names. `kubectl kustomize deploy/` builds the base."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"

NAMESPACE = "fylgja"
PART_OF = {"app.kubernetes.io/part-of": "fylgja"}
CORE_POD = {"app.kubernetes.io/name": "fylgja-core"}
GATEWAY_POD = {"app.kubernetes.io/name": "versity"}
CLUSTER_SCOPED = {"Namespace", "ClusterRole", "ClusterRoleBinding"}
SUBJECT = {"kind": "ServiceAccount", "name": "fylgja-core", "namespace": NAMESPACE}
GATEWAY_IMAGE = "ghcr.io/versity/versitygw:v1.10.0"

# The core container's literal environment, and no other: what is the same at every site.
CORE_ENV = {
    "FYLGJA_STORE": "s3://fylgja",
    "FYLGJA_S3_ENDPOINT": "http://versity:7070",
    "FYLGJA_LEASE": "fylgja-core",
    "FYLGJA_DRIVER": "clabernetes",
    "FYLGJA_LISTEN": "0.0.0.0:7650",
    "FYLGJA_TOKENS": "/etc/fylgja/tokens/tokens",
    "FYLGJA_TLS_CERT": "/etc/fylgja/tls/tls.crt",
    "FYLGJA_TLS_KEY": "/etc/fylgja/tls/tls.key",
}

# The gateway's root keys, each the key of the Secret `fylgja-s3` the core reads its own two from.
GATEWAY_KEYS = {"ROOT_ACCESS_KEY": "FYLGJA_S3_ACCESS_KEY", "ROOT_SECRET_KEY": "FYLGJA_S3_SECRET_KEY"}

Rules = dict[tuple[str, str, tuple[str, ...]], set[str]]

# The ClusterRole: D-062's nouns, with the verbs the clabernetes driver's calls were read to need from inside a pod
# (verified-facts.md), and no other. A server-side apply asks `create` of an object not there yet beside `patch`; a
# Secret, a NetworkPolicy and a Topology go with their namespace, so none is deleted alone. `watch` on pods is the
# driver's `events`, one watch on pods across every namespace by the owner's label, and `list` is `pods`; `delete` on
# pods is the renewal's and the hot-add's (D-070). An exec's WebSocket handshake asks `get` and `create` on `pods/exec`.
CLUSTER_RULES: Rules = {
    ("", "namespaces", ()): {"get", "create", "patch", "delete"},
    ("", "nodes", ()): {"get", "list"},
    ("", "secrets", ()): {"create", "patch"},
    ("networking.k8s.io", "networkpolicies", ()): {"create", "patch"},
    ("c9s.run", "topologies", ()): {"get", "create", "patch"},
    ("", "services", ()): {"list", "patch"},
    ("", "pods", ()): {"list", "watch", "delete"},
    ("", "pods/exec", ()): {"get", "create"},
}

# The Role in the core's namespace: its one Lease by name, and `create`, which a name does not confine (D-071).
LEASE_RULES: Rules = {
    ("coordination.k8s.io", "leases", ()): {"create"},
    ("coordination.k8s.io", "leases", ("fylgja-core",)): {"get", "update"},
}

ADDRESSES = {"0.0.0.0"}
HOSTS_WITH_PORTS = {"versity:7070", "0.0.0.0:7650"}

_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_HOST_PORT = re.compile(r"(?<![\w.-])[A-Za-z0-9][\w.-]*:\d+(?!\d)")
_VARIABLE = re.compile(r"\bFYLGJA_[A-Z0-9_]*")
_SETTING = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
_YAML_BLOCK = re.compile(r"^```yaml\n(.*?)^```$", re.MULTILINE | re.DOTALL)


def _files() -> list[Path]:
    """Every file under `deploy/`, the README among them."""
    return sorted(p for p in DEPLOY.rglob("*") if p.is_file())


def _manifests() -> list[Path]:
    return sorted(p for p in DEPLOY.glob("*.yaml") if p.name != "kustomization.yaml")


def _objects() -> list[dict[str, Any]]:
    """Every object of every manifest under `deploy/`."""
    return [o for p in _manifests() for o in yaml.safe_load_all(p.read_text()) if o is not None]


def _one(kind: str, name: str) -> dict[str, Any]:
    found = [o for o in _objects() if o["kind"] == kind and o["metadata"]["name"] == name]
    assert len(found) == 1, f"{kind} {name}: {len(found)} in deploy/"
    return found[0]


def _pod(kind: str, name: str) -> dict[str, Any]:
    spec: dict[str, Any] = _one(kind, name)["spec"]["template"]["spec"]
    return spec


def _container(kind: str, name: str, container: str) -> dict[str, Any]:
    named: list[dict[str, Any]] = [c for c in _pod(kind, name)["containers"] if c["name"] == container]
    [found] = named
    return found


def _rules(role: dict[str, Any]) -> Rules:
    """A role's rules by API group, resource and names, whatever rules they are written in."""
    rules: Rules = {}
    for rule in role["rules"]:
        for group in rule["apiGroups"]:
            for resource in rule["resources"]:
                key = (group, resource, tuple(sorted(rule.get("resourceNames", []))))
                rules.setdefault(key, set()).update(rule["verbs"])
    return rules


def _settings() -> set[str]:
    """The names `.env.example` lists."""
    return set(_SETTING.findall((ROOT / ".env.example").read_text()))


def _overlay() -> dict[str, Any]:
    """`deploy/README.md`'s example overlay, its one YAML block."""
    blocks = _YAML_BLOCK.findall((DEPLOY / "README.md").read_text())
    assert len(blocks) == 1, f"deploy/README.md holds {len(blocks)} YAML blocks, not the overlay's one"
    overlay: dict[str, Any] = yaml.safe_load(blocks[0])
    return overlay


def _named_by_the_base() -> tuple[set[str], set[str]]:
    """The Secrets and the ConfigMaps the base's pods name, which the site's overlay makes."""
    secrets: set[str] = set()
    configmaps: set[str] = set()
    for o in _objects():
        if o["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        pod = o["spec"]["template"]["spec"]
        secrets |= {s["name"] for s in pod.get("imagePullSecrets", [])}
        for volume in pod.get("volumes", []):
            if "secret" in volume:
                secrets.add(volume["secret"]["secretName"])
            if "configMap" in volume:
                configmaps.add(volume["configMap"]["name"])
        for container in pod.get("initContainers", []) + pod["containers"]:
            for source in container.get("envFrom", []):
                if "secretRef" in source:
                    secrets.add(source["secretRef"]["name"])
                if "configMapRef" in source:
                    configmaps.add(source["configMapRef"]["name"])
            for variable in container.get("env", []):
                reference = variable.get("valueFrom", {})
                if "secretKeyRef" in reference:
                    secrets.add(reference["secretKeyRef"]["name"])
                if "configMapKeyRef" in reference:
                    configmaps.add(reference["configMapKeyRef"]["name"])
    return secrets, configmaps


def test_the_base_lists_every_manifest_and_generates_nothing() -> None:
    kustomization = yaml.safe_load((DEPLOY / "kustomization.yaml").read_text())
    assert kustomization["kind"] == "Kustomization"
    assert sorted(kustomization["resources"]) == [p.name for p in _manifests()]
    # The images' registry and tag, the Secrets and the ConfigMap are the site's overlay's.
    assert not {"images", "secretGenerator", "configMapGenerator"} & kustomization.keys()


def test_every_object_is_in_or_bound_to_the_namespace_fylgja_and_labelled() -> None:
    objects = _objects()
    assert {"Namespace", "ClusterRoleBinding", "RoleBinding"} <= {o["kind"] for o in objects}
    for o in objects:
        metadata = o["metadata"]
        what = f"{o['kind']} {metadata['name']}"
        assert PART_OF.items() <= metadata.get("labels", {}).items(), what
        if o["kind"] == "Namespace":
            assert metadata["name"] == NAMESPACE
        if o["kind"] in CLUSTER_SCOPED:
            assert "namespace" not in metadata, what
        else:
            assert metadata.get("namespace") == NAMESPACE, what
        if o["kind"] in {"ClusterRoleBinding", "RoleBinding"}:
            assert o["subjects"] == [SUBJECT], what
        if "template" in o.get("spec", {}):
            assert PART_OF.items() <= o["spec"]["template"]["metadata"]["labels"].items(), what


def test_no_secret_and_no_configmap_is_in_the_base() -> None:
    assert [o["metadata"]["name"] for o in _objects() if o["kind"] in {"Secret", "ConfigMap"}] == []


def test_the_scan_finds_an_address_and_a_host_with_a_port_a_placeholder_holding_one_among_them() -> None:
    text = "at 192.0.2.10. and https://registry.example:5000/fylgja and 198.51.100.7:443, and <198.51.100.8>"
    assert _IPV4.findall(text) == ["192.0.2.10", "198.51.100.7", "198.51.100.8"]
    assert _HOST_PORT.findall(text) == ["registry.example:5000", "198.51.100.7:443"]


def test_no_address_and_no_host_with_a_port_but_the_bases_own_anywhere_under_deploy() -> None:
    files = _files()
    assert DEPLOY / "README.md" in files
    for path in files:
        text = path.read_text()  # a `<placeholder>` is read too: one holding an address is no placeholder
        assert set(_IPV4.findall(text)) <= ADDRESSES, path.name
        assert set(_HOST_PORT.findall(text)) <= HOSTS_WITH_PORTS, path.name


def test_the_core_containers_literal_environment_is_the_bases_alone() -> None:
    core = _container("Deployment", "fylgja-core", "core")
    assert [set(variable) for variable in core["env"]] == [{"name", "value"}] * len(CORE_ENV)
    assert {variable["name"]: variable["value"] for variable in core["env"]} == CORE_ENV
    assert core["envFrom"] == [
        {"secretRef": {"name": "fylgja-credentials"}},
        {"secretRef": {"name": "fylgja-s3"}},
        {"configMapRef": {"name": "fylgja-site"}},
    ]


def test_the_core_reads_its_files_from_secrets_mounted_read_only() -> None:
    pod = _pod("Deployment", "fylgja-core")
    core = _container("Deployment", "fylgja-core", "core")
    volumes = {v["name"]: {k: x for k, x in v.items() if k != "name"} for v in pod["volumes"]}
    mounts = {m["name"]: m for m in core["volumeMounts"]}
    assert volumes == {
        "tokens": {"secret": {"secretName": "fylgja-tokens"}},
        "tls": {"secret": {"secretName": "fylgja-tls"}},
        "tmp": {"emptyDir": {}},
    }
    assert mounts == {
        "tokens": {"name": "tokens", "mountPath": "/etc/fylgja/tokens", "readOnly": True},
        "tls": {"name": "tls", "mountPath": "/etc/fylgja/tls", "readOnly": True},
        "tmp": {"name": "tmp", "mountPath": "/tmp"},
    }
    assert CORE_ENV["FYLGJA_TOKENS"].startswith(mounts["tokens"]["mountPath"] + "/")
    assert CORE_ENV["FYLGJA_TLS_CERT"].startswith(mounts["tls"]["mountPath"] + "/")
    assert CORE_ENV["FYLGJA_TLS_KEY"].startswith(mounts["tls"]["mountPath"] + "/")


def test_the_core_is_one_replica_under_recreate_with_a_readiness_probe_alone() -> None:
    spec = _one("Deployment", "fylgja-core")["spec"]
    assert spec["replicas"] == 1
    assert spec["strategy"] == {"type": "Recreate"}  # a second core must never start beside the first
    pod = spec["template"]["spec"]
    assert pod["serviceAccountName"] == "fylgja-core"
    assert pod["imagePullSecrets"] == [{"name": "fylgja-registry"}]
    [core] = pod["containers"]
    assert (core["name"], core["image"]) == ("core", "fylgja-core")
    assert core["ports"] == [{"name": "api", "containerPort": 7650}]
    # Nothing listens until the Lease is held, so a waiting pod is never Ready, and never restarted for waiting.
    assert core["readinessProbe"] == {"tcpSocket": {"port": "api"}, "periodSeconds": 5}
    assert "livenessProbe" not in core and "startupProbe" not in core


def test_the_core_pods_label_is_what_its_deployment_service_and_the_gateways_policy_select() -> None:
    deployment = _one("Deployment", "fylgja-core")["spec"]
    assert CORE_POD.items() <= deployment["template"]["metadata"]["labels"].items()
    assert deployment["selector"] == {"matchLabels": CORE_POD}
    service = _one("Service", "fylgja-core")["spec"]
    assert service["type"] == "LoadBalancer"
    assert service["selector"] == CORE_POD
    assert service["ports"] == [{"name": "api", "port": 443, "targetPort": "api"}]


def test_the_gateway_admits_the_cores_pods_alone_on_7070() -> None:
    gateway = _one("StatefulSet", "versity")["spec"]
    assert GATEWAY_POD.items() <= gateway["template"]["metadata"]["labels"].items()
    assert gateway["selector"] == {"matchLabels": GATEWAY_POD}
    policy = _one("NetworkPolicy", "versity")["spec"]
    assert policy["podSelector"] == {"matchLabels": GATEWAY_POD}
    assert policy["policyTypes"] == ["Ingress"]
    # One rule, one source: a pod selector alone, so this namespace's pods, those of the core's label.
    assert policy["ingress"] == [{"from": [{"podSelector": {"matchLabels": CORE_POD}}],
                                  "ports": [{"protocol": "TCP", "port": 7070}]}]


def test_the_roles_rules_are_the_tables() -> None:
    assert _rules(_one("ClusterRole", "fylgja-core")) == CLUSTER_RULES
    assert _rules(_one("Role", "fylgja-core-lease")) == LEASE_RULES
    group = "rbac.authorization.k8s.io"
    assert _one("ClusterRoleBinding", "fylgja-core")["roleRef"] == {
        "apiGroup": group, "kind": "ClusterRole", "name": "fylgja-core"}
    assert _one("RoleBinding", "fylgja-core-lease")["roleRef"] == {
        "apiGroup": group, "kind": "Role", "name": "fylgja-core-lease"}
    assert _one("ServiceAccount", "fylgja-core")["metadata"]["namespace"] == NAMESPACE
    # The one Lease the Role names is the one the core takes.
    assert {names for _, _, names in LEASE_RULES if names} == {(CORE_ENV["FYLGJA_LEASE"],)}


def test_the_store_is_the_gateway_over_a_local_path_volume_its_bucket_made_before_it_starts() -> None:
    spec = _one("StatefulSet", "versity")["spec"]
    assert spec["replicas"] == 1
    pod = spec["template"]["spec"]
    bucket = CORE_ENV["FYLGJA_STORE"].removeprefix("s3://")
    [init] = pod["initContainers"]
    assert (init["image"], init["command"]) == (GATEWAY_IMAGE, ["mkdir", "-p", f"/data/{bucket}"])
    gateway = _container("StatefulSet", "versity", "versity")
    assert (gateway["image"], gateway["args"]) == (GATEWAY_IMAGE, ["posix", "/data"])
    assert gateway["readinessProbe"] == {"tcpSocket": {"port": 7070}}
    for container in (init, gateway):
        assert container["volumeMounts"] == [{"name": "data", "mountPath": "/data"}]
    [claim] = spec["volumeClaimTemplates"]
    assert claim["metadata"]["name"] == "data"
    assert claim["spec"] == {"storageClassName": "local-path", "accessModes": ["ReadWriteOnce"],
                             "resources": {"requests": {"storage": "1Gi"}}}
    service = _one("Service", "versity")["spec"]
    assert (service["type"], service["selector"]) == ("ClusterIP", GATEWAY_POD)
    assert [(p["port"], p["targetPort"]) for p in service["ports"]] == [(7070, 7070)]
    assert CORE_ENV["FYLGJA_S3_ENDPOINT"] == f"http://versity:{service['ports'][0]['port']}"


def test_the_gateway_and_the_core_run_as_no_root_with_nothing_to_escalate() -> None:
    core = _container("Deployment", "fylgja-core", "core")
    pod = _pod("StatefulSet", "versity")
    contexts = [c["securityContext"] for c in pod["initContainers"] + pod["containers"]]
    stated = {
        "runAsNonRoot": True,
        "readOnlyRootFilesystem": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert core["securityContext"] == stated
    assert contexts == [stated | {"runAsUser": 10001, "runAsGroup": 10001}] * 2
    assert core["resources"] == {"requests": {"cpu": "250m", "memory": "256Mi"}}
    gateway = _container("StatefulSet", "versity", "versity")
    assert gateway["resources"] == {"requests": {"cpu": "50m", "memory": "64Mi"}}


def test_every_variable_set_is_a_setting() -> None:
    settings = _settings()
    assert {variable["name"] for variable in _container("Deployment", "fylgja-core", "core")["env"]} <= settings
    for path in _files():
        named = set(_VARIABLE.findall(path.read_text()))
        assert {n for n in named if not n.startswith("FYLGJA_CREDENTIAL_")} <= settings, path.name


def test_the_gateways_keys_are_the_s3_secrets_two() -> None:
    gateway = _container("StatefulSet", "versity", "versity")
    assert gateway["env"] == [
        {"name": name, "valueFrom": {"secretKeyRef": {"name": "fylgja-s3", "key": key}}}
        for name, key in GATEWAY_KEYS.items()
    ]
    assert set(GATEWAY_KEYS.values()) <= _settings()


def test_the_overlay_example_makes_what_the_base_names() -> None:
    overlay = _overlay()
    assert overlay["resources"] == ["../../deploy"]
    assert overlay["namespace"] == NAMESPACE
    assert [image["name"] for image in overlay["images"]] == ["fylgja-core"]
    secrets, configmaps = _named_by_the_base()
    assert {g["name"] for g in overlay["secretGenerator"]} == secrets
    assert {g["name"] for g in overlay["configMapGenerator"]} == configmaps == {"fylgja-site"}
    [site] = overlay["configMapGenerator"]
    assert {literal.partition("=")[0] for literal in site["literals"]} == {
        "FYLGJA_CLABERNETES_NAMESPACE", "FYLGJA_POD_CIDR"}
    for generator in overlay["secretGenerator"]:
        sources = [s.rpartition("=")[2] for s in generator.get("files", []) + generator.get("envs", [])]
        assert sources and all(s.startswith("secret/") for s in sources), generator["name"]
    # The certificate's Secret is a TLS one, and the pull secret one the kubelet reads as a registry's credential.
    assert {g["name"]: g.get("type") for g in overlay["secretGenerator"]} == {
        "fylgja-tokens": None, "fylgja-credentials": None, "fylgja-s3": None, "fylgja-tls": "kubernetes.io/tls",
        "fylgja-registry": "kubernetes.io/dockerconfigjson"}
    # The resync is an optional literal on the core's container, the site's to set (D-070).
    assert "FYLGJA_RESYNC_S" in (DEPLOY / "README.md").read_text()
