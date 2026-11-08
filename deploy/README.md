# The core's kustomize base

`deploy/` is the core's kustomize base ([D-062](../design/decisions.md#d-062)): the core as one
pod on a cluster under its Lease, with its role, its Service and its store. It names what is the
same at every site: the namespace `fylgja`, the objects' names, the paths inside the pods, the
Lease, the bucket and the store's endpoint inside the namespace. A site's overlay, under
`local/deploy/` and never committed, adds the rest. `kubectl kustomize deploy/` builds the base,
and `kubectl apply -k local/deploy` applies a site's.

| File | Holds |
|---|---|
| `namespace.yaml` | The namespace `fylgja`: the core, its Service and its store, and nothing else |
| `rbac.yaml` | The service account `fylgja-core`; the ClusterRole `fylgja-core` and its binding; the Role `fylgja-core-lease` and its binding |
| `core.yaml` | The Deployment `fylgja-core`, one replica under `Recreate` with one readiness probe, and its Service, a LoadBalancer on 443 |
| `versity.yaml` | The store, Versity S3 Gateway v1.10.0: the StatefulSet `versity` over a `local-path` volume of 1 GiB, an init container that makes the bucket, its Service on 7070, and the NetworkPolicy that admits the core's pods alone ([D-061](../design/decisions.md#d-061)) |

**What it is not.** It holds no Secret, no ConfigMap, no address and no value, and names the
core's image with no registry and no tag, so applied alone its pods cannot start: they name
Secrets and a ConfigMap it does not make. It is no Helm chart, and no image is published for
it.

**The role.** The core's service account acts on Secrets and pods in every namespace
([SECURITY.md](../SECURITY.md)). The ClusterRole holds what the clabernetes driver does to a
twin, each verb one its calls were read to need from inside a pod under this account
([verified-facts.md](../design/verified-facts.md)): its namespace made, read, changed and
deleted; its Secrets, NetworkPolicy and Topology made and changed by server-side apply, which asks
`create` beside `patch`, and deleted with the namespace; its Topology read; its Services listed
and patched; its pods listed, watched and deleted; and `get` and `create` on `pods/exec`, both of
which an exec's WebSocket handshake asks. `watch` on pods is cluster-wide because the driver's
`events` is one watch on pods across every namespace, by the owner's label; the driver deletes a
twin's pod whose container ended or restarted in it ([D-070](../design/decisions.md#d-070)), and
the pod of a node given a port after boot, which arrives only with a new pod
([D-057](../design/decisions.md#d-057)). The Lease's rule is a Role in `fylgja` alone: `get` and
`update` on the Lease `fylgja-core`, and `create`, which a name cannot confine
([D-071](../design/decisions.md#d-071)). `core/tests/test_deploy.py` holds the rules as tables.

## A site's overlay

`local/deploy/kustomization.yaml`, whole, each `<placeholder>` the site's:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: fylgja
resources:
  - ../../deploy
labels:
  - pairs:
      app.kubernetes.io/part-of: fylgja
images:
  - name: fylgja-core
    newName: <registry>/<path>/fylgja-core
    newTag: <commit>
configMapGenerator:
  - name: fylgja-site
    literals:
      - FYLGJA_CLABERNETES_NAMESPACE=<clabernetes' namespace>
      - FYLGJA_POD_CIDR=<the cluster's pod network, in CIDR form>
secretGenerator:
  - name: fylgja-tokens
    files:
      - tokens=secret/tokens
  - name: fylgja-credentials
    envs:
      - secret/credentials.env
  - name: fylgja-s3
    envs:
      - secret/s3.env
  - name: fylgja-tls
    type: kubernetes.io/tls
    files:
      - tls.crt=secret/tls.crt
      - tls.key=secret/tls.key
  - name: fylgja-registry
    type: kubernetes.io/dockerconfigjson
    files:
      - .dockerconfigjson=secret/dockerconfig.json
patches:
  # Optional: the Service's address, one of the load balancer's pool, which the certificate names.
  # The key is MetalLB's (0.16.0), whose older metallb.universe.tf/loadBalancerIPs it flags as deprecated.
  - patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: fylgja-core
        namespace: fylgja
        annotations:
          metallb.io/loadBalancerIPs: <the Service's address>
  # Optional: the loop's resync in seconds, 300 unset; a run that must tell a restore an event
  # started from one the resync started sets it long, 3600.
  # - patch: |-
  #     apiVersion: apps/v1
  #     kind: Deployment
  #     metadata:
  #       name: fylgja-core
  #       namespace: fylgja
  #     spec:
  #       template:
  #         spec:
  #           containers:
  #             - name: core
  #               env:
  #                 - name: FYLGJA_RESYNC_S
  #                   value: "<seconds>"
```

`<registry>/<path>` is where the core's image was pushed, and `<commit>` its tag: the first 12
characters of the commit `make image` built it at, from a clean head, since a `-dirty` tag is
never pushed ([CONTRIBUTING.md](../CONTRIBUTING.md#running-the-core-on-a-cluster)).

## The files under `local/deploy/secret/`

Each is made under `umask 077`, so each is mode `0600`, and none is ever printed or committed.
Kustomize names each Secret by a hash of what it holds, so a changed file makes a new Secret,
which the pods are rolled onto, and `kubectl apply -k` deletes nothing it no longer applies: the
old Secret stays, holding the old credential, until it is deleted by hand (`kubectl -n fylgja get
secrets` lists both).

| File | Secret | Holds |
|---|---|---|
| `tokens` | `fylgja-tokens` | The token file `FYLGJA_TOKENS` names, made as [CONTRIBUTING.md](../CONTRIBUTING.md#running-the-core) says: a token's hash and its principal a line, never a token |
| `credentials.env` | `fylgja-credentials` | An env file of the credential provider's variables: each package's node login, and the pull credential's `_REGISTRY`, `_USERNAME` and `_PASSWORD` |
| `s3.env` | `fylgja-s3` | An env file of `FYLGJA_S3_ACCESS_KEY` and `FYLGJA_S3_SECRET_KEY`: the core's keys to its store, and the gateway's root keys |
| `tls.crt`, `tls.key` | `fylgja-tls` | The pair the server ends TLS with ([D-063](../design/decisions.md#d-063)), signed by the site's CA as the registry's certificate is, the certificate naming the Service's address as an IP SAN; the key unencrypted. The CA's certificate, which a client's `FYLGJA_API_CA` names, must carry a key usage allowing certificate signing: Python's client verifies strictly, and refuses a CA without one ([CONTRIBUTING.md](../CONTRIBUTING.md#running-the-core-on-a-cluster)) |
| `dockerconfig.json` | `fylgja-registry` | The kubelet's login to the private registry, for the core's image: `{"auths": {"<registry>": {"auth": "<base64 of user:password>"}}}` |

The two env files, by name, with the packages this tree ships:

```sh
# credentials.env
FYLGJA_CREDENTIAL_SRLINUX_USERNAME=<login>
FYLGJA_CREDENTIAL_SRLINUX_PASSWORD=<password>
FYLGJA_CREDENTIAL_EOS_USERNAME=<login>
FYLGJA_CREDENTIAL_EOS_PASSWORD=<password>
FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY=<registry>/<path>
FYLGJA_CREDENTIAL_ARISTA_CEOS_USERNAME=<user>
FYLGJA_CREDENTIAL_ARISTA_CEOS_PASSWORD=<password>

# s3.env, two keys made for the store and never echoed:
#   umask 077
#   printf 'FYLGJA_S3_ACCESS_KEY=%s\nFYLGJA_S3_SECRET_KEY=%s\n' "$(openssl rand -hex 10)" "$(openssl rand -hex 20)" > s3.env
FYLGJA_S3_ACCESS_KEY=<an access key>
FYLGJA_S3_SECRET_KEY=<a secret key>
```

**Two pull secrets, not one.** The pull credential in `credentials.env` is the driver's: it makes
it a Secret in each twin's namespace, for clabernetes to pull a gated image
([D-057](../design/decisions.md#d-057)). `dockerconfig.json` is the kubelet's, in `fylgja`, for
the core's own image. They may name the same registry and the same login, and are still two
files and two Secrets.

## Applying it

With the image pushed:

```sh
kubectl apply -k local/deploy
kubectl -n fylgja rollout status statefulset/versity
kubectl -n fylgja rollout status deployment/fylgja-core
```

A pod waiting for the Lease is Running and not Ready, and binds no socket. At the first apply the
core's pod may start before its store: it exits 1 at the store's proof, and the kubelet starts it
again after its backoff (10 s, then doubling). A client reaches the core at `https://<the
Service's address>`, with `FYLGJA_API_CA` naming the site's CA
([CONTRIBUTING.md](../CONTRIBUTING.md#running-the-core-on-a-cluster)).

**A stop past the kubelet's grace.** A pod deleted or rolled is sent SIGTERM: the core gives its
open connections 5 s, stops its loop, which is unbounded, and then releases the Lease. The kubelet
waits its termination grace, 30 s by default, which the base leaves as it is, and then sends
SIGKILL: a stop that takes longer ends with the Lease unreleased and nothing logged, and the next
holder takes it once its duration, 15 s, has passed.

**Never two cores on the cluster at once.** Once the core is deployed, `make cluster`, which runs
a driver in process on the development host under the same owner label, runs only with the core's
Deployment scaled to no replica (`kubectl scale deployment fylgja-core --replicas=0 -n fylgja`),
and it is scaled back to one after (`--replicas=1`). The labels name no core, the driver's watch
is cluster-wide, and since [D-070](../design/decisions.md#d-070) a core deletes a pod of any
twin's whose container ended or restarted in it, so two would each act on the other's twins.
