# Decision log

This is Fylgja's decision log. Each entry states a decision in force: its context, the
options considered, the decision and its consequences. **The options considered are the
point.** [architecture.md](architecture.md) describes what was chosen; this log keeps the
paths not taken and why. Check the rejected alternatives here before proposing one: it may
already have been weighed.

- **Append-only from this baseline (2026-10-31).** A changed decision is a new entry that
  supersedes the old one, and a number is never reused. The old entry keeps its text, and
  its status line names the entry that superseded it, the date, and the part, when only a
  part. The constitution is amended only by citing an entry.
- **Every entry here is in force**, except where its status line says a later entry
  superseded it. Decisions taken before the baseline, and the
  orchestrator's own (reading Infrahub, stages, the checks, the rehearsal's report), are
  recorded in the project's archived repository. The orchestrator's decisions return here,
  restated, when it moves here.
- **Citing an entry.** Cite it by its number, `D-0NN`, and link it by its anchor:
  `decisions.md#d-0nn` from `design/`, or `design/decisions.md#d-0nn` from the repository root.
- **The frozen Go core**, in the archived repository, is the reference implementation of
  the core ([D-001](#d-001)). Where an entry describes its behaviour, it says so.

## Index

| ID | Decision | Topic |
|---|---|---|
| [D-001](#d-001) | The core is written new, in Python, with the frozen Go core as its reference | The project and its shape |
| [D-002](#d-002) | A clean break: every format and interface starts at version 1 | The project and its shape |
| [D-003](#d-003) | Fylgja is two deployables: a core, and an orchestrator that drives it through the API alone | The project and its shape |
| [D-004](#d-004) | Infrahub is the first source of truth, and the core knows none | The project and its shape |
| [D-005](#d-005) | The production project lives in a new repository, the core first | The project and its shape |
| [D-006](#d-006) | The blueprint is the core's one input, addressed by the hash of its network and probes | Intent and the blueprint |
| [D-007](#d-007) | Configuration is rendered by the source of truth, never by Fylgja | Intent and the blueprint |
| [D-008](#d-008) | A probe is a declaration outside intent, carried by the blueprint and compiled by a probe package | Intent and the blueprint |
| [D-009](#d-009) | A twin is frozen at its blueprint until it is stepped | Intent and the blueprint |
| [D-010](#d-010) | The compiler is pure, and a bundle is addressed by its content | The compiler and the bundle |
| [D-011](#d-011) | The bundle is runtime-neutral, and a driver's pure `plan` binds it | The compiler and the bundle |
| [D-012](#d-012) | Every compile and every deployment reports its fidelity | The compiler and the bundle |
| [D-013](#d-013) | Multi-vendor by requirement; a platform is data | Platforms and packages |
| [D-014](#d-014) | A mechanism is code keyed by a format value | Platforms and packages |
| [D-015](#d-015) | A platform package states only what the runtime does not know | Platforms and packages |
| [D-016](#d-016) | SR Linux first, EOS second | Platforms and packages |
| [D-017](#d-017) | Runtimes are drivers behind a seam of seven calls | Runtimes and drivers |
| [D-018](#d-018) | The containerlab driver runs the `containerlab` CLI | Runtimes and drivers |
| [D-019](#d-019) | Many named twins, each in its own isolation unit | Runtimes and drivers |
| [D-020](#d-020) | Node access on clabernetes: a LoadBalancer per node | Runtimes and drivers |
| [D-021](#d-021) | Account-gated images live in a private registry the cluster trusts | Runtimes and drivers |
| [D-022](#d-022) | kind is the cluster for the clabernetes driver's development | Runtimes and drivers |
| [D-023](#d-023) | The core runs its own reconcile loop, scheduled by a queue keyed by twin | The reconcile loop and state |
| [D-024](#d-024) | State lives behind one store; no database | The reconcile loop and state |
| [D-025](#d-025) | The API is the core's boundary: API 1, with the twin as a resource in Kubernetes's shape | The API and its clients |
| [D-026](#d-026) | The thin CLI: noun-verb, a client like any other | The API and its clients |
| [D-027](#d-027) | A replace resets the candidate to the node's own baseline | Pushing, stepping and verifying |
| [D-028](#d-028) | A refused SR Linux replace asks the node again for its reason | Pushing, stepping and verifying |
| [D-029](#d-029) | A step that fails after touching the twin leaves it up and diverged | Pushing, stepping and verifying |
| [D-030](#d-030) | Observed facts are a Fylgja-owned vocabulary, mapped to paths by each package | Pushing, stepping and verifying |
| [D-031](#d-031) | Verify's assertions are data derived from the bundle | Pushing, stepping and verifying |
| [D-032](#d-032) | Verify is advisory: no Fylgja operation acts on its verdict | Pushing, stepping and verifying |
| [D-033](#d-033) | A lighter process: design document, decision entry, pull request | Process and repository |
| [D-034](#d-034) | Tests are tiered by cost | Process and repository |
| [D-035](#d-035) | The schemas' `$id` namespace is the repository's GitHub URL | Process and repository |
| [D-036](#d-036) | The production cluster: three k3s servers with embedded etcd on SSD, MetalLB in layer 2, the registry off the cluster | Runtimes and drivers |
| [D-037](#d-037) | Each node's LoadBalancer keeps the client's address: `externalTrafficPolicy: Local`, set by the clabernetes driver | Runtimes and drivers |
| [D-038](#d-038) | What the compiler refuses and what it omits | The compiler and the bundle |
| [D-039](#d-039) | Phase 4's libraries: Starlette on uvicorn, httpx, and nothing else | The API and its clients |
| [D-040](#d-040) | Run ids are ULIDs made in the core | The reconcile loop and state |
| [D-041](#d-041) | The local store's layout and how it writes | The reconcile loop and state |
| [D-042](#d-042) | Configuration and credentials come from `FYLGJA_*` variables, with no configuration file | The API and its clients |
| [D-043](#d-043) | The local driver's allocation and its reach into Docker | Runtimes and drivers |
| [D-044](#d-044) | The deployment id hashes the driver, the twin, the bundle id and the files | The compiler and the bundle |
| [D-045](#d-045) | The driver's plan refuses a runtime port two cabled interfaces share | The compiler and the bundle |
| [D-046](#d-046) | The driver registry is the one module above the seam that names a runtime | Runtimes and drivers |
| [D-047](#d-047) | A refusal `commit validate` passes names both its possible causes in one sentence | Pushing, stepping and verifying |
| [D-048](#d-048) | Configuration is optional in a blueprint, and an absent configuration is unmanaged | Intent and the blueprint |
| [D-049](#d-049) | The seam grows for the step: `changes`, `exec`, and the allocation `admit` keeps | Runtimes and drivers |
| [D-050](#d-050) | A step runs the create's phases, refuses before it touches, and resumes under the create's rules | The reconcile loop and state |
| [D-051](#d-051) | Verify reads both ends of a link, a node it cannot read fails the verdict, and phase 5 runs the burst and not the flow | Pushing, stepping and verifying |
| [D-052](#d-052) | Phase 5's library: pygnmi for the gNMI reader | Pushing, stepping and verifying |
| [D-053](#d-053) | Verify judges a neighbour's port by the far port's node name, and three refinements of D-051 | Pushing, stepping and verifying |
| [D-054](#d-054) | The step as built: its dispatch, its record before `applied`, the spec it answers to, and its endings | Pushing, stepping and verifying |
| [D-055](#d-055) | The local driver's destroy waits for a stray deploy and removes every container of the lab | Runtimes and drivers |
| [D-056](#d-056) | A deploy's output goes to a file in the twin's directory, so a stray deploy runs to completion | Runtimes and drivers |

The [Parked](#parked) and [Open questions](#open-questions) sections follow the entries.

## The project and its shape

<a id="d-001"></a>
### D-001 — The core is written new, in Python, with the frozen Go core as its reference

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Fylgja needs a production core: many twins, several runtimes, one input. Its audience is
network engineers, and their ecosystem (Infrahub's SDK, NetBox's client, Nornir, NAPALM) is
Python. The frozen Go core is about 32k source lines and 96k test lines. Its foundations
(one twin at a time, a fixed lab name, state under one root, one host, Temporal's workflow
identity) run through every layer, and its tests are tied to Go and Temporal.

#### Options considered

- **Go end to end, one runtime.** Rejected: if most contributors write Python and few write
  Go, adoption beats elegance.
- **Keep the Go core and refactor it.** Rejected: the foundations to remove run through
  every package.
- **Port the Go core to Python, file by file.** Rejected: it copies the old structure into a
  new language and keeps the foundations.
- **Write the core new in Python, with the Go core as its reference.** Chosen.

#### Decision

- `fylgja-core` is a new Python 3.14 package, `fylgja_core`, under `core/`, with strict type
  checking. Both deployables ([D-003](#d-003)) share one model package for every format they
  both read ([Constitution I](constitution.md#i-one-language-typed)). The design is
  [design/core.md](core.md).
- The Go core is frozen, fixes only, in the archived repository. It explains behaviour and
  supplies test scenarios, and is not translated. When the new core replaces it, it is
  retired.

#### Consequences

- The fixtures, the platform and probe packages, the verified facts the core needs and these
  decisions carry over; the Go code, its workflow histories and its frozen contract copies
  do not.
- The compiler facts under `testdata/compiler/` came from the Go core, and the new compiler
  must state the same facts for the same fixtures.

<a id="d-002"></a>
### D-002 — A clean break: every format and interface starts at version 1

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A review of every format of the frozen Go core found the same three things in each: fields
no consumer reads, facts stored three to five times, and one-host and Temporal identity.
There is no outside user to keep compatible with.

#### Options considered

- **Keep the formats, and add new versions beside them.** Rejected: every retired field
  survives as a reader.
- **Read the archived repository's snapshot 2 files, and break the rest.** Rejected by the
  maintainer: those files exist only on development hosts.
- **A clean break.** Chosen.

#### Decision

- Every format and interface starts at version 1, specified by one current-state document
  with no addenda, under [formats/](../formats/README.md). The core reads no earlier version.
- The orchestrator moves to API 1 and blueprint 1 in one change, when it moves here
  ([D-005](#d-005)). Until then the earlier formats stay in the archived repository.

#### Consequences

- A compatibility reader or a frozen copy returns only through a decision
  ([Constitution XII](constitution.md#xii-every-field-earns-its-place)).

<a id="d-003"></a>
### D-003 — Fylgja is two deployables: a core, and an orchestrator that drives it through the API alone

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Reading a source of truth, resolving the moments of a change and reporting back to the
source are one kind of work. Building, stepping and verifying a twin from a fixed input is
another. A core that does both knows a branch, carries a source's credential, and takes new
code for every new source.

#### Options considered

- **One deployable, with the readers in the core's server.** Rejected: the core keeps
  knowing a branch, and every new source is code inside it.
- **The orchestrator on Temporal.** Rejected: it defers the question of the orchestrator's
  platform.
- **The orchestrator on Kestra.** Rejected: declarative YAML fits an orchestrator that is a
  contract others' flows fill, which is not decided.
- **The orchestrator on Prefect, in Python.** The ecosystem's language, flows as code,
  Apache 2, no Kubernetes, and the platform Infrahub's own checks run on. Chosen.
- **A source reader kept as a tool in another language.** Rejected: the orchestrator would
  hold two toolchains.
- **The source's own check posts the report.** Rejected: a source with no checks, such as a
  NetBox branch, would get no report.

#### Decision

- **The core** turns a blueprint ([D-006](#d-006)) into a named twin, and steps, verifies,
  shows and destroys it; it compiles a blueprint, validates packages and diffs two bundles.
  It knows no source, branch, proposed change or stage, and holds no source credential.
- **The orchestrator** is a Python project on Prefect. Its adapters read one source each
  into a blueprint; it resolves the stages of a proposed change, rehearses a change on a
  twin, and posts the report back to the source, rendering it from the core's documents.
- **The orchestrator drives the core through the API alone** ([D-025](#d-025)).
- [Constitution I](constitution.md#i-one-language-typed) binds both to Python; the
  orchestrator may call a tool in another language, and the core may not link one.

#### Consequences

- Whatever writes a blueprint is a **producer**. The orchestrator is the one Fylgja ships,
  and a blueprint file is as good an input.
- **Revisit** if Prefect's open-source server lacks what the flows need, or once the
  orchestrator is decided to be a contract rather than a product.

<a id="d-004"></a>
### D-004 — Infrahub is the first source of truth, and the core knows none

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A source of truth must offer **branching** (the source itself is versioned, so a change has
an address to build a twin of) and a **flexible schema**.

#### Options considered

- **NetBox or Nautobot.** Mature, with a large ecosystem and a fixed DCIM-shaped model.
  Without branching, a change is a configuration diff somewhere else, with nothing
  addressable to build a twin of. NetBox 4.7.4 with netbox-branching 1.2.2 (probed
  2026-10-29) has branches with a diff, merge, revert and change log, but cannot read a
  branch as it stood at an earlier time.
- **Infrahub.** Native branching with diff and merge, a user-defined schema, GraphQL,
  branch-scoped artifacts and time-travel reads. A younger ecosystem, and heavy to run (a
  graph database, a message bus, task workers, a cache). Chosen as the first source.
- **In-house.** Full control and no ecosystem; a source of truth is not the product.
- **The core reads its source itself.** Rejected: see [D-003](#d-003).

#### Decision

- **Infrahub is the first source of truth**, read by the orchestrator's adapter through one
  documented mapping of the OpsMill schema library's DCIM.
- **NetBox with its branching plugin is a source Fylgja may read**, through an adapter of its
  own.
- **The core is source-agnostic**: it takes blueprints, whoever wrote them
  ([Constitution III](constitution.md#iii-the-blueprint-is-the-contract)).

#### Consequences

- Time travel is the producer's: a twin of last Tuesday is a blueprint read as of last
  Tuesday, an incident-reconstruction tool.
- Infrahub's rendered artifacts give configuration its home ([D-007](#d-007)).
- A twin's lifetime is coupled to no branch's: the core knows none.

<a id="d-005"></a>
### D-005 — The production project lives in a new repository, the core first

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A new language, new formats, new runtimes and a new process ([D-001](#d-001),
[D-002](#d-002), [D-017](#d-017), [D-033](#d-033)) change the project's nature. The earlier
repository is public, with the v0.1.0 and v0.2.0 releases, and its tree and history carry
process tooling and host details that do not belong in a production repository. The
orchestrator there drives the frozen Go core in the earlier formats, and Infrahub fetches
its template and checks from that repository with no credential.

#### Options considered

Where the project goes:

- **Clean forward in place.** Rejected: everything stays one `git log` away.
- **Rewrite history in place.** Rejected: it reaches no existing clone or fork, rewrites
  every cited commit, invalidates both releases and breaks Infrahub's imported commits.
- **A new repository, the earlier one archived and kept public.** Rejected by the
  maintainer.
- **A new repository, the earlier one renamed, archived and made private.** Chosen, made
  private only once nothing fetches from it.

What the first commit holds:

- **The core and the orchestrator together.** Rejected: it carries the earlier formats and a
  test tier that needs the archived Go tree.
- **The core alone**, the orchestrator moving here once the new core runs twins. Chosen.

#### Decision

- A new public repository, `fylgja`, starts from one curated first commit, held to the
  release-hygiene checks: the formats, the core's package, the platform and probe packages,
  their fixtures and the documents.
- **The orchestrator stays in the archived repository**, with Infrahub's template, query,
  checks and vendored schema, and drives the frozen Go core there. It moves here when the
  new core runs twins on the local containerlab driver ([D-017](#d-017)).
- The earlier repository is renamed and archived read-only, and keeps the frozen Go core.
  **It stays public until the orchestrator moves here**, because Infrahub fetches the
  checks from it with no credential.
- **Infrahub's registration moves to the archived repository's new name before this
  repository takes the name `fylgja`**: GitHub redirects a renamed repository's old URL only
  until another repository takes the name. When the orchestrator moves here, the
  registration moves to this repository before the archived one goes private.

#### Consequences

- Until the orchestrator moves here, Fylgja spans two repositories.
- Making a repository private recalls nothing already cloned or forked. Any credential that
  ever reached the history is rotated regardless.
- Links to the archived repository's releases break once it goes private.
- This repository's code cites no commit of the archived one, and holds no converter between
  the two repositories' formats ([D-002](#d-002)).

## Intent and the blueprint

<a id="d-006"></a>
### D-006 — The blueprint is the core's one input, addressed by the hash of its network and probes

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The core knows no source, branch or stage ([D-003](#d-003)), so it needs one input that is
none of those: what to build, in a form any producer can write and anyone can address. It
holds the network (devices, interfaces, links, each device's rendered configuration) and
the probes ([D-008](#d-008)). Synthesized nodes, such as probe hosts, are in no source. The
same intent read twice, from two branches or at two times, should have one id.

#### Options considered

The model:

- **Compile from the source's own generated types.** Rejected: they are shaped by query
  structure (edges, nullable pointers), and synthesized nodes have nowhere to go.
- **A mapping declared as data per install.** Rejected: a small extract-transform language,
  multiplied by every source.
- **The configurations in a second document beside the network.** Rejected: a second place
  for one fact.
- **A thin document of Fylgja's own, written through one documented mapping per source.**
  Chosen.

Its id:

- **One language's JSON encoder output as the canonical form** (the archived repository's
  snapshot 2 id hashed Go's indented, HTML-escaped encoding). Rejected: every other language
  would have to mimic one encoder.
- **RFC 8785 over the whole document.** Rejected: provenance (branch, time, scope, mapping)
  would give one topology many ids.
- **The read time in the hashed body, with an exception in the hash rule.** Rejected: every
  hasher and reader would need to know the hidden exception.
- **Sort and fill defaults on the producer's behalf.** Rejected: the id would hash something
  other than what the producer sent, and a producer's defect would pass unseen.
- **RFC 8785 over `{network, probes}`, with the source opaque beside it.** Chosen.

Its name:

- **"Snapshot".** Rejected: in network tooling a snapshot is discovered operational state (IP
  Fabric, Forward Networks), and for virtual machines and storage captured runtime state.
  The input is intent, not yet run, and the word stays free for capturing a twin's state.
- **"Spec".** Rejected: it collides with API specifications and says nothing of networks.
- **"Intent" as a noun.** Rejected: it is also the general concept, so "the intent's id" is
  ambiguous.
- **"Blueprint".** Chosen. Juniper Apstra uses it for intended network design, and it reads
  plainly: "compile a blueprint into a bundle", "step the twin to a blueprint".

#### Decision

- **The blueprint is the core's one input**
  ([formats/blueprint-1.schema.json](../formats/blueprint-1.schema.json)): devices with a
  platform id, interfaces with `mgmt_only` and `enabled`, links with ends `a` and `b`, each
  device's configuration as one plain string, and the probes.
- **Its id** is the SHA-256 of the RFC 8785 canonical JSON of `{"network": …, "probes": …}`.
  The version and `source` are not hashed. The id is the store's key, not a field.
- **Every list arrives sorted and unique by its key.** Unsorted or duplicated input is
  rejected (`blueprint.unsorted`, `blueprint.duplicate`), never normalized.
- **`source` is opaque**: the source, branch, point in time, scope, mapping, schema version,
  the read's time (`observed_at`) and the reader's fidelity rows. The core stores and
  returns it, and never validates, reads or hashes it
  ([Constitution VI](constitution.md#vi-intent-is-addressed)).
- **A blueprint is filed once** (`POST /v1/blueprints`) and kept by id, never overwritten
  ([D-024](#d-024)). A twin's spec names a blueprint or bundle by id ([D-025](#d-025)).
- **A producer maps one source by one documented mapping**, records every approximation and
  omission in `source`, reports every fault in one pass, and writes no blueprint on failure
  ([Constitution III](constitution.md#iii-the-blueprint-is-the-contract)).

#### Consequences

- The same topology read from two branches, at two times or by two producers has one id.
- A rule about provenance, such as refusing a step across scopes, is the producer's.
- A blueprint holds configuration, so it never appears in a finding, a log line or a report.
- The fixtures under `testdata/blueprint/` were converted once from the archived
  repository's snapshot 2 files, each recording the conversion in its `source`.

<a id="d-007"></a>
### D-007 — Configuration is rendered by the source of truth, never by Fylgja

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A twin fed by a Fylgja-specific renderer tests a different configuration from the one
production receives. Infrahub renders per-branch artifacts inside the source of truth: the
same templates, data and output as production. It regenerates nothing on its own (verified
on 1.11.2), so an intent change nobody generated for leaves the old bytes.

#### Options considered

Who renders:

- **Fylgja, with its own templates.** Rejected: twin and production diverge by construction.
- **An external pipeline** (Ansible or Nornir in git). Rejected, not deferred: a second
  ingest path and a branch-to-run mapping, for a renderer this deployment does not have.
- **The source of truth**, as Infrahub's artifacts. Chosen.

When it enters:

- **At push time.** Rejected: a configuration-only change would never move the bundle id,
  and a twin of a past moment would get whatever the source holds at provisioning.
- **At read time, in the blueprint.** The bundle is the whole of what the twin will run, and
  a read as of a past moment gets the configuration as it then stood. Chosen.

#### Decision

- **The source renders, and Fylgja renders nothing**
  ([Constitution IV](constitution.md#iv-fylgja-never-renders-configuration)).
- **The producer reads each device's rendered configuration at read time**, checks it (its
  name, content type and checksum, as the source states them) and writes it into the
  blueprint as one plain string. The core does not know the source's word "artifact".
- **The compiler copies it verbatim into the bundle**, and the push sends it unchanged
  after boot, by the package's mechanism ([D-014](#d-014), [D-027](#d-027)).
- **Fylgja never rewrites it.** Where the twin maps a production interface to a port the
  node calls something else, or omits it, the line is pushed as production wrote it, and
  the compile warns, naming the line and what the node calls the interface. It never
  refuses: the operator decides what that means for the test.
- **Fylgja adds no configuration of its own**: each kind's baseline holds the host name,
  linked ports, LLDP and gNMI ([D-015](#d-015)).
- **Generating is the source's.** Fylgja never generates, since that is a write to the
  source.

#### Consequences

- Twin and production run identical text once it is pushed, and the bundle id covers it.
- Staleness is the source's status, judged by the producer, never by the core.
- **Revisit** if an organisation renders outside its source of truth.

<a id="d-008"></a>
### D-008 — A probe is a declaration outside intent, carried by the blueprint and compiled by a probe package

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The headline measurement is loss during a change applied to a running twin. Traffic needs
endpoints that are not in the network: hosts with addresses, attached to device ports. No
source holds such hosts, and the source renders every device's configuration
([D-007](#d-007)).

#### Options considered

- **Probes derived from the topology.** Rejected: Fylgja guessing at intent.
- **Synthesized nodes written into the source**, flagged, on the twin's branch. Rejected: it
  makes Fylgja a writer and pollutes the branch's diff.
- **A source kind as the primary home, a file only the compile's input.** Rejected: a source
  without the kind takes a file alone, and the blueprint is the core's one input.
- **A declaration of its own, by file first, carried in the blueprint, with each host's
  address and gateway in it.** Chosen.
- **A generator type per probe, in code.** Rejected: a branch on what a thing is
  ([D-014](#d-014)).
- **The probe package as a facet of the platform package.** Rejected: a host is of no
  platform.

#### Decision

- **A probe declaration** ([formats/probes-1.schema.json](../formats/probes-1.schema.json))
  names each probe, its format and two endpoints: a device, an uncabled interface, the IPv4
  address its host takes with its prefix length, and its gateway. Rate and burst count are
  the package's.
- **The operator writes it**, as a file or in the source (the orchestrator reads an Infrahub
  kind too). The producer carries it in the blueprint, hashed into the id ([D-006](#d-006)).
- **Each endpoint becomes one synthesized `linux` host** on a synthesized link, configured
  from the declaration alone. A probe that cannot be placed is refused, and every
  synthesized node, link and port is marked as such. The device side is intent's.
- **A probe package** (`probes/`) is a mechanism keyed by its format ([D-014](#d-014)): the
  host image and set-up, how a flow and a burst run and are read, rate, count and timeouts.
  `ping` is the first format.
- **Transient loss across a step is reported**, labelled as the container's, never
  asserted. **Unrecovered loss is the verify assertion `burst`** ([D-031](#d-031)).

#### Consequences

- A probe across two devices needs routing that the source's configuration renders.
- **Revisit** at a second format, or if a probe needs a rate of its own.

<a id="d-009"></a>
### D-009 — A twin is frozen at its blueprint until it is stepped

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A producer can read a branch again at any time and get a new blueprint. Something must
decide when a running twin moves to it, and a twin that may rebuild itself between two
measurements is the wrong ground for probes.

#### Options considered

- **A twin that follows its source**: a scheduled read and compare in the core, rebuilding
  the twin whenever the id moves. Rejected: the core would hold a timer and a branch, and
  probes would measure a twin that rebuilds itself.
- **Following as an opt-in flag.** Rejected: the same, behind a choice nobody defaults to.
- **A frozen twin that changes only when it is stepped.** Chosen.

#### Decision

- **A twin is frozen at its blueprint.** It changes only when a client writes a new spec (a
  step, [D-025](#d-025)) or deletes it.
- **Walking means stepping**, from one blueprint to another: through the stages of a
  proposed change, or to any blueprint.
- The loop's resync restores a twin to its spec ([D-023](#d-023)); it never moves the spec.

#### Consequences

- The core holds no timer of its own over intent.
- A producer that follows a branch does so outside the core: read, compare, step.
<a id="d-048"></a>
### D-048 — Configuration is optional in a blueprint, and an absent configuration is unmanaged

**Status:** Accepted 2026-11-04. Supersedes [D-038](#d-038) in part: `config.missing` narrows
to a configuration that is present and blank. Details [D-007](#d-007).

#### Context

Blueprint 1 requires a non-empty `config` on every device, the compiler refuses a blank one
(`config.missing`), and bundle 1 gives every node a configuration file and its checksum, which
the push sends and verify's claim relies on. Phase 5's step is a layer-1 step, on links and
nodes; configuration management in production is the orchestrator's, and a source may hold no
rendered configuration for a device, or no templates at all. Both kinds' baselines already
hold the host name, linked ports enabled, LLDP and gNMI ([D-015](#d-015)), so a node with no
configuration is a working layer-1 node.

#### Options considered

- **Keep `config` required.** Rejected: a source with no templates gets no twin, and a
  layer-1 rehearsal must carry configuration it does not care about.
- **An empty string means none.** Rejected: absent is the way to say none, and a blank
  configuration stays a mistake worth refusing.
- **Absent means the baseline**: a step from a configuration to none pushes an empty replace,
  which by [D-027](#d-027) resets the node to the kind's baseline. Rejected: a disruptive
  push to remove what the core is told not to manage.
- **Absent means unmanaged**: the core neither pushes nor compares that node's configuration.
  Chosen.

#### Decision

- Blueprint 1 drops `config` from a device's required members; a present `config` is still a
  non-empty string. Bundle 1 makes a node's `config` optional, and a node without one has no
  file under `configs/`. The compiler files `config.missing` only for a configuration that is
  present and blank.
- **The push passes over a node with no configuration**, emitting a `skipped` event for it,
  and marks it as holding the bundle, so the step's re-push decision and verify's bookkeeping
  stay as they are. Readiness still waits for every device node: verify needs a booted node,
  and the push transport answering is the measured signal that it has booted.
- **Verify makes no claim of such a node**: the claim assertion is a skip, an info finding.
- **A step from a configuration to none pushes nothing.** The node keeps what it holds,
  which after a restart or recreate is the kind's baseline. The bundle diff reports the
  change under the reason `config`, which covers a checksum moved and a configuration present
  on one side alone.
- Twin record 1's `holds` says what it means for such a node: nothing owed under the bundle,
  not pushed.

#### Consequences

- A blueprint with no configuration is a complete layer-1 twin, and a producer can build one
  from topology alone, with no rendered artifact.
- A twin may mix nodes with and without configuration.
- The open question of a cEOS node with no data link refusing `ip routing` arises only when a
  configuration carries that line.
- `testdata/` gains a blueprint fixture with a device that carries no configuration, and
  the compile, plan and push tests read it.


## The compiler and the bundle

<a id="d-010"></a>
### D-010 — The compiler is pure, and a bundle is addressed by its content

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The compiler holds the highest-risk logic, interface mapping, and must be testable without a
lab. A bundle's id is load-bearing: a stored bundle is checked against it before it is
deployed, and two bundles are compared by it. Anyone should be able to check it without
Fylgja.

#### Options considered

- **A compiler that does I/O.** Rejected: every test needs infrastructure, and a failure
  could be in any of three concerns.
- **A pure compiler.** Chosen.
- **Hash a canonical serialization of the manifest alone.** Rejected: an edited
  configuration file would keep its id.
- **Hash an archive of the directory** (tar, zip). Rejected: the id would depend on an
  archive format's ordering, padding, recorded times and permissions.
- **Hash a file listing in `sha256sum`'s format.** Fully specified, reproducible with
  standard tools, and blind to everything but a regular file's path and bytes. Chosen.
- **A build stamp in the bundle, excluded from the hash.** Rejected: a hidden exception
  every hasher must know.
- **A build stamp, with a new id per release.** Rejected: every twin's bundle would change on
  upgrade.

#### Decision

- **The compiler is a pure function** from a blueprint and the loaded packages to a bundle,
  with no I/O, clock or environment, enforced by a test
  ([Constitution V](constitution.md#v-the-compiler-is-pure-identity-is-content)).
- **A bundle** ([formats/bundle-1.schema.json](../formats/bundle-1.schema.json)) is
  `manifest.json`, as RFC 8785 bytes, and `configs/<node>.cfg`, each configuration verbatim.
- **Its id** is the lowercase hex SHA-256 of a listing in `sha256sum`'s format: one
  `<hex>  <path>\n` line per regular file, in byte-wise path order, paths relative to the
  root. It carries no build stamp, and its id is never written into it:

  ```sh
  ( cd <bundle> && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1 )
  ```

#### Consequences

- The compiler is tested on fixtures with no infrastructure, and `POST /v1/bundles` runs the
  same function as the tests.
- The same blueprint and packages give the same bundle id on any machine, and a copied
  bundle keeps its id. A compiler change that should invalidate every bundle says so as a
  format version change, never silently.
- Synthesized nodes come from the blueprint's declarations, never from a lookup.

<a id="d-011"></a>
### D-011 — The bundle is runtime-neutral, and a driver's pure `plan` binds it

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Many named twins on several runtimes ([D-017](#d-017), [D-019](#d-019)) need one bundle to
back any twin, anywhere. The frozen Go core's bundle is a containerlab topology with a fixed
lab name, which feeds its id. The measurements of 2026-10-30 rendered one containerlab body
for both containerlab drivers, which differed only in driver inputs.

#### Options considered

- **One bundle per twin and runtime.** Rejected: the same intent gets many ids, and nothing
  is left to deduplicate.
- **Bind at deploy, outside any pure step.** Rejected: an untested binding, and a second
  place where a twin's shape is decided.
- **A neutral bundle, plus a pure, per-driver `plan`.** Chosen.

#### Decision

- **A bundle holds** nodes, links, the interface mapping, configurations and probes as
  placed: no topology file, lab name, image or fidelity.
- **A driver's `plan(bundle, twin, allocation)` is pure**, tested on fixtures, and is the
  one step that binds a bundle to a twin and a runtime. The allocation comes from `admit`
  ([D-017](#d-017)). It returns a **deployment**
  ([formats/deployment-1.schema.json](../formats/deployment-1.schema.json)): the rendered
  files (`topology.clab.yml`, named for the twin, for both containerlab drivers), the
  allocation, the demand admission checks, and the deployment's fidelity ([D-012](#d-012)).
- **The deployment's id** hashes the driver, the twin, the bundle id and the files, so the
  same plan gets the same id and `apply` is idempotent.

#### Consequences

- A bundle id depends only on the blueprint and the packages.
- A step compares two bundles for what changes in intent, and two deployments for what
  changes on the runtime, such as an image.

<a id="d-012"></a>
### D-012 — Every compile and every deployment reports its fidelity

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Nothing verifies that a twin resembles production: fidelity is asserted, never measured. A
twin that quietly dropped three devices is worse than no twin. Part of fidelity depends on
the packages, and part on the runtime: containers forward in software, hardware in silicon.
A twin may mix vendors.

#### Options considered

- **Disclose fidelity in documentation.** Rejected: nobody reads it when it matters.
- **Disclose it with every build.** Chosen.
- **Hash it into the bundle.** Rejected: rewording a package would move a bundle id.
- **One forwarding value per twin, the last platform winning.** Rejected: a mixed twin would
  assert one vendor's answer for another's node.
- **One value, refusing a twin whose platforms disagree.** Rejected: wrong as soon as a
  mixed twin is meant to work.
- **A production-forwarding entry in each platform package.** Rejected: the runtime decides
  how a twin forwards, and what production does differently is the package's approximation.

#### Decision

- **Every compile returns its runtime-independent fidelity**: each package's
  approximations, every omitted interface with its reason, and every synthesized node.
- **Every deployment adds the runtime's part**: how its nodes forward, from the driver's
  capabilities; the rename's many-to-one counts; and the ports a rename shares.
- **Approximations are kept per package**, deduplicated on the package and its sentence, so
  a mixed twin states each vendor's own claims.
- **Fidelity is never hashed into the bundle.** Every surface that shows it says it is
  asserted, not measured ([Constitution X](constitution.md#x-report-honestly)).

#### Consequences

- Skips and omissions are recorded, never silent, and each mapping row carries intent's
  `enabled`.
- The compiler's omissions are verify's context, never its findings ([D-031](#d-031)).

<a id="d-038"></a>
### D-038 — What the compiler refuses and what it omits

**Status:** Accepted 2026-11-03; superseded in part by [D-048](#d-048) on 2026-11-04:
`config.missing` narrows to a configuration that is present and blank; the rest stands.

#### Context

The frozen Go compiler refused every production interface name no rule of the platform's
profile matched, linked or not, on the ground that a gap in the profile and a mistake in
intent look alike. Bundle 1 ([D-011](#d-011)) gave its mapping rows an omission `no_rule`
beside `out_of_range`, and the shipped packages' mapping rows name logical interfaces a
source lists (`Port-Channel1`, `Vlan100`) as `no_rule`. Building the compiler (phase 3)
also met inputs the formats were silent on: a network with no devices, a device with two
management-only interfaces, a device name that is not a safe host, container, pod or file
name, and a string JSON admits but UTF-8 cannot encode.

#### Options considered

- **Refuse an interface no rule matches, as the Go core did.** Rejected: a source lists
  logical interfaces (port channels, VLAN interfaces, loopbacks) on most devices, which a
  twin cannot and need not represent; refusing would block real networks, and the omission
  is not silent, since fidelity reports it with its reason.
- **Omit an unmappable interface a link or probe touches too.** Rejected: the twin would
  silently lose a connection intent holds.
- **Compile a network with no devices to an empty bundle.** Rejected: a twin of nothing has
  nothing to admit, push or verify, and a bundle of one file would be deployed by accident.
- **Refuse a network with no devices in the schema (`minItems`).** Rejected: an empty
  network is a well-formed statement a reader may make of a scope that matched nothing;
  calling it malformed hides the cause, while a compile finding names it.
- **Refuse a device with two management-only interfaces.** Rejected: chassis and some
  fixed-form devices have two; the twin has one management port, and the second is an
  omission to report, as the Go core reported it.
- **Map every management-only interface to the one management port.** Rejected: a
  production port the twin does not have would go unsaid (Constitution X).
- **Refuse in the compiler only what breaks a file name** (a slash, NUL, another control
  character, a leading dot, whitespace at an end). Rejected: piecemeal, and a name a file
  system accepts may still be one a host name, a container or a pod refuses.
- **Let the compiler crash or answer 500 on a lone surrogate.** Rejected: the blueprint
  loader can refuse it with a pointer, as it refuses everything else at the door.

#### Decision

- An interface the platform has no port for (out of its rule's range, or matched by no
  rule) is an **omission** when nothing touches it, recorded in the bundle's mapping row and
  reported in fidelity, and a **refusal** (`interface.unmappable.linked`) when a link or a
  probe ends on it.
- A device's first management-only interface, by name, is its management port; each
  further one is an omission, `extra_management`, a value added to bundle 1's and
  deployment 1's omissions.
- A network with no devices is refused (`network.empty`).
- A device name is a DNS-1123 label of at most 63 characters, required by the blueprint
  schema (`device_name`), since it becomes the node's host name, its container or pod name
  and its bundle file name; a reader that renames a device to fit records it in its
  fidelity rows. A label is also a path `sha256sum` never escapes, so the by-hand id check
  of [D-010](#d-010) reproduces the id.
- A blueprint whose hashed body holds a lone surrogate is refused at the door
  (`blueprint.unencodable`): UTF-8 cannot encode it and RFC 8785 has no form for it, so it
  could have no id.
- Ports two interfaces are renamed onto, and lossy renames, are the driver plan's to find
  and count, since only the plan renders the rename ([D-011](#d-011)).

#### Consequences

- The compiler's tests hold it to the Go goldens for nodes, links, mapping rows,
  configurations, probes and unmappable omissions; shared ports and lossy rows are checked
  when the plan is built.
- [`docs/rules.md`](../docs/rules.md) catalogues each rule, and `testdata/compiler/rejected/`
  holds a fixture per refusal.

<a id="d-044"></a>
### D-044 — The deployment id hashes the driver, the twin, the bundle id and the files

**Status:** Accepted 2026-11-03. Details [D-011](#d-011).

#### Context

Deployment 1's `$comment` hashes `{driver, twin, bundle_id, files}`, while its `allocation`
description said the allocation was hashed too; the plan could not be built on both.

#### Options considered

- **Hash the allocation as a fifth member.** Rejected: an allocation detail no rendered file
  carries would move the id with no change on the runtime.
- **Hash the four members; the allocation reaches the id through the files it shapes.**
  Chosen: the management subnet is in the rendered topology, so a different allocation is a
  different file.

#### Decision

The deployment id is the SHA-256 of the RFC 8785 bytes of `{driver, twin, bundle_id, files}`,
as the `$comment` says; the allocation's description is corrected in the same change.

#### Consequences

- Planning the same bundle for the same twin with the same allocation gives the same id,
  which keeps `apply` idempotent.

<a id="d-045"></a>
### D-045 — The driver's plan refuses a runtime port two cabled interfaces share

**Status:** Accepted 2026-11-03. Details [D-038](#d-038).

#### Context

A kind with no aliases (cEOS, the synthetic `chassisos`) takes renamed ports, one rename per
data rule ([D-015](#d-015)). A rename that drops a placeholder of its rule's match can put
two interfaces of one node on one runtime port, and when both are cabled, by a link's end or
a probe's endpoint, the topology cables that port twice, which containerlab refuses only at
deploy. The compiler is runtime-neutral and cannot know the rename, and [D-038](#d-038) made
the ports two interfaces share the plan's to find. The frozen Go core refused this case in
its compiler, as `interface.port.collision`.

#### Options considered

- **Refuse in the compiler.** Rejected: the rename is runtime-specific, since a kind with
  aliases shares no port, and D-038 makes sharing the plan's finding.
- **Refuse in `admit`.** Rejected: late, and impure, for a fact the pure plan computes.
- **Answer a dry run with a `Plan` whose deployment is optional.** Rejected: API 1's `Plan`
  requires a deployment, and a refusal is not a plan.
- **The plan raises `Unplannable` with findings; the API answers a 422 problem
  `plan.rejected`, and the loop ends the run `rejected`.** Chosen: a plan refuses as a
  compile does, with every fault in one pass.

#### Decision

- `plan` raises `Unplannable` (`fylgja_core.driver`), holding every fault as a finding in a
  verdict's order, as a compile raises `Uncompilable`.
- On a kind with no aliases, each cabled interface the rename puts on a port with another
  cabled interface of its node is one error finding, `interface.port.shared`; a probe's
  endpoint is cabled. An uncabled interface on a cabled one's port stays an omission,
  `shared`, which fidelity reports.
- The API answers a dry run the plan refuses with a 422 problem document, rule
  `plan.rejected`, carrying the findings, as it answers `bundle.rejected`; the reconcile loop
  ends such a run `rejected`, the findings in its verdict.

#### Consequences

- The rule `interface.port.shared` is catalogued in [`docs/rules.md`](../docs/rules.md), its
  object an interface as `device:interface`.
- `testdata/deployment/rejected/` holds a rejection fixture for each way to reach it, a link
  and a probe: a valid blueprint the compiler accepts and the plan refuses.
- `plan.rejected` arrives with the API, as `bundle.rejected` does.



## Platforms and packages

<a id="d-013"></a>
### D-013 — Multi-vendor by requirement; a platform is data

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A slice of a real network spans vendors.

#### Options considered

- **Single-vendor first, generalize later.** Rejected: an abstraction validated at one
  platform is fiction, and generalizing then happens under pressure.
- **Several vendors, one per twin.** Rejected: a real slice is mixed.
- **Multi-vendor by requirement, with mixed twins**: nothing may assume one vendor, and the
  vendor abstraction is a named, declarative object. Chosen.

#### Decision

- **A platform package is the unit of platform support**
  ([formats/platform-package-1.schema.json](../formats/platform-package-1.schema.json)),
  with a section per runtime ([D-015](#d-015)). A platform is supported when its package
  passes the conformance suite.
- **If a new platform needs a compiler change, the abstraction is wrong**, and the change is
  rejected ([Constitution II](constitution.md#ii-platforms-are-data-never-code)).

#### Consequences

- The format is designed against the full range expected: a public container, an
  account-gated container, a restricted CLI-first binary, a licensed virtual machine.
- Resources, timeouts, readiness, image acquisition and fidelity are package facets.
- `nokia_srlinux` and `arista_eos` ship, and a mixed twin of both compiles with no platform
  branch in the code ([D-014](#d-014)).

<a id="d-014"></a>
### D-014 — A mechanism is code keyed by a format value

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A second vendor tests [D-013](#d-013). cEOS differs from SR Linux in how a node is reached:
its gNMI is **plaintext**, not TLS; its configuration arrives over **eAPI** in a named
configuration session, not JSON-RPC over a candidate; its image is **account-gated**. Each
time, the cheapest change is a branch on the platform (`if kind == "ceos"`), and each would
make D-013 a slogan.

#### Options considered

- **Branch on the platform where a difference appears.** Rejected: every later platform pays
  for it, the compiler stops being pure, and no line says where to stop.
- **A plugin interface per platform.** Rejected: the platform is back in code, and two
  vendors that differ in one field carry two implementations.
- **Make the package a program** (an expression language, or the push's body as a
  template). Rejected: a package becomes untestable by inspection, and failures move from
  "refused at load" to "wrong at the node".
- **A fixed, named set of mechanisms, each selected by a format value.** Chosen.

#### Decision

**A mechanism is code; a platform is data; the format is the seam between them.**

- The core implements a fixed set of mechanisms: two push mechanisms (`json_rpc`, `eapi`),
  each with its replace ([D-027](#d-027)); a gNMI reader that dials with TLS or without;
  handling for an image that may not be pulled; and a reader of a booted node keyed by the
  package's `conformance` paths ([D-030](#d-030)). A probe format selects its mechanism the
  same way ([D-008](#d-008)).
- **No code may branch on what a platform is**: its id, vendor, operating system, runtime
  kind or image. A pure-tier test greps the product source for every platform name the tree
  knows, comments included.
- **A value this build has no mechanism for is refused at load**, naming the values there
  are: never skipped, never defaulted at the moment of use.
- **A platform that needs something new is a format change and a new mechanism**, available
  to every package.

#### Consequences

- A package can ask for a combination no mechanism honours; each such case is a consistency
  rule that refuses at load, naming both fields.
- The test of this entry is the third platform, and what it should cost is a YAML file.

<a id="d-015"></a>
### D-015 — A platform package states only what the runtime does not know

**Status:** Accepted at the baseline (2026-10-31).

#### Context

containerlab's kinds already map SR Linux's interface names (aliases since 0.56), set
default logins, apply a default configuration (linked ports, LLDP, gNMI, JSON-RPC) and wait
for SR Linux's management server. The measurements of 2026-10-30 settled what follows. A
package that repeats the kind says it twice, and the frozen Go core's packages held about 7
fields and 17 option values read by nothing.

#### Options considered

- **Keep the packages whole.** Rejected: they duplicate the kind and carry unused fields.
- **Import the kind's knowledge as data.** Impossible: it is Go code inside containerlab.
- **Write production names into the topology, and let the kind map them.** Chosen.
- **Fylgja's own bootstrap configuration per node.** Rejected: with no startup
  configuration, each kind's baseline already holds the host name, linked ports enabled,
  LLDP and gNMI, and all of it survives the replace push.
- **A readiness probe per package, with a flag to wait for the push transport.** Rejected:
  readiness that is not "the push answers" lets a push race the node; cEOS's eAPI opens a
  second or two after its gNMI.

#### Decision

- **A package's `runtime.containerlab` section** holds the kind, image, acquisition,
  resources, measured timeouts and the link mode, shared by both containerlab drivers.
- **Production names go into the topology where the kind has aliases.** SR Linux has them.
  **cEOS has none** (containerlab 0.79 through 0.82), so its package keeps one rename rule,
  `Ethernet{a}[/{b}[/{c}]]` → `eth{a}[_{b}[_{c}]]`. The kind's name pattern is unanchored at
  the start, so a wrong name ending in `et<digit>` (`Ethernet1`) is accepted and wires a port
  EOS never sees; the plan emits only the rule's output, and conformance checks every
  link's port inside the operating system.
- **One `credentials` name**, resolved by the core's credential provider, names a login.
- **No bootstrap** ([D-007](#d-007)). **Readiness means the push transport answers** an
  authenticated request.
- **`link_apply_mode`** (`live` or `restart`) and `hot_add_ports` are written on each node
  at create:
  - under `live`, both kinds re-cable with no restart and keep the push, for ports present
    at boot;
  - cEOS never sees a port added after boot (`hot_add_ports: false`), so a step that adds
    one replaces the node and pushes again;
  - the mode is never changed on a running twin: on clabernetes that replaces every pod,
    and there `restart` and `recreate` both replace the pod.
- **`memory_mb` and `cpu` are the pod's requests on clabernetes** (its default of 512 Mi is
  about a third of a node's use) and an admission budget locally.
- **The source's concerns stay with the producer**: which source platform a package matches,
  and the rendered configuration's name and content types.

#### Consequences

- A name the kind refuses is found by the driver's validate step before apply. A package's
  optional range keeps early refusal where it matters.
- The cEOS name pattern is worth reporting upstream.

<a id="d-016"></a>
### D-016 — SR Linux first, EOS second

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The mechanics need a first platform to be proven on, and a second to prove the platform
abstraction ([D-013](#d-013)) real.

#### Options considered

- **The production platform first (EOS).** Valuable at once, but cEOS is account-gated and
  needs an import path, and the harder interface mapping arrives before the loop is proven.
- **SR Linux first.** A public image, containerlab's home platform, and YANG-modelled
  throughout. Chosen.

#### Decision

SR Linux first, then EOS. The order after that is [parked](#parked).

#### Consequences

- **SR Linux's one-to-one mapping must not shape the mapping format.** It is designed against
  the lossy case first, on a test-only package with EOS-style naming, `chassisos`
  (`testdata/packages/chassisos.yaml`): many-to-one, collapsing breakout, and a node name
  unlike the production name. Its names come from public documentation, verified against no
  image, and it is never shipped.
- **EOS is not the lossy case.** cEOS carries production's names one to one (`Ethernet1` …
  `Ethernet511`, `Ethernet2/1`, `Ethernet3/1/1`), so the first lossy platform that boots is
  still ahead.
- **A second vendor finds what one cannot**: a second push mechanism, a second gNMI transport
  and CLI syntax ([D-014](#d-014)). cEOS reads `!` as a comment and refuses `#` at token 0.

## Runtimes and drivers

<a id="d-017"></a>
### D-017 — Runtimes are drivers behind a seam of seven calls

**Status:** Accepted at the baseline (2026-10-31); superseded in part by [D-049](#d-049) on
2026-11-04: the seam has nine calls, `changes` and `exec` joining; the rest stands.

#### Context

Production needs many twins across many hosts, and Kubernetes is accepted for that. A later
release targets real hardware. Development must not need Kubernetes. The measurements of
2026-10-30 (containerlab 0.79 locally; clabernetes 0.10.1 on a three-node kind cluster)
grew the seam to seven calls.

#### Options considered

- **One lab host.** Rejected: it contradicts many twins across many hosts.
- **Kubernetes only, with an operator and custom resources.** Rejected: development and the
  live tier would need a cluster, and hardware fits no pod model.
- **containerlab on remote hosts.** Rejected: Fylgja would build its own scheduler, host
  queues and image shipping.
- **A driver seam, with a local driver and a cluster driver now, and hardware later.**
  Chosen.

#### Decision

- **Seven idempotent calls**: `capabilities`, `admit`, `plan` (pure), `apply`, `inspect`,
  `destroy` and `endpoints` ([Constitution XIII](constitution.md#xiii-runtimes-are-drivers)).
  `admit(bundle, twin)` reserves what the twin is bound to (a lab name and subnet, a
  namespace, a device reservation) into the twin record by compare-and-set, or refuses with
  the reason; `destroy` releases it. `plan` is pure, so what it binds to must exist first:
  a paper hardware driver showed this, and two local labs need disjoint subnets too.
- **Push, readiness, verify and flows sit above the seam**, and reach nodes by the address
  `endpoints` returns. Nothing above it may branch on a runtime; it may branch on a declared
  capability.
- **`containerlab`** is the local driver, for development, the live tier and a single lab
  host ([D-018](#d-018)). **`clabernetes`** is the production driver, a namespace per twin
  ([D-020](#d-020) to [D-022](#d-022)). **`hardware`** is a later release's; its paper shape
  checks the seam.

#### Consequences

- A driver conformance suite runs on each driver's own runtime.
- Hardware, unable to re-cable, refuses a step whose links differ from its reservation:
  shutting ports to emulate an absent link would be configuration derived from intent
  ([D-007](#d-007)).
- clabernetes 0.10.1 embeds containerlab 0.81, so the local driver's containerlab is pinned
  to the version clabernetes embeds.

<a id="d-018"></a>
### D-018 — The containerlab driver runs the `containerlab` CLI

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The local driver deploys, inspects and destroys containerlab labs. It must survive
containerlab's releases, and an operator must be able to repeat what it did by hand.

#### Options considered

- **Use containerlab's own packages**, through a binding or a helper. Rejected: they are not
  a stable API and churn between releases, and the core would link a second language
  ([Constitution I](constitution.md#i-one-language-typed)).
- **Run the `containerlab` CLI** with structured output: stable, and what an operator runs.
  Chosen.

#### Decision

The local driver runs the `containerlab` CLI as a subprocess, with structured output. Each
other driver reaches its runtime by its own means: clabernetes through the Kubernetes API.

#### Consequences

- A broken lab is reproducible by hand from what Fylgja logged.
- A containerlab upgrade does not break the build; the kinds' behaviour is re-verified on
  each upgrade ([verified-facts.md](verified-facts.md)).

<a id="d-019"></a>
### D-019 — Many named twins, each in its own isolation unit

**Status:** Accepted at the baseline (2026-10-31).

#### Context

One twin at a time is a simplification for one host. Production must handle many twins;
the first target is about five at once, of tens of nodes each.

#### Options considered

- **One twin per host.** Rejected: it contradicts the goal.
- **Named twins, isolated by the driver.** Chosen.

#### Decision

- **Every twin has a name** (a DNS-1123 label of at most 40 characters) and an isolation
  unit from its driver: a lab with its own management network, a namespace, or a
  reservation ([Constitution VII](constitution.md#vii-twins-are-named-and-isolated)).
- **Twins share nothing mutable.** Every resource a twin uses is labelled as its own, and an
  orphan is found by a label sweep. **Admission refuses a twin that cannot fit**, saying why.
- **Management reach between twins** (verified 2026-10-30): on clabernetes, the plan emits a
  NetworkPolicy per twin namespace, admitting the twin's own pods, the clabernetes namespace
  and non-pod sources (the LoadBalancer path), and refusing other twins' pods; on kindnet
  the push, links and readiness are kept. Locally, two labs' management networks route to
  each other through the host, and no unprivileged control closes that. The maintainer
  accepts it for the local driver, whose twins are the operator's own, and the driver
  declares it (`isolation: names`, against clabernetes' `isolation: network`).

#### Consequences

- No fixed lab name; API 1 names a twin in every path ([D-025](#d-025)).
- **The orphan sweep.** Locally, through containerlab only: removing containers by label
  leaves root-owned `/etc/hosts` lines and `/etc/ssh/ssh_config.d/clab-<lab>.conf`, which
  only a deploy-then-destroy clears, and a refused deploy leaves its management network for
  `docker network rm`. On clabernetes, the namespace delete (49 s, nothing left by label).

<a id="d-020"></a>
### D-020 — Node access on clabernetes: a LoadBalancer per node

**Status:** Accepted at the baseline (2026-10-31); superseded in part by [D-037](#d-037) on
2026-11-02, which sets each Service's `externalTrafficPolicy` to `Local`. A LoadBalancer
per node, auto-expose off and `endpoints()` stand.

#### Context

The core reaches each node's management address from outside the cluster; node access is
direct, by the maintainer's decision. clabernetes 0.10.1 gives each node a LoadBalancer
Service, and by default exposes 14 TCP ports per node beyond those declared.

#### Options considered

- **A LoadBalancer per node.** SSH, gNMI and the push all work through it, with no hop.
  Chosen for now.
- **One bastion or ingress per twin.** Deferred: one address per twin, but a hop, and the
  record's `access` would need a port map. It returns when the address pool runs short.

#### Decision

- The clabernetes plan sets `expose.disableAutoExpose: true`, and declares only the
  package's push, gNMI and SSH ports.
- `endpoints()` returns each node's LoadBalancer address; the record's `access` stays absent.

#### Consequences

- One address per node: five twins of tens of nodes take hundreds of addresses.

<a id="d-021"></a>
### D-021 — Account-gated images live in a private registry the cluster trusts

**Status:** Accepted at the baseline (2026-10-31).

#### Context

cEOS is account-gated: it may not be pulled from, or pushed to, a public registry.
clabernetes 0.10.1 reads an image's manifest from its registry before it plans a pod, so an
image present on a host is not enough.

#### Options considered

- **Load the image onto every cluster node by hand.** Rejected: clabernetes still reads the
  manifest from a registry.
- **A private registry with TLS and authentication, reachable from the cluster alone.**
  Chosen.

#### Decision

- A gated image is pushed to a private registry with TLS and authentication, reachable from
  the cluster alone, never to a public one.
- Each twin namespace gets a pull secret, named in `Topology.spec.imagePull.pullSecrets`,
  and the controller trusts the registry's CA through
  `Config.spec.imagePull.registryMetadataTrust`.
- The package's `pull_secret` names the credential provider's entry. Locally the image must
  be present and is never pulled.

#### Consequences

- Pods pulled the cEOS image in about 3.5 minutes on first use.

<a id="d-022"></a>
### D-022 — kind is the cluster for the clabernetes driver's development

**Status:** Accepted at the baseline (2026-10-31); superseded in part by [D-036](#d-036) on
2026-11-02, which decides the production cluster's shape that this entry left to the
multi-host trial. kind for development stands.

#### Context

Working on the clabernetes driver needs a cluster, which must not need root or dedicated
hosts. The production cluster's shape needs separate hosts to decide.

#### Options considered

- **kind on the development host.** No root, quick to make and discard. Chosen.
- **A production-shaped cluster for every developer.** Rejected: several hosts for work one
  host can do.

#### Decision

- **kind (v0.33.0, Kubernetes 1.37.0) is the clabernetes driver's development cluster.** It
  needs no root; the `vxlan` module loads on demand, and kindnet enforces NetworkPolicy.
  Three nodes, MetalLB, clabernetes and a registry install in about 7 minutes; fixture
  twins come up in 3.5–4 minutes on a first pull, and in about 70 s with the images cached.
- The local containerlab driver stays the one for development and the live tier
  ([Constitution XIII](constitution.md#xiii-runtimes-are-drivers)).
- **The production cluster's shape is decided after the multi-host trial**: two or three
  separate hosts with k3s, MetalLB on the LAN and the registry's CA in `registries.yaml`.

#### Consequences

- Memory sizes a cluster: about 1.6–2 GiB per SR Linux node and 0.9–1.5 GiB per cEOS node,
  as locally. Five twins of 20 nodes need about 180 GiB.

<a id="d-036"></a>
### D-036 — The production cluster: three k3s servers with embedded etcd on SSD, MetalLB in layer 2, the registry off the cluster

**Status:** Accepted 2026-11-02. Supersedes [D-022](#d-022) in the production cluster's
shape, which D-022 left to the multi-host trial.

#### Context

The multi-host trial ran on 2026-11-02 on three Proxmox VMs, each with 8 vCPU, 24 GiB and
80 GB on spinning disks the VMs share. It used k3s v1.37.1+k3s1, MetalLB 0.16.0 and
clabernetes 0.10.1. It ran five twins at once (11 SR Linux and 4 cEOS nodes), steps across
hosts, a drain of one host, and teardown ([verified-facts.md](verified-facts.md)).

- **Spread.** The default scheduler put each three-node twin's nodes one per host, so every
  link crossed hosts over VXLAN. Steps behaved as on kind.
- **etcd.** The three hosts unpacked the 5.2 GB SR Linux image at once. etcd's applies took
  5 s against an expected 100 ms, the leader was lost, and k3s restarted on two servers,
  cancelling the pulls.
- **Drain.** One host drained in 6 s. Every twin was Ready again on the other two within
  94–114 s, each node at the same LoadBalancer address. etcd stayed in quorum, with one
  blip of 2–3 s.
- **Use.** The five twins used about 6.8 cores and 23 GiB.

#### Options considered

- **The control plane.**
  - *One server and agents.* Rejected: draining or losing the server stops the API that the
    core and clabernetes both need.
  - *An external datastore for k3s.* Rejected: one more service to run, for nothing
    embedded etcd lacks at this size.
  - *Three servers with embedded etcd.* Chosen: quorum survives one host drained, which the
    trial did.
- **etcd's disks.**
  - *Spinning disks, with etcd's timings relaxed.* `heartbeat-interval=500` and
    `election-timeout=5000`, with images pulled one host at a time, cut the outages to blips
    of 2–3 s. Kept as the fallback for a cluster without SSD, not as the production shape:
    the blips remain, and a pull the operator did not stagger brings the outages back.
  - *SSD.* Chosen.
- **LoadBalancer addresses.**
  - *k3s's own service load balancer.* Rejected: it binds host ports, so every SR Linux
    node's 22 and 57400 would collide on each host.
  - *MetalLB in BGP mode.* Rejected for now: one LAN segment needs no routing.
  - *MetalLB in layer 2, one address per node from a pool outside DHCP.* Chosen
    ([D-020](#d-020)).
- **Where the private registry runs** ([D-021](#d-021)).
  - *In the cluster.* Rejected: clabernetes reads an image's manifest from the registry
    before it creates a pod, so the registry must answer while pods move. A registry pod on
    the drained host would be unreachable just when the evicted pods need it.
  - *On one cluster host, outside Kubernetes.* What the trial did, under Podman on one host.
    Rejected for production: that host can never be drained.
  - *On a host outside the cluster*, or an existing private registry. Chosen.

#### Decision

- **Three k3s servers with embedded etcd**, k3s pinned by version, installed with
  `--disable servicelb --disable traefik`. Flannel VXLAN and k3s's embedded network policy
  controller stay: the controller enforces [D-019](#d-019)'s NetworkPolicy.
- **etcd on SSD.** A cluster on spinning disks needs the relaxed timings above, with images
  pulled one host at a time.
- **MetalLB in layer 2**, its pool outside DHCP, one address per node.
- **The private registry on a host outside the cluster.** Each node trusts its CA through
  `/etc/rancher/k3s/registries.yaml`, and clabernetes through
  `Config.spec.imagePull.registryMetadataTrust`.
- **Host size, projected from the trial.** Five twins of 20 nodes is 100 nodes. At the
  packages' requests (SR Linux 2 GiB and 0.5 CPU, cEOS 1.5 GiB and 0.5 CPU), that is up to
  200 GiB and 50 CPUs. Two hosts must hold it all while the third is drained. So: **three
  hosts of 128 GiB and 32 vCPU each**.

#### Consequences

- **Drain one host at a time.** A drained host's nodes come back as new pods on the others,
  each with a new incarnation and without its pushed configuration. The core re-pushes
  them on the changed incarnation ([D-023](#d-023)). Nothing moves back after the uncordon.
- **A drain refuses a pod with no controller.** Nothing of a twin's is one, but a
  diagnostic pod left in a twin's namespace blocks the drain until it is deleted.
- **The cluster's prerequisites are the operator's**, listed in [core.md](core.md): the
  modules, the ports between hosts, the AppArmor widening and the address pool.
- The relaxed etcd timings and the staggered pulls are an operating note for a cluster
  without SSD, not something the core does.

<a id="d-037"></a>
### D-037 — Each node's LoadBalancer keeps the client's address: `externalTrafficPolicy: Local`, set by the clabernetes driver

**Status:** Accepted 2026-11-02. Supersedes [D-020](#d-020) in the Services' traffic
policy; its LoadBalancer per node, auto-expose off and `endpoints()` stand.

#### Context

On the multi-host trial, [D-019](#d-019)'s NetworkPolicy refused LAN access to some nodes
and not others.

- clabernetes 0.10.1 creates each node's Service with `externalTrafficPolicy: Cluster`, and
  has no setting for it.
- MetalLB in layer 2 announces each address from one host, chosen per Service, often not the
  host running the pod.
- kube-proxy then forwards from the announcing host to the pod's host, with the source
  rewritten to the announcing host's flannel address (`10.42.N.0`). That address is inside
  the pod CIDR, which the policy's `except` refuses.
- So a node was unreachable whenever MetalLB announced its address from another host.
  kind's single host had not shown it.

#### Options considered

- **Admit the hosts' flannel addresses in the policy.** Rejected: it ties `plan` to one
  CNI's addressing, and admits whatever any host sends, host-network pods included.
- **No NetworkPolicy on clabernetes.** Rejected: twins would reach each other's nodes
  ([D-019](#d-019)).
- **`externalTrafficPolicy: Local`.** Chosen.
  - The source is not rewritten, so the policy sees the client's LAN address.
  - MetalLB announces from the pod's host.
  - The node sees who connected, which an audit trail wants
    ([Constitution X](constitution.md#x-report-honestly)).
  - Its cost, dropping traffic that arrives on a host without the pod, does not arise: each
    Service has one pod, and MetalLB announces from its host only.
- **A field in clabernetes for it.** Worth asking upstream. It replaces the patch only once
  a release has it.

#### Decision

- **The clabernetes driver's `apply` patches each of a twin's Services** to
  `externalTrafficPolicy: Local`, once the controller has created them.
- **`inspect` reports a Service that is not `Local` as drift**, and the loop patches it
  again.
- Verified on the trial: clabernetes keeps the patched value across Topology updates, pod
  replacements and a drain, and a node keeps its address through a drain.

#### Consequences

- The driver's service account needs `patch` on `services` in twin namespaces.
- A Service clabernetes deletes and re-creates, for a node removed and added again, comes
  back `Cluster` until the next reconcile patches it.
- **Ping is no test of the policy.** k3s's network policy controller accepts ICMP echo into
  every pod, whatever the policy. The driver conformance suite tests isolation over TCP,
  from a pod that has run for at least 15 s.

<a id="d-043"></a>
### D-043 — The local driver's allocation and its reach into Docker

**Status:** Accepted 2026-11-03. Details [D-018](#d-018) and [D-019](#d-019).

#### Context

`admit` reserves a lab name and a management subnet for a twin, since two labs on one host
need disjoint subnets ([D-017](#d-017)). The loop needs each container's incarnation and
Docker's events for the twin's containers ([D-023](#d-023)). The driver runs the containerlab
CLI as a subprocess ([D-018](#d-018)).

#### Options considered

- **docker-py**, or the daemon's HTTP API by hand. Rejected: a second way to reach Docker
  beside the CLI, and a dependency for two reads.
- **A prefixed lab name** (`fylgja-<twin>`). Rejected: the twin name is already a DNS-1123
  label kept to 40 characters for exactly this, and containerlab prefixes `clab-` itself.
- **The twin's name as the lab's name, a /24 from a pool, and the `docker` CLI.** Chosen.

#### Decision

- The lab is named exactly the twin's name; containers are `clab-<twin>-<node>`.
- `admit` takes a /24 for the lab's management network from a pool, by default
  `172.20.0.0/16`, skipping any subnet a Docker network already holds, and records
  `{lab, mgmt_subnet}` as the allocation; `destroy` releases it.
- Incarnations (`State.StartedAt`) and the twin's container events come from `docker inspect`
  and `docker events`, run as subprocesses like containerlab, with no SDK.

#### Consequences

- An operator reproduces anything the driver did with the two CLIs it logged.
- The pool's size bounds concurrent labs locally; admission refuses when it is exhausted.

<a id="d-046"></a>
### D-046 — The driver registry is the one module above the seam that names a runtime

**Status:** Accepted 2026-11-03. Details [D-017](#d-017).

#### Context

[Constitution XIII](constitution.md#xiii-runtimes-are-drivers) flags code above the seam
that names a runtime, and a flagged gate returns only through a decision. Yet something
above the seam must name the drivers: `GET /v1/drivers` lists them, and `FYLGJA_DRIVER`
([D-042](#d-042)) names the one the core runs.

#### Options considered

- **Name the drivers in the server's configuration code.** Rejected: two places, the API's
  listing and `FYLGJA_DRIVER`'s reading, would each name them.
- **Entry points, or another plugin discovery.** Rejected: a dependency and an indirection
  for two drivers.
- **One registry module, `fylgja_core.drivers`.** Chosen.

#### Decision

`fylgja_core.drivers` is the one module above the seam that names a runtime. It lists the
drivers the core serves (`NAMES`), makes one by name over a working directory (`make`), and
answers a driver's capabilities without making it (`capabilities`). It is the registry, not
a branch: nothing else above the seam names a runtime, and what branches does so on a
declared capability.

#### Consequences

- `GET /v1/drivers` and `FYLGJA_DRIVER` read the registry; an unknown name is a `KeyError`
  that names the drivers served.
- A new driver is one line there, beside its own module behind the seam.
- A boundary test (`core/tests/test_boundary_seam.py`) scans every module's imports: none
  outside `fylgja_core.containerlab` imports it or any of its modules, the registry alone
  excepted.

<a id="d-049"></a>
### D-049 — The seam grows for the step: `changes`, `exec`, and the allocation `admit` keeps

**Status:** Accepted 2026-11-04. Supersedes [D-017](#d-017) in its count of calls: nine, not
seven. The rest of D-017 stands.

#### Context

A step whose plan restarts or recreates a node needs `allow_restart`, refused before anything
is touched ([D-029](#d-029)). Which nodes a change of topology restarts is the runtime's
knowledge: containerlab's dry run names them, and `link_apply_mode` and `hot_add_ports`,
which decide it, live under a package's `runtime.containerlab` section, which nothing above
the seam may read. A probe host has no management transport, and probe package 1 says its
readiness runs "through the driver's exec", a call the seam does not have. A stepping twin
keeps its lab and subnet, while `admit` reserves a new allocation every time.

#### Options considered

What a step will do to each node:

- **Ask containerlab's dry run** (`deploy --dry-run --format json`) when a step is planned.
  Rejected: impure, needs the running lab's directory, and it is one runtime's answer where
  the seam needs every driver's.
- **Compute above the seam from the bundle diff and the packages.** Rejected: the deciding
  fields are a runtime's section, so code above the seam would read one, and the image lives
  in the deployment, not the bundle.
- **A pure driver call over two deployments**, held to containerlab's dry run in the live
  tier. Chosen.

Reaching a probe host:

- **A small HTTP server in the host image.** Rejected: a mechanism inside the image, and a
  second image to maintain.
- **SSH into the host.** Rejected: a login and a daemon in the image.
- **The driver runs a command inside the node**: `docker exec` locally, the pod exec API on
  clabernetes. Chosen.

Admitting a step:

- **Admit as a new twin.** Rejected: it would reserve a second subnet and count the twin's
  own nodes against it.
- **Skip admission on a step.** Rejected: a node added needs capacity, and its image present.
- **Admit with the allocation the twin holds, checking the added demand alone.** Chosen.

#### Decision

- **`changes(before, after, platforms, probe_packages)`**, pure: given two deployments with
  their rendered files, answers what the runtime does to each node to go from the first to
  the second: `kept`, `added`, `removed`, `recabled` (its links change and the node stays),
  `restarted` (a link change under a restart link mode), or `recreated` (its image, kind or
  another property of the node changes, or a port is added to a kind that cannot add one
  after boot, which containerlab's dry run does not name: under `live` it adds a veth the
  operating system never lists), each with its reasons; and the links added and removed. It
  is the only source of what `allow_restart` must cover, and of a dry run's `changes`
  member. The local driver's `apply` makes the hot-add recreate so by removing that node's
  container before the deploy, which creates it anew with its ports; plan 3 verifies that
  on containerlab 0.81.0, and the fallback, should it not hold, is a refusal for that node
  (`step.relink.unsupported`), never a port the node cannot see.
- **`exec(twin, node, argv, timeout_s)`** runs an argument vector inside a node and answers
  its exit code and output, bounded in time and in bytes. It is the one way code above the
  seam reaches a node that has no management transport, and probe hosts are the only such
  nodes.
- **`admit` takes `held`**, the deployment a stepping twin has applied, or none for a
  create. With it, `admit` keeps that deployment's allocation and checks the demand the new
  manifest adds over the applied deployment's, and the images its added nodes need.
- `capabilities` is unchanged; `relink` is what `changes` and the loop consult for a link
  change.

#### Consequences

- The live tier compares `changes` with containerlab's dry run for every kind of change, on
  the version clabernetes embeds, and a disagreement is a driver bug, recorded in
  [verified-facts.md](verified-facts.md).
- The hardware driver's `changes`, when built, answers a link change as something it cannot
  satisfy, and the step refuses it, as D-017 foresaw.
- The driver conformance suite (phase 6) gains scenarios for `changes` and `exec`.
- [architecture.md](architecture.md) §4.4's table and `fylgja_core.driver` gain the two
  calls and the argument in the change that builds them.


<a id="d-055"></a>
### D-055 — The local driver's destroy waits for a stray deploy and removes every container of the lab

**Status:** Accepted 2026-11-04. Adds to [D-054](#d-054) (item 14, the stray deploy's wait,
which named `apply` alone, and the premise that a stray runs on) and details [D-029](#d-029) (a
diverged twin's deletion removes everything). Superseded in part by [D-056](#d-056) on 2026-11-04: a stray
deploy no longer ends at its next write, since its output goes to a file.

#### Context

Phase 5's live tier (plan 6) asked for a twin's deletion right after a server was killed 5 s
into a step's deploy that added a node. The deploy ran on in its own session and made the node.
The step's resume was cancelled, which left the step diverged with its apply begun. The step had
not recorded `applied`, so the record still named the deployment the twin ran, and the destroy
wrote that deployment's topology and ran `containerlab destroy -t` with it.

containerlab 0.81.0's destroy removes only the nodes its file names
([verified-facts.md](verified-facts.md)). The added node stayed up, holding the management
network, so every `docker network rm` after it failed. The loop retried the destroy run on its
backoff, from 1 s doubling to 60 s, and it had not ended within the test's 600 s.
`destroy --name` did no better: it read the same file, through the container's own label. The
destroy had also run while the stray deploy might still be making nodes, which D-054 item 14
guards against for `apply` alone.

#### Options considered

- **Destroy the target deployment once a step's apply has begun.** Rejected: a step that removes
  a node and is cut short leaves that node, which the target does not name, so either deployment
  can miss a container.
- **`containerlab destroy --name`.** Rejected: it finds the lab's file through the containers'
  label and removes only what that file names, as `-t` does. It also leaves the ssh config, as
  read on 0.81.0 on 2026-11-03 and not read again here ([verified-facts.md](verified-facts.md)).
- **Remove every container of the lab the deployment does not name with `docker rm -f`, before
  containerlab's destroy, which then clears the rest and the network.** Chosen. The containers
  are the twin's by containerlab's label, which `inspect` already reads them by.
- **The destroy runs beside a stray deploy.** Rejected: the deploy may add a container after
  the destroy has read the lab.
- **The destroy waits for a stray deploy, as `apply` does.** Chosen: the same scan of `/proc`,
  within the deploy's budget, logged once. One still running past the budget is `DriverFailed`,
  which the loop retries.

#### Decision

1. **`destroy` waits for a stray deploy** of the twin's topology before it reads the lab, as
   `apply` does (D-054 item 14).
2. **`destroy` removes each container of the lab that the deployment's topology does not
   name** (`docker rm -f`, a container already gone being no failure) before containerlab's
   destroy, which removes the nodes the file names, the host entries, the ssh config and the
   network.

#### Consequences

- A twin whose step diverged after its deploy added a node, before `applied`, is deleted whole,
  as D-029 requires. Phase 5's plan 6 holds this live with a deletion asked right after a kill
  mid-deploy; the deletion after a step cancelled during its apply takes the same path.
- In the rare case where a step cut short before `applied` left none of the nodes the running
  deployment names, containerlab's destroy finds none of its file's nodes. Whether it then still
  clears the hosts block and the ssh config was not read.
- The pure tier holds both rules (`core/tests/test_containerlab_driver.py`), and `apply`'s wait
  (D-054 item 14). The live tier holds `destroy`'s: after a kill 5 s into a step's deploy, the
  destroy waited 16.6–18.9 s for it. `apply`'s never fired live, since every stray a resume met
  had ended before the resume's probe was done.
- `destroy` waits within the budget of the deployment it destroys, while the stray deploys the
  step's target, whose slowest package may have a longer one. A stray still running past it is
  `DriverFailed`, which the loop retries.
- **A stray deploy ends at its next write once the core is gone**, which qualifies this entry's
  premise and D-054 item 14's: its stdout and stderr are pipes the core held, and containerlab
  0.81.0 dies of SIGPIPE once their reader is gone, at its first write by inference
  ([verified-facts.md](verified-facts.md)). So a stray runs on only through one of
  containerlab's quiet stretches, the longest a node's post-deploy wait, tens of seconds on
  the development host. The waits remain for that stretch: a node the stray makes in it is
  real.

<a id="d-056"></a>
### D-056 — A deploy's output goes to a file in the twin's directory, so a stray deploy runs to completion

**Status:** Accepted 2026-11-04. Supersedes in part [D-055](#d-055) (its last bullet: a stray
ends at its next write) and restores the premise of [D-054](#d-054) item 14 and of D-055: a
stray deploy runs on, and the waits are for it.

#### Context

Every command the local driver runs had its stdout and stderr piped to the core
([D-043](#d-043): `cli.run`). Phase 5's plan 6 read on containerlab 0.81.0 that a deploy whose
core has died dies of SIGPIPE, at its next write by inference
([verified-facts.md](verified-facts.md)): at once when the kill lands in a stretch of logging,
and after the nodes' post-deploy wait, tens of seconds, when it lands there. In the second case the nodes are made and running, and
the hosts block and the ssh config, which containerlab writes last, never are. A create's
resume probes the lab and skips the apply when every node answers ([D-023](#d-023)), so such
a twin ends Ready with no `/etc/hosts` entries and no ssh config: correct to the core, which
reaches nodes by the address `inspect` reads, and wrong to a person on the host. A step's
resume applies again and so repairs it, after the stray wait, by chance.

#### Decision

- **`apply` gives the deploy a file for its output**: `deploy.log` in the twin's directory,
  truncated when the deploy starts, holding stdout and stderr in the order written. The core
  opens it, hands the descriptor to the child and closes its own copy, so nothing the core
  holds ends the deploy once the core is gone.
- **`cli.run` takes the file as `log`**, answers an empty stdout for such a run, and raises
  `CommandFailed` for a failure with the file's last `STDERR_KEPT` characters as its stderr.
  A budget run out kills the deploy as before. A file that cannot be opened is `DriverFailed`
  before the command runs.
- **The file is never logged**, as no command's stdout is ([D-043](#d-043)): a deploy's output
  names nodes, images and files, and sits in the twin's directory beside the topology the
  core wrote and containerlab's root-owned lab directory. `destroy` removes it with the
  directory.
- **Every other command keeps its pipes.** A destroy or a `docker` command is short and
  idempotent, and a destroy cut short is found by the next one; the stray that matters is the
  deploy, which makes nodes for up to a budget.

#### Alternatives rejected

- **Start the deploy with SIGPIPE ignored.** Go's runtime decides for itself what a write to a
  broken pipe on descriptors 1 and 2 does, so whether an inherited disposition holds would
  need reading on each containerlab release, and the output would still go to pipes no one
  reads once the core is gone.
- **Keep the pipes and accept the stray's death**, as D-055's last bullet did. A Ready twin
  without its hosts block, and waits premised on a window, is the thing this entry removes.
- **Have the create's resume always apply again.** It would repair the hosts block at the
  cost of a deploy on every resume, and leave the stray's death in place for the step.

#### Consequences

- A stray deploy runs to completion once the core is gone, and `apply`'s and `destroy`'s waits
  (D-054 item 14, D-055) are for a deploy that runs for as long as it takes. In the live
  tier's kill scenarios `destroy`'s wait fires; `apply`'s has not fired live, since each stray
  had ended before a step's resume reached its apply ([verified-facts.md](verified-facts.md),
  the steps block), and the pure tier holds it.
- An orphaned deploy runs with no budget: the budget kill died with the core, and D-054
  rejected killing a stray. One still running past the budget makes each `apply` or `destroy`
  wait a budget out and raise `DriverFailed`, which the loop retries until the stray ends.
  Before this entry a stray's next write ended it after a quiet stretch, so the bound was
  shorter in practice; it is as long as a deploy now.
- A kill in a create's deploy ends in a Ready twin whose hosts block and ssh config are
  present once the orphan has ended. The create's resume does not wait for it when every node
  answers, so the live test waits for the orphan's end before it looks, and asserts the resume
  ran no deploy of its own.
- The twin's directory holds one file the deployment does not name; `_check_files` checks the
  deployment's files alone, and the directory is removed whole at destroy.


## The reconcile loop and state

<a id="d-023"></a>
### D-023 — The core runs its own reconcile loop, scheduled by a queue keyed by twin

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A local driver has no cluster to hold state or run a controller, so a Kubernetes operator
cannot be the control plane everywhere. A twin's lifecycle is a desired state (a bundle)
reached in a few ordered phases, which suits a level-triggered loop. The core serves about
five twins at once, each with runs of minutes; one twin must never have two runs at once,
and one slow twin must never hold up the others. containerlab reconciles nothing itself;
clabernetes reconciles its `Topology`, not the twin as a whole.

Kill tests on 2026-10-30 confirmed the loop: on the local driver, each killed phase
recovered in one resume under the rules below; on clabernetes, with every controller
manager killed mid-step, the step completed.

#### Options considered

The control plane:

- **A Kubernetes operator (kopf) with a `Twin` custom resource.** Rejected: the local driver
  has no cluster.
- **Short workflows under a fixed workflow id per operation.** Rejected: a fixed id is one
  twin's identity, and the workflow service is one more stateful service to run.
- **Temporal, through its Python SDK.** Kept as the fallback, if resuming mid-phase proves
  fragile.
- **The core's own reconcile loop over a store interface.** Chosen.

Scheduling:

- **One serial loop over every twin.** Rejected: one create would stall every other twin.
- **One long-lived task per twin.** Rejected: concurrency has no bound, idle twins hold
  tasks, and a trigger for a busy twin needs a mailbox anyway.
- **A process per run.** Rejected: state shared through the store alone, and a crash loses
  the run's place unless the store holds it, which the queue keeps anyway.
- **A queue keyed by twin, with a bounded pool of workers**, as Kubernetes controllers
  schedule. Chosen.

#### Decision

- **A twin is a record whose desired state is a bundle**
  ([Constitution VIII](constitution.md#viii-reconcile-to-desired-state)). The loop drives it
  through the driver: `compiled`, `admitted`, `planned`, `applied`, `ready`, `pushed`,
  `verified`, `flows`, and `destroyed` for a deletion, recording each phase before the next,
  so a restarted core resumes. The API and the loop run in one process.
- **Recovery rules:**
  - **A lab present while the record lacks `applied` is probed.** A node silent past the
    boot window means applying again with `--reconfigure`: a deploy killed in post-deploy
    leaves nodes that never answer, and a plain redeploy returns 0 and fixes nothing.
  - **A destroy that finds host entries and no lab** deploys, then destroys.
  - **Each node's incarnation is recorded** (the container's start time, the pod's uid). A
    changed incarnation voids what the node holds, and the loop pushes it again.
- **The queue holds twin names, not tasks.** A name already waiting is not added twice; one
  that arrives while a worker holds its twin is marked dirty and queued again when the
  worker lets go. So each twin has at most one worker, and one run, at a time.
- **Workers are a bounded pool** of asynchronous tasks, sized by the server's setting. A
  driver's blocking work (a subprocess, a Kubernetes call) does not block the others.
- **A worker makes one pass**: it compares `generation` with `status.observed_generation`
  and runs phases until the twin converges, must wait on the runtime, or fails. A twin that
  must wait goes back on the queue with a delay rather than holding a worker.
- **Triggers** queue a twin: its `PUT` or `DELETE` ([D-025](#d-025)); a change the driver
  reports (Docker's events for the twin's containers locally, a watch on its `Topology` and
  pods on clabernetes); a periodic resync, so a missed event is only late; and the core's
  start.
- **A transient failure** goes back with a backoff that doubles up to a ceiling and resets
  on success. **A failure only a new spec can clear** (admission refused, a step needing
  `allow_restart`, a refused push) sets the twin's conditions and waits for that write.
- **Cancelling a run** marks it in the store. The worker checks the mark between phases and
  at each driver call, stops the call, and runs cleanup.
- **One core per store**: on Kubernetes, the replica holding a Lease; locally, an exclusive
  lock on the store's directory, so a second core refuses to start and says which holds it.

#### Consequences

- **Concurrency is bounded twice**: by the pool for the core's work, and by admission
  ([D-017](#d-017)) for the runtime's capacity.
- **The queue lives in memory.** Losing it loses nothing: the start and the resync refill it
  from the store.
- **The queue's semantics are pure-testable**; the kill tests run per driver.

<a id="d-024"></a>
### D-024 — State lives behind one store; no database

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The core keeps twin records, runs and their events, blueprints, bundles and deployments.
Records are read by key and changed by one writer per twin at a time; blueprints and bundles
are written once and read by id. The same core runs on a development host and a cluster.

#### Options considered

- **A database.** Rejected: a stateful service to run, for records read by key and changed
  by compare-and-set. No question needs one yet.
- **State spread over the runtime, files under one state root and a workflow service's
  history.** Rejected: one root assumes one twin, and the history ties state to the workflow
  service.
- **Kubernetes resources as the store.** Rejected: the local driver has no cluster.
- **One store interface, with a directory and object storage behind it.** Chosen.

#### Decision

- **One store interface** holds every record and document the core keeps
  ([Constitution IX](constitution.md#ix-state-lives-behind-one-store-no-database)): `local`,
  a directory with each twin's record in its own file (`twins/<name>.json`), for development
  and a single lab host; `object`, S3-compatible storage (MinIO in development), for
  production.
- **Blueprints and bundles are kept by id and never overwritten. A twin record changes only
  by compare-and-set** on its revision.
- **No database**, unless a decision names the question only a database can answer.

#### Consequences

- Compare-and-set keeps concurrent runs on two twins from colliding.
- Run history is the store's run records and events, read with a cursor.

<a id="d-040"></a>
### D-040 — Run ids are ULIDs made in the core

**Status:** Accepted 2026-11-03.

#### Context

Every long operation is a run with an id that sorts by start
([D-023](#d-023), [D-025](#d-025)); twin record 1 fixes the id's form as a ULID. The core
has two runtime dependencies.

#### Options considered

- **The `python-ulid` package.** Rejected: a dependency for about thirty lines, and its
  current release is too new to pin.
- **UUIDv7.** Rejected: the format already names ULIDs, and the Crockford form is what
  clients and tests match.
- **A ULID written in the core.** Chosen.

#### Decision

`fylgja_core.ulid` makes a ULID: 48 bits of milliseconds since the epoch and 80 random bits,
Crockford base32, monotonic within a process, tested against the format's pattern and for
ordering.

#### Consequences

- No new dependency; the id's form is the format's, not a library's.

<a id="d-041"></a>
### D-041 — The local store's layout and how it writes

**Status:** Accepted 2026-11-03. Details [D-024](#d-024).

#### Context

The local store is a directory holding twin records changed by compare-and-set, documents
kept by id and never overwritten, and runs with appended events; one core holds it at a
time ([D-023](#d-023)). A killed core must leave every file whole.

#### Options considered

- **One JSON file for everything.** Rejected: every write rewrites every twin.
- **SQLite.** Rejected: a database by another name (Constitution IX).
- **One file per record, written through a temp file and an atomic rename.** Chosen.

#### Decision

- Layout: `lock` at the root; `blueprints/<id>.json`; `bundles/<id>/manifest.json` and
  `configs/<node>.cfg`; `deployments/<id>/deployment.json` with the rendered files beside
  it; `twins/<name>.json`; `runs/<ulid>.json` and `runs/<ulid>.events.ndjson`, one JSON
  line per event carrying its sequence number.
- Every write goes to a temporary file in the same directory, is fsynced, and is renamed into
  place, so a reader sees the old file or the new one and never a partial one. A
  content-addressed document is linked into place rather than renamed, so an existing id is
  never overwritten.
- Compare-and-set is the revision check and the write under one in-process lock per store;
  the exclusive lock on `lock` (held by the running core) already makes one core per store.
- Events are appended and fsynced one line at a time; a reader by cursor skips a trailing
  partial line.

#### Consequences

- Nothing in the layout assumes one twin; a record is reached by its name alone.
- The object store implements the same interface with keys of the same shape.

<a id="d-050"></a>
### D-050 — A step runs the create's phases, refuses before it touches, and resumes under the create's rules

**Status:** Accepted 2026-11-04; superseded in part by [D-054](#d-054) on 2026-11-04: the
dispatch, the record before `applied`, the generation a run works toward, the cancel's and the
ending's readings, and a refused step's verdict; the rest stands. Details [D-023](#d-023) and
[D-029](#d-029); adds `FYLGJA_STEP_WAIT_S` to [D-042](#d-042).

#### Context

D-029 fixed what a failed step leaves and that a restart needs `allow_restart`; D-023 fixed
the phases and the recovery rules of a create; D-032 put the step's wait inside its run and
its bound in the server's settings. What remained before code: how a step is admitted, when
it refuses, which nodes each phase acts on, how a kill mid-step resumes given that the
silent-node remedy (`reconfigure`) recreates every node, what a cancel before `apply` does,
and the wait's bound. The record's `phase` and `last_step.phase` already name one sequence
for both operations.

#### Options considered

- **A state machine of its own for the step.** Rejected: two sequences to keep aligned, and
  the record already names one.
- **Refuse at the API door alone**, from a dry run. Rejected: the plan can change between the
  door and the run, so the loop must refuse anyway; the door refuses only what it can read
  from the record, a diverged twin.
- **On a resume with a silent node, `reconfigure` as a create does.** Rejected: it recreates
  every node, which `allow_restart` may forbid.
- **End the step `diverged` when a node stays silent and restarts are not allowed; otherwise
  `reconfigure`.** Chosen.
- **A wait budget per package.** Rejected by D-032. **The server's setting**, with a default
  from the measured cEOS restart (a node answers gNMI about 49 s after, and a step across a
  restart took 62–81 s). Chosen.

#### Decision

- **A step is the create's phases**, `compiled`, `admitted`, `planned`, `applied`, `ready`,
  `pushed`, `verified`, `flows`, each recorded before the next. The loop runs a step when the
  record has an applied deployment and the spec's generation is ahead of the observed one; a
  twin whose create never applied is created again.
- **`compiled`**: the spec's bundle. A bundle equal to the twin's ends the run `ok` here,
  `last_step` outcome `unchanged`, the observed generation caught up. Otherwise `last_step`
  is written with `from`, `to`, outcome `running`, the `Stepping` condition set and `Ready`
  False with the reason `twin.stepping`.
- **`admitted`**: the driver's `admit` with the held allocation ([D-049](#d-049)).
- **`planned`**: the driver's `plan`, then `changes` over the applied and the planned
  deployment. Then the refusals, each ending the run `rejected` with the twin running what
  it ran: `step.twin.diverged` ([D-029](#d-029)); `step.restart.required` when `changes`
  restarts or recreates a node and the spec lacks `allow_restart`; `step.relink.unsupported`
  when links change and the driver's `relink` is false. A refusal is recorded as a refused
  create is: the observed generation catches up, `Ready` is False with the refusal's rule as
  its reason, and `last_step` ends with the outcome `rejected`, naming the run, so the
  record still says the spec was not reached and where its verdict is. A blueprint that does
  not compile is recorded the same way under `bundle.rejected`.
- **`applied`**: `apply` of the new deployment over the running lab, then `inspect`.
  `status.bundle_id`, `blueprint_id`, `deployment_id` and `nodes` move to the target here:
  removed nodes leave the record, added ones join it, and a node whose incarnation moved
  has its `holds` voided.
- **`ready`**: every device node whose `holds` is void or absent, and every probe host of
  the new deployment, by `exec` of the probe package's readiness command. **`pushed`**: every
  device node with a configuration whose `holds` is void or absent, or whose configuration
  checksum differs between the two bundles; a node whose configuration is unchanged is
  marked as holding the target bundle without a push, as is a node without one
  ([D-048](#d-048)).
- **`verified`** is the wait: verify ([D-051](#d-051)) until it holds or `FYLGJA_STEP_WAIT_S`
  (default 180) runs out; an expiry is the warning `step.wait.expired`, and the step still
  ends `stepped`. **`flows`** records each probe's loss as `not_started` and is otherwise
  skipped ([D-051](#d-051)). The run ends `ok`, `last_step` outcome `stepped`, `Stepping`
  cleared, `Ready` True with the reason `twin.ready`.
- **Resume**: after the last recorded phase, under the create's rules, with one change to
  the partial-lab probe: on a step the lab is always present, so the probe runs only when the
  run's events show an `apply` started and not ended. Then the lab is applied again plainly
  when every device node answers; when one stays silent, `reconfigure` with `allow_restart`,
  and without it the step ends `diverged` with the finding `step.node.silent`, which is
  honest: the apply had begun.
- **A spec written during a run** is accepted at the door, as Kubernetes accepts one. The
  run completes toward its own target, the pass records the generation it took the run under
  (not the record's latest), and the next pass finds the newer generation and steps again.
  Phase 4's loop wrote the latest generation on settling, which would swallow the newer
  spec; plan 5 corrects it.
- **Cancel**: before `apply` begins, the run ends `failed` with `run.cancelled` and the twin
  is as it was; from `apply` on, `diverged` ([D-029](#d-029)), the finding `step.diverged`
  naming the phase and each node's held bundle.

#### Consequences

- `FYLGJA_STEP_WAIT_S` joins the settings of [D-042](#d-042) and `.env.example`.
- The API's `501` for a new spec on a twin that exists goes; `fylgja-core twin step` writes
  the spec and waiting is a watch ([D-026](#d-026)).
- Twin record 1's description of `allow_restart` names `step.restart.required`, the rule
  D-029 chose, where it says `step.restart.refused`; `last_step.outcome` gains `rejected`.
- The rule catalogue gains `step.twin.diverged`, `step.restart.required`,
  `step.relink.unsupported`, `step.wait.expired`, `step.node.silent` and `step.diverged`,
  and the `Ready` reason `twin.stepping`; a stepped twin's reason is `twin.ready` again.


## The API and its clients

<a id="d-025"></a>
### D-025 — The API is the core's boundary: API 1, with the twin as a resource in Kubernetes's shape

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A CLI that links the core puts every credential the system has in the operator's shell, and
every other client (the orchestrator, a web UI, an agent) would have to repeat each rule the
CLI holds. The core reconciles each twin toward a desired state ([D-023](#d-023)). Clients
need to ask for a twin, follow it to convergence, and not overwrite each other unseen.

#### Options considered

Where the boundary is:

- **An API beside a CLI that still links the core.** Rejected: two paths per operation, a
  guard that exists twice or differs, and the shell keeps every credential.
- **The CLI as the API's client for the lifecycle alone.** Rejected: the shipped CLI would
  keep a path to the core no other client could use.
- **Pure commands in the client, the rest through the API.** Rejected by the maintainer: the
  rule would name its exceptions, and a bundle compiled in a shell with other packages need
  not be the server's.
- **The API as the only path for every user-facing client, test code excepted.** Chosen.
- **No exception: every test through the API.** Rejected: the pure tier calls the pure core
  by design, and the live tier's oracles must be independent of the system under test.
- **A direct mode in the CLI for tests.** Rejected: a second path in a shipped client,
  proving a path no operator takes.

The API's shape:

- **One operation per POST** (JSON-RPC 2.0, or the frozen Go core's 16 operations with
  NDJSON streams and frame kinds). Rejected: it names no twin, holds open a stream no
  client needs, and reports errors many ways.
- **Verbs, each answering a run** (create, plan, step, destroy). Rejected: a step and a
  create are different calls for the same change of intent, a retry can start a second run,
  and two clients can overwrite each other's request unseen.
- **The Kubernetes API itself**, a `Twin` custom resource. Rejected: the local driver has no
  cluster, the API would leak the runtime, and a second front door would break the boundary.
- **gRPC, or Connect.** Rejected: the formats are JSON identified by the hash of their JSON,
  so protobuf would wrap them in a second schema; HTTP/2 end to end, or a young Python
  implementation, and no `curl`. Kept in reserve for a high-rate telemetry stream.
- **GraphQL.** Rejected: flexible querying for a surface too small to need it, and long
  operations sit awkwardly as mutations.
- **A message bus.** Rejected: a stateful service of its own, for about five twins.
- **A resource API over HTTP, long operations as runs, the twin in Kubernetes's shape.**
  Chosen.

Authentication:

- **One shared token from the process environment.** Rejected: no change can be attributed
  to a principal, and rotating it stops every client at once.
- **Per-client bearer tokens, each with a principal.** Chosen.

#### Decision

The boundary ([Constitution XI](constitution.md#xi-the-api-is-the-boundary)):

- **A user-facing client reaches the core through the API alone**: the thin CLI
  ([D-026](#d-026)), the orchestrator ([D-003](#d-003)), any later client. None imports or
  runs the compiler, the store or the drivers, or writes the store or the runtime.
- **Every refusal is the server's**, so every client is refused alike, under the same rule.
- **The payloads are the documents Fylgja versions**, with no second representation. The API
  returns documents, and clients render them. It exposes what clients need, and a later
  client adds the endpoint it needs.
- **Test code and test tools are excepted, and nothing else.** No flag makes a shipped
  client link the core; a test over imports holds the boundary.

API 1 ([formats/api-1.openapi.yaml](../formats/api-1.openapi.yaml)):

- **Resources**: `blueprints`, `bundles` (with a diff), `packages:validate`, `drivers`,
  `twins/{name}`, `runs/{id}` with events read by cursor, and `version`.
- **The twin record is the twin resource.** Its **`spec`** (the blueprint or bundle, the
  driver, `allow_restart`) is written by clients alone; its **`status`** (conditions
  `Ready`, `Stepping`, `Diverged`, the phase, what runs, the nodes, the last step,
  `observed_generation`) by the loop alone. **`generation`** rises with every change of spec
  and a deletion request; **`revision`** with every write.
- **`PUT /v1/twins/{name}` with a spec creates or steps the twin**, answers the record, and
  the loop starts a run toward it; the same spec again changes nothing. `If-Match` carries
  the revision read, and a write over another fails `412`; `If-None-Match: *` creates only.
  **`?dry_run=true`** runs admission and the driver's `plan` and writes nothing.
- **`DELETE` sets `deletion_requested_at`**; the loop tears down, then deletes the record,
  readable meanwhile.
- **`?watch=true`** on a twin or the list answers server-sent events, each carrying the
  whole record; reconnecting with the last revision seen misses nothing.
- **What stays an action**: `POST /v1/twins/{name}/verifications`, a question rather than a
  desired state, and `POST /v1/runs/{id}/cancel`.
- **Runs** record every transition: a ULID, the principal, a state, and once ended a
  verdict, with events read by cursor.
- **One error model**: an RFC 9457 problem document for anything malformed, unauthorised,
  refused at the door or conflicting; a findings document for a domain verdict.
- **Auth**: per-client bearer tokens mapped to principals, from Secrets on a cluster or a
  local file of token hashes. `401` and `403` are distinct, several tokens are valid at once
  for rotation, the audit log and every run name the principal, and TLS ends at the
  ingress. OIDC and roles follow the first outside user.

#### Consequences

- A client holds one credential, its token. Node logins stay with the core's credential
  provider, and source credentials with the producer.
- A client words only what happened to itself: an unreachable server, a refused token, a
  local file it cannot read.
- **One idempotent call** takes a twin from any state toward what is asked; a retry is
  harmless. Convergence reads the same on every driver: `observed_generation` equal to
  `generation`, and `Ready` true.
- An agent's interface (an MCP server, say) would sit on this API, never beside it.

<a id="d-026"></a>
### D-026 — The thin CLI: noun-verb, a client like any other

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The CLI serves operators ("give me a twin") and developers ("show me what this blueprint
compiles to"), and is a client of the API ([D-025](#d-025)).

#### Options considered

- **`twin build`** as the front door. Rejected: it reads as producing an artifact, and sits
  oddly beside `destroy`.
- **Verb-first** (`fylgja build`). Rejected: messy once nouns multiply.
- **The intermediate steps only** (file, compile, deploy). Rejected: operators want a twin.
- **Noun-verb, `twin create` the front door, each intermediate step a command of its own.**
  Chosen.

#### Decision

- **`fylgja-core`**: `twin create|step|show|verify|destroy|list`, `run get|watch|cancel`,
  `blueprint push`, `bundle build|get|diff`, with `--json` on every command. Otherwise it
  renders text from the API's documents, through a client library it shares with the
  orchestrator.
- **`twin create` and `twin step` both write the spec**; waiting for a twin is a watch.
- **Exit codes**: 0 ok; 1 a negative verdict (`rejected`, `failed`, `nonconforming`); 2 a
  problem document or a transport failure; 3 a twin left dirty (`unclean`, `diverged`).
- Flags arrive with the feature that needs them.

#### Consequences

- The CLI holds no rule of its own: every refusal is the server's.

<a id="d-039"></a>
### D-039 — Phase 4's libraries: Starlette on uvicorn, httpx, and nothing else

**Status:** Accepted 2026-11-03; added to by [D-052](#d-052) on 2026-11-04: pygnmi for the
gNMI reader; the rest stands.

#### Context

API 1 serves JSON documents validated by the schemas in `formats/`, streams a twin's changes
as server-sent events, and runs in one process with the reconcile loop's asyncio workers
([D-023](#d-023)). The push and readiness are HTTPS requests to a node's management address
([D-027](#d-027)). The core has two runtime dependencies so far, and every pin is a release
at least two weeks old.

#### Options considered

- **FastAPI.** Rejected: its pydantic models would be a second representation of every
  document the formats already define, and its generated OpenAPI would compete with the
  hand-written `api-1.openapi.yaml`.
- **aiohttp**, server and client. Rejected: the core would use half of a bundle, and its
  server is not ASGI.
- **The standard library's `http.server`.** Rejected: synchronous, no streaming response.
- **Starlette on uvicorn**, plain ASGI with streaming responses. Chosen.
- **The client: `urllib` in a thread.** Rejected: the loop is asynchronous, and a blocking
  push would hold a worker. **httpx's async client.** Chosen.

#### Decision

- **Starlette 1.9.0 on uvicorn 0.54.0** serve API 1; the server validates every request body
  against its format's schema and answers documents, with no model layer of the
  framework's.
- **httpx 0.28.1** carries the push, readiness and, later, any HTTP read of a node, with the
  node's boot-time certificate accepted unverified as the packages state.
- No other library enters phase 4; what else it needs (ULIDs, logging, the store) is written
  in the core.

#### Consequences

- The pins move only by a decision's rule for dependencies: a release at least two weeks old.
- The API's test suite is written from the OpenAPI document and runs against the service,
  so no framework-generated schema is ever the reference.

<a id="d-042"></a>
### D-042 — Configuration and credentials come from `FYLGJA_*` variables, with no configuration file

**Status:** Accepted 2026-11-03; added to by [D-050](#d-050) on 2026-11-04:
`FYLGJA_STEP_WAIT_S`; the rest stands. Answers the credential provider's local naming, open
since the baseline.

#### Context

The core runs on a development host and on a cluster. Credentials come from one provider:
the environment locally, Secrets on a cluster (Constitution X). A platform package names its
login by a `credentials` name, never a value, and `.env.example` listed provisional variable
names.

#### Options considered

- **A configuration file** (YAML or TOML) beside the store. Rejected: a second place for
  values that on a cluster come from Secrets as environment variables anyway, and a file an
  operator could commit.
- **Command-line flags.** Rejected: a credential on a command line is visible in the process
  list.
- **Environment variables alone, one naming rule.** Chosen.

#### Decision

- The server reads `FYLGJA_STORE` (the store directory), `FYLGJA_LISTEN` (default
  `127.0.0.1:7650`), `FYLGJA_DRIVER` (the default driver), `FYLGJA_WORKERS` (the pool's
  size), `FYLGJA_PACKAGES` (directories of platform and probe packages, colon-separated) and
  `FYLGJA_TOKENS` (a file of per-client token hashes with their principals).
- A node login is `FYLGJA_CREDENTIAL_<NAME>_USERNAME` and `FYLGJA_CREDENTIAL_<NAME>_PASSWORD`,
  where `<NAME>` is the package's `credentials` value upper-cased with dashes as
  underscores: `srlinux` is `FYLGJA_CREDENTIAL_SRLINUX_USERNAME`.
- A client reads `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`.
- On a cluster the same variables are set from Secrets; the provider's interface is the same
  on both.

#### Consequences

- `.env.example` is the list of names, and `local/.env` the one place values live.
- A missing variable is refused at start, naming the variable and never its value.


## Pushing, stepping and verifying

<a id="d-027"></a>
### D-027 — A replace resets the candidate to the node's own baseline

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A step takes a running twin from one bundle to another. A merge push from configuration A to
B would leave whatever A added that B lacks, so a step needs a **replace**, and since Fylgja
never renders configuration ([D-007](#d-007)), the device must compute the difference. A
replace by `delete /` takes the management plane dark: the source's configuration carries
no management, the kind's does. containerlab leaves that management on every node as a
**baseline** (SR Linux's startup configuration and its checkpoint `clab-initial`; cEOS's
`flash:startup-config`), and no push saves over it. These methods were tried on SR Linux
24.7.1 and cEOS 4.32.0.2F under containerlab 0.79.0 on 2026-10-01.

#### Options considered

SR Linux:

- **S1: load the baseline into the private candidate, send the configuration, commit.**
  `load` replaces the candidate, uncommitted edits included, in 2.2–4.5 s; `diff flat`
  gives the device's diff. Chosen.
- **S2: a gNMI Set with a CLI-origin replace carrying the baseline.** Every replace carries
  containerlab's management text; 19.3 s for a 573-line baseline.
- **S3: scoped deletes kept as package data.** Leaves anything A added outside the scopes.
- **S4: a JSON-RPC `set` replace at `/`.** Needs JSON and the whole tree, management
  included.
- **S5: NETCONF `copy-config` startup to candidate.** About 0.7 s, but it commits through the
  shared candidate, gives no device diff, and would make SR Linux's configuration XML while
  EOS's stays CLI.
- **napalm-srlinux.** Its replace is `delete /` plus the lines, which darkens the node.

EOS:

- **E1′: in a named session, `rollback clean-config`, `copy startup-config session-config`,
  the configuration, commit.** The pair makes the session exactly the baseline (the copy
  alone would merge); 1.6 s; `show session-config diffs` gives the device's diff. Chosen.
- **E1: replay the baseline's lines read from `show startup-config`.** Fylgja would read,
  strip and replay the node's own configuration, hashed secret included.
- **E2: `configure replace flash:<file>`.** Ties the push to the lab host's paths.
- **E3: `configure replace startup-config`, then a merge.** Not atomic.
- **E4: a gNMI Set with a CLI-origin root replace.** The blob must carry the baseline, and
  cEOS silently ignores gNMI's commit-confirmed extension.
- **E5: NETCONF.** No reset into the candidate, refuses repeated lines, and a refused edit
  drops the session.
- **NAPALM, Ansible `arista.eos`, AVD, scrapligocfg.** E1's pattern, and each saves the
  running configuration, overwriting the baseline.

Both:

- **The source renders management too**, so each vendor's native full replace works.
  Rejected: the source would hold twin facts, a login would enter the configuration, and it
  reverses [D-007](#d-007).

#### Decision

**A replace resets the candidate to the baseline the node already holds, sends the
configuration and commits**, in one request with one atomic commit.

- **SR Linux (`json_rpc`):** `enter candidate private`, `load startup`, the configuration's
  lines, `diff flat`, `commit now`. `load startup` is chosen over the checkpoint, which is
  pruned once ten newer exist, and is faster.
- **EOS (`eapi`):** `enable`, `configure session fylgja-<attempt>-<ns>`, `rollback
  clean-config`, `copy startup-config session-config`, the configuration's lines, `show
  session-config diffs`, `commit`, with `format: "text"`. A refused session is aborted
  before the next attempt.
- The reset is code keyed by the delivery mechanism ([D-014](#d-014)). A create and a step
  share one push: at create the node holds only its baseline.
- **Fylgja never saves the running configuration**, and computes no diff: what a step
  records of a node's change is the device's.
- A refused `json_rpc` replace may send a second request that lands nothing
  ([D-028](#d-028)); a replace that commits is always one request.

#### Consequences

- No baseline text is read, carried or replayed. The baseline is the kind's, so it is
  re-verified on a containerlab or image upgrade.
- A safety net, if ever wanted, is the device's own timer (SR Linux's `commit confirmed`,
  EOS's `commit timer`), never gNMI's or NETCONF's commit-confirmed, which cEOS 4.32 ignores.
- A topology step's order: the re-cable; readiness of every restarted node (a restarted cEOS
  node answered gNMI after about 49 s and eAPI after about 55 s); then the replace on every
  node whose content changed **and every node that restarted**.
- A refused EOS request leaves its session pending until aborted, and EOS allows five. A
  refused SR Linux line stays in the login's private candidate until the next `load
  startup`.
- **Revisit S5** if SR Linux's configuration becomes structured for its own sake, **and E4**
  if an EOS release honours gNMI's commit-confirmed extension.

<a id="d-028"></a>
### D-028 — A refused SR Linux replace asks the node again for its reason

**Status:** Accepted at the baseline (2026-10-31); superseded in part by [D-047](#d-047) on
2026-11-03, which rewrites the first sentence, for a candidate that validates. The second
request, the second sentence and the rest stand.

#### Context

A refused SR Linux JSON-RPC push echoes every command sent, and Fylgja reads the reason
after the echo, at `' failed with error '`. SR Linux cuts the message at about 1 KiB. Under
the replace ([D-027](#d-027)) the reset precedes the configuration: a replace of 33
commands made a 1,604-byte echo, and the node's 1,032-byte message ended inside it, so the
reason (`invalid port 99, max is 58`) never arrived. On SR Linux 24.7.1, `commit validate`
gives the reason for a schema constraint (a VLAN encapsulation on a port without
`vlan-tagging`), but answers `All changes are valid.` for a check made as a commit applies
(the port range).

#### Options considered

- **Accept the cut message.** Rejected: a refusal would say nothing useful on the platform
  where refusals are most common.
- **Commit in a request of its own, on every replace.** Rejected: two requests per replace,
  and a line refused at parse time still echoes them all.
- **Re-commit the refused candidate.** Rejected: after a parse-time refusal, it would land a
  partial configuration.
- **Ask again with `commit validate`.** Chosen.
- **Drop the request, since it misses commit-time reasons.** Rejected: it would lose the
  schema-constraint reasons for no gain.

#### Decision

- **A `json_rpc` replace whose refusal gives no reason gets one more request:** `enter
  candidate private`, `commit validate`. It lands nothing; its echo is two commands, so a
  validation reason fits. It runs inside the push's budget and is never retried, and the
  refusal stays a refusal. The next `load startup` clears the candidate. `eapi` needs none:
  it names the refused command in its own answer.
- **A reason it gives is the finding's.** When it gives none, the finding says so in one of
  two sentences, and quotes nothing:
  - the candidate validates: `the node's message ends before any reason Fylgja can read,
    and the candidate it refused passes `commit validate`, which does not run every check a
    commit does (D-028)`;
  - the answer is cut, unreadable, failed or absent: `the node's message ends before any
    reason Fylgja can read, and asking again with `commit validate` gave none (D-028)`.
- The refusal is read before the message's first empty line, so a value in the diff after
  the echo never names the wrong command.

#### Consequences

- A refusal costs about one more second, inside a 30 s budget.
- A commit-time refusal names the node and its configuration's checksum, not the reason; the
  operator finds it by pushing by hand, or from the package's port ranges, which the compile
  already enforces.
- Both sentences are part of the core's contract, held word for word by the pure tier.
- **Revisit** if SR Linux makes `commit validate` run the commit-time checks, or lifts its
  1 KiB cap.

<a id="d-029"></a>
### D-029 — A step that fails after touching the twin leaves it up and diverged

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A create that fails tears its twin down: cleanup runs on every failure path. A step cannot
follow that rule: before it there was a ready twin the operator may have worked on for an
hour. Verified facts ([verified-facts.md](verified-facts.md)): containerlab's dry run
(`containerlab deploy --dry-run --format json`) names every node a change of topology will
restart, recreate or create, and writes nothing. Under `link_apply_mode: live` both kinds
re-cable with no restart for ports present at boot ([D-015](#d-015)); a node whose image or
kind changes, or a cEOS node that needs a port it lacked at boot, is replaced and loses its
push.

#### Options considered

What a failed or cancelled step leaves:

- **Tear the twin down.** Rejected: it destroys the state the step was meant to keep.
- **Roll back automatically.** Rejected: a rollback is a second step that can fail in turn.
- **Cancel to the previous state.** Rejected: not what the operator asked for.
- **Leave the twin up and diverged, and record where it stopped.** Chosen.

What a diverged twin may do next:

- **Step again**, or **repair to the same target.** Rejected: no bundle describes the twin,
  so the diff and the push would be wrong.
- **Only deletion.** Chosen.

A step that restarts or recreates a node:

- **Proceed.** Rejected: an unexpected reboot loses running state.
- **Refuse any kind that restarts.** Rejected: EOS could never take some topology steps.
- **Require `allow_restart` in the spec.** Chosen.

#### Decision

- **A step that fails or is cancelled after touching the runtime ends `diverged`**, with
  the `Diverged` condition and a finding naming the phase and which nodes the push reached.
  Nothing is torn down. A refusal before that touches nothing and is `rejected`.
- **Cleanup for a step is the record**, written whatever happened, idempotently: the
  previous blueprint and bundle, the target, the run and the last phase completed, and each
  node's held bundle, or none for a node that restarted and was never pushed.
- **A diverged twin accepts only deletion.** A step from it is refused
  (`step.twin.diverged`), naming the run, the target, the phase and the remedy.
- **A step whose plan restarts or recreates a node needs `allow_restart`**
  (`step.restart.required`), refused before anything is touched. A node created for the step
  needs none. Every restarted, recreated or created node is awaited, then pushed.
- **The device's diff lives in the run's events alone**, bounded, never in a record, finding
  or log line.

#### Consequences

- The thin CLI exits 3 for `diverged`, as for `unclean` ([D-026](#d-026)).
- A deletion during a step cancels its run, waits for its record, then tears down.
- Rollback and repair, when built, start from the diverged record.
- Steps that restarted a cEOS node took 62–81 s; a configuration-only step 5.5 s.

<a id="d-030"></a>
### D-030 — Observed facts are a Fylgja-owned vocabulary, mapped to paths by each package

**Status:** Accepted at the baseline (2026-10-31).

#### Context

The conformance suite reads five facts of a booted node, and verify reads three of them
against intent, over gNMI, by paths each package's `conformance` facet declares. The
question is what model those reads are of.

#### Options considered

- **Adopt OpenConfig**, translating each platform's answers into it. Rejected: SR Linux
  answers in its native model and cEOS in OpenConfig, and a translation layer is a second
  model to maintain for five facts.
- **Assertion code per platform.** Rejected by [D-014](#d-014).
- **Fylgja's own names for the facts**, each package mapping them to its paths and values,
  read by one mechanism. Chosen.

#### Decision

Fylgja owns a vocabulary of observed facts: `host_name`, `port.enabled`,
`port.discovering`, `port.neighbor` (with `system_name` and `port_id`) and `version`. A
package maps each to a path, a value and what absence means; no model is adopted. Verify
asserts three (host name, port enabled, neighbour) against intent; the conformance suite
asserts all five against the package. The readers are product code, shared by verify, a
step's wait and the suite.

#### Consequences

- A new fact is a new name and one reader, never a model import. An operational-state
  comparison extends the vocabulary (adjacencies, routes).
- A platform whose transport is not gNMI needs a new reader, and verify refuses it until one
  exists.
- **Revisit** if a platform's answers cannot be named by a path and a value.

<a id="d-031"></a>
### D-031 — Verify's assertions are data derived from the bundle

**Status:** Accepted at the baseline (2026-10-31); superseded in part by [D-051](#d-051) on
2026-11-04: the host name is asserted against the device name only where no configuration
could have set it, and a neighbour is judged against the far node's read host name; the rest
stands.

#### Context

Verify asserts that each node's host name is its node name, every cabled port intent
enables is enabled, and every link is an LLDP adjacency seen from both ends. Each is
derivable from what the twin was built from.

#### Options considered

- **Operator-written assertion files.** Rejected: nothing asks for them, and any operator
  surface should be declarative.
- **Assertions as code per check.** Rejected: it would branch on a platform and bypass the
  manifest.
- **Derived from the blueprint.** Rejected: the names the node uses come from the compiler's
  mapping, which is in the bundle.
- **Derived from the bundle's manifest**, beside every twin, carrying the node's names, the
  links and each interface's intended `enabled`. Chosen.
- **Read the configuration back from the node.** Rejected: a per-package read of the
  running configuration is a new mechanism and a research question of its own.

#### Decision

- **Verify's assertions are a pure function of the twin's bundle manifest**: host name, port
  enabled, neighbour, and the `burst` assertion probes add ([D-008](#d-008)).
- **It asserts what is cabled.** A port intent disables, and its link, are skipped at both
  ends, each skip recorded. It asserts nothing of an uncabled port, an omitted interface or
  a lossy mapping's production name ([D-012](#d-012)).
- **A node's configuration is reported from the record's claim** of the bundle it holds,
  labelled as the claim; a claim not held is a finding.

#### Consequences

- A diverged twin is verified against the bundle it was stepping to, its divergence named.
- New assertion kinds are added as data under this entry. Nothing is read back
  ([Constitution IV](constitution.md#iv-fylgja-never-renders-configuration)).
- **Revisit** when an operator needs to assert something intent does not carry.

<a id="d-032"></a>
### D-032 — Verify is advisory: no Fylgja operation acts on its verdict

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Verification reports and never blocks. Verify needs a verdict shape, a status, a place in
the step, and a bound for its waiting form.

#### Options considered

- **A gate**: a nonconforming twin refuses a step. Rejected: advisory means nothing in
  Fylgja acts on the verdict.
- **A document of its own.** Rejected: the findings document with verify's counts suffices.
- **Status `ok` whenever the read succeeded.** Rejected: a script would parse the findings
  for the one thing it asks.
- **The same status as a refusal.** Rejected: it conflates intent not met with a request
  refused at the door, which is a problem document.
- **A status of its own, `nonconforming`, a negative verdict.** Chosen.
- **A waiting verify for every client.** Rejected: a verify that blocks for minutes is a run
  in all but name; the wait belongs inside the step's run.
- **A wait budget per package.** Rejected: it bounds how long a step waits, not a
  platform's behaviour.
- **The record's claim as information only.** Rejected: a diverged twin could verify `ok`
  while running the wrong configuration.

#### Decision

- **Verify reads and changes nothing.** `POST /v1/twins/{name}/verifications` reads every
  node once and answers a findings document: one finding per failed assertion and per claim
  not held, with counts.
- **`nonconforming`** means every node was read and an assertion failed. A node that could
  not be read is never reported as nonconforming.
- **A step's wait runs verify inside the step's run**, until the twin settles or the bound
  (the server's setting) runs out. A step never fails for it; a wait that did not settle is
  a warning.
- **No Fylgja operation acts on the verdict.**

#### Consequences

- A gate, such as a proposed change's check, is a consumer's mapping of the status, outside
  the core.
- A read stops dialling a node that does not answer, so a silent node costs one deadline per
  read and a wait stays inside its bound.
- No verdict carries configuration or a credential
  ([Constitution X](constitution.md#x-report-honestly)).
- **Revisit** if a consumer needs a gate inside Fylgja: that is a new entry, not a flag.

<a id="d-047"></a>
### D-047 — A refusal `commit validate` passes names both its possible causes in one sentence

**Status:** Accepted 2026-11-03. Supersedes [D-028](#d-028) in its first sentence, the one
for a candidate that validates.

#### Context

D-028's first sentence says a refused SR Linux candidate passes `commit validate`, "which
does not run every check a commit does": it implies a check made as the commit applied. On
containerlab 0.81.0 the live tier showed that a parse-time refusal in a configuration whose
echo is cut gets the same answer, `All changes are valid.`, because the refused line never
entered the candidate ([verified-facts.md](verified-facts.md)). For a typo, the sentence
points at a commit-time check that never happened.

#### Options considered

- **Keep the sentence.** Rejected: it misleads on a typo.
- **A third sentence for parse errors.** Rejected: the cut message does not say which case
  it is, so Fylgja cannot choose between the two.
- **One honest sentence covering both.** Chosen.

#### Decision

- **When `commit validate` gives a cut refusal no reason, the finding's message is
  exactly:** `the node's message ends before any reason Fylgja can read, and `commit
  validate` finds nothing wrong with what reached the candidate: the line it refused was
  either checked only as the commit applied, or never entered the candidate (D-047)`.
- D-028's second request, its second sentence and the rest of it stand.

#### Consequences

- The sentence is part of the core's contract, held word for word by the pure tier, as
  D-028's are.
- An operator reading it looks for a typo in the configuration as well as a value outside
  the package's ranges.
- **Revisit** with D-028.
<a id="d-051"></a>
### D-051 — Verify reads both ends of a link, a node it cannot read fails the verdict, and phase 5 runs the burst and not the flow

**Status:** Accepted 2026-11-04; superseded in part by [D-053](#d-053) on 2026-11-04, which
judges a neighbour's `port-id` against the far port's node name, not its production name; the
rest stands. Supersedes [D-031](#d-031) in part: the host name is asserted against the device
name only where no configuration could have set it, and a neighbour is judged against the far
node's read host name. Details [D-008](#d-008) and [D-032](#d-032).

#### Context

Verify's assertions are derived from the manifest ([D-031](#d-031)) and its verdict is
advisory ([D-032](#d-032)). Open before code: the verdict's status when a node could not be
read, since D-032 forbids `nonconforming` for it and `ok` would mislead a script; whether a
link is read from one end or both, since a shut port still lists a far end that restarted in
place while the far end sees none ([verified-facts.md](verified-facts.md)); the claim
assertion for a node with no configuration ([D-048](#d-048)); and how much of the probes
phase 5 builds. The maintainer's call: the probes stay a placeholder, built small, with
traffic still the line the orchestrator's report leads with.

One more came from the builder's reading. D-031 asserts each node's host name is its device
name and each neighbour's `system-name` is the far device's name. The kind's baseline sets
the host name from the node name, but a source-rendered configuration sets the production
hostname, and a device whose production name is no DNS-1123 label is renamed by its reader
([D-038](#d-038)). On a real network both assertions would fail on every configured node,
and every step's wait would run out.

#### Options considered

The host name:

- **Keep D-031's assertions.** Rejected: device names would have to equal configured
  hostnames, case included, and real networks would fail verify until renamed at the source.
- **Carry the hostname in the blueprint.** Rejected for now: a format change and a producer
  change, for a fact verify can read from the node.
- **Read it from the node**: assert the host name against the device name only for a node
  with no configuration, where the baseline guarantees it; for a configured node read it,
  report it, and judge each neighbour's `system-name` against the far node's read host name.
  Chosen: layer 1 stays the judgement, and a hostname is reported, not asserted.

The status when a node cannot be read:

- **`ok` with a warning.** Rejected: a script reading the status would take it for a pass.
- **`nonconforming`.** Rejected by D-032: intent not met and a node not read are different
  facts.
- **`failed`**, with findings 1 saying what it means for verify. Chosen.

The probes in phase 5:

- **Build the flow across the step** (a background ping started before `apply`, read after
  the wait) and the burst. Rejected for this phase: the facts exist, but the probes are a
  placeholder by the maintainer's call, and the flow is the larger half.
- **Omit `loss` from a step's verdict.** Rejected: findings 1 requires it, and silence would
  read as "no probes".
- **The burst alone**, each direction of each probe, and a `loss` entry of `not_started`
  per probe and direction. Chosen.

#### Decision

- **Verify reads, per device node**: the host name, asserted against the device name for a
  node with no configuration and otherwise read and reported as an info finding;
  `port.enabled` on every cabled port, a link's end or a probe's endpoint; `port.neighbor` on
  both ends of every intent link, each end's `system-name` judged against the far node's
  read host name and its `port-id` against the far port's production name; and the record's
  claim for a node with a configuration. The reads are gNMI by the package's `conformance`
  paths ([D-030](#d-030)), with the library of [D-052](#d-052). A neighbour assertion whose
  far node could not be read is a skip, not a failure, and the verdict is `failed` for the
  unread node.
- **Skips, each an info finding**: a port intent disables and its link, at both ends; a
  synthesized link's neighbour; the claim of a node with no configuration; a configured
  node's host name.
- **The burst** runs by `exec` ([D-049](#d-049)) from host `a` to `b` and from `b` to `a`,
  the package's count and wait, held when every echo is answered.
- **Status**: `ok`; `nonconforming` when every node was read and an assertion failed;
  `failed` when a node could not be read (`verify.node.unread`, naming the node and what
  failed), whatever else was found. Findings 1's comment says that for verify, `failed` means
  the read did not complete.
- **Verify is refused `409`** (`twin.not_running`) on a twin with no applied deployment. A
  stepping or diverged twin is read as it stands, against the bundle it is stepping to
  ([D-031](#d-031)).
- **A step's verdict** lists each probe of the target bundle in both directions with the
  loss outcome `not_started`, and findings 1 says in that value's description that flows
  across a step are not built in this phase.

#### Consequences

- The rule catalogue gains `verify.host_name`, `verify.port.enabled`, `verify.port.neighbor`,
  `verify.claim`, `verify.burst`, `verify.skipped` and `verify.node.unread`.
- `fylgja-core twin verify` exits 1 on `nonconforming` and `failed` ([D-026](#d-026)).
- The flow across the step returns as its own entry when a probe is wanted for real; the
  facts of 2026-10-29 stand for it.

<a id="d-052"></a>
### D-052 — Phase 5's library: pygnmi for the gNMI reader

**Status:** Accepted 2026-11-04; added to by [D-054](#d-054) on 2026-11-04: the reads of a
step's wait run on daemon threads, sixteen at most and one per node; the rest stands. Adds to
[D-039](#d-039).

#### Context

Verify reads a node's facts over gNMI ([D-030](#d-030)), which is gRPC. The core's
dependencies carry HTTP alone (httpx), and every measurement so far used the `gnmic` tool
by hand. SR Linux answers gNMI over TLS on 57400 with a boot-time certificate, cEOS in
plaintext on 6030, both in `json_ietf`, as the packages state.

#### Options considered

- **`gnmic` as a subprocess**, as containerlab is ([D-018](#d-018)). Rejected: a second Go
  binary to install and pin on every host the core runs on, where containerlab is the runtime
  itself; and its JSON output would be parsed as a second contract.
- **Read over the push transport instead** (SR Linux JSON-RPC `get`, EOS eAPI `show`
  commands), superseding D-030's paths. Rejected: eAPI answers are commands, not paths, so
  the fact vocabulary would need a mapping per command, and D-030 chose paths for a reason.
- **A gRPC client in Python.** `pygnmi` on `grpcio`: a maintained client of gNMI's `Get`
  with the encodings and TLS modes the packages name. Chosen.

#### Decision

- `pygnmi`, pinned with `grpcio` and `protobuf` to releases at least two weeks old, chosen
  when the plan is written. The reader is one mechanism, `fylgja_core.gnmi`, keyed by the
  package's `gnmi` section (TLS or plaintext, the port, `json_ietf`), dialling by the address
  `endpoints` answers, with the boot-time certificate accepted unverified as the packages
  state.
- No other library enters phase 5.

#### Consequences

- The pins move only by the rule for dependencies.
- A platform whose transport is not gNMI still needs a new reader ([D-030](#d-030)).

<a id="d-053"></a>
### D-053 — Verify judges a neighbour's port by the far port's node name, and three refinements of D-051

**Status:** Accepted 2026-11-04. Supersedes [D-051](#d-051) in part: the far port is judged by
its node name; details D-051's skips and the unread node.

#### Context

D-051 judges each end's neighbour `port-id` "against the far port's production name". LLDP
carries the far port as the far node names it (`port-id-type` `INTERFACE_NAME`): SR Linux its
own interface name, cEOS its own, which is one to one with production there
([verified-facts.md](verified-facts.md)). A production name and a node name differ wherever a
package's interface rule states a `node_name`, what the node's OS calls the port
([formats/platform-package-1.schema.json](../formats/platform-package-1.schema.json)).
Verify's code, the rule catalogue and both packages' `port_id` comments already judge against
the far row's `node_name`; D-051's text does not.

Building verify settled three cases D-051 leaves open: a node that reports no host name,
though the kind's baseline and any configuration both set one; a probe whose endpoint intent
disables, which cannot pass by intent; and a probe host the driver's `exec` cannot reach,
where D-051's unread node names device nodes alone.

#### Options considered

- **Judge the `port-id` against the far port's production name**, as D-051 says. Rejected:
  wherever a package's rule gives a port a `node_name` other than its production name, every
  neighbour facing that port would fail on a twin wired as intended.
- **Judge it against the far row's `node_name`**, the name the far node's LLDP sends. Chosen:
  it is the name the far node itself reports, as the `system-name` is judged against the far
  node's read host name; on the shipped packages, whose rules state no `node_name` for a data
  port, the two names are one.

#### Decision

- **A neighbour's `port-id` is judged against the far row's `node_name`**, and the failure's
  message names the far port by it.
- **A device node whose host-name leaf is unreported fails `verify.host_name`**, whatever its
  configuration: the kind's baseline and any configuration both set one, so none is a fault
  and not a value to report. The neighbour assertions facing it are skips, since there is no
  host name to judge them against.
- **A probe whose endpoint port is intent-disabled has both bursts skipped**, each an info
  finding naming the port, and runs no echo: the probe cannot pass by intent.
- **A probe host the driver's `exec` cannot reach is an unread node**: one
  `verify.node.unread` naming the host, its burst a skip, and the verdict `failed`, as for a
  device node the reader cannot read.

#### Consequences

- [`docs/rules.md`](../docs/rules.md)'s verify table says so: `verify.port.neighbor` by the
  far port's node name, `verify.host_name` for a node that reports none, the skips of the
  bursts and of the neighbours facing a node with no host name, and `verify.node.unread` for a
  probe host.
- The pure tier exercises all four on the fake reader and driver
  (`core/tests/test_verify.py`). The live tier holds the first on both kinds, where the
  shipped packages' node names are their production names; it does not reach the other three.

<a id="d-054"></a>
### D-054 — The step as built: its dispatch, its record before `applied`, the spec it answers to, and its endings

**Status:** Accepted 2026-11-04; added to by [D-055](#d-055) on 2026-11-04: the stray deploy's
wait, item 14, is `destroy`'s too, and a stray ends at its next write once the core is gone;
superseded in part by [D-056](#d-056) on 2026-11-04: a stray runs to completion.
Supersedes [D-050](#d-050) in part: the dispatch, the record before `applied`, the generation a
run works toward, the cancel's and the ending's readings, and a refused step's verdict. Details
[D-029](#d-029) (the record a diverged twin keeps) and [D-051](#d-051) (the bundle verify judges
a stepping twin against); adds to [D-052](#d-052) (the threads the wait's reads run on).

#### Context

D-050 fixed the step's phases, refusals, resume and cancel before code. Building it (phase 5,
plan 5) found what D-050 leaves open or can be read two ways: when a twin has "an applied
deployment", since a create's cleanup clears what it applied and a create killed after
`planned` names a deployment no lab runs; where a step's phases are recorded while the twin
still runs its old bundle, which [design/core.md](core.md) left to the builder; where "the
generation it took the run under" lives across a kill; whether a transient failure ends "an
`apply` started"; what a cancel or a refusal read after the last phase does; what a refused
step's verdict and an unchanged step's conditions say; what becomes of a queued run no pass
takes; and on what threads the wait's gNMI reads run.

The branch's final review found four more. A step refused on a diverged twin wrote its own
`last_step` over the diverged step's, which D-029 keeps. A spec a client writes mid-run replaces
the record's, since the loop writes its status over the client's record, so an older run could
restart a node under a newer spec's `allow_restart`, the phase's anti-goal. A node missing from
the lab counted as silent in a step's resume probe, so a step cut short before its deploy made
a node it adds ended diverged, though an added node needs no `allow_restart`. And a core killed
mid-deploy leaves `containerlab deploy` running in its own session, which a step's resume,
deploying again plainly, would run beside.

#### Options considered

- **Dispatch by the deployment id alone.** Rejected: a create killed or refused after
  `planned` names a deployment with no lab, and a step would diff from a lab that is not there.
  **By Ready True.** Rejected: a refused or cancelled step leaves Ready False while the twin
  runs, and a new spec must step it, not create over it. **By a deployment id and the nodes an
  apply left.** Chosen.
- **Move `status.phase` with the step from `compiled`.** Rejected: until `applied` nothing is
  touched, and a kill would leave a record naming a target no lab runs. **Record the phases
  before `applied` in `last_step.phase` alone.** Chosen; the cost is that `status.phase` shows
  the running twin's phase until `applied`, and a client reads the step's from `last_step`.
- **Keep the generation a run works toward in the pass alone.** Rejected: a kill loses it, and
  the resume would observe the latest generation, swallowing a spec written meanwhile, as phase
  4's loop did. **In the record.** Chosen: a format change D-050 did not list.
- **An `apply started` followed by a transient `apply failed` is an apply that ended.**
  Rejected: the failed apply may have partly landed, and the next pass would apply without
  probing. **Any `apply started` of the run begins the apply.** Chosen.
- **An uncompilable target writes no `last_step`.** Rejected: the record would not say the spec
  was not reached, nor where its verdict is (D-050). **`from` and `to` both the running
  bundle.** Chosen, since the schema requires both; the cost is that `to` names no target.
- **An unchanged step leaves Ready as it was.** Rejected: a refused twin given back the spec it
  runs would stay Ready False while it runs what is asked. **Ready True.** Chosen.
- **A queued run no pass takes stays queued.** Rejected: its watch never ends, and the API
  queues by the dispatch rule as it reads the record, which a later pass may read otherwise.
  **It ends, superseded.** Chosen.
- **The wait's reads on a thread pool.** Rejected: an executor's workers are joined at exit, so
  a read that never answers holds the server's exit. **Daemon threads.** Chosen.
- **A refusal of a diverged twin writes its own `last_step`, as every refusal does.** Rejected:
  it erases the record D-029 keeps of where the diverged step stopped. **The diverged step's
  `last_step` stays.** Chosen.
- **The record's `allow_restart`, whatever its generation.** Rejected: an older run would
  restart a node under a newer spec's permission. **The run's `allow_restart` kept in the record
  too.** Rejected: a second format change for one boolean. **`allow_restart` trusted only while
  the record's generation is the run's.** Chosen. Its cost falls on a run whose own spec allowed
  a restart when a client writes a newer spec during it: before its apply began it is refused at
  `planned`, and the next run steps the newer spec; on a resume into its begun apply, whose pure
  re-plan skips the restart check the pass that began the apply passed, it ends
  `step.node.silent`, diverged, only when the probe finds a node silent, where the run's own spec
  would have allowed the reconfigure. With every node answering it applies plainly and ends
  stepped.
- **A node missing from the lab is silent in a step's probe, as in a create's.** Rejected: a
  plain deploy makes a node whose container is gone anew ([verified-facts.md](verified-facts.md),
  0.81.0). **Not silent.** Chosen.
- **A stray deploy killed.** Rejected: a deploy killed part-way leaves a partial lab, the fault
  the probe exists to remedy. **The deploy skipped while the lab is present, as a create's probe
  skips it.** Rejected: a step's lab is always present. **Waited for, within the deploy's
  budget.** Chosen.

#### Decision

1. **Dispatch.** A step runs when the spec's generation is ahead, `status.deployment_id` is
   set, `status.nodes` is non-empty (a lab was applied) and no create run is in flight;
   otherwise a create, so a twin whose create never applied is created again. The API queues a
   run of the kind the same rule reads from the record.
2. **The record before `applied`.** A step's phases `compiled`, `admitted` and `planned` are
   recorded in `last_step.phase` alone; `status.phase`, `bundle_id`, `blueprint_id`,
   `deployment_id` and `nodes` keep describing the running twin until `applied` moves them to
   the target. A resume after `planned` plans again, purely, to the same deployment id, and
   refuses again before it touches anything; into an apply already begun, all but the restart
   check, which the pass that began the apply passed under the run's own spec.
3. **The generation a run works toward** is written into the record when the run is taken
   (`status.generation_in_flight`, twin record 1), kept on a resume whatever the generation has
   become since, and copied to `observed_generation` when the run ends, so a spec written
   meanwhile is the next run's. The run's own spec decides what it may restart:
   `allow_restart` counts only while the record's generation is the one the run was taken
   under, and is read as false otherwise, by the restart check at `planned` and by the
   reconfigure of a resume's probe; a resume into a begun apply does not make the restart check
   again (2).
4. **Refusals** come at `compiled` for a diverged twin, before the unchanged short-cut, and at
   `planned` for the rest, in the order diverged, relink or unsupported, restart: what no spec
   setting can fix first. A `changes` that cannot read the running deployment, which names a
   node no loaded package runs, is `bundle.rejected`, and so is a running deployment whose
   bundle names a package this core has not loaded, found before the run starts. A refused
   step's verdict names what the run compiled and planned: the target's blueprint from its
   manifest (the stored target's when the pass that ends the run read none), never a newer
   spec's, the target bundle, and the target deployment once planned. An uncompilable target
   records `last_step` with `from` and `to` both the running bundle, at `compiled`.
5. **An unchanged step** ends `ok` with Ready True for `twin.ready` and Stepping False.
6. **The apply has begun** whenever the run's events hold an `apply started`, of any pass; a
   transient `apply failed` is no end. From then every failure and every cancel ends the step
   `diverged`, with `step.diverged` beside the failure's finding; a cancel before it ends the run
   `failed` with `run.cancelled`, `last_step` `cancelled`. A cancel or a refusal read once
   `last_step.phase` is `flows` ends the step
   stepped, since it had completed. A resume into a begun apply probes the lab: a node missing
   from it is not silent, since the plain apply that follows makes it; one present but stopped,
   without an address or not answering is, and without the run's `allow_restart` the step ends
   `diverged` with `step.node.silent`.
7. **Each ending's record.** Stepped or unchanged: Ready True and Stepping False for
   `twin.ready`. Rejected, or cancelled before its apply began: Ready and Stepping False for the
   rule, `run.cancelled` for a cancel, the twin running what it ran. Diverged: Ready and
   Stepping False and Diverged True for `step.diverged` or `step.node.silent`; Diverged is never
   set back. `last_step` takes the ending's outcome, and a run that ends before `compiled` wrote
   one records `from` and `to` both the running bundle, at `compiled`. On a twin diverged
   already, the diverged step's `last_step` stays, its bundles, run and phase (D-029): a later
   run refused or cancelled writes only the conditions, the observed generation and no run.
8. **An ended step is settled from its verdict first.** A pass that finds the record naming an
   ended step run completes the record's last write from the verdict before anything else, on
   any core, since a step tears nothing down. A core that does not serve the twin's driver ends
   a step in flight `rejected` before its apply began, `diverged` with `step.diverged` after it,
   and `ok` once every phase has run.
9. **The verdict's members.** The last verify's findings and counts and the wait come from the
   pass that ran `verified`: a step resumed after it carries neither counts nor a wait. A step
   that ends stepped always lists its flows, each probe of the target from each host
   `not_started` (D-051), whichever pass ends it.
10. **A run superseded.** When a pass takes a create or step run afresh (one it makes, the
    loop's own, or the newest queued of the operation), every other create or step run of the
    twin still queued, or queued and marked cancelling by a client, ends `failed` with
    `run.cancelled`, superseded before it started, its message naming the run taken. A resumed
    run supersedes nothing, and a destroy run is never superseded.
11. **A twin whose step has not recorded `applied`**, stepping or diverged during its apply, is
    verified against the bundle its record names, the running one; from `applied` on that is the
    target, the bundle it is stepping to (D-051). Its deletion destroys the running deployment,
    with that deployment's files.
12. **Ready and push select by the node's hold.** A node is readied and pushed when it holds
    nothing: added, its incarnation moved, or restarted or recreated by `changes`, since a
    runtime may restart a node in place and keep its incarnation. It is pushed when its
    configuration's checksum differs from the one it ran; any other is marked holding the target
    without a push.
13. **The reads of the wait** run on daemon threads, sixteen at most and one per node, so an
    abandoned read holds neither the other nodes' reads nor the server's exit (adds to D-052).
14. **The local driver waits for a stray deploy.** Before it removes a hot-add container or
    deploys, `apply` waits, polling every second within the deploy's budget, for every
    `containerlab deploy` whose command line names the twin's topology file to end, and logs
    once that it waits; one still running past the budget is `DriverFailed`, which the loop
    retries. A scan of `/proc` finds them, injectable for the pure tier.

#### Consequences

- Twin record 1 gains `status.generation_in_flight` and the `last_step` outcome `rejected`;
  its `last_step` description says a diverged twin keeps the diverging step's.
- The rule catalogue's Steps section ([docs/rules.md](../docs/rules.md)) states the refusals,
  the endings and the conditions above.
- The live tier of plan 6 exercises 1, 4, 6 and 14 on containerlab 0.81.0, the last with a
  server killed mid-deploy, and records what it finds in [verified-facts.md](verified-facts.md).


## Process and repository

<a id="d-033"></a>
### D-033 — A lighter process: design document, decision entry, pull request

**Status:** Accepted at the baseline (2026-10-31).

#### Context

A scripted chain of specification stages with repeated closing passes suits a teaching
project; its closing passes take about a third of each feature's time and do not end by
their own rule. A production project needs a process that records decisions
and keeps changes reviewable, and no more.

#### Options considered

- **The chain, trimmed.** Rejected by the maintainer.
- **The chain for the orchestrator alone.** Rejected by the maintainer: one process for the
  repository.
- **Design document, decision entry, pull request.** Chosen.

#### Decision

- A change is a design document, then a decision entry where it changes a decision, then a
  pull request. A change to a format is made in `formats/`, in the same change as the code.
- This log is append-only, and [verified-facts.md](verified-facts.md) records what was
  verified against a running system.
- The constitution, [constitution.md](constitution.md), binds both deployables; its
  amendment history lives in git.

#### Consequences

- [CONTRIBUTING.md](../CONTRIBUTING.md) describes the flow, and a new term goes in
  [glossary.md](../docs/glossary.md) in the same change.

<a id="d-034"></a>
### D-034 — Tests are tiered by cost

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Fylgja integrates with containerlab, clabernetes, network operating systems and, through
the orchestrator, a source of truth, each slow or heavy to run. Its tests must be cheap
enough for every change, and real where the integrations are most likely to surprise.

#### Options considered

- **Everything real, always.** Rejected: ten minutes or more per change, which one lab host
  cannot run often; people stop running it.
- **Mock-heavy.** Rejected: fakes encode assumptions about the integrations most likely to
  surprise.
- **Recorded interactions.** Rejected: recordings go stale as the systems evolve.
- **A pure core, tiered by cost.** Chosen.

#### Decision

- **Pure tier**, on every pull request, with no infrastructure: the model, the compiler,
  every driver's `plan`, the packages, the failure, cancellation and cleanup paths, and the
  loop's queue.
- **Contract tier**: real systems, never fakes; a real Infrahub for the orchestrator.
- **Live tier**: booted network operating systems on the local driver, on demand. It never
  gates a change.
- **Driver conformance suite**: one set of scenarios on each driver's own runtime, a cluster
  for clabernetes.

#### Consequences

- The compiler's purity is enforced by a test ([D-010](#d-010)).
- The fixtures under `testdata/blueprint/` serve both the pure tier and demonstrations.

<a id="d-035"></a>
### D-035 — The schemas' `$id` namespace is the repository's GitHub URL

**Status:** Accepted at the baseline (2026-10-31).

#### Context

Every schema carries a JSON Schema `$id`, and the schemas refer to one another by those
ids. A validator that resolved `$id`s by fetching would fetch whatever is served there,
under this project's name. Nothing here fetches: the id is the name a document is
registered and referred to by.

#### Options considered

- **A domain the project does not control.** Rejected: someone else may serve it.
- **The company's domain.** Rejected: nothing is served there either.
- **A URN.** Rejected: valid but unfamiliar.
- **The repository's URL as the prefix.** Chosen.

#### Decision

Every `$id` is under `https://github.com/happypathnetworking/fylgja/schemas/`, and
cross-document `$ref`s are relative to it. The ids are identifiers: nothing is served at
those paths, and nothing resolves them.

#### Consequences

- The namespace is metadata, not part of any format, so it moves no format version.

---

<a id="parked"></a>
## Parked

Directions neither adopted nor rejected until the scope that needs them is planned. Each
becomes an entry then.

- **Firewall staging.** A firewall platform is staged: its network configuration first, its
  policy later, traffic validation last. Policy and traffic validation need more than a
  pushed configuration and a read of the node. Parked because no firewall platform is
  planned.
- **Production state collection.** A twin is built from intent alone, and nothing compares
  it with the network it models. That is a stated limitation; read-only substitutes for it
  are a later decision.
- **The platform order's tail.** After SR Linux and EOS ([D-016](#d-016)), Cisco IOL is
  next, then PAN-OS. IOL needs no KVM, and its image is account-gated, as cEOS's is. PAN-OS
  is a licensed virtual machine and waits for a runtime with KVM.

<a id="open-questions"></a>
## Open questions

- **An SR Linux configuration marker after a pod replacement** on clabernetes
  ([D-015](#d-015)). In one reading the marker was present after a link-mode switch to
  `restart` or `recreate` replaced the pod, and absent after the switch to `live`.
  Unexplained. The multi-host trial pushed no marker, so it was not re-checked there; the
  driver conformance suite's step scenarios read it.
- **Scheduling at the packages' requests.** The multi-host trial ran on clabernetes' default
  requests (200m CPU, 512 Mi), so neither the spread nor the drain was exercised with the
  packages' 0.5 CPU and 1.5–2 GiB ([D-036](#d-036)). The driver conformance suite's
  five-twin scenario does.
- **The Temporal fallback** ([D-023](#d-023)). Whether the core killed mid-run on
  clabernetes resumes without a manual step.
- **A cEOS node with no data link refuses `ip routing`**: its forwarding agent never starts
  ([verified-facts.md](verified-facts.md)), so the push of a configuration carrying it is
  refused. Whether the compiler reports it as a finding, or the driver gives such a node a
  port, is open.
