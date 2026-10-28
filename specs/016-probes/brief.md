# Specify brief: 0.3 spec 4 of 5: probes (F-014)

This is what `/speckit-specify` reads for roadmap F-014, the fourth spec of
[Release 0.3](../../docs/roadmap.md#release-03). It was written on 2026-10-28, while 019
ran its live tiers under [D-062](../../docs/decisions.md#d-062), accepted the same day,
and replaces the brief written on 2026-10-16 for Release 0.2, which three features had
overtaken: 017 removed the addresses it read intent's side of a probe from, 018 made the
snapshot the core's one input and reserved the probe slot in it, and 019 froze a twin at
its snapshot. What the old brief decided and the roadmap kept is under
[Decided](#decided); what it decided and the roadmap overturned on 2026-10-25 is named
there too. **A probe is the first input to the core that is not intent**: a declaration
the operator writes beside intent, carried in the snapshot, compiled into synthesized
hosts, and measured across a step. The session verified nothing live; the plan verifies
each point before relying on it. Re-read against 019's close on 2026-10-28, at
feature-open, where the operator settled its four open questions. Specify
what the operator gets, not a new design.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/016-probes GIT_BRANCH_NAME=016-probes. 0.3, the fourth of its five specs: probes, ping only, as docs/roadmap.md's F-014 and Release 0.3 section define it. Read specs/016-probes/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. It names a new Infrahub kind, so load the infrahub-managing-schemas skill before naming it. Specify what the operator gets, not a new design.
```

## Why

- **The slot is reserved and empty.** A snapshot `1` carries `probes`, a list required and
  empty, "this intent, with no probe declarations" ([D-061](../../docs/decisions.md#d-061);
  [snapshot.schema.json](../../contracts/snapshot.schema.json)), and the store refuses a
  non-empty one as `snapshot.invalid`. 018 left the element and the version bump to this
  feature, with no change to how a snapshot is taken, stored or handed to a workflow.
- **The ground is now still.** Since 019 a twin changes only when the operator steps it
  ([D-062](../../docs/decisions.md#d-062)), so loss across a step is the step's and nothing
  else's. 019 was placed before this feature for that reason.
- **It is the headline demo and a seam the production shape needs.** The roadmap's
  [F-014](../../docs/roadmap.md#f-014) names loss during a change on a running twin as the
  demo, and the [production shape](../../docs/roadmap.md#the-production-shape) names a
  declaration outside intent as the third thing 0.3 proves of the core: an input the
  orchestrator writes, that no source of truth owns.
- **The CTM already makes room.** [Architecture §4.2](../../docs/architecture.md#42-canonical-topology-model-ctm)
  justifies the CTM partly by synthesized nodes, provenance `synthesized` is in the
  model ([ctm.schema.json](../../contracts/ctm.schema.json)) and nothing is `synthesized`
  yet. Constitution X demands every synthesized node in the fidelity manifest, and the
  Constitution Check's gate says a synthesized node is added to the CTM.

## Where the shape is fixed

- **The roadmap's [F-014](../../docs/roadmap.md#f-014)**, re-shaped on 2026-10-25 with
  the operator, its table row and its bullet under
  [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs): `ping`
  only and no other synthesized node type; the declaration a file first, one input to the
  snapshot, and the Infrahub kind one source of that file; the declaration carrying the
  host's address and its gateway, since the CTM carries no address. This brief differs
  from the F-014 paragraph in one place, owed back to it by the chain
  ([What changes](#what-changes) item 12): the paragraph's
  first generator runs "ping and iperf3", and the re-shape below it says `ping` only;
  the re-shape wins.
- **[018's hand-off](../018-snapshots/brief.md#hand-off)**: the probe set is part of the
  snapshot, not a second input to the compile; `twin compile` does not take it as a file;
  it is hashed by the snapshot id and reaches the bundle through the synthesized nodes
  and the manifest; `intent read` gains the way to put a declaration file into the
  snapshot. **[019's hand-off](../019-following-removed/brief.md#hand-off)**: loss across a
  step is the step's, and 018's one question for this feature is answered under
  [Decided](#decided): one probe list per request.
- **[D-057](../../docs/decisions.md#d-057)**: the CTM is the contract and a reader maps one
  source onto it, reading nothing the mapping does not name. The Infrahub reader does not
  read `ip_addresses`, and this feature does not make it: the device side of a probe is
  rendered by Infrahub, never read by Fylgja. CTM `2` does not move.
- **[D-061](../../docs/decisions.md#d-061)**: the snapshot wraps the CTM unchanged, with
  `probes` beside it; its id hashes the probe list. **[D-062](../../docs/decisions.md#d-062)**:
  a twin is frozen at its snapshot, and `twin step` takes it to a stage or to a snapshot.
- **[D-045](../../docs/decisions.md#d-045)'s pattern** for the kind: Fylgja-owned,
  branch-agnostic, loaded on `main` beside the stage kind, written by the operator and only
  read by Fylgja ([schema/fylgja-stage.yaml](../../schema/fylgja-stage.yaml) is the
  template). [D-032](../../docs/decisions.md#d-032), which the old brief cited, is
  superseded by D-045 and the pattern is D-045's now.
- **[D-031](../../docs/decisions.md#d-031)**: a mechanism is code keyed by a format value,
  and no code branches on what a platform is. A probe generator is a mechanism, so it is
  reached by a format value in a package, never by a platform branch; and
  `TestCompilerNamesNoPlatform` must still pass with a `linux` node in the compiler.
- **[D-038](../../docs/decisions.md#d-038)**: verify's assertions are
  `verify.Derive(manifest)`, data derived from the staged bundle, and its consequences
  name probes as an assertion kind to add under that entry. [D-039](../../docs/decisions.md#d-039):
  verify is advisory, and 015's gate reads it through the rehearsal's verdict.
- **[D-028](../../docs/decisions.md#d-028)** and Constitution IV: Infrahub renders every
  device's configuration. Fylgja configures only what it synthesizes.
- **[D-022](../../docs/decisions.md#d-022)** and **[D-023](../../docs/decisions.md#d-023)**:
  every bundle carries a fidelity manifest, and the bundle hashes everything it was built
  from and nothing about the read.
- **[Constitution 2.2.0](../../.specify/memory/constitution.md)**: II, platforms are data;
  III, the CTM is the contract; IV, no rendering; V, the compiler is pure; VI, intent is
  addressed, and from 2.2.0 a snapshot's id addresses it; IX, the manifest is the
  provenance of what runs; X, honesty: container forwarding is not an ASIC's, and every
  surface that reports loss says so. The Check's gate blesses the CTM "a synthesized node
  is added to" and the PSP abstraction; whether a probe package is a fourth blessed layer
  is the plan's ([Left to the plan](#left-to-the-plan)).

<a id="what-changes"></a>
## What changes, and nothing else

1. **The probe declaration**, a document of its own with a contract and a version.
   - Each probe has a name, a format (`ping`), and two endpoints. An endpoint names a
     device, one of its interfaces, the address its host takes with its prefix length,
     and its gateway, the device interface's address. Nothing about the device side but
     the two names: the interface's own address is intent's, rendered by Infrahub.
   - The declaration lives in a file the operator writes
     (`contracts/probes.schema.json`), and in Infrahub as `FylgjaProbe`, one object per
     probe, the file's shape as attributes. A read of the kind yields the file's content.
     The kind is one source of the declaration, not the declaration.
2. **The snapshot carries it: snapshot `2`.** `probes` is the list of declarations, each
   element the contract's, empty when none were given. Hashed into the id as today. How a
   snapshot is taken, stored and handed to a workflow does not change; whether a `1` on
   disk is still read, as a `2` with no probes, or refused as D-061 refuses another
   version, is the plan's.
3. **How the probes reach a take.** `intent read --out`, `twin create --branch` and
   `--stage`, `twin step --stage`, `stage plan` and the rehearsal's takes gain
   `--probes <file>`; with no file, the probes read from `FylgjaProbe` on `main`,
   unpinned, as stages are; with neither, none. `twin create --snapshot` and `twin step
   --snapshot` take whatever the snapshot carries and no flag. A request reads its list
   once, and every snapshot it takes carries it ([Decided](#decided)).
4. **Synthesized hosts, in the compile.** Each endpoint becomes a containerlab `linux`
   node, its address set and a route via the gateway, on a synthesized link to the device
   interface. Node, link and the port it takes carry provenance `synthesized` and are in
   the manifest. The compiler refuses, at the compile and so at `fylgja-step` for a stage,
   a probe whose device is not in the snapshot, whose interface the device lacks or
   intent cables, or whose interface is `mgmt_only`; a probe that takes a port a lossy
   package would have shared is recorded under `fidelity.lossy` as a shared port is. The
   refusal of a host address outside the interface's prefix is lost, since the CTM holds
   no address. Bundle `5` moves to `6`: a host node has no package, no artifact and no
   bootstrap, and the manifest says what it is instead.
5. **A probe package format**, `ping` the first, beside the PSP and in its pattern: a
   format value, the image and its acquisition, the mechanism (the flow's command, how its
   counters are read, how the burst is run), its resources and timeouts, validated by a
   schema at load and embedded as the PSPs are. iperf3 and Ixia-c ([F-020](../../docs/roadmap.md#f-020))
   are later formats of the same declaration and are not built. The host check refuses a
   run whose probe image is absent as it refuses a platform's.
6. **Transient loss, the step's measurement.** The step starts every flow before its
   first change and reads each after the wait: packets sent and lost and the longest gap,
   per probe, in the step record and in `twin step`'s document, labelled container
   timing. Never asserted. The worker gains the activities that start and read a flow,
   and D-062's count of activities moves.
7. **Unrecovered loss, verify's assertion.** `verify.Derive` gains a fourth kind beside
   `host_name`, `port_enabled` and `neighbor`: after the wait, a short burst gets N
   consecutive replies, read from the host. A failure is a finding like any other, so the
   step's wait expires on it and 015's gate fails the stage, with no change to the gate.
   `twin verify` runs the burst too, from the server.
8. **The report gains a `loss` column**: `| stage | at | snapshot | bundle | step | wait |
   verify | loss | new verification failures | verdict |`, transient loss per probe for a
   stepped stage, `—` for a created or refused one, with the caveat in the report's
   footer. The `rehearsal` document carries the same per stage.
9. **The template renders an interface's addresses.** `InterfacePhysical` inherits
   `InterfaceLayer3`, whose `ip_addresses` are `IpamIPAddress`es
   ([dcim.yml](../../schema/dcim/dcim.yml), [ipam.yml](../../schema/dcim/ipam.yml)), and
   neither [device_config.gql](../../infrahub/queries/device_config.gql) nor
   [device_config.j2](../../infrahub/templates/device_config.j2) reads them. Both do, for
   both platforms, and the reference transform's README says so. The reader and the
   mapping do not change: "not read" stays true of the reader, and the artifact carries
   the address to the node. The template reaches Infrahub only when the operator pushes
   and imports it (`CLAUDE.md`, Environment), so its tier-2 and tier-3 proof waits on that.
10. **The fixture gains a probe-ready interface per device**: uncabled, addressed,
    beside `ethernet-1/1`, `ethernet-1/2` and `mgmt0`, whose six ethernet ports are all
    cabled today. Its snapshot id, its compiled id and its artifacts move, and
    `testdata/ctm/three-node.json` follows if it is to stay the fixture's CTM.
11. **The decision entry**, one, D-064: a probe is a declaration outside intent, a file
    first and a kind second on D-045's pattern, carried by the snapshot and compiled into
    synthesized hosts; a probe package is a mechanism keyed by a format value beside the
    PSP; and the declaration carries its own gateway. It stands beside D-057, D-061 and
    D-062 and supersedes nothing. [D-010](../../docs/decisions.md#d-010)'s "everything is
    `intent` today" and the architecture's stop being true.
12. **The documents:**
    - **The contracts:** the new `probes.schema.json` and the probe package's schema;
      `snapshot.schema.json` (`2`), `manifest.schema.json` (`6`), `step.schema.json`,
      `verify.schema.json`, `rehearsal.schema.json`, `twin.schema.json` if the record
      moves, [cli.md](../../contracts/cli.md) and [api.md](../../contracts/api.md) with
      their F-014 sections; the frozen copies older tests read.
    - **[schema/README.md](../../schema/README.md):** the kind, how a probe is written
      (object file, the UI, `infrahubctl object create`), and the template's addresses.
    - **[psp/README.md](../../psp/README.md)** or a README beside the probe packages.
    - **[docs/architecture.md](../../docs/architecture.md):** §4.2 (provenance is no
      longer all `intent`; the snapshot's `probes`), §4.3 (synthesized hosts), §4.4 (the
      step's flows), §4.6 (the step and verify), §4.7 (the probe package beside the PSP),
      §6 (software forwarding and container timing), and the C4 model redrawn, `make
      diagrams` run.
    - **[docs/glossary.md](../../docs/glossary.md):** Probe, Probe declaration, Probe
      package, Flow, Transient loss, Synthesized node reworded; "Probe" is already the
      readiness probe's word, and the two must be told apart.
    - **[docs/development.md](../../docs/development.md), [README.md](../../README.md)**'s
      walk-through, **[docs/verified-facts.md](../../docs/verified-facts.md)**, the
      roadmap (F-014's paragraph: "ping and iperf3" to `ping` only, D-032 to D-045's
      pattern, and the entry built; [Exit](#exit)) and **`CLAUDE.md`**'s Formats, State and the fixture's ids.
    - **[docs/brief.md](../../docs/brief.md):** Scope and Pipeline, one sentence each.

<a id="decided"></a>
## Decided

Each was settled with the operator on 2026-10-25 through the roadmap's re-shape, or on
2026-10-16 in the old brief and kept by it, unless marked otherwise.

- **`ping` only, from a containerlab `linux` node, and no other synthesized node type**
  (2026-10-25). iperf3, Ixia-c and an emulated boundary device are later formats of the
  same declaration. *Overturns* the old brief's "ping and iperf3".
- **The declaration is a file first; the Infrahub kind is one source of it** (2026-10-25).
  *Overturns* the old brief, which made the kind primary and the file `twin compile`'s
  input. The NetBox reader ([F-025](../../docs/roadmap.md#f-025)) takes the file alone.
- **The declaration carries the host's address and its gateway** (2026-10-25). The CTM
  carries no address, so Fylgja configures the host from the declaration alone, and the
  refusal of a host address outside the interface's prefix is lost. *Overturns* the old
  brief's item 3.
- **The probe set rides in the snapshot and is hashed by its id** (018, 2026-10-27).
  `twin compile` takes no probe file. *Overturns* the old brief's "a separate input,
  hashed into the bundle beside intent".
- **Probes are declared by the operator, never derived from the topology** (2026-10-16,
  kept). Deriving which ports hosts take and which pairs to mesh would be Fylgja guessing
  at intent.
- **The device side of a probe is intent's** (2026-10-16, kept). The interface's address
  is written in Infrahub and rendered by Infrahub's template. Fylgja configures only the
  host.
- **Transient loss is measured and reported, never gated; unrecovered loss gates, as a
  verify finding** (2026-10-16, kept). The gate does not change.
- **Loss is labelled container timing wherever it appears** (2026-10-16, kept;
  Constitution X). Containers forward in software, so the loss measured is the
  container's, never the ASIC's.
- **The template renders addresses, and the reader does not read them.** *Settled by the
  brief's author* on 2026-10-28, as following from D-057 and the old brief's item 8: the
  mapping stays exact, CTM `2` stands, and the device side reaches the node by the only
  road Constitution IV allows.
- **The compiler refuses a probe it cannot place; a proposed change that cables a probe's
  port fails `fylgja-step` at that stage** (2026-10-16, kept, less the prefix refusal).
- **One probe list per request** (the operator, 2026-10-28, at feature-open). A request
  reads its probes once, from `--probes <file>` or `FylgjaProbe` on `main`, and every
  snapshot it takes carries that list, so a rehearsal's stages share one; a later create
  or step reads them afresh. The server keeps nothing between requests and the snapshot
  stays the one input ([D-061](../../docs/decisions.md#d-061), [D-062](../../docs/decisions.md#d-062)),
  while a probe edited mid-rehearsal cannot move its hosts between stages. Transient loss
  is measured for the probes in both the twin's snapshot and the target's; a host the step
  adds gets the verify burst alone, and what a step does with a host the target drops is
  the plan's. *Not chosen*: one list for the twin's life, carried in its record into
  every later take (the old brief's, before snapshots), which would override or refuse a
  `twin step --snapshot` carrying another; and every take afresh, a rehearsal's stages
  included, which lets a mid-rehearsal edit move hosts between stages.
- **A `--probes <file>` replaces the kind's probes, and a take with neither has none,
  with no warning** (the operator, 2026-10-28, at feature-open). One source per take
  keeps the snapshot's list exactly what was declared, as the file-first re-shape and
  F-025's file-alone reader have it; and the empty list already says "no probes", as
  every snapshot says today. *Not chosen*: the file added to the kind's probes, a name in
  both refused, which makes a take's provenance two sources; and a warning on a take with
  no probes, which would sound on nearly every take.
- **The rate and the burst's N are the `ping` package's alone** (the operator,
  2026-10-28, at feature-open). A probe declares its name, its format and its two
  endpoints and nothing else, so the file, the kind and the snapshot's hash stay small;
  the package override directory changes them host-wide, as it does a PSP's timeouts; and
  per-flow rates belong to F-020's element shape, not `ping`'s. *Not chosen*: each
  probe's own, the format's as the default, which adds two optional fields to the
  declaration, the kind and the contract, and moves a snapshot id for a rate alone.
- **A stage that removes a probe's device or deletes its interface is refused at the
  compile, and so fails `fylgja-step` at that stage** (the operator, 2026-10-28, at
  feature-open), as a stage that cables a probe's port is. The compiler keeps one rule, a
  probe it cannot place is refused, and a probe never vanishes from a stage, hiding the
  loss it was declared to show; the remedy is the declaration's, in the file or in
  `FylgjaProbe` on `main`. A probe kept in Infrahub therefore blocks a change that
  decommissions its device until it is deleted on `main`. *Not chosen*: the probe dropped
  from that stage with a finding and the stage going on, which leaves the compiled hosts
  short of the snapshot's declaration and gives the compiler a third outcome.
- **One decision entry, D-064, superseding nothing.** *Settled by the brief's author*, on
  D-061's pattern (D-063 is the feature chain's, 2026-10-28).
- **Out of this feature:**
  - any second format, and any node type but the `ping` host;
  - loss as a graph or an export ([F-013](../../docs/roadmap.md#f-013)); the report's
    column is a number;
  - any change to the CTM, the reader, the mapping or the schema library's files;
  - the NetBox reader (F-025) and the orchestrator;
  - a running-configuration read of a node, or any assertion of the device's address.

<a id="open"></a>
## Open, for clarify

none

<a id="left-to-the-plan"></a>
## Left to the plan

- **Where the synthesized nodes enter.** The constitution says synthesized nodes are added
  to the CTM before compilation, and the snapshot keeps the declarations beside the CTM,
  not in it, so the CTM stays the reader's contract. The plan says how the compile adds
  the hosts to the CTM it compiles, under provenance `synthesized`, without the stored
  CTM moving; `Compile(c *ctm.CTM, reg *psp.Registry)` gains the declarations or a step
  before it does.
- **The `linux` image, its acquisition and how a host is configured**, verified on
  containerlab 0.79.0: the kind's `exec` lines for the address and the route, whether the
  image is pulled, its size, and that a privileged SR Linux container and a plain `linux`
  one share a lab. Then how a flow runs and how its counters are read, from the lab host,
  by the worker for the step and by the server for `twin verify`; both have `docker` on
  their `PATH` already. None of it is in [docs/verified-facts.md](../../docs/verified-facts.md).
- **The step's phases.** The flows start before `reconcile` and are read after the wait;
  whether a flow that fails to start is a new phase or a finding under `record`, and what
  a cancelled step does with its flows.
- **The format versions that move**: snapshot `2`, bundle `6`, the step, verify and
  rehearsal documents, `twin.json` if the record names the hosts, and the frozen copies
  under each package's `testdata/contracts/`. The three goldens move with the bundle
  version, so the re-baseline is a commit of its own, as `CLAUDE.md` says.
- **The fixture's new interface**: its name, its address and prefix, and whether
  `testdata/ctm/three-node.json` and the wrapped fixture under `testdata/snapshot/` follow
  it, which moves the goldens again. The seed is
  [internal/testsupport/seed.go](../../internal/testsupport/seed.go), and the fixture tool
  ([cmd/fylgja-fixture](../../cmd/fylgja-fixture)) gains what the tests and tier 3 need:
  a probe written, a probe's port disabled is `-disable-port` already.
- **The template's lines**, on both platforms, verified on the images: SR Linux's
  `subinterface 0 ipv4 address` and its admin state, EOS's `no switchport` and `ip
  address`; the artifact changes for every device with an addressed port and for no other.
- **The kind's shape**, with the `infrahub-managing-schemas` skill loaded before
  `data-model.md`: whether an endpoint is two attributes or a related kind, the uniqueness
  constraint, and what a read of the kind yields when a device or interface it names is
  not in the scope. `-objects` for the object file the README shows, `-transforms` for the
  template.
- **The Constitution Check.** Whether a probe package format is a fourth blessed layer in
  the Check's gate adjustments, a MINOR amendment citing D-064, or falls under II and the
  PSP's blessing with no amendment. The author leans to the amendment, since the gate
  names the layers it will not flag and a second package kind is one.
- **The assertion kind's name and rule id**, in `verify.Derive`'s style
  ([internal/verify/assert.go](../../internal/verify/assert.go)).
- **The burst's budget** inside the step's wait and `twin verify --wait`, against
  `fylgja-twin`'s `timeout` of 4260.
- **The estimate.** The roadmap's 5–7 hours was set before snapshots and before the
  template change; the plan re-estimates.

<a id="operator-steps"></a>
## Operator steps

- [x] Push `main` to `origin` before the chain (`git push origin main`): 019's merge and the
  feature chain's commits, twelve ahead. Done 2026-10-28; `origin/main` is `7a1a180`. A push
  during the chain would stop the loop at `contract`.

Waiting for the chain, each the route's `[operator]` task with its reason:

- **Load `FylgjaProbe` on `main`**, since the plan settles the kind's shape and writes its
  schema file: `.venv/bin/infrahubctl schema check --branch main <file>`, then `schema
  load`, from the repository root with `local/.env` loaded, Infrahub up and no twin, as
  014's T003 loaded the stage kind. It is a lasting write to `main`'s schema on an install
  that is not throwaway, and it moves `main`'s hash. After the plan, before tier 2.
- **Push the template and import it**, since the import waits on the pushed tree: once
  `device_config.gql` and `.j2` render the addresses, merge into `main` and push `origin`'s
  `main`, then `InfrahubReadOnlyRepositoryImportLastCommit(data: {id})` on `main` for the
  registration `fylgja`, and read both task workers' `commits/` (`CLAUDE.md`, Environment),
  as 017's T057 did. Before tier 2's artifact proof, the fixture's re-seed and tier 3.
- **The review, the merge and the push**, because they are the operator's at every
  feature's close, with `make command-log` once the session is closed.

The fixture's re-seed and the `linux` image's pull are the live sessions': a write to a
branch and to the host, not to `main`.

<a id="hand-off"></a>
## Hand-off

- **To F-025**: the NetBox reader produces snapshots with a probe list from the file
  alone; the kind is the Infrahub reader's source and nobody else's. The device side of a
  probe is whatever NetBox's `render-config` renders.
- **To F-020**: Ixia-c is a second format of the probe package and a second element shape
  of the declaration, with flows, rates and latency; the slot it fills is this feature's.
- **To the production shape**: the declaration is the first input to the core that no
  source of truth owns; the orchestrator writes it, and the API takes it as a file.

<a id="exit"></a>
## Exit

**The one criterion:** a change applied to a running twin reports the loss it caused,
labelled as the container's, and a flow that has not recovered fails the stage.

- **Tier 1:**
  - A snapshot `2` with probes compiles to a bundle with the hosts, their links and
    their ports under provenance `synthesized`, all in the manifest; the same snapshot
    with no probes compiles to the bundle it did, but for the version.
  - Each refusal: the device not in the snapshot, the interface missing, cabled or
    `mgmt_only`, a malformed address, a format no package declares, a probe image absent.
  - Two declarations that differ only in a probe have two snapshot ids.
  - The assertion kind's derivation, and a step record and verify document with loss.
  - The probe package's schema, and the shipped `ping` package passing it; the
    conformance suite's pure half extended if the plan puts the probe packages under it.
  - `TestCompilerNamesNoPlatform` still passes.
  - The goldens re-baselined on their own commit.
- **Tier 2:**
  - `FylgjaProbe` loads on `main`, and a probe written there is read into a take on a
    `fylgja-test-*` branch and deleted after.
  - `intent read --out --probes <file>` files a snapshot `2`; `twin create --snapshot`
    of it compiles.
  - Once the template is imported: the fixture's artifacts carry the addresses, and its
    ids are the ones `CLAUDE.md` records.
- **Tier 3:**
  - A twin with probes steps, and the step's document reports transient loss per probe.
  - Case 9's proposed change gains a stage that disables a probe's port. The check fails
    at that stage on the new assertion kind, and the thread's table carries the `loss`
    column.
  - Nine cases still, unless the plan adds a tenth for the probes alone.
- **Owed before the work starts**, all done on 2026-10-28 at feature-open:
  - 019 built, closed, merged and pushed, and this brief re-read against its close and
    its [Hand-off](../019-following-removed/brief.md#hand-off).
  - The roadmap: Release 0.3's item 4 links here, and F-014's table row and its decisions
    bullet say `ping` only. The F-014 paragraph's "ping and iperf3" and its D-032 citation
    are the chain's, under [What changes](#what-changes) item 12, by the operator's choice;
    the re-shape wins until then.
  - The estimate is the plan's ([Left to the plan](#left-to-the-plan)), by the operator's
    choice; this brief committed.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Release 0.3](../../docs/roadmap.md#release-03), [The production shape](../../docs/roadmap.md#the-production-shape), [F-014](../../docs/roadmap.md#f-014), [F-020](../../docs/roadmap.md#f-020), [F-025](../../docs/roadmap.md#f-025), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope, the 2026-10-25 re-shape, and the decision owed |
| [018's brief](../018-snapshots/brief.md) and its [Hand-off](../018-snapshots/brief.md#hand-off); [019's brief](../019-following-removed/brief.md) and its [Hand-off](../019-following-removed/brief.md#hand-off) | the probe slot, the one open question, and the frozen twin |
| [docs/decisions.md](../../docs/decisions.md): D-010, D-022, D-023, D-028, D-031, D-038, D-039, D-045, D-057, D-061, D-062 | synthesized nodes, the manifest, the hashing, the mechanism pattern, the assertions, the kind's pattern, the contract, the snapshot, the frozen twin |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 2.2.0: II, III, IV, V, IX, X and the Check's gate adjustments | the Constitution Check, and the possible amendment |
| [docs/architecture.md](../../docs/architecture.md) §4.2, [§4.3](../../docs/architecture.md#43-compiler), §4.4, §4.6, [§4.7](../../docs/architecture.md#47-platform-support-packages), §6 | the CTM's synthesized nodes, the compile, the step, verify, the package, the known limitations |
| [contracts/snapshot.schema.json](../../contracts/snapshot.schema.json), [ctm.schema.json](../../contracts/ctm.schema.json), [manifest.schema.json](../../contracts/manifest.schema.json), [step.schema.json](../../contracts/step.schema.json), [verify.schema.json](../../contracts/verify.schema.json), [rehearsal.schema.json](../../contracts/rehearsal.schema.json), [twin.schema.json](../../contracts/twin.schema.json), [cli.md](../../contracts/cli.md), [api.md](../../contracts/api.md) | the formats that move |
| [psp/README.md](../../psp/README.md), [psp/psp.schema.json](../../psp/psp.schema.json) | the package format's pattern: format value, image, acquisition, mechanism, timeouts, embedding and the override directory |
| [schema/README.md](../../schema/README.md), [schema/fylgja-stage.yaml](../../schema/fylgja-stage.yaml), [schema/dcim/dcim.yml](../../schema/dcim/dcim.yml) (`InterfaceLayer3.ip_addresses`), [schema/dcim/ipam.yml](../../schema/dcim/ipam.yml) (`IpamIPAddress`), [017's mapping](../017-dcim-reader/contracts/mapping.md) | the kind's pattern, where the device side's address lives, and what the reader does not read |
| [infrahub/queries/device_config.gql](../../infrahub/queries/device_config.gql), [infrahub/templates/device_config.j2](../../infrahub/templates/device_config.j2), [infrahub/checks/](../../infrahub/checks/) | the template to extend, and the checks that run the gate |
| [internal/compiler](../../internal/compiler) (`compile.go`, `topology.go`, `manifest.go`), [internal/snapshot](../../internal/snapshot), [internal/verify](../../internal/verify) (`assert.go`), [internal/rehearsal](../../internal/rehearsal) (the markdown), [internal/lab](../../internal/lab), [internal/provision/workflow_step.go](../../internal/provision/workflow_step.go), [internal/server](../../internal/server) (`read.go`, `snapshot.go`, `step.go`, `verify.go`) | the compile, the store, the assertions, the report, the activities, the step and the server's takes |
| [internal/testsupport/seed.go](../../internal/testsupport/seed.go), [cmd/fylgja-fixture](../../cmd/fylgja-fixture), [scripts/e2e.sh](../../scripts/e2e.sh): cases 5, 8 and 9 | the fixture, its tool, and where tier 3 shows the criterion |
| [docs/verified-facts.md](../../docs/verified-facts.md) | what is verified of containerlab and the nodes, and that nothing is of a `linux` node |
