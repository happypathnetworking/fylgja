# Feature Specification: A proposed change's stages

**Feature Branch**: `014-proposed-change-stages`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/014-proposed-change-stages. 0.2, the first of its three specs: a proposed change's stages in place of waypoints, as docs/roadmap.md's F-023 and Release 0.2 section define it. Read specs/014-proposed-change-stages/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.2 rehearses a proposed change on a twin before it merges, and everything it
rehearses is a stage. This feature, the release's first of three, replaces the waypoint
with the **stage**: a moment of a proposed change, Infrahub's own unit of change. The
operator opens a proposed change on the branch they are building, draft or not, marks the
moments between its branch point and its head as `FylgjaStage` objects related to it, and
Fylgja reads them: `stage plan` compiles every stage and shows the step between each
pair, `twin create --stage` boots a twin at one, and `twin step` walks the twin through
them. The branch point and the head are derived, so a proposed change with nothing marked
already has two stages. Waypoints, their commands, their contract and their kind are
removed. Its decision is [D-045](../../docs/decisions.md#d-045), which supersedes
[D-032](../../docs/decisions.md#d-032); its settled points are the brief's
[Decided](brief.md#decided) list and its verified behaviour is
[research.md](research.md), both restated here only where a requirement needs the
sentence. The contract stays `0.2`; the twin record, the API and the CLI move.

Two actors appear below. **The operator** edits intent in Infrahub, opens the proposed
change and marks its stages there, by Infrahub's own means, and runs Fylgja's commands
from a client. **Fylgja** reads intent, proposed changes and stages from Infrahub and
writes nothing there (Constitution III). The **rehearsal**, which creates, steps and
verifies a twin through a proposed change's stages from inside Infrahub's checks, is the
next feature's (`015-proposed-change-rehearsal`) and reads what this one builds.

## Clarifications

### Session 2026-10-16

- Q: How is a stage named on the command line, given that the two derived stages have no label? → A: `<branch>/<label>`, with two reserved labels for the ends, `branch-point` and `head`; a mark carrying a reserved label is refused, naming it. No naming by position.
- Q: What does Fylgja do with a proposed change that is merged, closed or canceled? → A: Open and draft proposed changes alone are visible: their stages are listed, planned and created from. A merged, closed or canceled one is invisible to Fylgja, and a reference naming its branch is refused as unknown. A twin built from a stage of a proposed change that has since closed keeps its record, and `stage list` warns that the record's stage is gone.
- Q: Where does the staleness check refuse? → A: At `resolve`, on every command that resolves a stage: `stage plan`, `twin create --stage`, `twin step` and `intent read --stage`. No run starts from a stale stage.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The operator marks a proposed change's stages and plans them (Priority: P1)

The operator is building a change on a branch, say a third link between two devices, and
wants to tell it as a story: the fabric before the change, after the link is cabled, after
its configuration is live. They open a proposed change on the branch in Infrahub, as a
draft while they work, and after each moment's writes have landed and its artifacts have
been regenerated they mark the moment: a `FylgjaStage` related to the proposed change,
with a label of their choice and, if they want an instant other than the moment of the
mark, an `as_of`. Then `stage plan`, naming the proposed change by its source branch,
reads and compiles every stage of the proposed change, the branch point first, their marks
in order of time, the head last, and shows what each step between two consecutive stages
changes: nodes, links, bootstraps and artifacts, by name and checksum, never a line of
content. It needs no lab, no worker and no workflow service. A stage that cannot be built
is refused with a reason the operator can act on, and the plan goes on to the others.

**Why this priority**: the plan is how every stage is proved before any twin is booted,
and the surface the rehearsal reads. Without it nothing else in the release has a stage
to rehearse.

**Independent Test**: on a throwaway branch with a draft proposed change and two marked
stages, `stage plan` lists four stages in order with their `at` and where each `at` came
from, a bundle identifier and the read's counts for each stage that compiled (the branch
point compiles only where `main` carries the contract and intent, which the development
host's does not: there it is refused `contract.node.missing` and its step is not
computed), and three steps, the one into the second mark adding one link and changing
two nodes' artifacts; a stage marked before its regenerate is
refused as stale, naming the device; the plan exits non-zero for a refusal and zero
otherwise.

**Acceptance Scenarios**:

1. **Given** a proposed change on branch `b` with nothing marked, **When** the operator
   runs `stage plan` for `b`, **Then** the plan lists two stages, the branch point (`main`
   pinned at the branch's `branched_from`) and the head (the branch pinned one
   microsecond after the later of its latest stamp and its latest intent event), each
   resolved and planned, compiled where `main`
   carries the contract and intent, and one step between them, not computed when either
   end was refused.
2. **Given** two stages marked on the proposed change, the first with no `as_of` and the
   second with one, **When** the operator runs `stage plan`, **Then** four stages are
   listed, the branch point, the two marks in order of their `at`, then the head, with
   three steps; each mark's `at` is the written `as_of` or the mark's own write stamp,
   and the plan says which.
3. **Given** a stage marked after an intent change and before the artifacts were
   regenerated, **When** the operator runs `stage plan`, **Then** that stage is refused
   as stale, the finding names each device whose intent is newer than its artifact and
   says to regenerate, by a generate or by the proposed change's run-check, and mark
   again; the other stages are still planned, and the steps touching the refused stage
   say they were not computed.
4. **Given** a stage whose `as_of` is before the branch point or later than now,
   **When** the operator runs `stage plan`, **Then** that stage is refused, saying which.
5. **Given** the branch was rebased after two stages were marked, **When** the operator
   runs `stage plan`, **Then** both marks are refused at once, the refusal says a rebase
   moved the branch point past them, and the branch point and the head are still planned.
6. **Given** `main` has been written since the branch was created, **When** the operator
   runs `stage plan`, **Then** a warning says `main` has moved since the branch point,
   and nothing is refused for it.
7. **Given** the stage kind is not loaded on the default branch, **When** the operator
   runs any stage command or passes `--stage`, **Then** the command is refused naming
   the schema file to load, and `schema check` reports whether the default branch has the
   kind.

---

### User Story 2 - A twin from a stage, stepped through its proposed change (Priority: P1)

The operator builds a twin at one stage of a proposed change, `twin create --stage`, and
walks it: `twin step` with no target takes the twin to the next stage of its own proposed
change, `--stage` takes it to any stage of it, forward or back, and the step changes only
what differs, as M11's step does. The twin is pinned at the stage's instant and never
follows. `twin show`, `twin verify` and the twin's record name the stage the twin is at.
A twin steps only within its own proposed change: a stage of another is refused.

**Why this priority**: this is the release's story told on a running twin, and the
rehearsal is this sequence run by a check.

**Independent Test**: on a throwaway branch with a proposed change and two marks, `twin
create --stage` from the first mark deploys the bundle the plan printed for it and records
the stage; `twin step` goes to the second mark and the twin verifies against it; `twin
step --stage` back to the first; a step to the head from there; a step to a stage of
another proposed change is refused; `twin destroy` leaves nothing.

**Acceptance Scenarios**:

1. **Given** the plan printed a bundle identifier for a stage, **When** the operator
   creates a twin from that stage, **Then** the twin deploys that identifier, is pinned at
   the stage's `at`, does not follow, and its record names the proposed change, the stage
   and where its `at` came from.
2. **Given** a twin at a marked stage, **When** the operator runs `twin step` with no
   target, **Then** the twin steps to the next stage of its proposed change, which is the
   head when no mark follows; at the head with no later stage, the step is refused saying
   there is none.
3. **Given** a twin at the head, **When** the operator runs `twin step --stage` naming an
   earlier mark, **Then** the twin steps back to it, the replace push taking off each
   node what the earlier stage lacks.
4. **Given** a twin at one proposed change's stage, **When** the operator names a stage of
   another proposed change, **Then** the step is refused as foreign, before anything on
   the host is touched.
5. **Given** a twin created from the branch point, **When** the operator steps to the
   head, **Then** the step goes straight there, warning that marked stages were skipped
   when any lie between.
6. **Given** a twin at the head, and the branch has been written since, **When** the
   operator steps to the head again, **Then** the step goes to the new head, since its
   reference differs from the record's, and `stage list` had warned that the record's
   stage had moved.
7. **Given** a twin built from a stage, **When** the operator runs `twin create
   --branch main --at <instant>` after destroying it, **Then** a story along `main`'s own
   history still works as before, with no stage named: a proposed change cannot have
   `main` as its source, so `main` has no stages.
8. **Given** a stage marked before its regenerate, **When** the operator creates a twin
   from it or steps to it, **Then** the command is refused as stale at resolution, before
   any run starts, with the same finding `stage plan` gives.

---

### User Story 3 - The operator lists stages and sees where the twin is (Priority: P2)

`stage list` shows the stages Fylgja can see, each resolved to its branch and `at`, and
marks the one the running twin was built from. When that stage no longer resolves to what
the record holds, because its `as_of` was edited, it was deleted, the head moved, or the
branch was rebased, the list warns beside it, and the twin stays what it was built from.

**Why this priority**: the list is the operator's and the rehearsal's view of a proposed
change's stages without compiling anything; the plan and the twin work without it.

**Independent Test**: with a twin at a mark, `stage list` for the branch shows the four
stages with the twin's mark flagged and no warning; after the mark's `as_of` is edited,
the list warns that the twin's stage has moved; after the proposed change is closed, the
list no longer shows its stages and warns that the twin's stage is gone.

**Acceptance Scenarios**:

1. **Given** a proposed change with two marks and no twin, **When** the operator runs
   `stage list` for its branch, **Then** four stages are listed in order with branch,
   `at`, where the `at` came from and the label or description, and no twin is marked.
2. **Given** a twin at the second mark, **When** the operator runs `stage list`, **Then**
   that row is marked as the twin's, with the record's state (ready or diverged, and the
   target it diverged towards).
3. **Given** a stage its proposed change no longer names (removed from its
   `fylgja_stages`; [D-047](../../docs/decisions.md#d-047)), **When** the operator runs
   `stage list`, **Then** the orphan is reported as a finding naming it, nothing crashes,
   and it is planned and created from by nothing.
4. **Given** a proposed change that was merged, closed or canceled, **When** the operator
   runs `stage list` for its branch, **Then** its stages are not listed, and `stage plan`
   or `--stage` naming it is refused as unknown, saying no open proposed change has that
   source branch.
5. **Given** a mark whose label is `head` or `branch-point`, **When** the operator runs
   `stage list` or `stage plan`, **Then** the mark is refused naming the reserved label,
   and the derived stage of that name is still the derived one.

---

### User Story 4 - A stage as an intent reference everywhere (Priority: P2)

Wherever a command took `--waypoint`, it takes `--stage`: `twin create`, `twin step` and
`intent read`. `--stage` resolves to a pinned `(branch, at)` before any run starts and
before any branch is read, and the run is then the pinned run M3 built, unchanged. The
stage's name enters neither the CTM nor the bundle, so the same intent hashes the same
however it was named.

**Why this priority**: it makes the stage a first-class reference beside `--branch` and
`--branch --at`, which the rehearsal and the operator's hand use alike.

**Independent Test**: `intent read --stage` writes the same CTM, but for `observed_at`,
as `intent read --branch b --at <the stage's at>`; `twin create --stage` beside `--branch`,
`--at` or `--interval` is refused as a flag conflict; a malformed stage reference is
refused before anything is read.

**Acceptance Scenarios**:

1. **Given** a stage, **When** the operator runs `intent read --stage` with it, **Then**
   the resolved reference is printed first, the CTM read at its `at` follows, and the CTM
   carries the branch and `at` and no stage name.
2. **Given** `--stage` and `--branch` together, **When** the command starts, **Then** it
   is refused as a flag conflict naming the first conflicting flag, with no request to
   Infrahub.
3. **Given** a stage reference naming no proposed change, or no stage of it, **When** any
   command resolves it, **Then** it is refused naming what exists, before any branch is
   read.

---

### User Story 5 - Waypoints are gone and the records say so (Priority: P3)

Fylgja is 0.x and keeps one way to name a pinned reference. `FylgjaWaypoint` is removed
from the schema this repository ships and from the development host's `main`; `waypoint
list`, `waypoint plan` and `--waypoint` are gone, with their rules and their contract; the
fixture tool and test support make proposed changes and stages where they made series;
tier 3's stepping cases and the README's stepping walk-through run on stages; and the
decision log, the architecture and its diagrams, the glossary, the schema README, the
contracts, `docs/verified-facts.md`, `docs/development.md`, `docs/ideas.md` and
`CLAUDE.md` describe stages where they described waypoints.

**Why this priority**: it is the clean-up the first four stories leave, and the records a
stranger reads must describe what runs.

**Independent Test**: after the contract tier the default branch has no `FylgjaWaypoint`
kind and `FylgjaStage { count }` reads 0; `fylgja --help` names no waypoint command and
no `--waypoint`; the repository holds no `fylgja-waypoint.yaml`, `waypoints.schema.json`
or `waypoint.*` rule; a grep for "waypoint" finds only what SC-009 allows.

**Acceptance Scenarios**:

1. **Given** the development host's `main`, **When** the feature closes, **Then** the
   final stage kind is loaded there as a migration of the candidate already on it, the
   waypoint kind is removed, and `schema check` reports the stage kind present.
2. **Given** the README's stepping walk-through, **When** a stranger follows it, **Then**
   it seeds a throwaway branch, opens a draft proposed change on it, marks two stages,
   plans, creates, steps and lists them, and deletes the stages, the proposed change and
   the branch in that order.
3. **Given** tier 3, **When** it runs whole, **Then** cases 7 and 8 run on stages and the
   run ends `E2E-OK`, with no `fylgja-test-*` branch, proposed change or stage left.

---

### Edge Cases

- **A mark whose `at` is later than the head's pin.** A mark written after the last
  intent write and regenerate has a write stamp later than the head's `at`. The head is
  still last: its position is fixed, and marks are ordered among themselves. The step from
  such a mark to the head is `unchanged`, since the two reads see the same intent, and the
  plan says so.
- **The head is stale while the draft is edited.** The pipeline regenerates artifacts at
  the proposed change's creation and on a run-check, not as the branch is edited, so after
  an edit the head's intent is newer than its artifacts and the head is refused as stale,
  like any stage, until the operator regenerates or runs the checks. The finding's remedy
  names both.
- **A mark with `as_of` exactly at a write's stamp.** A read pinned at exactly a stamp
  sees the node and not the value. Fylgja passes a written `as_of` verbatim and infers
  nothing; the staleness check and the read see what Infrahub answers at that instant.
  The schema README says to leave `as_of` out unless an instant is wanted, and that the
  mark's own write is always after what it seals.
- **A rebase.** Every mark falls before the new branch point and is refused at once; the
  refusal says a rebase did it, since `branched_from` moved and `created_at` did not. The
  branch point and the head still plan. A twin built before the rebase keeps its record,
  and `stage list` warns that its stage has moved.
- **Two proposed changes share a name.** A proposed change is found by its source branch,
  never by its name; Infrahub allows one open proposed change per branch.
- **The source branch is deleted under an open proposed change.** Infrahub cancels the
  proposed change about sixteen seconds later, and it still names the branch. Until the
  cancel lands its stages still list and every read of them fails on the missing branch;
  once canceled, the proposed change is invisible and its stages are listed, planned and
  created from by nothing.
- **A stage is removed from its proposed change.** Infrahub refuses a proposed change's
  delete while a stage names it, so a stage is orphaned only when it leaves the proposed
  change's `fylgja_stages` ([D-047](../../docs/decisions.md#d-047)). The stage is left
  pointing at nothing. Each is a finding in `stage list`, never a crash, and a reference
  naming one is refused as unknown.
- **Two stages with one label on one proposed change.** Infrahub refuses the second at
  the write; Fylgja never sees a duplicate. The same label on another proposed change is
  fine.
- **A branch whose schema predates the kind.** A branch created before the stage kind
  was loaded on `main` cannot query it, but stages are read from the default branch, so
  a proposed change on such a branch still has its stages listed and planned, and its
  intent is read as before. `fylgja-fixture` is such a branch and has no proposed
  change.
- **`main` as a source.** Infrahub refuses a proposed change whose source is `main`, so
  `main` has no stages; a story along `main`'s history is `--branch main --at`.
- **A stage with more than six fractional digits in `as_of`.** Refused as before
  (`intent.at.precision`): a pinned `at` carries at most six.
- **A given `as_of` later than now.** Refused until it has passed; Fylgja compares its own
  clock with a written `as_of` and never sends that reading, and never compares a stamp
  Infrahub returned with it.
- **The host's clock against Infrahub's.** The branch point and the head are stamps
  Infrahub returned, or the first instant after one; Fylgja composes no `at` from a clock
  of its own (Constitution VI, 1.2.0).

## Requirements *(mandatory)*

### Functional Requirements

**The kind**

- **FR-001**: Fylgja MUST ship `schema/fylgja-stage.yaml`, a branch-agnostic
  `FylgjaStage` beside the contract (the contract stays `0.2`), with a required
  relationship to the `CoreProposedChange` it belongs to, a `label` unique within that
  proposed change, an optional `as_of` and an optional `description`, no branch attribute
  and no human-friendly id, ordered by `as_of`; and an extension giving
  `CoreProposedChange` its stages. It loads on the default branch, as the contract does.
- **FR-002**: The final kind MUST land on the development host's `main` as a migration
  of the candidate already there, with the SDL refetched after it, and `FylgjaWaypoint`
  MUST be removed from that `main`.
- **FR-003**: The operator writes stages by Infrahub's own means (the UI, an object file,
  `infrahubctl`), and Fylgja MUST only read them. Every operation Fylgja makes on Infrahub
  stays a query, held by the existing read-only test.
- **FR-004**: Without the kind on the default branch, every stage command and `--stage`
  MUST be refused naming the schema file to load, and `schema check` MUST report whether
  the default branch has the kind and the extension, as it reported the waypoint kind.

**A proposed change's stages**

- **FR-005**: A proposed change MUST be found by its source branch, among the open and
  draft ones alone, and its stages MUST be, in this order: the branch point, read on `main` pinned at the branch's
  `branched_from`; each `FylgjaStage` related to it, in order of `at`, where `at` is the
  written `as_of` or else the stamp Infrahub returned for the stage's writing; and the
  head, read on the branch pinned at the later of the latest `updated_at` across its
  intent (attributes and relationship edges) and its artifacts' checksums, and the
  `occurred_at` of the latest intent event in its event log since `branched_from`, plus
  one microsecond, so a removal no stamp records is seen ([D-048](../../docs/decisions.md#d-048)). The ends'
  positions are fixed whatever the marks' stamps.
- **FR-006**: Every stage MUST be pinned, and Fylgja MUST compose no `at` from a clock of
  its own: each `at` is a stamp Infrahub returned or the first instant after one, passed
  verbatim on every query of the read and recorded as the read's `at`.
- **FR-007**: Every command, report and record MUST say where a stage's `at` came from:
  written on the stage, the stage's own write, the branch point, or the head.
- **FR-008**: A stage reference on the command line MUST be `<branch>/<label>`: the
  proposed change by its source branch, then a mark's label, or `branch-point` or `head`
  for the derived ends. The branch has no `/` and no whitespace, as before. A mark
  carrying a reserved label MUST be refused, naming it, wherever stages are listed or
  resolved; Fylgja cannot refuse the write, so the schema README says the two labels are
  reserved. There is no naming by position.
- **FR-009**: Open and draft proposed changes alone MUST be visible to Fylgja: their
  stages are listed, planned and created from. A merged, closed or canceled one MUST be
  invisible: its stages are listed by nothing, and a reference naming its branch MUST be
  refused as unknown, saying no open proposed change has that source branch.

**Refusals and warnings**

- **FR-010**: A stage whose `at` is before the branch point or later than now MUST be
  refused, saying which. When `branched_from` has moved past the stage's stamp while the
  branch's `created_at` has not, the refusal MUST say a rebase did it.
- **FR-011**: A stale stage MUST be refused: at each stage, pinned at its `at`, Fylgja
  reads, per device, the latest stamp of its own intent and its generation stamp, the
  later of its artifact's checksum stamp (never its status stamp) and the proposed
  change's artifact validator's completion ([D-046](../../docs/decisions.md#d-046)), and
  the intent events later than that generation stamp and no later than the stage's `at`
  that name the device or one of its interfaces ([D-048](../../docs/decisions.md#d-048)); intent newer than that,
  by a stamp or an event, is `stage.artifact.stale`, naming the device and saying to
  regenerate, by a generate or by the proposed change's run-check, and mark again. It applies to every stage, the head included, and it is made at
  `resolve` on every command that resolves a stage: `stage plan` runs it over every
  stage, and `twin create --stage`, `twin step` and `intent read --stage` refuse a stale
  stage before any run starts, with the same finding.
- **FR-012**: Fylgja MUST warn when `main` has moved since the branch point, read as the
  head is: `main`'s latest stamp against `branched_from`. It refuses nothing for it.
- **FR-013**: A stage whose proposed change no longer exists MUST be a finding naming it,
  never a crash; it is listed as such and neither planned nor created from.
- **FR-014**: The resolution refusals MUST all be made before any run starts and before
  any branch's intent is read: a malformed reference, `--stage` beside `--branch`, `--at`
  or `--interval`, the kind absent, no open or draft proposed change on the branch or no
  such stage of it, a reserved label on a mark, a given `at` later than now, a stale
  stage, and the rules above. Each MUST have a stable `stage.*` identifier; the waypoint
  rules become `stage.*` ones, and every finding, rejection and warning keeps a stable
  identifier (Constitution X).

**The commands**

- **FR-015**: `--stage` MUST replace `--waypoint` on `twin create`, `twin step` and
  `intent read`, resolving to a pinned `(branch, at)` at the findings step `resolve`; the
  run is then the pinned run, which never follows, and the stage's name enters neither the
  CTM nor the bundle.
- **FR-016**: `stage list` MUST replace `waypoint list`: it lists the stages of every
  open or draft proposed change, or of the one named by its branch, resolved to their
  branch and `at`, each with where its `at` came from, its label and description, and
  whether its proposed change is a draft, sorted so the same input gives the same
  document; marks the
  stage the host's readable record names, with the record's state and, when diverged, the
  target; and warns `stage.twin.moved` beside a record whose stage no longer resolves to
  what the record holds or is gone. It needs no lab, worker or workflow service.
- **FR-017**: `stage plan` MUST replace `waypoint plan`: for one proposed change, named
  by its source branch, it resolves, reads and compiles each stage in order on the stage
  pipelines, files each bundle in the store, prints each stage's reference, bundle
  identifier and read counts or its findings, and the step between each consecutive pair
  as M10's pure step does: nodes, links, bootstraps and artifacts by name and checksum,
  never a line of content, with both bundle identifiers; a step touching a refused stage
  says it was not computed. It needs no lab, worker or workflow service.
- **FR-018**: `twin step` MUST go to a stage of the twin's own proposed change: with no
  target, the next stage in order; with `--stage`, any stage of it, forward or back. A
  stage of another proposed change MUST be refused as foreign, the record's own stage,
  judged by its resolved reference, as current, and no next stage as unknown, each before
  anything on the host is touched; skipping marks between the record's stage and the
  target MUST warn. A head that has moved since the record MUST be a valid target. The
  step's own rules (D-036: `--allow-restart`, divergence, the diff, the wait) are
  unchanged.
- **FR-019**: `twin show`, `twin verify`, the dry runs and the run's first line MUST
  name the stage where they named the waypoint, in the same places and shape.
- **FR-020**: The text and JSON renderings of every stage command and every command
  taking `--stage` MUST keep the findings document's shape: one document, the operation's
  own block, the findings; `--json` prints the document and nothing else on stdout. Every
  refusal with a rule identifier is the server's, so every client is refused alike
  (Constitution XI).

**The record and the formats**

- **FR-021**: The twin's record MUST name the stage the twin was created from or stepped
  to where it named a waypoint, the proposed change it belongs to, by Infrahub's
  identifier and its source branch, and where the `at` came from; `twin_version` moves,
  and a frozen copy of the previous format stays under its package's test data for the
  tests of older records.
- **FR-022**: The findings document MUST carry `stage` blocks where it carried waypoint
  ones: the resolved reference on `twin create`, its dry run and `intent read` with
  `--stage`; the list block on `stage.list`; the plan block on `stage.plan`; the step
  block's two sides naming stages; `subject` naming the stage as supplied; and `schema
  check`'s report of the kind. `waypoints.schema.json` is replaced by a stages contract
  under its own `$id`; `findings_version` and the bundle, CTM, PSP and contract formats
  do not move.
- **FR-023**: The API MUST serve `stage.list` and `stage.plan` where it served the
  waypoint operations, and take `stage` where `twin.create`, `twin.step` and
  `intent.read` took `waypoint`; the payloads stay the documents Fylgja versions
  (Constitution XI). [contracts/api.md](../../contracts/api.md) and
  [contracts/cli.md](../../contracts/cli.md) MUST say what moved and what each command
  needs, as they do for M10–M13.
- **FR-024**: No golden, no fixture identifier, no workflow, no activity and no wire type
  beyond the record's stage MUST move; the live fixture still compiles to the identifier
  it has on each install.

**Removal**

- **FR-025**: `FylgjaWaypoint` MUST be removed: the schema file, the waypoint commands,
  `--waypoint`, the `waypoint.*` rules, `waypoints.schema.json`, the reader, the fixture
  tool's `-waypoint` and `-delete-series` (`-at` and `-description` stay, for `-stage`),
  and test support's series. Waypoints are not kept beside stages.
- **FR-026**: The fixture tool and test support MUST make, on a `fylgja-test-*` branch
  alone, a draft proposed change and stages on it, and delete what they made in order:
  the stages, then the proposed change, then the branch. The fixture tool MUST refuse to
  write a stage or a proposed change for `fylgja-fixture`, which has no proposed change.

**Tests and tier 3**

- **FR-027**: Tier 1 MUST cover the stage list with its ends derived, the head's stamp,
  its latest intent event and its microsecond, the order with the ends fixed, each refusal, the rebase message,
  the staleness rule, the `main`-moved warning, `--stage` parsing, the step's target rule
  and the record, with no infrastructure.
- **FR-028**: Tier 2 MUST, against the real Infrahub, find the kind on `main`; make a
  throwaway branch and draft proposed change with two stages, list and plan them; exercise
  the refusals tier 2 can make: stale, a rebase, a reserved label, a closed proposed
  change, an unknown branch or stage, a duplicate label and a future `as_of` (the kind
  absent and a malformed reference are tier 1's); prove a removal seen: a link deleted
  as the branch's latest write moves the head past it, and a stage marked after it is
  refused stale on its endpoint devices alone (`TestStagesSeeARemoval`, [D-048](../../docs/decisions.md#d-048)); delete
  the stages, the proposed change and the branch in that order; and find no
  `FylgjaWaypoint` on `main` and no stage after it.
- **FR-029**: Tier 3's cases 7 and 8 MUST run on a throwaway branch with a draft proposed
  change and stages where they ran on a series, ending `E2E-OK` whole and `E2E-PARTIAL`
  narrowed as before, with no `fylgja-test-*` branch, proposed change or stage left; the
  README's stepping walk-through does the same by hand, and the recording is remade at
  `v0.2.0`, not here.

**The records**

- **FR-030**: The schema README MUST gain "Stages: marking one", saying how to open a
  draft proposed change, when to mark (after the writes and after the artifacts are
  regenerated, with the stale refusal as the backstop), the fields, the three ways to
  write one, what editing a stage changes, and that stages are deleted before their
  proposed change.
- **FR-031**: At the close, [docs/architecture.md](../../docs/architecture.md) and its C4
  model (redrawn in the same change), the [glossary](../../docs/glossary.md),
  [docs/development.md](../../docs/development.md),
  [docs/verified-facts.md](../../docs/verified-facts.md), the [roadmap](../../docs/roadmap.md),
  [docs/ideas.md](../../docs/ideas.md) (the persistent fixture series closed),
  [README.md](../../README.md) and `CLAUDE.md`'s Formats and State MUST describe stages
  where they describe waypoints; the decision log is append-only and D-045 is already
  written.
- **FR-032**: A draft of the upstream request for named points in time MUST be prepared
  for the operator's approval once the pass works, citing the issues the brief names and
  the strict boundary and the rebase's discarded history; a session never files it.
- **FR-033**: Nothing this feature writes (a finding, a record, a log line, a test's
  output) MUST carry a token, a login or a password.

### Key Entities

- **Proposed change**: Infrahub's unit of change, `CoreProposedChange`: a source branch,
  a destination, a state (open, closed, merged, canceled) and a draft flag. One open per
  source branch; `main` is never a source. Fylgja finds it by its source branch and reads
  its stages through the extension.
- **Stage**: a moment of a proposed change, a pinned intent reference on its source
  branch. Two are derived, the **branch point** (`main` at the branch's
  `branched_from`) and the **head** (the branch one microsecond after the later of its
  latest stamp and its latest intent event);
  the rest are **marks**, `FylgjaStage` objects the operator writes: a label unique
  within the proposed change, an optional `as_of`, an optional description.
- **Stage reference**: `<branch>/<label>`, how a stage is named on the command line
  and in the findings document: the proposed change by its source branch and the stage
  within it, a mark's label or the reserved `branch-point` and `head` (FR-008). It
  resolves to `(branch, at)` and an `at` source.
- **Step (of a proposed change)**: the difference between two consecutive stages'
  bundles, M10's pure step, printed by `stage plan` and applied by `twin step`.
- **Twin record**: `twin.json`, which names the stage and the proposed change the twin
  was built from or stepped to, beside the bundle, the provenance and the step block.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a proposed change with nothing marked, `stage plan` lists exactly two
  stages and one step; with two marks, exactly four and three; the order is the branch
  point, the marks by `at`, the head, in every case.
- **SC-002**: A twin created from a stage deploys the bundle identifier `stage plan`
  printed for it, every time, and `intent read --stage` writes the same CTM as the same
  branch and `at` given by hand, but for `observed_at`.
- **SC-003**: A stage marked after an intent change and before its regenerate is refused
  as stale, naming every device whose artifact is older than its intent and no other;
  the same mark after a regenerate and a fresh mark is planned.
- **SC-004**: After a rebase, every mark is refused in one plan, the refusal names the
  rebase, and the two derived stages are still planned: the head compiles, the branch
  point where `main` holds the contract.
- **SC-005**: Every refusal of a stage, the stale one included, is made before any run
  starts and before any branch's intent is read, on every command alike, and every one
  has a stable identifier.
- **SC-006**: Tier 1 passes with no infrastructure in its present budget; tier 2 passes
  against the real Infrahub, deleting its stages, proposed change and branch in order and
  leaving `FylgjaStage { count }` at 0 and no `FylgjaWaypoint` kind on `main`; tier 3
  ends `E2E-OK` with cases 7 and 8 on stages, leaving no `fylgja-test-*` branch, proposed
  change or stage.
- **SC-007**: `stage list` and `stage plan` answer with no lab, no worker and no workflow
  service running.
- **SC-008**: The three goldens, the live fixture's identifier, the bundle, CTM, PSP and
  contract formats and the four workflows do not move; only the twin record's version,
  the API's and CLI's stage surface and the findings document's stage blocks do.
- **SC-009**: A grep of the tree for `waypoint` finds only history (the decision log, the
  archive, `docs/how-it-was-built.md`, the recording and its caption, `CLAUDE.md`'s
  Milestones), the glossary's superseded terms, one sentence per record saying what
  replaced the waypoint (the README's note beside the recording, the architecture, the
  roadmap's F-023, the contracts' rows marked moved at 014), one sentence each in the
  architecture and `contracts/cli.md` on how a `5` record's step reads in `twin show` and
  `twin verify`, the frozen `twin.schema.json` copies and the `5`-record wording that names
  it; `fylgja --help` names no waypoint command or flag, and no code, schema, query or test
  outside the frozen copies does but what proves the waypoint gone or reads an older
  record: the tests that `fylgja waypoint list` is unknown, `/v1/waypoint/*` is `404`, a
  `waypoint` argument is `400` and M10's shape is refused where a stage goes; `twin.json`
  `5`'s tests and decoder field; the contract schemas' version-history descriptions;
  `internal/lab/wire`'s `TwinRecord.SupersededWaypoint` (the contracts' own words, the one
  place a `5` record's stage is worded for `twin show`, `twin verify` and the step's
  refusal) with its `SideName` and `SideStage`; `workflow_step.go`'s `5`-record refusal;
  and `internal/provision/testdata/rewrite-stage.go` (quickstart §6's greps, as amended at
  T055 and T074).
- **SC-010**: A stranger following the README's stepping walk-through marks, plans,
  creates, steps and lists stages on a throwaway branch and deletes everything after, in
  the order the README gives, with no leftover in Infrahub.

## Assumptions

- **The proposed change in the record is named by its identifier and its source branch.**
  Names are not unique, and a branch may carry a new proposed change after one closes, so
  the record names the proposed change the twin was built from by identifier, with the
  branch beside it for the reader.
- **`stage list` without a branch lists every open or draft proposed change**, each with
  its stages, as `waypoint list` listed every series; with a branch, the one proposed
  change.
- **The head is always last and the branch point always first**, whatever a mark's
  stamp, since a mark written after the last regenerate is the normal case and lies after
  the head's `at`. The step from such a mark to the head is `unchanged`.
- **The staleness check reads the stamps as research.md §2.5 verified them, and the
  branch's intent events as §8.18 did** ([D-048](../../docs/decisions.md#d-048)): intent is attributes and
  relationship edges, and a removal, which moves no stamp, is seen by its event; an
  artifact's stamp is its checksum's; the branch
  point is checked too, which on an install where `main` holds no devices is trivially
  fresh.
- **A twin steps from the bundle its record holds**, whatever the record's stage now
  resolves to; a moved stage is a warning in `stage list` and on the step, never a
  refusal of the step, as M11 had it.
- **Marks are read through the default branch's endpoints** and need no branch named,
  as waypoints were; a branch whose schema predates the kind still has its proposed
  change's stages listed.
- **The fixture tool gains the flags test support needs** to open a draft proposed
  change and mark stages on a `fylgja-test-*` branch, and to delete them in order; their
  names are the plan's.
- **Infrahub's proposed-change view shows no stages.** The stage's own page and the
  sidebar do; the rehearsal's comment lists them on the proposed change; the upstream
  request asks for a native mark.
- **The recording is remade at `v0.2.0`**, not here; until then the README's image shows
  waypoints and the text beside it says so.
- **The development host's Infrahub is the only install**; its `main`'s hash moves with
  the migration, the fixture branch's does not, and the fixture compiles to the same
  identifier before and after.
