# Feature Specification: The split: the core and the orchestrator

**Feature Branch**: `020-core-orchestrator-split`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/020-core-orchestrator-split GIT_BRANCH_NAME=020-core-orchestrator-split. 0.3, the fifth of its six specs: the split, the core and the orchestrator, as docs/roadmap.md's F-027 and Release 0.3 section define it. Read specs/020-core-orchestrator-split/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.3 is exploratory coding toward the production refactor
([roadmap](../../docs/roadmap.md#release-03)), and this is its fifth spec
([F-027](../../docs/roadmap.md#f-027)), added on 2026-10-29 and placed before F-025 by the
operator. Since 018 every workflow starts with a snapshot id and a bundle id
([D-061](../../docs/decisions.md#d-061)), since 019 no workflow reads a source of truth
([D-062](../../docs/decisions.md#d-062)), and since 016 the one input that is not intent
reaches the core inside the snapshot ([D-064](../../docs/decisions.md#d-064)). But the
server still reads Infrahub for `twin create --branch` and `--stage`, `twin step --stage`,
`intent read`, `stage list`, `stage plan`, `twin rehearse` and `schema check`, resolves
stages, renders the rehearsal's report and holds Infrahub's token, and the rehearsal is the
worker's fourth workflow. The seam the release has been proving is proved on the core's
side alone. This feature cuts along it. **Fylgja becomes two deployables**
([D-065](../../docs/decisions.md#d-065)): a **core** that builds, steps, destroys, shows and
verifies a twin from a snapshot and knows no branch, proposed change, stage or source of
truth; and an **orchestrator** that owns the readers, the stages and their resolution, the
rehearsal and the report posted back to the source, and drives the core through the API
alone, never by starting its workflows.

What the operator gets: the same twin from the same intent, by the same commands under a
second name. Every command that names a branch, a stage or a rehearsal, and the schema
check, moves to the orchestrator's CLI, `fylgja-cli`, which prints the same findings
document and exits by the same status; `fylgja`'s own CLI keeps create and step from a
snapshot, provision, destroy, show, verify, compile and the package validation. The core's
server starts with no Infrahub credential and listens on loopback alone; the rehearsal runs
as a flow of the orchestrator and posts its own report; the two checks inside Infrahub ask
the orchestrator, on the Docker bridge, where they asked the core. A run of the core can be
started and left, then read and interrupted by its identity, which is what a platform whose
resume is a rerun needs. The core gains one pure operation, the step between two
snapshots, so the plan and the report keep their edges though nothing outside the core
compiles. The Infrahub reader is rewritten in Python on the orchestrator's toolchain and
reads to the same snapshot, byte for byte, and the goldens, the fixture's snapshot id and
its compiled id do not move: that is the test that the split changed nothing of what a twin
is. The brief's [Decided](brief.md#decided) list is settled and restated here only where a
requirement needs the sentence; the two decision entries, D-065 and D-066, are written; and
every exact name and wording the brief [leaves to the plan](brief.md#left-to-the-plan) is
the plan's to write.

Five actors appear below. **The operator** runs the lab host, models intent in Infrahub,
marks stages, opens proposed changes and runs both CLIs. **The core** is the `fylgja`
binary in its three roles, `serve`, `worker run` and the client CLI: its server takes a
snapshot, compiles, files and starts runs; its worker runs provision, step and destroy;
every refusal that concerns a twin, a bundle, a snapshot or the host is the server's. **The
orchestrator** is a project of its own on its platform, in this repository, with its flows,
its CLI `fylgja-cli`, its state as files and its one adapter, the Infrahub adapter, which
reads a branch, a pinned branch or a stage under a scope to a snapshot file; every refusal
that concerns a branch, a proposed change, a stage, a scope or the schema is its. **The
checks**, `fylgja-step` and `fylgja-twin`, are clients of the orchestrator inside Infrahub's
task workers. **Infrahub** is the first source of truth and the one the development host
runs. F-025's NetBox adapter, following brought back as a flow, a callback on the core's
API, the explicit mutation of a node or a link and a second orchestrator platform are out
of this feature.

## Clarifications

### Session 2026-10-29

- No question was asked (headless). The brief's [Open](brief.md#open) section is empty,
  the operator having settled its six questions at feature-open on 2026-10-29, and the
  coverage scan found every category Clear or deliberately the plan's: functional scope,
  the five actors and the out-of-scope list (Clear, from the brief's Decided list); the
  entities, the snapshot's identity and the twin record's version (Clear; `twin.json`
  `12`'s shape, the orchestrator's record's shape and place, and the new operations' names
  and frames the plan's, by the brief); the journeys, each refusal and the empty or
  distrusted record (Clear; the words of a distrusted record's line and of the read of an
  unknown run identity the plan's); security, in that the core's token never crosses the
  bridge, the task workers hold the orchestrator's credential alone, and the adapter holds
  no node login and never the API's token (Clear); performance, tier 1's 65 s budget kept
  and tier 2's wall time and `fylgja-twin`'s `timeout` against the flow's overhead (the
  plan's, by the brief); the external dependencies, Prefect's open-source boundary and
  how a task worker triggers and waits for a deployment on the bridge, each verified on the
  development host by the plan before it is relied on (the plan's, by the brief); the
  formats and versions, what moves (`twin.json`, the API's documents) and what does not
  (FR-033), and whether the API's version moves (the plan's, by the brief); the negative
  flows (Clear; the 015 defect's fate the plan's to confirm); the constraints and the
  rejected alternatives (Clear, each *Not chosen* in the brief's Decided list);
  terminology (Clear; Core, Orchestrator, Adapter, Tool and Flow (orchestrator) are the
  glossary's new terms, and the two Flows and the two Checks are told apart); the
  completion signals (Clear, the fixture's ids and the goldens); and no placeholder or
  unquantified adjective remains. Two consequences the spec states that the brief leaves
  implicit are derivations, not decisions, recorded here for `analyze`: a distrusted record
  leaves `twin step` requiring a target and `stage list` without a twin row, as 019's rule
  for a twin that names no stage already has it (US6 scenario 2, FR-021); and a twin the
  reclaim finds not its own leaves the rehearsal refused as the host held, as 015's
  `host.twin.present` already refuses it (US6 scenario 4).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A proposed change is rehearsed and reported by the orchestrator, while the core knows no branch (Priority: P1)

The operator opens a proposed change on a branch, marks its stages and marks it ready for
review. Infrahub runs `fylgja-twin` in a task worker; the check triggers the orchestrator's
rehearse flow on the Docker bridge, waits for its run, reads its document and concludes
from the report's status alone. The flow plans the stages through the adapter, reclaims a
twin its own dead run left, creates the baseline through the core's API, steps and
verifies each later stage in order through the step's wait, stops at the first that
fails, destroys whatever happened, computes each stage's verdict and the report, and posts
the report as a thread on the proposed change, as the view shows one. Throughout, the
core's server and worker run with no Infrahub credential in their environment, the server
listens on loopback alone, and its log shows no request to Infrahub, since it can make
none. The report's readers see no change but `fylgja-cli` where the reproduce lines named
`fylgja`.

**Why this priority**: this is the feature's one exit criterion. A rehearsal is the one
command that touches everything the split moves: the reader, the stages, the rehearsal's
rules, the report, the check and the core's runs. If it passes through the seam, the seam
holds.

**Independent Test**: tier 3's case 9, through the orchestrator: a proposed change with
three stages, two rehearsals asked by `fylgja-twin` from inside Infrahub, the second
failing on `verify.burst` at `probe-port-down`, the thread's table carrying `loss` as it
does today, with the core's server started with no `INFRAHUB_*` and the credential greps
extended to the orchestrator's logs. In tier 2, the orchestrator's rehearse flow against
the real Infrahub and a core server started with no Infrahub credential, refused before
any run on a stale mark, and the composition the fixture tool exercises today
(`TestRehearseComposedByTheFixtureTool`'s), and `TestChecksInsideInfrahub` reaching the
orchestrator's platform on the bridge.

**Acceptance Scenarios**:

1. **Given** a ready proposed change with marked stages and no twin, **When** Infrahub runs
   `fylgja-twin`, **Then** the check triggers the rehearse flow on the orchestrator's
   platform through the Docker bridge, waits for the run, and concludes success when the
   report's status is `ok` and failure otherwise; it posts nothing itself.
2. **Given** that rehearsal, **When** the flow ends, **Then** the report is one thread on
   the proposed change holding one comment whose markdown is the report as 015 and 016
   shaped it, its table carrying `loss`, and whose reproduce lines name `fylgja-cli`.
3. **Given** a core server started with no `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` or
   `FYLGJA_DEFAULT_SCOPE`, **When** the rehearsal runs, **Then** every create, step,
   verify and destroy reaches the core through its API alone, the server's log names no
   request to Infrahub, and the core's token appears in no request on the bridge.
4. **Given** a draft proposed change, **When** Infrahub runs `fylgja-twin`, **Then** the
   check succeeds with its skip message and no flow runs, as today.
5. **Given** a stage whose mark is stale, **When** the rehearsal is asked, **Then** it is
   refused before any run by `stage.artifact.stale`, with 014's wording and exit, as the
   orchestrator's refusal.
6. **Given** a rehearsal whose flow is cancelled or times out, **When** it ends, **Then**
   the twin it built is destroyed and the report says what was reached, as the
   workflow's deadline cut did.
7. **Given** a rehearsal whose run died outside Fylgja and left a twin, **When** the next
   rehearsal starts, **Then** the twin is reclaimed and `rehearsal.twin.reclaimed` warns,
   naming the run and what was removed; a twin the operator built is never reclaimed.
8. **Given** the host held by a twin or a run of the operator's, **When** `fylgja-twin`
   asks, **Then** it asks again at 015's interval while its deadline allows, then fails
   naming what holds the host, with the retry and the margin now the glue's.

---

### User Story 2 - The core's surface narrows to the snapshot (Priority: P1)

The operator runs the core's commands with a snapshot: `twin create --snapshot <id|file>`,
`twin step --snapshot <id|file>`, `twin provision`, `twin destroy`, `twin show`, `twin
verify`, `twin compile --snapshot` and `psp validate`, each as today. `twin create
--branch`, `--at`, `--stage`, `--scope` and `--probes`, `twin step --stage` and `--probes`,
`twin rehearse`, `stage list`, `stage plan`, `intent read` and `schema check` are gone from
`fylgja`'s CLI, and the API's operations and arguments under them are gone with them: a
lost operation's path is `404` as an operation the version has not, and a lost argument is
refused as unknown. The server's environment loses `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN`
and `FYLGJA_DEFAULT_SCOPE`, its start-up report says it dials the workflow service, Docker,
containerlab and the nodes and nothing else, and it listens on loopback unless told
otherwise. The worker serves three workflows, provision, step and destroy, and the
seventeen activities. The twin record moves to `12`: it names the snapshot, the bundle, the
scope and the mapping, and no stage and no rehearsal; `twin show`'s kinds stand and its
stage line goes; a record of `11` or earlier is shown and destroyed, never stepped from.
The step's rule that a twin never steps to another scope or mapping stays, read from the
two snapshots' envelopes.

**Why this priority**: this is the split on the core's side, the half the release's four
earlier specs prepared. Until the handlers that read Infrahub leave, the core knows a
branch and holds a credential it has no business holding.

**Independent Test**: in tier 1, each lost operation answers `404` with the version's
"no operation at this path" and each lost argument is refused as unknown; a create and a
step by snapshot id and by file; the worker registers three workflows; a `12` record
round-trips and an `11` is shown and refused a step; the boundary test over imports. Live,
start the server from a shell with no `INFRAHUB_*` and read its report; create from the
fixture's snapshot by id and read `twin show`.

**Acceptance Scenarios**:

1. **Given** a request to `/v1/twin/rehearse`, `/v1/stage/list`, `/v1/stage/plan`,
   `/v1/intent/read` or `/v1/schema/check`, **When** the server reads it, **Then** it is
   `404` without `Fylgja-Api-Versions`, as a path the version has no operation at, and
   nothing was read or done.
2. **Given** a request to `twin.create` or `twin.step` carrying `branch`, `at`, `stage`,
   `scope` or `probes`, **When** the server reads it, **Then** it is refused as an unknown
   argument, as any unknown argument is, before any guard runs.
3. **Given** `fylgja twin create --branch <b>`, `fylgja twin rehearse`, `fylgja stage list`,
   `fylgja intent read` or `fylgja schema check`, **When** the operator runs it, **Then** it
   ends as an unknown flag or command, exit 2, with no request sent.
4. **Given** a shell with no `INFRAHUB_ADDRESS`, `INFRAHUB_API_TOKEN` or
   `FYLGJA_DEFAULT_SCOPE`, **When** the operator starts `fylgja serve`, **Then** it starts,
   its report names the workflow service, Docker, containerlab and the nodes as what it
   dials and no Infrahub and no default scope, and it listens on `127.0.0.1:7650` when no
   `--listen` is given.
5. **Given** a snapshot id the store holds, or a snapshot file, **When** the operator runs
   `fylgja twin create --snapshot` or `fylgja twin step --snapshot`, **Then** the twin is
   built or stepped as 018 and 019 defined it, the probes the snapshot carries placed as
   016 defined them, with no request to any source of truth.
6. **Given** a worker of this build, **When** it starts, **Then** its report names both
   platform packages and the probe package as today, and it serves provision, step and
   destroy and the seventeen activities, and no rehearsal.
7. **Given** a twin of this build, **When** the operator runs `twin show`, **Then** its kind
   is one of `none`, `snapshot`, `from_bundle` and `diverged`, its kind line names the
   snapshot and its branch and `at` or read time as 019 defined it, and no line names a
   stage or a rehearsal.
8. **Given** a record of `twin.json` `11` or earlier, **When** the operator runs `twin
   show`, **Then** it is shown and names its version; `twin step` refuses it as
   unsteppable, naming `twin destroy` as the remedy; `twin destroy` clears it.
9. **Given** a twin and a snapshot whose envelope names another scope or another mapping,
   **When** the operator steps to it, **Then** it is refused by `step.twin.unsteppable`
   before any run, naming both, read from the two envelopes alone.

---

### User Story 3 - The operator reads, creates, steps, lists and plans through `fylgja-cli` (Priority: P1)

The operator runs the orchestrator's CLI where they ran `fylgja` for a branch or a stage:
`fylgja-cli intent read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>]
[--probes <file>] --out <file>`, `fylgja-cli twin create --branch <b> | --stage <b>/<l>`
with `--dry-run`, `fylgja-cli twin step [--stage <b>/<l>]`, `fylgja-cli stage list
[--branch <b>]`, `fylgja-cli stage plan --branch <b>`, `fylgja-cli twin rehearse --branch
<b> [--markdown]` and `fylgja-cli schema check --branch <b>`, each with `--json`. Each runs
its flow: the adapter reads the branch, the pinned branch or the stage under the scope,
with probes from the file, else from `FylgjaProbe` on the default branch, else none, and
writes a snapshot file whose id is the one the Go reader files today; the flow then calls
the core's `twin.create`, `twin.step` or `twin.compile`, or lists, plans or checks; and the
command prints the same findings document the core's CLI printed, text or JSON, and exits
by its status. Every stage rule and refusal keeps 014's, 015's, 016's and 017's identifier
and wording where the rule moved whole. The snapshot the adapter takes from
`fylgja-fixture` is `0940db93…`, and the twin it creates is built from bundle `c3872f5c…`.

**Why this priority**: this is the operator's half of the split. Without it the commands
the core loses are lost to the operator too, and the tiers lose the document that is their
oracle.

**Independent Test**: in tier 2, the adapter's read of `fylgja-fixture` files `0940db93…`,
its stage list and schema check answer what the server's did, each ported contract test
green and each compared with the Go reader's answer before the Go reader goes; a create
from the fixture and a stage plan of a throwaway proposed change through the flows. In
tier 3, cases 1 to 8 through `fylgja-cli` for every command that names a branch or a stage,
case 3's dry run among them, and through `fylgja` for the rest.

**Acceptance Scenarios**:

1. **Given** the fixture branch, **When** the operator runs `fylgja-cli intent read
   --branch fylgja-fixture --out s.json`, **Then** the file is a snapshot `2` whose id is
   `0940db93…`, byte for byte the one the Go reader files today, and the command prints
   the read's summary line and exits 0.
2. **Given** that branch and no twin, **When** the operator runs `fylgja-cli twin create
   --branch fylgja-fixture`, **Then** the adapter reads, the flow calls the core's
   `twin.create` with the snapshot, the run's progress is printed as it happens, the twin
   is built from bundle `c3872f5c…`, and the document is `twin.create`'s as today.
3. **Given** a proposed change with marked stages, **When** the operator runs `fylgja-cli
   stage list --branch <b>`, **Then** the `stages` document lists the branch point, the
   marks and the head with what each resolves to, the twin's row where the orchestrator's
   record names a stage, and the warnings of 014 where they apply.
4. **Given** that proposed change, **When** the operator runs `fylgja-cli stage plan
   --branch <b>`, **Then** the `plan` document names each stage's snapshot and bundle and
   the step between each pair, nodes and links changed and artifacts moved, as today's
   plan does, and `fylgja-step` concludes from it as today.
5. **Given** a twin the orchestrator created from stage A, **When** the operator runs
   `fylgja-cli twin step` with no `--stage`, **Then** the target is the next stage of the
   twin's own proposed change; with `--stage <q>/<l>`, that stage of any proposed change;
   and the record names the stage reached.
6. **Given** a branch, **When** the operator runs `fylgja-cli twin create --branch <b>
   --dry-run`, **Then** the core's dry run is reached and its lines printed, and no lab,
   container, twin directory or run changes.
7. **Given** a branch whose schema lacks a kind or a field the mapping reads, **When** the
   operator runs `fylgja-cli schema check --branch <b>` or any read of it, **Then** it is
   refused under the `schema.*` rules with 017's identifiers and wording.
8. **Given** a probe file, **When** the operator runs any of the five reading commands with
   `--probes <file>`, **Then** the snapshot carries the file's probes; with none, the
   default branch's `FylgjaProbe` objects; with neither, none; an empty file declares
   none.
9. **Given** `fylgja-cli` with `--scope` left out, **When** the operator runs it, **Then**
   the scope is `FYLGJA_DEFAULT_SCOPE` from the orchestrator's environment, and its
   absence is `scope.unset` as today.
10. **Given** a device whose platform no shipped package matches, **When** the adapter
    reads it, **Then** it is refused by `platform.unmatched` naming the pair and every
    package's pairs; and a snapshot whose package the core's packages do not know is
    refused by the core when it takes the snapshot, never silently.

---

### User Story 4 - A run is started, then read and interrupted by its identity (Priority: P2)

A client of the core's API asks `twin.create`, `twin.provision`, `twin.step` or
`twin.destroy` to end its answer at the run's identity instead of following it. A new
operation reads a run by its identity, answering the events so far and, once it has ended,
its document, both built from the run's history, so that the server still keeps nothing
between two requests. The interrupt reaches a run by its identity as well as by its stream.
The stream stays for the core's own CLI, which follows a run as it does today. The
orchestrator's flows use the detached shape, so a flow that reruns after its platform
restarts finds its run rather than starting a second into `run.in_flight`.

**Why this priority**: it is the orchestrator's first demand of the core, and the shape
the production shape named independent of the platform. Without it a flow holds a
connection open for the length of a run and loses the run when the platform restarts.

**Independent Test**: in tier 1, a run started detached answers its identity and no event;
a read of it replays its events and, once ended, its document, from a recorded history,
each of the seven replay histories among them; an interrupt by identity reaches the run as
the stream's did. In tier 2, a flow creates from the fixture detached and polls to the end.

**Acceptance Scenarios**:

1. **Given** a request to `twin.create` under the detached argument, **When** the server
   starts the run, **Then** the answer ends with the run's identity and no event, and the
   run goes on.
2. **Given** a run in flight, **When** a client reads it by its identity, **Then** the
   answer carries the events so far and ends without a document; once the run has ended,
   the same read ends with the run's document, the one the stream would have carried.
3. **Given** an identity no run has, **When** a client reads it, **Then** it is refused in
   words that name the identity, before anything is dialled but the workflow service.
4. **Given** a run in flight, **When** a client interrupts it by its identity, **Then** the
   run is asked to cancel, as the stream's first interrupt asks today, and a read of it
   afterwards shows its cancellation.
5. **Given** `fylgja twin create --snapshot <id>`, **When** the operator runs it, **Then**
   the stream is followed as today, line for line, and the operator's interrupt reaches the
   run through the stream as today.
6. **Given** a destroy started detached, **When** a client reads it, **Then** the events
   and the document are the destroy's, with no `run` frame, as the stream's answer has
   none today.

---

### User Story 5 - The step between two snapshots is an operation of the core (Priority: P2)

A client sends two snapshots, each a filed id or a file, and the core compiles each on the
goldens' code path and answers the step between them: the nodes and links changed and the
artifacts moved, pure, touching no lab and starting no run. The orchestrator's plan and
rehearse flows are its consumers: the stage plan's steps and the report's drawing keep
their edges, though nothing outside the core compiles.

**Why this priority**: the adapter is a reader and never compiles, and D-040 rejected a
compiler in a client; without this operation the plan shows snapshot and bundle ids alone
and the drawing loses its edges.

**Independent Test**: in tier 1, the goldens: three-node to three-node-probed names the
two probe hosts and their links and no changed device; a snapshot to itself is unchanged; a
snapshot whose compile is refused is refused with the compile's finding. In tier 2, a
stage plan whose steps equal today's plan's for the same proposed change.

**Acceptance Scenarios**:

1. **Given** the three-node and three-node-probed goldens' snapshots, **When** a client asks
   the step between them, **Then** the answer names the two hosts `<probe>-a` and
   `<probe>-b` and their links as added, and no device changed.
2. **Given** one snapshot twice, **When** a client asks the step, **Then** it is
   `unchanged`, as a step to a stage of the same bundle is today.
3. **Given** a snapshot whose compile is refused, **When** a client asks the step, **Then**
   the refusal is the compile's own finding, and nothing is deployed, stepped or filed
   beyond the snapshots.
4. **Given** a stage plan through `fylgja-cli`, **When** its steps are read, **Then** each
   step between two stages is what the core answered for their two snapshots, and equals
   what today's plan computes for the same stages.

---

### User Story 6 - The orchestrator keeps one record of the twin it drove (Priority: P2)

The orchestrator files every snapshot it takes under a directory of its own, by id, never
overwriting, and keeps one record of the twin it last drove: the stage it created or
stepped it to, that stage's snapshot id and the flow run that did it. The record is read
beside the core's `twin show` and trusted only while the two name one snapshot. It is what
`stage list`'s twin row, `twin step`'s default target and `stage.twin.moved` read now that
the core's record names no stage, and what the reclaim reads to tell a twin its own dead
run left from the operator's. Files, no database of Fylgja's own.

**Why this priority**: four behaviours the operator has today have nothing to read once
`twin.json` names no stage; and the snapshot directory is the seed of the stage store
F-025 fills for a source that cannot replay time ([D-066](../../docs/decisions.md#d-066)).

**Independent Test**: in tier 1, the record written by a create and a step, read by the
list, the default target and the moved rule, and distrusted when `twin show`'s snapshot
differs; in tier 2, a twin created from a stage, stepped by default to the next, listed
with its row, and the record left stale by a step through `fylgja`'s own CLI to another
snapshot.

**Acceptance Scenarios**:

1. **Given** a twin the orchestrator created from stage A, **When** the operator runs
   `fylgja-cli stage list`, **Then** the twin's row names A, read from the orchestrator's
   record, and the core's `twin show` names A's snapshot.
2. **Given** that twin, **When** the operator steps it through `fylgja twin step
   --snapshot` to another snapshot, **Then** the orchestrator's record no longer matches
   `twin show`'s snapshot, the next `fylgja-cli stage list` shows no twin row for A and
   says why, and `fylgja-cli twin step` with no `--stage` is refused as naming no stage,
   requiring a target.
3. **Given** a twin the orchestrator created, **When** its stage no longer resolves to the
   `(branch, at)` it was created at, **Then** `stage.twin.moved` warns in `stage list` and
   beside a step's target, as today, judged under the record's scope.
4. **Given** a rehearsal whose flow run is dead and whose twin stands, **When** the next
   rehearsal starts, **Then** the reclaim reads the record and the platform's run state,
   finds the twin its own, and destroys it with `rehearsal.twin.reclaimed`; a twin whose
   record names no flow run of the orchestrator's, or whose snapshot `twin show` does not
   name, is left standing and the rehearsal is refused as the host held.
5. **Given** every snapshot the orchestrator took, **When** the directory is read, **Then**
   each is under its id, filed once, and a second take of the same snapshot writes nothing.

---

### User Story 7 - The repository, the host, the tiers, the decisions and the documents (Priority: P3)

The orchestrator lives in this repository under one directory with its own toolchain, its
tests and its lint; CI's unit job runs its tests beside Go's and its lint job its linter
beside golangci-lint and ShellCheck; the bring-up script gains a part that installs it and
starts its platform's server and worker detached, so the development host runs five
processes; `make` gains its targets. Tier 1 holds the Go tests, the boundary tests and the
Python tests of the flows' pure parts against goldens captured from the Go implementation
before it is removed; tier 2 holds the adapter's contract tests, ported from the Go
reader's and compared with its answers before it goes, and the flows against the real
Infrahub; tier 3 holds nine cases, `E2E-OK`. The constitution is amended MAJOR, citing
D-065 and D-066: I kept for the core and freed for the orchestrator, VIII and IX the
core's, XI gaining the orchestrator as a client. The contracts, the architecture and its
C4 model, the glossary, the development notes, `SECURITY.md`, the README, `CLAUDE.md`, the
verified facts and the roadmap say what is now true, the roadmap reconciled by the route's
first documents task.

**Why this priority**: none of it changes what a twin does, and all of it is how the next
spec, F-025, finds the toolchain, the flow shape and the stage store's seed it inherits,
and how a reader of the tree finds out what was decided here.

**Independent Test**: a fresh clone's CI runs three jobs green with the Python tests and
linter in them; `scripts/bring-up.sh` on the development host leaves five processes;
`make test` inside its budget; the constitution's version MAJOR with its Sync Impact
Report citing both entries; `make linkcheck` clean; grep the tracked documents for the
rehearsal as a workflow, the server on the bridge or the reader in Go as current
behaviour and find them only in the decision log's superseded entries, the archive and
the release notes.

**Acceptance Scenarios**:

1. **Given** the tree, **When** the boundary tests run, **Then** no package the core's
   binary links reads Infrahub, the Go module holds no reader, and the client reaches the
   core through the API alone, as today's test holds.
2. **Given** the goldens captured from the Go implementation, **When** the orchestrator's
   renderers run, **Then** the `stages`, `plan` and `rehearsal` documents' text and
   markdown match byte for byte but for `fylgja-cli` in place of `fylgja` in the reproduce
   lines, and each stage's verdict matches.
3. **Given** the constitution, **When** it is read, **Then** its version is MAJOR above
   2.3.0, its Sync Impact Report cites D-065 and D-066, I binds the core and frees the
   orchestrator, and XI names the orchestrator as a client.
4. **Given** the decision log, **When** D-065 and D-066 are read, **Then** each
   superseded entry carries its *Superseded* status line naming the part and the entry,
   and nothing else of it changed.
5. **Given** the roadmap, **When** it is read after the route's first documents task,
   **Then** F-027's row carries its description, its dependency on F-014 and its estimate,
   Release 0.3's total has moved by that estimate, and item 5 links to this feature.
6. **Given** the bring-up script run on the development host, **When** it ends, **Then**
   the workflow service, the core's worker and server, and the orchestrator's platform
   server and worker run detached, and each task worker of Infrahub reaches the
   orchestrator's platform on the bridge and the core's server not at all.

---

### Edge Cases

- **A record of `11` or earlier** is shown, naming its version, and destroyed; it is never
  stepped from, as 019 and 016 did with theirs. The upgrade note says to destroy any twin
  an earlier build left before upgrading.
- **A record of this build whose stage the operator wants**: it is the orchestrator's to
  know; `fylgja twin show` names the snapshot and `fylgja-cli stage list` names the stage,
  while the two agree.
- **The orchestrator's record and `twin show` disagree**: the record is distrusted and
  said so; nothing is refused by the record alone, and a target is required of `twin
  step` as for a twin that names no stage.
- **A snapshot the adapter wrote with packages the core does not know** (a skew between
  the adapter's `psp/*.yaml` and the core's): refused by the core when it takes the
  snapshot, under `platform.unsupported` as a CTM naming a package the build lacks is
  today; never silent.
- **A probe the adapter cannot place**: the core refuses the snapshot as it refuses a
  sent one today; which checks the adapter makes before it writes is the plan's.
- **Two flows at once**: refused by the core's fixed workflow identities under
  `run.in_flight`, as two shells were; the orchestrator adds no lock of its own on the
  core.
- **A flow that reruns after its platform restarts**: reads its run by identity rather
  than starting a second; a run it cannot find is reported, not restarted.
- **A rehearsal cancelled or timed out by the platform**: still destroys; the report says
  where it was cut, as `rehearsal.deadline.cut` does today.
- **A check cancelled or timed out by Infrahub**: as today, it interrupts the flow it
  started and Infrahub leaves the validator `in_progress`; the flow still destroys.
- **The orchestrator's platform unreachable from a task worker**: the check fails naming
  the address, as it failed naming the core's; `TestChecksInsideInfrahub` skips, saying
  why, where the task workers reach none.
- **The core's server reached from a task worker**: it cannot be; it listens on loopback
  alone, and the override's variables name the orchestrator's platform.
- **A detached run whose answer was cut** before the identity reached the client: `twin
  show` names it in flight, as today; the read by identity finds it by the fixed workflow
  identity.
- **A read by identity of a run the workflow service no longer holds**: refused in words
  that say so; no history is kept by the server.
- **A snapshot file sent to the step between two snapshots with no declared id**: the
  core computes the id and files it, as on create.
- **The 015 defect, a client following a rehearsal terminated outside Fylgja that answers
  only once its abandoned children close** (015 research §5.2): goes with the parent
  workflow, by the author's reading, which the plan confirms or corrects.
- **The rehearsal's deadline**: the flow's, derived from the stages' budgets as D-051
  derived it; how the flow learns the budgets without loading the packages is the plan's.
  `fylgja-twin`'s `timeout` of 4260 stands until the plan measures the flow's overhead.
- **The Go reader removed before the port reproduces it**: never; the route ports,
  compares against the Go reader's answers, then removes, as it captures the renderers'
  goldens before it removes them.
- **The task workers recreated with the changed override**: a live session's of the
  attended loop, with no twin up and no tier running; a headless session never runs it.
- **`fylgja-cli` with the core's server down**: the flow's refusal is `api.unreachable`
  as a client's is today, exit 2, and no twin changes.
- **A credential in a log**: the greps over the orchestrator's logs and its platform's
  find no token, password or login; the core's server log names no request to Infrahub.

## Requirements *(mandatory)*

### Functional Requirements

**The core's surface**

- **FR-001**: The core MUST be the `fylgja` binary in its three roles, unchanged in name,
  and MUST know no branch, proposed change, stage or source of truth: no package its
  binary links MUST read Infrahub, the Go module MUST hold no reader once the port
  reproduces it (FR-016), and the boundary MUST be held by a test over imports beside the
  one that holds the client to the API.
- **FR-002**: The API MUST keep `twin.create` (`snapshot`, `dry_run`), `twin.provision`,
  `twin.step` (`snapshot`, `allow_restart`, `wait`, `dry_run`), `twin.destroy`,
  `twin.show`, `twin.verify`, `twin.compile` and `psp.validate`, each as
  [api.md](../../contracts/api.md) has it, and MUST lose `twin.rehearse`, `stage.list`,
  `stage.plan`, `intent.read` and `schema.check`, each path answering `404` without
  `Fylgja-Api-Versions` as an operation the version has not, and the arguments `branch`,
  `at`, `stage`, `scope` and `probes` wherever they were taken, each refused as an unknown
  argument. `twin.create` and `twin.step` MUST take `snapshot` alone, a filed id or a file
  sent, which carries its probes.
- **FR-003**: The core's CLI MUST lose the same commands and flags, each ending as an
  unknown command or flag, exit 2, with no request sent; `fylgja --version` and `--help`
  MUST need no server.
- **FR-004**: The server MUST start and serve with no `INFRAHUB_ADDRESS`,
  `INFRAHUB_API_TOKEN` or `FYLGJA_DEFAULT_SCOPE` in its environment and MUST read none; it
  MUST dial the workflow service, Docker, containerlab and the nodes, and nothing else, and
  its start-up report MUST say so and name no Infrahub and no default scope. The worker's
  environment MUST NOT change.
- **FR-005**: The server MUST listen on loopback alone unless `--listen` says otherwise;
  the bridge listener MUST NOT be part of the development host's start, and the Compose
  override's two variables MUST point Infrahub's task workers at the orchestrator's
  platform API, so that the core's token never crosses the bridge. `SECURITY.md`'s threat
  model MUST follow.
- **FR-006**: Every `scope.*`, `stage.*`, `stages.*`, `rehearsal.*`, `schema.*` and
  `intent.*` rule the server made MUST leave the core, each kept by the orchestrator or
  the adapter where its rule moved whole, with its identifier, severity, exit, step and
  wording; `snapshot.flags.conflict` and the step's stage-shaped targets MUST go. The
  step's rule that a twin never steps to another scope or mapping MUST stay in the core,
  read from the two snapshots' envelopes, under `step.twin.unsteppable` naming both.
- **FR-007**: `twin.json` MUST move to `12`: the stage a twin was built from, the stage a
  step brought it to and the rehearsal block MUST go; the snapshot, the bundle, the scope
  and the mapping MUST stay. `twin show`'s kinds `none`, `snapshot`, `from_bundle` and
  `diverged` MUST stand, and its stage line MUST go. A record of `11` or earlier MUST be
  shown, naming its version, and destroyed, and MUST be refused a step as unsteppable
  naming `twin destroy` as the remedy.

**The worker**

- **FR-008**: The worker MUST serve three workflows, provision, step and destroy, under
  their fixed identities, and the seventeen activities; `fylgja-rehearse` MUST go with the
  rehearsal's reclaim, deadline and ceiling, which become the orchestrator's. Every
  remaining recorded history MUST replay against the workflows as changed; the rehearsal's
  histories MUST go with it.

**The API's shape for long operations**

- **FR-009**: `twin.create`, `twin.provision`, `twin.step` and `twin.destroy` MUST take an
  argument (its name the plan's) under which the answer ends at the run's identity instead
  of following it, and the run goes on. A refusal before the start MUST be the document, as
  today.
- **FR-010**: A new operation MUST read a run by its identity, answering its events so far
  and, once it has ended, its document, both built from the run's history so that the
  server keeps nothing between two requests; an identity no run has MUST be refused in
  words that name it. The interrupt MUST reach a run by its identity as well as by its
  stream, with the stream's meaning. The stream MUST stay for the core's own CLI, which
  MUST follow a run as it does today. Whether the API's version moves is the plan's: 019
  removed arguments without a move, pre-1.0, and this feature removes operations.

**The step between two snapshots**

- **FR-011**: The core MUST gain one operation that takes two snapshots, each a filed id or
  a file sent, compiles each on the goldens' code path and answers the step between them,
  nodes and links changed and artifacts moved, pure: it MUST touch no lab, start no run
  and file nothing but the snapshots and their bundles. Its name is the plan's. One
  snapshot against itself MUST answer `unchanged`, and a refused compile MUST answer the
  compile's own finding.

**The Infrahub adapter**

- **FR-012**: The orchestrator MUST hold one adapter for Infrahub, in Python on
  `infrahub-sdk`, a reader alone that never compiles: it MUST read a branch, a pinned
  branch or a stage, under a scope `tag:<name>` with `FYLGJA_DEFAULT_SCOPE` as its default,
  with probes from a file, else `FylgjaProbe` on the default branch, else none, and write a
  snapshot `2` file whose id is the one the Go reader files today, byte for byte, by the
  same mapping ([D-057](../../docs/decisions.md#d-057), `schema/README.md`), the same stage
  rules ([D-045](../../docs/decisions.md#d-045) to [D-048](../../docs/decisions.md#d-048))
  and the same stamps ([D-058](../../docs/decisions.md#d-058) to
  [D-060](../../docs/decisions.md#d-060)); it MUST list a proposed change's stages and
  what each resolves to; it MUST check a branch's schema against the mapping. Each rule and
  refusal MUST carry its identifier and wording over, and nothing MUST be added that the
  port does not need.
- **FR-013**: The adapter MUST read the platform packages' `platform.matches` from the
  shipped packages, with the same override directory, and MUST refuse a platform no
  package matches under `platform.unmatched`; a skew between the adapter's packages and the
  core's MUST be refused by the core when it takes the snapshot, never silently.
- **FR-014**: The adapter's environment MUST be `INFRAHUB_*` and the default scope; it
  MUST hold no node login and never the API's token.
- **FR-015**: An empty probe file, or one of JSON's whitespace alone, MUST declare no
  probes, as 016 defined it.
- **FR-016**: The Go reader (`internal/intent`, the moved halves of `internal/stages` and
  `internal/stage`, and the schema check) MUST leave the Go module only after the adapter
  files `0940db93…` from `fylgja-fixture` and each ported contract test's assertions pass
  against the adapter and have been compared with the Go reader's answers: the route MUST
  port, compare, then remove. `cmd/fylgja-fixture` MUST stay Go, a test tool that writes
  Infrahub through the test support package and links no reader.

**The orchestrator**

- **FR-017**: The orchestrator MUST be a Python project on Prefect, in this repository
  under one directory (its name the plan's), with its own toolchain, tests and lint, and
  MUST drive the core through the API alone, as a client under D-040's rule, never by
  starting a core workflow.
- **FR-018**: It MUST run these flows, each a flow and a deployment: a read (branch, pinned
  branch or stage, with probes) to a snapshot file through the adapter; a create from a
  branch or a stage, which reads then calls `twin.create`; a step to a stage, which reads
  then calls `twin.step`; the stage plan, which reads every stage, compiles each through
  `twin.compile` and asks the core for the step between each pair (FR-011); the rehearsal
  (FR-019); and the schema check, passed through. Each flow's refusals MUST keep 014's,
  015's, 016's and 017's identifiers and wording where the rule moved whole.
- **FR-019**: The rehearse flow MUST plan, reclaim a twin its own dead run left, create
  from the baseline, step and verify each later stage in order through the step's wait,
  stop at the first that fails, destroy whatever happened, compute each stage's verdict
  and the report, and post the report as one thread holding one comment on the proposed
  change, as the view shows one; a flow that times out or is cancelled MUST still destroy.
  Its deadline MUST be the flow's, derived from the stages' budgets as D-051 derived it;
  `rehearsal.steps.none` MUST judge as 015 defined it. The baseline rule (015 R-03) and the
  plan's compile-and-diff MUST be re-made in the orchestrator over the core's operations,
  not ported.
- **FR-020**: The orchestrator MUST ship one console script, `fylgja-cli`, noun-verb, whose
  commands are the ones the core's CLI loses: `intent read`, `stage list`, `stage plan`,
  `twin create --branch|--stage` with `--dry-run`, `twin step [--stage]`, `twin rehearse`
  (`--markdown` kept) and `schema check`, each running its flow and printing the same
  findings document the core's CLI printed, text or `--json`, and exiting by its status.
  Its `twin create --dry-run` MUST reach the core's dry run.
- **FR-021**: The orchestrator's state MUST be files and its platform's own: a directory of
  its own under its state root for every snapshot it takes, by id, never overwritten; and
  one record of the twin it last drove, the stage it created or stepped it to, that
  stage's snapshot id and the flow run that did it, read beside the core's `twin show` and
  trusted only while the two name one snapshot. `stage list`'s twin row, `twin step`'s
  default target (the next stage of its own), `stage.twin.moved` and the reclaim MUST read
  it; when it is distrusted, `twin step` MUST require a target and `stage list` MUST show
  no twin row and say why. No database of Fylgja's own.
- **FR-022**: The orchestrator's environment MUST be `INFRAHUB_*` and
  `FYLGJA_DEFAULT_SCOPE` for the adapter, `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN` for
  the core, and its platform's address; never a node login.
- **FR-023**: The `rehearsal`, `stages` and `plan` documents and the markdown report MUST
  move from the core's contracts to the orchestrator's unchanged but for `fylgja-cli` in
  place of `fylgja` in the reproduce lines, so that the checks and the report's readers see
  no other change. Their text and markdown renderers MUST be held to goldens captured from
  the Go implementation before it is removed, byte for byte but for that name.

**The checks**

- **FR-024**: `fylgja-step` and `fylgja-twin` MUST stay Python glue under
  `infrahub/checks/`, run by Infrahub's task workers on every proposed change; each MUST
  trigger its flow's deployment through the orchestrator's platform API on the host's
  Docker bridge, wait for the flow run, read its document and conclude from the status
  alone (D-052), with 015's conclusions and messages; `fylgja-twin` MUST post nothing and
  MUST skip a draft as today; the retry while the host is held (015 R-15) and the deadline
  margin MUST move into the glue. `fylgja-twin`'s `timeout` of 4260 MUST stand until the
  plan measures the flow's overhead. The checks MUST hold the orchestrator's credential and
  never the core's token.

**The decisions and the constitution**

- **FR-025**: The two decision entries, [D-065](../../docs/decisions.md#d-065) and
  [D-066](../../docs/decisions.md#d-066), appended at feature-open, MUST stand as written
  with each superseded entry's *Superseded* status line; the chain MUST write no entry for
  them. The constitution MUST be amended MAJOR citing both: I kept for the core and freed
  for the orchestrator, III binding the adapters, VIII and IX the core's, VI and X binding
  both, XI gaining the orchestrator as a client with "no command of the CLI runs the core
  in its own process" held for the core's CLI, the Development Workflow's "single Go
  module, one binary" the core's, and the Sync Impact Report written; the text is the
  plan's. `docs/architecture.md` MUST be searched for each superseded position.

**The repository, the host and the tiers**

- **FR-026**: CI's unit job MUST run the orchestrator's tests beside `go test`, and its
  lint job the Python linter beside golangci-lint and ShellCheck; the bring-up script MUST
  gain a part that installs the orchestrator's environment and its platform and starts the
  platform's server and worker detached as the three processes are, so the development
  host runs five; `make` MUST gain the orchestrator's targets.
- **FR-027**: Tier 1 MUST hold the Go tests less the removed packages' share, the boundary
  tests (FR-001), the long-operation shape's replay (FR-009, FR-010), the step between two
  snapshots on the goldens (FR-011), the record round-trips (FR-007), the worker's three
  workflows (FR-008) and the Python tests of the flows' pure parts, the verdict, the
  report, the deadline and the renderers against the captured goldens (FR-023); `make test`
  MUST stay inside its 65 s budget with the Python tests beside it.
- **FR-028**: Tier 2 MUST hold the adapter's contract tests, ported to Python from the Go
  reader's with each Go test's assertions carried over against the same fixture and
  throwaway `fylgja-test-*` branches, each run against the Go reader's answers before it is
  removed; the orchestrator's flows against the real Infrahub and a core server started
  with no Infrahub credential (a create from the fixture, a stage plan of a throwaway
  proposed change, a rehearsal refused before any run on a stale mark, and the composition
  `TestRehearseComposedByTheFixtureTool` exercises); and `TestChecksInsideInfrahub`
  reaching the orchestrator's platform on the bridge, skipping, saying why, where the task
  workers reach none. Nothing of the core's tiers MUST move that the split does not move.
- **FR-029**: Tier 3 MUST keep nine cases, `E2E-OK`: every command that names a branch, a
  stage or a rehearsal through `fylgja-cli`, case 3's dry run among them, and through
  `fylgja` for the rest; case 9's two rehearsals asked by `fylgja-twin` from inside
  Infrahub through the orchestrator and the core, the thread's table carrying `loss`; the
  credential greps extended to the orchestrator's logs and its platform's; the core's
  server log showing no request to Infrahub.

**The documents**

- **FR-030**: [api.md](../../contracts/api.md) (the operations lost, the long-operation
  shape, the step between two snapshots), [cli.md](../../contracts/cli.md) (the commands
  lost), a contract of the orchestrator's CLI and documents, the checks' contract moved
  from 015's to `contracts/`, `twin.schema.json` (`12`), `api.schema.json` and the frozen
  copies the older tests read MUST say what is now true; `.infrahub.yml` MUST be unchanged
  but for the checks' bodies, the template and its query untouched.
- **FR-031**: `docs/architecture.md` (§1, §2, §4.1, §4.4, §4.6, a section for the
  orchestrator, §5, §6) and the C4 model (redrawn with the orchestrator, its platform, the
  adapter and the checks' new reach, `make diagrams` run), `docs/glossary.md` (Core,
  Orchestrator, Adapter, Tool and Flow (orchestrator) added, the last told apart from
  016's Flow; Client, Server, Rehearsal, Stage and Check (Infrahub) reworded),
  `docs/development.md`, `SECURITY.md`, `README.md`'s walk-throughs, `CLAUDE.md`,
  `docs/verified-facts.md` (Prefect's facts) and `docs/brief.md` MUST say what is now true.
- **FR-032**: The route's first documents task MUST reconcile the roadmap: F-027's row
  with its description, its dependency on F-014 and its estimate, Release 0.3's total moved
  by the same figure, and item 5 linking to this feature; the production shape's "a
  direction, not a decision" line is the close's.

**What does not move**

- **FR-033**: CTM `2`, snapshot `2`, bundle `6`, the probe declaration `1`, the probe
  package `0.1`, PSP `0.7`, the mapping, the schema library's files, the template, the
  step's and verify's rules, the four goldens (`c70589c3…`, `10099944…`, `44ac283f…`,
  `5222063b…`) and the fixture's snapshot id (`0940db93…`) and compiled id (`c3872f5c…`)
  MUST NOT move; nothing on Infrahub's `main` and no fixture changes.

### Key Entities

- **Core**: the `fylgja` binary in its three roles. Builds, steps, destroys, shows and
  verifies a twin from a snapshot, compiles one, validates a package and answers the step
  between two snapshots. Knows no branch, proposed change, stage or source of truth; holds
  no Infrahub credential.
- **Orchestrator**: a project on its platform, in this repository. Owns the adapters, the
  stages and their resolution, the flows, the rehearsal and its report, its CLI and its
  state as files. A client of the core's API.
- **Adapter**: a tool of the orchestrator that reads one source of truth under a scope to
  a snapshot file, with probes. The Infrahub adapter is the first; F-025's NetBox adapter
  the second.
- **Flow (orchestrator)**: one of the orchestrator's runnable units, each a deployment:
  read, create, step, plan, rehearse, schema check. Told apart from a probe's flow (016).
- **Snapshot**: unchanged ([D-061](../../docs/decisions.md#d-061)); the core's one input,
  the adapter's one output, and the orchestrator's filed copy under its own directory.
- **Stage**: a moment of a proposed change ([D-045](../../docs/decisions.md#d-045)),
  resolved by the adapter to a snapshot by a pinned read where the source replays time,
  else the snapshot taken when it was marked ([D-066](../../docs/decisions.md#d-066)). The
  flows that consume stages take snapshot ids.
- **Run identity**: the workflow and run identifiers of a core run, under which a detached
  run is read and interrupted.
- **The step between two snapshots**: the pure answer of the core for two snapshots,
  nodes and links changed and artifacts moved; the plan's and the report's edges.
- **Twin record (`12`)**: the core's; names the snapshot, the bundle, the scope and the
  mapping, and no stage or rehearsal.
- **The orchestrator's record of the twin**: the stage it created or stepped the twin to,
  that stage's snapshot id and the flow run that did it; trusted while `twin show` names
  the same snapshot.
- **Report**: the rehearsal's document, text and markdown, as 015 and 016 shaped it,
  posted by the rehearse flow as a thread on the proposed change.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A ready proposed change is rehearsed on a twin and its report posted as a
  thread by the orchestrator, asked by `fylgja-twin` from inside Infrahub, while the core's
  server and worker run with no Infrahub credential and the core's server log shows no
  request to Infrahub: tier 3's case 9, `E2E-OK`.
- **SC-002**: The adapter's read of `fylgja-fixture` files snapshot `0940db93…` and a
  create from it is built from bundle `c3872f5c…`; the four goldens stand unchanged; every
  ported contract test passes in Python and matched the Go reader's answer before the Go
  reader went.
- **SC-003**: The five lost operations answer `404` as an operation the version has not,
  and the five lost arguments are refused as unknown, in 100% of tier-1 cases; no package
  the core's binary links reads Infrahub, and the Go module holds no reader.
- **SC-004**: The worker registers three workflows and seventeen activities; a `12` record
  round-trips; an `11` is shown and refused a step; every remaining recorded history
  replays.
- **SC-005**: A run started detached ends at its identity, and a read by identity replays
  its events and document from each of the recorded histories; the core's own CLI follows
  a run line for line as today.
- **SC-006**: The step between the three-node and three-node-probed goldens names the two
  hosts and their links; a stage plan's steps through `fylgja-cli` equal today's for the
  same proposed change.
- **SC-007**: The `stages`, `plan` and `rehearsal` documents' text and markdown from the
  orchestrator match the goldens captured from the Go implementation byte for byte but for
  `fylgja-cli` in the reproduce lines; each stage's verdict matches.
- **SC-008**: Tier 2 passes whole, `TestChecksInsideInfrahub` green through the
  orchestrator's platform on the bridge; tier 3 passes nine cases, `E2E-OK`; the credential
  greps over the orchestrator's logs and its platform's find nothing.
- **SC-009**: Tier 1 stays inside its 65 s budget with the Python tests beside it; CI's
  three jobs are green with the Python tests and linter in them.
- **SC-010**: The development host runs five processes after the bring-up script, and
  each Infrahub task worker reaches the orchestrator's platform on the bridge and the
  core's server not at all.
- **SC-011**: The constitution is MAJOR above 2.3.0 citing D-065 and D-066; `make
  linkcheck` is clean; the tracked documents name the rehearsal as a workflow, the server
  on the bridge or the reader in Go as current behaviour nowhere but the decision log's
  superseded entries, the archive and the release notes.

## Assumptions

- The brief's [Decided](brief.md#decided) list, settled with the operator on 2026-10-25
  and 2026-10-29, is not reopened here: two deployables; Temporal in the core;
  Constitution I kept for the core and freed for the orchestrator; the long-operation
  shape as start, identity, poll, with no callback; F-025 after this split as the second
  adapter in Python; D-001 superseded in NetBox's branching and a stage as a snapshot held
  where the source cannot replay time; Prefect; the Infrahub adapter rewritten in Python on
  `infrahub-sdk`; `fylgja-cli`; the report posted by the rehearse flow and the check
  triggering, waiting and concluding; the core on loopback and the bridge listener the
  orchestrator's platform's; the orchestrator in this repository; the documents' shapes the
  orchestrator's; the adapter a reader alone with the pure step the core's; one record of
  the twin driven; two decision entries and a MAJOR amendment; the estimate of 22–33 hours,
  re-made by the plan, which proposes a cut into two specs if its route runs past 017's.
- The brief's [Open](brief.md#open) section is empty: nothing is left for clarify.
- The plan decides what the brief [leaves to it](brief.md#left-to-the-plan): Prefect
  verified on the development host before the design (the open-source server's boundary,
  the version, whether Infrahub's embedded Prefect is a separate server to run beside, how
  a task worker's Python triggers a deployment and waits over plain HTTP on the bridge,
  what a flow reaching the core's API on loopback needs); the names and frames of the
  core's new operations and whether the API's version moves; the adapter's name, command
  shape, output and start-up line, which of the Go reader's checks it makes before it
  writes and which it leaves to the core, the snapshot id's canonical bytes in Python, the
  `infrahub-sdk` version, and how the Go tests' assertions are carried over and compared;
  `twin.json` `12`'s shape and how the step's rule reads the envelopes; the orchestrator's
  record's shape and place and how the reclaim reads it with the platform's run state;
  which live run captures the goldens and where the route places the capture; the
  rehearsal's deadline from the budgets without loading the packages, and `fylgja-twin`'s
  `timeout` against the flow's overhead; the orchestrator's layout, venv, linter and test
  runner, CI's jobs, the bring-up part, the `make` targets, and whether `scripts/e2e.sh`
  starts an orchestrator of its own; tier 2's new shape and wall time; the Constitution
  Check's amendment text per principle and its Sync Impact Report; which Infrahub skills to
  load (`infrahub-managing-checks` before the checks are touched, `infrahub-common`'s
  GraphQL references and `infrahub-managing-transforms`' union-fragment rule before the
  adapter's queries, each applied where this repository does not already decide otherwise;
  none designs a kind). Each is verified against the running system before it is relied on.
- Nothing on Infrahub's `main`, no fixture branch, no query, template or check definition
  moves; the checks' bodies change and are pushed and imported by the operator, as the
  route's `[operator]` task with its reason, before tier 2's `TestChecksInsideInfrahub` and
  tier 3's case 9. The review, the merge and the push are the operator's at the close.
- Recreating Infrahub's task workers with the changed override is a live session's of the
  attended loop, with no twin up and no tier running, followed by a read from inside each
  task worker that the orchestrator's platform answers on the bridge; a headless session
  never runs it.
- The 015 defect the release took with no spec goes with the parent workflow, by the
  author's reading, which the plan confirms or corrects.
- The explicit mutation of a node or a link, following brought back as a flow or by a
  webhook, the NetBox adapter and its stage store, a callback on the core's API, a list of
  runs, a fetch of a filed bundle or snapshot, a human gate, any Prefect feature the
  open-source server lacks, the remote hosts' runtime, the WebUI, the agent surface and a
  second orchestrator platform are out of this feature.
