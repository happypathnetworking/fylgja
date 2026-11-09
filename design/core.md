# fylgja-core: a new Python core

This is the design of the new core: a Python rebuild of `fylgja-core` with a clean break in
formats, many named twins, and runtimes behind a driver seam. Phases 2–8 are planned from
it.

- **Done:** phase 0 (the decisions, the constitution, this repository); phase 1: the
  measurements on both runtimes (2026-10-30), and the multi-host stage on three k3s hosts
  (2026-11-02); phase 2: the formats, their model types and the loaders (2026-11-03); phase
  3: the compiler (2026-11-03); phase 4: one named twin on the local driver (2026-11-03);
  phase 5: step, verify and the burst on the local driver (2026-11-04); phase 6: the
  clabernetes driver, the core as a pod and the conformance suite (2026-11-08); and phase 7:
  many twins at once, admitted by the runtime's room (2026-11-09).
- **Next:** the cut-over (phase 8).
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
| Link changes | `link_apply_mode: live` re-cables both kinds with no restart on both drivers, for ports present at boot. cEOS never sees a port added later. The mode is set at create only: on clabernetes a change replaces the pod of each node whose mode changed | [D-015](decisions.md#d-015) |
| The seam | **Seven calls** settled here, with `admit` joining to reserve what `plan` binds (a subnet, a namespace, devices); nine since phase 5 added `changes` and `exec`, ten since phase 6 added `events`, eleven since phase 7 added `capacity` | [D-017](decisions.md#d-017), [D-011](decisions.md#d-011), [D-049](decisions.md#d-049), [D-058](decisions.md#d-058), [D-073](decisions.md#d-073) |
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
  - TLS at the server ([D-063](decisions.md#d-063)).

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

The seam has eleven calls, and every call but `exec` is idempotent
([D-017](decisions.md#d-017), [D-049](decisions.md#d-049), [D-058](decisions.md#d-058),
[D-073](decisions.md#d-073)):
- `capabilities()`: whether the driver provisions nodes or claims existing ones; whether it
  can re-cable live; per-kind restart behaviour; how nodes are reached; whether applying
  again finishes an apply cut short ([D-068](decisions.md#d-068)).
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
- `events()`: an asynchronous iterator of the names of twins whose runtime changed, which
  the loop kicks; a driver's own trigger, beside the write, the resync and the start.
- `capacity(reserved)`: the runtime's room as `admit` would read it now, each host's total and
  free CPU and memory and the pending demand of the twins whose allocations are `reserved`;
  `admit` is written over it, passing its own `reserved` ([D-073](decisions.md#d-073)).

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
  the interface mapping, configurations and probes, and no containerlab topology. Each
  driver's `plan` renders its own deployment: the same containerlab definition for both
  containerlab drivers (with production names where the kind has aliases, renamed ports
  where it does not, and the twin's lab name), a file of its own locally and wrapped in a
  `Topology` on clabernetes, and a device assignment for hardware.
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
| A `Topology` CR (`c9s.run/v1alpha1`) holds the containerlab YAML as-is in `spec.definition.containerlab` | The clabernetes `plan` wraps the containerlab definition the local driver's plan renders, less its `mgmt` block, with each device's ports declared, a gated image prefixed and the core's label (`fylgja.owner: core`) beside the twin's in its default labels. The two `plan`s share most of their code |
| One Deployment and pod per node, with no Docker or containerlab inside | Kind behaviour that containerlab runs at deploy time may differ from local; aliases and running without bootstrap were checked on both drivers |
| `restart` and `recreate` replace the pod, losing the pushed configuration | A step that restarts or recreates a node re-pushes it: the loop re-enters `pushed` for those nodes, and the driver's capabilities say so |
| Each node gets its own LoadBalancer Service, and by default 14 TCP ports are exposed per node | `plan` sets `expose.disableAutoExpose: true` and declares only the package's push, gNMI and SSH ports ([D-020](decisions.md#d-020)) |
| The pod network is flat: a node reaches another twin's pods | `plan` emits a NetworkPolicy per twin that admits its own pods, the clabernetes namespace, non-pod sources ([D-019](decisions.md#d-019)) and the core's namespace ([D-059](decisions.md#d-059)) |
| The `mgmt` block is ignored and binds are rejected (from its docs) | `plan` relies on neither. Per-twin management networks are the local driver's alone |
| The controller fetches the image manifest from a registry before creating a pod | The account-gated cEOS image lives in a private registry, pulled through `Topology.spec.imagePull.pullSecrets` with the CA trusted by the controller's config ([D-021](decisions.md#d-021)) |
| The default request is 200m CPU and 512 Mi per node | Requests come from the package's `cpu` and `memory_mb` |
| Each node's Service is `externalTrafficPolicy: Cluster`, with no setting to change it; a patched value is kept across steps, pod replacements and a drain | `apply` patches each Service to `Local`, and `inspect` patches one it finds that is not ([D-037](decisions.md#d-037), [D-057](decisions.md#d-057)) |
| A drain moves a host's nodes to the other hosts as new pods, at the same LoadBalancer addresses | The loop sees each moved node's new incarnation and re-pushes it ([D-036](decisions.md#d-036)) |
| No in-place upgrade from before 0.9; Kubernetes 1.31 or later, VXLAN and nftables required (from its docs) | Pin the clabernetes version in the driver's capabilities, and document the cluster prerequisites |
| containerlab 0.81.0 inside clabernetes (its `go.mod`); the development host moved from 0.79.0 to 0.81.0 on 2026-11-03 | No version skew between the two drivers: the local driver's containerlab is pinned to the version the clabernetes release embeds, so the kinds behave alike. The facts measured on 0.79 stand until phase 4 re-exercises them |

The clabernetes driver is one driver behind the seam ([D-017](decisions.md#d-017)). It is
developed on a three-server k3s cluster, kind having been retired
([D-060](decisions.md#d-060)); the production cluster is three k3s servers with embedded
etcd on SSD ([D-036](decisions.md#d-036)).

### Durability and state

- **The core owns its control loop** ([D-023](decisions.md#d-023)). A twin is a record
  whose desired state is a bundle. A level-triggered reconciler in the core process drives
  it through the driver, phase by phase: compiled, admitted, planned, applied, ready,
  pushed, verified, flows.
  It records each phase before the next begins, so a restarted core resumes from the record.
  - Neither kopf nor CRDs are used, because the local driver has no cluster.
  - Design choice: the Temporal Python SDK was kept as the fallback, should resuming mid-phase
    prove fragile. The conformance suite's kills resumed on both drivers, and it is retired
    ([D-072](decisions.md#d-072)).
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
- **Each node's incarnation** (the container's start time locally, the pod's uid and its
  container's restart count on clabernetes, [D-069](decisions.md#d-069)) is recorded. When
  `inspect` reports a different one, the node was replaced and lost its push: the loop voids
  its `holds` and pushes again.
- **A state-store interface** holds twin records, run records and their events, blueprints
  and bundles, and offers a compare-and-set write on a twin record.
  - `local`: a directory, for development, with each twin's record in its own file. No
    single state root assumes one twin.
  - `object`: S3-compatible storage that honours conditional writes, for production
    (Versity S3 Gateway in development, [D-061](decisions.md#d-061)).
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
  is the twin's changes nothing of the lab: where every device node holds that bundle it ends `ok`
  at `compiled`, `last_step` outcome `unchanged`; where one holds none, as a restore that failed
  leaves one, it readies and pushes that node and runs verify, and ends `ok`, `unchanged`, or
  `failed` when that readiness or push fails, `last_step` then `rejected`
  ([D-070](decisions.md#d-070)). A spec written
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

## Phase 6: the clabernetes driver, and the core as a pod (settled 2026-11-05)

Phase 6 takes the walk phase 5 ends on to Kubernetes. The core runs as a pod on the
three-server k3s cluster; a twin is created there through the API, stepped through the step
fixtures and verified after each step, driven by the thin CLI from a workstation. It is
built against the seam as phase 5 left it, with one call added.

**What the phase is for.** Production runs twins on a cluster, and the core beside them.
Everything so far ran on one host: the core a process there, its store a directory, its
twins containerlab labs. This phase builds the second driver behind the seam, the second
store behind the store interface, and the core's own deployment, and proves the three
together by the same scenarios the local driver passes. It also answers whether the core's
own loop resumes on clabernetes after a kill, which the Temporal fallback has waited on
([D-023](decisions.md#d-023)).

**What is settled before code.**

- **The clabernetes driver** ([D-057](decisions.md#d-057)). A twin is the namespace
  `fylgja-twin-<twin>`, labelled as its own. The allocation holds that namespace and what
  the site decides that `plan` writes: the core's namespace when the core is a pod,
  clabernetes' namespace and the pod CIDR (two settings of the driver), and the image prefix
  of every pull credential the provider holds at admission. So a resumed `plan` renders the
  same files from the record alone, and a step may bring a gated kind. `plan`
  renders the namespace, a NetworkPolicy and a `Topology` wrapping the containerlab YAML the
  local driver's plan renders, less its `mgmt` block and binds; no Secret is a file, and
  `apply` makes each pull secret from the credential provider. `apply` waits within the
  packages' budget until two reads in a row, 2 s apart, find every node's pod and the
  Topology ready (the Topology's first write of a new generation keeps the readiness of the
  one before for a moment), and patches each Service to `Local`
  ([D-037](decisions.md#d-037)); `reconfigure` deletes the twin's pods. `inspect` reads
  pods: a pod's uid and its container's restart count are the node's incarnation
  ([D-069](decisions.md#d-069)), its Service's LoadBalancer address the node's address
  ([D-020](decisions.md#d-020)), and a node runs while its pod is `Running` and its
  container is. `destroy` deletes the namespace and waits for it to go. `exec` runs in the
  node's pod, naming no container. `changes` is pure, written from the recorded facts, and
  **held in the cluster tier to the pods' uids before and after each step fixture**,
  clabernetes having no dry run. A probe host runs as it does locally: its start-up lines
  set its address at every boot, and a change to them replaces its pod. A cEOS port added
  after boot arrives with a new pod, so `apply` deletes that pod once the Topology has taken
  the change, under an annotation a resumed `apply` finishes
  ([verified-facts.md](verified-facts.md)).
- **A twin's policy admits the core's namespace** ([D-059](decisions.md#d-059)). Read on the
  cluster: the policy as [D-019](decisions.md#d-019) wrote it refuses a pod in another
  namespace on every path to a node, and one `namespaceSelector` opens them while a third
  namespace stays refused ([verified-facts.md](verified-facts.md)). The core's namespace
  therefore holds the core and its store, and nothing else.
- **The seam's tenth call, `events`** ([D-058](decisions.md#d-058)): an asynchronous
  iterator of the names of twins whose runtime changed. The local driver follows Docker's
  events for its labs' containers; the clabernetes driver holds one watch on its twins'
  pods. The loop kicks each name. The periodic resync stays, so a missed event is only late
  ([D-023](decisions.md#d-023)).
- **A kick on a settled twin inspects it** ([D-067](decisions.md#d-067)). As built, a pass
  acts only on a deletion or a new generation, so a node the runtime replaced keeps its
  kind's baseline until the twin is stepped. Now a pass on a settled twin inspects it, and a
  node at another incarnation is readied and pushed again, and verify run, which is advisory,
  under a run of a new operation, `restore`, its principal the core's own. A node missing or
  not running is waited for and then reported (`twin.node.missing`), never made: nothing is
  applied, and a twin is not repaired. A refused restore leaves `Ready` False and is not
  repeated.
- **A driver declares whether applying again finishes an apply cut short**
  ([D-068](decisions.md#d-068)). The partial-lab probe and its reconfigure are containerlab's
  remedy. On clabernetes the controller goes on after the core dies, and a resumed core
  would find pods still coming up and delete them, or end a step `diverged`. The capability
  `reapply` is true for clabernetes and false locally; where it is true a resume applies
  again, with no probe.
- **The object store** ([D-061](decisions.md#d-061)). MinIO's open-source edition ended in
  2026, so [D-024](decisions.md#d-024)'s development store is replaced. The `object` store
  speaks S3 to any endpoint that honours conditional writes, with four calls signed by the
  core over httpx: `If-None-Match: *` creates, `If-Match` at the ETag read replaces and
  deletes, a run's event is one object created under its sequence number, and a document is
  written after its files and read before them. **The store proves its endpoint at start**
  and refuses one that accepts a write it should not. In development the endpoint is
  Versity S3 Gateway, one pod over a volume in the core's namespace, its conditions read
  under 32-way races ([verified-facts.md](verified-facts.md)). `FYLGJA_STORE` is a directory
  or `s3://<bucket>[/<prefix>]`.
- **The core on the cluster** ([D-062](decisions.md#d-062)): one pod in the namespace
  `fylgja`, under a Lease it takes before the loop starts and exits on losing; credentials
  as `FYLGJA_*` variables from Secrets ([D-042](decisions.md#d-042)); one ClusterRole; a
  kustomize base under `deploy/` that holds no address and no value, with the site's overlay
  under `local/`; and an image built from a `Dockerfile` in the tree, pushed to the private
  registry as the gated image was. The server refuses an `s3://` store without a Lease.
- **TLS ends at the server** ([D-063](decisions.md#d-063)): a LoadBalancer Service, the
  certificate and key named by two variables, and a CA the client names by a third. No
  ingress.
- **Libraries** ([D-064](decisions.md#d-064)): lightkube 1.0.1 for every Kubernetes call,
  imported by the clabernetes driver and the Lease alone; no S3 library. What the driver
  relies on in it was read against the cluster ([verified-facts.md](verified-facts.md)).
- **The cluster** ([D-060](decisions.md#d-060)): the driver is developed and its conformance
  suite run on the three-server k3s cluster; kind is retired. The pure tier covers the
  driver's `plan` and `changes` by fixtures and its acting calls over a fake of the
  Kubernetes API, so no change to the core needs a cluster.
- **The three leftovers that need no cluster.** The formats ship inside the package, built
  from `formats/`, so the server and the client validate wherever they are installed
  ([D-066](decisions.md#d-066)). Every command the local driver runs gets an environment
  from an allow-list ([D-065](decisions.md#d-065)). The CLI's watches reconnect when the
  server ends a stream before its end, resuming from the last revision or event seen, which
  the server already honours.
- **The conformance suite is one set of scenarios and two harnesses.** Phase 4's and
  phase 5's end-to-end scenarios (create, show, step through every step fixture with verify
  after each, destroy; the core killed at every phase boundary of a create and of a step,
  during an apply and during a destroy; a step cancelled mid-apply) are written once. A
  harness per driver says how to start the core, kill it (a signal locally, the pod's
  deletion on the cluster), replace a node behind its back, and look for leftovers. A
  scenario reads what a step should do from the driver's `changes` and never from a
  driver's name. The cluster's run adds isolation over TCP between two twins
  ([D-059](decisions.md#d-059)) and the two open questions it was left: the SR Linux marker
  after a pod replacement, and the resume after a kill
  ([open questions](decisions.md#open-questions)). Five twins at once are phase 7's.
- **Formats touched**, each in the change that builds it: deployment 1 and twin record 1
  (the clabernetes allocation's members; the files, which name no Secret; `holds` absent for a
  node a restore found replaced and has not pushed), API 1 (a run's operation gains `restore`,
  and a driver's capabilities `reapply`), findings 1 (a verdict's `operation` gains `restore`,
  since a run's verdict names its run's operation, [D-070](decisions.md#d-070)), the server's
  and the client's settings (`.env.example`, `FYLGJA_RESYNC_S` among them), and the rule
  catalogue (`admission.namespace.taken`, `twin.restoring`, `twin.node.missing`, and the rule
  an endpoint that fails the store's proof is refused with).
- **Logging** stays as phase 4 set it; on the cluster the stream is the pod's log. No
  credential reaches a line, a manifest in the tree, an image layer or a Topology.

**Non-goals.** Several twins at once, admission by capacity and scheduling at the packages'
requests (phase 7); a store or a core that survives its host's drain; an ingress, OIDC or
roles; a Helm chart; a published image; the flows beyond one burst a probe; the eAPI session
sweep; the repair of a twin whose node is gone; the `hardware` driver. A core run off the cluster against it serves the driver's own
live tests, and is not a deployment this phase delivers. **Anti-goals**, each a failure even
if the code works: a node of one twin reachable from another twin's pod; a credential in a
file of the tree, a stored deployment, an image or a log line; two cores reconciling one
store; a store that starts against an endpoint that ignores a condition; a host name or an
address in the tree; anything above the seam naming a runtime; a scenario that passes on one
driver by branching on its name.

**Seven plans, each a branch and a pull request useful on its own, in this order:**

1. **The leftovers that need no cluster** ([D-065](decisions.md#d-065),
   [D-066](decisions.md#d-066)): the formats in the package, with the test that installs the
   wheel outside the tree; the local driver's allow-listed environment, read on containerlab
   0.81.0; the CLI's watch reconnect.
2. **The object store** ([D-061](decisions.md#d-061)): the signer and its known answers, the
   store, its proof at start, its settings; pure tests over a fake endpoint, and a live test
   against Versity under Docker.
3. **The clabernetes driver's pure half** ([D-057](decisions.md#d-057),
   [D-059](decisions.md#d-059)): the allocation, `capabilities`, `plan` sharing the local
   driver's render, `changes`; the golden deployments for every fixture; the two formats'
   descriptions.
4. **The driver's live half** ([D-057](decisions.md#d-057), [D-064](decisions.md#d-064)):
   `admit`, `apply`, `inspect`, `destroy`, `endpoints` and `exec` over lightkube, a pull
   secret from the credential provider, run against the cluster from the development host;
   the registry's second name; `changes` held to the pods' uids for every step fixture; each
   behaviour recorded for clabernetes 0.10.1 on k3s v1.37.1.
5. **The trigger and the restore** ([D-058](decisions.md#d-058),
   [D-067](decisions.md#d-067), [D-068](decisions.md#d-068)): `events` on the seam and its
   fake, the loop's task, Docker's events locally and the pod watch on the cluster; the pass
   on a settled twin and the `restore` run; the `reapply` capability and the resume it
   changes; a live test on each driver that replaces a node behind the core's back. **Built**
   as [D-070](decisions.md#d-070) records: `events` and both drivers' sources, the loop's task
   and `FYLGJA_RESYNC_S`; the settled pass, the `restore` run and each absent node's boot
   window; a step to the twin's own bundle that pushes what holds nothing; `reapply` and the
   resume it changes; on clabernetes, a pod whose container ended in it deleted by the driver,
   at most three times in ten minutes a node, so that the cluster makes the node anew; and a
   module in the live tier and one in the cluster tier that replace nodes behind the core's
   back, with the resync an hour away.
6. **The core as a pod** ([D-062](decisions.md#d-062), [D-063](decisions.md#d-063)): the
   Lease, the TLS settings and the client's CA, the `Dockerfile` and `make image`, the
   kustomize base with Versity, the role's rules read from inside a pod, and the core
   deployed: `twin create`, `show` and `destroy` through its LoadBalancer address.
7. **The conformance suite**: the scenarios written once over the two harnesses, run on the
   local driver and on the cluster. It closes the phase.

Plans 1, 2 and 3 are independent of each other; 4 follows 3; 5 follows 4; 6 follows 2 and 4;
7 closes. The cluster's scenarios run one plan at a time, and never while the local live
tier boots labs, since here the two share a hypervisor.

**The phase is done** when the conformance suite passes on both drivers; on the cluster a
fixture twin is created through the API over TLS by the CLI from a workstation, stepped
through every step fixture with `twin verify` after each and the burst held, and destroyed
leaving nothing by its label; the core's pod killed at each phase boundary of a create and
of a step, during an apply and during a destroy, resumes to the desired state or ends
`diverged` as designed; a node replaced behind the core's back is restored without waiting
for the resync; and every behaviour the driver, the Lease and the store rely on is
recorded for the versions they run on.

**Left to the builder.** The module layout (`fylgja_core.clabernetes`,
`fylgja_core.object_store`, `fylgja_core.lease`, or otherwise) and `deploy/`'s; how the
build copies `formats/`; the environment's allow-list; the object keys beyond the rules
above; which pod changes `events` drops; the watch reconnect's backoff and when it gives up;
the pod's probes, which add no route to API 1; the role's exact rules; what a missing binary
answers through `exec`; the wording of each new refusal; and how the conformance harness is
parametrised.

## Phase 7: many twins (settled 2026-11-08)

Phase 7 runs several twins at once on each driver: three on the development host, five on
the three-server cluster. The orchestrator is the client that makes it so, one twin per open
proposed change, and the core's part is to admit what fits, refuse what does not with a
reason, and keep each twin's runs honest while the others run. It is built against the seam
as phase 6 left it, with one call added.

**What the phase is for.** The requirement is about five concurrent twins of tens of nodes
on a 2–3-node cluster. The loop was built for it: a queue keyed by twin, a bounded pool of
workers, one run a twin ([D-023](decisions.md#d-023)). What has never been exercised is the
rest. An admission that knows how much room the runtime has, so that a sixth twin is refused
in a second rather than scheduled into pods that never start; and the places five twins
share inside one core, gNMI's read threads, the node HTTP client, the step's and the
deploys' waits, and containerlab's post-deploy on one host, so that a verdict never says a
twin is wrong when the core was merely busy. The phase settles the first, builds the second,
and proves both with one scenario of the conformance suite, run on each driver.

**What is settled before code.**

- **Capacity is read from the runtime, never a budget the site declares**
  ([D-073](decisions.md#d-073)). At `admit` the driver reads the runtime: on clabernetes each
  host's allocatable CPU and memory less the effective request of every pod on it that has
  not ended, as the scheduler computes it ([D-077](decisions.md#d-077)), whoever owns the pod (clabernetes' and k3s's own
  pods, the core's, anything else the cluster runs), read on 2026-11-08
  ([verified-facts.md](verified-facts.md)); locally the kernel's available memory and the
  CPU count. Off that reading comes the **pending** demand: for each twin already
  admitted, its recorded demand less what the runtime already holds for it (its pods'
  requests on the cluster; locally nothing once every container of its lab runs, since the
  kernel's figure counts them, though a node grows for about a minute after it starts and
  that minute is uncounted, one twin at a time under the deploy lock), floored at zero, so that five twins admitted in one second do not
  each see the same free room. A twin **fits** when its demand fits the free sum less the
  pending demand, CPU and memory each, and each of its nodes fits the roomiest host; the
  scheduler places exactly, and admission only keeps the core from asking for what cannot
  be placed. A step is admitted on the demand it adds over the deployment the twin holds
  ([D-049](decisions.md#d-049)), as before, and on its sum alone
  ([D-077](decisions.md#d-077)). The refusal, `admission.capacity`, names each
  shortfall: what the twin needs, what the reading found free and pending, or the node no
  host can take. Nothing is queued: a twin that does not fit ends `rejected`, and the
  orchestrator asks again.
- **The allocation records the demand** ([D-073](decisions.md#d-073)). `admit` writes
  `demand` (nodes, CPU, memory) into the allocation beside the driver's own members, on both
  drivers, and a step's admission answers the allocation the twin holds with `demand`
  refreshed to the target's, which the loop now records at `admitted` for a step as it does
  for a create (today it drops a step's answer). So the pending demand is read from the twin
  records the loop already hands `admit`, and no store call is added. A step refused or
  cancelled before `applied` leaves the target's demand recorded while the twin runs the old
  deployment: the pending sum then over-counts that twin, by at most its own demand, until
  its next step. Conservative, and accepted.
- **The seam's eleventh call, `capacity`** ([D-073](decisions.md#d-073)): the reading above,
  as `admit` would take it now, with every admitted twin's pending demand; `admit` is written
  over it. The clabernetes reading lists the cluster's nodes and every pod through the Kube
  protocol, and the core's ClusterRole gains the rule for nodes; the local reading is two
  kernel files, the CPU count and one `docker ps` by label.
- **A client may look before it asks** ([D-076](decisions.md#d-076)). `GET /v1/capacity`
  answers the running driver's reading: each host's total and free CPU and memory, the
  pending demand and the count of twins admitted, with when it was read. The CLI shows it as
  `fylgja-core capacity show` ([D-079](decisions.md#d-079)). A dry run of the twin stays the way to ask whether this twin fits:
  its 422 carries the shortfall the create would.
- **Contention becomes waiting, never a verdict** ([D-075](decisions.md#d-075)). The sixteen
  gNMI read threads stop being one process-wide pool five twins race for: each twin's verify
  has a share of its own, the claim of one read per address staying global, so a node is
  reported unread only when it did not answer within its budget, never because another twin
  held the threads. Where a twin's own share still runs out, the node stays
  `verify.node.unread` and the verdict `failed`, as [D-051](decisions.md#d-051) has it, and
  the orchestrator asks again: the core does not wait past the budget. The push and the
  readiness wait each make a node HTTP client of their own per call, so no shared limit
  binds them; what five twins pushing together do to the host's connections is read and
  recorded, and nothing is bound unless the reading shows a need: it was read for three twins
  on the local run, and nothing is bound ([D-078](decisions.md#d-078)). The worker pool's default
  rises from four to eight, so that five twins
  created together each hold a worker through an apply with room beside. The step's wait and
  the deploys' budgets are measured on the many-twins run and widened where it shows them
  short, each a fact; none is shortened. None was short, and none was widened
  ([D-078](decisions.md#d-078)).
- **The local driver deploys one lab at a time** ([D-074](decisions.md#d-074)). Two labs
  deploy together without harm ([verified-facts.md](verified-facts.md), "Two labs at once"),
  and two live tiers booting eight SR Linux nodes between them took the host to a load of
  about 33 and crashed `sr_cli` in containerlab's post-deploy
  ([verified-facts.md](verified-facts.md), "Under memory pressure its own `sr_cli` can
  segfault", the 2026-11-03 reading). Admission
  still admits as many as fit, and every other phase runs beside, but `containerlab deploy`
  runs under one lock in the driver, its wait for the lock outside the deploy's budget, so
  a third twin's nodes boot after the second's. Destroys are not held: a destroy during
  another twin's deploy is what [D-055](decisions.md#d-055) already handles; the one deploy a
  destroy makes, of a twin with residue and no lab, is an apply and takes the lock
  ([D-077](decisions.md#d-077)). On clabernetes
  the scheduler spreads the boots over the hosts, and nothing is held.
- **Scheduling at the packages' requests** is exercised, not changed: `plan` already writes
  every node's requests into the Topology ([verified-facts.md](verified-facts.md), "The
  Topology's requests are by node name"), and the many-twins scenario records where the
  cluster placed fifteen pods at 0.5 CPU and 1.5–2 GiB each, which closes the open question
  the multi-host stage left ([open questions](decisions.md#open-questions)). Requests alone,
  never limits.
- **The many-twins scenario** joins the conformance suite, written once over both harnesses:
  the harness's count of twins created together (three locally, five on the cluster, from
  the `three-node` and `mixed` fixtures), each stepped once and verified while the others
  run, each step's final verdict and the suite's settled `twin verify` free of
  `verify.node.unread` (the suite's 30 s tolerance for a Service without its endpoint after
  a step stays, being the cluster's and not contention's); the capacity read before, during
  and after, agreeing with the refusal in its hosts and in its sign (free less pending below
  the refused twin's demand), never to the unit, since pods start between two readings; one
  twin that does not fit, refused at admission with the shortfall named, and its dry run
  refused alike; every twin destroyed, leaving nothing by its label.
- **Formats touched**, each in the change that builds it: deployment 1 and twin record 1
  (the allocation's `demand` member, on both drivers), API 1 (`GET /v1/capacity` and its
  schema), the server's settings (`FYLGJA_WORKERS`'s default), and the rule catalogue
  (`admission.capacity` filed by both drivers, with each shortfall it names). The
  deployment's `demand` keeps its three sums: the per-node figures live in the rendered
  Topology and in the packages the fit rule reads, which answers the open question in
  [formats/README.md](../formats/README.md#still-open).
- **Logging** stays as phase 4 set it. A refusal's log line carries the shortfall, and names
  no host beyond what the runtime calls it.

**Non-goals.** A queue or a priority among twins waiting for room; preemption; a declared
capacity budget or a quota a setting sets; scheduling constraints beyond requests (affinity,
spread, taints); limits on a pod; disk, ephemeral storage, image bandwidth or LoadBalancer
addresses as capacity; the orchestrator's own retry policy (phase 8); a core or a store that
survives its host's drain; the Lease's open questions; the flows beyond one burst; the
`hardware` driver's capacity. **Anti-goals**, each a failure even if the code works: a
verdict that says a twin is wrong when the core was busy; a twin held inside the core
waiting for room; an admission that counts twins and not the cluster's other pods; a refusal
whose numbers the capacity read would not show; a scenario that passes on one driver by
branching on its name; a host name or an address in the tree.

**Four plans, each a branch and a pull request useful on its own, in this order:**

1. **Capacity behind the seam** ([D-073](decisions.md#d-073)): the pure fit rule (a reading,
   a demand, the shortfalls), the allocation's `demand` and a step's refresh of it, the
   seam's `capacity` and `admit` over it on both drivers, the local reading and the
   clabernetes reading over the Kube protocol and its fake, the ClusterRole's rule for
   nodes; the two formats' descriptions and the rule catalogue; pure tests over readings
   taken from the cluster on 2026-11-08, and a cluster-tier test that reads the live cluster
   and agrees with `kubectl describe node`.
2. **The capacity read on API 1** ([D-076](decisions.md#d-076)): the route and its schema,
   the client and `fylgja-core capacity show`; the pure API tests; the dry run's 422 carrying the
   shortfall.
3. **Under load** ([D-074](decisions.md#d-074), [D-075](decisions.md#d-075)): the read
   threads a twin's own, `FYLGJA_WORKERS`'s default, and the local driver's one deploy at a
   time; pure tests of each; a live test of three labs created together locally, their
   host's load read and recorded. That test pushes nothing, so the connections were read in
   plan 4 ([D-078](decisions.md#d-078)).
4. **The many-twins scenario** in the conformance suite, run on the local driver and on the
   cluster: the count from the harness, the fixture that does not fit, the placement read on
   the cluster, and the waits measured and widened where needed, each a fact (none was). It
   closes the phase.

Plans 1 and 3 are independent of each other; 2 follows 1; 4 follows all. Live runs are one at
a time: plan 3's live test and plan 4's two runs never share the hypervisor.

**The phase is done** when the conformance suite, with the many-twins scenario, passes on
both drivers: on the cluster five twins created together all reach Ready, each is stepped
once and verified while the others run with no node unread, a twin that does not fit is
refused at admission with the shortfall named and the capacity read agrees with it in its
hosts and its sign, and all five are destroyed leaving nothing by their labels; locally three twins the same; and every
behaviour the reading, the threads, the lock and the waits rely on is recorded for the
versions they run on.

**Left to the builder.** The module layout (`fylgja_core.capacity`, or otherwise); the
capacity document's exact members within the rule above; the per-twin thread count and how
an idle twin's share is dropped; where the local deploy lock lives and what a resume's deploy
does under it; the fixture that does not fit (a bundle of many nodes, or a node no host can
take) and how the harness gives the count; the exact Kube calls and the fake's shape; the
wording of each refusal; and which waits the measurements widen.

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
   deploy runs to completion ([D-056](decisions.md#d-056)). It left to phase 6 the trigger
   that replaces the periodic resync, the CLI's watch reconnect and `schemas.formats_dir()`
   (item 6), and to later phases the flows beyond one burst per probe and the eAPI session
   sweep.
6. **The clabernetes driver**: the object store, the Lease, per-twin namespaces and node
   access. The driver conformance suite passes on both drivers. *Settled on 2026-11-05*; see
   "Phase 6". It takes up, from phases 4 and 5:
   - `formats/` shipped with the package, so the server and the client run installed outside
     the tree: the wheel carries the schemas and the OpenAPI document, and `schemas.formats_dir()`
     reads them from the installed package ([D-066](decisions.md#d-066));
   - the CLI's reconnect of a watch the server ends early, the server being remote for the
     first time;
   - the trigger that replaces the periodic resync, its shape decided with a pod watch in
     view beside the Docker events the local driver would use;
   - an allow-listed environment for every command the local driver runs
     ([D-065](decisions.md#d-065)). Each inherited the server's until phase 6, node
     credentials included; no deploy output read then held any
     ([verified-facts.md](verified-facts.md)), and the allow-list removes the question.

   Built, in the seven plans of "Phase 6": the formats in the package, the local driver's
   allow-listed environment and the CLI's reconnect; the object store; the clabernetes driver, its
   pure half and its live calls ([D-069](decisions.md#d-069)); the trigger and the restore
   ([D-070](decisions.md#d-070)); the core as a pod under its Lease, behind TLS
   ([D-071](decisions.md#d-071)); and the driver conformance suite, which passed on both drivers:
   on 2026-11-07 but for the cluster's cEOS scenarios, failed by a site whose deployed core held no
   EOS login, and those four on 2026-11-08 once the login was applied ("Verification"). *Done on
   2026-11-08*: the maintainer's own walk on the development cluster passed end to end, a twin
   created over TLS by the CLI from a workstation, stepped through every step fixture with
   `twin verify` after each, and destroyed, then a twin from `mixed` given its cEOS port, by the
   commands in [CONTRIBUTING.md](../CONTRIBUTING.md#running-the-core-on-a-cluster).
7. **Many twins**: concurrent create and step, and admission refused when capacity runs out.
   Several labs on the development host locally, and five twins on a 2–3-node cluster.
   *Settled on 2026-11-08*; see "Phase 7". Built, in its four plans: admission by the
   runtime's room on both drivers, the allocation's demand and the seam's eleventh call
   ([D-073](decisions.md#d-073), [D-077](decisions.md#d-077)); `GET /v1/capacity` and
   `fylgja-core capacity show` ([D-076](decisions.md#d-076), [D-079](decisions.md#d-079)); the
   read threads a twin's own, eight workers and the local driver's one deploy at a time
   ([D-074](decisions.md#d-074), [D-075](decisions.md#d-075)); and the many-twins scenario of
   the conformance suite. *Done on 2026-11-09*: the suite passed whole on both drivers with
   that scenario, three twins created, stepped and verified together locally and five on the
   cluster, their fifteen pods five a host, with no node unread and no wait expired, a twin
   of forty nodes refused with its shortfall and the capacity read agreeing, and nothing left
   ([verified-facts.md](verified-facts.md), "Three twins at once through the core" and "Five
   twins at once through the core"). No wait or budget was widened and no bound was set on
   the node clients ([D-078](decisions.md#d-078)). It left to later phases: a drain at the
   packages' requests; the node clients' connections for five twins on the cluster and for
   twins of tens of nodes; the refused twin's size read from the runtime and not fixed at
   forty nodes ([open questions](decisions.md#open-questions)); and the orchestrator's use of
   the capacity read and of `admission.capacity` as "ask again", which is phase 8's.
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
- **Driver conformance suite** (`core/tests/conformance/`): one set of scenarios, written once
  over a harness per driver, run on each driver's own runtime. It holds a twin created and shown;
  stepped through every step fixture with verify after each and the burst held, and the step's
  refusals; the core killed at each phase boundary of a create and of a step, during an apply and
  during a destroy, a waiting CLI riding through, a deletion after a kill, and a step cancelled; a
  node replaced behind the core and restored without the resync, and one stopped, reported missing
  and never made; leftovers read at each destroy and at the session's end, on the cluster by the
  twin's label; node access, each node read through its own transport at its recorded address;
  and isolation over TCP between two twins and from a third namespace, where the driver declares
  it. Locally twins are kept apart by names, so the isolation scenario skips; on clabernetes a
  stopped node is not expressible, clabernetes 0.10.1 scaling a node's Deployment back to one
  within 1.3 s, so that scenario skips. It passed on both drivers: on 2026-11-07, 48 tests and a
  skip locally and 44 and a skip on the cluster, where the four cEOS scenarios failed on the site,
  the deployed core holding no EOS login; and those four on 2026-11-08, 22 of the steps module
  passing once the login was applied ([verified-facts.md](verified-facts.md)). The clabernetes
  run needs a 2–3-node cluster. Phase 7 added many twins at once (`test_many.py`): the harness's
  count, three locally and five on the cluster, created together and all Ready; each stepped
  while the others run, every step's verdict and the verify after it with no node unread and no
  wait expired; the capacity read before, during and after; a twin of forty nodes refused in a
  dry run and at its create with the shortfall named, the capacity read agreeing in its hosts and
  its sign; and every twin destroyed, leaving nothing. With it the suite passed on both drivers on
  2026-11-09, 53 tests and a skip on each ([verified-facts.md](verified-facts.md)).
- **Resumption**: kill the core mid-phase on each driver; the twin reaches its desired state
  or is cleaned up. The suite's kill scenarios do so on both drivers, where the kill found the
  run unfinished ([D-072](decisions.md#d-072) names the two boundaries it did not on the
  cluster).
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
| Steps across hosts | As on kind: default modes replace the cEOS pods (136–138 s); switching every node to `live` replaces every pod; `live` replaces none (25 s) | [D-015](decisions.md#d-015) |
| Node access over the LAN | **Refused for some nodes** by the twin's NetworkPolicy, until each Service was set to `externalTrafficPolicy: Local` | [D-037](decisions.md#d-037) |
| Isolation | Holds over TCP. Ping is no test: k3s's policy controller accepts ICMP echo into every pod | [D-019](decisions.md#d-019), [D-037](decisions.md#d-037) |
| Five twins | Three created at once were Ready in 89–119 s with the images present. 15 nodes, 15 addresses; every node's push transport, SSH and gNMI answered | — |
| Use | About 6.8 cores and 23 GiB for the five twins. Per node: SR Linux 0.35–0.5 core and 1.6 GiB, cEOS 0.2–0.45 core and 0.9 GiB. The packages' `cpu` is now 0.5 | [D-015](decisions.md#d-015) |
| Drain | One host drained in 6 s; every twin Ready again in 94–114 s on the other two, at the same addresses, its moved nodes new pods. Nothing moved back after the uncordon | [D-036](decisions.md#d-036) |
| Teardown | 13–14 s for an SR Linux twin, 46–48 s for a mixed one; nothing left by label | [D-019](decisions.md#d-019) |

The twins ran on clabernetes' default requests (200m CPU, 512 Mi), not the packages'. The
packages' `cpu: 0.5` is set from what the nodes used. The scheduler placed twins at the
packages' requests on 2026-11-09, phase 7's five twins of fifteen pods five a host
([verified-facts.md](verified-facts.md), "Five twins at once through the core"); a drain at
those requests is still to be read ([open questions](decisions.md#open-questions)).

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
  at once, and one more for the core's Service;
- open: TCP 6443 and 10250, TCP 2379–2380 (etcd between servers), UDP 8472 (flannel),
  UDP 14789–14790 and TCP 14791 (clabernetes).

And beside them, the private registry on a host outside the cluster, which is never drained
with it.

On the cluster, the storage class `local-path`, for the store's volume
([D-061](decisions.md#d-061)).

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
- **The core's own reconcile loop.** Under the conformance suite's kills, resuming held on both
  drivers during an apply and a destroy, and at every phase boundary of a create and of a step
  where the kill found the run unfinished: every one but a step's `verified` locally, and on the
  cluster every one but that and a create's `pushed`, where the kill found the run ended. Temporal
  is no longer the fallback ([D-072](decisions.md#d-072)). The suite's kill scenarios are the
  guard, and a kill the loop does not survive is a design document first.
- **Two drivers drifting apart.** The conformance suite is the guard, and so is the rule
  that nothing above the seam names a runtime. Pin containerlab to the version clabernetes
  embeds.
- **A seam shaped by containers alone.** Hardware claims rather than creates. The paper
  `hardware` driver above checks the seam before it sets.
- **An unexplained reading, not seen again.** An SR Linux marker was once read as present after
  its pod was replaced by a link-mode switch. The conformance suite read it absent after each of
  three pod replacements on the cluster, each the pod's deletion; the link-mode switch itself was
  not repeated. A replaced pod boots the kind's baseline, as [D-048](decisions.md#d-048) and
  [D-023](decisions.md#d-023) assume ([verified-facts.md](verified-facts.md)). Nothing relies on a
  replaced node keeping its push.
- **etcd's disks.** On spinning disks, etcd lost its leader under parallel image pulls.
  Production needs SSD; relaxed timings are only a fallback ([D-036](decisions.md#d-036)).
- **A store on one host.** Development's object store is one pod over a volume bound to a
  host, so a drain of that host stops the core's writes until it returns
  ([D-061](decisions.md#d-061)). Production points the core at replicated S3 storage.
- **lightkube** has one maintainer and a 1.0 three months old. REST over httpx is the
  fallback ([D-064](decisions.md#d-064)).
- **The Services' traffic policy is a patch.** clabernetes has no setting for
  `externalTrafficPolicy`, so the driver patches it and watches for drift
  ([D-037](decisions.md#d-037)). Worth asking upstream for a field.
