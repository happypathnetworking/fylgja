# fylgja-core: a new Python core

This is the design of the new core: a Python rebuild of `fylgja-core` with a clean break in
formats, many named twins, and runtimes behind a driver seam. Phases 2–8 are planned from
it.

- **Done:** phase 0 (the decisions, the constitution, this repository); phase 1: the
  measurements on both runtimes (2026-10-30), and the multi-host stage on three k3s hosts
  (2026-11-02); phase 2: the formats, their model types and the loaders (2026-11-03); phase
  3: the compiler (2026-11-03); and phase 4: one named twin on the local driver
  (2026-11-03).
- **Next:** step, verify and probes on the local driver.
- **Meanwhile:** the orchestrator stays in the archived repository and drives the frozen Go
  core there, the reference implementation. It moves here at cut-over
  ([D-005](decisions.md#d-005)). Until then the core is built and tested from blueprint
  files.

The constitution is [`design/constitution.md`](constitution.md). The formats are in
[`formats/`](../formats/README.md). Terms are in the [glossary](../docs/glossary.md).

## Requirements

| Requirement | Value |
|---|---|
| The shape | Keep the two deployables ([D-003](decisions.md#d-003)): a core that turns one blueprint into a twin and steps, verifies, shows and destroys it, and an orchestrator that owns readers, stages, rehearsals and reports and drives the core through the API alone |
| What goes | The Go core's accumulated fields and its foundations: one twin at a time, state on local disk, one lab host |
| What must work | Many twins across many hosts |
| Language | Python, for its audience (network engineers) and its ecosystem (Infrahub's SDK, NetBox's client, Nornir, NAPALM) ([D-001](decisions.md#d-001)) |
| Runtimes | A driver seam ([D-017](decisions.md#d-017)): clabernetes on Kubernetes for production; a local containerlab driver, so development needs no Kubernetes; real hardware in a later release |
| Scale | About 5 concurrent twins of tens of nodes, on a 2–3-node cluster |
| First outside user | Not yet known. OIDC and RBAC roles wait for one |
| Node access | Direct, over SSH, gNMI or a CLI session, from outside the cluster |
| Core CLI | A thin API client |
| Repository | This repository: the core first, the orchestrator beside it at cut-over ([D-005](decisions.md#d-005)) |
| Process | Design document, decision entry, pull request ([D-033](decisions.md#d-033)) |
| Constitution | One, for both deployables, at `design/constitution.md` |
| The Go core meanwhile | Frozen, fixes only; the reference implementation |
| Compatibility | A clean break: every format and interface starts at version 1, nothing older is read, and the orchestrator moves to the new API in the same change ([D-002](decisions.md#d-002)) |
| Management reach between local twins | Accepted on the local driver, where it is host-routed. Closed on clabernetes by a NetworkPolicy per twin ([D-019](decisions.md#d-019)) |

## The decision: build from scratch, in Python, with the Go core as reference

Do not port the Go code. Write `fylgja-core` new ([D-001](decisions.md#d-001)). Use the
frozen Go core to explain behaviour and to supply test scenarios, not as code to translate.

**Why not reuse the code:**
- A change of language means no code carries over, and a port would copy a structure that
  has the old foundations written into it: the fixed lab name `fylgja`, fixed workflow ids,
  `twin.json` under a local state root, one task queue, one host and the `clab` CLI
  ([D-018](decisions.md#d-018), [D-019](decisions.md#d-019),
  [D-024](decisions.md#d-024), [D-023](decisions.md#d-023),
  [D-017](decisions.md#d-017)).
- The Go core is about 32k source lines, 22% of them comments, plus about 96k test lines.
  Those tests are tied to Go or Temporal: replay histories, `GetVersion` shims, and about 80
  frozen contract copies.
- The archived formats carry fields nobody reads, facts stored three to five times, and
  one-host and Temporal identity throughout. A clean break leaves them out (see "The
  formats").

**What carries over:**
- **Principles**: the blueprint as the only input, the API as the boundary, a pure compiler,
  platforms as data, no rendered configuration, honest reports.
- **Scenarios**: the blueprints in `testdata/blueprint/` and the declarations in
  `testdata/probes/invalid/`; the archived repository's CTM and PSP defect fixtures, to be
  rewritten as rejection fixtures for blueprint 1 and platform package 1; and the nine
  end-to-end cases of its `scripts/e2e.sh`, re-expressed as behaviours.
- **Data**: `psp/*.yaml` and `probes/ping.yaml`, converted to version 1.
- **Knowledge**: the containerlab, SR Linux and cEOS sections of
  [`design/verified-facts.md`](verified-facts.md) (about 50 facts, with measured timeouts
  and memory), and [`design/decisions.md`](decisions.md).

## What the measurements settled (2026-10-30)

Measured on containerlab 0.79 locally and on clabernetes 0.10.1 in a kind cluster.

| Question | Answer | Decision |
|---|---|---|
| cEOS interface aliases | **None** in containerlab 0.79–0.82, so one rename rule stays. The kind's name pattern is unanchored at the start: a wrong name ending in `et<digit>` (`Ethernet1`) is accepted silently and wires a port EOS never sees | [D-015](decisions.md#d-015) |
| SR Linux interface aliases | Yes: `ethernet-1/1` deploys as `e1-1`, breakouts too; an out-of-range name is refused at post-deploy | [D-015](decisions.md#d-015) |
| Bootstrap | **Not needed** on either kind or driver. With no startup-config, each kind's baseline holds the hostname, linked ports enabled, LLDP and gNMI, and all of it survives the replace push | [D-015](decisions.md#d-015) |
| Link changes | `link_apply_mode: live` re-cables both kinds with no restart on both drivers, for ports present at boot. cEOS never sees a port added later. The mode is set at create only: on clabernetes a change replaces every pod | [D-015](decisions.md#d-015) |
| The seam | **Seven calls** settled here, with `admit` joining to reserve what `plan` binds (a subnet, a namespace, devices); nine since phase 5 added `changes` and `exec` | [D-017](decisions.md#d-017), [D-011](decisions.md#d-011), [D-049](decisions.md#d-049) |
| The core's own reconcile loop | Holds. Kills mid-apply, after apply, between pushes and mid-destroy each reach the desired state in one resume, given two recovery rules and each node's recorded incarnation (below). clabernetes finishes a step after its managers are killed mid-step | [D-023](decisions.md#d-023) |
| Isolation | A lab or a namespace per twin works, with concurrent creates. Management reach between twins is closed on clabernetes by a NetworkPolicy per twin, and accepted locally | [D-019](decisions.md#d-019) |
| Orphans | Locally, swept only through containerlab, since it leaves root-owned host entries. On clabernetes, the namespace delete sweeps the twin (49 s) | [D-019](decisions.md#d-019) |
| clabernetes 0.10.1 | Installs from one pinned chart in 20 s. Fixture twins are Ready in 70–240 s | [D-017](decisions.md#d-017), [D-022](decisions.md#d-022) |
| Node access | A LoadBalancer per node: SSH, gNMI and the push work through it. Auto-expose off, ports from the package. Across hosts, each Service needs `externalTrafficPolicy: Local` (below) | [D-020](decisions.md#d-020), [D-037](decisions.md#d-037) |
| Account-gated images | A private registry the cluster trusts, with a pull secret per namespace | [D-021](decisions.md#d-021) |
| Memory | About 1.6–2 GiB per SR Linux node and 0.9–1.5 GiB per cEOS node, on both drivers. clabernetes' default request (512 Mi) is too low, so requests come from the package | [D-015](decisions.md#d-015), [D-022](decisions.md#d-022) |
| Still open | One unexplained reading: an SR Linux marker read as present after its pod was replaced by a link-mode switch. Scheduling at the packages' requests | [Open questions](decisions.md#open-questions) |

## The formats

Every format and interface starts at version 1 ([D-002](decisions.md#d-002)), and each
has one schema in [`formats/`](../formats/README.md). This section says what each holds
and why.

### 1. Blueprint 1

Schema: [`blueprint-1.schema.json`](../formats/blueprint-1.schema.json);
[D-006](decisions.md#d-006).

- **Body:** the network (devices, interfaces, links, each device's configuration) and
  probes.
- **Id: the RFC 8785 (JCS) SHA-256 over the network and probes only.**
  - The same topology read from two branches, at two times or by two readers gets one id.
  - JCS is a standard, so any language computes the id without mimicking another's
    encoder.
- **Source envelope, carried but not read.** `branch`, `at`, `scope`, `mapping`,
  `schema_hash`, `observed_at` and the reader's fidelity rows travel as an opaque `source`
  object. The core neither validates nor hashes them.
- **Every field is stated.** `mgmt_only` and `enabled` are required, so an absent field
  never hashes differently from its default.
- **Nothing derivable is stored.** An interface's link and a link's id follow from `links`.
  A configuration is a plain string; checking it against the source is the reader's job, at
  read time.
- **Lists arrive sorted.** An unsorted or duplicated list is rejected, never sorted on the
  client's behalf.

### 2. Platform package 1

Schema: [`platform-package-1.schema.json`](../formats/platform-package-1.schema.json);
[D-015](decisions.md#d-015). A package states only what the runtime's kind does not
already know.

| Kind knowledge | containerlab | Platform package 1 |
|---|---|---|
| Interface names | SR Linux maps `ethernet-L/P[/C]`, `eL-P` and `mgmt0` and refuses unknown names at deploy | Production names, with no port templates where the kind has aliases (`alias: true`) |
| cEOS interface names | No aliases: only `ethN` reaches EOS as `EthernetN` | One `rename` rule per data rule (`alias: false`) |
| Logins | Each kind sets a documented default login | One credential reference per platform |
| Bootstrap | Each kind's baseline holds hostname, linked ports, LLDP and gNMI | None |
| Boot wait | SR Linux waits for `mgmt_server`; cEOS runs post-deploy over the CLI | Readiness is "the push transport answers" |

- **Only implemented behaviour is a field.** The push is always a replace (a merge cannot
  step) with an explicit commit, and the startup format is `cli`; none of these is a field.
  `delivery` names one of the two push mechanisms.
- **Only the core's consumers are served.** Matching a source's platform to a package, and
  the source's artifact names, are the orchestrator's, since only a reader needs them.
  Interface mapping examples are test data.
- **Image and resources sit under `runtime.containerlab`**, and each driver reads them its
  own way:
  - `pull_secret` is an image pull secret on clabernetes, and a presence check locally;
  - `memory_mb` and `cpu` are pod requests on clabernetes, and an admission budget locally.
- **Link changes:** `link_apply_mode` (set at create, never changed) and `hot_add_ports`
  (whether a port added after boot appears in the NOS).
- **Fylgja's own knowledge:** interface rules, fidelity and approximations, measured
  timeouts, the push mechanism and conformance read paths.

### 3. Probe declaration and probe package 1

Schemas: [`probes-1.schema.json`](../formats/probes-1.schema.json) and
[`probe-package-1.schema.json`](../formats/probe-package-1.schema.json).

- **The declaration** is a list of blueprint probes: one definition serves both. Its order
  is free.
- `format` is checked against the loaded packages, not a schema enum, so a new package
  needs no schema change.
- **Address family:** IPv4 only.
- **The package:** readiness by `exec` alone, an image with an optional pull secret, and a
  host kind that is always `linux`.
- The `FylgjaProbe` kind is the orchestrator's to read into a declaration.

### 4. Bundle 1

Schema: [`bundle-1.schema.json`](../formats/bundle-1.schema.json);
[D-011](decisions.md#d-011).

- **Runtime-neutral, with nothing per twin.** A bundle holds no topology file and no lab
  name: a driver's `plan` renders those with the twin's name. One bundle can then back many
  twins on any runtime.
- **The manifest holds** nodes (name, platform, configuration checksum and file), mapping
  rows, links, probes, and the blueprint id, which references the source envelope.
- **Fidelity is not in the hashed bundle.** It is computed per deployment from the platform
  package and the mapping, since the runtime decides software or hardware forwarding
  (constitution X). Rewording a package moves no bundle id.
- **No image.** An image is runtime-specific, so it lives in the deployment.
- **No stored copies.** Probe hosts, their links and the management port are derived where
  they are needed.
- Bundles live in the state store, addressed by id. On clabernetes the configurations reach
  the nodes as ConfigMaps; locally they are files beside the rendered topology.

The **deployment** ([`deployment-1.schema.json`](../formats/deployment-1.schema.json)) is a
driver `plan`'s output: the rendered runtime files, the allocation `admit` reserved, the
demand admission checks, and the deployment's fidelity. A step finds what changes on the
runtime by comparing the old and new deployments.

### 5. Twin record 1 (in the state store, the same on every runtime)

Schema: [`twin-record-1.schema.json`](../formats/twin-record-1.schema.json);
[D-019](decisions.md#d-019), [D-023](decisions.md#d-023).

- **Spec**, written by a client ([D-025](decisions.md#d-025)): the blueprint id (or bundle
  id), the driver, and allow-restart. Beside it, the twin's `generation` and `revision`, and
  `deletion_requested_at` once deletion is asked for.
- **Status**, written by the loop alone:
  - conditions: Ready, Stepping, Diverged;
  - the blueprint id and bundle id;
  - the deployment id (the driver's plan) and the allocation;
  - the phase reached and the run in progress;
  - `nodes[]` with the driver's node handle (container, pod or device), its incarnation,
    address, access endpoint and `holds`;
  - the last step, by its run id;
  - the observed generation.
- **Facts are reached by id, not copied.** The source is reached through the blueprint id,
  and node facts through the bundle.
- **Timings are events of the run**, and a step's wait and loss are in its verdict.
- **One record per twin**, in its own file locally, and a lab named for the twin.

### 6. Findings 1 and errors

Schemas: [`findings-1.schema.json`](../formats/findings-1.schema.json) and
[`problem-1.schema.json`](../formats/problem-1.schema.json);
[D-025](decisions.md#d-025).

- **One error model.** RFC 9457 problem documents for anything malformed or refused at the
  door (4xx), and findings only for domain verdicts, so each fault lands in one place.
- **The core's own rule catalogue.** Rules for readers, stages and rehearsals are the
  orchestrator's ([D-003](decisions.md#d-003)), and no rule names a host or a workflow
  engine.
- **Exit codes** on the thin CLI only: 0 ok, 1 negative verdict, 2 usage or transport,
  3 twin left dirty.
- **JSON only.** The core renders no text; clients render, and the rehearsal's report is
  the orchestrator's.

### 7. API 1, resource-oriented, every run asynchronous

Schema: [`api-1.openapi.yaml`](../formats/api-1.openapi.yaml);
[D-025](decisions.md#d-025).

| Call | What it does |
|---|---|
| `POST /v1/blueprints` → `{id}`; `GET /v1/blueprints/{id}` | Files a blueprint; idempotent, since the id is the content's |
| `POST /v1/bundles {blueprint_id}` → `{id, manifest, fidelity, findings}`; `GET /v1/bundles/{id}` | Compiles a filed blueprint with the loaded packages |
| `GET /v1/bundles/{a}/diff/{b}` | What a step between two bundles changes, runtime-independent |
| `POST /v1/packages:validate` | Holds a package to its schema and cross-field rules |
| `GET /v1/twins`, `GET /v1/twins/{name}` | Every twin; one twin's record |
| `PUT /v1/twins/{name}` `{spec: {blueprint_id \| bundle_id, driver?, allow_restart?}}` → the record | A new spec creates or steps the twin ([D-025](decisions.md#d-025)); `driver` defaults to the server's configured one |
| `GET /v1/twins/{name}?watch=true` (and the list) | Server-sent events, one per change to the record |
| `GET /v1/drivers` | The drivers this core serves and their capabilities |
| `PUT /v1/twins/{name}?dry_run=true` | The plan, without applying it |
| `POST /v1/twins/{name}/verifications` | Reads every node once and judges it |
| `DELETE /v1/twins/{name}` → 202, the record | Deletion is requested, the loop tears down, the record goes |
| `GET /v1/runs?twin=`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events?after=N` (or SSE) | Runs, newest first; one run and its verdict; its events by cursor |
| `POST /v1/runs/{id}/cancel` | Cancels a run; it cleans up and ends |
| `GET /v1/version` | The API and build versions |

- **Every run is asynchronous.** A write answers at once and links its run, and a client
  follows it by cursor or by server-sent events. A request carries intent only: no output
  paths and no rendering options.
- **Auth.** Version 1 ships per-client bearer tokens (from Secrets, or a local file of
  hashes in development), each with a principal:
  - 401 and 403 kept distinct;
  - several keys valid at once, for rotation;
  - an audit log naming the principal;
  - TLS at the ingress.

  OIDC and RBAC roles follow when the first outside user is known.
- **Thin CLI**: `fylgja-core twin create|step|show|verify|destroy|list`,
  `run get|watch|cancel`, `blueprint push`, `bundle build|get|diff`, and `--json`. It renders
  text from documents and shares its client library with the orchestrator.

## Target shape

- **`core/`**: a Python 3.14 package, `fylgja_core`, with ruff, pytest and mypy in strict
  mode, the same tooling the orchestrator uses.
- **A shared model package** (blueprint 1, the JCS id, network types, validation, package
  loading), imported by both deployables once the orchestrator moves here. It is one module
  per format, named for the schema's stem: `blueprint`, `platform_package`,
  `probe_package`, `probes` (the declaration), `bundle`, `deployment`, `twin_record`,
  `findings` and `problem`, with what they share in `documents` and the schemas in
  `schemas`. Each follows one pattern: `validate` reports every problem in one pass, the
  version first, then the schema, then the rules the schema cannot state, each with a stable
  rule id and a JSON pointer; `decode` builds the model type or raises `Rejected`; a
  loader's `load` reads a file. A model type encodes back to its document unchanged, so a
  document has one representation (Constitution XII). The API's own response shapes (a
  run, an event, a driver) were built with the server in phase 4; the bundle diff's,
  `BundleDiff`, was built with its route in phase 5.

### Runtimes behind one driver seam

| Driver | When | Isolation unit | Many hosts | Node access |
|---|---|---|---|---|
| `containerlab` (local) | now: development, the live tier, a single lab host | a lab named for the twin, with its own management network and subnet | no; one host | the host's management network |
| `clabernetes` | now: production | a namespace per twin, with a NetworkPolicy | the cluster's nodes | a LoadBalancer per node ([D-020](decisions.md#d-020)) |
| `hardware` | a later release | a reservation of devices from a pool | the pool | the devices' own management addresses |

The seam has nine calls, and every call but `exec` is idempotent
([D-017](decisions.md#d-017), [D-049](decisions.md#d-049)):
- `capabilities()`: whether the driver provisions nodes or claims existing ones; whether it
  can re-cable live; per-kind restart behaviour; how nodes are reached.
- `admit(bundle, twin)`: reserves what the twin is bound to (a lab name and subnet, a
  namespace, a device reservation) into the twin record by compare-and-set, or refuses with
  the reason. `plan` is pure, so its allocation must exist before it runs.
- `plan(bundle, twin, allocation)`: pure; a runtime-specific deployment derived from the
  bundle, with its own id.
- `changes(before, after, packages)`: pure; what the runtime does to each node to go from
  one deployment to another, each with its reasons, and the links added and removed.
- `apply(deployment, files, packages, reconfigure)`, `inspect(twin)` and
  `destroy(deployment, files, packages)`: the packages' measured timeouts bound a deploy
  and a destroy, and `reconfigure` is the partial-lab remedy.
- `endpoints(twin)`: the management addresses that push, readiness, verify and flows use.
- `exec(twin, node, argv, timeout_s)`: an argument vector run inside a node, bounded in time
  and bytes; the one way into a node with no management transport, a probe host.

Push, readiness, verify and flows sit above the seam: they reach a node's management
address whatever runtime it runs on. Nothing above the seam names a runtime; it may branch
on a declared capability (constitution XIII).

**The `hardware` driver** is not built now. Its shape checks the seam on paper:

| Call | `hardware` | What it asks of the seam |
|---|---|---|
| `capabilities()` | claims rather than provisions; cannot re-cable; forwards in hardware; a node restart is a reboot | a capability for "cannot satisfy a link change", so a step refuses or approximates (a port shut) and says so in fidelity |
| `admit` | reserves devices from an inventory | admission returns an allocation for every driver |
| `plan` | a device assignment: node to device, production port to physical port; refused if the bundle's links are not a subset of the pool's fixed cabling | the inventory is an input, like the allocation |
| `apply` | claims the reservation and resets each device to a stored baseline | the replace push needs a stored golden baseline per device |
| `inspect` | reservation held, devices reachable, baseline loaded | same shape |
| `destroy` | resets to baseline, then releases; nothing is deleted | the orphan sweep becomes a reservation sweep |
| `endpoints` | the devices' static management addresses | same shape |

### Consequences of the seam

- **The bundle is runtime-neutral** ([D-011](decisions.md#d-011)). It holds nodes, links,
  the interface mapping, configurations and probes, and no containerlab topology. Each driver's `plan` renders its own deployment: `topology.clab.yml` for both containerlab
  drivers (with production names where the kind has aliases, renamed ports where it does
  not, and the twin's lab name), and a device assignment for hardware.
  - Design choice: this keeps the compiler and the bundle id independent of where a twin
    runs. `plan` is pure too, and is tested with fixtures.
- **Platform packages get a per-runtime section** ([D-015](decisions.md#d-015)).
  - `runtime.containerlab`: kind, image, resources, measured timeouts, `alias`, `rename`,
    `link_apply_mode` and `hot_add_ports`. Both containerlab drivers share it.
  - `runtime.hardware`: added with that driver.
  - Platform-level sections (interfaces, push, readiness, gNMI, conformance, fidelity) stay
    shared.
- **Fidelity depends on the runtime.** Containers forward in software and hardware in
  silicon, so fidelity is computed per deployment, beside the bundle.

### clabernetes as the driver relies on it

clabernetes 0.10.1 (released 2026-10-20) embeds containerlab 0.81. Verified on a kind
cluster on 2026-10-30 unless marked "from its docs".

| Fact | Consequence |
|---|---|
| A `Topology` CR (`c9s.run/v1alpha1`) holds the containerlab YAML as-is in `spec.definition.containerlab` | The clabernetes `plan` renders the same `topology.clab.yml` as the local driver and wraps it. The two `plan`s share most of their code |
| One Deployment and pod per node, with no Docker or containerlab inside | Kind behaviour that containerlab runs at deploy time may differ from local; aliases and running without bootstrap were checked on both drivers |
| `restart` and `recreate` replace the pod, losing the pushed configuration | A step that restarts or recreates a node re-pushes it: the loop re-enters `pushed` for those nodes, and the driver's capabilities say so |
| Each node gets its own LoadBalancer Service, and by default 14 TCP ports are exposed per node | `plan` sets `expose.disableAutoExpose: true` and declares only the package's push, gNMI and SSH ports ([D-020](decisions.md#d-020)) |
| The pod network is flat: a node reaches another twin's pods | `plan` emits a NetworkPolicy per twin that admits its own pods, the clabernetes namespace and non-pod sources ([D-019](decisions.md#d-019)) |
| The `mgmt` block is ignored and binds are rejected (from its docs) | `plan` relies on neither. Per-twin management networks are the local driver's alone |
| The controller fetches the image manifest from a registry before creating a pod | The account-gated cEOS image lives in a private registry, pulled through `Topology.spec.imagePull.pullSecrets` with the CA trusted by the controller's config ([D-021](decisions.md#d-021)) |
| The default request is 200m CPU and 512 Mi per node | Requests come from the package's `cpu` and `memory_mb` |
| Each node's Service is `externalTrafficPolicy: Cluster`, with no setting to change it; a patched value is kept across steps, pod replacements and a drain | `apply` patches each Service to `Local`, and `inspect` reports one that is not as drift ([D-037](decisions.md#d-037)) |
| A drain moves a host's nodes to the other hosts as new pods, at the same LoadBalancer addresses | The loop sees each moved node's new incarnation and re-pushes it ([D-036](decisions.md#d-036)) |
| No in-place upgrade from before 0.9; Kubernetes 1.31 or later, VXLAN and nftables required (from its docs) | Pin the clabernetes version in the driver's capabilities, and document the cluster prerequisites |
| containerlab 0.81.0 inside clabernetes (its `go.mod`); the development host moved from 0.79.0 to 0.81.0 on 2026-11-03 | No version skew between the two drivers: the local driver's containerlab is pinned to the version the clabernetes release embeds, so the kinds behave alike. The facts measured on 0.79 stand until phase 4 re-exercises them |

The clabernetes driver is one driver behind the seam ([D-017](decisions.md#d-017)). Its
development cluster is kind on one host ([D-022](decisions.md#d-022)); the production
cluster is three k3s servers with embedded etcd on SSD ([D-036](decisions.md#d-036)).

### Durability and state

- **The core owns its control loop** ([D-023](decisions.md#d-023)). A twin is a record
  whose desired state is a bundle. A level-triggered reconciler in the core process drives
  it through the driver, phase by phase: compiled, admitted, planned, applied, ready,
  pushed, verified, flows.
  It records each phase before the next begins, so a restarted core resumes from the record.
  - Neither kopf nor CRDs are used, because the local driver has no cluster.
  - Design choice: the Temporal Python SDK remains the fallback, should resuming mid-phase
    prove fragile in production.
- **Scheduling** ([D-023](decisions.md#d-023)): a work queue keyed by twin name and a
  bounded pool of workers, so each twin has at most one run while different twins proceed
  at once. A client's write, a driver's event, a periodic resync and the core's start each
  queue a twin. A twin waiting on the runtime goes back on the queue rather than holding a
  worker, and a transient failure backs off. One core per store: a Lease on Kubernetes, a
  lock on the local store's directory.
- **Two recovery rules** make a resume reach the desired state, measured on the local driver:
  - **A partial lab:** a lab present while the record lacks `applied` is probed. A plain
    redeploy of a partial lab is a silent no-op, so any node silent past the boot window
    means `deploy --reconfigure`.
  - **Residue after a killed destroy:** a resumed destroy cannot remove containerlab's
    root-owned host entries, so the fallback is deploy, then destroy.
- **Each node's incarnation** (the container's start time locally, the pod's uid on
  clabernetes) is recorded. When `inspect` reports a different one, the node was replaced
  and lost its push: the loop voids its `holds` and pushes again.
- **A state-store interface** holds twin records, run records and their events, blueprints
  and bundles, and offers a compare-and-set write on a twin record.
  - `local`: a directory, for development, with each twin's record in its own file. No
    single state root assumes one twin.
  - `object`: S3-compatible storage (MinIO in development), for production.
  - Still no database (constitution IX). The compare-and-set write is what keeps concurrent
    runs on two twins from colliding.
- **On Kubernetes** the core runs as one replica, holding a Lease so that a second never
  reconciles at the same time. Pods and namespaces carry owner labels, so an orphan is found
  by a label sweep.
- **Run history**: run records and their events live in the store, read with a cursor by
  `GET /v1/runs/{id}/events`.
- **Node logins** come from the environment locally and from Secrets on Kubernetes, both
  behind one credential provider.
- **Platform behaviour**: SR Linux JSON-RPC push, EOS eAPI push, gNMI reads, verify, bundle
  diff and ping flows. For behaviour, read the archived repository's Go core:
  `internal/lab/push_jsonrpc.go`, `push_eapi.go`, `gnmi_get.go`, `internal/verify`,
  `internal/step` and `lab/flows.go`.

## Phase 4: one named twin on the local driver (settled 2026-11-03)

Phase 4 is six plans, each a branch and a pull request useful on its own, in this order:
the local store ([D-041](decisions.md#d-041)); the containerlab driver's pure half
(`capabilities`, the allocation `admit` reserves, and `plan`, which renders
`topology.clab.yml` and takes over the lossy and shared-port facts the compiler leaves to
it; [D-043](decisions.md#d-043), [D-044](decisions.md#d-044)); the driver's live half
(`admit`, `apply`, `inspect`, `destroy`, `endpoints`, the two recovery rules, each fact
re-verified on containerlab 0.81.0); push and readiness (the credential provider, the two
replace mechanisms of [D-027](decisions.md#d-027)); the reconcile loop with runs and events
([D-023](decisions.md#d-023), [D-040](decisions.md#d-040)); and API 1 with the thin CLI
([D-025](decisions.md#d-025), [D-026](decisions.md#d-026)). The live half and the push can
proceed in parallel once the pure half is in.

What the phase settled before code: its libraries ([D-039](decisions.md#d-039)), its
configuration and the credential provider's naming ([D-042](decisions.md#d-042)), and the
entries above. **Logging** is the standard library's, one JSON object per line on stderr,
each with the time, the level, the logger, the message and the fields it carries (a twin,
a run, a phase); the **audit log** is the same stream, each write to a twin carrying the
principal and the action, so no second sink is run. No credential reaches a line
(Constitution X): the credential provider logs names, never values.

The phase is done when `fylgja-core twin create`, `show` and `destroy` run end to end on a
fixture through the API, a kill at each phase boundary resumes to the desired state, and
every containerlab behaviour the driver relies on is recorded for 0.81.0.

## Phase 5: step, verify and the burst on the local driver (settled 2026-11-04)

Phase 5 takes a running twin from one bundle to another at layer 1, judges what the twin
formed, and sends one burst of traffic across it. It is built against the seam as phase 4
left it, on the local driver alone.

**What the phase is for.** The orchestrator rehearses a change on a twin: it steps the twin
to the change's blueprint and reports what happened. The report leads with traffic: which
declared flows pass after the change. The step is a layer-1 step, on links and nodes added,
changed and removed. Configuration rides along: the blueprint is a snapshot, so a new node is
pushed after it boots and a restarted or recreated one is pushed again, but a configuration
change as a workflow is the orchestrator's, in production, and a device may carry no
configuration at all ([D-048](decisions.md#d-048)). Verify is a layer-1 judgement: an
exception on a change, a wrong LLDP neighbour, a linked port down, a node missing or
replaced. The probes stay a placeholder: one format, `ping`, and one burst per probe after
the step settles, no flow across the step and no loss counters.

**What is settled before code.**

- **Configuration is optional, and absent means unmanaged** ([D-048](decisions.md#d-048)).
  Blueprint 1 drops `config` from a device's required members; a device with none compiles
  to a node with no configuration file; the push passes it over and marks it as holding the
  bundle; verify makes no claim of it; a step from a configuration to none pushes nothing,
  and the node keeps what it holds, which after a recreate is the kind's baseline. Both kinds'
  baselines carry the host name, linked ports enabled, LLDP and gNMI
  ([D-015](decisions.md#d-015)), so a blueprint with no configuration is a complete layer-1
  twin.
- **The seam grows by two calls and one argument** ([D-049](decisions.md#d-049)): `changes`,
  pure, says what the runtime does to each node between two deployments (kept, added,
  removed, re-cabled live, restarted, recreated, each with its reason), so the loop knows
  before `apply` what `allow_restart` must cover; `exec` runs an argument vector inside a
  node, for a probe host's readiness and the burst, since a host has no management
  transport; and `admit` takes the deployment a stepping twin has applied, keeps its
  allocation, and checks the demand the new deployment adds over it. containerlab's own dry
  run is `changes`'s oracle in the live tier, never its implementation. One case the oracle
  does not name: a port added after boot to a kind that cannot add one (cEOS under the
  `live` link mode gets a veth EOS never lists). `changes` answers it `recreated`, and the
  driver's `apply` makes it so by removing that node before the deploy, which recreates it
  with its ports. Plan 3 verified that on 0.81.0 (the phase 5 block, "`changes` against the
  dry run", of [verified-facts.md](verified-facts.md#containerlab-0790)): containerlab
  obliged, so the fallback, a refusal (`step.relink.unsupported` for that node) and never a
  dead port, was not needed.
- **A step's phases are the create's** ([D-050](decisions.md#d-050)): `compiled`,
  `admitted`, `planned`, `applied`, `ready`, `pushed`, `verified`, `flows`, each recorded
  before the next. After `planned` and before anything is touched the loop refuses, ending
  the run `rejected` with the twin running what it ran: a diverged twin
  (`step.twin.diverged`, [D-029](decisions.md#d-029)), a restart or recreate without
  `allow_restart` (`step.restart.required`), a link change on a driver that cannot re-cable
  (`step.relink.unsupported`). A refused step is recorded as a refused create is: the
  observed generation catches up, `Ready` is False with the refusal's rule as its reason,
  and `last_step` ends with the outcome `rejected`, naming the run, so a watcher reads the
  verdict from it. `ready` and `pushed` act on the nodes `changes` named and on every node
  whose incarnation `inspect` reports changed; a node whose configuration is unchanged
  between the two bundles is marked as holding the new one without a push, and a node
  without configuration likewise. `verified` is the wait: verify until it holds or
  `FYLGJA_STEP_WAIT_S` runs out, an expiry being a warning (`step.wait.expired`), never a
  failure ([D-032](decisions.md#d-032)). A kill resumes after the last recorded phase under
  the create's rules, with two differences: the partial-lab probe runs only when the run's
  events show an `apply` started and not ended, since on a step the lab is always present;
  and the silent-node remedy, `reconfigure`, recreates every node, so without
  `allow_restart` the step ends `diverged` (`step.node.silent`) instead. A step whose bundle
  is the twin's ends `ok` at `compiled`, `last_step` outcome `unchanged`. A spec written
  while a run is in flight is accepted: the run completes toward its own target, the pass
  records the generation it took the run under, and the next pass steps to the newer spec.
- **No rollback** ([D-029](decisions.md#d-029) stands). A step that fails or is cancelled
  after `apply` began leaves the twin up and `Diverged`, the record naming the phase and each
  node's held bundle; a diverged twin accepts only deletion. A cancel before `apply` ends the
  run `failed` with `run.cancelled` and touches nothing.
- **Verify reads layer 1 from both ends** ([D-031](decisions.md#d-031) stands,
  [D-051](decisions.md#d-051)): each device node's host name, asserted against the device
  name only where no configuration could have changed it, and otherwise read and reported,
  since a source-rendered configuration carries the production hostname and a reader renames
  the device to a DNS-1123 label; `port.enabled` on every cabled port, a link's end or a
  probe's endpoint; `port.neighbor` on both ends of every intent link, each end's
  `system-name` compared with the far node's read host name and its `port-id` with the far
  port, since a shut port still lists a far end that restarted while the far end sees none
  ([verified-facts.md](verified-facts.md)); the record's claim, for a node with a
  configuration; and the `burst`, each direction of each probe, run by `exec`. A port intent
  disables, its link, a synthesized link's neighbour, a node with no configuration's claim
  and a configured node's host name are skips, each an info finding. `nonconforming` means every node was read and an
  assertion failed; a node that could not be read ends the verdict `failed`
  (`verify.node.unread`) and is never nonconforming. Verify is refused `409` on a twin with
  no applied deployment, and reads a stepping or diverged twin as it stands, against the
  bundle it is stepping to. The reads are gNMI, by the package's `conformance` paths
  ([D-030](decisions.md#d-030)); the client library is [D-052](decisions.md#d-052).
- **The flow across the step is not built** ([D-051](decisions.md#d-051)). A step's verdict
  lists each probe of the target bundle, both directions, outcome `not_started`, and
  findings 1 says so in that value's description. The `flows` phase records that and is
  otherwise skipped. The burst is the traffic the report leads with.
- **The bundle diff is a pure function of two manifests**, answered by
  `GET /v1/bundles/{a}/diff/{b}` in API 1's `BundleDiff` shape: nodes added, removed and
  changed (reasons `platform`, `mapping`, `config`, where `config` covers a checksum moved
  and a configuration present on one side alone), links added and removed, probes added and
  removed. An image change is no bundle fact (formats note 3); `changes` finds it.
- **A dry run of a step** (`PUT …?dry_run=true` on a twin that exists) compiles, admits the
  added demand, plans and runs `changes`, writing nothing, and answers `Plan` with a new
  optional member, `changes`, beside the deployment and the verdict, `rejected` where the
  step would be refused.
- **Formats touched**, each in the change that builds it: blueprint 1 and bundle 1
  (`config` optional), twin record 1 (`holds` for a node with no configuration;
  `last_step.outcome` gains `rejected`; `status.generation_in_flight`, the generation the
  run the record names works toward ([D-054](decisions.md#d-054)); the description of
  `allow_restart` names `step.restart.required`, as [D-029](decisions.md#d-029) does, where it says
  `step.restart.refused`), findings 1 (`not_started`'s description),
  API 1 (`Plan.changes`; the `501` answers of the diff, verify and a step go), the server's
  settings (`FYLGJA_STEP_WAIT_S`, adding to [D-042](decisions.md#d-042)), and the rule
  catalogue (`step.*`, `verify.*`, `config.missing` narrowed).
- **Logging** stays as phase 4 set it. A step's events carry each node the phase acts on;
  the device's diff from a push lives in the run's events alone, bounded, as
  [D-029](decisions.md#d-029) says.

**Non-goals.** Flows across the step and loss counters; rollback or repair of a diverged
twin; a configuration-change workflow; a second probe format; clabernetes (phase 6); more
than one twin at a time (phase 7). **Anti-goals**, each a failure even if the code works: a
node restarted without `allow_restart`; a verdict that says a flow passed when none ran; a
read of a node's configuration; a client that learns what a step does from a runtime name.

**Six plans, each a branch and a pull request useful on its own, in this order:**

1. **Optional configuration** ([D-048](decisions.md#d-048)): the two schemas, the compiler,
   the push, the record, the rule catalogue, and a fixture with a device that carries none.
2. **The bundle diff**: the pure function, its route, `fylgja-core bundle diff`, and fixture
   pairs for every kind of change.
3. **The seam's growth** ([D-049](decisions.md#d-049)): `changes`, `exec` and `admit`'s
   held allocation on the seam and the local driver; probe hosts' readiness in the ready
   phase, for a create too; pure tests of `changes` over deployment pairs; a live test that
   holds `changes` to containerlab's dry run for every kind of change, recorded on 0.81.0.
4. **Verify** ([D-051](decisions.md#d-051), [D-052](decisions.md#d-052)): the gNMI reader
   of the fact vocabulary, the assertions derived from the manifest, the burst by `exec`, the
   route, `fylgja-core twin verify`, and a live test on a probed fixture.
5. **The step** ([D-050](decisions.md#d-050)): the loop's step path, its refusals, phases,
   wait, resume and cancel; the API's step and its dry run; `fylgja-core twin step`.
6. **The live tier for steps**: a link added and removed on SR Linux live; a cEOS node
   restarted under `allow_restart` and refused without it; a node added and removed; a kind
   change; a kill at each phase boundary; a cancel mid-apply ending diverged. Each
   containerlab behaviour the step relies on is recorded for 0.81.0.

Plans 1 and 2 are independent of each other and of the rest; 3 precedes 4 and 5; 6 closes.
The live tier runs one plan's scenarios at a time on the development host.

**The phase is done** when `fylgja-core twin step` takes a fixture twin through plan 6's
scenarios end to end through the API, a kill at each phase boundary resumes to the desired
state or ends `diverged` as designed, `twin verify` answers on demand with the burst held, the
bundle diff answers for every fixture pair, and every containerlab behaviour the step and
`changes` rely on is recorded for 0.81.0.

**Left to the builder.** The module layout (`fylgja_core.diff`, `fylgja_core.gnmi`,
`fylgja_core.verify`, `fylgja_core.burst`, or otherwise); when `status.bundle_id` and
`status.deployment_id` move to the target (they move at `applied`, with `blueprint_id` and
`nodes`, `last_step.from` keeping the previous and `last_step.phase` alone recording the phases
before it, [D-054](decisions.md#d-054)); the exact wording of each new finding; the shape of
`changes`'s reasons; `exec`'s output bound; and the fixtures.

### The deploy's output goes to a file (2026-11-04)

Plan 6 read on the running system that a `containerlab deploy` whose core has died dies of
SIGPIPE, at its next write by inference, since the core held its stdout and stderr as pipes. A
kill in a node's post-deploy wait leaves the nodes made and the hosts block and ssh config never
written, and a create's resume, finding every node answering, skips the apply: a Ready twin
no one on the host can reach by name. The driver therefore gives each deploy a file for its
output, `deploy.log` in the twin's directory, beside the topology it describes, and reads the
file's tail when the deploy fails. A deploy the core's death orphans then runs to completion,
which is what the waits of [D-054](decisions.md#d-054) item 14 and
[D-055](decisions.md#d-055) were premised on; the file is never logged
([D-056](decisions.md#d-056)).

## Sequence

0. **The baseline.** *Done.* The decision log ([decisions.md](decisions.md)), the
   constitution (`design/constitution.md`), the process (`CONTRIBUTING.md`) and this
   repository; the Go core frozen in the archived repository.
1. **Measure both runtimes.** *Done on 2026-10-30, and the multi-host stage on 2026-11-02.*
   See "What the measurements settled" and "The multi-host stage".
2. **Formats 1.** *Done on 2026-11-03.* The schemas are current in
   [`formats/`](../formats/README.md), the packages are converted, and the fixtures are
   blueprints. Every format has a model type in `core/src/fylgja_core/`; the blueprint
   module holds the id, the order rules and the cross-field rules; and the loaders for
   platform packages, probe packages and probe declarations hold each document to its
   schema and to the cross-field rules its schema names, with a rejection fixture per fault
   under `testdata/`. Two rules are the loaders' own: a probe package whose format this
   build has no mechanism for is refused at load ([D-014](decisions.md#d-014)), and a
   declaration's probe formats are checked against the loaded probe packages. The
   registry-level rule, two loaded packages with one id, is the server's, in phase 4.
3. **Compiler.** *Done on 2026-11-03.* Blueprint plus packages to bundle 1
   (`fylgja_core.compiler`, with `fylgja_core.mapping` deciding each interface by its
   package's rules). It is checked against the four fixtures for the **same facts** as the
   Go core's goldens: nodes, links, mapping rows, configurations, probes and omissions. Byte
   equality is not the target, since the formats changed. Lossy counts and ports shared by
   a rename are the driver plan's facts, since only the plan renders the rename, and are
   checked when the plan is built in phase 4. The defect fixtures became rejection tests:
   the compiler's under `testdata/compiler/rejected/`, and a test over imports enforces
   purity. What the compiler refuses and what it omits is [D-038](decisions.md#d-038): two
   choices bundle 1 made differ from the Go core (an interface no rule matches, and no link
   touches, is an omission fidelity reports rather than a refusal, and sharing is the
   plan's finding), a network with no devices is refused, a device's second management-only
   interface is an omission (`extra_management`), a device name is a DNS-1123 label,
   required by the blueprint schema, and a blueprint whose hashed body UTF-8 cannot encode
   is refused at the door. The rule catalogue starts at
   [`docs/rules.md`](../docs/rules.md).
4. **One named twin on the local driver**: the reconcile loop, the local store, create,
   readiness, push, show and destroy, through the API and the thin CLI. **No Kubernetes
   anywhere in this phase.** *Done on 2026-11-03.* It built the local store
   ([D-041](decisions.md#d-041)); the containerlab driver, its pure `plan` and its live
   `admit`, `apply`, `inspect` and `destroy` with the two recovery rules, every behaviour it
   relies on re-verified on containerlab 0.81.0; the credential provider, readiness and the
   two replace mechanisms ([D-027](decisions.md#d-027)); the reconcile loop, with runs and
   their events, which resumes after a kill at the phase after the one recorded
   ([D-023](decisions.md#d-023)); and API 1 on Starlette and uvicorn with per-client tokens,
   problem documents and watches by server-sent events, beside the thin CLI
   ([D-025](decisions.md#d-025), [D-026](decisions.md#d-026), [D-039](decisions.md#d-039)).
   The live end-to-end test runs `three-node` through `fylgja-core-server` and the CLI, with
   the server killed at every phase boundary of a create, during the deploy and during a
   destroy, each resumed to the state asked for. It left to phase 5 a probe host's
   readiness (probe hosts are deployed and their readiness skipped), steps (a new spec on a
   twin that exists answers `501`), verify, the flows, the Docker events trigger (the loop
   is kicked by writes and resyncs on a period), and the bundle diff route. It also left:
   the stray `containerlab deploy` a killed core leaves running in its own session, which the
   driver does not stop before it acts (the test that kills the server mid-deploy passed
   because the orphan had made the nodes before it ended; phase 5 read that such a deploy
   dies of SIGPIPE, at its next write by inference, since the core held its output as pipes,
   and gave the deploy a log file, [D-056](decisions.md#d-056)); a sweep of the eAPI
   configuration sessions a push leaves pending, beyond its best-effort abort; the CLI's
   reconnect of a watch the server ends early; and `schemas.formats_dir()`, which resolves
   `formats/` through the repository and so must change before the client is installed
   outside the tree.
5. **Step, verify and the burst** on the local driver: the bundle diff, a layer-1 step
   through the loop, verify's rules read from both ends, and one burst per probe. Settled
   and *done on 2026-11-04*; see "Phase 5". It built: configuration as an optional element
   of a blueprint, an unmanaged node pushed nothing ([D-048](decisions.md#d-048)); the bundle
   diff and its route; `changes` and `exec` on the seam, with `admit` holding a stepping
   twin's allocation ([D-049](decisions.md#d-049)); verify over gNMI with pygnmi and each
   probe's burst by `exec` ([D-051](decisions.md#d-051), [D-052](decisions.md#d-052),
   [D-053](decisions.md#d-053)); the step through the loop, the API and the CLI, with its
   refusals, its record before `applied`, its resume and its cancel, and a probe host's
   readiness by `exec` ([D-050](decisions.md#d-050), [D-054](decisions.md#d-054)); and a live
   tier that steps a twin through every fixture, kills the core at each phase boundary,
   cancels a step mid-apply and deletes a twin after a kill. Two driver rules came out of that
   tier: a destroy waits for a stray deploy and removes every container of the lab
   ([D-055](decisions.md#d-055)), and the deploy's output goes to a file so that a stray
   deploy runs to completion ([D-056](decisions.md#d-056)). It left to later phases: the
   flows beyond one burst per probe, the Docker events trigger, and item 4's leftovers (the
   eAPI session sweep, the CLI's watch reconnect, and `schemas.formats_dir()`).
6. **The clabernetes driver**: the object store, the Lease, per-twin namespaces and node
   access. The driver conformance suite passes on both drivers.
7. **Many twins**: concurrent create and step, and admission refused when capacity runs out.
   Several labs on the development host locally, and five twins on a 2–3-node cluster.
8. **Cut-over**, once phase 5 runs twins locally ([D-005](decisions.md#d-005)):
   - Move the orchestrator into this repository. It writes blueprint 1 and calls API 1, in
     the same change ([D-006](decisions.md#d-006)).
   - Run a rehearsal end to end on the new core, on both drivers.
   - Retire the Go core.
   - **The `hardware` driver** is a later release's feature, built on the seam as it then
     stands.

## Verification

- **Formats**: every document the core emits validates against its schema. JCS ids are
  checked against a second, independent JCS implementation.
- **Compiler**: the four fixtures compile to the facts the Go core's goldens hold, tested by
  a small test that reads those goldens while they exist. The new bundles become the
  goldens.
- **API**: a pytest suite written from the OpenAPI document, run against the deployed
  service.
- **Driver `plan`**: pure fixture tests, one bundle rendered by each driver.
- **Live tier, local driver** (no Kubernetes): pytest end-to-end tests of the nine
  end-to-end behaviours, and several twins at once.
- **Driver conformance suite**: one set of scenarios (create, push, step, verify, destroy,
  orphan sweep, node access) run on each driver's own runtime. The clabernetes run needs a
  2–3-node cluster and covers five concurrent twins.
- **Resumption**: kill the core mid-phase on each driver; the twin reaches its desired state
  or is cleaned up.
- **Orchestrator**: its pure and contract suites stay green, and a rehearsal passes on the
  new core.

## The multi-host stage (2026-11-02)

The clabernetes measurements of 2026-10-30 ran on a kind cluster on one host. The
multi-host stage repeated them on three Proxmox VMs running k3s v1.37.1+k3s1, each with
8 vCPU, 24 GiB and 80 GB on spinning disks. It decided the production cluster's shape
([D-036](decisions.md#d-036)) and confirmed clabernetes for production
([D-017](decisions.md#d-017)). The facts are in
[verified-facts.md](verified-facts.md#k3s-v1371k3s1-three-servers-with-clabernetes-0101).

| Question | Answer | Decision |
|---|---|---|
| The cluster | Three k3s servers with embedded etcd, MetalLB 0.16.0 in layer 2, clabernetes 0.10.1, and the private registry under Podman on one host | [D-036](decisions.md#d-036) |
| etcd | **Lost its leader on spinning disks** when three hosts unpacked an image at once, and k3s restarted on two servers. Relaxed timings and pulls one host at a time cut it to blips of 2–3 s. Production puts etcd on SSD | [D-036](decisions.md#d-036) |
| Spread | The default scheduler put each three-node twin one node per host, so every link crossed hosts over VXLAN | — |
| Steps across hosts | As on kind: default modes replace the cEOS pods (136–138 s); switching to `live` replaces every pod; `live` replaces none (25 s) | [D-015](decisions.md#d-015) |
| Node access over the LAN | **Refused for some nodes** by the twin's NetworkPolicy, until each Service was set to `externalTrafficPolicy: Local` | [D-037](decisions.md#d-037) |
| Isolation | Holds over TCP. Ping is no test: k3s's policy controller accepts ICMP echo into every pod | [D-019](decisions.md#d-019), [D-037](decisions.md#d-037) |
| Five twins | Three created at once were Ready in 89–119 s with the images present. 15 nodes, 15 addresses; every node's push transport, SSH and gNMI answered | — |
| Use | About 6.8 cores and 23 GiB for the five twins. Per node: SR Linux 0.35–0.5 core and 1.6 GiB, cEOS 0.2–0.45 core and 0.9 GiB. The packages' `cpu` is now 0.5 | [D-015](decisions.md#d-015) |
| Drain | One host drained in 6 s; every twin Ready again in 94–114 s on the other two, at the same addresses, its moved nodes new pods. Nothing moved back after the uncordon | [D-036](decisions.md#d-036) |
| Teardown | 13–14 s for an SR Linux twin, 46–48 s for a mixed one; nothing left by label | [D-019](decisions.md#d-019) |

The twins ran on clabernetes' default requests (200m CPU, 512 Mi), not the packages'. The
packages' `cpu: 0.5` is set from what the nodes used. The scheduler has not yet placed
twins at the packages' requests ([open questions](decisions.md#open-questions)).

### Production cluster sizing

Five twins of 20 nodes is 100 nodes. At the packages' requests (SR Linux 2 GiB and 0.5 CPU,
cEOS 1.5 GiB and 0.5 CPU) that is up to 200 GiB and 50 CPUs, which two hosts must hold
while the third is drained. So: **three hosts of 128 GiB and 32 vCPU each**, with etcd on
SSD ([D-036](decisions.md#d-036)). The trial's three hosts of 8 vCPU and 24 GiB held five
three-node twins with a host drained, with 10–11 GiB to spare on each remaining host.

### Cluster prerequisites

On each host:
- x86_64, with no nested virtualization;
- SSD for etcd, or else `etcd-arg` `heartbeat-interval=500` and `election-timeout=5000` in
  `/etc/rancher/k3s/config.yaml`, with images pulled one host at a time;
- k3s pinned by version, installed with `--disable servicelb --disable traefik`;
- the private registry's CA in `/etc/rancher/k3s/registries.yaml`;
- the `vxlan` and `nf_tables` modules;
- on Ubuntu, the AppArmor widening for SR Linux's `rsyslogd` (`design/verified-facts.md`);
- inotify limits of at least 512 instances and 524,288 watches;
- time sync.

Between them:
- one L2 segment for MetalLB, with a pool outside DHCP of one address per node of every twin
  at once;
- open: TCP 6443 and 10250, TCP 2379–2380 (etcd between servers), UDP 8472 (flannel),
  UDP 14789–14790 and TCP 14791 (clabernetes).

And beside them, the private registry on a host outside the cluster, which is never drained
with it.

## Risks to watch

- **clabernetes maturity.** The 0.8 → 0.9 upgrade was destructive, and there is no in-place
  upgrade from before 0.9. Pin the version, and read each release's notes before moving.
- **The cEOS name pattern.** containerlab accepts a wrong cEOS interface name silently. The
  plan emits only rename output for cEOS, and conformance checks that every linked port
  appears in the NOS. The pattern's defect is worth reporting upstream.
- **Privileged pods** for SR Linux, and memory: five twins need the multi-node cluster by
  phase 6.
- **Distributing the account-gated cEOS image** without making it public: the private
  registry must stay private ([D-021](decisions.md#d-021)).
- **LoadBalancer addresses.** One per node means five twins of tens of nodes take hundreds
  of addresses. A bastion or ingress per twin returns if the pool runs short
  ([D-020](decisions.md#d-020)).
- **The core's own reconcile loop.** Resuming held on the local driver with the two recovery
  rules; it is not yet exercised on clabernetes under the core's own loop. Temporal Python is
  the fallback.
- **Two drivers drifting apart.** The conformance suite is the guard, and so is the rule
  that nothing above the seam names a runtime. Pin containerlab to the version clabernetes
  embeds.
- **A seam shaped by containers alone.** Hardware claims rather than creates. The paper
  `hardware` driver above checks the seam before it sets.
- **An unexplained reading.** An SR Linux marker read as present after its pod was replaced
  by a link-mode switch. The multi-host stage pushed no marker, so it is still open; the
  driver conformance suite's step scenarios re-check it.
- **etcd's disks.** On spinning disks, etcd lost its leader under parallel image pulls.
  Production needs SSD; relaxed timings are only a fallback ([D-036](decisions.md#d-036)).
- **The Services' traffic policy is a patch.** clabernetes has no setting for
  `externalTrafficPolicy`, so the driver patches it and watches for drift
  ([D-037](decisions.md#d-037)). Worth asking upstream for a field.
