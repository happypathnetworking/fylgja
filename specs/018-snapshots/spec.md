# Feature Specification: Snapshots, the core's one input

**Feature Branch**: `018-snapshots`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/018-snapshots GIT_BRANCH_NAME=018-snapshots. 0.3, the second of its four specs: snapshots, the core's one input, as docs/roadmap.md's F-024 and Release 0.3 section define it. Read specs/018-snapshots/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.3 is exploratory coding toward the production refactor
([roadmap](../../docs/roadmap.md#release-03)), and this is its second spec
([F-024](../../docs/roadmap.md#f-024)). Today two of the three live paths, `twin step` and
`twin rehearse`, already read the branch, compile and file on the server and hand the
worker a bundle id; the third, `twin create`, still reads the branch inside its provision
workflow. Until every workflow the core runs takes one input that is not a branch, the
production shape's core, which knows no branch, proposed change, stage or source of
truth, is a drawing. This feature makes that input real: **the snapshot**, one small
document wrapping an unchanged CTM `2`, which already carries each device's rendered
configuration and the read's provenance, beside an empty slot for the probe declarations
the third spec fills. Its id is a hash of its body without the read's `observed_at`, by
the rule the manifest already uses for the bundle id. It is stored by that id beside the
bundles, and it retires the bundle's CTM sidecar.

What the operator gets: `twin create --branch` and `--stage` work in one step as they do
now, but the server takes and files the snapshot and the worker never reads the branch;
the same intent taken twice has the same snapshot id, so a stage is addressed by a value
anyone can compare; a twin can be built from a snapshot id or file directly, and is then
frozen; `intent read --out` writes a snapshot and `twin compile --snapshot` compiles one,
`--ctm` retired; and every record that names a bundle id names the snapshot id beside it,
except the bundle, so bundle `5` and the three goldens do not move. The brief's
[Decided](brief.md#decided) list is settled and restated here only where a requirement
needs the sentence. The decision entry (D-061), the constitution's amendment of
Principle VI to 2.2.0, and every exact name and wording the brief leaves to the plan are
the plan's to write.

Four actors appear below. **The operator** runs the lab host and Fylgja, models intent in
Infrahub and marks stages. **A hand user** is an operator using the offline tools, `intent
read --out` and `twin compile`, against files. **The server**, `fylgja serve`, reads,
takes the snapshot, compiles, files both, and starts workflows. **The worker** runs the
workflows, which after this feature take a snapshot id and a bundle id and never a branch,
but for the reconcile workflow, which this feature leaves exactly as it is. Following's
removal (F-026), probes (016) and the NetBox reader (F-025) are the release's later specs
and are out of this one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A create the server takes a snapshot for (Priority: P1)

The operator runs `fylgja twin create --branch fylgja-fixture` exactly as before, or
`--stage <s>`. The server reads the branch, wraps the CTM in a snapshot, files it in the
snapshot store under its id, compiles it, files the bundle, and starts the provision
workflow with the snapshot id and the bundle id. The workflow begins at the host check;
it runs no read and no compile. A read or compile refusal is the server's answer before
any run starts, as it already is for a step. `twin show` names the snapshot beside the
bundle in its record line, and the twin record keeps it.

**Why this priority**: this is the seam the feature proves. Without it the core still
knows a branch, and nothing else here has a reason to exist.

**Independent Test**: on the fixture branch, `twin create --branch fylgja-fixture` boots
the three-node twin; `snapshots/<id>.json` exists under the state root and its body holds
the CTM the read produced; the bundle is `f764e1fa…` as before, with no
`<bundle_id>.ctm.json` beside it; the provision run's history holds no read and no
compile activity; and `twin show`'s record line reads `record: branch fylgja-fixture,
snapshot <id>, bundle_id f764e1fa…, …`.

**Acceptance Scenarios**:

1. **Given** the fixture branch and no twin, **When** the operator runs `twin create
   --branch fylgja-fixture`, **Then** the server files one snapshot and one bundle before
   the provision workflow starts, the workflow is started with both ids, and the twin
   boots as it did before this feature.
2. **Given** a stage on a proposed change, **When** the operator runs `twin create --stage
   <s>`, **Then** the server resolves the stage to its pinned read, takes that read's
   snapshot, and the twin is built from it; the record names the stage, the snapshot id
   and the bundle id.
3. **Given** a branch whose read is refused (a tagged device no package matches, say),
   **When** the operator runs `twin create`, **Then** the refusal is the server's answer,
   no workflow is started, and no snapshot and no bundle are filed.
4. **Given** a create's dry run, **When** the operator runs it, **Then** the answer names
   the snapshot id and the bundle id and the store paths each was filed at.
5. **Given** any build of this feature, **When** a create, a step or a rehearsal files a
   bundle, **Then** no CTM sidecar is written beside it, and sidecars already on disk are
   never read.
6. **Given** a twin built by `twin create --branch` with no `--at`, **When** time passes,
   **Then** it follows its branch exactly as before: the reconcile workflow reads the
   branch on its schedule and rebuilds on a changed bundle id, and a twin that rebuild
   made records `snapshot none`, since the reconcile workflow takes no snapshot.

---

### User Story 2 - The same intent has the same snapshot id (Priority: P1)

The operator, or a later spec, needs to say "this intent" by a value. A snapshot's id is
the hash of its body with the read's `observed_at` taken out, and nothing else taken out:
the branch, the `at`, the schema hash, the scope, the mapping with its version, the
fidelity list, every device's artifact and the empty probe list are all in it. So the
same stage resolved twice, or a branch read twice while nothing on it moved, gives one
id, and a changed artifact byte, fidelity row, schema or mapping gives another, as each
already moves the bundle id.

**Why this priority**: an id that moves with the clock addresses nothing. F-025 rests on
this: where the source of truth cannot replay time, the snapshot's id is what addresses
intent.

**Independent Test**: read the fixture branch twice, a few seconds apart, with no change
between; both snapshots have one id and differ only in `observed_at`. Change one byte of
one device's rendered configuration on a throwaway branch; the id moves. Resolve one
stage twice through the server; both takes have one id.

**Acceptance Scenarios**:

1. **Given** two CTMs identical but for `observed_at`, **When** each is wrapped, **Then**
   both snapshots have the same id.
2. **Given** a CTM and the same CTM with its lists reordered, **When** each is wrapped,
   **Then** both have the same id, since the body is normalised before it is hashed.
3. **Given** a snapshot, **When** one byte of one device's artifact changes, or one
   fidelity row is added or altered, **Then** the id changes.
4. **Given** a stored snapshot, **When** a test hashes the stored body with the inner
   `observed_at` removed, by its own code, **Then** it gets the stored id.
5. **Given** the fixture read twice through tier 2's existing reproducibility test,
   **When** both reads are wrapped, **Then** they have one snapshot id, beside the one
   bundle id the test already asserts.
6. **Given** one stage resolved twice through the server's path, **When** each take is
   filed, **Then** both have one id, the store keeps the first take's document unchanged,
   and the second filing writes nothing.

---

### User Story 3 - A twin from a snapshot, frozen (Priority: P2)

The operator holds a snapshot: an id the store keeps, from an earlier create, dry run or
`intent read --out`, or a file. `twin create --snapshot <id|file>` builds the twin from
it with no read of any branch. An id the store does not hold is refused; a file is sent
by the client and refused if the id it declares is not the id its body hashes to. Such a
twin is **frozen**: its reference is a document, which does not move, so it never
follows, whatever the envelope's `at` says, and asking for an interval with it is refused.
It has no stage, so it does not step. `twin show` says it is of what its envelope says,
pinned or frozen by the existing rules, with a note that it was built from the snapshot.

**Why this priority**: it is the core's input used directly, and what F-025's stages will
be. The one-step create (Story 1) is what the operator uses every day; this is what makes
the seam usable without a branch.

**Independent Test**: take the id from Story 1's create, destroy the twin, and run `twin
create --snapshot <id>`; the twin boots with the same bundle id, no read reaches
Infrahub, no follow Schedule exists, and `twin show`'s kind line reads `frozen; not
following` with the note `built from snapshot <id>`. Repeat with the snapshot written to
a file.

**Acceptance Scenarios**:

1. **Given** a snapshot id the store holds, **When** the operator runs `twin create
   --snapshot <id>`, **Then** the server compiles the stored snapshot, files the bundle,
   and starts the provision workflow with both ids; no request reaches the source of
   truth.
2. **Given** a snapshot id the store does not hold, **When** the operator runs `twin
   create --snapshot <id>`, **Then** it is refused by `snapshot.unknown`, naming the id,
   before any workflow starts.
3. **Given** a snapshot file whose declared `snapshot_id` its body does not hash to,
   **When** the operator creates from it, **Then** it is refused by
   `snapshot.id.mismatch`, naming both ids.
4. **Given** a snapshot file with no `snapshot_id`, **When** the operator creates from it,
   **Then** the server computes the id, files the snapshot under it, and builds the twin.
5. **Given** `--snapshot` with `--interval`, **When** the operator runs `twin create`,
   **Then** it is refused before any connection by `follow.flags.conflict`, saying "a twin
   built from a snapshot never follows"; with `--no-follow` it is accepted, redundant, as
   with `--at`.
6. **Given** a twin built from a snapshot whose envelope carries an `at`, **When** the
   operator runs `twin show`, **Then** the kind line reads `pinned at <T>; not following`
   with the note `built from snapshot <id>`, the record line reads `record: branch B at
   T, snapshot <id>, bundle_id …`, and the record's `source` says it was asked for by
   snapshot; with no `at`, the kind line reads `frozen; not following` with the same
   note. No Schedule is made in either case.
7. **Given** a twin built from a snapshot, **When** the operator runs `twin step --stage
   <s>`, **Then** it is refused by the existing guard that only a twin built from a stage
   steps.
8. **Given** two takes of one stage filed under one id, **When** the operator creates
   from that id, **Then** the twin records the first take's `observed_at`, the stored
   document's.

---

### User Story 4 - The hand tools read and write snapshots (Priority: P2)

A hand user runs `fylgja intent read --out snap.json`, which writes a snapshot, not a bare
CTM, and files it, so a hand read and a create of the same intent share one stored
document; the summary line says so. `fylgja twin compile --snapshot snap.json --out
bundle/` compiles it and writes the bundle, filing nothing, as `--ctm` files nothing
today. **`--ctm` is retired**: a hand user with a bare CTM wraps it in the outer fields,
leaving out `snapshot_id`, which the server computes. The repository ships the three
fixture CTMs wrapped, under `testdata/snapshot/`, so the README's offline example
compiles one.

**Why this priority**: the one-input claim has to hold in the hand tools too, and the
README's walk-through is how a new reader meets the compiler.

**Independent Test**: `twin compile --snapshot testdata/snapshot/three-node.json --out
<dir>` writes the bundle whose id is the three-node golden, `43d91715…`, and the state
root's snapshot store gains nothing; `twin compile --ctm …` is refused as an unknown
flag; `intent read --branch fylgja-fixture --out <file>` writes a snapshot file whose id
the store also holds.

**Acceptance Scenarios**:

1. **Given** each of the three wrapped fixtures, **When** a hand user compiles it with
   `twin compile --snapshot`, **Then** the bundle is byte-identical to the golden its CTM
   compiles to today: `43d91715…`, `4213b3cf…` and `ecb665f5…`.
2. **Given** `intent read --out <file>` on the fixture branch, **When** it completes,
   **Then** the file is a snapshot of version `1`, the store holds the same document under
   the same id, and the summary line names the snapshot id beside what it names today.
3. **Given** a hand-wrapped CTM with no `snapshot_id`, **When** a hand user compiles it,
   **Then** it compiles, and nothing is filed.
4. **Given** `twin compile --ctm <file>`, **When** a hand user runs it, **Then** it is
   refused before any connection as an unknown flag, and the help text names
   `--snapshot`.
5. **Given** tier 3's read-then-compile helper, **When** tier 3 runs, **Then** it reads
   with `intent read --out` and compiles with `--snapshot`, and its case passes as
   before.

---

### User Story 5 - Stages, steps and rehearsals name the snapshot (Priority: P2)

Wherever a record names a bundle id, it names the snapshot id beside it. `stage plan`
names each compiled stage's snapshot id beside its bundle id; `stage list`, which neither
reads nor compiles, does not. `twin step --stage <s>` keeps its one input and its guard;
the server takes the stage's snapshot and starts the step workflow with the snapshot id
and the bundle id, and the step record names one snapshot on each side. A rehearsal
takes every stage's snapshot in its plan, up front, as it already compiles every stage up
front, so a refused stage is found before the first boot. The rehearsal's per-stage rows
carry the snapshot id, and the report posted on the proposed change gains a `snapshot`
column before `bundle`, in the same eight-character short form, within the comment's
existing size limit. The rule that a step to an identical bundle is a step to nowhere
(`rehearsal.steps.none`) still judges by bundle equality.

**Why this priority**: the seam has to reach every workflow, and the reader of a report
should see why two stages are the same twin.

**Independent Test**: on a throwaway branch with two stages, `stage plan` names two
snapshot ids beside two bundle ids; a rehearsal's report shows the `snapshot` column; and
`internal/stages` and `internal/checks` pass in tier 2 with the id in their rows.

**Acceptance Scenarios**:

1. **Given** a proposed change with two stages, **When** the operator runs `stage plan`,
   **Then** each compiled stage names its snapshot id beside its bundle id, and both
   snapshots are filed.
2. **Given** a twin built from stage A, **When** the operator runs `twin step --stage B`,
   **Then** the step workflow is started with B's snapshot id and bundle id, and the
   record's step block names A's snapshot on one side and B's on the other.
3. **Given** a rehearsal whose third stage's read is refused, **When** it starts, **Then**
   the refusal is found while the plan takes every stage's snapshot, before the first
   twin boots.
4. **Given** a rehearsed proposed change, **When** its report is posted, **Then** its
   table has a `snapshot` column before `bundle`, each cell eight characters, and the
   comment stays within the existing limit.
5. **Given** two adjacent stages with one bundle id, **When** a rehearsal plans them,
   **Then** `rehearsal.steps.none` judges as before, and the two rows show why: their
   snapshot ids.

---

### User Story 6 - The records true (Priority: P3)

The twin record moves from `twin.json` `8` to `9`, naming its snapshot id and one on each
side of a step; a twin `twin provision <bundle-dir>` built, and one a following rebuild
made, names none, and `twin show` prints `snapshot none` rather than inventing one. The
snapshot's schema is in `contracts/` at version `1`, its `$id` under this repository's
URL. The five records that name a bundle id (`twin.json`, `show`, `stages`, `step`,
`rehearsal`) gain the snapshot id, and their earlier formats still load from frozen
copies. The decision entry D-061 records the snapshot as the core's one input, and
Constitution VI is amended to 2.2.0 citing it, with its sentence for F-025: where the
source of truth cannot replay time, the snapshot's id addresses intent. The CLI and API
contracts, the README, the architecture, the glossary, the C4 model, the development
notes and `CLAUDE.md` say what is now true, and `CLAUDE.md` records the snapshot id the
live fixture reads to.

**Why this priority**: none of it changes what a twin does, and all of it is how the next
spec and the next reader find out what this one built.

**Independent Test**: grep the tracked documents for the CTM sidecar, `twin compile
--ctm` and the provision workflow's read; nothing describes them as current. Load each
frozen record of the earlier formats; each loads.

**Acceptance Scenarios**:

1. **Given** a twin record of `8` or earlier, **When** `twin show` reads it, **Then** it
   loads, and the record line says it names no snapshot, naming the record's version.
2. **Given** a twin built by `twin provision <bundle-dir>`, **When** the operator runs
   `twin show`, **Then** the kind is `from a bundle`, as today, and the record line reads
   `snapshot none`.
3. **Given** the constitution, **When** the plan's Constitution Check runs, **Then** it
   reads 2.2.0, whose Principle VI says every CTM, snapshot and bundle records its
   provenance and that `observed_at` appears neither in the bundle nor in the bytes a
   snapshot's id hashes.
4. **Given** the API at version `1`, **When** a client of an earlier build sends a create
   with `--branch`, **Then** it is answered as before; the snapshot arguments and answers
   are additive.

---

### Edge Cases

- **A snapshot whose inner CTM fails CTM 2's validation** (a CTM `1`, a missing field):
  refused before any compile, naming the CTM's fault, by the rule the plan names (the
  CTM's own or `snapshot.invalid`).
- **A snapshot of another version, or declaring none**: refused by
  `snapshot.version.unsupported`, naming the version read and the one this build takes.
- **A version-1 snapshot with a non-empty `probes` list**, or with `probes` missing:
  refused by `snapshot.invalid`; in version 1 the list is required and empty.
- **Two snapshots differing only in `observed_at`**: one id; `snapshot.id.mismatch` is
  never raised for a differing `observed_at`, only for a declared id the body does not
  hash to.
- **The same stage taken twice**: one stored document, the first take's; the second
  filing writes nothing, and its own `observed_at` is not kept.
- **A stage resolved after its branch was rebased**: reads differently or empty and gets
  a different id. Correct, documented as a limit, and tested by nothing: a snapshot id is
  reproducible only while the branch's history is.
- **An artifact Infrahub re-renders to different bytes for unchanged data**: never seen;
  the id would move with it. Documented, not tested.
- **`--snapshot` beside `--branch`, `--stage`, `--at` or `--scope`**: refused before any
  connection, naming the conflicting flag, as `--stage` beside `--branch` is refused today.
- **`--snapshot <arg>` that is neither a readable file nor an id of the store's form**:
  refused by the client before any connection, naming the argument.
- **Bundle sidecars from earlier builds on disk**: left where they are and never read.
- **A following twin's rebuild**: unchanged; reads through `bundles/.reads/`, compares
  bundle ids, and its record says `snapshot none`.
- **A snapshot whose platform no package on the server matches**: the compile's existing
  refusal, before any workflow starts.
- **Infrahub unreachable or slow during a create's read**: the create fails within the
  read bound with the read's existing refusal, no workflow starts and nothing is filed;
  the worker no longer retries the read for create.

## Requirements *(mandatory)*

### Functional Requirements

**The snapshot**

- **FR-001**: A snapshot MUST be one JSON document of version `1` with an outer part
  (`snapshot_version`, `snapshot_id`, `observed_at`) and a body (`ctm`, one CTM `2` valid
  under its own contract and unchanged by this feature; `probes`, a list, required and
  empty in version 1).
- **FR-002**: The snapshot id MUST be a content hash of the canonical, normalised body
  with the inner CTM's `observed_at` removed, and of nothing else removed; the outer
  part's fields are not hashed. The algorithm and length follow the bundle id's unless the
  plan finds a reason to differ.
- **FR-003**: Validation MUST check the outer fields, then the inner CTM under CTM 2's
  own validation, and MUST refuse by `snapshot.invalid`, `snapshot.version.unsupported`
  or `snapshot.id.mismatch` as the bundle's three rules refuse a bundle; an id the store
  does not hold MUST be refused by `snapshot.unknown`.
- **FR-004**: `contracts/snapshot.schema.json` MUST describe version `1`, with its `$id`
  under this repository's URL ([D-055](../../docs/decisions.md#d-055)), and MUST say in
  one sentence that the bytes the id hashes differ from the stored bytes.
- **FR-005**: A snapshot file a client sends MAY omit `snapshot_id`; the server MUST
  compute it when absent and check it when present.

**The store**

- **FR-006**: Snapshots MUST be filed by id under the state root's `snapshots/`, beside
  `bundles/`, behind the same small interface as the bundle store (so object storage can
  replace the directory, [D-014](../../docs/decisions.md#d-014)), and kept for ever, as
  bundles are.
- **FR-007**: Filing an id the store already holds MUST keep the stored document and
  write nothing.
- **FR-008**: A build MUST NOT write the bundle's CTM sidecar or read one;
  `bundles/.reads/` MUST stay, for the reconcile workflow alone.

**The server takes the snapshot**

- **FR-009**: For `twin create --branch` and `--stage`, the server MUST read, take the
  snapshot, file it, compile it, file the bundle, and start the provision workflow with
  the snapshot id and the bundle id; the workflow MUST begin at the host check and run no
  read and no compile.
- **FR-010**: The server's read for a create MUST be bounded by the same read bound as
  its reads for dry runs, step and rehearse; a read or compile refusal MUST be answered
  before any workflow starts; the server MUST file nothing for a refused read, and a compile
  refused after a clean read MUST leave the snapshot filed and name it in the answer, since
  the input validated and only the output was refused. The read
  activity's retries and heartbeat are given up for create, as they were for step and
  rehearse: a source of truth that fails or times out during the read fails the create at
  once, and the operator runs it again.
- **FR-011**: For `twin step --stage`, the server MUST take the stage's snapshot and
  start the step workflow with the snapshot id and the bundle id; `--stage` stays step's
  one input and `step.twin.unsteppable` its guard.
- **FR-012**: A rehearsal MUST take every stage's snapshot in its plan, before the first
  boot, and file each.
- **FR-013**: The reconcile workflow MUST be left as it is: it reads the branch on its
  schedule, compiles in the worker, reads `bundles/.reads/`, compares bundle ids, and
  takes no snapshot.
- **FR-014**: A dry run and a plan MUST file their snapshots and bundles; the dry run
  MUST print each id with its store path, and the plan each compiled stage's snapshot id
  above its bundle id, as it prints the bundle id alone today. There is no fetch of a
  snapshot by id over the API, as there is none for a bundle.

**The snapshot as a direct input**

- **FR-015**: `twin create --snapshot <id|file>` MUST build a twin from the snapshot: an
  id looked up in the store, a file read by the client and sent; a file's snapshot MUST be
  filed under its id. The create MUST NOT send any request to the source of truth.
- **FR-016**: A twin built from a snapshot MUST never follow: `--interval` with
  `--snapshot` MUST be refused before any connection by `follow.flags.conflict`, saying "a
  twin built from a snapshot never follows"; `--no-follow` MUST be accepted; a Schedule
  MUST NOT be made whatever the envelope's `at` says.
- **FR-017**: `twin show` MUST describe a `--snapshot` twin by its envelope, by the
  existing rules (`pinned at T; not following` with an `at`, `frozen; not following`
  without), with the note `built from snapshot <id>`; the record's `source` MUST say it was
  asked for by snapshot. `from a bundle` MUST stay the one kind for a twin with no
  envelope.
- **FR-018**: `--snapshot` beside `--branch`, `--stage`, `--at` or `--scope` MUST be refused
  before any connection, naming the first conflicting flag found in that order, since a
  snapshot carries its own branch, `at` and scope.
- **FR-019**: `twin compile --snapshot <file>` MUST compile the snapshot's CTM on the
  golden tests' code path and write the bundle, filing nothing and needing no state root;
  `twin compile --ctm` MUST be retired.
- **FR-020**: `intent read --out <file>` MUST write a snapshot, file it, and name its id
  in the summary line.
- **FR-021**: `testdata/snapshot/` MUST hold the three fixture CTMs wrapped, each compiling
  to its golden.

**The records**

- **FR-022**: Every record that names a bundle id MUST name the snapshot id beside it,
  except the bundle: `twin.json` (to version `9`, one on each side of a step block),
  `twin show` (`record: <ref>, snapshot <id>, bundle_id <id>, …`), `stage plan` per
  compiled stage, the step record, and the rehearsal's per-stage rows.
- **FR-023**: A twin with no snapshot (built by `twin provision <bundle-dir>`, or by a
  following rebuild) MUST record none, and `twin show` MUST print `snapshot none`; a
  record of `8` or earlier MUST load and say it names no snapshot.
- **FR-024**: The rehearsal report's table MUST gain a `snapshot` column before `bundle`,
  in the eight-character short form, inside the existing comment size guard;
  `rehearsal.steps.none` MUST still judge by bundle equality.
- **FR-025**: The records that move (`twin.json`, `show`, `stages`, `step`, `rehearsal`)
  MUST keep frozen copies of their earlier formats under their packages'
  `testdata/contracts/`, each still loading.
- **FR-026**: Bundle `5`, the manifest, CTM `2`, the compiler and the three goldens MUST
  NOT change.

**The contracts and documents**

- **FR-027**: `contracts/cli.md` MUST gain an F-024 section (the one-step create kept,
  `--snapshot` on create and compile, `intent read` writing a snapshot, the client's rules
  for a snapshot file, `--ctm` retired), and `contracts/api.md` the additive arguments and
  answers under API version `1`.
- **FR-028**: One decision entry, D-061, MUST record the snapshot as the core's one input,
  with the wrap, the hash rule, the store and the retired sidecar; Constitution VI MUST be
  amended to 2.2.0 citing it, adding the snapshot to the provenance sentence, keeping
  `observed_at` out of the bytes a snapshot's id hashes, and adding the sentence that where
  the source of truth cannot replay time the snapshot's id addresses intent and a stage
  there is the snapshot Fylgja took when the operator marked it.
- **FR-029**: The glossary, `docs/architecture.md` §4.2–§4.6, the C4 model (redrawn with
  `make diagrams`), `docs/development.md`, the README's walk-through, the roadmap and
  `CLAUDE.md`'s Formats and State MUST say what is now true; the rebase and re-render
  limits MUST be stated in the records.

### Key Entities

- **Snapshot**: the core's one input. An outer part (version, id, the take's
  `observed_at`) around a body: one CTM `2`, unchanged, and a probe list, empty in
  version 1. One snapshot compiles to one bundle under one compiler, one PSP set and one
  build.
- **Snapshot id**: the content hash of the body without the inner `observed_at`. Equal for
  the same intent however and whenever it was read, while the branch's history stands.
- **Snapshot store**: `snapshots/<snapshot_id>.json` under the state root, beside the
  bundle store, behind the same small interface; never overwritten, kept for ever.
- **Bundle**: unchanged, the output; its CTM sidecar retired.
- **Twin record** (`twin.json` `9`): names its snapshot id, or none, beside its bundle id,
  and one on each side of a step.
- **Stage**: unchanged ([D-045](../../docs/decisions.md#d-045)), the operator's mark,
  resolved to a pinned read; the snapshot is what that read produces.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every workflow the core runs but reconcile takes a snapshot id and a bundle
  id and no branch: the provision, step and rehearsal runs' histories hold no read and no
  compile activity.
- **SC-002**: The same intent read twice, and the same stage resolved twice, give one
  snapshot id in 100% of tier-2 runs; a changed artifact byte or fidelity row moves it in
  100% of tier-1 cases.
- **SC-003**: The three goldens stand unchanged, `43d91715…`, `4213b3cf…` and
  `ecb665f5…`, each compiled from its wrapped snapshot; the live fixture still compiles
  to `f764e1fa…`, and `CLAUDE.md` records the snapshot id it reads to.
- **SC-004**: A twin can be rebuilt from a snapshot id alone with no request reaching
  Infrahub, and it never follows.
- **SC-005**: Each of FR-022's five records names a snapshot id or says it has none; no
  record invents one.
- **SC-006**: Tier 3's nine cases pass as they are, with no case added, `twin show`'s
  record line naming a snapshot id beside the bundle id and case 5's rebuilt twin reading
  `snapshot none`; tier 2's `internal/stages` and `internal/checks` pass with the id in
  their rows.
- **SC-007**: The earlier formats of the five moved records still load from their frozen
  copies.
- **SC-008**: Tier 1 stays under its 45 s budget, uncached.

## Assumptions

- Nothing on Infrahub's `main`, no fixture branch, no query, template or check, and no
  golden moves; no Infrahub skill applies, since nothing is designed in Infrahub.
- Infrahub replays time, so the new sentence of Principle VI binds nothing in this
  feature; it is written for F-025 to inherit.
- The plan decides what the brief [leaves to it](brief.md#left-to-the-plan): the id's
  algorithm, the outer fields' exact names and whether the outer `observed_at` copies the
  inner one, the record's `source` values and the stale comment on `intent`, whether the
  two stores share one interface or two of one shape, where the tier-2 cases live, the
  frozen copies, `intent read`'s summary wording, where the ids and paths go in the
  findings document, how the client tells an id from a file, the rule for `--snapshot`
  beside another reference, the rule for an invalid inner CTM, D-061's and VI's text, the
  glossary entries and the C4 redraw. Each is verified before it is relied on.
- The rebase limit and the re-render limit are documented, not tested.
- The API stays at version `1`: the additions are additive and pre-1.0, as at 014, 015 and
  017.
- Following, `--interval`, `--no-follow`, the reconcile workflow, `ReadIntent` and
  `bundles/.reads/` stay as they are until F-026, which follows this feature and comes
  before 016; `twin step --snapshot` arrives there.
- `twin verify`'s block keeps naming the bundle alone (`verify.twin.bundle_id`): it is a
  document, not one of FR-022's records, and moves with the kind line at F-026.
- The API's shape for long operations, the split into core, reader and orchestrator,
  probes and the NetBox reader are out of this feature.
