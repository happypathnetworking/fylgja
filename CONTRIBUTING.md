# Contributing

> **Not accepting contributions yet.** Thank you for your interest in Fylgja. The project is
> at an early stage: the core is being built phase by phase from
> [design/core.md](design/core.md), and its formats and API are still settling, so outside
> issues and pull requests are not being taken for now. This page describes how the project
> itself works, and will say when that changes. A security concern is always welcome, as
> [SECURITY.md](SECURITY.md) describes.

How to set up, build, test and change fylgja-core. The project's governance and design live
in [`design/`](design/): the system in [architecture.md](design/architecture.md), the rules
every change keeps in the [constitution](design/constitution.md), and the reasons in the
[decision log](design/decisions.md). User-facing documentation lives in [`docs/`](docs/).

## How a change is made

A change is a **design document, then a decision entry where it changes a decision, then a
pull request** ([D-033](design/decisions.md#d-033)).

1. **Design.** A feature larger than a fix gets a design document under `design/`.
   It covers:
   - intent;
   - requirements;
   - the shape;
   - what it retires;
   - how it is verified.

   [design/core.md](design/core.md) is the current one, and its "Sequence" is the build
   order.
2. **Decide.** A changed decision is a new entry in [decisions.md](design/decisions.md) that
   supersedes the old one. The log is append-only. Check the rejected alternatives before
   proposing one.
   - **The constitution changes only by citing such an entry,** with a semver bump.
   - **Then search** [architecture.md](design/architecture.md) for the old position.
3. **Formats change with the code.** Each format has one current version, specified by its
   file in [`formats/`](formats/README.md) ([D-002](design/decisions.md#d-002)). A change to a
   format is made there, in the same change as the code that reads or writes it.
4. **Verify against the running system** before code depends on how containerlab,
   clabernetes or a network operating system behaves. Record the result, with its version
   and date, in [verified-facts.md](design/verified-facts.md).
5. **Pull request.**
   - Conventional-commit messages whose body says *why*.
   - A new term goes in [glossary.md](docs/glossary.md) in the same change.

## How a phase is built

A phase is one item of the "Sequence" in [design/core.md](design/core.md). It goes through
the flow above in four stages. The procedure an agent follows, with the rules every
implementer and reviewer is handed and the template for a phase's branch plan, is
[`.claude/skills/build-phase/`](.claude/skills/build-phase/SKILL.md); this section is its
statement for people, and is the one that is right where the two disagree.

1. **Settle.** On the branch `phase-N-design`, cut from `main`:
   - the behaviour the phase rests on is read on the running systems and recorded in
     [verified-facts.md](design/verified-facts.md), in a commit of its own;
   - the phase's section goes into [design/core.md](design/core.md), with its decision
     entries: what the phase is for, what is settled before code, the formats touched, its
     non-goals and anti-goals, its plans, when it is done, and what is left to the builder;
   - a fresh reader checks the draft against the code before the maintainer approves it.
2. **Plan.** One working document for each of the design's plans, and a "plan 0" that holds
   the branches, the order and the names the plans share. They live under `local/plans/`,
   git-ignored: a plan is how a branch gets built, and the design and the decision log are
   the record.
3. **Execute.** The integration branch `phase-N-integration` is cut from `main` with the
   design merged in. Each plan is a branch `phase-N/<n>-<name>` in a worktree beside the
   repository (`../fylgja-core-wt/<n>-<name>`).
   - Each task is built from its own brief, test first, and its diff is read by a fresh
     reviewer before the next task starts.
   - Each decision taken along the way is written down as a ruling, with what it costs if
     wrong.
   - A plan's whole branch is reviewed once more, then merged into the integration branch.
   - Live runs are one at a time.
4. **Land.** On the maintainer's word:
   - the integration branch is squashed onto `main` as one commit;
   - its history is kept under the local tag `archive/phase-N-integration`;
   - the build's records (ledgers, briefs, reviews, rulings) go to `local/sdd/phase-N/`;
   - the item in "Sequence" is marked done, with what it left to later phases.

## Tooling

| Tool | Version | Notes |
|---|---|---|
| Python | 3.14 | [D-001](design/decisions.md#d-001) |
| jsonschema, PyYAML | 4.26.0, 6.0.3 | Runtime dependencies: the formats' validation and the packages' YAML |
| httpx | 0.28.1 | A runtime dependency: the readiness wait and the push ([D-039](design/decisions.md#d-039)) |
| Starlette, uvicorn | 1.9.0, 0.54.0 | Runtime dependencies: the server's ASGI application and the process that serves it ([D-025](design/decisions.md#d-025)) |
| pygnmi, grpcio, protobuf | 0.8.15, 1.84.0, 7.36.2 | Runtime dependencies: verify's gNMI reader ([D-052](design/decisions.md#d-052)) |
| lightkube, lightkube-models, httpx2, msgspec | 1.0.1, 1.37.0.8, 2.16.0, 0.22.0 | Runtime dependencies: the clabernetes driver's Kubernetes calls ([D-064](design/decisions.md#d-064)) |
| pytest, ruff, mypy | 9.2.0, 0.17.3, 2.4.0 | mypy in strict mode (Constitution I) |
| rfc8785 | 0.1.4 | Tests only: an independent RFC 8785 implementation that the blueprint id is checked against |
| openssl | the host's (3.5.5) | Tests only: the pure tier's TLS tests make a self-signed certificate and key with it (`core/tests/tls.py`); without it they are skipped, and fail when `CI` is set |
| containerlab, Docker | 0.81.0, 29.8.1 | The local driver and the live tier. containerlab is pinned to the version clabernetes 0.10.1 embeds, so the kinds behave alike on both drivers |
| Versity S3 Gateway | v1.10.0 | The object store's live test, and development's endpoint ([D-061](design/decisions.md#d-061)) |
| clabernetes, k3s | 0.10.1, v1.37.1+k3s1 | The clabernetes driver's development ([D-060](design/decisions.md#d-060)) |
| crane | 0.22.1 | Pushes the core's image to the cluster's private registry from a tarball Docker saved ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| kubectl | 1.37.2, its kustomize v5.8.1 | Builds the core's kustomize base under `deploy/` and applies a site's overlay ([Running the core on a cluster](#running-the-core-on-a-cluster)) |

Each dependency is pinned to a release at least two weeks old when it was chosen.
`make venv` builds `core/.venv` at the pins, with the package installed editable. A venv
inside the tree carries a `.gitignore` of `*`.

## Make targets

| Target | What it does |
|---|---|
| `make venv` | The core's venv |
| `make lint` | ruff over `core/` and `scripts/`, then mypy in strict mode |
| `make test` | The pure tier: no infrastructure. Gates every pull request |
| `make live` | The live tier on the local driver: the driver's own modules under `core/tests/live/`, then the conformance suite on the local harness. The driver's own: readiness and the push on one SR Linux and one cEOS node booted under containerlab (`core/tests/live/test_push.py`); labs through the local driver, `admit`, `apply`, `inspect` and `destroy`, the residue rule and two labs at once (`core/tests/live/test_containerlab_driver_live.py`); three labs applied at once, their deploys one after the other, with the host's load and connections read (`core/tests/live/test_many_labs_live.py`, about 2.5 minutes alone); `changes` held to containerlab's own dry run for every step fixture, with the hot-add recreate of two cEOS nodes and `exec` in a probe host (`core/tests/live/test_changes_live.py`, about 4.5 minutes alone); verify over gNMI on a probed twin, with a node stopped and started by containerlab and by Docker, and a configured cEOS node's host name (`core/tests/live/test_verify_live.py`, about 5 minutes alone); the trigger and the restore through Docker's own restart paths, the loop run in-process with its resync an hour away: a node restarted by `docker restart` and one started again by Docker's restart policy, each pushed again by a restore the driver's events started within seconds (its links are not restored), and one removed, reported missing once its boot window passed (`core/tests/live/test_restore_live.py`, about 4 minutes alone); and the object store against Versity S3 Gateway under Docker, the store contract whole and every compare-and-set raced by 32 stores (`core/tests/live/test_object_store_live.py`, about 1 minute alone). Then the suite, as `make conformance DRIVER=containerlab` runs it (below), its many-twins scenario among it, about 36 minutes of the whole. 165 tests by collection; the tier was last timed whole at about 54 minutes, with the cluster quiet, and the suite has since grown from about 31 minutes to 36, so about 59 minutes, a derivation and not a reading. Load `local/.env` first |
| `make cluster` | The cluster tier: the clabernetes driver's calls on the k3s cluster, from the development host. The driver's reach into Kubernetes, every call of `LightKube` read on a two-node SR Linux twin (`core/tests/cluster/test_kube_cluster.py`, 1 to 2 minutes alone); the driver as the server makes it on a three-node twin: `admit` against a namespace that is not the twin's, `apply` with the root logger at DEBUG and its repeat, `exec`, a node's container ended in its pod, a pod deleted, `reconfigure`, `destroy` and the residue (`core/tests/cluster/test_clabernetes_driver_cluster.py`, about 4 minutes alone); and `changes` held to the pods' uids for every step fixture, with the hot-add recreate of two cEOS nodes killed before its deletions and resumed (`core/tests/cluster/test_clabernetes_changes_cluster.py`, about 10 minutes alone); and the trigger and the restore through the loop, run in-process with the resync an hour away, on a two-node twin stepped twice: a pod deleted, a container ended in its pod and that pod replaced by the driver, a probe host's and a cEOS node's pods deleted, each restored without the resync, the settled twin's pods watched for three minutes, and a watch asked at a compacted version (`core/tests/cluster/test_restore_cluster.py`, about 14 minutes alone); and the Lease, on a Lease of its own in the kubeconfig's default namespace held by two holders in one process: taken, waited for, taken over 15 s after its holder went silent and released (`core/tests/cluster/test_lease_cluster.py`, about 30 s alone). About 30 minutes. Load `local/.env` first, with `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE`, `FYLGJA_POD_CIDR` and the cEOS pull credential set. With the core deployed on the cluster, its Deployment is scaled to no replica first and back to one after ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make conformance DRIVER=containerlab\|clabernetes` | The driver conformance suite alone (`core/tests/conformance/`): one set of scenarios, written once, on the harness of the driver `DRIVER` names, `containerlab` by default; any other name is refused in one line. A twin created and shown; stepped through every step fixture with verify after each and the burst held, and the step's refusals; the core killed at each phase boundary of a create and of a step, during an apply and during a destroy, a waiting CLI riding through, a deletion after a kill, and a step cancelled; a node replaced behind the core and one stopped; leftovers read by label; node access through each node's own transport; and isolation over TCP between two twins and from a third namespace, where the driver declares it. Then many twins at once (`core/tests/conformance/test_many.py`): the harness's count, three here and five on the cluster, created together and all Ready, each stepped while the others run with no node unread, a twin of forty nodes refused in a dry run and at its create with the capacity read agreeing, and every twin destroyed, about 5 minutes here and 8 on the cluster. The scenario needs a band of room: about 4.5 CPU and 17 GiB free here for its three twins and 7.5 CPU and 28 GiB on the cluster for its five, and, with them up, under about 80 GiB free on either, since the forty-node twin must be refused; on a roomier runtime its dry run is answered and the scenario fails there, having made no twin of it. `containerlab` runs `fylgja-core-server` on this host under the live tier's marker: 54 tests, about 36 minutes. `clabernetes` drives the core deployed on the cluster over TLS, killing it by its pod, under the cluster tier's marker: 54 tests, about 71 minutes. Load `local/.env` first, and for the cluster the suite's own variables ([Running the core on a cluster](#running-the-core-on-a-cluster)) |
| `make linkcheck` | Every relative link and anchor in the tracked Markdown resolves |
| `make wheelcheck` | Builds the wheel from `core/` and `formats/`, installs it into an empty venv outside the tree and validates a fixture there ([D-066](design/decisions.md#d-066)). Needs the network, so it is no part of `make test`; CI runs it on every push and pull request |
| `make image` | Builds the core's image from the `Dockerfile` at the root ([D-062](design/decisions.md#d-062)) as `fylgja-core:<tag>`, the tag the commit's first 12 characters, with `-dirty` where `git status --porcelain` prints anything. Its build context is `.dockerignore`'s allow-list, so nothing under `local/` reaches a layer. Needs Docker and the network |
| `make imagecheck` | Builds the image, then runs it: its user is 10001; given only `FYLGJA_STORE` and a `FYLGJA_TOKENS` that names no file, it exits 2 naming `FYLGJA_TOKENS`, its packages loaded against the wheel's formats; and the formats it carries are `formats/`'s, by name and by bytes; and its copies of `psp/` and `probes/` hold the files git tracks there and no other, by path, so a file git ignores there (an editor's `*.swp`, a nested `local/`), which reaches the image with no `-dirty` tag, fails it. Prints the tag it checked last. CI runs it on every push and pull request, and pushes nothing |

## Test tiers

| Tier | Needs | Runs |
|---|---|---|
| **Pure** | Nothing | `make test`, in CI on every push and pull request: the model, the compiler, every driver's `plan`, the packages and the fixtures, and the store, the object store over a fake S3 endpoint, the reconcile loop, API 1 and the CLI over fakes of the runtime |
| **Live** | Booted images on the local containerlab driver, and Versity S3 Gateway under Docker | On demand: `make live`, with `local/.env` loaded: the driver's own modules under `core/tests/live/` (the driver, `changes` against containerlab's dry run, readiness and the push, verify over gNMI, the trigger and the restore through Docker's restart paths, and the object store against the gateway), then the conformance suite on the local harness. 165 tests by collection; about 59 minutes, derived from the 54 minutes last read with the cluster quiet and the suite's growth from about 31 minutes to 36, not re-measured. Never while the cluster runs the suite or the cluster tier: here the two share a hypervisor, and SR Linux segfaults under the contention. `make test` deselects it (the `live` marker) |
| **Cluster** | The k3s cluster, reached from the development host | On demand: `make cluster`, with `local/.env` loaded and `KUBECONFIG`, `FYLGJA_CLABERNETES_NAMESPACE` and `FYLGJA_POD_CIDR` set: the clabernetes driver's calls on the cluster, its reach into Kubernetes first (`core/tests/cluster/test_kube_cluster.py`), then the driver's calls and `changes` held to the pods' uids (`core/tests/cluster/test_clabernetes_driver_cluster.py`, `core/tests/cluster/test_clabernetes_changes_cluster.py`), the trigger and the restore through the loop (`core/tests/cluster/test_restore_cluster.py`), and the Lease (`core/tests/cluster/test_lease_cluster.py`). Each test twin has its own namespace, deleted at its module's end; never while `make live` runs. `make test` deselects it (the `cluster` marker) |
| **Driver conformance** | Each driver's own runtime: for the local driver, containerlab and Docker on the development host; for clabernetes, the core deployed on the cluster with `FYLGJA_RESYNC_S` of 3600 or more, a token of the suite's own principal, both node logins and the cEOS pull credential, reached from the development host ([Running the core on a cluster](#running-the-core-on-a-cluster)) | On demand, per driver: `make conformance DRIVER=containerlab`, 54 tests in about 36 minutes, which `make live` runs too; and `make conformance DRIVER=clabernetes`, 54 tests in about 71 minutes. Each was measured with the other runtime quiet, and the two are never run together here: they share a hypervisor. Each runtime needs the many-twins scenario's band of room: about 4.5 CPU and 17 GiB free locally and 7.5 CPU and 28 GiB on the cluster, and under about 80 GiB free on either with its twins up, so that its forty-node twin is refused. `make test` deselects the suite (its harness's marker, `live` or `cluster`) |

Development and the live tier never need Kubernetes (Constitution XIII).

## Test data

| Path | Holds |
|---|---|
| `testdata/blueprint/` | Five blueprints: `three-node`, `mixed`, `lossy`, `three-node-probed`, `three-node-unmanaged` (it has no Go facts) |
| `testdata/compiler/` | The facts the frozen Go compiler produced for each, which the new compiler is held to; and under `rejected/`, valid blueprints the compiler must refuse, one fault each |
| `testdata/packages/` | `chassisos`, a synthetic lossy platform; the interface mapping rows each package must produce; and under `invalid/`, the rejection fixtures for the platform and probe package loaders |
| `testdata/probes/` | Probe declaration files, valid and, under `invalid/`, the rejection fixtures for the declaration loader |
| `testdata/deployment/` | The golden deployments: for each driver (`containerlab/`, `clabernetes/`) and fixture, the rendered runtime files and the deployment document the plan must reproduce, which change in a commit of their own; and under `rejected/`, valid blueprints a driver's plan must refuse, one fault each |
| `testdata/s3/` | The SigV4 signer's known answers, written once by `generate.py` from botocore's signer in a venv outside the tree; botocore is never a dependency (D-061) |

## Local environment

**Credentials** live in `local/.env` alone (git-ignored, mode `0600`), with the names in
[`.env.example`](.env.example).
- Load it with `set -a; . local/.env; set +a`. Fylgja reads the process environment, never a
  file.
- Never print, log or persist a token or a password.

**The live tier** needs:
- Docker and containerlab, with the user in the `docker` and `clab_admins` groups;
- the SR Linux image (`ghcr.io/nokia/srlinux:24.7.1`, public);
- the cEOS image (`ceos:4.32.0.2F`), imported from Arista's account-gated download and never
  pulled;
- the Versity S3 Gateway image (`ghcr.io/versity/versitygw:v1.10.0`, public), pulled on first
  use.

On Ubuntu, SR Linux's `rsyslogd` needs an AppArmor widening ([verified-facts.md](design/verified-facts.md)).

## Running the core

`fylgja-core-server` is one process: API 1 on uvicorn and the reconcile loop, over one store
held for one core, a directory by its lock and an object store by a Lease
([D-023](design/decisions.md#d-023), [D-039](design/decisions.md#d-039), [D-062](design/decisions.md#d-062)).
Everything it runs with is a `FYLGJA_*` variable ([D-042](design/decisions.md#d-042)), listed
in [`.env.example`](.env.example):

| Variable | Default | Holds |
|---|---|---|
| `FYLGJA_STORE` | required | The store's directory, created on first start (the driver's working files live under it), or `s3://<bucket>[/<prefix>]`, an object store ([D-061](design/decisions.md#d-061)), which needs `FYLGJA_LEASE` and a driver that keeps no files in the store's directory (`clabernetes`) |
| `FYLGJA_S3_ENDPOINT` | required for `s3://` | The object store's endpoint, an `http://` or `https://` URL of a host and an optional port |
| `FYLGJA_S3_ACCESS_KEY` | required for `s3://` | The endpoint's access key |
| `FYLGJA_S3_SECRET_KEY` | required for `s3://` | The endpoint's secret key |
| `FYLGJA_S3_REGION` | `us-east-1` | The region its requests are signed for |
| `FYLGJA_S3_CA` | the system's | A CA bundle for an `https://` endpoint a private CA signed |
| `FYLGJA_LEASE` | none; required by `s3://` | The Lease that holds the store for one core ([D-062](design/decisions.md#d-062)), in the core's namespace (the service account's in a pod, the kubeconfig context's off the cluster), taken before the store is opened: a core that finds it held waits, saying once whom for, and one that loses it stops at once (`lease.lost`): its loop's stop begun, given 2 s, every connection dropped, one still in its TLS handshake among them, and each request in flight cancelled, none answered and none given grace, nothing released, exit status 1 |
| `FYLGJA_PACKAGES` | required | Colon-separated directories of platform and probe packages, loaded once at start: `psp:probes` |
| `FYLGJA_TOKENS` | required | The token file (below) |
| `FYLGJA_LISTEN` | `127.0.0.1:7650` | The address it serves on, `host:port` |
| `FYLGJA_TLS_CERT` | none | The certificate the server ends TLS with, set with `FYLGJA_TLS_KEY` ([D-063](design/decisions.md#d-063)); without the two it serves HTTP, which is for loopback, and a listen address off loopback is one warning at start |
| `FYLGJA_TLS_KEY` | none | The certificate's key, unencrypted, set with `FYLGJA_TLS_CERT`: an encrypted key is refused at start, never prompted for |
| `FYLGJA_DRIVER` | `containerlab` | The driver twins run on: `containerlab`, the local driver, or `clabernetes`, which reaches the cluster from its service account in a pod and from the kubeconfig `KUBECONFIG` names off the cluster |
| `FYLGJA_CLABERNETES_NAMESPACE` | none; required by `clabernetes` | clabernetes' namespace, a DNS-1123 label (`c9s`), which each twin's policy admits |
| `FYLGJA_POD_CIDR` | none; required by `clabernetes` | The cluster's pod network, an IPv4 network in CIDR form (`10.244.0.0/16`); each twin's policy admits any source outside it |
| `FYLGJA_WORKERS` | `8` | How many twins the loop works on at once: five twins created together each hold a worker through an apply, with room beside ([D-075](design/decisions.md#d-075)) |
| `FYLGJA_STEP_WAIT_S` | `180` | Seconds a step waits for verify to hold before it ends anyway (an integer of 1 or more) |
| `FYLGJA_RESYNC_S` | `300` | Seconds between the loop's resyncs, each of which queues every twin again, so a runtime event missed is only late (an integer of 1 or more) |
| `FYLGJA_CREDENTIAL_<NAME>_USERNAME`, `_PASSWORD` | none | Each package's node login, `<NAME>` its `credentials` value upper-cased; a run needing one not set fails with `credential.missing` |
| `FYLGJA_CREDENTIAL_<NAME>_REGISTRY`, `_USERNAME`, `_PASSWORD` | none | A package's pull secret on the clabernetes driver: the image prefix a gated image is pulled under, and the registry's login; a twin's allocation holds the prefixes set when it was admitted |

**The token file** holds one `<sha256 hex of the token> <principal>` per line, `#` comments
and blank lines skipped. It never holds a token itself, and several tokens may be valid at
once, one per client. Make a client's token and add its line:

```sh
token=$(head -c 24 /dev/urandom | base64)
printf '%s %s\n' "$(printf %s "$token" | sha256sum | cut -d' ' -f1)" alice >> local/tokens
printf 'FYLGJA_API_TOKEN=%s\n' "$token" >> local/.env   # the client's token, never echoed
unset token
```

`printf %s "$FYLGJA_API_TOKEN" | sha256sum` gives the hash of a token already set.

The commands the local driver runs, `containerlab` and `docker`, get `DOCKER_HOST` and `PATH`
from the server's environment and nothing else ([D-065](design/decisions.md#d-065)); a
variable containerlab should see is added to `ALLOWED_ENV` by a change, with its reason.

**Start it** with the environment loaded:

```sh
set -a; . local/.env; set +a
core/.venv/bin/fylgja-core-server
```

It logs one JSON object per line on stderr, the principal on every write, never a token or a
password. A start refused is one line naming the variable or the file at fault. SIGTERM or
Ctrl-C ends open watches, stops the loop and then releases the Lease. A second Ctrl-C, landing
before uvicorn has begun the loop's stop, gives the loop 2 s to stop; landing after, it leaves
uvicorn's own stop running, unbounded; either way the Lease is released only once the loop has
stopped. SIGTERM anywhere in the start, while it waits for the Lease or opens the store among
it, ends the start as Ctrl-C does, and while the console script imports the server, before
anything is opened, it exits 143: the server handles SIGTERM itself, since in a container it is
PID 1, which ignores a signal it has no handler for. Three windows are left, each leaving the
Lease to its duration (the server's module docstring): the interpreter's first 0.14-0.16 s in the
image, and two in the start, each read at under a millisecond on the development host, where the
Lease's client had no connection to close; against the API the one that closes it takes longer,
by how much not read. A create cut short resumes at the next start. Waiting for a Lease another
holds is not an exit: one INFO line a holder, and no socket bound. Its exit status:

| Status | Means |
|---|---|
| 0 | stopped cleanly, the Lease released first when one is held |
| 130 | stopped by Ctrl-C (SIGINT), the Lease released first when one is held; or Ctrl-C anywhere in the start, while it waits for the Lease, while the store is opened or before uvicorn runs, what was opened closed again and the Lease released first, but in the two windows in the start above, where the status is the same and the Lease is left to its duration |
| 143 | stopped by SIGTERM, as by Ctrl-C, in a container as PID 1 too: after uvicorn's graceful shutdown, which releases the Lease; or anywhere in the start, as Ctrl-C, what was opened closed again and the Lease released first, the two windows in the start above as for 130; or while `fylgja-core-server` imports the server, nothing yet opened |
| 1 | the store is held by another core, an object store cannot be opened (its endpoint unreachable, or refusing), the Lease is lost (`lease.lost`), or the application failed to start |
| 2 | a misconfiguration: a `FYLGJA_*` variable not set, empty or malformed, or set to what another rules out (an `s3://` store without `FYLGJA_LEASE` or with the `containerlab` driver, one of the TLS pair without the other); a certificate or key that does not load (`FYLGJA_TLS_CERT`); a key that is encrypted (`FYLGJA_TLS_KEY`); `FYLGJA_LEASE` set with no cluster to reach, or a Lease the service account may not read or write; a CA bundle that does not load (`FYLGJA_S3_CA`); an endpoint that fails the store's proof (`FYLGJA_S3_ENDPOINT`, `store.unconditional`); Python run optimised (`-O` or `PYTHONOPTIMIZE`, `server.optimised`); a package refused, a token file it cannot read, a cluster the clabernetes driver cannot reach (`KUBECONFIG` not set, or not a kubeconfig, off the cluster), or an address it cannot listen on (`FYLGJA_LISTEN`) |

**The thin CLI** reads `FYLGJA_API_ADDRESS` (the server's `host:port` or URL) and
`FYLGJA_API_TOKEN`, and `FYLGJA_API_CA` where it is set: the CA file an `https://` address is
verified against, the system's trust when it is not ([D-063](design/decisions.md#d-063)). A
certificate not trusted is one line saying so and one naming `FYLGJA_API_CA`, and exits 2. In a
shell of its own, load the environment and point the CLI at the server's listen address:

```sh
set -a; . local/.env; set +a
export FYLGJA_API_ADDRESS=127.0.0.1:7650   # FYLGJA_LISTEN's value
core/.venv/bin/fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
core/.venv/bin/fylgja-core twin show demo
core/.venv/bin/fylgja-core twin destroy demo
```

A command that waits rides through a restart of the server: its watch reconnects for up to about
three minutes, each try given 5 s to connect, saying so once on stderr, and then exits 2. A
`twin create` already waiting rides through; a `run watch` begun while the server is away exits 2
at once, since its version read is made once, before any stream.

## Running the core on a cluster

On a cluster the core is one pod under a Lease, run from an image built in the tree
([D-062](design/decisions.md#d-062)). The image holds no containerlab, so a core in a pod
serves the `clabernetes` driver alone.

**Build** the image with `make imagecheck`, which builds it, runs it and prints its tag last.
The tag is the commit the image was built at, so a run on the cluster says which commit's code
it read. Push from a clean head: a `-dirty` tag is for the development host alone and is never
pushed. CI builds the image and pushes nothing: publishing one is a release's decision.

**Push** it to the cluster's private registry as the gated image is
([D-021](design/decisions.md#d-021)): by `crane`, from a tarball Docker saves. Nothing of the
registry is in the tree: `<registry>` is its host and port, `<path>` the repository's path in
it and `<user>` its login, each the site's. In one shell, with `DOCKER_CONFIG` a directory under
`local/` for `crane`'s login, `SSL_CERT_FILE` the registry's CA, and the password read on
standard input from a file under `local/` of mode `0600`, never put on a command line:

```sh
export DOCKER_CONFIG=$PWD/local/<config directory> SSL_CERT_FILE=$PWD/local/<the registry's CA>
crane auth login <registry> -u <user> --password-stdin < local/<password file>
docker save -o local/fylgja-core-<tag>.tar fylgja-core:<tag>
crane push local/fylgja-core-<tag>.tar <registry>/<path>/fylgja-core:<tag>
```

**Deploy** it from a site's overlay, `local/deploy/kustomization.yaml`, over the base under
[`deploy/`](deploy/README.md), which holds no address and no value. The overlay names the image
just pushed by its registry, path and tag; makes the Secrets the base's pods name from files
under `local/deploy/secret/`, each of mode `0600`, and their ConfigMap from two literals; and
may give the Service its address. [deploy/README.md](deploy/README.md) holds a whole example and
says which Secret each file becomes. With `KUBECONFIG` naming the cluster's kubeconfig:

```sh
kubectl apply -k local/deploy
kubectl -n fylgja rollout status statefulset/versity
kubectl -n fylgja rollout status deployment/fylgja-core
```

The core's pod turns Ready when it listens, which it does only after it holds the Lease and has
opened its store; one that waits for the Lease is never Ready, and is not restarted for waiting.
At the first apply it may start before its store: it exits 1 at the store's proof, and the
kubelet starts it again after its backoff (10 s, then doubling).

**Reach** it from a workstation over TLS, at the Service's address, with a token whose hash the
overlay's `secret/tokens` holds, trusting the CA that signed the server's certificate.
`local/.env`'s `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` are the development host's core's, so
the three are set in the shell's own environment, the token read from its file under `local/`
(mode `0600`), never echoed. The token's line needs bash: under dash, Ubuntu's `sh`, `$(< file)`
is empty.

```bash
export FYLGJA_API_ADDRESS=https://<the Service's address> FYLGJA_API_CA=$PWD/local/<the site's CA>
export FYLGJA_API_TOKEN="$(< local/<the token's file>)"
core/.venv/bin/fylgja-core twin create demo --blueprint testdata/blueprint/three-node.json
```

The client verifies strictly: Python's `ssl.create_default_context()` sets `VERIFY_X509_STRICT`.
The server's certificate names the address as an IP SAN, and the CA's certificate must carry a
key usage that allows signing certificates. One made by `openssl req -x509` with OpenSSL's
default configuration carries none and is refused (`CA cert does not include key usage
extension`); issued again over the same key and subject with `-addext
keyUsage=critical,keyCertSign,cRLSign`, it is accepted, and every certificate it signed verifies
against it ([verified-facts.md](design/verified-facts.md)).

**Never two cores on the cluster at once.** Once the core is deployed, `make cluster`, a driver
run in process on the development host under the same owner label, runs only with the core's
Deployment scaled to no replica (`kubectl scale deployment fylgja-core --replicas=0 -n fylgja`),
and it is scaled back to one after (`--replicas=1`). The labels name no core, the driver's watch
is cluster-wide, and since [D-070](design/decisions.md#d-070) a core deletes a pod of any twin's
whose container ended or restarted in it, so two would each act on the other's twins.

**The conformance suite on the cluster**, `make conformance DRIVER=clabernetes`, drives the
deployed core from the development host, as the CLI does from a workstation. It reads, beside the
node logins of `local/.env` and the `FYLGJA_CONFORMANCE_DRIVER` that `make` sets:

| Variable | Holds |
|---|---|
| `KUBECONFIG` | The cluster's kubeconfig: the harness reads the core's pod, its Lease and the twins' namespaces |
| `FYLGJA_API_ADDRESS`, `FYLGJA_API_TOKEN`, `FYLGJA_API_CA` | The core's `https://` address, a token and the CA, set as "Reach" says; the token is the suite's own principal's, its hash in the overlay's `secret/tokens` |
| `FYLGJA_CONFORMANCE_SELECTOR` | The label selector of the core's pod, `app.kubernetes.io/name=fylgja-core` in the base |
| `FYLGJA_CONFORMANCE_NAMESPACE` | The core's namespace, `fylgja` where it is unset |

A variable missing ends the session in one line naming it, and a value is never printed. The
deployed core runs with `FYLGJA_RESYNC_S` of 3600 or more as a literal of its pod, the overlay's
optional patch ([deploy/README.md](deploy/README.md)), so a restore the suite reads was started by
the driver's events and not by the resync; the suite refuses to start otherwise. It prints the tag
of the image the core runs, the only record of the commit a run read. To kill the core it labels
the pod that holds the Lease, cuts its egress by a NetworkPolicy of its own, writes an annotation on
the Lease between two renewals, or once one is 6 s overdue, so the release the dying pod sends is
refused, and deletes the pod with no grace; the next pod takes the Lease 15 s after
([D-072](design/decisions.md#d-072)). It undoes the policy, the label and the annotation after
each kill, and deletes the namespace `fylgja-conformance-probe` it makes for its isolation
scenario at its end. A run stopped hard leaves its twins in the store; the next run removes them
first, and says so.

**The maintainer's walk**, the phase's own gate ([Sequence](design/core.md#sequence), item 6): a
twin created over TLS by the CLI from `three-node`, stepped through each step fixture with `twin
verify` after each, and destroyed; and a twin from `mixed` given its cEOS port. In a shell with the
three variables set as "Reach" says; the cEOS steps need the EOS login among the overlay's
credentials:

```bash
(
  set -e
  f=core/.venv/bin/fylgja-core b=testdata/blueprint s=testdata/blueprint/steps
  $f twin create walk --blueprint $b/three-node.json; $f twin verify walk
  for to in $s/three-node-unlinked $b/three-node $s/two-node $b/three-node \
            $s/three-node-n1-disabled $b/three-node $b/three-node-unmanaged $b/three-node \
            $b/three-node-probed; do
    $f twin step walk --blueprint $to.json
    $f twin verify walk || { rc=$?; [ $rc -eq 1 ] || exit $rc; sleep 5; $f twin verify walk; }
  done
  $f twin step walk --blueprint $s/three-node-probed-moved.json --allow-restart; $f twin verify walk
  $f twin step walk --blueprint $b/three-node.json; $f twin verify walk
  $f twin step walk --blueprint $s/three-node-n3-eos.json --allow-restart; $f twin verify walk
  $f twin destroy walk
  $f twin create walk-eos --blueprint $b/mixed.json; $f twin verify walk-eos
  $f twin step walk-eos --blueprint $s/mixed-e2-port.json --allow-restart; $f twin verify walk-eos
  $f twin destroy walk-eos
)
```

Each command exits by its verdict: 0 for `ok`, 1 for `rejected`, `failed` or `nonconforming`, 3
for `unclean` or `diverged`, and 2 for a fault of the CLI's own. The walk runs in a subshell under
`set -e`, so the first command that does not exit 0 ends it and nothing after it runs; the shell
stays open, with the twin left as that command found it, to read with `twin show` and `run get`
and then destroy. A `twin verify` that exits 1 within seconds of a step, with `verify.node.unread`
as its only error, is no finding but the blink [verified-facts.md](design/verified-facts.md)
records, a node's Service the step kept without its endpoint for a second or two, so the loop asks
a verify that exits 1 once more, 5 s on, before the walk stops.

## Conventions

- **Platforms are data.** A platform is added by writing a platform package under `psp/`,
  never by code ([D-013](design/decisions.md#d-013), [D-015](design/decisions.md#d-015)).
- **Fixtures change in a commit of their own,** with the diff reviewed: the blueprints, the
  compiler facts and any golden file.
- **A rejection fixture carries one fault,** named in its file name and its header comment
  (a blueprint's in its `source` envelope), and the loader's or the compiler's test holds a
  row per fixture saying the rule and the pointer or object it must report: exactly those,
  so that nothing else is reported, and a fixture without a row fails.
- **A new rule goes in [`docs/rules.md`](docs/rules.md)** in the same change as the code
  that files it.
- **No credential in any output**: not in a blueprint, bundle, finding, answer or log line.
