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
  superseded it. Decisions taken before the baseline are recorded in the project's archived
  repository, and so are the prototype orchestrator's (reading Infrahub, stages, the checks,
  the rehearsal's report), which bind nothing here: those kept were restated in
  [D-082](#d-082), [D-086](#d-086), [D-087](#d-087) and [D-088](#d-088).
- **Citing an entry.** Cite it by its number, `D-0NN`, and link it by its anchor:
  `decisions.md#d-0nn` from `design/`, or `design/decisions.md#d-0nn` from the repository root.
- **The frozen Go core**, in the archived repository, was the reference implementation of
  the core ([D-001](#d-001)) and is retired ([D-081](#d-081), [D-094](#d-094)). Where an
  entry describes its behaviour, it says so.

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
| [D-057](#d-057) | The clabernetes driver: a namespace per twin, files that hold no credential, and pods as incarnations | Runtimes and drivers |
| [D-058](#d-058) | The seam's tenth call, `events`: a driver names the twins whose runtime changed | Runtimes and drivers |
| [D-059](#d-059) | A twin's NetworkPolicy also admits the core's namespace | Runtimes and drivers |
| [D-060](#d-060) | The clabernetes driver is developed on the three-server k3s cluster; kind is retired | Runtimes and drivers |
| [D-061](#d-061) | The object store is S3 by conditional writes, signed in the core, with Versity in development | The reconcile loop and state |
| [D-062](#d-062) | On a cluster the core is one pod under a Lease, deployed by kustomize from an image built in the tree | The reconcile loop and state |
| [D-063](#d-063) | TLS ends at the server | The API and its clients |
| [D-064](#d-064) | Phase 6's libraries: lightkube for Kubernetes, and none for S3 | The API and its clients |
| [D-065](#d-065) | Every command the local driver runs gets a stated environment | Runtimes and drivers |
| [D-066](#d-066) | The formats ship inside the package, built from `formats/` | Process and repository |
| [D-067](#d-067) | A kick on a settled twin inspects it, and a replaced node is pushed again under a `restore` run | The reconcile loop and state |
| [D-068](#d-068) | A driver declares whether applying again finishes an apply cut short | Runtimes and drivers |
| [D-069](#d-069) | A clabernetes node's incarnation is its pod's uid and its container's restart count | Runtimes and drivers |
| [D-070](#d-070) | The trigger and the restore as built | The reconcile loop and state |
| [D-071](#d-071) | The core as a pod as built: the Lease's Role, one Kubernetes client above the seam, and the stop at a lost Lease | The reconcile loop and state |
| [D-072](#d-072) | The core's own loop resumes on both drivers; the Temporal fallback is retired | The reconcile loop and state |
| [D-073](#d-073) | Admission by capacity: the runtime's free room, read at `admit`, less the admitted twins' pending demand | Runtimes and drivers |
| [D-074](#d-074) | The local driver deploys one lab at a time | Runtimes and drivers |
| [D-075](#d-075) | Contention becomes waiting, never a verdict: read threads a twin's own, the client's limits bound, eight workers | Pushing, stepping and verifying |
| [D-076](#d-076) | `GET /v1/capacity`: the running driver's reading, for a client that looks before it asks | The API and its clients |
| [D-077](#d-077) | Capacity and the deploy lock as built: the reading is given the reserved twins, a step is judged on the sum, and a pod's request is the scheduler's own | Runtimes and drivers |
| [D-078](#d-078) | Contention as read on the many-twins runs: no bound on the node clients, and no wait widened | Pushing, stepping and verifying |
| [D-079](#d-079) | The capacity read as built: `capacity show`, and `read_at` from the core's one clock | The API and its clients |
| [D-080](#d-080) | A phase is built in four stages on an integration branch and lands on `main` as one squash | Process and repository |
| [D-081](#d-081) | Three pieces at three standards: the core, a reader for each source, and an example orchestrator written new here | The project and its shape |
| [D-082](#d-082) | The Infrahub reader: read-only, complete or refused, and a configuration older than its intent is refused | Intent and the blueprint |
| [D-083](#d-083) | The reader speaks plain HTTP through httpx, states the Infrahub versions it passed on, and is tested against a real one | The API and its clients |
| [D-084](#d-084) | What an integrator installs and calls: the core's base install is the model and the client, and the client follows a run | The API and its clients |
| [D-085](#d-085) | The example orchestrator: a rehearsal library, a change source behind a seam, and Prefect at the edge alone | The API and its clients |
| [D-086](#d-086) | The example's rehearsal: one twin a rehearsal, a look before it asks, "ask again" without a retry, and what it leaves out | The API and its clients |
| [D-087](#d-087) | The rehearsal's report: the verdict first, each failure with its message, and no loss | The API and its clients |
| [D-088](#d-088) | A stage mark names its branch, so marks can be written before the proposed change exists | Intent and the blueprint |
| [D-089](#d-089) | The Infrahub reader as built: the stale rule reads every node a configuration renders from, a read is pinned the instant after a write, and the schema is checked by its structure | Intent and the blueprint |
| [D-090](#d-090) | The base install and the client's following as built: four libraries, and a follow that takes no timeout | The API and its clients |
| [D-091](#d-091) | The development Infrahub and its seed as built: `infrahub/` at the root, the task workers given a `.git` directory, and each worker holding the registered commit | The API and its clients |
| [D-092](#d-092) | The example's rehearsal, its clean-up and its report as built: a fourth status, a deletion read until the twin is gone, and no document after a cancel | The API and its clients |
| [D-093](#d-093) | The Infrahub change source, the two checks and the edge as built: four permissions, the head read once the validation has completed, and a draft planned but not rehearsed | The API and its clients |
| [D-094](#d-094) | The cut-over as made: a proposed change rehearsed through Infrahub's own check on both drivers, and what is left to the maintainer's word | The project and its shape |
| [D-095](#d-095) | The NetBox reader: a branch as it stands, complete or refused, its configuration rendered by NetBox at the read | Intent and the blueprint |
| [D-096](#d-096) | The NetBox reader speaks REST through httpx, states the versions it passed on, and is tested against a real NetBox | The API and its clients |
| [D-097](#d-097) | The example's NetBox change source: marks taken as the branch is built, a tag that asks for the rehearsal, and the report a journal entry | The API and its clients |
| [D-098](#d-098) | The NetBox reader as built: the bracket also counts the rows below its open and reads the branch again, a render has five refusals, and an active probes context is an error | Intent and the blueprint |
| [D-099](#d-099) | The NetBox reader's versions and tests and the development NetBox as built: NetBox 4.7.5 pinned two days old, a Compose network off the lab pool, and a contract tier with a marker of its own | The API and its clients |
| [D-100](#d-100) | The example's NetBox change source as built: a branch refused before its tag is taken, a mark held by its blueprint's id, a warning for a branch behind `main`, and Prefect's credential readable in NetBox's changelog | The API and its clients |
| [D-101](#d-101) | The NetBox acceptance as made: a seeded branch rehearsed from its tag on both drivers, the build's output shown to the maintainer counted as their watching, and phase 8's rehearsal made once more | The project and its shape |

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
Superseded in part by [D-081](#d-081) and [D-085](#d-085) on 2026-11-09 (phase 8):
the orchestrator is an example and not a product, a reader for each source is a library of
its own, and Prefect is at the example's edge alone. Its boundary, the API alone, stands.

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
Detailed by [D-081](#d-081) and [D-082](#d-082) on 2026-11-09 (phase 8): the
Infrahub reader is a library of its own, not the orchestrator's adapter.
Detailed by [D-095](#d-095) on 2026-11-12 (phase 9): NetBox with its branching plugin is
read by a reader of its own, on what was read of NetBox 4.7.5 that day.

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
Detailed by [D-081](#d-081) on 2026-11-09 (phase 8): what moves here is the
orchestrator's capability, written new, and the cut-over is the example rehearsing a proposed
change on the new core.
Detailed by [D-094](#d-094) on 2026-11-12 (phase 8's landing): the cut-over as made, and what of
it is left to the maintainer's word.

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

<a id="d-081"></a>
### D-081 — Three pieces at three standards: the core, a reader for each source, and an example orchestrator written new here

**Status:** Accepted 2026-11-09 (phase 8). Supersedes [D-003](#d-003) in what the
orchestrator is and in who reads a source; its boundary, the API alone, stands. Details
[D-005](#d-005): what moves here is the capability, written new. Details [D-004](#d-004): the
reader is a library of its own, not the orchestrator's adapter.
Detailed by [D-091](#d-091) and [D-094](#d-094) on 2026-11-12: what Infrahub fetches lives in
`infrahub/` at the root, not under `orchestrator/`; and the cut-over as made.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): for NetBox the rehearsal's steps do
not change, and its seam and its sentences gain what that entry names.
Detailed by [D-101](#d-101) on 2026-11-13 (phase 9's landing): the NetBox acceptance as made.

#### Context

D-003 made Fylgja two deployables and the orchestrator a product: it read the source,
resolved stages, rehearsed and reported. Its revisit clause names the case that has come:
"once the orchestrator is decided to be a contract rather than a product". On 2026-11-09 the
maintainer described who phase 8 is for. Someone who runs Infrahub takes the core and an
Infrahub integration, and joins them to the orchestration platform they already have, or to
code of their own. The orchestrator's "primary purpose is to serve as an example of how to
integrate fylgja with an existing system"; it "is not meant to be production-ready"; the
Infrahub integration is developed "with some rigor" and "should be usable in a production
workflow". NetBox is to follow, and its user is to rehearse a multi-step proposed change.

D-005 moves the orchestrator here "when the new core runs twins". The prototype in the
archived repository is about 12,000 lines against the Go core's API and formats, of which
about half would carry over unchanged or with small edits. On 2026-11-05 the maintainer read
D-005 as cutting over the orchestrator's capability and not its code.

#### Options considered

- **The orchestrator as a product, moved here** (D-003 as written). Not taken: a user with a
  platform of their own would have to run a second one, or take the reader out of it by
  hand.
- **The reader inside the example**, as the prototype's adapter was. Not taken: the part
  held to a production standard would live in the part that is not, and would learn its
  stages and its workflow engine.
- **The reader inside the core's package.** Rejected by D-003: the core knows no source.
- **Port the prototype.** Not taken: its documents are held byte for byte to the Go core's,
  its tests seed Infrahub through a Go tool, and its flows assume one twin on one host.
- **Three pieces, written new, the prototype the reference.** Chosen.

#### Decision

- **Fylgja ships three pieces.** The **core**, as built. A **reader** for each source, a
  library that turns that source into a blueprint: the first is `fylgja-infrahub`, under
  `readers/infrahub/` ([D-082](#d-082)). And an **example orchestrator**,
  `fylgja-orchestrator`, under `orchestrator/`, which rehearses a proposed change and posts
  the report ([D-085](#d-085)).
- **Their standards differ.** The reader is held to what a production workflow needs. The
  example is honest on its main path and on plain failures, and is not hardened
  ([D-086](#d-086)).
- **Imports run one way**, held by a test over imports: the reader imports the core's model
  and client and nothing of the example; the example imports the reader, the core's client
  and model, and its workflow engine; the core imports neither.
- **Stages, the source's checks and the report's post are the example's**, not the reader's
  (the maintainer, 2026-11-09).
- **Both are written new in this repository**, with the prototype as the reference for
  behaviour. Nothing of its code, its formats or its test data is carried without being read
  against the new contracts.
- **The cut-over of D-005 is this**: once the example rehearses a proposed change through
  Infrahub's own check on the new core, Infrahub's registration moves to this repository,
  the Go core is retired, and the archived repository may go private.

#### Consequences

- [Constitution](constitution.md)'s opening and its principles I and III speak of two
  deployables and of the orchestrator reading sources. It is amended citing this entry: the
  reader is the constitution's "reader", and the example is a client like any other.
- A NetBox user needs a second reader and a second change source ([D-085](#d-085)), and
  nothing of the rehearsal changes.
- The example is not a supported product. A defect in it is a defect in the documentation of
  how to integrate.


<a id="d-094"></a>
### D-094 — The cut-over as made: a proposed change rehearsed through Infrahub's own check on both drivers, and what is left to the maintainer's word

**Status:** Accepted 2026-11-12 (phase 8's landing). Details [D-005](#d-005) and
[D-081](#d-081): what of the cut-over was made, and what was not. Supersedes nothing.
Added to by [D-101](#d-101) on 2026-11-13 (phase 9's landing): the seeded proposed change was
rehearsed through Infrahub's own check once more, on the local driver, and passed.

#### Context

D-081 makes the cut-over this: "once the example rehearses a proposed change through
Infrahub's own check on the new core, Infrahub's registration moves to this repository, the Go
core is retired, and the archived repository may go private". The phase was done when the
maintainer had created a proposed change of a seeded branch and read the rehearsal's report on
it, once with the core on the local driver and once on the cluster
([core.md](core.md#phase-8-the-infrahub-reader-and-the-example-orchestrator-settled-2026-11-09)).
Phase 8's plan 6 made those runs on 2026-11-12, each after a dry run of its own
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"; rulings P5-8, P5-56, P6-22, P6-27,
P6-40, P6-43, P6-46 and P6-47).

#### Options considered

The cluster run's criterion, of which the maintainer said "The rehearsal passed as before":

- **Take the sentence as a reading of the thread.** Not taken alone: the criterion is the
  maintainer's own act, not an inference from their words.
- **Ask.** Chosen. The maintainer confirmed on 2026-11-12 that they had read the cluster
  rehearsal's report in its thread, as in the local run.

#### Decision

- **The acceptance was met on both drivers on 2026-11-12.** Each time, a proposed change the
  maintainer created in Infrahub's UI, of the seeded branch with its two marks, started the
  rehearsal with nothing else done by hand. On the local driver and on the cluster's core,
  reached over TLS, each rehearsal ended `passed`: a twin created at the branch point, stepped
  and verified through the two marks, the head unchanged, the twin destroyed, and the report
  posted in the proposed change's thread. The maintainer read each report there
  ([verified-facts.md](verified-facts.md), "A proposed change created by the maintainer in the
  UI, rehearsed through its own check, on the local driver" and "… on the cluster's core").
- **Infrahub, Prefect and the runner ran on the development host both times.** Plan 6's
  runs, the dry runs first, were the first to run the two checks on a task worker, and the
  first in which a task worker reached Prefect.
- **Infrahub's registration is this repository's**, `.infrahub.yml` at its root, read by the
  development Infrahub from the main checkout's `.git` ([D-091](#d-091)).
- **The Go core is retired**: it gets no more fixes, and nothing tracked here needs it or the
  archived repository to build, test or run.
- **Not made, each the maintainer's to ask for**, being a push or an act outside the phase's
  branches: pointing the registration at this repository on GitHub, which no reading covers,
  and making the archived repository private.
- **One test constant changed in plan 6**, a plan that was to change no code. At its closing
  gate the contract test of a check's cancel failed: the rehearsal had made no call on the
  runtime when the test's deadline passed. The test now gives its check a `timeout` of 660 s,
  so a deadline 420 s after it begins, where it gave 420 s and 180 s, and nothing it tests
  changed. In the plan's two closing runs of the tier the four stages were planned in 187.3 s
  and 211.6 s and `fylgja-step` concluded in 206.5 s and 236.7 s, where plan 5's run of the
  tier had read it at 105.9 s ([verified-facts.md](verified-facts.md), "Prefect 3.9.2").

#### Consequences

- Why the reads had slowed is not established, and is an [open question](#open-questions).
- The contract tier last passed whole at the commit that widened that deadline. The one
  change to code after it was a docstring, and the tier was not run again (ruling P6-47).
- [core.md](core.md)'s "Sequence" marks item 8 done.


<a id="d-101"></a>
### D-101 — The NetBox acceptance as made: a seeded branch rehearsed from its tag on both drivers, the build's output shown to the maintainer counted as their watching, and phase 8's rehearsal made once more

**Status:** Accepted 2026-11-13 (phase 9's landing). Details [D-081](#d-081), which said NetBox
was to follow, and [D-097](#d-097): how the phase's criterion was met. Adds to
[D-094](#d-094): the seeded proposed change rehearsed through Infrahub's own check once more,
under the edge as phase 9 left it. Supersedes nothing.

#### Context

The phase was done when the maintainer had watched a script build a branch in NetBox in steps
and mark each, the branch given its tag, the rehearsal started by that with nothing else done by
hand, and had read its report on the branch's journal, once with the core on the local driver
and once on the cluster; and, beside it, when the reader's contract tier passed, the wheels
installed, phase 8's rehearsal through Infrahub still passed, and every behaviour of NetBox the
code relies on was recorded
([core.md](core.md#phase-9-the-netbox-reader-and-the-examples-netbox-change-source-settled-2026-11-12)).
Phase 9's plan 4 made those runs on 2026-11-13, each of NetBox's after a dry run of its own
([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3" and the end
of "Infrahub 1.11.11"; plan 4's rulings R7, R9 to R14 and R16 of the phase's ledgers).

#### Options considered

What the maintainer's watching of the build is. On the local driver the controller ran the
build while the maintainer watched; on the cluster the controller ran it on the maintainer's
word and showed them its whole output before the tag was asked for:

- **The shown output taken as the watching, on the controller's ruling.** Not taken alone: the
  criterion is the maintainer's own act, and theirs to call.
- **Ask.** Chosen. Asked whether they had watched the local driver's branch being built, the
  maintainer answered "yes"; asked whether the build's whole output shown to them before the
  tag counts as their watching the cluster's branch being built, "it counts" (both 2026-11-13).

Phase 8's rehearsal made once more, whose two checks' validators were made 11.4 s and 11.7 s
past the 120 s the runbook expects them in:

- **Not the run**, as phase 8's runbook had it of a run with no `fylgja-twin` validator 120 s
  after the creation. Not taken: that bound was written to tell a check that never starts,
  and here both validators came, both checks concluded `success`, and the validators were made
  before either check's code began. The runbook now says so.
- **The run counts, recorded as read with the bound passed.** Chosen.

The Infrahub contract tier at the phase's closing gates:

- **Run again at the last plan's head.** Not taken, on the maintainer's word of 2026-11-13.
- **Cited from the commit it last ran at.** Chosen.

#### Decision

- **The acceptance was met on both drivers on 2026-11-13.** Each time the seed's script built a
  branch in the development NetBox in two steps and marked each through that run's core; the
  maintainer set the tag by hand, in the branch's edit form; and that started one run of
  `twin-rehearse` with nothing else done by hand. Each rehearsal ended `passed`: a twin created
  at `main`, stepped and verified through the two marks, the head unchanged, the twin destroyed,
  and the report filed as one journal entry of kind `success` on the branch.
- **On the local driver** the branch was built while the maintainer watched, and they read:
  "The journal includes the rehearsal success report" ("A branch built in steps and marked by
  the seed's script, tagged by hand, rehearsed from its tag on the local driver, built while the
  maintainer watched, and its report as they read it on the Journal tab").
- **On the cluster** the build's whole output was shown to the maintainer before they set the
  tag, which they ruled is such watching, and they read: "The tables and lists render
  correctly" ("A branch built in steps and marked by the seed's script through the cluster's
  core, its build's output shown to the maintainer, tagged by them by hand, rehearsed from its
  tag on the cluster's core, and its report as they read it on the Journal tab"). The deployed
  core ran the image `fylgja-core:ea4cbde1d213`, built at the commit that merged the phase's
  third plan, and pushed and deployed on the maintainer's word; nothing the image holds changed
  after that commit.
- **NetBox, Prefect and the runner ran on the development host both times**, NetBox and the
  local driver's twin together ([D-099](#d-099)), and each run was made from the main checkout
  checked out at the code under test.
- **Phase 8's rehearsal through Infrahub's own check was made once more**, on the local driver,
  the proposed change the seed's and not one made in Infrahub's UI. Both checks concluded
  `success` and the rehearsal `passed`, its summary and detail phase 8's but for the sentence on
  when the stages were read ([D-100](#d-100)) and the run's own values ("The seeded proposed
  change rehearsed through its own check once more, the edge opening the source its setting
  names"). It was made with NetBox up beside it, NetBox's runner stopped, its trigger installed
  and no branch tagged.
- **The contract tiers.** NetBox's passed whole at the last plan's closing gate, 14, 45 and 12
  tests; what followed that commit changed documents, comments, pure tests and
  `scripts/netbox_dev.py`.
  Infrahub's was not run again there: it passed on 2026-11-13 at a commit of the phase's third
  plan, 7, 30 and 11 tests, and since that commit nothing under `infrahub/` or
  `readers/infrahub/` changed, nor anything of the rehearsal library or the Infrahub source,
  and of the edge docstrings and comments alone.
- **One start of NetBox on the merged code.** The last plan's fix wave changed
  `scripts/netbox_dev.py`'s start after the last live start of NetBox, so `make netbox-up` and
  `make netbox-down` were run once more on the merged code, each exiting 0, the network standing
  at the override's range.

#### Consequences

- The Infrahub rehearsal took 600.5 s where phase 8's took 277.2 s, the steps that read
  Infrahub slower and the twin's own not. Why is not established, and is an
  [open question](#open-questions), with the cluster's rehearsal against the local driver's and
  the address no rule of verify reads.
- Of the maintainer's readings, the render of the report's table and lists in a browser is said
  of the cluster's run alone.
- [core.md](core.md)'s "Sequence" marks item 9 done.


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


<a id="d-082"></a>
### D-082 — The Infrahub reader: read-only, complete or refused, and a configuration older than its intent is refused

**Status:** Accepted 2026-11-09 (phase 8). Details [D-006](#d-006)'s producer for Infrahub
and [D-004](#d-004)'s adapter. Restates, for this repository, what the archived repository's
D-012, D-045, D-046, D-048, D-058 and D-060 decided about a pinned read and a stale
configuration; those entries bind nothing here.
Superseded in part by [D-089](#d-089) on 2026-11-12: nothing regenerates unasked; the stale
rule reads every node a configuration renders from, the task workers' account discounted and
`__system__` never; a read is pinned the instant after a write; and the schema is checked by
its structure, at no commit.

#### Context

[Constitution III](constitution.md#iii-the-blueprint-is-the-contract) says what a reader
must do: one documented mapping, every approximation recorded, every finding in one pass, no
blueprint on failure. The maintainer asked what else could go wrong for a user six months
in. The worst is a twin that is quietly not the network: a valid blueprint of less than the
source holds, or of a configuration rendered before the intent it is read with. Infrahub
regenerates an artifact some time after the intent behind it changes, so a read just after
an edit meets the old configuration. The prototype refused such a read, and that rule was
the largest part of its stage code. Part of it read the proposed change's artifact
validation, which a reader that knows no proposed change ([D-081](#d-081)) cannot.

The DCIM library's platform kind holds a name and a manufacturer and nothing that names a
platform package, and the packages hold no source matching ([D-015](#d-015)). The name of
the artifact that holds a device's configuration is the installation's own.

#### Options considered

Staleness:

- **Leave it to the caller.** Not taken: every caller would have to rebuild the rule, and the
  one that does not gets the quietly wrong twin.
- **Refuse it in the reader, the proposed change's part given as a time.** Chosen.

Where the matching and the artifact's name come from:

- **An attribute added to Infrahub's platform kind.** Not taken for the first version: it
  would require a schema of Fylgja's on every installation, where the DCIM library alone is
  required.
- **Environment variables.** Not taken: a table does not fit one.
- **A configuration file for the reader.** Rejected by [D-042](#d-042)'s reasoning where it
  would hold an address or a credential.
- **An input document with a format, given to each read**, as a probe declaration is.
  Chosen. It is not D-006's rejected "mapping declared as data per install": it maps no
  kind and no attribute, and holds two lookups the schema cannot carry.

#### Decision

- **The reader is a typed library with a command of its own**, `fylgja-infrahub`. It takes a
  connection, a branch, a time, a scope and a reader document, and answers a blueprint with
  its source envelope, or the findings that refused it. It checks the schema, reads the
  network, matches platforms to packages, and reads probes where the document asks.
- **It is read-only**: it sends no mutation, and its token never reaches a blueprint, a
  finding, a log line or an error.
- **Complete or refused.** Every list is counted against the total Infrahub answers for it
  ([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"). Every scoped device has its
  configuration artifact, ready, its content matching its checksum. A gap is an error and
  no blueprint, or a fidelity row. Nothing is defaulted in silence.
- **A configuration older than its intent is refused**, by device, with the remedy. How the
  two are told apart is the prototype's rule, a hypothesis until plan 2 reads it on the
  version built against: the latest write to the device's own attributes and relationships
  at the time read, by stamps and by the branch's events, a write by Infrahub's own account
  not counting, against its artifact's checksum stamp. `generated_since` is an optional
  time the caller gives, at which it knows every artifact was regenerated, and it stands for
  the checksum stamp where it is later.
- **No read is pinned at a time from the reader's clock.** A read is pinned at a time
  Infrahub returned or the first instant after one; `observed_at` in the source envelope
  ([D-006](#d-006)) says when the read was made, and pins nothing. `head` answers the first instant after a branch's latest
  write, for a caller that wants the present.
- **The same read gives the same blueprint id.**
- **The schema is checked before the read**, each fault naming the kind, attribute or
  relationship. The first version requires the OpsMill DCIM library at the commit the
  mapping names (the maintainer, 2026-11-09).
- **Every finding names its object in Infrahub**, in findings 1's finding shape, under rule
  ids of the reader's own.
- **The reader document** ([`formats/`](../formats/README.md), a new format) holds the pairs
  of manufacturer and platform with the package id of each, the artifact's name, and whether
  probes are read. It holds no address and no credential: those are `FYLGJA_INFRAHUB_ADDRESS`
  and `FYLGJA_INFRAHUB_TOKEN` ([D-042](#d-042)).
- **The `FylgjaProbe` kind's schema ships with the reader**, and an Infrahub without it is
  no fault unless the document asks for probes.

#### Consequences

- What the reader reads of an artifact (its status, checksum, storage and content, at a
  past time too), the stale rule's stamps, events and own account, a branch's latest write,
  and how the DCIM library's commit is told were read on Infrahub 1.11.2 in the archived
  repository alone. Each is read again on the version built against before code depends on
  it, and the rule is restated if a reading differs.
- A caller that knows of a regeneration the stamps do not show says so through
  `generated_since`. The example's change source fills it from the proposed change
  ([D-085](#d-085)).
- A second schema, or a mapping a user can change, is a later entry.


<a id="d-088"></a>
### D-088 — A stage mark names its branch, so marks can be written before the proposed change exists

**Status:** Accepted 2026-11-09 (phase 8). The maintainer confirmed on 2026-11-09 that "open
the proposed change" means creating it in Infrahub's UI, with marks on the branch so that
the rehearsal has several stages. Restates the archived repository's D-045 for this repository, with
one change: the mark's key.
Superseded in part by [D-093](#d-093) on 2026-11-12: of the two checks only `fylgja-twin`
concludes over a draft without starting anything; `fylgja-step` plans it.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): in NetBox, which reads no earlier
time, a mark is taken by a command of the example's when the step exists, and names a
blueprint the core keeps. This entry's marks, Infrahub's, stand as they are.

#### Context

Phase 8 is done when the maintainer opens a seeded proposed change and that alone starts the
rehearsal. Infrahub 1.11.11 runs a proposed change's user checks at its creation, a draft or
not, and on a run-check; setting `is_draft` to false starts nothing
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"). The prototype's stage kind
required a relationship to its proposed change, so no mark could exist before it. A proposed
change the maintainer creates would be rehearsed at once, with no marks to find.

#### Options considered

- **Marks on the proposed change, the seed making it too**, and the maintainer pressing
  "re-run checks". Not taken: the act that starts the rehearsal is then a re-run, not the
  opening.
- **No marks in the acceptance run.** Not taken: a rehearsal of one step shows less than the
  example exists to show.
- **A new trigger on leaving draft** (a webhook or an event rule). Not taken: a third path
  beside the two checks, for the acceptance run alone.
- **The mark names its branch as text.** Chosen. A mark so keyed was written before any
  proposed change existed, read from the default branch, refused when duplicated, and
  absent from the branch's diff (the same reading).

#### Decision

- **`FylgjaStage` is branch-agnostic and names its branch as text**, with a `label` unique
  within that branch, an optional `as_of` and an optional description. It has no
  relationship to a proposed change. Its schema is the example's, loaded on the default
  branch.
- **A change's stages, in order**: the branch point, read on the default branch at the
  time the branch was cut; each mark of the branch in order of its time; and the head.
- **The operator writes marks; Fylgja reads them.**
- **A draft is not rehearsed.** Infrahub runs the check on it, and the check concludes
  without starting anything.
- **The seeded branch is made after the registration is imported**: a branch runs the checks
  it saw when it was made (the same reading).

#### Consequences

- A mark outlives its branch, and may name a branch that does not exist. The example reads
  marks by a branch's name and cleans up none.
- A source whose change is only a branch, as NetBox's may be, is not at odds with the stage's
  shape.
- What the prototype built around a mark, its orphaning, its refusals after a rebase and
  its warnings, is not restated. One line of it is kept where plan 5's reading allows: the
  report says when the default branch has moved since the branch was cut.
- The time a branch was cut, what a rebase does to it, and a mark's time where `as_of` is
  absent were not read. Plan 5 reads them first, and a mark with no `as_of` is refused if
  Infrahub gives its writing no time.


<a id="d-089"></a>
### D-089 — The Infrahub reader as built: the stale rule reads every node a configuration renders from, a read is pinned the instant after a write, and the schema is checked by its structure

**Status:** Accepted 2026-11-12 (phase 8's landing). Supersedes [D-082](#d-082) in four parts:
what its Context says of regeneration, what the stale rule reads, the time a read is pinned
at, and how the schema's library is told. Details it in `generated_since`, in `head` and in
which devices are judged. The rest stands.

#### Context

D-082 called its stale rule "a hypothesis until plan 2 reads it on the version built against",
and said the rule is restated if a reading differs. Phase 8's plan 2 read Infrahub 1.11.11
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11", "What a stale rule can be built
on"), and plan 3 built the rule on those readings (rulings P2-25, P2-30, P3-24 to P3-31, P3-36,
P3-38, P3-42, P3-44, P3-45, P3-50 and P3-51 of the phase's ledgers). The readings differed from
what D-082 supposes in five places.

- **Nothing was regenerated unasked.** D-082's Context has Infrahub regenerate an artifact "some
  time after" its intent changes. On 1.11.11 an artifact was rewritten only when a generation
  was asked, so a stale configuration stays stale until someone asks.
- **A configuration's intent is more than "the device's own attributes and relationships".**
  An address's edit moved the address's own stamp alone, and its event named the address
  alone; an address made moved its port's stamp and logged no event. A removal left no stamp,
  or moved one back, and only an event showed it.
- **"A write by Infrahub's own account not counting" is required, and not enough.** The task
  workers' account restamps the nodes that join a query group after a generation, so a
  newest-stamp rule with no discount reads stale right after every generation. An operator's
  create and edit of an address are written as `__system__`, so that id can never be
  discounted. And a discount loses an operator's write that lies under a restamp.
- **A read pinned at exactly a write's stamp** answered the write's values with the earlier
  stamps; a microsecond after, the write. D-082's "a time Infrahub returned" is unsafe for a
  write's own stamp.
- **Nothing on the instance names the schema library's commit.** A kind's hash is the
  instance's own: one file loaded on two branches gave two hashes.

#### Options considered

What the rule reads beside the device:

- **The device's own stamps and events**, as D-082 words it. Rejected by the readings: an
  address's edit would go unseen.
- **Every node stamp of everything the template touches**, the platform's, the manufacturer's
  and each cable's far end's among them. Rejected: a device made on a shared platform moves the
  platform's node stamp, and an address made on a neighbour moves the far port's, so every
  device beside them would read stale for a write its configuration does not render.
- **The members of the artifact's internal query group**, which lists the nodes its query
  read. Not taken: it was not read, and it is named in the reader's `mapping.md` as the
  direction to read next.
- **The device's own nodes whole, and of the platform, the manufacturer and each cable's far
  port and far device their names alone**, since the names are what the configuration renders
  of them. Chosen.

Which events are a device's:

- **An event naming the device's platform among its related nodes.** Rejected: a device made
  elsewhere names the shared platform there, and every device on it would be refused.
- **An event whose primary node is one of the nodes above, or whose related nodes name one of
  the device's own.** Chosen.

How the schema's library is told:

- **A hash or a commit**, as D-082's "at the commit the mapping names" supposes. Rejected: the
  instance holds neither in a form that can be compared.
- **The structure of the kinds the mapping reads.** Chosen.

#### Decision

1. **The stale rule reads what a configuration renders from**: the device's own stamp; each of
   its interfaces', of either kind; each address's on them; each cable's at its ports; and the
   `name` attribute's stamp of its platform, of its manufacturer and of each cable's far port
   and far device, whether or not the far device is in the scope.
2. **The task workers' account is discounted, and `__system__` never.** A stamp last written
   by an account that made the query groups of the scope's artifacts counts at the node's
   creation and not at the restamp. Nothing but an account's name tells it from an operator's.
3. **The events are read too**: the branch's own, and `main`'s where they occurred no later
   than the branch was made, since a branch inherits a configuration already stale on `main`
   with the write that made it so. An event is a device's when its primary node is one of
   the nodes of item 1, a far end's only where it names the attribute `name`, or when its
   related nodes name one of the device's own: the device, an interface, an address or a
   cable. The platform and the manufacturer count through events whose primary node they
   are, alone. The reverse relationships a platform's `devices` and a manufacturer's
   `platforms`, and the group, artifact, profile and template relationships, are no intent.
   An event the task workers' account wrote, or one later than the time read, counts for
   none.
4. **A device is stale when the latest of its stamps and events is strictly later than when
   its configuration was generated**: its artifact's checksum stamp, or `generated_since` where
   that is later. A `generated_since` later than the time read is refused (`at.invalid`): it
   vouches for a regeneration the bytes read at that time cannot carry. The events are read
   from the later of the scope's earliest checksum stamp and `generated_since`, since no event
   before that floor can change a verdict.
5. **Every scoped device's artifact is selected, fetched and judged**, whether or not a
   package was chosen for it, so that every finding comes in one pass
   ([Constitution III](constitution.md#iii-the-blueprint-is-the-contract)).
6. **A read is pinned the first instant after a write, never at the write's own stamp.**
   `head` answers a microsecond after the branch's latest write, in the layout Infrahub
   answered the time in. It takes the latest of every stamp of item 1, of the platform's and
   the manufacturer's node stamps and of each checksum's, nothing discounted; of every
   `FylgjaProbe`'s stamp where the branch's schema holds the kind; and of every event of the
   branch's history, intent's or not. It checks the schema first.
7. **Only `head` raises its refusal**, `Refused`, carrying the findings: `scope.*`,
   `read.incomplete` and `schema.*`. It answers a bare time and has nowhere else to put one.
   `read` answers a result whose blueprint is absent where a finding is an error.
8. **The schema check compares structure**: the names, attributes and relationships of the
   kinds the mapping reads, the generics its queries select through among them, each
   difference a `schema.*` finding naming the branch. The commit in the reader's mapping is
   the mapping's claim of what it was written against, and is not verified; the hash in the
   source envelope is the instance's.

#### Consequences

- Where the rule was given a choice it errs toward refusing: a write it counts and a template
  does not render refuses a read that could have passed. What it cannot see is a write to
  something a template renders that is none of item 1, such as an attribute of a far end or
  of a platform other than its name, which counts by its event alone or not at all.
- What the rule does not yet rest on a reading of is listed in the reader's `mapping.md`,
  "The stale rule": an artifact reading `Error`, a device's platform changed, an address moved
  to another port, a rebase, and whether a proposed change's validation regenerates an
  artifact with other bytes, among others.
- A read's events are every event of the logs read since the floor, 50 a page, whatever the
  scope. What that costs as an instance's history grows is an
  [open question](#open-questions).
- A `head` taken within about 10 s of a write may answer a time a write falls after, since
  Infrahub logs a write's events up to seconds after it; the caller waits that out, as the
  seed and the example's change source do.
- [core.md](core.md) says the rule and the schema check as built.


<a id="d-095"></a>
### D-095 — The NetBox reader: a branch as it stands, complete or refused, its configuration rendered by NetBox at the read

**Status:** Accepted 2026-11-12 (phase 9). Details [D-004](#d-004): NetBox with its branching
plugin is read by a reader of its own. Builds on [D-081](#d-081), and holds this reader to
what [D-082](#d-082) holds the Infrahub reader to, restated for what NetBox is.
Superseded in part by [D-098](#d-098) on 2026-11-13: the bracket is the changelog's latest id,
the count of the rows at or below the open's id and the branch's own row read again, a sync
moving neither changelog; two kinds of row do not count, above the open's id alone; a render
has five refusals; a cable a refused device ends is neither a link nor an omission; a sync is
guarded; and the envelope's id is not the whole point in time of a branch.

#### Context

[D-081](#d-081) said NetBox was to follow, with a reader of its own. On 2026-11-12 the
maintainer asked for feature parity with the Infrahub integration, then set its bound:
"complete parity isn't a reasonable requirement. Let's get it as close as we can."

NetBox 4.7.5 with netbox-branching 1.2.3 was read on that day
([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3"). A
branch is read by a header on any request, as it stands; nothing reads it as it stood
earlier. A device's configuration is not stored: NetBox renders it on request from a
template, for the branch the header names, and the same state rendered the same bytes each
time. A device with no template answers 400 and a template that fails 500, each with its
reason. A REST list answers a `count`; no total was found in GraphQL. An interface carries
`enabled` and `mgmt_only` as its own members, where the DCIM library the Infrahub reader maps
has neither. A platform carries its manufacturer. A configuration context that is inactive
is in no device's rendered context and is still read by its name.

[D-082](#d-082)'s worst case, a twin that is quietly not the network, has another cause
here. There is no artifact to fall behind its intent. But a read is tens of requests with no
instant in common, and an edit made between two of them gives a blueprint of a network that
never was.

#### Options considered

How NetBox is read:

- **GraphQL**, as the archived repository's spike read it. Not taken: no total was found in it, so
  no list could be counted against one, and the renders are REST's whatever reads the lists.
- **REST alone.** Chosen.

Keeping a read to one state:

- **Nothing.** Rejected: it is the quietly wrong twin.
- **Reading everything twice and comparing.** Not taken: twice the requests, and two reads
  that agree may both straddle an edit.
- **The changelog's latest id, taken before and after.** Chosen. An edit made under a branch's
  header added a row to that branch's changelog, and one on `main` to `main`'s (the same
  reading). What a sync does to a branch's changelog is not read, and is plan 2's first
  reading.

Where a device's configuration comes from:

- **NetBox's own render.** Chosen: it is what NetBox itself would hand a deployment tool, and
  it follows the branch.
- **A render made elsewhere** from NetBox's data, by a tool the reader calls. Not taken: the
  reader would run another system, or Fylgja would render
  ([Constitution IV](constitution.md#iv-fylgja-never-renders-configuration)).

Where probes are declared:

- **A probe declaration file beside the reader document.** Not taken as the first answer: the
  probes would live outside the source the reader reads.
- **A further plugin for objects of one's own.** Not taken: a second plugin on every
  installation, for one list.
- **A configuration context the reader document names, inactive.** Chosen.

What the two readers share:

- **A package common to both.** Not taken: two readers show too little of what a third would
  need, and the Infrahub reader would be changed to make it.
- **Nothing but the core's model.** Chosen.

#### Decision

- **The reader is a typed library with a command of its own**, `fylgja-netbox`, the package
  `fylgja_netbox` under `readers/netbox/`. It takes a connection, a branch or none for
  `main`, a scope and a reader document, and answers a blueprint with its source envelope, or
  the findings that refused it. It takes no time.
- **It writes nothing to NetBox.** Its one request that is not a `GET` is `render-config`,
  which added no row to a changelog in the renders read. Its token never reaches a blueprint, a finding, a log line or an
  error.
- **Complete or refused.** Every list is read over REST and counted against the `count`
  NetBox answers for it. Every scoped device is rendered. A gap is an error and no blueprint,
  or a fidelity row. Nothing is defaulted in silence.
- **A device's configuration is NetBox's render of it at the read**, one request a device
  under the branch's header, the text verbatim. No template, a template that fails, and an
  empty render are each an error naming the device.
- **A read is of one state.** The reader takes the latest id of the changelog it reads from
  before its first list and after its last render. Where they differ the read is refused,
  with the remedy: read again, unless every row between them is of a kind no read reads, a
  journal entry's first among them. The reader does not read again by itself.
- **The source envelope carries that id**, beside `observed_at`, and no `at`: it is the
  point in time [Constitution VI](constitution.md#vi-intent-is-addressed) asks for, as near
  as NetBox gives one.
- **There is no stale rule**, nothing being stored between an edit and a render.
- **The same state gives the same blueprint id.**
- **NetBox's version is read first.** The reader warns outside the versions it passed on
  ([D-096](#d-096)), and refuses a branch asked of a NetBox that does not name the plugin.
- **One mapping, `netbox-dcim`**, documented in the reader's `mapping.md`: the scope a tag on
  devices; a device's platform and that platform's manufacturer matched to a platform package
  by the reader document; its physical interfaces, with `enabled` and `mgmt_only` as NetBox
  holds them; a cable of two interface ends, both in the scope, as a link, and any other
  cable omitted with its reason.
- **Every finding names its object in NetBox**, in findings 1's finding shape, under rule ids
  of the reader's own, the Infrahub reader's kept where the meaning is the same.
- **The reader document** is a new format, `netbox-reader-1`: the pairs of manufacturer and
  platform with the package id of each, and the name of the configuration context that
  declares the probes, or that none are read. It holds no address and no credential: those
  are `FYLGJA_NETBOX_ADDRESS` and `FYLGJA_NETBOX_TOKEN` ([D-042](#d-042)).
- **Probes are an inactive configuration context's data**, a probe declaration held to the
  core's own loader. A NetBox without that context is no fault unless the document names one.
- **The reader imports the core's base install and httpx**, and nothing of the Infrahub
  reader or of the example. A test over imports holds it.

#### Consequences

- A read of a `main` that many hands are editing may be refused more than once. A bounded
  number of further reads inside the reader is a later entry, once a site shows the need.
- The reader's guard sees an edit that the changelog records. What it does not record, if
  anything, is not guarded, and plan 2 reads what a sync and a merge on `main` write there.
- A configuration that a site renders outside NetBox is not read. Such a site needs a reader
  of its own, or a later entry.
- Two readers hold two transports, two sets of findings' sentences and two reader documents.
  What they have in common is seen when a third is written.
- NetBox needs nothing of Fylgja's installed in it for a read: no schema, no plugin, no
  custom field.


<a id="d-098"></a>
### D-098 — The NetBox reader as built: the bracket also counts the rows below its open and reads the branch again, a render has five refusals, and an active probes context is an error

**Status:** Accepted 2026-11-13 (phase 9's landing). Supersedes [D-095](#d-095) in six parts:
what brackets a read, which rows of the changelog do not count, what a render is refused for,
which cables are neither a link nor an omission, what the reader's guard does not see, and what
the envelope's id says of a branch. Details it in an active probes context, in which
interfaces are ports, in what a finding names, in a name NetBox answers twice or not at all, and
in what the reader's token must be. The rest stands.

#### Context

D-095 chose the changelog's latest id as a read's bracket and left to plan 2 "What a sync does
to a branch's changelog", "what a sync and a merge on `main` write there", and which kinds' rows
no read reads. Phase 9's plan 2 read NetBox 4.7.5 with netbox-branching 1.2.3
([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3") and built
the reader on the readings (plan 0's bends and its reconciled item 4; plan 2's rulings C5, R1
to R3, R5 to R11, R15 and R16 of the phase's ledgers). The readings differed from what D-095
supposes, or said what it left open, in these places.

- **A sync adds no row to either changelog, and changes what the branch reads** ("A sync"). The
  branch's `status` went `ready`, `syncing`, `ready`, and its `last_sync` moved. So the latest id
  of a changelog cannot see a sync.
- **A journal entry's row and the branch object's own land on `main`'s changelog alone** ("The
  kinds of a changelog's rows"): a mark, a report and the example's write of a branch's tags each
  add a row to `main`'s during a read of `main`.
- **Under the header of a branch deleted, syncing or merged a list is answered 400**, and under
  a deleted branch's a render too ("A sync", "A merge", "A render under the header of a branch
  that is gone"); so is a list asked by an id NetBox does not hold. A render under a branch
  that is syncing or merged was not read.
- **A render has more answers than D-095 lists.** A device with no template is 400 in NetBox's
  own words, a template that fails 500, and a template that renders nothing 200 with no byte; an
  account without `render_config` is answered 404, though it has just listed the device; and
  NetBox refuses a render to a token that may not write ("Permissions").
- **A key of an active configuration context renders** ("A render of a template that reads the
  configuration context"), so a probes context left active reaches every device it applies to.
- **`?id__lte=` on the changelog is honoured** ("An upper bound on the id"). Whether rows commit
  in the order of their ids was not read.
- **NetBox takes two devices of one name on two sites** ("A device's name, per site").

#### Options considered

What brackets a read through a sync:

- **The changelog's latest id alone**, as D-095. Rejected by the reading: a sync moves neither
  changelog.
- **The branch's `last_sync` carried in the source envelope**, beside the changelog's id. Not
  built: the envelope's members were fixed before the reading was made, and the limit is said in
  the reader's `mapping.md` instead.
- **The branch's own row read again at the close.** Chosen.

A row of a lower id that commits after the open:

- **Nothing more.** Not taken: such a row moves no latest id, and whether NetBox commits rows in
  the order of their ids was not read.
- **The count of the rows at or below the open's id, taken at the open and at the close.**
  Chosen: two requests of one row each.

A 400 answered after the open:

- **Raised as the transport's error.** Not taken: a branch deleted or synced during a read would
  show as a failed request, and a caller that reads again does so on `read.moved` alone.
- **Weighed at the close.** Chosen.

#### Decision

1. **The bracket is three guards, and it closes on every path past its opening.** The latest id
   of the changelog read from, `main`'s or the branch's, is taken before the first list and
   after the last render, and the rows between are listed, held to their `count` and to the
   close's own row. The rows at or below the open's id are counted at the open and at the
   close. And a branch's own row is read before the open and again at the close. A read is
   refused, `read.moved`, where a row between the two ids is of a kind a read reads, where the
   count moved, or where the branch is gone, is no longer `ready`, or was synced, its `last_sync`
   moved. Since the close is always taken, `read.moved` may stand beside another refusal,
   `scope.empty` and `read.incomplete` among them.
2. **Two kinds of row do not count above the open's id**: `extras.journalentry` and
   `netbox_branching.branch` (`bracket.UNREAD`). One committed below the open's id refuses the
   read whatever its kind, the count telling no kinds.
3. **A 400 answered to a request past the open is weighed at the close.** Where the bracket
   moved it is `read.moved`; where it did not, the 400 is raised as it came, or, for a render,
   filed as `render.unavailable`. A 400 to the close's own requests under a branch's header is
   `read.moved`; on `main` it is raised.
4. **A render has five refusals**, each an error naming the device: `render.template.missing`,
   a 400 in the words NetBox answers a device with no template, and in no other;
   `render.failed`, a 500; `render.empty`, a 200 of nothing but whitespace; `render.invalid`, a
   200 that NetBox does not call `text/plain` or that is no UTF-8 text; and
   `render.unavailable`, any other status, among them 404, where its sentence names the
   `render_config` grant. A refused token, 401 or 403, is the transport's error.
5. **An active probes context is an error**, `probe.context.active`, and a context the reader
   document names and NetBox does not list `probe.context.absent`. A declaration stating another
   `probes_version` than 1 goes to the core's loader as it is, which files
   `probes.version.unsupported` and checks nothing else of it.
6. **The mapping.** A port is every interface whose type is not `virtual`, `bridge` or `lag`, a
   wireless type among the ports. A cable is judged for omission first, for the first of four
   reasons: a side of other than one termination, an end that is no interface, an end outside
   the scope or on an interface that is no port, and an end `mgmt_only`, which blueprint 1
   refuses a link on, though both ends be interfaces in the scope. A cable that would be a link
   and ends on a device the mapping refused is neither a link nor an omission: the device's
   refusal is the read's already. Two scoped devices that make one blueprint name are each
   refused, and two of one exact name are told apart by their ids.
7. **A name asked that NetBox answers twice is the transport's error**, the scope's tag, the
   branch and the probes' context alike, before anything is built on the first row. A branch
   name that is empty or whitespace alone is refused before any request: a `ValueError` in the
   library and a usage error at the command.
8. **What a finding names.** Each names its object in NetBox, but these: `read.incomplete` names
   the list by its object type, `scope.invalid` and `scope.empty` the scope,
   `netbox.version.unverified` the pair of versions, and a problem of the blueprint built its
   pointer.
9. **The envelope's `changelog` is the id taken at the close**, null where the changelog holds no
   row. Of `main` it is the point in time
   [Constitution VI](constitution.md#vi-intent-is-addressed) asks for, as near as NetBox gives
   one. Of a branch it is not the whole of it: the envelope does not carry `last_sync`.
10. **The reader's token must be one that may write**, NetBox refusing a render otherwise. What
    keeps the reader from writing is its account's grants: `view` of what a read lists and
    `render_config` on devices, each `view` grant carrying no constraints. Its contract tier
    ends on a test that the reader's connections sent no request but a `GET` and the render.

#### Consequences

- The guard against a sync rests on one reading, that a sync moves `last_sync`. Two reads of one
  branch either side of a sync can carry one `changelog` id for two states.
- What the bracket does not see is listed in the reader's `mapping.md`, "The bracket", and in
  the facts' "Not read": a row pruned at or below the open's id while another commits late; a
  template that renders a device's own journal entries; what lives on `main` alone under a
  branch's read, the reader account's permissions among it; a `view` grant with constraints,
  under which a list and its `count` would be short alike; and a write NetBox makes outside a
  request. None was read.
- A journal entry or a branch's `PATCH` that commits below the open's id refuses a read of
  `main`, and the remedy is the same: read again.
- A NetBox that allowed two of a name would refuse every read until one is renamed, and one
  behind a proxy that relabels a render's content type every read until the rule is widened.
  Each errs toward refusing.
- The count costs two requests a read. Whether a row can commit below a higher one, which it
  guards, is an [open question](#open-questions).
- [core.md](core.md) says the bracket, the renders and the probes' context as built, and the
  reader's `rules.md` and `mapping.md` every rule.


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
Superseded in part by [D-069](#d-069) on 2026-11-05: on clabernetes a link-mode change
replaces the pods of the nodes whose mode changed, not every pod; the rest stands.

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
Superseded in part by [D-058](#d-058) on 2026-11-05: the seam has ten calls, `events` joining.
Superseded in part by [D-073](#d-073) on 2026-11-08: the seam has eleven calls, `capacity` joining.

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
Added to by [D-074](#d-074) on 2026-11-08: `containerlab deploy` runs under one lock in the driver.

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
Superseded in part by [D-059](#d-059) on 2026-11-05: the policy also admits the core's
namespace; the rest stands.
Detailed by [D-073](#d-073) on 2026-11-08: what `admission.capacity` compares the demand with.

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
Superseded by [D-060](#d-060) on 2026-11-05 in its cluster: the three-server k3s cluster
replaces kind. The local driver's sufficiency stands.

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
Superseded in part by [D-057](#d-057) on 2026-11-05: `inspect` patches a Service it finds not
`Local` itself; the rest stands.

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
Added to by [D-065](#d-065) on 2026-11-05: a command's environment is an allow-list.
Added to by [D-073](#d-073) on 2026-11-08: the local reading subtracts the admitted twins' pending
demand, and the allocation carries `demand`; and by [D-074](#d-074): one deploy at a time.

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
Detailed by [D-069](#d-069) on 2026-11-05: behind the seam, the clabernetes package imports
the local driver's `plan` and `changes` alone.

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
Superseded in part by [D-058](#d-058) on 2026-11-05: the seam has ten calls.
Added to by [D-073](#d-073) on 2026-11-08: a step's admission answers the held allocation with its
`demand` refreshed to the target's; the rest of the allocation stays.

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

<a id="d-057"></a>
### D-057 — The clabernetes driver: a namespace per twin, files that hold no credential, and pods as incarnations

**Status:** Accepted 2026-11-05. Details [D-017](#d-017), [D-019](#d-019), [D-020](#d-020)
and [D-021](#d-021); supersedes [D-037](#d-037) in who patches a Service that drifted.
Detailed by [D-069](#d-069) on 2026-11-05: a node's incarnation is its pod's uid and its
container's restart count, the pull secrets name every registry of the allocation, and a
namespace of the twin's name that is not the twin's is `absent` to `inspect`, left by
`destroy` and refused by `apply` and `exec`; superseded in part by it the same day: a
link-mode change replaces the pods of the nodes whose mode changed, not every pod. The rest
stands.
Detailed by [D-073](#d-073) on 2026-11-08: admission by capacity, and the allocation's `demand`.

#### Context

The seam ([D-017](#d-017), [D-049](#d-049)) and the facts measured on the cluster
([verified-facts.md](verified-facts.md)) fix most of the driver. What they left open: the
names, what `plan` renders, where a gated image's registry comes from, how each acting call
maps to Kubernetes, and what `changes` is held to on a runtime with no dry run. Deployment 1
already lists the driver's files, the pull secret's Secret among them, and the store keeps
every deployment's files.

#### Options considered

- **The namespace named for the twin alone.** Rejected: a twin named `default` or `c9s`
  would claim a namespace that is not its own.
- **The pull secret rendered as a file of the deployment.** Rejected: the store would hold a
  registry password ([Constitution X](constitution.md#x-report-honestly)).
- **The registry's address in the platform package.** Rejected: a package is data any site
  shares, and it names its pull secret already. Where that secret's registry is belongs
  with the credential.
- **What the site decides (the core's namespace, the controller's, the pod CIDR, the
  registries) as the driver's configuration, not the allocation.** Rejected: a resumed `plan`
  must render the same files from the record alone, whatever the core's settings have become
  ([D-017](#d-017)).
- **`registries` holding only the pull secrets the bundle names.** Rejected: a stepping twin
  keeps its allocation ([D-049](#d-049)), and a step from an SR Linux twin to one with a
  cEOS node would have no prefix to write.
- **The pod CIDR or the controller's namespace as a constant.** Rejected: each is a site's,
  and [D-037](#d-037) kept one CNI's addressing out of `plan`.
- **`changes` trusted from the recorded facts alone.** Rejected: the local driver's is held to
  containerlab's dry run ([D-049](#d-049)), and this one deserves an oracle as real.

#### Decision

- **The allocation** is `{namespace, core_namespace, controller_namespace, pod_cidr,
  registries}`: the twin's own namespace, and what the site decides that `plan` writes.
  - `namespace` is `fylgja-twin-<twin>`.
  - `core_namespace` is the namespace the core runs in, absent when it runs off the cluster.
  - `controller_namespace` and `pod_cidr` are clabernetes' namespace and the cluster's pod
    CIDR, which the policy names. The driver reads them from `FYLGJA_CLABERNETES_NAMESPACE`
    and `FYLGJA_POD_CIDR`, both required when it is the driver ([D-042](#d-042)).
  - `registries` maps every pull credential the provider holds at admission to its image
    prefix ([D-062](#d-062)), whichever the bundle names, so a step may bring a gated kind.
    A bundle naming a pull secret the allocation lacks is unplannable.

  `admit` reserves the allocation by compare-and-set and refuses, with
  `admission.namespace.taken`, a namespace that exists without the twin's labels. A stepping
  twin keeps its allocation ([D-049](#d-049)). Capacity is phase 7's.
- **Labels.** Every object the driver makes carries `fylgja.owner: core` and
  `fylgja.twin: <twin>`, and the containerlab topology's default labels put both on every
  pod. An orphan is a namespace with the first label and no twin record.
- **`plan` renders three files**: `namespace.yaml` (the labels, and pod security
  `privileged`), `networkpolicy.yaml` ([D-059](#d-059)) and `topology.yaml`, a `Topology`
  wrapping the containerlab YAML the local driver's plan renders, less its `mgmt` block and
  its binds. The Topology sets `expose.disableAutoExpose`, declares each package's push and
  gNMI ports and SSH on 22, requests each package's `cpu` and `memory_mb`, names each pull secret
  in `imagePull.pullSecrets`, and writes a gated image as `<prefix>/<ref>`. **No Secret is a
  file**: `apply` makes each pull secret in the twin's namespace from the credential
  provider.
- **`capabilities`**: provisions nodes, re-cables live, forwards in software, direct access,
  isolation by network, and an apply cut short is finished by applying again
  ([D-068](#d-068)).
- **`changes`** is pure, from the two rendered topologies and the packages, by the recorded
  facts: a link change under the `live` mode re-cables and keeps the pod; a `restart` or
  `recreate` mode replaces the link's pods; a change to any node's link mode, kind or image
  replaces that pod, and a link-mode change replaces every pod; a change to a host's `exec`
  lines replaces the host's pod; a port added after boot to a kind that cannot add one is
  `recreated`, and `apply` makes it so. **Its oracle is the cluster**: the live tier holds
  each step fixture's answer to the pods' uids before and after the step.
- **`apply`** applies the namespace and the policy, makes the pull secrets, applies the
  Topology, waits within the packages' deploy budget until every node's pod is `Ready` and
  the Topology says so, and patches each Service to `externalTrafficPolicy: Local`
  ([D-037](#d-037)). `reconfigure` deletes every pod of the twin, so each returns as a new
  incarnation.
- **A recreate `apply` must make** (a port added after boot) it finds by comparing the
  Topology the cluster holds with the one it applies: the cluster's is its "before", as the
  topology on disk is the local driver's. It applies the new Topology carrying an annotation
  that names each such node and its pod's uid, waits until the Topology has observed its
  generation, deletes each named pod still at that uid, and removes the annotation. An
  `apply` that finds the annotation finishes it, so a kill between the two is resumed. Read
  on the cluster: the replacement pod lists the added port
  ([verified-facts.md](verified-facts.md)).
- **`inspect`** answers `absent` when the namespace does not exist, `residue` when it exists
  and holds none of the twin's pods, and `present` otherwise. A node's handle is its pod's
  name, its incarnation the pod's uid, its address its Service's LoadBalancer address; a
  probe host declares no port, has no such Service, and so no address. A
  Service it finds not `Local` it patches and logs: the seam's `Inspection` carries no
  drift, and every pass inspects.
- **`destroy`** deletes the namespace and waits, within the packages' destroy budget, until
  it is gone. **`endpoints`** is each node's LoadBalancer address ([D-020](#d-020)).
- **`exec`** runs the argument vector in the node's pod, naming no container, within its
  budget, keeping the tail of each stream. A budget run out is `DriverFailed`, and the
  command may run on in the node ([verified-facts.md](verified-facts.md)), so a caller passes
  a command that ends by itself, as the burst's does.

#### Consequences

- Deployment 1 and twin record 1 describe the allocation's members, and deployment 1's
  description of the files drops the Secret; the rule catalogue gains
  `admission.namespace.taken`. The driver registry serves a second name
  ([D-046](#d-046)).
- A changed setting or registry prefix reaches a twin only when it is admitted anew, since a
  stepping twin keeps its allocation; so does a pull credential added after its admission.
- The driver's service account acts in every twin namespace ([D-062](#d-062)).
- What a missing binary answers through `exec` (the API server's 500 here, an exit status
  locally) is made the same on both drivers where the conformance suite reads it.

<a id="d-058"></a>
### D-058 — The seam's tenth call, `events`: a driver names the twins whose runtime changed

**Status:** Accepted 2026-11-05. Supersedes [D-017](#d-017) and [D-049](#d-049) in the
seam's count; details [D-023](#d-023)'s third trigger. Detailed by [D-070](#d-070) on
2026-11-06: what names a twin on clabernetes, what each source drops, their gaps and how a
failure is logged; and the resync is a setting, `FYLGJA_RESYNC_S`.

#### Context

[D-023](#d-023) names four triggers. Three are built: a client's write, the core's start and
a resync every 300 s. The fourth, a change the driver reports, was left by phase 4. Without
it a node the runtime replaces (a drained host's pods, a restarted container) holds no
configuration until the next resync. The two runtimes report differently: Docker's event
stream, and a watch on pods.

#### Options considered

- **A shorter resync.** Rejected: every twin inspected every few seconds, and still late.
- **Each driver calls the loop's `kick` itself.** Rejected: the driver would hold the loop,
  and the seam would run both ways.
- **Events that carry the node and what happened to it.** Rejected: the loop is
  level-triggered and `inspect` tells it what is true; an event's detail would be a second,
  staler account.
- **An asynchronous iterator of twin names.** Chosen.

#### Decision

- **`events()` answers an asynchronous iterator of twin names**, each a twin whose runtime
  state may have changed. It ends only when cancelled. The driver reconnects for itself, and
  after a reconnect may name every twin it holds: a name with nothing behind it costs one
  pass that finds nothing to do.
- **The loop runs one task that kicks each name.** The queue already folds repeats
  ([D-023](#d-023)); a name with no record is dropped.
- **The local driver** follows `docker events` for containers carrying containerlab's lab
  label, and names the lab on a start, a die or a destroy.
- **The clabernetes driver** holds one watch on pods labelled `fylgja.owner: core` in every
  namespace, and names `fylgja.twin` when a pod is added, deleted, or changes its uid or its
  readiness.
- **The resync stays** at its period, so that a missed event is only late.

#### Consequences

- The seam has ten calls. What a kick does on a settled twin is [D-067](#d-067). The core's
  own applies raise events, each costing one further pass that finds nothing to do.
- The conformance suite replaces a node behind the core's back, with the resync set long,
  and reads the push return within seconds.

<a id="d-059"></a>
### D-059 — A twin's NetworkPolicy also admits the core's namespace

**Status:** Accepted 2026-11-05. Supersedes [D-019](#d-019) in the policy's sources; the
rest stands.

#### Context

[D-019](#d-019)'s policy admits a twin's own pods, the clabernetes namespace and non-pod
sources. It was written when the core ran off the cluster. The core is now a pod
([D-062](#d-062)), and read on the cluster on 2026-11-05 such a pod is refused at a node's
pod address, its Service's cluster address and its LoadBalancer address alike
([verified-facts.md](verified-facts.md)).

#### Options considered

- **The core on the host's network.** Rejected: its traffic to another host's pods carries
  the host's flannel address, inside the pod CIDR the policy refuses ([D-037](#d-037)).
- **A `namespaceSelector` naming the core's namespace.** Chosen, as verified: every path
  opened within a second, and a pod in a third namespace stayed refused.
- **That selector narrowed by a pod label.** Not taken now: it was not read on the cluster,
  and the core's namespace holds only the core and its store.

#### Decision

The plan's NetworkPolicy admits, beside D-019's three sources, the namespace the allocation
names as `core_namespace`, selected by `kubernetes.io/metadata.name`. An allocation without
one, a core off the cluster, adds nothing: such a core is a non-pod source already.

#### Consequences

- Whatever runs in the core's namespace reaches every twin's nodes, so that namespace holds
  the core and its store and nothing else.
- The conformance suite tests isolation over TCP from another twin's pod and from a pod in a
  third namespace, each at least 15 s old ([D-037](#d-037)).

<a id="d-060"></a>
### D-060 — The clabernetes driver is developed on the three-server k3s cluster; kind is retired

**Status:** Accepted 2026-11-05. Supersedes [D-022](#d-022) in its cluster; that the local
driver stays sufficient for development and the live tier stands.

#### Context

[D-022](#d-022) chose kind before the multi-host stage. That stage found two behaviours
kind's single host had hidden: the Services' traffic policy ([D-037](#d-037)) and etcd under
parallel pulls ([D-036](#d-036)). The three-server cluster now stands, phase 6 ends on it,
and every fact the driver relies on would otherwise be re-verified on two clusters whose
network policy controllers differ.

#### Options considered

- **kind for development, k3s for the exit.** Rejected: two sets of facts, and the one
  developed against is the one that hid what mattered.
- **kind in CI.** Rejected: CI cannot hold the gated image, and boots no node.
- **The k3s cluster for both.** Chosen.

#### Decision

- The three-server k3s cluster of [D-036](#d-036)'s shape is where the clabernetes driver is
  developed and where its conformance suite runs.
- kind's facts stay in [verified-facts.md](verified-facts.md) under their dates and are not
  re-verified; kind leaves the tooling.
- The pure tier covers the driver's `plan` and `changes` by fixtures, and its acting calls
  over a fake of the Kubernetes API, so no contributor needs a cluster to change the core
  ([Constitution XIII](constitution.md#xiii-runtimes-are-drivers)).

#### Consequences

- A contributor without such a cluster cannot run the clabernetes conformance suite, as one
  without the images cannot run the live tier ([D-034](#d-034)).
- The cluster's prerequisites in [core.md](core.md) are its setup.

<a id="d-065"></a>
### D-065 — Every command the local driver runs gets a stated environment

**Status:** Accepted 2026-11-05. Adds to [D-043](#d-043): `cli.run`'s default environment.

#### Context

`cli.run` hands a command the core's whole environment unless told otherwise
([D-043](#d-043)), and the core's environment holds every node login and its settings
([D-042](#d-042)). No output read so far held one ([verified-facts.md](verified-facts.md)),
but containerlab expands variables in a topology, and a deploy's output goes to a file
([D-056](#d-056)).

#### Options considered

- **Remove the `FYLGJA_*` variables.** Rejected: whatever else the operator's shell holds
  still passes.
- **An allow-list.** Chosen.

#### Decision

- Every command the local driver runs, `docker events` included ([D-058](#d-058)), gets an
  environment built from an allow-list: the variables `containerlab` and `docker` need to
  find their binaries, their home and the Docker daemon, and nothing named `FYLGJA_*`.
- The list is the smallest with which a deploy, a destroy, an inspect and each `docker`
  command the driver runs succeed on the running system, recorded in
  [verified-facts.md](verified-facts.md) for containerlab 0.81.0.

#### Consequences

- A variable an operator relied on reaching containerlab through the core no longer does;
  it is added to the list by a change, with its reason.
- A pure test holds that no `FYLGJA_*` variable reaches a child.

<a id="d-068"></a>
### D-068 — A driver declares whether applying again finishes an apply cut short

**Status:** Accepted 2026-11-05. Supersedes [D-023](#d-023)'s partial-lab rule and
[D-050](#d-050)'s resume of a step in their reach: both hold for a driver that declares it
cannot. Adds a member to API 1's driver capabilities ([D-025](#d-025)). Detailed by
[D-070](#d-070) on 2026-11-06: no path of the loop reconfigures on a driver that declares
`reapply`.

#### Context

The partial-lab rule is containerlab's fact: a deploy over a partial lab returns 0 and fixes
nothing, so a resumed core probes the lab and, finding a node silent, reconfigures it, or
ends a step `diverged` where the spec allows no restart ([D-023](#d-023),
[D-050](#d-050)). The probe counts a node that is not running, or has no address, silent at
once, and any other after its readiness window, which was measured from a deploy's return.

On clabernetes the controller goes on after the core dies. A resumed core finds pods still
coming up, 55 to 119 s from their apply to `Ready`
([verified-facts.md](verified-facts.md)), against readiness windows of 60 and 90 s. The
probe would delete pods that were about to answer, or end a step `diverged` for them. And
the Topology is declarative: applying it again waits for the same pods.

#### Options considered

- **`inspect` reports a pod still coming up as running.** Rejected: the probe's window then
  decides, and it was measured for a node whose deploy had returned.
- **The probe moved behind the seam.** Rejected: readiness and the logins sit above it
  ([D-017](#d-017)).
- **A declared capability.** Chosen: the loop may branch on one
  ([Constitution XIII](constitution.md#xiii-runtimes-are-drivers)).

#### Decision

- **`Capabilities` gains `reapply`**, true when applying a deployment again finishes an
  apply that was cut short. The local driver declares false, the clabernetes driver true.
- **Where it is true**, a resumed create or step whose apply had begun applies again, with no
  probe and no reconfigure, and `step.node.silent` cannot arise. **Where it is false**,
  D-023's and D-050's rules stand as written.

#### Consequences

- API 1's `Driver` lists the member. The `hardware` driver would declare true: its apply
  resets each device to a baseline.
- A scenario that kills the core during an apply expects the same ending on both drivers.

<a id="d-069"></a>
### D-069 — A clabernetes node's incarnation is its pod's uid and its container's restart count

**Status:** Accepted 2026-11-05. Details [D-057](#d-057) (a node's incarnation, the pull
secrets `apply` makes, and what the driver does with a namespace of the twin's name that is
not the twin's) and [D-046](#d-046) (the boundary between the two containerlab drivers);
supersedes [D-057](#d-057) and [D-015](#d-015) in what a link-mode change replaces. Detailed
by [D-070](#d-070) on 2026-11-06: a pod whose container ended or restarted in it is deleted by
the driver, at most three times in ten minutes a node, since such a node's address does not
answer again, and the cluster makes it anew.

#### Context

[D-057](#d-057) makes a node's incarnation its pod's uid, so that a pod the cluster replaces
voids what the node holds and the loop pushes it again ([D-023](#d-023),
[D-067](#d-067)). But a pod outlives its container. Kubernetes' contract for a Deployment's
pod, as a node's is (`restartPolicy: Always`), is that a container that ends is restarted in
place: the uid stays and the container's restart count grows. What a node does when its
container is restarted so was not yet read on clabernetes. If it boots again, its push is
lost, and by the uid alone the restore pass would never see it. Read since, on 2026-11-05:
an SR Linux node's container ended in its pod came back at the same uid, its restart count
one more, booted again, its push lost ([verified-facts.md](verified-facts.md)).

Building the driver (phase 6, plan 4) settled three more points, which D-057 left implicit
or the cluster contradicted:

- the clabernetes driver renders and compares the containerlab definition the local driver
  renders, through the local driver's own modules, where [D-046](#d-046)'s boundary test let
  no module outside `fylgja_core.containerlab` import them;
- `plan` names in `imagePull.pullSecrets` the pull secret of every registry the allocation
  holds, whichever the bundle uses;
- read on the cluster on 2026-11-05, a link-mode change replaced the pods of the nodes whose
  mode changed and no other ([verified-facts.md](verified-facts.md)), where D-057 and
  [D-015](#d-015) say it replaces every pod. The k3s reading that switching to `live`
  replaced every pod ("Steps across hosts", 2026-11-02) had changed every node's mode at
  once; the kind reading that changing any node's mode replaces every pod (2026-10-30) was
  not read again, kind being retired ([D-060](#d-060)).

#### Options considered

- **The pod's uid alone, as D-057 has it.** Rejected: a container restarted in place keeps
  it, and the record would say the node holds a push it may have lost.
- **The container's start time, as the local driver's.** Rejected: a container waiting to
  restart has none, so a node between two runs of a crash loop would read no incarnation,
  and a replaced pod is the uid's to say already.
- **The restart count beside the incarnation, a member of its own.** Rejected: `NodeState`
  has one incarnation, which the loop compares alone ([D-067](#d-067)); a second member is a
  change to the seam for one driver's fact.
- **The pod's uid and its container's restart count, in one string.** Chosen.

#### Decision

- **A clabernetes node's incarnation is `<uid>/<restarts>`**: the uid of the pod that stands
  for the node (its newest not being deleted, or the newest of all when every one is) and
  the restart count of its one container, 0 before it has a status. A pod replaced and a
  container restarted in place each change it, and the loop voids the node's `holds` and
  pushes it again, as for any changed incarnation. `changes`' oracle in the cluster tier
  (the clabernetes driver's on-demand tier, beside [D-034](#d-034)'s) still compares uids: a
  step's pods are replaced, not restarted in place.
- **The clabernetes package imports, of the local driver, `fylgja_core.containerlab.plan`
  and `fylgja_core.containerlab.changes` alone, and the two drivers find a node's packages
  by one lookup,** told how a package's image is written: by its `ref` locally, as
  `<prefix>/<ref>` for a gated image in a Topology. Both drivers run one containerlab
  definition, so its render, its comparison and the lookup are written once; the CLI
  runner, the pool and the local driver's names stay its own, and the local driver imports
  nothing of clabernetes. Above the seam nothing imports either package, as D-046 has it;
  `core/tests/test_boundary_seam.py` holds both.
- **`imagePull.pullSecrets` names every registry of the allocation, so an ungated twin's
  `apply` needs every held registry's login.** The allocation is the twin's for life
  ([D-049](#d-049)), so a step that brings a gated kind changes no pod's pull secrets; and a
  Topology naming a Secret its namespace lacks gets no pod
  ([verified-facts.md](verified-facts.md)), so `apply` makes every one, each login read
  before the first Secret is applied. A Secret's `auths` host is the host of the
  allocation's prefix, under which the Topology writes the images, and a provider whose
  registry is no longer that prefix fails the `apply`, naming the variable: the twin is bound
  to the prefix it was admitted with.
- **A namespace is the twin's by its two labels at every call, not at admission alone.** One
  of the twin's name that exists without `fylgja.owner: core` and `fylgja.twin: <twin>` is
  `absent` to `inspect`, where [D-057](#d-057) says `absent` only of a namespace that does
  not exist; `destroy` leaves it, logging a warning; `apply` fails, `DriverFailed`, with
  nothing applied and the namespace not labelled; and `exec` fails with nothing run. The
  driver never labels, applies into or deletes a namespace that is not the twin's.
- **D-057's and D-015's clauses that a link-mode change on clabernetes replaces every pod
  are superseded.** A change to a node's link mode replaces that node's pod and no other, as
  read on the cluster, and `changes` answers so: `recreated` for `link_mode`, as the local
  driver answers it.

#### Consequences

- Twin record 1 describes a node's `handle` on clabernetes as its pod's name and its
  `incarnation` as `<uid>/<restarts>`.
- The cluster tier restarts a node's container in place and reads the same uid, one restart
  more, another incarnation and whether the node boots again, recorded in
  [verified-facts.md](verified-facts.md): read there on 2026-11-05, on an SR Linux node,
  which booted again and lost its push. Until then the pure tier alone held the rule.
- A step that changes one node's link mode needs `allow_restart` for that node alone. A
  neighbour the cluster did replace would still be pushed again, since the loop acts on
  every changed incarnation.
- A pull credential removed from the provider, left without its login, or set to another
  registry refuses the next admission of a stepping twin that was admitted while it was held,
  and fails an `apply` already under way, each naming its variable, until it is set again.
  One left without its login refuses any admission, a new twin's included. One added reaches
  a twin only when it is admitted anew ([D-057](#d-057)).

<a id="d-073"></a>
### D-073 — Admission by capacity: the runtime's free room, read at `admit`, less the admitted twins' pending demand

**Status:** Accepted 2026-11-08 (phase 7). Supersedes [D-017](#d-017) in its count of calls:
eleven, `capacity` joining; the rest stands. Details [D-019](#d-019) (what `admission.capacity`
compares with), [D-043](#d-043) (the local reading), [D-049](#d-049) (a step's admission, whose
held allocation now carries the target's demand) and [D-057](#d-057), which left capacity here.
Superseded in part by [D-077](#d-077) on 2026-11-09: the call takes the reserved allocations, a
step is judged on the sum alone, and a pod's effective request is the scheduler's own sum.

#### Context

The requirement is about five concurrent twins of tens of nodes on a 2–3-node cluster
([core.md](core.md#requirements)). The deployment carries a demand, the sum of its nodes'
package resources, and [architecture.md](architecture.md) says admission compares it with
"free capacity" and refuses with `admission.capacity`; what free capacity is was left to this
phase. As built, the local driver refuses a twin whose demand exceeds the kernel's
`MemAvailable` or the CPU count, counting no twin admitted whose lab is not yet up, and the
clabernetes driver admits every twin. A twin that does not fit the cluster would then have its
namespace, policy, Topology and pods made, and end `failed` when the deploy's budget ran out
with pods still Pending, holding room meanwhile. The orchestrator becomes a concurrent client
as soon as two proposed changes are open, and its check already treats a refused admission as
"held, ask again" every 30 s. The maintainer's answer to where free capacity comes from was
the cluster, not a number the site declares.

Read on 2026-11-08 ([verified-facts.md](verified-facts.md)): each host reports 8 CPU and
23.46 GiB as both capacity and allocatable (k3s reserves nothing by default), the system's own
pods request 70m–320m CPU and 192–460 MiB a host, and MetalLB's pods request nothing. Five
three-node SR Linux twins at the packages' requests take 7.5 CPU and 30 GiB of about 23 CPU
and 70 GiB; a twin of 36 such nodes does not fit.

#### Options considered

- **A budget the site declares**, `FYLGJA_MAX_TWINS`, or CPU and memory totals in settings.
  Rejected: a second number to keep right beside the cluster's own, wrong whenever the
  cluster grows, shrinks or runs something else, and it was not what the maintainer asked
  for.
- **Queue a twin that does not fit until room frees.** Rejected: the wait would be invisible
  to the orchestrator, whose rehearsal deadline assumes a run starts at once, and the
  architecture already refuses; a refusal keeps the wait where the client can see it.
- **Let the scheduler decide**: admit, apply, and read Pending pods. Rejected: a twin that
  does not fit touches the cluster and ends `failed` after minutes rather than `rejected` in a
  second, and its partial pods hold room others could take.
- **Count twins alone**: allocatable less the twins' demand. Rejected: clabernetes, k3s, the
  core and anything else the cluster runs request CPU and memory too; counting twins alone
  admits into room that is not there.
- **Bin-pack nodes onto hosts in the core.** Rejected: the scheduler's job, and a second
  placement to keep in agreement with it. The core checks the sum and the largest node.
- **Read the runtime at `admit`**: allocatable less every pod's requests, less the demand of
  twins admitted whose pods are not yet requesting. Chosen.

Where the admitted twins' demand is kept:

- **Look up each twin's deployment.** Rejected: a deployment exists only after `plan`, and
  the loop would add a store call per reserved twin to every admission.
- **In the allocation.** Chosen: the allocation is what `admit` reserved, and the room is
  part of it. Both drivers write it; a step refreshes it.

#### Decision

- **`capacity()`** is the seam's eleventh call. It answers a **reading**: the hosts, each
  with a name and its total and free CPU and memory; and the **pending** demand (nodes, CPU,
  memory), the sum over every other twin's recorded `demand` (its allocation's) less what
  the runtime already holds for that twin, each twin floored at zero. On clabernetes a
  host's total is its allocatable and its free that less the effective request of every pod
  on it that has not ended, computed as the scheduler does (the larger of the init
  containers' requests and the containers' sum, plus a restartable init container's, plus
  overhead), whoever owns the pod; a twin's pods are found by its label. Locally there is one
  host: its total is the CPU count and `MemTotal`, its free memory `MemAvailable`, its free
  CPU the count less the demand of every twin whose lab has every container running (the
  kernel reports no CPU reservation); a twin's demand is pending until every container of
  its lab runs. `admit` takes the reading first, under the loop's admission lock, so two admissions
  never read the same room.
- **The fit rule** is pure and shared by both drivers. A demand fits when its CPU and its
  memory each fit the sum of the hosts' free less the pending demand, and each of its nodes'
  package resources fit the roomiest host, CPU and memory each. A step's demand is what the
  target adds over `held.demand`, per component floored at zero ([D-049](#d-049)), and its
  own twin is not in the pending sum.
- **The refusal** is `admission.capacity`, one sentence per shortfall: what the twin needs of
  the resource, what the reading found free and pending; or the node no host can take, with
  the roomiest host's free. The local driver's subnet-pool refusal keeps its sentence. A
  refused twin ends `rejected` with that finding, and a dry run answers 422 with it.
- **The allocation gains `demand`** `{nodes, cpu, memory_mb}`, on both drivers, written by
  `admit`; a step's admission answers the allocation the twin holds with `demand` set to the
  target's and nothing else changed, and the loop records that answer at `admitted` for a
  step as it does for a create, where today it drops a step's answer
  (`reconcile.py`, `_admit`). A step's own added demand is still judged against
  `held.demand`, the running deployment's ([D-049](#d-049)); the allocation's `demand` serves
  the pending sum alone. Deployment 1's and twin record 1's descriptions of the allocation
  name it.
- **The core's ClusterRole** gains `get` and `list` on `nodes`; `list` on pods it has.
- The reading is also what `GET /v1/capacity` answers ([D-076](#d-076)).

#### Consequences

- The reading is a moment, not a reservation: the scheduler places, and a pod another
  workload makes between the reading and the Topology's apply is its to fit. The pending
  demand covers the core's own twins, which is the race that matters here.
- A pod with no requests is invisible to the reading, as it is to the scheduler.
- Locally the kernel's figure counts whatever the host is doing, as it does today.
- A twin whose packages change their resources between a step's admission and its apply is
  counted at the target's demand, which is what the Topology will request.
- A step refused or cancelled before `applied` leaves the target's demand in the allocation
  while the twin runs the old deployment, so the pending sum over-counts that twin, by at most
  its own demand, until its next step. Conservative, and accepted.
- A twin whose destroy is retrying keeps its allocation ([D-055](#d-055)) and, its containers
  or pods gone, its whole demand pending, so it holds its room until the destroy succeeds.
  Conservative, and intended.
- Locally a node grows for about a minute after its container starts, and that minute is
  counted by neither the kernel's figure nor the pending sum; under [D-074](#d-074)'s lock one
  twin at a time is in it, and a fixture that does not fit must exceed the host by more than
  one twin's demand.
- The orchestrator reads `admission.capacity` as "ask again", as its check does today for the
  Go core's refusals; keeping that is phase 8's.
- The facts the reading rests on were read on 2026-11-08 and are re-read by a cluster-tier
  test of phase 7's plan 1.

<a id="d-074"></a>
### D-074 — The local driver deploys one lab at a time

**Status:** Accepted 2026-11-08 (phase 7). Details [D-018](#d-018) and [D-043](#d-043);
[D-055](#d-055)'s destroy stands. Superseded in part by [D-077](#d-077) on 2026-11-09: the
deploy a destroy's recovery makes takes the lock.

#### Context

Two labs deploy together in 48–53 s without harm ([verified-facts.md](verified-facts.md),
"Two labs at once"). On 2026-11-03 two live tiers ran at once on the development host, eight
SR Linux nodes booting between them on 10 cores: the load reached about 33 and SR Linux's
`sr_cli` segfaulted in containerlab's post-deploy, failing the deploy
([verified-facts.md](verified-facts.md), "Under memory pressure its own `sr_cli` can segfault",
the 2026-11-03 reading: 22 GiB available, the load at 33). Memory was not
the limit; CPU was. Three twins created together would boot nine nodes at once, and
admission by capacity ([D-073](#d-073)) admits them: the steady 0.5 core a node says nothing
about a boot.

#### Options considered

- **No bound.** Rejected: the crash.
- **A bound by setting**, so many deploys at once. Rejected: a number to tune per host, and
  the boot's load is not the package's steady figure, so no reading sizes it.
- **Admit by CPU with a boot factor.** Rejected: admission would refuse twins the host can
  run once booted, for a minute's load.
- **One `containerlab deploy` at a time**, under a lock in the driver. Chosen: a boot is a
  minute, the second twin's create waits in its apply, which is waiting and not failing, and
  the host's load stays what one deploy makes.

#### Decision

- `apply`'s `containerlab deploy`, and the hot-add container removals before it
  ([D-049](#d-049)), run under one lock held by the driver instance. The wait for the lock is
  outside the deploy's budget, which starts when the deploy does; the lock is taken in the
  order asked.
- `destroy` is not held: a destroy during another twin's deploy is what [D-055](#d-055)
  already handles, and a resume's wait for a stray deploy of its own twin
  ([D-056](#d-056)) precedes the lock.
- On clabernetes nothing is held: the scheduler spreads the boots over the hosts.
- The live test of phase 7's plan 3 creates three labs together and reads the host's load.

#### Consequences

- Three twins created together locally reach Ready in about three deploys' time; the
  conformance suite's many-twins scenario records what that is.
- One core runs per host (one core per store, [D-024](#d-024)), so the lock in the driver
  instance is the only one needed.


<a id="d-077"></a>
### D-077 — Capacity and the deploy lock as built: the reading is given the reserved twins, a step is judged on the sum, and a pod's request is the scheduler's own

**Status:** Accepted 2026-11-09 (phase 7's landing). Supersedes [D-073](#d-073) in three parts: the
call's signature, a step's fit and the arithmetic of a pod's effective request; and
[D-074](#d-074) in one: the deploy a destroy's recovery makes. The rest of both stands.

#### Context

D-073 and D-074 were settled before code. Building them (phase 7, plans 1 and 3) found four
places where they could not be built as written, and what they leave unsaid.

- D-073's `capacity()` takes nothing, so the driver must itself know which twins are admitted.
  As first built it kept the `reserved` of its last `admit`. A read made for the API
  ([D-076](#d-076)) then counted the wrong twins: none after a restart, one too many after a
  destroy, and never the twin admitted last, which is in no `reserved` of its own.
- D-073's fit rule checks each of a twin's nodes against the roomiest host. A step's `admit`
  is given the deployment the twin holds and not the nodes the target adds, and a check over
  every node of the target would refuse a step that adds nothing on a full cluster, whose
  running nodes already hold their room.
- D-073's parenthetical for a pod's effective request ("the larger of the init containers'
  requests and the containers' sum, plus a restartable init container's, plus overhead") is an
  approximation of "as the scheduler does", its binding words. It differs from the scheduler's
  sum where a restartable init container comes before a larger init container, and it knows
  nothing of a request set on the pod itself.
- D-074 says `destroy` is not held. A destroy that finds a twin's residue and no lab deploys
  the lab before it destroys it (recovery rule 2, [D-019](#d-019), [D-023](#d-023)), and that
  deploy boots every node: the load the lock exists for.

#### Options considered

Which twins a reading counts:

- **The driver keeps the `reserved` of its last `admit`.** Rejected: the three miscounts above.
  "A look and not a reservation" covers a race, not a wrong set of twins.
- **The driver reads the twin records.** Rejected: a driver knows no store.
- **The caller passes the allocations.** Chosen.

A step's fit:

- **The sum, and every node of the target against the roomiest host.** Rejected: it refuses a
  step that adds nothing where the hosts are full.
- **The sum, and the nodes the step adds against the roomiest host.** Not taken: `admit` is
  not given them, and the seam's `changes` answers them only after admission.
- **The sum alone.** Chosen.

A pod's effective request:

- **D-073's parenthetical.** Rejected: not the scheduler's figure in the two cases above.
- **Kubernetes' own sum**, in init-container order, a request on the pod replacing it. Chosen.

The deploy a destroy's recovery makes:

- **Outside the lock, as D-074 has every destroy.** Rejected: nodes booting beside another
  twin's deploy.
- **Through `apply`, under the lock.** Chosen; a destroy that deploys nothing takes no lock.

#### Decision

1. **The seam's call is `capacity(reserved: Sequence[Allocation]) -> Reading`.** `admit` passes
   the `reserved` the loop gave it; `GET /v1/capacity` passes every twin record's allocation. A
   driver keeps no set of twins between calls.
2. **A create must fit in its sum and in each node; a step in its sum alone.** A step's demand
   is what the target adds over `held.demand`, per component floored at zero, and a component
   of zero is never short: a step that adds nothing is admitted whatever the reading. Locally
   a step's reading also subtracts the stepping twin's own held CPU, which the loop leaves out
   of `reserved`.
3. **A pod's effective request is Kubernetes' own sum**, per resource. The containers' total is
   the sum over the containers. The init containers are walked in order, keeping the running
   sum of the restartable ones seen so far: a restartable one adds its request to the
   containers' total and to the running sum, and its figure is the running sum; another's
   figure is its request plus the running sum before it. The request is the larger of the
   containers' total and the largest init figure; a request the pod itself sets
   (`spec.resources.requests`) replaces that figure, for CPU and for memory each; then the
   overhead is added. Memory is summed in bytes and floored to MiB once.
4. **What a twin holds on the cluster is its pods bound to a host the reading lists.** A pod
   bound to no host yet takes no host's room and leaves its twin's demand pending, so each
   unit of a twin's demand is counted once, as a bound pod's request or as pending.
5. **A reading that cannot be taken is `DriverFailed`**: on the cluster a node with no
   allocatable or a quantity that will not parse, through the Kube protocol's failure; locally
   an unknown CPU count, a missing or garbled `/proc/meminfo` key, or the file unread. No host
   is skipped in silence. The local host's kilobytes are floored to MiB.
6. **An allocation whose `demand` is absent**, as every one admitted before phase 7 is, counts
   as nothing and is logged once a twin at INFO; one whose `demand` will not read counts as
   nothing and is logged once a twin at WARNING. Neither blocks an admission.
7. **The local host is named `host`** in the reading, never the machine's name, so the API's
   answer holds no site value on the local driver either.
8. **The refusal's sentences** begin "The twin needs" for a create and "The step adds" for a
   step, and name "the host" locally and "the cluster" on clabernetes; a node no host can take
   is named with the roomiest host and its free CPU and memory.
9. **The deploy of a destroy's recovery rule 2 is an `apply` and takes the deploy lock.** A
   destroy that deploys nothing takes none. An apply that must wait logs once that it waits.

#### Consequences

- A step that adds a node larger than any host's free passes admission and fails at its apply
  with the pod Pending, as before the phase.
- A destroy of a twin with residue and no lab can wait behind another twin's deploy.
- A twin admitted before phase 7 is counted at nothing until its next step records its demand.
- Three twins created together locally were Ready 163.9–177.2 s after their asks, the deploys
  one after the other ([verified-facts.md](verified-facts.md), "Three twins at once through the
  core"), which is the figure D-074 left to the many-twins scenario.
- [core.md](core.md) and [architecture.md](architecture.md) name the call as built.


## The reconcile loop and state

<a id="d-023"></a>
### D-023 — The core runs its own reconcile loop, scheduled by a queue keyed by twin

**Status:** Accepted at the baseline (2026-10-31).
Detailed by [D-058](#d-058) (the driver's trigger), [D-062](#d-062) (the Lease) and
[D-067](#d-067) (the pass on a settled twin) on 2026-11-05; superseded in part by
[D-068](#d-068) the same day: the partial-lab rule holds for a driver that cannot apply again.
Detailed by [D-070](#d-070) on 2026-11-06: a driver's event never brings a twin's pass forward
of its backoff (item 18). Superseded in part by [D-072](#d-072) on 2026-11-07: Temporal is no
longer the fallback, the core's own loop having resumed every run a kill of the conformance suite
found unfinished, on both drivers; on the cluster the kills at a create's `pushed` and a step's
`verified` found the run ended, and locally the one at a step's `verified` did.
Added to by [D-075](#d-075) on 2026-11-08: the pool's default is eight workers.

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
Superseded in part by [D-061](#d-061) on 2026-11-05: development's object storage is Versity
S3 Gateway, MinIO's open-source edition having ended; the rest stands.

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
Superseded in part by [D-068](#d-068) on 2026-11-05: a step's resume applies again, with no
probe, on a driver that declares it can. Superseded in part by [D-070](#d-070) on 2026-11-06:
a step to the bundle the twin runs ends at `compiled` only when every device node holds it, and
otherwise readies, pushes and verifies those that hold nothing.

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

<a id="d-061"></a>
### D-061 — The object store is S3 by conditional writes, signed in the core, with Versity in development

**Status:** Accepted 2026-11-05. Supersedes [D-024](#d-024) in development's object storage
(MinIO); details its `object` store. One store interface and no database stand.

#### Context

[D-024](#d-024) names MinIO for development. MinIO's open-source repository was archived in
April 2026, and its vendor no longer serves that edition's binaries or images; what replaced
it is proprietary. The `object` store needs four calls and one property: a write that
succeeds only if the object is absent, or only if it is unchanged. The store interface is
synchronous ([D-041](#d-041)). The cluster's one storage class binds a volume to a node, so
any store of one replica there is as pinned as a directory on a volume.

#### Options considered

The store, for development:

- **Garage.** Rejected: it accepts `If-None-Match: *` and overwrites; its maintainers say its
  replication cannot support the condition.
- **SeaweedFS, RustFS.** Not taken: fuller systems than megabytes of JSON need, with
  conditional-write races repaired in releases weeks old.
- **Ceph through Rook.** Rejected for development: about 10 GiB of daemons and a raw disk per
  host. It is what a site that needs the store to survive a drain would point the core at.
- **The store beside the registry, off the cluster.** Not taken now: host setup the manifests
  cannot carry.
- **Versity S3 Gateway, one pod over a volume.** Chosen: one Apache-2.0 process that makes a
  directory an S3 endpoint, its conditional writes read on 2026-11-05
  ([verified-facts.md](verified-facts.md)).

The client:

- **boto3 in threads; aiobotocore.** Rejected: 7 to 17 packages, a second HTTP stack or
  none typed, for four calls.
- **obstore.** Rejected: one package, but a compiled extension still before 1.0.
- **SigV4 written in the core, over httpx.** Chosen: about a hundred lines, whose signatures
  matched botocore's byte for byte.

#### Decision

- **The `object` store speaks S3 to any endpoint that honours conditional writes**:
  `GetObject`, `PutObject`, `DeleteObject` and `ListObjectsV2`, path-style, signed with
  SigV4 by the core over httpx. No S3 library is a dependency.
- **Compare-and-set is the condition.**
  - A document kept by id, a new twin record and a new run are put with `If-None-Match: *`;
    a refusal means it exists.
  - A twin record or a run is replaced with `If-Match` at the ETag it was read with, once
    the revision or the state read is the one expected; a delete carries the same
    condition.
  - A run's event is one object, keyed by the run and its sequence number padded to sort,
    created with `If-None-Match: *`; a refusal means the number is taken. Events are read by
    `prefix` and `start-after`.
  - A bundle's or a deployment's document is written after its files and read before them,
    so a reader sees every file or `NotFound`.
- **The store proves its endpoint at start.** On a key of its own it must be refused a
  create over an object, a replace at an earlier ETag and a delete at an earlier ETag; an
  endpoint that accepts any of them is refused, naming which.
- **Settings** ([D-042](#d-042)): `FYLGJA_STORE` is a directory or `s3://<bucket>[/<prefix>]`;
  with the latter, `FYLGJA_S3_ENDPOINT`, `FYLGJA_S3_ACCESS_KEY` and `FYLGJA_S3_SECRET_KEY`
  are required, and `FYLGJA_S3_REGION` (default `us-east-1`) and `FYLGJA_S3_CA` are
  optional.
- **One core per store** is the Lease's ([D-062](#d-062)): the server refuses an `s3://`
  store when no Lease is named.
- **In development** the endpoint is Versity S3 Gateway v1.10.0, one pod in the core's
  namespace over a `local-path` volume, reached over the cluster network without TLS: a
  request carries a signature, never the secret, and no record holds a credential.
- **The signer is tested** against answers taken from botocore's signer and kept in
  `testdata/`, and the store against Versity under Docker in the live tier.

#### Consequences

- The store and the core stop together when the store's host is drained; the twins run on,
  unmanaged, until it returns. A site that cannot accept that points the core at replicated
  S3 storage.
- An ETag is used only as the token a condition names, never as a checksum.
- Reading a run's events is one listing and one read an event, which the volume allows.
- A watcher's subscription stays in the process, as the local store's is.

<a id="d-062"></a>
### D-062 — On a cluster the core is one pod under a Lease, deployed by kustomize from an image built in the tree

**Status:** Accepted 2026-11-05. Details [D-023](#d-023)'s Lease; adds to [D-042](#d-042):
`FYLGJA_LEASE`, and a pull credential's `_REGISTRY`.
Detailed by [D-071](#d-071) on 2026-11-07: the Lease's rule is a Role in the core's namespace,
beside the one ClusterRole; what the Lease promises and what it does not; what the server does
when it loses it; and what a store's fault on a read route answers.

#### Context

Phase 6 runs the core off the development host for the first time: as a pod on the
three-server cluster ([D-060](#d-060)), holding a Lease so that a second never reconciles
beside it ([D-023](#d-023)), its credentials from Secrets ([D-042](#d-042)). The tree holds
no host name, address or value, and the cluster's private registry is how an image reaches a
node ([D-021](#d-021)).

#### Options considered

The manifests:

- **A Helm chart.** Not taken now: a second tool and templates to keep, before any outside
  user asks for one.
- **Plain YAML and a script.** Rejected: the site's values would be substituted ad hoc.
- **kustomize.** Chosen: `kubectl` carries it, the base is plain YAML, and an overlay holds
  what is a site's.

The image:

- **A distroless base.** Not taken: no shell when a pod needs a look, for megabytes saved.
- **Built in CI and published.** Not taken: publishing an image is a release's decision.
- **A Dockerfile in the tree on `python:3.14-slim`.** Chosen.

The role:

- **A Role per twin namespace, bound by the core as it makes each.** Rejected: the core would
  need the right to grant rights.
- **One ClusterRole.** Chosen, and stated: the core's service account acts on Secrets and
  pods in every namespace.

#### Decision

- **The Lease.** `FYLGJA_LEASE` names a `coordination.k8s.io/v1` Lease in the core's
  namespace; its holder is the pod's name, its duration 15 s, renewed every 5 s. The server
  takes it before it starts the loop or listens, and exits when no renewal has succeeded
  within the duration; the pod's restart resumes from the record. The Deployment has one
  replica and the `Recreate` strategy.
- **The namespace** `fylgja` holds the core, its Service and its store, and nothing else
  ([D-059](#d-059)).
- **The role** is one ClusterRole: namespaces; in any namespace Secrets, NetworkPolicies and
  Topologies, Services to read and patch, pods to read, watch and delete, and `create` on
  `pods/exec`; and Leases in its own namespace. The rules are read from inside a pod before
  they are relied on.
- **Credentials** are `FYLGJA_*` variables set from Secrets ([D-042](#d-042)). A pull
  secret's entry is `FYLGJA_CREDENTIAL_<NAME>_REGISTRY` (the image prefix, a host and port
  with an optional path), `_USERNAME` and `_PASSWORD`.
- **The manifests** are a kustomize base under `deploy/`, with no address and no value in
  it, and an overlay under `local/` that sets the image, the Secrets and the addresses.
- **The image** is built by `make image` from a `Dockerfile` at the root: two stages on
  `python:3.14-slim` pinned by digest, a user that is not root, the platform and probe
  packages inside, `fylgja-core-server` its entry point, tagged by commit. It is pushed to
  the private registry as the gated image was. CI builds it and pushes nothing.

#### Consequences

- A core that loses its Lease stops mid-phase, which the record already survives.
- A rollout stops the core before it starts the next, so the API is away for a start's
  length.
- The image holds no containerlab: a core in a pod serves the clabernetes driver alone.

<a id="d-067"></a>
### D-067 — A kick on a settled twin inspects it, and a replaced node is pushed again under a `restore` run

**Status:** Accepted 2026-11-05. Details [D-023](#d-023)'s incarnation rule and
[D-036](#d-036)'s drain. Adds `restore` to API 1's run operations ([D-025](#d-025)).
Detailed by [D-070](#d-070) on 2026-11-06: findings 1's `restore`, the conditions a restore
touches, that it records no phase, its endings, the boot window and how a missing node is
named; D-070 also corrects the reason the options below give for rejecting a step run to the
twin's own bundle, which now pushes what holds nothing. The Consequences' "Repairing a twin is
not built" is detailed by D-070 item 13: on clabernetes the driver deletes a pod whose container
ended or restarted in it, and the cluster makes the node anew; the loop still makes no node.

#### Context

[D-023](#d-023) says a changed incarnation voids what a node holds and the loop pushes it
again, and [D-036](#d-036) relies on that after a drain. As built, a pass acts only on a
deletion or a new generation, and incarnations are compared only inside a step's apply. A
kick on a Ready twin, from the resync, the start or an event ([D-058](#d-058)), does
nothing, so a node the runtime replaced holds its kind's baseline until someone steps the
twin.

#### Options considered

- **Leave it, and let the trigger name twins nothing acts on.** Rejected: the behaviour is
  decided, and the cluster needs it at its first drain.
- **Push again inside the pass, with no run.** Rejected: a push changes a twin, and every
  change is recorded and attributable
  ([Constitution X](constitution.md#x-report-honestly)).
- **A `step` run to the twin's own bundle.** Rejected: such a step ends unchanged at
  `compiled` ([D-050](#d-050)), and `last_step` would show a step no client asked for.
- **A run of an operation of its own.** Chosen.

#### Decision

- **A pass on a settled twin inspects it.** Settled means no deletion asked, the generation
  observed, a deployment applied, no run in flight and not diverged. With every node running
  at its recorded incarnation, nothing is written.
- **A node at another incarnation is restored.** The pass takes a run of operation
  `restore`, its principal the core's own. It records the nodes as inspected, those nodes
  holding nothing, then runs `ready`, `pushed` and `verified` for them as a step does for a
  node whose incarnation moved ([D-050](#d-050)). `Ready` is False with the reason
  `twin.restoring` until the run ends. `last_step` is not touched.
- **A node missing or not running is waited for, never made.** The twin goes back on the
  queue; once the node's boot window has passed, the record says so (`Ready` False,
  `twin.node.missing`, naming the node) and the pass ends, to begin again at the next kick.
  Nothing is applied.
- **A failure.** A transient one backs off and is tried again ([D-023](#d-023)). A refusal,
  of the push or of a login, ends the run `failed` with `Ready` False for its rule; the
  record keeps the node's new incarnation, holding nothing, so no later pass repeats the
  push, and the twin is not diverged: its deployment is the record's.
- **A diverged twin and a twin with a run in flight are passed over.** A step compares
  incarnations itself.

#### Consequences

- API 1's run operations gain `restore`, and the rule catalogue `twin.restoring` and
  `twin.node.missing`.
- A resync costs one `inspect` a settled twin. On clabernetes that pass also returns a
  drifted Service to `Local` ([D-057](#d-057)).
- A container removed on the local driver does not return by itself: its twin stays
  `twin.node.missing` until it is stepped or deleted. Repairing a twin is not built.

<a id="d-070"></a>
### D-070 — The trigger and the restore as built

**Status:** Accepted 2026-11-06. Details [D-067](#d-067) (findings 1's `restore`, the principal,
the conditions a restore touches, that it records no phase, its endings and its cancel, the boot
window, how a missing node is named) and [D-058](#d-058) (what names a twin, what each driver's
`events` drops, their gaps and their failures); details [D-068](#d-068) (no path of the loop
reconfigures on a driver that declares `reapply`) and [D-069](#d-069) (a container restarted in
its pod). Supersedes [D-050](#d-050) in part, and [D-054](#d-054)'s item 5: a step to the
bundle the twin runs ends at `compiled` only when every device node holds it, and leaves `Ready`
False for `twin.node.missing` as it is; and corrects the reason [D-067](#d-067) gives for
rejecting a step run to the twin's own bundle. Adds `FYLGJA_RESYNC_S` to [D-042](#d-042).

#### Context

D-067 and D-058 fixed the restore and the trigger before code. Building them (phase 6, plan 5)
and running them on both drivers found what they leave open, and two places where a runtime does
not do what D-067's Context assumes.

- D-067 says the record names a missing node, and the twin record's condition has no member to
  name it in.
- It does not say what a restore does to a twin that already does not run what its spec asks,
  where its progress is kept across a kill, or what a failed or cancelled restore leaves a client
  to do.
- Its rejected option, a step run to the twin's own bundle, "ends unchanged at `compiled`": no
  longer so once a restore can fail and leave a node holding nothing.
- D-058 has the clabernetes driver name a twin for a pod's uid or readiness, which is less than
  what the loop reads of a pod; neither entry says how a source's failure is logged or what its
  gaps cost.
- D-067's Context assumes a replaced node lacks only its configuration. On the local driver every
  Docker restart path read loses the node's links. On clabernetes a replaced pod comes back whole,
  but a container restarted in its pod comes back without its management address
  ([verified-facts.md](verified-facts.md)).
- The resync, 300 s since [D-023](#d-023), had no setting, and a harness must set it long to show
  that an event, not the resync, restored a node.

#### Options considered

Naming a missing node:

- **A message on the `Ready` condition, or a member per node.** Rejected: twin record 1's
  conditions carry a type, a status, a reason and a time, and either is a format change for a
  fact the next `inspect` may undo.
- **The log, and under a restore its events and its finding.** Chosen.

What a failed or cancelled restore leaves:

- **Repeated at the next pass.** Rejected: a refused push or login would be tried again at
  every kick and every resync, and a cancel would not hold.
- **Not repeated: the nodes' new incarnations are recorded before any is pushed.** Chosen.

Where a restore's progress is kept:

- **`status.phase` or `last_step`.** Rejected: the phase says how far a create or a step got,
  and `last_step` would show a step no client asked for (D-067).
- **The nodes' `holds`.** Chosen: what is pushed is held, and a resume passes over it.

The remedy after a restore that failed or was cancelled:

- **A route or an operation a client asks for.** Rejected: a spec already says what the twin
  runs, and a second way to say it is a second contract.
- **A step to the twin's own bundle ending at `compiled`, as D-050 has it.** Rejected: it would
  set `Ready` True over a node holding nothing.
- **That step pushes what holds nothing.** Chosen.
- **`last_step.outcome` `failed` for such a step whose push failed.** Rejected: a format value
  no client asked for; the run's verdict says `failed` and `Ready`'s reason carries the rule.

`Ready` after a restore whose verify did not hold:

- **A reason, or a condition, for restores alone.** Rejected: `Ready` has never meant
  conforming ([D-032](#d-032)), and a reason or condition for restores alone would split its
  meaning by operation.
- **`Ready` as any run sets it.** Chosen; a condition carrying the last verify's status, for
  every run that verifies, is an [open question](#open-questions).

The boot window:

- **One window for the twin, from its first node gone.** Rejected: a drain evicts a twin's pods
  one after another, and a node gone later would be judged on the first's clock.
- **Kept in the record.** Rejected: a member for a count that moves every few seconds.
- **Each absent node's own window, from the first pass that saw it absent, in the core's
  memory.** Chosen: a restarted core counts again.

The trigger's gaps:

- **The clabernetes driver restarting its own watch.** Rejected: `LightKube.watch_pods`
  reconnects for itself and then delivers every pod again; a second loop would duplicate it.
- **The local source following before it lists, or following with `--since`.** Rejected:
  following first only narrows the gap, and `--since` needs a clock shared with a daemon that
  may be remote, and Docker's replay buffer of 256 events.
- **`PR_SET_PDEATHSIG` for the local source, or a wrapper binary.** Rejected: the first needs
  `preexec_fn`, unsafe beside the server's threads; the second is a binary to ship.

A container restarted in its pod on clabernetes:

- **Left reported**, `Ready` False for `readiness.timeout` until someone deletes the pod by hand.
  Rejected: a container restarting in its pod is ordinary on Kubernetes (an out-of-memory kill,
  a failed probe), and no Fylgja operation would mend it.
- **The loop applies again.** Rejected: a restore never applies (D-067).
- **The restart count out of the incarnation.** Rejected: the loop would read the node as it was
  and never act ([D-069](#d-069)).
- **The driver deletes the pod, and the cluster makes it anew.** Chosen: [D-057](#d-057) already
  has this driver delete a pod where the runtime cannot bring a node to its definition, a port
  added after boot; this is the same remedy for the same kind of fact.

When the driver deletes such a pod, and how often:

- **At the restart count's move.** Rejected: the kubelet restarts the container about 25 s after
  it ends, and that wait and the replacement's boot together run past an SR Linux node's 60 s
  boot window, so every such renewal read `twin.node.missing` for some seconds.
- **At the container's end**, a state no starting pod passes through. Chosen.
- **As often as the container ends.** Rejected: a node whose container keeps ending would be made
  anew at its crash rate for ever, where the kubelet alone slows it to one restart in five
  minutes, each round a pod, a restore run kept in the store and its log lines; and a pushed
  configuration that ends the container would be pushed again into each new pod.
- **At most three times in ten minutes a node.** Chosen.
- **A deletion that fails ends the watch under the watch's own backoff.** Rejected: each name the
  listing gives before the pod resets that backoff, so a deletion that always fails would list
  every pod and fail again each second.
- **Under a backoff of its own.** Chosen.

The resync:

- **Fixed at 300 s.** Rejected: a harness could not show the event's work apart from the
  resync's.
- **A setting.** Chosen.

#### Decision

**The restore** (details D-067):

1. **Findings 1's `operation` gains `restore`.** A run's verdict carries its run's operation, so
   a restore's names it; D-067 listed API 1's run operations alone.
2. **Its principal is `core`**, the one the loop already writes for a run no client asked for.
3. **What it touches.** It is taken only on a settled twin: no deletion asked, the generation
   observed, a deployment applied, no run in flight, not diverged; `Ready` is not part of it, so
   a twin a refused step or a failed restore left not Ready is still inspected. Where the twin
   runs what its spec asks, `Ready` is False for `twin.restoring` while the restore runs and True
   for `twin.ready` when it ends `ok`. Where it does not, after a refused or cancelled step, the
   conditions stay as that step left them. It never touches `status.phase`, `last_step`,
   `observed_generation`, `bundle_id`, `deployment_id` or `allocation`: it records no phase. Its
   progress is the nodes' `holds`, written as each node is pushed, and a resume is the same code,
   passing over what is held.
4. **It is not repeated.** The nodes are recorded as inspected, each moved one holding nothing,
   before any is readied, so a restore that fails (`readiness.timeout`, `credential.missing`, a
   refused or unauthorized push or login) or is cancelled leaves nothing the next pass finds
   moved, and a core restart retries nothing. Since it records no phase, a restore killed after
   its last push and then cancelled ends `failed` for `run.cancelled`, `Ready` False, though
   nothing was left to do; so does a cancel read during verify, after every push. A cancel read
   once verify is done ends it `ok`. A cancel that lands before the nodes are written (a core
   stopped between the take and that write) leaves the old incarnations, and the next kick
   restores again.
5. **Its wait** for verify is a step's, within `FYLGJA_STEP_WAIT_S`; an expiry is the warning
   `step.wait.expired`, its message naming the restore's wait, and the restore ends `ok`.
6. **The boot window.** A recorded node the inspection lacks or reads not running is waited for
   through its own window, its package's `readiness.timeout_s` (60 s SR Linux, 90 s cEOS, 30 s a
   ping host), from the first pass that saw it absent, kept in the core's memory and dropped by a
   pass that sees it run. Inside it the pass writes nothing and looks again within 5 s. Past it,
   with no run in flight, `Ready` is False for `twin.node.missing`, written once and only where
   the twin runs what its spec asks, and a restore run left queued by a take cut short (a core
   stopped between making the run and the record's naming it) is ended before it started, as a
   create's or a step's is by the run taken after it, since no pass takes a restore while a node
   is missing; with a restore in flight, the restore ends `failed`. A twin
   so reported whose nodes all run again is restored before it is Ready again: what holds nothing
   readied and pushed, and verify run, which is advisory.
7. **A missing node is named** in a WARNING line, and under a restore by the run's `ready failed`
   event and one finding per node, its object the node: the record's condition has no member for
   it.
8. **A step to the bundle the twin runs pushes what holds nothing** (supersedes D-050's
   unchanged step in part, and corrects D-067's rejected option). It ends at `compiled` only
   when every device node holds the twin's bundle. Otherwise it readies, pushes and verifies those
   nodes, with no plan, `changes` or apply, and a failure there leaves the twin up and not
   diverged, as a failed restore does. So a new spec is the remedy after a restore that failed or
   was cancelled; since an identical spec changes nothing, a client toggles `allow_restart` or
   names the bundle. Such a step records `last_step.phase` `compiled` whatever it pushed, and when
   its push fails its run ends `failed` while `last_step` reads `rejected`: twin record 1 has no
   outcome `failed`, and none is added. It never clears `twin.node.missing`, which is the settled
   pass's to clear. Resumed, it finishes what it began and does not take up a newer spec.
9. **`Ready` stays as any run sets it**: a restore whose wait expired ends `ok`, `Ready` True.
10. **A cancel** of a restore, by a client or by the twin's deletion, is read between phases,
    before each node and during every call on the runtime; it ends the run `failed` with
    `run.cancelled` and tears nothing down. Any authenticated principal may cancel the core's own
    restore, and the cancel is audited: there are no roles in phase 6. A deletion asked between a
    pass's `inspect` and its take of the restore is served once the restore ends: late, not lost,
    as for a step. A node replaced again after a running restore's `inspect` is pushed, and
    restored again at the next pass.
11. **Left, and known.** A probe host a failed restore never readied is not seen by the
    unchanged step's test, since probe hosts hold nothing and their readiness is not recorded; a
    verify shows it. On a twin that does not run what its spec asks, a restore ended for a
    missing node leaves the conditions as they were, so a node that returns at its old
    incarnation (a paused container unpaused, on the local driver) stays unpushed until a step.
    On clabernetes, while a pod's renewal keeps failing (a role without the right to delete pods,
    an admission webhook), the twins whose pods the watch lists after that pod are named by the
    resync alone, and the round repeats at most once a minute (item 13). And:
    - **A node running with no address at a new incarnation** is not absent, so its restore is
      taken at once and fails for `readiness.timeout` with nothing waited for, and it is not
      repeated when the address comes: the new incarnation is recorded holding nothing (item 4).
      Reproduced on the fake, not read on a runtime; it needs a pod that runs before its Service
      has an address. A new spec is the remedy (item 8).
    - **A node that returned and went again between two passes** keeps its first sighting, since
      only a pass that sees it run drops it: where the events between were missed, it is
      reported, or its restore ended, with no further wait.
    - **Restore runs are not bounded** for a node that keeps restarting: one stored run for each
      incarnation, at the pace of the kubelet's backoff for a left pod and of Docker's under
      `always` for a local probe host. Neither pace was read here, and each backoff starts short
      and doubles to its ceiling. The renewal's bound limits the pods, not the runs, and nothing
      prunes runs; a retention rule for runs is a later phase's.
    - **A renewal inside a hot-add's window**, between `apply`'s read of the pods' uids and the
      controller's pass, replaces the pod from the definition before; the hot-add's own deletion
      then reads it already replaced, so the added port does not arrive, and verify reports it.
      It needs a container to end in that window.
    - **What the clabernetes source read of a pod deleted while lightkube's watch was down** is
      kept until the source's own next restart: a fresh watch never delivers that `DELETED`. It
      grows slowly, and is left.
    - **Two cores on one cluster each renew.** The renewal goes by labels, which name no core:
      the deployed core and an in-process loop of a test tier would each renew the other's twins'
      pods (a deletion of a pod already gone is a 404, and fine) and each count its own three.
      This phase runs them one at a time for that reason; a label naming the core is later work.
    - **A renewal is counted and audited though the pod was already gone.** A deletion answered
      404 is taken as made, so a pod another hand deleted between the watch's delivery and the
      renewal's own deletion still gets its audit line and one of the node's three.
    - **A restore run left queued can outlast a quiet twin** where the core starts again without
      the twin's packages or its driver: the pass that would report the node missing, and end
      the run (item 6), is then never made. The run is ended once the core has both again.
    - **A left pod is not revisited.** The final review would revisit a left pod once, when its
      window has room, since a node that ended four times in ten minutes and then runs on is the
      node the renewal exists for, and it stays `Ready` False with no remedy through the API.
      Recorded as an option not taken: no timer is added in this plan (item 13).
12. **Links.** On the local driver a restore recovers a node's configuration, not its links:
    every Docker restart path read (`docker stop` then `start`, `docker restart`, Docker's own
    restart policy) loses the node's veths and its peers' ports, and the restore ends `ok` with
    `step.wait.expired`, `Ready` True, as after a step whose wait expired. Inferred, not read: a
    probe host Docker restarts (containerlab gives a `linux` node the restart policy `always`)
    comes back without its link and its address, since containerlab's `exec` lines set the
    address after the links are made and a restart runs neither, and ping's readiness expects the
    address on the interface; its restore ends `failed` for `readiness.timeout` after 30 s.
    `containerlab start --node` keeps links, and the remedy for such a twin is a delete and a
    create. On clabernetes, read: a replaced SR Linux or cEOS node's pod comes back with its links
    and its neighbours, and its restore's verify held at its first try; a replaced probe host's pod
    was readied and its restore's verify, its probe's burst through the host's link among the
    assertions, held after 31.6–32.6 s. A probe host's own links and neighbours were not read.
13. **A container ended or restarted in its pod on clabernetes** (details D-069, with D-057's
    remedy). Read on clabernetes 0.10.1, on an SR Linux node alone: a node whose container
    restarted in its pod keeps its links, its configuration and its servers, but its management
    subinterface, a DHCP client, holds no address again, and none of its ports answers from
    outside (240 s and 420 s read), while its pod reads `Ready`. That this is why the address
    answers nothing, and that no lease is served again, are inferred, not read; a cEOS node and a
    probe host were not read. Pushing such a node again cannot work, so the driver's `events`
    deletes a pod not being deleted whose container has ended in it or restarted in it, for every
    kind of node alike, before it names the twin, and the Deployment makes the node anew; the
    settled pass restores the new pod as any replaced one.
    - **What reads as ended:** the container's state `terminated`, read on the cluster at the
      count it had, about 25 s before the kubelet restarts it, a state no starting pod passes
      through (a pod starting shows no status, then `waiting` with no last state, then
      `running`); or `waiting` after a last state `terminated`, the form a container in the
      kubelet's backoff shows, which was not read on the cluster. A restart count above 0 is
      renewed too. Renewed at the end, the replacement runs inside the node's boot window. Read in
      three runs: the end was delivered 0.71–1.32 s after the kill and the pod deleted 0.04–0.06 s
      later; the replacement ran 41.1–47.3 s after the deletion, and the restore was taken
      12.7–18.9 s inside the 60 s window and ended `ok`, verify held, `Ready` True, 60.5–61.1 s
      after the kill, with no `twin.node.missing` at any time.
    - **The deletion** is held to the test the hot-add's deletions pass: the twin's own
      namespace, the twin's by its labels, the pod standing there at its uid, a node's, not being
      deleted. It comes before the twin is named: a pass the name kicks finds the pod being
      deleted, never the node running at an address that does not answer, where it would take a
      restore that could only time out. The rule reads the pod as delivered, not its move: an end
      or a restart during lightkube's own reconnect is delivered then, and one a fresh watch
      missed is renewed when that watch delivers the pod. Each deletion is one audit line by the
      core's own principal, `core`, the restore's, naming the twin, the node and the pod: it
      changes a twin under no run ([Constitution X](constitution.md#x-report-honestly)).
    - **The bound.** A node is renewed at most three times in ten minutes, counted in the
      driver's memory by twin and node, since a container that keeps ending would otherwise be
      made anew at its crash rate, where the kubelet slows it to one restart in five minutes, each
      round a pod, a restore run in the store and its log lines. Past that its pod is left, with
      one WARNING per restart, and its twin named: the node then reads as the in-place restart
      read before this rule, its restore `failed` for `readiness.timeout` and `Ready` False. No
      timer revisits a left pod. It is left until it is delivered again with room in the window
      (its next end or restart), until the core restarts, or until someone deletes the pod; a left
      pod that then runs on unchanged is not delivered again, and its twin stays `Ready` False for
      the restore's rule. That is the bound's cost, and its likeliest case is a pushed
      configuration that ends the node's container: the left pod boots again without the push,
      which cannot reach it, and stays up. The counts go with the twin: `destroy` drops them once
      it is gone, so a twin made again under its name starts afresh.
    - **`twin.node.missing` can still be read** for a node renewed late, its end missed by the
      watch and renewed at its restart count about 25 s later, and for a node left, whose
      container restarts in place under the kubelet's backoff and can be down past its window.
    - **A deletion that fails** names the pod's twin, ends the watch with a WARNING naming the
      pod's renewal by the failure's type and status, and waits a backoff of its own, growing
      whatever the round named before it, reset by a round that ends otherwise; the next watch
      delivers the pod again.
    - The loop is unchanged: it never makes a node and never applies in a restore. The restart
      count stays in the incarnation (D-069): it shows the loop a node that restarted where the
      watch was down, or before its pod is deleted.

**The trigger** (details D-058):

14. **What names a twin on clabernetes**: a pod of the owner added or deleted, or modified in its
    uid, its restart count, its phase, its deletion, its container's state or its `Ready`: what
    the loop reads of it through `inspect`, and whether it is Ready, which is more than D-058's
    "uid or readiness". A `Ready` blink costs two kicks and two inspects that write nothing. The
    watch is the driver's one call at cluster scope.
15. **What each source drops.** The local source passes over, at DEBUG and never quoting it, a
    line that is no JSON object or carries no lab label. The clabernetes source names nothing for
    a pod modified in nothing of the above, or that names no twin. A name that is no twin name is
    dropped below the seam.
16. **Gaps.** The clabernetes source relies on the watch's own reconnect: lightkube asks again at
    the version it reached and delivers what changed meanwhile, and after a version too old, a
    fresh watch after a failure or the driver's own restart, it lists every pod again; a twin
    whose every pod went during such a gap is named by the resync alone. The local source names,
    after a restart, every lab on the host and every twin it has a directory for under its root,
    so a twin whose every container went is still named; then it follows; an event between the
    listing and the subscription (about the docker CLI's start, at the core's start and after a
    stream failure) waits for the resync. Kept, since the resync bounds it, and a `die` whose
    `start` falls in the gap is caught by the absent node's poll.
17. **A core killed with SIGKILL** leaves its `docker events` running until the next event it
    prints.
18. **A driver's event never brings a twin's pass forward of its backoff.** A runtime's own
    events follow every apply and destroy, so a pass that failed after it changed the runtime
    (a deploy that made containers, a destroy part-way) is kicked by its own events; were they to
    bring the retry forward, the backoff, the loop's one bound on a failure that repeats
    ([D-023](#d-023)), would be lost, and on the fake such a deploy ran 634 times 0.01 s apart in
    3.5 s. So an event received while the failing pass runs, or while the twin waits its backoff
    out, queues it no earlier than the backoff's end, and the retry then reads whatever the event
    was about. A client's write (a spec, a deletion, a cancel) brings the pass forward as it did
    before: a twin waiting out its backoff is served at once, and one whose pass is running is
    served again as soon as that pass ends. So do the resync and a core's start. A pass that did
    not fail is unchanged: its own events cost the one settled pass after it. The backoff's
    growth and ceiling are as they were. A pass that fails in a way the loop does not class (a
    fault outside the seam's contract) is still the worker's to log with its traceback, and its
    twin now waits the same backoff before its next pass: before this plan such a twin waited
    for the resync or a write, and with events its own apply's event served it again at once
    (on the fake, 201 applies 6 ms apart in 20 s). The local reading of `docker rm -f` in
    [verified-facts.md](verified-facts.md) was made under the rule before, where the `destroy`'s
    kick ran a failed pass's retry at once.
19. **A source's failure is logged by its type and status**, never its text, and a transport
    failure's text is in no `KubeFailed`, at DEBUG alone: an error's text can name the cluster's
    API address, and a driver's failure reaches the run's events.
20. **The resync is a setting**, `FYLGJA_RESYNC_S`, an integer of 1 or more, default 300, refused
    otherwise as `FYLGJA_STEP_WAIT_S` is.
21. **No path of the loop reconfigures on a driver that declares `reapply`** (details D-068): a
    resumed create applies plainly, with no `inspect` before it, and a resumed step never asks
    `reconfigure`. On clabernetes `apply(reconfigure=True)` compares no Topology and writes no
    hot-add annotation, so a reconfigure cut short and resumed plainly would leave a port added
    after boot unarrived; no path reaches it.

#### Consequences

- D-042's list gains `FYLGJA_RESYNC_S`; the facts of both drivers' sources and of the cluster's
  restore are in [verified-facts.md](verified-facts.md).
- API 1's `BundleDiff.unchanged` says "the orchestrator skips a step on it". An orchestrator
  that goes by the diff alone never gives the remedy of item 8: after a restore that failed, it
  steps the twin to the spec it has, `allow_restart` toggled or the bundle named.
- The rule catalogue ([docs/rules.md](../docs/rules.md)) says each rule as built.

<a id="d-071"></a>
### D-071 — The core as a pod as built: the Lease's Role, one Kubernetes client above the seam, and the stop at a lost Lease

**Status:** Accepted 2026-11-07. Details [D-062](#d-062) (the Lease's rule, a Role beside the one
ClusterRole; what the Lease promises and what it does not; what the server does when it loses it;
what a store's fault on a read route answers) and [D-064](#d-064) (the client made in one module
above the seam, so three modules import lightkube, not two).

Status note (2026-11-07, plan 6 Task 8): item 3 holds only while the event loop runs. The
store's calls run on the loop, each bounded by `s3.TIMEOUT_S`; two in a row held it past the
deadline on the cluster (the holder stopped 21.08 s after its last renewal was sent, 6.08 s
late, while a waiter takes the Lease from about 15.5 s). Nothing checks the Lease's deadline
before a store write of the loop's, as each renewal checks it before its own write. Moving the
store's calls off the loop, or bounding them under the Lease, is a later decision's.

#### Context

D-062 and D-064 fixed the core's Lease, its role and its Kubernetes client before code. Building
them (phase 6, plan 6) found two places where they could not be built as written, and what they
leave unsaid.

- D-062's one ClusterRole holds "Leases in its own namespace". A ClusterRoleBinding grants a
  ClusterRole's rules in every namespace, so no rule it binds ends at a namespace.
- D-064 has the clabernetes driver and the Lease alone import lightkube. The Lease cannot call the
  driver's client: a module above the seam that imports the driver's package names a runtime
  ([D-046](#d-046)). Nor can it make its own by lightkube's default configuration, which falls
  back to `~/.kube/config` where the driver's refuses it by design; and a client lightkube cannot
  make raises more than its `ConfigError` ([verified-facts.md](verified-facts.md)).
- D-062 says the server exits when no renewal has succeeded within the duration. It does not say
  how a waiting core judges a holder whose clock it does not share, what a Lease deleted under its
  holder means, or what becomes of the requests in flight at a loss.

#### Options considered

The Lease's rule:

- **In the ClusterRole.** Rejected: bound cluster-wide, it lets the core's account write every
  Lease in the cluster, those of the cluster's own controllers among them.
- **A ClusterRole of its own, bound by a RoleBinding in the core's namespace.** Not taken: a
  cluster-scoped object for a rule that lives in one namespace.
- **A Role and a RoleBinding in the core's namespace.** Chosen.

The client:

- **The Lease makes its own lightkube client.** Rejected: two ways to reach the cluster, one of
  them reading `~/.kube/config`, which the driver refuses.
- **The Lease calls the driver's `client()`.** Rejected: a runtime named above the seam.
- **One module above the seam that names no runtime, `fylgja_core.kubeapi`.** Chosen.

The server at a loss:

- **uvicorn's graceful shutdown.** Rejected: it waits for every connection, a watch held open
  among them, so a request in flight could write after the duration the next holder waits.
- **The loop's stop begun and every connection cut before uvicorn's own shutdown, nothing
  released.** Chosen.

A store's fault on a read route:

- **A problem document a watch resumes from.** Not taken now: a change to API 1 and to the
  client, before what a gateway stopped under an open watch does has been read.
- **`500 server.error`, as before.** Chosen.

#### Decision

1. **The Lease's rule** (details D-062's role). A Role in the core's namespace,
   `fylgja-core-lease`, bound to the core's service account by a RoleBinding: `get` and `update`
   on the one Lease the core takes (`FYLGJA_LEASE`, `fylgja-core` in the base), and `create` on
   Leases, which a rule's resource names cannot confine (Kubernetes's RBAC documentation). The one
   ClusterRole holds the rest of D-062's rules: its `watch` on pods is the clabernetes driver's
   `events`, one watch across every namespace ([D-070](#d-070) item 14), and its `list` on pods
   lists a twin's pods in its namespace; its `delete` on pods is the renewal's and the hot-add's
   (D-070 item 13, [D-057](#d-057)); and an exec asks `get` and `create` on `pods/exec`, where
   D-062 names `create`, since its WebSocket upgrade is authorised as `get` and then as `create`
   ([verified-facts.md](verified-facts.md)). The base under
   `deploy/` states both roles and `core/tests/test_deploy.py` holds their rules as tables; they
   are read from inside a pod before they are relied on (D-062).
2. **One Kubernetes client, above the seam** (details D-064). `fylgja_core.kubeapi` makes the
   client from the service account in a pod, and from the file `KUBECONFIG` names off the
   cluster, never from `~/.kube/config`; what keeps it from making one is `Unconfigured`, naming
   the variable at fault. It names no runtime. `fylgja_core.clabernetes.kube` and
   `fylgja_core.lease` make their clients there, and the boundary test allows lightkube and httpx2
   in those three modules and no other. The Lease answers `Unconfigured` with a refusal carrying
   the variable, which the server names as it exits 2.
3. **What the Lease promises** (details D-062's Lease):
   - A holder is judged by the waiter's own clock, never by the Lease's times: a record (its
     holder and `renewTime`) seen unchanged for the duration, counted from the answer of the read
     that first saw it, is taken, replaced at the `resourceVersion` read. Two pods' clocks need
     not agree.
   - A holder stops at its deadline, the duration after the last renewal that succeeded was sent,
     and writes nothing then: each renewal, and the sleep before it, is bounded by the deadline.
     One renewal failing costs nothing.
   - A Lease deleted or emptied under its holder by another hand is lost at once, since a waiter
     creates a Lease that is not there, and takes one no one holds, at once. One deleted between a
     waiter's read and its take is read again.
4. **What it does not promise.**
   - `time.monotonic` does not count the time a host is suspended, so a host suspended past its
     deadline wakes holding the Lease by its own clock. The refusal of its next renewal stops it:
     a 409, the Lease read back held by another or by no one, or a 404, the Lease deleted. That
     comes within three times `RENEW_S` (5 s) of waking, since the sleep before that renewal, its
     write and a 409's read-back are each bounded by `RENEW_S`.
   - Two cores on one host share a holder name, the host's, so the second takes the first's Lease
     at once, as held under its own name. In a pod the name is the pod's, and each has its own.
5. **The server at a loss** (details D-062's exit): one ERROR line, rule `lease.lost`; the loop's
   stop begun and given `LOST_STOP_S` (2 s); every connection dropped, those uvicorn does not hold
   yet (a TLS handshake not done, a connection just accepted) among them, and each request in
   flight cancelled, none answered and none given grace, so no request writes after the loss; then
   uvicorn's own shutdown; nothing released; exit status 1. The cut rests on uvicorn 0.54.0's h11
   protocol and asyncio's event loop, both named in the server's configuration, and on an `assert`
   in asyncio that `-O` strips, so the server refuses to start optimised (`server.optimised`, exit
   2) ([verified-facts.md](verified-facts.md)).
6. **A store's fault on a read route** answers `500 server.error`, as before. A watch ends at once
   on a 5xx that carries a problem document, so a transient fault of an object store ends a
   client's watch. What a gateway stopped under an open watch does is read on the cluster first; a
   change is a later decision's.

#### Consequences

- The base carries two roles: the ClusterRole, stated in [SECURITY.md](../SECURITY.md), and a Role
  whose rights end at the core's namespace and its one Lease.
- A module that needs the cluster takes its client from `kubeapi`; a fourth module importing
  lightkube takes a new entry that supersedes this one, and a change to the boundary test.
- Left: a host suspended past its deadline can act beside the next holder for up to three times
  `RENEW_S` after it wakes.
- The server never runs optimised, and an upgrade of uvicorn or of Python reads the cut's facts
  again.

<a id="d-072"></a>
### D-072 — The core's own loop resumes on both drivers; the Temporal fallback is retired

**Status:** Accepted 2026-11-07. Supersedes [D-023](#d-023) in its fallback: Temporal is no longer
kept for a loop whose resume proves fragile; the rest of D-023 stands.

#### Context

D-023 chose the core's own reconcile loop and kept Temporal, through its Python SDK, as the
fallback should resuming mid-phase prove fragile. The local half was read in phases 4 and 5: a
server killed with SIGKILL at every phase boundary of a create and of a step, during a deploy and
during a destroy, resumed the same run each time it found the run unfinished
([verified-facts.md](verified-facts.md)). The clabernetes half waited for the core to run as a pod
([D-062](#d-062)): plan 6 read one pod deleted mid-apply resume its run with no gap in its events,
and left two readings to phase 6's conformance suite, a kill at every phase boundary and a kill that
releases nothing.

The suite (phase 6, plan 7) holds the kill scenarios once, for both drivers, and in each the dying
core hands nothing over to the next:

- **Locally** the harness sends the server SIGKILL: no handler runs, and nothing is released.
- **On the cluster** a pod's deletion, forced or not, still delivers SIGTERM, and the server
  releases the Lease within half a second, a graceful restart. So the harness kills the core in four
  steps ([verified-facts.md](verified-facts.md), "the conformance suite's cluster harness" and "the
  conformance suite on the cluster"):
  1. It labels the pod that holds the Lease and cuts its egress by a NetworkPolicy of its own.
  2. The cut leaves alone the connection the Lease's client holds, so the renewals usually ride on;
     where a renewal opens a new connection the cut refuses it, and the renewals stop. They stopped
     in two kills of one lifecycle run and in four of nine of another; that a new connection was
     the cause is the facts' explanation, not a reading.
  3. It writes an annotation on the Lease between two renewals, or once one is 6 s overdue: in the
     whole run, 15 of the 18 kills between two renewals and 3 of the 18 at the overdue mark.
  4. It deletes the pod with no grace, and the release the dying pod's SIGTERM handler sends meets a
     Conflict and is refused.

  The next pod takes the Lease 15 s after, as it would from a holder lost with its host.

On the cluster (k3s v1.37.1+k3s1, clabernetes 0.10.1, the core's image `c6be28acb35b`,
2026-11-07), every kill scenario of the suite passed with no step by hand, in its module's runs and
in the whole suite's: 35 kills, 9 more after the lifecycle module's review, and 18 in the whole run
([verified-facts.md](verified-facts.md), "the conformance suite on the cluster"). Locally, this
phase's two runs of the same scenarios made 18 kills a session, every one passing
([verified-facts.md](verified-facts.md), "the conformance suite on the local driver"). Every next
pod on the cluster waited for the Lease the pod that went still held, and the core answered again
21.2 to 26.5 s after each deletion. Every resume was the same run, its events without a gap: from
`applied` on, after the phase killed at, or after the next where the run had reached it before the
deletion (a step's `pushed`, resumed after `pushed` or `verified`), every node at the incarnation
the record held; at `compiled`, `admitted` and `planned`, after `planned`, applying again
([D-068](#d-068)). A waiting `twin create` and a waiting `twin destroy` each rode through its kill,
and a deletion asked after a kill in a step's apply ended the step `diverged` and the twin
destroyed. Two runs failed on the way, neither in the loop: a verify asked while a kept node's
Service was without its endpoint, now asked again while its only errors are nodes unread, and two
kills whose Lease was not renewed under the cut, now written at the overdue mark.

Two boundaries were not resumed on the cluster. The kill at a create's `pushed` and the kill at a
step's `verified` landed after the run had ended, in every run (the explanation, not measured
against those phases, is that the harness's wait for the renewal window outlasts them); nothing
resumed there ("the conformance suite on the cluster":
at `pushed` "the run had ended before the cut", at `verified` "the run had ended and nothing
resumed"). Locally the kill at a create's `pushed` found the run unfinished, and the resume wrote
its end (phase 4's block); a step's `verified` is past every resume there too, its `flows` phase
and the run's end taking about 10 ms (phase 5's steps block: "Killed after `verified`, the run had
already ended in each run"). So the resume at a create's `pushed` rests on the local harness
alone, and at a step's `verified` no kill on either driver finds a run to resume.

#### Options considered

- **Adopt Temporal now.** Rejected: no resume failed for it to fix, and it is one more stateful
  service to run, D-023's reason for rejecting short workflows.
- **Keep the fallback open.** Rejected: the question it was kept for is answered on both drivers.
- **Retire the fallback: the core's own loop is the control plane on both drivers.** Chosen.

#### Decision

- D-023's loop stands on both drivers. Its resume was read by kills that release nothing: locally
  SIGKILL of the process; on the cluster the four steps above, the pod that holds the Lease labelled
  and its egress cut by a NetworkPolicy of its own, an annotation written on the Lease between two
  renewals or once one is 6 s overdue, and the pod deleted with no grace, so the release the dying
  pod sends is refused. It was read during an apply and during a destroy on both drivers, and at
  every phase boundary of a create and of a step but a step's `verified` on the local driver, and
  on the cluster at all of those but a create's `pushed` too, where the kill found the run ended.
  At a step's `verified` the run ends within about 10 ms, and no kill on either driver finds it
  unfinished.
- Temporal is no longer the fallback. A proposal to adopt it, or another workflow engine, is a
  design document first ([D-033](#d-033)), with the kill the loop did not survive.

#### Consequences

- The kill scenarios of `core/tests/conformance/` guard the resume: a change to the loop's resume,
  or to a driver's `apply`, runs them on both drivers.
- The cluster's kill is not a partition: the holder dies with its pod. A holder that lives on, cut
  off from the API, keeps its Lease while the connection it holds lasts
  ([verified-facts.md](verified-facts.md)), and one held past its deadline by a slow store is
  [D-071](#d-071)'s status note; neither is answered here.
- design/core.md stops naming Temporal as the fallback.


## The API and its clients

<a id="d-025"></a>
### D-025 — The API is the core's boundary: API 1, with the twin as a resource in Kubernetes's shape

**Status:** Accepted at the baseline (2026-10-31).
Superseded in part by [D-063](#d-063) on 2026-11-05: TLS ends at the server, not an ingress;
added to by [D-067](#d-067) (the run operation `restore`) and [D-068](#d-068) (the
capability `reapply`); the rest stands.
Added to by [D-076](#d-076) on 2026-11-08: `GET /v1/capacity`.

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
Detailed by [D-084](#d-084) on 2026-11-09 (phase 8): following a run moves from
the CLI into the client library.

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
Added to by [D-064](#d-064) on 2026-11-05: lightkube for Kubernetes.
Added to by [D-083](#d-083) and [D-084](#d-084) on 2026-11-09 (phase 8): httpx is
the reader's one library, and the server's libraries become the `server` extra.
Superseded in part by [D-093](#d-093) on 2026-11-12: Prefect 3.9.2 was pinned three days old,
on the maintainer's word.
Superseded in part by [D-099](#d-099) on 2026-11-13: NetBox 4.7.5 was pinned two days old, on
the maintainer's word.

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
Added to by [D-057](#d-057), [D-061](#d-061), [D-062](#d-062) and [D-063](#d-063) on
2026-11-05: the clabernetes driver's two variables, the object store's, `FYLGJA_LEASE`, a
pull credential's `_REGISTRY`, and the TLS variables. Added to by [D-070](#d-070) on
2026-11-06: `FYLGJA_RESYNC_S`.

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

<a id="d-063"></a>
### D-063 — TLS ends at the server

**Status:** Accepted 2026-11-05. Supersedes [D-025](#d-025) in where TLS ends (an ingress);
adds to [D-042](#d-042): `FYLGJA_TLS_CERT`, `FYLGJA_TLS_KEY` and `FYLGJA_API_CA`.

#### Context

[D-025](#d-025) ends TLS at an ingress. The cluster has none: its prerequisites disable
k3s's ([D-036](#d-036)), and MetalLB gives a Service an address on the LAN. A client's
bearer token crosses that LAN, and a watch is a stream held open for minutes.

#### Options considered

- **An ingress or a gateway.** Not taken: a component to run and a proxy under every watch,
  for one backend.
- **Plain HTTP on the LAN.** Rejected: the token in clear.
- **`kubectl port-forward`.** Rejected: every client would need the cluster's credentials,
  and the orchestrator will hold only its token.
- **The server's own TLS behind a LoadBalancer Service.** Chosen.

#### Decision

- `FYLGJA_TLS_CERT` and `FYLGJA_TLS_KEY` name a certificate and its key, set together or not
  at all; with them the server serves TLS, and without them HTTP, as on loopback today. A
  listen address off loopback without them is logged as a warning at start.
- A client's `FYLGJA_API_CA` names a CA file its `https://` address is verified against;
  absent, the system's trust is used.
- On the cluster the core's Service is a LoadBalancer, and the pair comes from a Secret,
  signed by a private CA as the registry's certificate is.

#### Consequences

- A new certificate takes a restart of the pod.
- An ingress, should one arrive with OIDC, would sit in front of this unchanged.

<a id="d-064"></a>
### D-064 — Phase 6's libraries: lightkube for Kubernetes, and none for S3

**Status:** Accepted 2026-11-05. Adds to [D-039](#d-039); the rest stands.
Detailed by [D-071](#d-071) on 2026-11-07: the client is made in one module above the seam,
`fylgja_core.kubeapi`, which the clabernetes driver and the Lease import, so three modules
import lightkube.

#### Context

The clabernetes driver and the Lease need the Kubernetes API from an asyncio process: core
objects and a custom resource, a watch that survives its stream's end, an exec with separate
streams and an exit status, and a Lease replaced under its resourceVersion. The object store
needs four S3 calls ([D-061](#d-061)).

#### Options considered

- **The official client's asyncio half.** Rejected: 23 packages and about 98 MB, a sync stack
  beside it, and an exec whose channels are split by hand.
- **kubernetes-asyncio.** Rejected: aiohttp as a second stack, one maintainer, and no release
  for Kubernetes 1.37.
- **kr8s.** Rejected: no release since January 2026, a deprecation warning on Python 3.14,
  and a watch and a Lease still to write.
- **`kubectl` as a subprocess**, as the local driver runs containerlab ([D-018](#d-018)).
  Rejected: a 59 MiB binary in the image, a process a call, and errors as text.
- **REST over the pinned httpx, with httpx-ws.** Not taken: two packages, and 500 to 700
  lines of authentication, watch and exec protocol to write and keep. It is the fallback.
- **lightkube.** Chosen.

#### Decision

- **lightkube 1.0.1** with lightkube-models 1.37.0.8 carries every Kubernetes call. It
  brings httpx2 2.16.0 and msgspec 0.22.0: ten packages in all, each release at least two
  weeks old. What the driver relies on was read against the cluster on 2026-11-05
  ([verified-facts.md](verified-facts.md)).
- **Only the clabernetes driver and the Lease import it**, held by the test over imports.
- **The Lease is written in the core** over it: lightkube has no leader election.
- **httpx stays** for the push, readiness and the object store. The core holds two HTTP
  stacks until a decision moves it to httpx2.

#### Consequences

- lightkube has one maintainer and a 1.0 three months old; its facts are re-verified on any
  upgrade, and the fallback above is what replaces it.
- Its models are for Kubernetes 1.37, the cluster's.

<a id="d-076"></a>
### D-076 — `GET /v1/capacity`: the running driver's reading, for a client that looks before it asks

**Status:** Accepted 2026-11-08 (phase 7). Adds a path to [D-025](#d-025)'s API 1; answers
[D-073](#d-073)'s reading. Superseded in part by [D-079](#d-079) on 2026-11-09: the CLI's
command is `fylgja-core capacity show`.
Answered by [D-086](#d-086) on 2026-11-09 (phase 8): the example looks with a dry
run, and reads the capacity when it is refused for room.

#### Context

The orchestrator decides when to open a rehearsal. Today it learns that a twin does not fit
only by asking: a create ends `rejected`, or a dry run answers 422. With several proposed
changes open it would ask and be refused in turn, each a run. The maintainer asked that a
client be able to read the core's room before it asks.

#### Options considered

- **The refusal alone.** Rejected by the maintainer's call.
- **Capacity in `GET /v1/drivers`.** Rejected: that lists every driver and its static
  capabilities without reaching a runtime; the reading reaches the runtime and takes a
  moment.
- **A fit check for a given demand.** Rejected: the dry run is that already, with the compile
  and the plan.
- **`GET /v1/capacity`.** Chosen.

#### Decision

- `GET /v1/capacity` answers 200 with the running driver's reading ([D-073](#d-073)), taken
  then and outside the admission lock, a look and not a reservation: `driver`, `read_at`,
  `hosts` (each `name`, `cpu` and `memory_mb`, each `{total, free}`), `pending`
  (`{nodes, cpu, memory_mb}`) and `twins`, the count of twins with an allocation. Any
  authenticated principal may read it, as `GET /v1/drivers`. A runtime the driver cannot
  read answers 503 with a problem of rule `capacity.unread`, naming nothing of the fault the
  log does not.
- The CLI shows it as `fylgja-core capacity`: one row a host, then the pending demand and the
  count.
- The numbers are advisory: admission decides, with the same reading taken under its lock.

#### Consequences

- API 1 gains a path and a `Capacity` schema, additive.
- Whether and when the orchestrator reads it is phase 8's.


<a id="d-079"></a>
### D-079 — The capacity read as built: `capacity show`, and `read_at` from the core's one clock

**Status:** Accepted 2026-11-09 (phase 7's landing). Supersedes [D-076](#d-076) in the CLI's
command; details what the document's `read_at` and `twins` are. The rest stands.

#### Context

D-076 names the CLI's command `fylgja-core capacity`. The CLI is noun then verb
([D-026](#d-026)), and its parser gives every noun a verb. The plan of the route had `read_at`
in whole seconds, taken when the reading returned; `clock.py` promises that every date-time the
core writes comes from its `now()`.

#### Options considered

- **`fylgja-core capacity`, a noun alone.** Rejected: the one command of the CLI with no verb.
- **`fylgja-core capacity show`.** Chosen, as `twin show`.
- **`read_at` in seconds, at the reading's return.** Rejected: a second date-time form in
  API 1.
- **`read_at` from `clock.now()`, taken before the reading is awaited.** Chosen.

#### Decision

- The CLI's command is `fylgja-core capacity show`: one line a host with its free and total
  CPU and memory, then the pending demand, then the count of twins; `--json` prints the
  document.
- `read_at` is the core's clock read before the driver is asked, in the form of every other
  date-time of API 1.
- `twins` is the count of twin records with an allocation, the same records whose allocations
  the handler passes to the driver as `reserved` ([D-077](#d-077)).
- The reading is the default driver's.

#### Consequences

- [core.md](core.md) names the command as built.


<a id="d-083"></a>
### D-083 — The reader speaks plain HTTP through httpx, states the Infrahub versions it passed on, and is tested against a real one

**Status:** Accepted 2026-11-09 (phase 8). Adds to [D-039](#d-039): httpx is the reader's
one library beside the core's package. [D-034](#d-034) stands and binds the reader's tests.
Superseded in part by [D-091](#d-091) on 2026-11-12: the development Infrahub held 4.46 GiB,
not about 5.5.

#### Context

The maintainer's first worry for the reader is "trouble maintaining the module for an
updated Infrahub". The prototype read through `infrahub-sdk` and used one call of it,
`execute_graphql`, then undid two of its habits: the SDK rewrites a read's time, and its
errors drop the HTTP status Infrahub answered. `infrahub-sdk` 1.23.2 and 1.24.0b1 both
require `whenever<0.10`, and beside either a resolver picks Prefect 3.8.8 where 3.9.2 is
current (resolved 2026-11-09), so the SDK would hold back whatever platform the reader is
installed into. Infrahub 1.11.11 answered to curl each read tried of it: GraphQL on
`/graphql/<branch>` with `at`, a list's `count`, the schema and the version
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"). An artifact's status, checksum
and content, the stamps and the events were not among them; plan 2 reads them first.

#### Options considered

The library:

- **`infrahub-sdk`.** Not taken: one call used, two habits undone, and a pin that reaches
  the host platform.
- **A GraphQL client library.** Not taken: the reader sends a few fixed documents and needs
  no query builder.
- **httpx, which the core's client already uses.** Chosen.

How the pure tier is fed:

- **Recorded Infrahub answers**, as the prototype kept. Rejected by [D-034](#d-034):
  recordings go stale as the system changes, which is the maintainer's worry exactly.
- **The mapping tested on rows built in the tests; everything that meets Infrahub tested on
  a real one.** Chosen.

#### Decision

- **The reader depends on `fylgja-core` and httpx**, and on no SDK.
- **All of the reader's contact with Infrahub is in one transport module**, and every GraphQL document is a
  file in one directory. Nothing else in the reader builds a request.
- **The versions it passed on are stated** in the reader's README. At connect the reader
  reads Infrahub's version, and files a warning when it is not one of them.
- **Its contract tier runs against a real Infrahub**, seeded, at a version one make target
  takes: every read rule of [D-082](#d-082), and the same read twice giving one id. Its
  pure tier holds the mapping, the ordering and the completeness rule over rows built in the
  tests, and the import boundary.
- **An upgrade is a procedure**: start the new version, seed it, run the contract tier, read
  again the recorded facts the code leans on, and extend the list.
- **Infrahub is seeded by data files and a short script**, with Infrahub's own
  `infrahubctl` where it is the easy way, run from an environment of its own, so that the
  SDK meets nothing else. The archived repository's Go seeding tool is not carried.

#### Consequences

- The reader holds its own paging and its own error sentences, which the SDK would have
  given.
- A change in Infrahub's GraphQL schema shows as a contract-tier failure at the upgrade,
  not as a stale recording that still passes.
- The contract tier needs a running Infrahub, about 5.5 GiB on the development host.


<a id="d-084"></a>
### D-084 — What an integrator installs and calls: the core's base install is the model and the client, and the client follows a run

**Status:** Accepted 2026-11-09 (phase 8). Adds to [D-039](#d-039), [D-052](#d-052) and
[D-064](#d-064): their libraries are the `server` extra's. Adds to [D-066](#d-066): each
distribution carries its own formats and is checked from its wheel. Details [D-026](#d-026): the CLI's following moves
into the client library it shares.
Superseded in part by [D-090](#d-090) on 2026-11-12: the base install is four libraries,
`referencing` among them.

#### Context

[Constitution I](constitution.md#i-one-language-typed) asks for one model package for every
format two pieces read. It is inside `fylgja-core`, which pins twelve packages exactly,
among them the server's: starlette, uvicorn, grpcio, protobuf, pygnmi, lightkube. The
modules a reader needs (the blueprint, the probes, the findings, the schemas, the client)
import PyYAML, jsonschema and httpx alone. A reader installed into someone's platform would
bring the server and its exact pins with it.

Every integrator that writes a twin's spec must then find the run that write started and
follow it to its verdict. The thin CLI does this in private functions, and the client
library offers the calls beneath them and not the whole.

#### Options considered

- **A second distribution for the model.** Not taken: two packages and two versions for one
  model, and a move of every import.
- **Leave it.** Not taken: the reader would be hard to install, which the maintainer's
  standard for it rules out.
- **The server's libraries as an extra of the one distribution.** Chosen.

#### Decision

- **`fylgja-core`'s base install is the model and the client**: PyYAML, jsonschema and
  httpx, as ranges. **`fylgja-core[server]`** adds the server's libraries and repeats those
  three, all at today's exact pins ([D-039](#d-039)), so an install of the extra is today's
  install. The image, `make venv` and the wheel check install the extra. A test over
  imports holds that the model and the client import nothing of the extra.
- **The client library follows a run**: given the record a write answered, it finds the run
  the write started and follows it to its end and its verdict, riding through a reconnect.
  The CLI calls it there.
- **Nothing is published in phase 8.** Each of the three distributions is built and
  installed from its wheel into an empty environment, as the core's is today. The reader
  names `fylgja-core` with no version range until a first release gives it one.
- **Each wheel carries the formats its own code reads.** `formats/` at the root stays the
  one place a format lives. The core's wheel carries the core's, as today; the reader's the
  reader document; the example's its two documents.
- **Python 3.14 stays the floor** of all three.

#### Consequences

- A user on an older Python cannot install the reader. Lowering the floor is a later entry,
  with what it costs the core.
- An install of the base alone cannot run the server, and its console script says so.
- API 1 does not change.


<a id="d-085"></a>
### D-085 — The example orchestrator: a rehearsal library, a change source behind a seam, and Prefect at the edge alone

**Status:** Accepted 2026-11-09 (phase 8). Supersedes [D-003](#d-003) in "a Python project on
Prefect": Prefect serves the two deployments a source's check starts, and nothing else of
the example imports it. Builds on [D-081](#d-081).
Superseded in part on 2026-11-12 by [D-091](#d-091): the task workers are given the main
checkout's `.git` directory, not a clone; by [D-092](#d-092): the clean-up after a cancel is the
library's, one request, and no document is filed; and by [D-093](#d-093): the example's
account holds four permissions.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): a second change source, NetBox's,
behind the seam; the edge's source is a setting; and how one asks again is the source's to
say. The NetBox lines of this entry's context were read on a running NetBox that day.
Detailed by [D-100](#d-100) on 2026-11-13 (phase 9's landing): the NetBox change source, the
seam's two sentences and the edge's settings as built.

#### Context

The example exists to be read and taken apart ([D-081](#d-081)). Someone with another
workflow engine should keep its rehearsal and replace its edge; someone with NetBox should
keep its rehearsal and its edge and write the source's side. The maintainer said Prefect is
not required, and is fine where replacing it would mean more bespoke code.

Infrahub's check needs something it can start over HTTP, wait on for many minutes, cancel,
and read a document from. Prefect 3.9.2 gives each of those to a caller with httpx alone,
installs beside the core, and after a cancel or a time limit gives the flow's body about
30 s of clean-up after a cancel; after a time limit clean-ups of 20 s ran whole, and longer
was not read ([verified-facts.md](verified-facts.md), "Prefect 3.9.2"). Calling a
decorated flow with no server starts one, 10 to 34 s a call.

What NetBox offers was read from its documentation on 2026-11-09 (NetBox 4.7.4,
netbox-branching 1.2.3, NetBox Change Management 1.1.3) and on no running system. As
documented: a change is a bare branch, with a change request only in NetBox Cloud and
Enterprise; a branch is one flat state, with no ordered steps and no read as of an earlier
time; the trigger is a webhook, sent once and waiting for nothing; a report would be a
comment on a change request or a journal entry on the branch; there is no check object; and
configuration is rendered on request.

#### Options considered

What runs a rehearsal a check starts:

- **A small HTTP run service of the example's own.** Not taken: a service, a store of runs,
  its auth and its cancel, all bespoke, where Prefect has them.
- **The rehearsal inside Infrahub's check.** Rejected: the core's token, the reader and the
  rehearsal's code would live in Infrahub's workers.
- **Prefect for every command, as the prototype.** Not taken: each command would need a
  server, and the rehearsal would be written in the engine's terms.
- **Prefect for the two deployments a check starts, and plain functions beneath.** Chosen.

#### Decision

- **Three layers.** The **rehearsal library** holds the plan, the create, the step, the
  rehearsal, the documents and the report, and imports the core's client and model alone.
  The **Infrahub change source** finds a proposed change and its stages, reads them through
  the reader, and posts the report. The **edge** is two Prefect deployments, the command
  line and Infrahub's two checks.
- **The seam to a source is four calls**: the change a trigger names; its stages, in order;
  a stage read into a blueprint or its findings; and the report posted with its status. A
  stage carries a label, a description and a pin that only its source reads.
- **The library assumes none of these**: that a stage can be read later; that the source has
  an object of review; that the trigger is reliable, comes once or waits for the answer; that
  the source holds a verdict; that the report is a comment; that configuration is a stored
  artifact.
- **The Infrahub change source** finds the open proposed change by its source branch, takes
  its stages as [D-088](#d-088) orders them, gives the reader `generated_since` where the
  proposed change's artifact validation gives it one ([D-082](#d-082)), and posts the report
  as a thread. It has a transport of its own for its few queries and its two mutations; the
  reader's transport is the reader's alone.
  Its account needs the three permissions a thread and a comment take
  ([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"); the reader beneath it still
  sends no mutation.
- **All six of the prototype's capabilities stay** (the maintainer, 2026-11-05). `intent
  read` and `schema check` are the reader's own commands. `stage list`, `stage plan`, `twin
  create`, `twin step` and `twin rehearse` are commands of the example that call the library
  in the command's own process, with no Prefect. **`stage-plan` and `twin-rehearse` are also
  deployments**, since a check starts them.
- **The two checks**, `fylgja-step` and `fylgja-twin`, use the standard library and httpx.
  Each finds the proposed change, starts its deployment, asks once more on a 503, waits,
  reads the run's document and concludes from its status alone. Neither holds the core's
  token. A check's timeout is set above the rehearsal's time limit. A draft is not
  rehearsed.
- **Clean-up after a cancel or a time limit is the flow's `finally`**: it asks the core to
  cancel the run in progress and to delete the twin, two requests that each answer at once,
  and waits for neither to finish; the core's destroy goes on by itself. It files the
  document it has if it can. A run that ends with no document is concluded by the check from
  the run's state: the rehearsal was stopped, and the twin's deletion asked.
- **Infrahub's registration** is `.infrahub.yml` at the root. It carries the development
  fixture's configuration template and artifact definition, which the reader's contract tier
  needs, and the example's two checks. While phase 8 is built, and for the acceptance run,
  Infrahub reads it from a clone mounted into its task workers. Pointing it at this
  repository on GitHub needs a push, so it is the landing's, on the maintainer's word.
- **Read first in plan 5**, none of it read yet on the version built against: how a proposed
  change is found by its source branch, with its draft flag; what its artifact validation
  says and when, and what the reader meets while that validation still runs, as it does when
  a check starts at the proposed change's creation; a check's timeout, its environment and
  what its message shows; and Infrahub's task workers reaching Prefect on the host. The
  change source is meant to wait, under a bound, for an artifact validation still running
  before it reads the head; the entry is restated if the reading shows that is not enough.

#### Consequences

- The example needs a Prefect server and a runner beside the core, which Infrahub's task
  workers must reach, and a token of the core's for a principal of its own.
- What a NetBox user does to mark the steps of a change is that phase's question; the seam
  only keeps from ruling an answer out.
- The NetBox lines above are documentation, and are read on a running NetBox before code
  depends on them.


<a id="d-086"></a>
### D-086 — The example's rehearsal: one twin a rehearsal, a look before it asks, "ask again" without a retry, and what it leaves out

**Status:** Accepted 2026-11-09 (phase 8). The maintainer confirmed on 2026-11-09 that
`admission.capacity` is kept as "ask again" with no retry in the example; the look by dry
run and the capacity read on a refusal are this entry's own. Answers what [D-076](#d-076) and phase 7 left to phase 8: when the orchestrator reads
the capacity, and what it does with `admission.capacity`. Restates the archived repository's
rehearsal for this repository, without its hardening.
Superseded in part by [D-092](#d-092) on 2026-11-12: the reclaim takes a twin under the
rehearsal's own name too; a deletion is read until the twin is gone, not followed; the time
limit is a deadline the library checks; and `stopped` is a fourth status.

#### Context

The maintainer said on 2026-11-09 that the example may drop the prototype's hardening:
reclaiming a dead rehearsal's twin, a deadline summed from package budgets, and retrying
while the runtime is busy. Phase 7 refuses a twin that does not fit, queues nothing, and
says "the orchestrator asks again" ([D-073](#d-073)); it built `GET /v1/capacity` because
the maintainer asked that a client be able to look before it asks ([D-076](#d-076)).
Verify does not wait outside a step's run, and a twin's protocols take a moment to settle
after a create.

#### Options considered

A refusal for room:

- **Retry inside the rehearsal, under a deadline**, as the prototype. Not taken: the
  hardening the maintainer said the example may leave out.
- **A queue in the example.** Not taken: an integrator's platform has its own.
- **End as not rehearsed, and say "ask again".** Chosen.

Looking before asking:

- **Not at all.** Rejected by D-076's context.
- **Read the capacity and compare it with the twin's demand in the example.** Not taken: the
  fit rule is the core's, and a dry run is the core applying it.
- **A dry run of each stage before anything is created, and the capacity read shown when one
  is refused.** Chosen.

#### Decision

- **One twin a rehearsal, named from the change and the run.** At its start a rehearsal
  deletes every other twin named for its change, left by a dead rehearsal or held by a live
  one, and follows each deletion to its end, so the newest rehearsal of a change is the one
  that stands. At its end it deletes its own twin and no other. A rehearsal whose twin was
  deleted under it says so in its report. This is the whole of the example's reclaim.
- **The path.** Plan: each stage read, filed and built, each bundle diffed against the one
  before. Leading stages that select no device are passed over, and the first that builds
  is the baseline. Look: a dry run of each stage as the twin it would make, which shows room
  and images, and not what a step alone would refuse. Create the
  baseline and follow its run. Settle: verify asked again until it holds or a fixed budget
  passes, what still fails then being recorded as failing before the change. Step to each
  later stage, restarts allowed, and verify; a failure the baseline did not have is the change's. Stop at the
  first stage that fails, later ones not reached. Destroy the twin on every path. Write the
  document, render the report, post it.
- **A stage whose bundle is unchanged is skipped only while the twin is Ready.**
- **`admission.capacity` means "ask again".** A dry run or a run refused for room ends the
  rehearsal as **not rehearsed**, a status of its own beside failed. The example then reads
  `GET /v1/capacity` and shows the room in the report. Nothing is retried: asking again is a
  re-run of the checks, or the retry of whatever platform an integrator runs.
- **Other plain failures are reported and not retried**: an image absent, the core
  unreachable or refusing the token, a run cancelled, a destroy that leaves something. Each
  report says which, and what to do.
- **One fixed time limit** bounds a rehearsal.
- **Left out**: any reclaim beyond the twin's name; a deadline computed from the packages;
  a retry on a busy runtime; a bound on how many rehearsals run at once; loss across a step.
- **Two documents of the example's own**, the plan and the rehearsal, each with a format in
  [`formats/`](../formats/README.md), every field read by the report, a check or a command.
- **A record per twin**, a file in a directory, for `twin step` and `stage list`: the
  change, the stage and the blueprint id, trusted only while that id is the twin's.

#### Consequences

- On a busy runtime a proposed change's check fails with "ask again" until someone re-runs
  it. An integrator who wants more writes it in their platform, with the capacity read.
- A runner that dies mid-rehearsal leaves a twin until that change is rehearsed again or
  someone deletes it; `fylgja-core twin list` shows it, named for its change.
- Two rehearsals of one change at once end as one report of a rehearsal and one of a twin
  deleted under it.
- The dry run of a later stage is judged as a whole twin, where the step that follows adds
  only what the stage adds, so the look can refuse what the step would have fitted. Erring
  that way starts nothing that cannot finish.


<a id="d-087"></a>
### D-087 — The rehearsal's report: the verdict first, each failure with its message, and no loss

**Status:** Accepted 2026-11-09 (phase 8). Restates the archived repository's report (its
D-053) for this repository, in a new form. Lets findings 1's `loss` stand without a consumer
until the flow is built.
Superseded in part by [D-092](#d-092) on 2026-11-12: the heading gives a fourth verdict,
stopped; and the summary keeps one duration, and names the twin where the cause is the twin.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): in NetBox the report is one journal
entry on the branch, its kind the verdict, with no bound on its size.
Detailed by [D-100](#d-100) on 2026-11-13 (phase 9's landing): the sentence on when the stages
were read as built, for either source, the lines a summary always keeps grown with it; and in
NetBox an empty line put before each list of the entry.

#### Context

The maintainer asked that loss be removed from the report and that the report be improved
otherwise. The prototype's report was a table of ten columns with times and hashes, a
diagram, and findings named by rule id alone, cut to fit one comment. A comment's text is at
most 4,092 bytes on Infrahub 1.11.11, and a thread takes more than one comment
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11").

#### Options considered

- **One comment, findings by id**, as the prototype. Not taken: the reader of the report
  must look elsewhere for why.
- **A link to a document kept elsewhere.** Not taken: the proposed change would not hold its
  own report.
- **A summary comment and a detail comment in one thread.** Chosen.

#### Decision

- **The heading is the verdict**: passed, failed at which stage of how many, or not
  rehearsed. The first sentence gives the cause.
- **One table of five columns**: the stage's number, its label, what changed in words (from
  the bundle diff), the result, and verify's count. Times, ids, the twin's name and the run
  go in the detail comment.
- **Each failure is given with its message.** What the twin does not model is listed in
  plain words, and so is what was already failing before the change.
- **The wait is mentioned only when it expired. Loss is not reported.**
- **The report says when the stages were read**, that later edits are not rehearsed, and
  that fidelity is asserted, not measured
  ([Constitution X](constitution.md#x-report-honestly)).
- **The summary is the thread's first comment and the detail its second**, each within the
  bound; what does not fit the detail is cut with a line saying so.
- **The check's message** is the heading and its first sentence, and says the report is in
  the proposed change's thread.
- **A report that cannot be posted** does not change the rehearsal's status; the document
  carries a warning naming the proposed change.

#### Consequences

- The report is tested by what it says, and is held byte for byte to nothing.
- How a thread of two comments renders in Infrahub's view was not read; the plan that builds
  the post reads it.
- Findings 1 names the report as the consumer of `loss`. The core measures none
  ([D-051](#d-051)), so with the report's column gone the field has no consumer. It stays,
  by this entry, until the phase that builds the flow gives it one
  ([Constitution XII](constitution.md#xii-every-field-earns-its-place)).


<a id="d-090"></a>
### D-090 — The base install and the client's following as built: four libraries, and a follow that takes no timeout

**Status:** Accepted 2026-11-12 (phase 8's landing). Supersedes [D-084](#d-084) in one part:
the base install is four libraries, not three. Details it in how the client follows a run and
in where a distribution finds its formats. The rest stands.

#### Context

D-084 counts three libraries the model and the client import: PyYAML, jsonschema and httpx.
Phase 8's plan 1 found a fourth: `schemas.py` imports `referencing` directly. D-084 says the
client "follows a run … to its end and its verdict" and not what ends a follow that should
stop; plan 4's rehearsal needed one time limit over many follows, and plan 0's reconciliation
settled how (its items 3 and 14; rulings P1-4 and P1-5).

#### Options considered

- **`referencing` left to arrive with jsonschema**, which requires it. Rejected: a library
  the base imports by name is the base's to declare.
- **A `timeout` on `follow` and on each of the client's calls.** Not taken: a caller with one
  limit over several calls would have to share it out among them.
- **No timeout: the caller's limit is a deadline it checks itself**, between calls and in the
  `progress` it hands `follow`. Chosen.

#### Decision

- **The base install is httpx, jsonschema, PyYAML and referencing**, as ranges.
  `fylgja-core[server]` repeats the four at exact pins and adds the server's libraries.
  `fylgja-core-server` run from a base install refuses with `server.extra.missing` and exits 2,
  naming the module it lacks ([docs/rules.md](../docs/rules.md)).
- **`Client.follow(record, operations, *, progress=None)`** answers the last record seen, the
  run the write started, ended and carrying its verdict, and whether the twin is gone. It
  takes no timeout, and neither do the client's other calls. An exception that `progress`
  raises leaves `follow`, held by a test, so a caller ends a follow at its own deadline from
  there.
- **The CLI's `twin destroy` follows as it did**, to the twin gone, and prints what it
  printed.
- **`schemas.formats_dir(package)`** answers `<package>/formats` in a wheel, and for a package
  under a checkout's `src/` the first `formats/` above it, so each distribution's code finds
  the formats its own wheel carries.
- **One development venv**, `core/.venv`, holds the three distributions editable. That the
  reader installs with the base alone is proven by the wheel check, not by that venv.

#### Consequences

- A watch on which the core reports nothing calls no `progress`, so a deadline checked there
  does not fire. The example bounds that case from outside, by its flow's time limit
  ([D-092](#d-092)); an integrator's platform must do the same.
- [core.md](core.md) names the four libraries.


<a id="d-091"></a>
### D-091 — The development Infrahub and its seed as built: `infrahub/` at the root, the task workers given a `.git` directory, and each worker holding the registered commit

**Status:** Accepted 2026-11-12 (phase 8's landing). Supersedes [D-083](#d-083) in one part,
the memory the development Infrahub takes, and [D-085](#d-085) in one, what Infrahub's task
workers read the registration from. Details [D-081](#d-081), D-083 and [D-088](#d-088) in
where what Infrahub fetches lives and in what the seed makes. The rest of each stands.

#### Context

The phase's design left "to the builder" where the development Compose files and the seed's
data live, and put what Infrahub fetches with the example, under `orchestrator/`. Plan 2
built the development Infrahub before `orchestrator/` existed, and the reader's contract tier
uses the same registration and seed. D-085 has Infrahub read the registration "from a clone
mounted into its task workers". D-083 gives the instance "about 5.5 GiB", read at the end of
a throwaway instance on 2026-11-09. Plans 2, 3 and 5 read the rest on Infrahub 1.11.11
([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"; plan 0's bends and its
reconciled items 1, 11 and 20; rulings P2-23, P5-17, P5-29, P5-31, P5-53 and P5-54).

#### Options considered

What the task workers are given:

- **The main checkout, mounted.** Rejected: the checkout holds `local/.env`, and the workers
  run repository code.
- **A bare mirror kept beside it.** Not built: it was the fallback had the `.git` of a
  checkout with linked worktrees not answered git in the workers, and it did (ruling P2-5).
- **The main checkout's `.git` directory alone, read-only.** Chosen.

A recreated worker, which holds no clone of the registration:

- **One task worker**, so that one import reaches every worker. Not taken: `fylgja-twin` holds
  a worker for as long as a rehearsal, and the validation the change source waits on would
  queue behind it; whether a worker runs tasks side by side was not read.
- **Two workers, and a registration that is settled only once each holds the commit's tree.**
  Chosen.

#### Decision

- **What Infrahub fetches, and what the development Infrahub is given, live in `infrahub/` at
  the root**: the queries, the template, the two checks and their glue, the schema library's
  DCIM and the example's stage kind, the seed, and the Compose override under `dev/`.
  `.infrahub.yml` is at the root. `infrahub/` is no distribution. What a run makes (the
  fetched Compose file, `infrahubctl`'s venv, `seed.json`) is under `local/infrahub/`.
- **The task workers are given the main checkout's `.git` directory, read-only**, and one
  directory of throwaway repositories beside it, read-only too. Nothing else under `local/`
  reaches a worker.
- **Every task worker must hold the registered commit's tree before a proposed change is
  opened.** A recreated worker holds none, and a user check that lands on it fails. `make
  infrahub-register` imports until each worker holds the tree, and refuses at 300 s naming a
  worker that lacks it and saying to run it again. It follows every `make infrahub-up` that
  recreates a worker.
- **The instance held 4.46 GiB** on the development host, Neo4j capped by the override: a
  derivation, the sum of its containers' memory as read once.
- **The seed.** `infrahubctl` runs from a venv of its own under `local/infrahub/`. A stage's
  time in `seed.json` is the reader's own `head` of the branch, taken once the instance is
  quiet, so the seed and the reader cannot disagree; the seed imports the reader for it, the
  one Fylgja package it imports. `make infrahub-seed` always makes its branch anew: the
  branch's marks and its open proposed change are removed first, then the branch. The fixture
  is loaded on `main` only where `main` holds none of its devices; a hand-edited `main` is
  restored by a purge and a seed.

#### Consequences

- Any deployment's task workers must each hold the commit before a proposed change is opened
  ([docs/integrating.md](../docs/integrating.md)). Whether a check ever lands on a worker that
  lacks its branch's commit was not read ([open questions](#open-questions)).
- A closed proposed change and its thread were read to stay through a later seed.
- The registration is still read from the mounted `.git`. Pointing it at this repository on
  GitHub is the maintainer's to ask for ([D-094](#d-094)).
- [core.md](core.md) and [CONTRIBUTING.md](../CONTRIBUTING.md) say where each piece lives.


<a id="d-092"></a>
### D-092 — The example's rehearsal, its clean-up and its report as built: a fourth status, a deletion read until the twin is gone, and no document after a cancel

**Status:** Accepted 2026-11-12 (phase 8's landing). Supersedes [D-085](#d-085) in one part,
the clean-up after a cancel or a time limit; [D-086](#d-086) in four, the reclaim, how a
deletion is waited for, what a time limit is and the fourth status; and [D-087](#d-087) in
two, the verdicts a heading can give and what the summary holds. Details the seam's types, the
twin's record and the report's two comments. The rest of each stands.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): the seam gains the two sentences a
source gives, and the report's sentence on when its stages were read is made true of a
stage read earlier.
Detailed by [D-100](#d-100) on 2026-11-13 (phase 9's landing): the two members' names, and the
sentence as built.

#### Context

Phase 8's plan 4 built the rehearsal library, and plan 5 its edge. Five things could not be
built as D-085, D-086 and D-087 word them (plan 0's bends and its reconciled items 2, 3, 4
and 15; rulings P4-2, P4-3, P4-7, P4-10, P4-11, P4-13, P4-14, P4-17 to P4-22 and P5-46).

- D-085 has the flow's `finally` send the core a cancel and a delete, "two requests", and file
  "the document it has if it can". API 1's `DELETE /v1/twins/{name}` marks the run in flight
  `cancelling` itself, so one request does both; and a rehearsal ended by a cancel has written
  no document to file.
- D-086 has a rehearsal follow "each deletion to its end". This core files no verdict for a
  destroy and retries a failed one without end, so a destroy has no end to follow to.
- D-086's reclaim deletes "every other twin named for its change". A rehearsal retried under
  the same run id would then meet its own earlier twin, and `twin.exists`, for ever.
- D-086's "one fixed time limit" does not say how it is kept. The client's calls take no
  timeout ([D-090](#d-090)).
- D-086 names two statuses beside passed, failed and not rehearsed, and D-087's heading the
  same three verdicts. A rehearsal that passed its limit, whose run another client cancelled
  or whose twin was deleted under it is none of them: nothing can be said of the change, and
  nothing was wrong with the runtime.

#### Options considered

The clean-up after a cancel:

- **In the flow's `finally`, two requests and a filing**, as D-085. Rejected: the second
  request is redundant, the engine's terms would enter the clean-up, and there is no document.
- **In the library, on any exception it does not conclude from: ask the deletion, and raise
  again.** Chosen.

A deletion's end:

- **Follow the destroy's run.** Rejected: it has no verdict.
- **Ask, and wait for nothing.** Not taken for the reclaim: the next create would meet the
  twin still there.
- **Ask, then read the twin until it is gone, under a bound.** Chosen.

A stopped rehearsal's status:

- **`failed`.** Rejected: the report would blame the change.
- **`not_rehearsed`.** Not taken: its remedy is the runtime's set-up, and here there is none.
- **A status of its own, `stopped`.** Chosen.

#### Decision

1. **The clean-up after a cancel or a flow's time limit is the library's, and one request.**
   `rehearse` asks the twin's deletion on any exception it does not conclude from, an
   interrupt and the engine's cancel among them, waits for nothing, posts nothing and raises
   it again. The flow's `finally` files a document only where it was handed one, and then
   closes the source and the core's client, which sends nothing. After a cancel no document is
   filed, and the check concludes from the run's state: stopped, the twin's deletion asked.
2. **A deletion is asked, then the twin is read until it is gone, for at most 120 s**, for the
   rehearsal's own twin and for each it reclaims. A reclaimed twin still there then ends the
   rehearsal `not_rehearsed` (`rehearsal.twin.held`); its own twin still there is a warning
   that names it and the command that removes it (`rehearsal.twin.left`). Where the core
   cannot be read, the deletion is asked once and the report says it was not confirmed.
3. **The reclaim takes a twin under the rehearsal's own name too**, beside every other twin
   named for its change: at its start nothing is this rehearsal's yet.
4. **The limit is a deadline the library checks itself**: between calls, in its own waits, and
   in the `progress` it hands `follow`. It is 3,600 s. A rehearsal the library stops there
   returns its document as any other, and then cleans up for up to the 120 s of item 2. A
   watch on which the core reports nothing is bounded from outside, by the flow's own limit
   ([D-093](#d-093)) or an interrupt of a command.
5. **Four statuses**, given by the document's first error finding and by nothing else:
   `passed`; `failed`, where the change failed at a stage; `not_rehearsed`, where the
   rehearsal could not be carried through for a reason that is not the change's (room, an
   image, another refusal for the runtime's set-up, the core unreachable or refusing, the
   source failed, an earlier twin still held, nothing to build); and `stopped`, where it was
   stopped before anything could be said of the change (the limit, a run cancelled by another
   client, the twin deleted under it). A step the core ended `diverged` with `step.diverged`
   its only error was cancelled by another client after its apply began, and is `stopped`. A
   create or a step refused for the runtime's set-up (`admission.*`, `credential.*`) is
   `not_rehearsed`, at the look or after it. The rules are in `orchestrator/rules.md`.
6. **The seam's types carry more than D-085 lists.** A change carries the reference it was
   named by, the source's id for it, its name and `where`, the change in words. A stage
   carries `where`, its pin in words, beside its label, its description and its pin. A read
   says whether the scope selected no device. The source states `comment_limit`, the bytes one
   part of a report may take.
7. **The twin's record** holds the reference the change was named by, the scope and when it
   was written, beside the change, the stage and the blueprint id. It is written where a step
   ended `ok` and also where the twin already ran the target's blueprint, so that `twin step`
   moves past an unchanged stage.
8. **The report.** Its heading gives one of four verdicts, `stopped` among them, and names one
   stage or none. "What failed" appears in a `failed` report alone; a `not_rehearsed` or
   `stopped` report carries its cause in the first sentence and in the detail. The summary
   keeps one duration, and names the twin only where the cause is the twin. The detail puts
   first what the summary points to, then each stage, with its wait where one expired, its
   skipped checks and the twins reclaimed. A rehearsal that ended before its plan was read
   files `plan` as null, and its summary says the stages were not read.

#### Consequences

- A cancelled rehearsal leaves no document: its only account is the check's message and the
  core's own record of the twin and its runs.
- A reclaim can take up to 120 s a twin before the rehearsal starts, and the clean-up up to
  120 s after its limit.
- A step that diverged for a reason the core filed no finding for reads as cancelled.
- How a thread of two comments renders, which D-087 left unread, the maintainer read in a
  browser on 2026-11-12: both comments as markdown, the summary's table as a table
  ([verified-facts.md](verified-facts.md), "A proposed change created by the maintainer in the
  UI, rehearsed through its own check, on the local driver").
- [core.md](core.md) says the clean-up and the statuses as built.


<a id="d-093"></a>
### D-093 — The Infrahub change source, the two checks and the edge as built: four permissions, the head read once the validation has completed, and a draft planned but not rehearsed

**Status:** Accepted 2026-11-12 (phase 8's landing). Supersedes [D-085](#d-085) in one part,
the permissions the example's Infrahub account needs; [D-088](#d-088) in one, what the checks
do with a draft; and [D-039](#d-039) in one, for one pin, Prefect's. Details D-085 in how the
head is read, in the times of the checks and the flows and in the two calls the edge asks of
a source beyond the seam's four; and D-088 in how the branch point is decided and when a mark
is refused. The rest of each stands.
Added to by [D-097](#d-097) on 2026-11-12 (phase 9): the edge asks a third call of a source,
the one that takes a request, which Infrahub's source answers by doing nothing.
Detailed by [D-100](#d-100) on 2026-11-13 (phase 9's landing): that call's name, and the
settings' fields that name no source.

#### Context

D-085 and D-088 each end with what plan 5 was to read first on Infrahub 1.11.11 and Prefect
3.9.2, and say the entry is restated if a reading shows the design is not enough. Plan 5 read
them ([verified-facts.md](verified-facts.md), "Infrahub 1.11.11" and "Prefect 3.9.2"), and
built on the readings (plan 0's bends and its reconciled items 12, 16 and 17; rulings P5-1,
P5-9, P5-13, P5-27, P5-28, P5-36, P5-42, P5-43 and P5-58).

- D-085 gives the example's account "the three permissions a thread and a comment take". An
  account holding those three alone read nothing: every kind was refused 403.
- D-085 means the source to wait, under a bound, for an artifact validation still running
  before it reads the head. The reader refuses a `generated_since` later than the time read
  ([D-089](#d-089)), and a validation's completion is likely later than the reader's `head` of
  the branch. And a proposed change that changes no device was read to get no artifact
  validator at all.
- D-088 keeps one line of the prototype's, "the report says when the default branch has moved
  since the branch was cut". Every write to `main` moves its head, a mark, a thread and a
  proposed change among them, so a time alone cannot say the intent there moved.
- D-088 says of a draft that "the check concludes without starting anything". Of the two
  checks only `fylgja-twin` was built so: plan 0's reconciliation has `fylgja-step` plan a
  draft (its item 17), a plan making no twin.

#### Options considered

The account's reads:

- **A view permission for each kind the reader reads.** Not taken: a row for every kind, to
  be kept in step with the mapping.
- **The instance's own view of every kind, on every branch.** Chosen.

Where no artifact validator appears:

- **Wait the whole bound.** Not taken: a branch that changes no device never gets one.
- **Wait a shorter bound for one to appear, then read the head on its artifacts' stamps
  alone, and say so.** Chosen.

Whether `main` moved:

- **Compare times.** Rejected: `main`'s head moves for writes that are no intent.
- **Compare `main`'s blueprint at the cut with its blueprint at its head.** Chosen.

#### Decision

1. **The example's Infrahub account holds four permissions** in one role: the two that a
   thread and its comments take, the one to edit the default branch, on which both are
   written, and a view of every kind on every branch. `make orchestrator-env` brings the role
   to exactly those four, and replaces a token line Infrahub refuses. The reader beneath the
   source still sends no mutation.
2. **A change is the one open proposed change of the branch a trigger names.** None is no
   change; two are refused naming both, never picked between.
3. **The stages** are the branch point, the branch's marks and the head, as D-088 orders
   them. Each stage's pin is the source's own, and carries the proposed change's id beside the
   branch and the time; the head's has no time until its read resolves one. A mark labelled
   `branch-point` or `head` is refused (`stage.label.reserved`), and so is a mark with no
   `as_of` to which Infrahub gave no time of writing, or whose time does not parse
   (`stage.at.unresolved`).
4. **The head is read once the proposed change's artifact validation has completed**, waited
   for up to 240 s, at the later of the reader's `head` and the validation's completion, with
   that completion as `generated_since`. Where no validator has appeared after 120 s, or the
   validation has not completed in its bound, the head is read on its artifacts' stamps alone,
   with no `generated_since`, and the stage carries a finding that says so
   (`stage.validation.absent`, an info, or `stage.validation.unfinished`, a warning).
5. **The branch point is `main` read at the time the branch was cut.** `main`'s head is then
   read as a comparison alone, and `stage.main.moved` is filed where its blueprint there is not
   the cut's.
6. **Only `fylgja-twin` passes over a draft**, starting nothing. `fylgja-step` plans a draft
   as it plans any proposed change. The `twin-rehearse` flow refuses a draft too, before the
   core is asked anything. The edge asks two calls of a source beyond the seam's four,
   `is_draft` and `close` (`EdgeSource`), so a second source for the edge gives both.
7. **The times.** The rehearsal's own limit is 3,600 s ([D-092](#d-092)). The flows'
   `timeout_seconds` are 600 (`stage-plan`) and 3,900 (`twin-rehearse`). Each check's `timeout`
   is 900 and 4,260 s; at 240 s before it the check asks the run's cancel, and it concludes in
   what is left.
8. **The source's rules are catalogued in `orchestrator/rules.md`**, in a section of their
   own, beside the rehearsal's.
9. **Prefect is pinned at 3.9.2**, three days old when it was read, against the two weeks
   D-039 asks of every pin: the maintainer's word, 2026-11-09 ("prefect 3.9.2 is fine").
   [CONTRIBUTING.md](../CONTRIBUTING.md) says so where the libraries are listed.

#### Consequences

- The example's account can read every object of the instance, wider than its reads need. It
  writes threads and comments, and nothing else.
- By the rule's construction, and by no reading, too short a bound on the validation can
  only refuse a stage, as stale or unready on its stamps; it cannot pass one.
- A rehearsal reads `main` again at its head, for the comparison alone.
- In the acceptance runs `fylgja-twin` concluded within 485 s of the proposed change's
  creation. A check that runs for most of its 4,260 s was not read
  ([open questions](#open-questions)).
- The checks first ran on a task worker, and the workers first reached Prefect on the host,
  in the acceptance runs of 2026-11-12, the dry runs first ([D-094](#d-094)).
- [core.md](core.md) and [docs/integrating.md](../docs/integrating.md) say each as built.


<a id="d-096"></a>
### D-096 — The NetBox reader speaks REST through httpx, states the versions it passed on, and is tested against a real NetBox

**Status:** Accepted 2026-11-12 (phase 9). Applies [D-083](#d-083) to the NetBox reader.
[D-034](#d-034) stands and binds its tests. The constitution's line on contract tests names
NetBox beside Infrahub citing this entry (version 1.1.1, wording).
Superseded in part by [D-099](#d-099) on 2026-11-13: the warning is filed where the pair of
versions is not among the pairs passed on; the contract tier provokes each rule of the
reader's, some by an answer altered in flight, and the pure tier holds more than this entry
lists; the development NetBox has a Compose network of its own, off the local driver's lab
pool; NetBox is up beside the twin of the acceptance run; and the reader exports `redact`,
which the example's transport imports.

#### Context

[D-083](#d-083) gave the Infrahub reader plain HTTP, stated versions and a contract tier on a
real instance, because the maintainer's first worry was maintaining the reader across the
source's upgrades. The worry is the same here, and NetBox moves as fast: 4.7.5 was released
two days before this entry and the plugin's 1.2.3 two weeks before. The readings behind
[D-095](#d-095) were made with httpx alone. NetBox on the development host is netbox-docker's
Compose project with one image layer adding the plugin; it idled at about 1.3 GiB in the
archived repository's reading, and its first start is minutes of migrations.

#### Options considered

- **pynetbox.** Not taken, for D-083's reasons: the reader sends a few fixed requests, and a
  client library's pins would reach whatever platform the reader is installed into.
- **httpx, which the core's client and the Infrahub reader already use.** Chosen.
- **Recorded answers for the pure tier.** Rejected by [D-034](#d-034).

#### Decision

- **The reader depends on `fylgja-core` and httpx**, and on no client library of NetBox's.
- **All of its contact with NetBox is in one transport module.** Nothing else in the reader
  builds a request.
- **The versions it passed on are stated** in its README, NetBox's and the branching
  plugin's. At connect it reads both, and files a warning when either is not among them.
- **Its contract tier runs against a real NetBox**, seeded, at versions one make target
  takes: every read rule of [D-095](#d-095), and the same state read twice giving one id. Its
  pure tier holds the mapping, the ordering, the counting and the bracket over rows built in
  the tests, and the import boundary.
- **An upgrade is a procedure**, D-083's: start the new versions, seed them, run the contract
  tier, read again the recorded facts the code leans on, and extend the list.
- **NetBox on the development host is netbox-docker at a stated version**, with an image that
  adds the plugin at a stated version, under `local/`, behind make targets. What the tree
  holds for it is under `netbox/`, as `infrahub/` holds Infrahub's.
- **It is seeded by a script over REST**, with the fixture network the Infrahub seed holds, a
  configuration template that renders it, and the probes' configuration context.

#### Consequences

- The reader holds its own paging and its own error sentences.
- The contract tier needs a running NetBox. Its memory is plan 1's reading; it and Infrahub
  are both stopped while a live tier runs on the development host.
- The example's change source meets NetBox through a transport of its own
  ([D-097](#d-097)), as its Infrahub source does; the reader's transport is the reader's
  alone.


<a id="d-097"></a>
### D-097 — The example's NetBox change source: marks taken as the branch is built, a tag that asks for the rehearsal, and the report a journal entry

**Status:** Accepted 2026-11-12 (phase 9). Adds a second change source behind
[D-085](#d-085)'s seam. Adds to [D-087](#d-087) where the report is filed, and to
[D-088](#d-088) what a mark is in a source that cannot be read at an earlier time. Adds to
[D-092](#d-092), which says the seam and the report as built, the two sentences a source
gives and the report's sentence on when its stages were read; and to [D-093](#d-093), which
says the edge asks two calls of a source beyond the seam's, a third. The
maintainer said on 2026-11-12 that the steps are seeded by a script, that a webhook is enough
to start the orchestration, and that a report on the branch is enough, with no gate on the
merge.
Superseded in part by [D-100](#d-100) on 2026-11-13: the source reads the tag and takes it off,
by hand too; a branch that keeps its tag and gains no report may have started and been refused
before the tag was taken; a mark is held by its blueprint's id, through any core given that
blueprint; a branch behind `main` is warned of by a count of `main`'s changelog, and nothing is
refused; both lesser accounts read the webhook's credential in `main`'s changelog; the
report's entry has an empty line put before each list; the seam gains two members; and the
source's transport also counts `main`'s changelog. Detailed by [D-101](#d-101): the acceptance
as made.

#### Context

[D-085](#d-085) kept its seam from ruling NetBox out, on NetBox's documentation alone. On
2026-11-12 NetBox 4.7.5 with netbox-branching 1.2.3 was read
([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3"). On the
community edition a change is a branch. It has no object of review, and the layer that adds
one is the paid editions'. Nothing read of it reads a branch as it stood earlier; the archived
repository read a merged branch refused on 4.7.4, which was not read again. A branch takes tags and journal entries; a journal entry on it lives on
`main`, is listed in the order written, showed on the branch's page, and was kept whole at a
megabyte. An event rule on the branch, conditioned on a tag, sent its webhook when the tag
was set and for an edit while it stayed set, and sent none for a journal entry, a sync or
the tag's removal. A webhook sends a body NetBox renders from a template, with headers it is
given. One answered 503 was not sent again in the 45 s watched. The plugin's merge validators could refuse a
merge, by code installed in NetBox.

The maintainer's picture, the same day: "we can build the branch in steps, generating a
series of blueprints as we go"; "use a script to seed the change so that we don't need to
worry about a user interface for this. Emphasis is on the demo; we can develop a change
authoring process once the concept is proven."

The core keeps a blueprint by its id and returns it
([Constitution IX](constitution.md#ix-state-lives-behind-one-store-no-database)), and Prefect
starts a deployment for any caller of `create_flow_run`
([verified-facts.md](verified-facts.md), "Prefect 3.9.2").

#### Options considered

Where a step's blueprint is kept until the rehearsal:

- **A directory of the example's**, as its record of a twin is. Not taken: the command that
  takes a mark and the runner that rehearses would have to share a disk, and the marks would
  be invisible in NetBox.
- **The blueprint's text in a journal entry.** Not taken: every device's configuration, in
  the branch's journal.
- **The blueprint in the core, and a journal entry naming its id.** Chosen: the core already
  keeps blueprints by id, and the mark is where the change is.

What makes a mark:

- **Every edit on the branch**, by a webhook. Not taken: an edit is not a step, and a change
  of ten edits would be ten stages.
- **A command, run when a step is complete.** Chosen. The seed's script runs it; what an
  engineer does in its place is the later phase's.

What asks for the rehearsal:

- **A lifecycle event of the branch.** Not taken: provisioning comes before any edit, a sync
  is not a request, and a merge is too late.
- **A custom script or a custom link in NetBox.** Not taken: code or a page inside NetBox,
  which the maintainer set aside for now.
- **A tag on the branch, and an event rule conditioned on it.** Chosen.

What receives the webhook:

- **A small HTTP service of the example's.** Not taken, as [D-085](#d-085) did not take one.
- **Prefect's own API**, the webhook's body being the request `create_flow_run` takes.
  Chosen.

What holds the verdict:

- **A merge validator.** Not taken: "report is good enough" (the maintainer, 2026-11-12).
- **A tag or a custom field on the branch beside the report.** Not taken: a write to the
  branch is an event of the branch's, and one more thing to keep true.
- **A journal entry, its kind the verdict.** Chosen.

#### Decision

- **A change is a branch**, named by its name. One that is not `ready` is refused.
- **Its stages, in order**: `main` as it stands when the rehearsal reads it; each mark of the
  branch in the order written; and the branch as it stands then.
- **A mark is taken by the example's command `stage mark`**, given a branch and a label. It
  reads the branch through the reader ([D-095](#d-095)), gives the blueprint to the core, and
  writes a journal entry on the branch that names the label, the blueprint's id, the scope
  read under and when, in a form a person reads and the source parses. A read that is refused
  writes no mark. A label is unique within its branch.
- **A mark's blueprint is read back from the core by its id, and the rest of it from its
  entry.** The core keeps the envelope of whoever first gave it that intent, so nothing of a
  mark is taken from the envelope. One the core does not hold, or one whose entry names
  another scope than the rehearsal's, refuses that stage with a finding.
- **A mark belongs to the core it was given to.** A change is rehearsed through the core it
  was marked through.
- **The example keeps no store for this.** The marks are NetBox's and the blueprints the
  core's.
- **`main` and the head are read at the rehearsal**, and read again, a fixed small number of
  times, where the reader refuses one for having moved ([D-095](#d-095)).
- **A tag on the branch asks for the rehearsal.** An event rule on the branch for
  `object_updated`, conditioned on the tag, sends a webhook that posts to Prefect's
  `create_flow_run` for `twin-rehearse`, its body the branch's name as the flow's one
  parameter. The edge takes the tag off before it calls the library, by a call it alone asks
  of a source, as it alone asks whether a change is a draft; Infrahub's source answers it by
  doing nothing. One setting of the tag is so one rehearsal; set again, it asks again. The
  tag is held by NetBox's rule and nothing else: `twin rehearse` run by hand rehearses a
  branch tagged or not, and no NetBox change is a draft.
- **The report is one journal entry on the branch**, the summary and the detail together,
  its kind `success` for the status `passed`, `danger` for `failed`, and `warning` for
  `not_rehearsed` and `stopped`. The source sets no bound on its size. It
  gates nothing.
- **The edge takes its source from a setting**, `FYLGJA_ORCHESTRATOR_SOURCE`, `infrahub` or
  `netbox`, `infrahub` where it is unset. NetBox is reached at `FYLGJA_NETBOX_ADDRESS` with
  `FYLGJA_NETBOX_TOKEN`, verified against `FYLGJA_NETBOX_CA` where one is named
  ([D-042](#d-042)), and the chosen source's variables alone are required. A runner serves
  one source, and a Prefect server one source's runner, since both sources' flows are served
  under the same two names. The two flows keep their one parameter. `stage mark` under
  `infrahub` is refused.
- **NetBox starts `twin-rehearse` alone.** `stage-plan` stays a deployment, which Infrahub's
  check starts, and a command.
- **The seam gains the source's own words, and the report's read time is made true of a
  mark.** The library's sentences that tell a reader to run the checks again, and to check
  the scope the checks run with, take those words from the source by a member the seam
  gains, and the library names neither Infrahub's checks nor NetBox's tag. The report's
  sentence that the stages were read at one time, and that later edits are not rehearsed, is
  restated so that it is true where a mark was read earlier, the mark's time coming from
  its stage. The rehearsal's steps, its statuses and its two documents do not change.
- **The source has a transport of its own** for its few requests: the branch, its journal
  entries, its tags. The reader beneath it still writes nothing.
- **The tag, the event rule and the webhook are made by a make target** on the development
  NetBox, the webhook's address and its credential for Prefect taken from `local/.env`.

#### Consequences

- The webhook holds a credential for Prefect in its headers, which NetBox answered to the
  superuser that read the webhook back; what a lesser account reads is plan 3's reading. It
  is Prefect's one basic-auth string, as phase 8 set it, which opens all of that Prefect's
  API. An integrator who will not keep it in NetBox puts a receiver of their own platform's
  there.
- A request can be lost. NetBox did not send again a webhook answered 503, and Prefect
  answered 503 to creates sent at once in phase 8's reading. A branch that keeps its tag and gains no report was
  never started; one that lost its tag and gained no report was started and stopped, and
  Prefect says why. Setting the tag again asks again. The example sends nothing a second
  time.
- An edit to the branch object while it still carries the tag sends the webhook again. The
  edge takes the tag off first, so the time this can happen in is short; it is not closed,
  and a second rehearsal so started deletes the first's twin ([D-086](#d-086)).
- Taking a mark needs the core running, and the seed's script with it. A change is seeded
  once for each core it is rehearsed through.
- What a mark's read found beside its blueprint, an omission among it, is said when the mark
  is taken and is not carried to the rehearsal's report.
- The first stage is `main` as it stands, not as it stood when the branch was made or last
  synchronised. Where `main` has moved since, the first step holds `main`'s later changes
  undone. Plan 3 reads how the API tells such a branch, and the report says so, or the
  rehearsal is refused, as the reading allows.
- Whoever may write a journal entry on a branch may write a mark. The example trusts the
  marks it reads.
- A mark names a blueprint the core holds. A core whose store is emptied loses every mark's
  blueprint, and the stage is refused by name.
- What an engineer does in NetBox to mark a step, in place of the seed's script, is a later
  phase's question.


<a id="d-099"></a>
### D-099 — The NetBox reader's versions and tests and the development NetBox as built: NetBox 4.7.5 pinned two days old, a Compose network off the lab pool, and a contract tier with a marker of its own

**Status:** Accepted 2026-11-13 (phase 9's landing). Supersedes [D-039](#d-039) in one part,
for one pin, NetBox's; and [D-096](#d-096) in five: what the version warning compares, what
each tier holds, where the development NetBox's network lies, when NetBox is stopped, and whose
the reader's `redact` is. Details D-096 in the seed's targets, the accounts and the wait for a
branch. The rest of each stands.

#### Context

D-039 asks that every pin be a release at least two weeks old. D-096's context says NetBox
4.7.5 "was released two days before this entry", and every fact the phase leans on was read on
it ([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3"). The
phase's plans 1, 2 and 4 built and read the rest (plan 0's bends; plan 1's rulings R3 and R10,
plan 2's R12 and R13, and plan 4's R2, R3, R8, R15 and R16, of the phase's ledgers).

- **Docker had given the Compose project the local driver's whole lab pool.** The project's
  default network answered the one subnet the pool is ([D-043](#d-043)), and while NetBox was up
  the driver's own choice of a lab's subnet answered none, no /24 of the pool being free ("The
  project's network and the local driver's lab pool"). The acceptance run on the local driver
  needs NetBox and a twin at once, which D-096's "both stopped while a live tier runs" did not
  foresee.
- **A first start on new volumes took about twelve and a half minutes**, most of it NetBox's
  migrations, Compose's first `up` giving up on an unhealthy container meanwhile; idle, the
  stack held 1.36 GiB, a derivation, the sum of its containers' memory read once ("A first start
  on new volumes").
- **A `DELETE` of a branch still provisioning is 500, and the branch stays**; it was read
  `provisioning` up to 1.9 s after one and `ready` from 26.7 s to 28.2 s after, the reads
  between not kept ("A branch deleted before it is `ready`").
- **The example's transport needed the reader's rule for hiding a token** in NetBox's words,
  and imported it from the reader's transport by a name the reader did not export.

#### Options considered

NetBox's pin:

- **An older release, two weeks out.** Not taken: every fact would be read again on it.
- **4.7.5, on the maintainer's word.** Chosen: "stay with netbox 4.7.5" (the maintainer,
  2026-11-13).

NetBox beside a twin on the local driver:

- **NetBox stopped whenever a twin runs there**, as D-096's consequence reads. Rejected: the
  acceptance run needs both.
- **The local driver's pool made a setting.** Not taken: a change of the core's, which the
  phase leaves as built.
- **A network of the project's own, named in the Compose override, in a documentation range.**
  Chosen.

The reader's `redact` and the example:

- **The import left on a name the reader does not export.** Rejected: a change inside the
  reader's transport would break the example.
- **A `redact` of the example's own.** Not built.
- **The name exported by the reader.** Chosen.

#### Decision

1. **NetBox is pinned at 4.7.5**, two days old when D-096 chose it, against the two weeks D-039
   asks of every pin, on the maintainer's word of 2026-11-13, as Prefect's pin was
   ([D-093](#d-093)). netbox-docker is at 5.1.1 and the branching plugin at 1.2.3.
   [CONTRIBUTING.md](../CONTRIBUTING.md) says so where the pins are listed.
2. **The versions the reader passed on are pairs**, NetBox's version and the plugin's
   (`SUPPORTED`). At connect it reads both and files the warning `netbox.version.unverified`
   where the pair is not among them, on every result of that connection. A NetBox that names no
   plugin is warned of too, and a branch asked of it refused.
3. **What each tier holds.** The contract tier provokes each rule of the reader's `rules.md` on
   the development NetBox, under the headers of branches it makes and deletes. What cannot be
   written into NetBox is provoked by an answer altered on its way to the reader: a NetBox
   naming no plugin, a list short of its `count`, a render answered 502 or in another content
   type. An edit, a journal entry, a branch's delete and its sync are made as a read's first
   render passes. The same state is read twice to one id, on `main` and on a branch. The pure
   tier holds, beside the mapping, the ordering, the counting, the bracket and the import
   boundary, the transport over a fake of HTTP, the renders, the probes, the command and the
   documents; and alone, the reader document's problems, a cable with no B side, and the forms
   of a rule the contract tier does not provoke, which the reader's README lists.
4. **The NetBox contract tier has a marker and a make target of its own**, `contract_netbox`
   and `make contract-netbox`: `netbox/`'s tests, the reader's and the example's NetBox change
   source's, in that order. `make contract` stays Infrahub's, so that either source's tier runs
   with the other source stopped.
5. **The development NetBox's network is a documentation range of its own**, named in
   `netbox/dev/compose.override.yml`, off the local driver's lab pool. `make netbox-up`
   recreates a project network that stands with another subnet: the project's containers and
   network are removed, the volumes kept, and the start makes the network again. A network the
   script cannot inspect is said in one line and the start goes on; a start that fails after a
   recreate names the range.
6. **NetBox is stopped for the live tier, the cluster tier and the conformance suite, and up
   beside the twin of the acceptance run through its tag**, which needs both. Infrahub is
   stopped for that run ([CONTRIBUTING.md](../CONTRIBUTING.md#through-netboxs-tag), "Alone").
7. **The seed is two targets and the trigger a third.** `make netbox-seed` writes the fixture on
   `main` and the two accounts, and needs nothing of Fylgja's but the superuser's token. `make
   netbox-change` builds the change's branch in steps and marks each, and needs the reader, the
   example and a running core. `make netbox-hook` installs the trigger ([D-100](#d-100)).
8. **Two accounts that are no superuser**, `fylgja-reader` and `fylgja-orchestrator`, each at
   the least grants read to serve its requests. `make netbox-seed` refuses an account that holds
   a group or a permission outside those grants, and removes nothing.
9. **The seed's transport waits 120 s for a branch to read `ready`**, about 4.3 times the
   slowest `ready` read, 28.2 s after a refused `DELETE`, a derivation. A tier's sweep
   waits, under that bound, for a branch of its prefix that is `new` or `provisioning`
   before it deletes it.
10. **The reader exports `redact`**, and the example's NetBox transport imports it. Every
    request of the reader's is still built in the reader's one transport module, and the
    example's in its own.

#### Consequences

- NetBox's pin is held to no waiting period. What stands in its place is that every behaviour
  the code leans on was read on 4.7.5 itself, and D-096's procedure for the next release. Had
  the word been refused, the facts would have been read again on an older release.
- What `make netbox-up` meets on a host where another network already holds the override's
  range was not read. The script's failure after a recreate, which names the range, and its
  line for a network it cannot inspect are held by pure tests alone; neither was read on a
  real Docker. Nor was what Compose's own `up` does to a standing network whose subnet the
  override changes.
- The whole contract tier took 986 s to 1,087 s in three runs on 2026-11-13, of 14, 45 and 12
  tests.
- An account's grant is by type: the example's `change` on branches reaches any member of a
  branch ([D-100](#d-100)).
- [core.md](core.md) and [CONTRIBUTING.md](../CONTRIBUTING.md) say the development NetBox as
  built.


<a id="d-100"></a>
### D-100 — The example's NetBox change source as built: a branch refused before its tag is taken, a mark held by its blueprint's id, a warning for a branch behind `main`, and Prefect's credential readable in NetBox's changelog

**Status:** Accepted 2026-11-13 (phase 9's landing). Supersedes [D-097](#d-097) in eight parts:
what holds the tag, what a branch's tag and journal say of a rehearsal, whose a mark is, what is
said of a branch behind `main`, what a lesser account reads of the webhook's credential, what
the report's entry holds, how many members the seam gains, and what the source's transport
asks. Details [D-085](#d-085), [D-087](#d-087), [D-092](#d-092) and [D-093](#d-093) in the
names the seam, the edge and its settings gained and in the report's sentence as built. The
rest of each stands.

#### Context

D-097 left two of its consequences to plan 3's readings, "what a lesser account reads" of the
webhook's headers and "how the API tells" a branch behind `main`, and the names of what the
seam gains to the builder. Phase 9's plan 3 read NetBox 4.7.5 with netbox-branching 1.2.3 and
Prefect 3.9.2 and built the source and the edge on the readings, and plan 4's acceptance runs
read more ([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching 1.2.3"
and "Prefect 3.9.2"; plan 0's bends, its rulings made before execution and its section on the
webhook's auth; plan 3's rulings R1 to R9). The readings differed from what D-097 supposes, or
said what it left open, in these places.

- **Nothing of a branch says it is behind `main`**: no member of it and no route of the
  plugin's API ("A branch behind `main`"). `main`'s changelog takes `?time_after=`, counting
  inclusively, and leaves a kind out by its object type's id.
- **Both lesser accounts read the webhook's credential.** Each is refused the webhook by its
  list and by its id. But both hold `view` on NetBox's changelog, which the reader's bracket
  and the source's count need, and the webhook's rows of `main`'s changelog hold its
  `additional_headers` and its `secret` unmasked, in `prechange_data` and `postchange_data`.
  The rows outlive the webhook: those of webhooks deleted the day before still held the value
  ("A webhook's rows of `main`'s changelog hold its headers, to either lesser account").
- **NetBox renders a Markdown list only where an empty line stands before it** ("A report as a
  journal entry"); the report's lists showed as one paragraph otherwise.
- **The flow's own untagging started nothing**, in the 60 s watched ("The tag starting
  Prefect's deployment"), so the fallback the maintainer approved before execution, a flow that
  ends at once for a branch with no tag, was not needed.
- **The plugin takes a branch's name holding `"` or `\`**, and the webhook's body template
  honours `tojson` ("A branch's name in a webhook's body").
- **A sending refused its connection failed within a second and was not sent again**, no run
  made 133 s after Prefect's next start ("A request lost and asked again"), beside the 503 of
  D-097's context.
- **A new Prefect home changes the deployment's id**; a server started again under the same
  home kept it.

#### Options considered

Prefect's credential in NetBox's changelog, which the maintainer handed to the controller on
2026-11-13 ("Settle decision"):

- **A constraint on the two accounts' changelog grant**, hiding the webhook's rows. Not taken:
  whether NetBox honours such a constraint was not read, it would narrow the changelog the
  reader's bracket counts, and it would cover the seed's two accounts alone.
- **A receiver of the example's between NetBox and Prefect**, so that Prefect's credential
  never enters NetBox. Not taken: D-097 took no service of the example's, as D-085 took none,
  and the maintainer's ruling of 2026-11-12 kept one a stop; and whatever such a receiver is
  sent, a header or a `secret`, the same rows hold.
- **Another trigger than a webhook that carries the credential.** Not taken: it supersedes
  D-097's trigger, and is a design of its own.
- **Accepted as the example's known limit, said in the documents and pinned by a test.**
  Chosen.

A branch behind `main`:

- **`main`'s blueprint when the branch last took it, compared with `main`'s as it stands**, as
  the Infrahub source compares ([D-093](#d-093)). Not possible: NetBox reads no earlier time.
- **The rehearsal refused.** Not taken: what can be counted is rows of `main`'s changelog of
  every kind but four, a site's or a user's among them, which cannot say that anything a read
  reads moved.
- **A warning with the count.** Chosen.

A label marked a second time:

- **`stage mark` takes it, the newer entry standing.** Not taken: NetBox reads no earlier time,
  so a past step cannot be read again whatever the command allowed, and a label would name two
  states.
- **A label is taken once, and each remedy says what can truly be done.** Chosen.

The report's lists in NetBox:

- **The library's text as it is.** Not taken: its lists showed as one paragraph.
- **The library's Markdown changed.** Not taken: Infrahub's report would change with it.
- **An empty line put before each list by the NetBox source, where it files the entry.**
  Chosen.

#### Decision

1. **A change is the branch whose name is exactly the reference a trigger names**, and its id
   is the branch's `schema_id`: a branch read again by its name is held to that id, so one made
   anew under the name is another change. A branch that is not `ready` is refused before its
   tag is taken: the flow fails, the tag stays, and nothing is posted.
2. **The source takes the tag off**, by its call `claim`: one `PATCH` of the branch's other
   tags, and nothing sent where the tag is not on it. `twin rehearse` run by hand goes through
   the same call, rehearses a branch tagged or not, and takes a tag off too. The fallback for a
   flow that finds no tag is not built.
3. **What a branch's tag and journal say.** A branch that keeps its tag and gains no report was
   not rehearsed: its request was lost, or its run started and was refused before the tag was
   taken off, by its settings or its reader document, or by the branch, none of the name, one
   made anew under it, one not `ready`, or its read or the tag's removal refused or unanswered;
   Prefect shows such a run failed. One that lost its tag and gained no report was started: by a
   flow, whose run in Prefect says what came of it, a rehearsal that ended and whose post NetBox
   refused among them; or by hand, of which Prefect knows nothing.
4. **A mark.** `stage mark --branch B --label L` reads the branch through the reader, gives the
   blueprint to the core and only then writes the entry, of kind `info`: a first line `Fylgja
   stage: <label>`, then the blueprint's id, the scope and the time read, each on a line the
   source parses. A label is 1 to 40 lowercase letters, digits and hyphens, beginning and ending
   with a letter or a digit, and neither `main` nor `head`; it is taken once in its branch. An
   entry that begins with the mark's prefix is a mark or a malformed one, never passed over. A
   mark refuses its stage where it is malformed (`mark.malformed`), where two entries share its
   label (`mark.duplicate`), where it was read under another scope than the rehearsal's
   (`mark.scope`), and where the core does not hold its blueprint, or answers another document
   under its id (`mark.unheld`). The command exits 0 for a mark written, 1 for a read refused
   and 2 for a fault of its own, the source being `infrahub` among them.
5. **A mark is held by its blueprint's id.** Its blueprint is read from the core the rehearsal
   runs through, by that id, and a core keeps a blueprint by its id whoever gave it
   ([D-006](#d-006)): so a mark is read through the core it was given to, and equally through
   any core given a blueprint of that id. A change is seeded once for each core it is rehearsed
   through, on a branch of its own, since `make netbox-change` deletes a branch of its name
   with its marks and its report.
6. **What a mark's remedies are.** NetBox reads no branch as it stood earlier, and the
   example's account may not delete a journal entry. So a mark the rehearsal cannot use is
   deleted in NetBox by a person who may, and its step marked again only while the branch still
   stands at it; otherwise the change is seeded again. A mark read under another scope is
   rehearsed under its own, and one whose blueprint another core holds through that core.
7. **`main` and the head are read through the reader as they stand**, and read again where the
   reader refuses one with `read.moved` and gives no blueprint, three reads in all, none waited
   between.
8. **A branch behind `main` is warned of, and nothing is refused**: `stage.main.gained`, on the
   first stage, with the count of the rows `main`'s changelog holds from the branch's
   `last_sync`, or its `created`, of every kind but a journal entry's, a branch's own, a
   webhook's and an event rule's. The last two are the trigger's own, which `make netbox-hook`
   writes on `main`.
9. **The trigger.** The tag `fylgja-rehearse`, limited to branches; an event rule on the branch
   for `object_updated`, conditioned on the tag's slug; and a webhook to Prefect's
   `create_flow_run`, which names the deployment by its id, asked of Prefect by its name when
   the trigger is installed. Its body writes the branch's name as a JSON string by the
   template's `tojson`. Its credential is `FYLGJA_ORCHESTRATOR_AUTH`'s, from `local/.env`; its
   address is the name NetBox's worker reaches the host by and Prefect's port, or what the
   script is given. `make netbox-hook` is idempotent by name and writes only what differs, and
   is run again after a new Prefect home.
10. **The report is one journal entry**, its kind the status's, the summary and the detail with
    an empty line put before each list. It is so not the library's text byte for byte, and
    NetBox keeps it with the whitespace at its end stripped. The source sets no bound on it.
11. **The seam gains two sentences, and the edge's source one call.** `ChangeSource.again` says
    how one asks for the rehearsal again, used whole and as the end of a sentence of the
    library's, and `ChangeSource.scope_remedy` where the scope is checked. `EdgeSource.claim`
    takes the request, and Infrahub's does nothing. A stage read before the rehearsal says its
    time in its `where`.
12. **The report's sentence on when its stages were read is one sentence, true of either
    source**: "The rehearsal read its stages at …; one taken earlier is as it was then, at the
    time its line in the detail gives; later edits are not rehearsed." It is the one place
    phase 8's path through Infrahub reads otherwise than it did, and the lines a summary
    always keeps grew with it, from at most 987 bytes to at most 1,079 of Infrahub's 4,092.
    The phase's anti-goal, that path behaving otherwise, is held to behaviour.
13. **The edge.** Its settings name the source and hold that source's address, token and CA in
    three fields that name no source, so the source not chosen is never read and its token never
    held. Its `opened` answers the source the setting names with the core's client.
14. **The source's own requests** are the branch, its journal entries and its tags, and beside
    them the count of `main`'s changelog and the object types whose ids that count leaves out.
15. **The example's wheel requires each reader**, and each change source loads its own reader
    alone, held by a scan of the imports and by the wheel check.
16. **The runner's environment is `scripts/edge_dev.py`'s alone to make**, for either source,
    and a command of the example's by hand runs through it. `local/.env` holds Infrahub's
    values and NetBox's at once: NetBox's reader document, scope and token under names of
    their own, handed to the runner under the names the edge reads.
17. **Prefect's credential in NetBox's changelog is the example's known limit.** An account
    that may view NetBox's changelog, as the reader's and the example's must, reads the
    webhook's headers there, and so Prefect's one basic-auth string, which opens all of that
    Prefect's API. No grant is constrained and the trigger is not changed. The documents say
    the limit, and a contract test holds the reading
    (`test_a_lesser_account_reads_the_webhooks_headers_in_the_changelog`), so that a NetBox that
    masks the header is noticed. Replacing the value removes no row of the changelog: the old
    value stays readable there and only stops opening Prefect. A deployment that shares its
    NetBox puts a receiver of its own before Prefect, or gives grants that hide the webhook's
    rows, which was not read.

#### Consequences

- A holder of either lesser NetBox token on a shared instance can drive the example's Prefect,
  and Infrahub's task workers hold the same string. The value in the development NetBox's
  changelog stays readable there until that changelog's own pruning, which was not read, or a
  purge; replacing it, or purging the instance, is the maintainer's to ask for.
- The example's account holds `change` on branches for the tag alone, and a grant is by type.
  In the plugin's source, read and not run, a branch's `recover` asks only `change`; the
  account's `sync` was refused. NetBox offers no narrower grant for a branch's tags.
- That a mark is read through another core given the same intent is how the source is built,
  and was not read on a running core. In the acceptance runs the two branches' marks named the
  same two ids; `mark.unheld` was read through the cluster's core before that core was given
  them, and the local driver's branch was not planned there after
  ([open questions](#open-questions)). The finding's sentence still says a mark belongs to the
  core it was given to.
- An edit of the branch object while it carries the tag asks again. As read, the tag's removal
  came 6.9 s to 15.9 s after its setting, each a derivation from two rows' times.
- `stage.main.gained` counts rows of kinds no read reads, a site's among them, so it can warn
  where nothing a read reads moved; and the source's count and the reader's bracket differ on a
  webhook's row, which the bracket still refuses a read for.
- A run goes to whichever source's runner serves `twin-rehearse/main`, each source's flows
  being served under the same names. A tag set while Infrahub's runner serves was not read.
- A rehearsal from a tag on a real driver was read to end `passed` alone, so an entry of kind
  `danger` or `warning` filed by one was not read.
- How an engineer marks a step in NetBox, in place of the seed's script, is still a later
  phase's ([open questions](#open-questions)).
- [core.md](core.md), [docs/integrating.md](../docs/integrating.md) and `orchestrator/rules.md`
  say each as built.


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
Added to by [D-075](#d-075) on 2026-11-08: the read threads a node is unread for want of are a twin's
own, never another twin's.

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
Added to by [D-075](#d-075) on 2026-11-08: the sixteen read threads are per twin.

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
superseded in part by [D-056](#d-056) on 2026-11-04: a stray runs to completion;
superseded in part by [D-070](#d-070) on 2026-11-06: item 5, an unchanged step, which pushes
what holds nothing and leaves `Ready` False for `twin.node.missing` as it is.
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

<a id="d-075"></a>
### D-075 — Contention becomes waiting, never a verdict: read threads a twin's own, the client's limits bound, eight workers

**Status:** Accepted 2026-11-08 (phase 7). Adds to [D-051](#d-051) and [D-052](#d-052) (the
read threads) and to [D-023](#d-023) (the pool's default). Superseded in part by
[D-078](#d-078) on 2026-11-09: the connections were read in plan 4, for three twins on the
local run; nothing is bound, and no wait or budget was widened.

#### Context

Verify's gNMI reads run on daemon threads bounded by one process-wide semaphore of sixteen
(phase 5's plan 5; [verified-facts.md](verified-facts.md), "An abandoned read keeps its
thread"). A read that finds no thread free within its 15 s budget is `verify.node.unread`,
and one unread node makes the verdict `failed` ([D-051](#d-051)). Five twins verifying
together, three nodes each, take fifteen threads; twins of tens of nodes would exceed
sixteen, and a step's wait verifies every `verify_poll_s`. The push and the readiness wait
each make a node HTTP client of their own per call (`push.py`, `readiness.py`), so no shared
limit binds them. The worker pool's default is four
(`FYLGJA_WORKERS`), and an apply holds its worker for the deploy's budget. The step's wait
(180 s) and the deploys' budgets were measured with one twin on the runtime. The maintainer
named the phase's one anti-goal: a verdict that fails from contention rather than intent.

#### Options considered

The read threads:

- **One pool, raised.** Rejected: any shared number lets a twin of tens of nodes starve
  another.
- **Wait past the budget until a thread frees.** Rejected: the maintainer's call is that an
  unread node stays unread; a verify that waits hides the wait inside the step's wait.
- **A pool per twin**, sixteen each, made on first use and dropped when idle, the claim of
  one running read per address staying global. Chosen.

Unread under load:

- **Mark such a node `unread` with a reason of its own, and the verdict `ok`.** Rejected by
  [D-051](#d-051): a script would take it for a pass.
- **Leave it `verify.node.unread`, the verdict `failed`, the orchestrator asking again.**
  Chosen, by the maintainer.

#### Decision

- Each twin's reads have a bounded pool of their own, of the same sixteen threads; a node is
  reported unread for want of a thread only when its own twin's are busy. The per-address
  claim stays global.
- An unread node stays `verify.node.unread` and the verdict `failed`, as D-051 has it; the
  core does not wait past the read's budget.
- What five twins pushing together do to the host's connections, each push a client of its
  own, is read in phase 7's plan 3 and recorded; nothing is bound unless the reading shows a
  need.
- `FYLGJA_WORKERS` defaults to eight: five twins created together each hold a worker through
  an apply, with room for steps beside.
- The step's wait and the deploys' budgets are measured on the many-twins run and widened
  where it shows them short, each a fact; none is shortened.

#### Consequences

- Up to sixteen read threads a twin at once, each ending when pygnmi returns; the memory is
  small, and the threads of an idle twin are gone.
- The verdict vocabulary does not change, and findings 1 says what `failed` means for verify.
- The settings' table and `.env.example` show the new default.


<a id="d-078"></a>
### D-078 — Contention as read on the many-twins runs: no bound on the node clients, and no wait widened

**Status:** Accepted 2026-11-09 (phase 7's landing). Details [D-075](#d-075): where the host's
connections were read and what that reading covers, and the waits and budgets as measured.
Supersedes it in one part: the connections were read in phase 7's plan 4, not its plan 3.

#### Context

D-075 left two things to readings. What twins pushing together do to the host's connections
was to be read in plan 3 and bound only if the reading showed a need; the step's wait and the
deploys' budgets were to be measured on the many-twins run and widened where short.

Plan 3's live test creates three labs through the driver alone, and the driver never pushes:
the push and the readiness wait are the loop's. Its connection count was the host's own
traffic ([verified-facts.md](verified-facts.md), "Three labs at once through the driver"). The
many-twins scenario creates through the core, so its local run is where the core's node
clients and its gNMI reads share a host with the reading. A scenario may start no process, by
the suite's own rule that it reads the API, the CLI, the nodes and the harness alone, so it
cannot run `ss`. On the cluster the core is a pod, and the suite's host sees none of its
connections to the nodes.

#### Options considered

Where the connections are read:

- **Plan 3's live test, as D-075 has it.** Rejected: it pushes nothing.
- **The many-twins scenario's local run**, from the kernel's tables. Chosen.

The five-twin reading on the cluster:

- **A route or a metric in the core that counts its node connections.** Not taken: a surface
  built for one reading, before any reading has shown a need for a bound.
- **Record that it was not read.** Chosen.

The bound:

- **A shared limit on the node HTTP clients now.** Rejected: the reading shows no need, and a
  shared number is what D-075 moved the read threads away from.
- **None, the reading recorded with what it does not cover.** Chosen.

#### Decision

- **The connections were read on the local run for three twins**, every 2 s, as the host's
  established TCP connections to the push and gNMI ports (443, 57400, 6030), from
  `/proc/net/tcp` and `/proc/net/tcp6`, whose count equalled `ss`'s beside it. Over three runs
  the count was at most 7 during the creates and during the steps and verifies, against 1–5
  at the quiet samples, and rose at most 4 above a phase's first sample
  ([verified-facts.md](verified-facts.md), "Three twins at once through the core"). The count
  holds the host's own connections to port 443 and misses one opened and closed between
  samples.
- **Nothing is bound.** Five twins' connections from the core to their nodes on the cluster
  were not read.
- **No wait and no budget was widened, and none shortened.** Every step's wait settled at its
  first verify, after 0.26–0.64 s of its budget locally and 0.31–0.80 s of 180 s on the
  cluster. Every apply ended within its deploy's budget: on the cluster 108.8–135.6 s of 240 s
  for an SR Linux twin and 151.9–177.1 s of 360 s for a mixed one; locally within the same
  budgets with the wait for the deploy lock counted in.
- **No node was unread and no wait expired** on any run of the scenario: three twins locally
  and five on the cluster, of three nodes each.
- **A twin's pool is dropped when its last read returns.** Its count holds every read holding
  or waiting for a thread, an abandoned read's among them, so a pool whose threads still run
  is kept until they end.

#### Consequences

- The anti-goal, a verdict failing from contention, held for the counts the phase names. Twins
  of tens of nodes verifying and pushing together are not read; a bound, where a later reading
  shows the need, is a new entry ([open questions](#open-questions)).
- The scenario's connection count is a handful read every 2 s, not an exact figure.


## Process and repository

<a id="d-033"></a>
### D-033 — A lighter process: design document, decision entry, pull request

**Status:** Accepted at the baseline (2026-10-31); added to by [D-080](#d-080) on 2026-11-09:
how the flow runs for a phase.

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

<a id="d-066"></a>
### D-066 — The formats ship inside the package, built from `formats/`

**Status:** Accepted 2026-11-05.
Added to by [D-084](#d-084) on 2026-11-09 (phase 8): each distribution is checked
from its wheel.

#### Context

`schemas.formats_dir()` finds `formats/` by walking up from the module to the repository's
root, so the server and the client validate nothing once installed outside the tree. Phase 6
installs the server into an image. `formats/` at the root is where a format is changed and
where every document links.

#### Options considered

- **Move `formats/` under the package.** Rejected: the tree's most-read directory would sit
  four levels down, and every link to it would move.
- **A second copy committed in the package, checked against the first.** Rejected: two
  copies of a contract.
- **Fetch each schema by its `$id`.** Rejected: a network read at start, from a URL that is
  an identifier ([D-035](#d-035)).
- **The build copies `formats/` into the wheel.** Chosen.

#### Decision

- `formats/` at the root stays the one place a format lives in the tree. The wheel carries
  it as the package's data, and `schemas.formats_dir()` reads it from the installed package;
  in a checkout it resolves to the root's `formats/`.
- A test builds the wheel, installs it into an empty environment outside the tree and
  validates a fixture there.

#### Consequences

- The client library the orchestrator will share validates wherever it is installed.
- How the build copies the directory is the builder's.

---

<a id="parked"></a>
<a id="d-080"></a>
### D-080 — A phase is built in four stages on an integration branch and lands on `main` as one squash

**Status:** Accepted 2026-11-09. Adds to [D-033](#d-033): how its flow runs for a phase of
[core.md](core.md#sequence)'s "Sequence", what gives each plan the review a pull request would,
and where the build's working records live. D-033 stands, and binds every change that is not a
phase as before.

#### Context

D-033 gives a change three steps: a design document, a decision entry where a decision
changes, a pull request. A phase is larger than one change: several plans, each a branch, built
by agents under the maintainer's direction, with live runs that share hardware. Phases 4 to 7
were built one way without that way being written down, and each new session recovered it from
the last phase's records. Phase 7 followed a written draft of it, and its landing amended the
draft with what the phase taught.

Three things in that practice are not in D-033. The plans' branches are merged into an
integration branch and not into `main`, which takes the phase as one commit. The plans, the
ledgers of the build and its reviews are working documents that never enter the tree. And
decisions are taken during the build on the maintainer's behalf.

#### Options considered

How a phase reaches `main`:

- **Each plan a pull request onto `main`.** Not taken: `main` would hold a phase half built
  between plans, and a later plan's review often changes an earlier plan's code.
- **The integration branch merged, its history on `main`.** Not taken: the commits of a phase
  are its tasks and fix rounds, 42 in phase 7 and 210 in phase 6, and what they record is the
  ledgers'.
- **One squash onto `main`, the branch's history under a tag.** Chosen.

Where the build's records live:

- **In the tree.** Not taken: a plan is how a branch gets built, and is spent once it is; the
  design, this log and [verified-facts.md](verified-facts.md) are the record.
- **Under `local/`, git-ignored.** Chosen.

Decisions during the build:

- **Stop and ask at each.** Not taken: a build parked on a question waits for the maintainer
  and buys nothing a recorded decision does not.
- **Rule, record what it costs if wrong, and report before the landing.** Chosen, with four
  stops.

#### Decision

- **A phase goes through four stages**: settle, plan, execute, land.
  [CONTRIBUTING.md](../CONTRIBUTING.md#how-a-phase-is-built) states them, and
  `.claude/skills/build-phase/` is the procedure an agent follows, with the rules every
  implementer and reviewer is handed. CONTRIBUTING is right where the two disagree.
- **Settle is D-033's first two steps**: the phase's section in [core.md](core.md) and its
  decision entries, on the branch `phase-N-design`, with the behaviour they rest on read first
  and recorded. No plan is written before the maintainer approves the design.
- **Each plan is a branch** `phase-N/<n>-<name>`, merged into `phase-N-integration`. Its
  review is a fresh reviewer for each task and one for the whole branch, before it merges.
- **A decision taken during the build is a ruling**, written in the plan's ledger with what it
  costs if wrong and reported to the maintainer before the landing. One that departs from a
  decision's text becomes a new entry at the landing. The build stops for four things alone:
  an operation that cannot be undone, a security-sensitive action, a merge into `main` or a
  push, and a plan so broken that every way forward is a guess.
- **A phase lands only on the maintainer's word**, as one squash commit on `main`, after the
  phase is written as built on the integration branch. That branch's history is kept under the
  tag `archive/phase-N-integration`. Nothing is pushed unless the maintainer asks.
- **Plans and the build's records stay out of the tree**: plans under `local/plans/`, the
  ledgers, briefs, reviews, rulings and run logs under `local/sdd/phase-N/`. What a later reader
  needs from them is in the design, this log and verified-facts.md.

#### Consequences

- `main`'s history says what each phase built, one commit a phase. Why a line is as it is is
  read from the design and this log, not from a task's commit.
- The archive tag is local until it is pushed, so the hashes a ledger names resolve only where
  the tag is.
- The procedure is amended at each landing with what the phase taught.
- The new terms are in [glossary.md](../docs/glossary.md).


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

- **A drain at the packages' requests.** The multi-host trial ran on clabernetes' default
  requests (200m CPU, 512 Mi), so neither the spread nor the drain was exercised with the
  packages' 0.5 CPU and 1.5–2 GiB ([D-036](#d-036)). Phase 7's many-twins scenario read the
  spread on 2026-11-09: five twins' fifteen pods at the packages' requests, five on each of
  the three hosts ([verified-facts.md](verified-facts.md), "Five twins at once through the
  core"). The drain at those requests stays open.
- **The node clients under larger twins** ([D-075](#d-075), [D-078](#d-078)). The host's
  connections were read for three twins of three nodes on the local run, and nothing is
  bound. What five twins' pushes and reads open from the core on the cluster, and what twins
  of tens of nodes do on either runtime, is unread: the cluster harness sees only the suite's
  own host. A reading from inside the core, and a bound where it shows the need, is a later
  phase's.
- **The size of the twin the many-twins scenario expects refused** ([D-073](#d-073)). It is
  fixed at forty SR Linux nodes, 20 CPUs and 81920 MiB, above every runtime the suite has
  met. On a runtime with more than about 80 GiB free the dry run would answer 200 and the
  scenario fail, having made no twin. Sizing that twin from the capacity read taken before
  it, as D-073 sizes admission from the runtime and not from a number, is a later plan's.
- **A condition carrying the last verify's status** ([D-070](#d-070), [D-032](#d-032)).
  `Ready` has never meant conforming, so a step or a restore whose wait expired ends `ok`,
  `Ready` True, and only its verdict says verify did not hold. A condition carrying the last
  verify's status, set by every run that verifies, would show it on the record; whether to add
  it, and what it says between runs, is a later phase's.
- **A holder that outlives its Lease under a slow store** ([D-071](#d-071), [D-062](#d-062)).
  The store's calls run on the event loop, each bounded by its 10 s timeout, and the stop at a
  lost Lease comes on time only while the loop runs: two such calls back to back held a holder on
  the cluster until 21.08 s after its last renewal was sent, 6.08 s past its 15 s deadline, where
  a waiting core takes the Lease from about 15.5 s (D-071's status note,
  [verified-facts.md](verified-facts.md)). The remedy, the store's calls moved off the loop or
  bounded under the Lease, is a decision entry of a later plan.
- **The release on a Conflict** ([D-062](#d-062), [D-071](#d-071), [D-072](#d-072)).
  `Lease.release` (`core/src/fylgja_core/lease.py`) writes the Lease held by no one at the version
  it holds, and gives up on a Conflict with one WARNING, the next holder taking it once its
  duration has passed ([verified-facts.md](verified-facts.md)): right for now, the duration being
  D-062's promise to that holder. A read-back, then one more write where the Lease is still this
  holder's, would release at once where another hand wrote the Lease's metadata or this holder's
  own renewal landed unanswered, as `renew` already reads back. The conformance suite's cluster
  kill depends on the present behaviour, the annotation it writes refusing the release, and with a
  read-back would have to move the Lease's `holderIdentity` instead. The change is a decision
  entry of a later plan, after the slow-store question above.
- **A cEOS node with no data link refuses `ip routing`**: its forwarding agent never starts
  ([verified-facts.md](verified-facts.md)), so the push of a configuration carrying it is
  refused. Whether the compiler reports it as a finding, or the driver gives such a node a
  port, is open.
- **What a read of Infrahub costs as an instance's history grows** ([D-089](#d-089),
  [D-094](#d-094)). On one development instance the reader's contract tier rose run over run:
  396 s and 402 s, then 757 s, 895 s, 1,602 s and 1,783 s, the last two on 2026-11-12
  ([verified-facts.md](verified-facts.md), "Infrahub 1.11.11" and "Prefect 3.9.2";
  [CONTRIBUTING.md](../CONTRIBUTING.md), the contract tier's row). The seed's own line did
  not: 242.52 s and 254.12 s in those last two runs. Why is not established. One hypothesis, read
  from the code and from the reader's README ("What it sends") and not verified on the
  instance: a read pages every event of the logs it reads since the oldest checksum stamp among
  the scoped devices; a regeneration that stores the same bytes moves no checksum stamp, so
  that floor stays where the first seed put it, while every seed, mark, proposed change and
  contract run adds events above it. The test, not run before phase 8 landed: time one read,
  purge the instance, seed it, and time the same read. If the hypothesis holds, a stage's read
  costs more the older an instance's artifacts are, which bears on the reader's standard
  ([D-081](#d-081)) and on `fylgja-step`'s flow, which has 600 s for a plan that took 187.3 s
  and 211.6 s on three devices. `InfrahubEvent` was read to take an `until`
  ([verified-facts.md](verified-facts.md), "The events' upper bound, and a completion as their
  floor"), which the reader does not send. Whether the events read is bounded or rebuilt is a
  later phase's.
- **A core test whose margin is the host's load.**
  `core/tests/test_containerlab_driver.py::test_the_deploys_budget_starts_once_the_lock_is_held`,
  phase 7's and untouched by phase 8, failed once under load during phase 8's plan 6 with
  `assert 0.2468 > 0.25`, and passed in the runs after. It holds one deploy for 0.3 s and
  asserts that the second started more than 0.25 s after the first, a margin of 50 ms. The
  margin is the test's, not the driver's. Mending it, so that it does not turn on when the
  first deploy started, is a later plan's.
- **A check on a task worker that lacks its branch's commit, and a check that runs for most of
  its `timeout`** ([D-091](#d-091), [D-093](#d-093)). In every acceptance run both checks ran
  on a worker that held the commit's tree, and `fylgja-twin` concluded within 485 s of the
  proposed change's creation under a `timeout` of 4,260 s
  ([verified-facts.md](verified-facts.md), "Infrahub 1.11.11"). A recreated worker was read to
  hold no clone, and a check on it to fail; whether a check lands on such a worker once `make
  infrahub-register` has ended, and what a check of about an hour does on a worker, were not
  read. Nor was a check concluding `failure` from a rehearsal run through Infrahub.
- **What the stale rule does not yet rest on a reading of** ([D-089](#d-089)). The reader's
  `mapping.md`, "The stale rule", lists it: among others an artifact reading `Error`, a
  device's platform changed, an address moved to another port, a rebase of a branch, whether
  the task workers' restamp moves an attribute's own stamp, and an artifact that a proposed
  change's validation regenerates with other bytes. Which role of Infrahub's grants the
  reader's reads and no more was not read either; the development Infrahub gives the reader
  the admin's token.
- **A registration read from GitHub** ([D-085](#d-085), [D-094](#d-094)). The development
  Infrahub reads the registration from the main checkout's `.git`. What Infrahub does with this
  repository registered from GitHub was not read, and waits on the maintainer's word.
- **Infrahub on volumes kept for days: its start, and why what reads it is slow**
  ([D-101](#d-101), and the question above on what a read of Infrahub costs). On 2026-11-13
  `make infrahub-up` on the volumes kept since phase 8 failed twice of three, each time on a
  database container read unhealthy; the database's log said `Started.` 51.6 s after its
  container's start. Phase 8's rehearsal made once more then took 600.5 s where it had taken
  277.2 s: the checks' validators were made 131.4 s and 131.7 s after the proposed change's
  creation, where phase 8 read 44.3 s; the first stage's plan was built 248.6 s after the
  run's start, against 98.6 s; and `fylgja-step` concluded 547.2 s after its start, of its
  `timeout` of 900 s, against 213.7 s. The twin's own steps were not slower. Read once during the run, Infrahub's message queue was at 176% of a CPU and
  its task manager at 99%; read after it, the task manager's database held about 10,300 flow
  runs, a derivation, the sum of its counts by state
  ([verified-facts.md](verified-facts.md), the end of "Infrahub 1.11.11"). The cause was not
  read: whether it is the instance's history, the task manager's, the host's load, or code phase
  9 changed in the planning. The test the question above names, a read timed before a purge and
  after a seed, is still not run. What is asked: what makes it slow; whether the database's
  health check needs a longer allowance on kept volumes; and whether `fylgja-step`'s 900 s
  stands on such an instance.
- **The cluster's rehearsal against the local driver's** ([D-101](#d-101)). In the dry runs the
  report came 249.6 s after the tag with the core on the cluster and 131.0 s with it on the
  local driver, 1.9 times, a derivation; in the maintainer's runs 231.2 s and 125.6 s. The
  baseline took 102.3 s and 108.2 s on the cluster against 75.1 s and 77.3 s, and the step
  `third-link` 68.9 s and 40.6 s against 14.2 s and 12.8 s, 52.8 s of the first from `pushed`
  to `verified` ([verified-facts.md](verified-facts.md), "NetBox 4.7.5 with netbox-branching
  1.2.3"). The cause was not read, nor the core's own log on the cluster. Where a rehearsal's
  time goes on clabernetes is a later phase's to read.
- **No rule of verify reads an address** ([D-031](#d-031), [D-101](#d-101)). The seeded
  change's second step gives a port of `n1` an address. Of a pushed configuration verify reads
  back each cabled port's admin state and the host name, so the step's 19 checks were the step
  before it's again, and nothing checked the address the second step pushed: the demonstration
  showed a push accepted, not an address in force (a derivation from verify's rules,
  [verified-facts.md](verified-facts.md), "What NetBox's render pushed, by the core's log").
  Whether verify gains a fact for an address ([D-030](#d-030)), or the seeded change a step
  verify can read, is open.
- **A mark through another core** ([D-100](#d-100)). The source reads a mark's blueprint from
  the core it runs through by its id, so a core given the same intent holds it. On 2026-11-13
  the two acceptance branches' marks named the same two ids, `mark.unheld` was read through the
  cluster's core before that core was given them, and the local driver's branch was not planned
  through it after. Whether that plan then builds, and whether the finding's sentence, "a mark
  belongs to the core it was given to", should say so, is open.
- **A row of the changelog that commits below a higher one** ([D-098](#d-098)). The reader's
  bracket counts the rows at or below its open's id to catch one. Whether NetBox ever commits a
  row of a lower id after a higher one was not read, nor its retention of the changelog, under
  which a row pruned as another commits late would cancel in that count.
- **A `view` grant with constraints, under the reader** ([D-098](#d-098)). By NetBox's design
  of its permissions, as documented and not as read, a constrained grant shortens a list and
  its `count` alike, so every check of a read would hold on a blueprint of less than NetBox
  holds. The reader's README asks that each grant carry none. What a list and its `count`
  answer under one was not read, and nothing in a read can tell.
- **Prefect's credential in NetBox's changelog, and what a deployment does instead**
  ([D-100](#d-100)). The webhook's rows of `main`'s changelog hold its headers unmasked to any
  account that may view the changelog, and outlive the webhook. Not read: whether grants with
  constraints can hide a webhook's rows from the reader's and the example's accounts and still
  leave the bracket and the count what they need; how long NetBox keeps a changelog row; and a
  receiver of a deployment's own before Prefect, which is not built. Of clearing the value
  from the development NetBox, by replacing `FYLGJA_ORCHESTRATOR_AUTH` or by a purge, the
  maintainer said "leave it" (2026-11-13). What stays open is what a deployment would do
  instead.
- **Authoring a change of several steps in NetBox** ([D-097](#d-097), [D-100](#d-100)). The
  seed's script builds the branch and runs `stage mark` at each step. What an engineer does in
  its place, and whether a mark is then taken by a command, a script or a page inside NetBox,
  the design left to a later phase, "once the concept is proven" (the maintainer, 2026-11-12).
  With it: a tag set while Prefect answers and no runner serves, two branches tagged close
  together, and a rehearsal from a tag ending other than `passed` on a real driver, none of
  which was read.
- **Three small gaps the last plan left.** In `netbox/seed/box.py` a list whose `count` moves
  between two pages is an error with no status, for which the seed prints the remedy of a
  NetBox that did not answer, `make netbox-up`, though NetBox answered. The readiness block of
  the acceptance run through NetBox's tag holds the runner's `FYLGJA_API_ADDRESS` to its own
  and not the runner's `FYLGJA_API_CA`. A fix of either is followed by a live run, the
  contract tier's or the block's, which is why neither was made in the last plan's fixes. And
  the probe of `scripts/wheelcheck.py` that judges that each change source loads its own
  reader alone drops the other source's modules but not the package's attribute for them, so
  one import form inside a source would pass it; the pure tier's scan of the imports sees
  every form.
- **`make netbox-up` where the network cannot be inspected, or the range is taken**
  ([D-099](#d-099)). The script's line for a network Docker cannot inspect, and its failure
  after a recreate, are held by pure tests and were not read on a real Docker; nor was what
  Compose's own `up` does to a standing network whose subnet the override changes.
