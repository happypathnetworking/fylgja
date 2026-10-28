# Feature Specification: Following removed from the core

**Feature Branch**: `019-following-removed`

**Created**: 2026-10-28

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/019-following-removed GIT_BRANCH_NAME=019-following-removed. 0.3, the third of its five specs: following removed from the core, as docs/roadmap.md's F-026 and Release 0.3 section define it. Read specs/019-following-removed/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.3 is exploratory coding toward the production refactor
([roadmap](../../docs/roadmap.md#release-03)), and this is its third spec
([F-026](../../docs/roadmap.md#f-026)). Since 018 every workflow the core runs but one
starts with a snapshot id and a bundle id and never reads a branch
([D-061](../../docs/decisions.md#d-061)). The one left is **following**: a twin built from
a branch with no `at` and no `--no-follow` is checked every interval by a scheduled
workflow that reads the branch, compiles it and rebuilds the twin when its bundle id has
moved ([D-012](../../docs/decisions.md#d-012), [D-026](../../docs/decisions.md#d-026),
[D-027](../../docs/decisions.md#d-027)). That check is the core's last reader of a branch,
and a twin that may tear itself down between two measurements is the wrong ground for the
probes the next spec adds. This feature takes following out of the core. **A twin is
frozen at its snapshot, and nothing rebuilds it but the operator.**

Following leaves the core, not Fylgja: the production shape's orchestrator
([roadmap](../../docs/roadmap.md#the-production-shape)) may bring it back as take, compare,
step, and for NetBox by push on an event rule. What the core keeps, and widens, is the
step. **Walking means stepping**: a twin walks when the operator steps it from one snapshot
to another, through a proposed change's stages or to any snapshot the operator takes, and
the name is kept. Following was one way of walking, the one the operator did not drive.

What the operator gets: a twin built from `--branch`, `--stage` or `--snapshot` stays
exactly as built until the operator steps or destroys it; `twin step --snapshot <id|file>`
steps any such twin to a snapshot of any branch, and `twin step --stage` to a stage of any
proposed change; a twin's scope and mapping are fixed for its life and a step to another is
refused before any run; `twin show` names the snapshot the twin was built from in place of
pinned, frozen or following; `--interval` and `--no-follow` are gone outright; `twin
destroy` is the destroy alone, and every rehearsal's deadline is shorter by the stop it no
longer makes. The brief's [Decided](brief.md#decided) list is settled and restated here
only where a requirement needs the sentence. The decision entry (D-062) and every exact
name and wording the brief [leaves to the plan](brief.md#left-to-the-plan) are the plan's
to write.

Four actors appear below. **The operator** runs the lab host and Fylgja, models intent in
Infrahub, marks stages and takes snapshots with `intent read --out`. **The server**,
`fylgja serve`, resolves, reads, takes and files snapshots, compiles, and starts
workflows; every refusal is its. **The worker** runs the workflows, which after this
feature are four, each started with a snapshot id and a bundle id. **The checks**,
`fylgja-step` and `fylgja-twin`, are clients inside Infrahub's task workers whose
rehearsal's deadline moves with this feature and whose behaviour otherwise does not.
Probes (016), the NetBox reader (F-025), the orchestrator and the API's shape for long
operations are out of this feature.

## Clarifications

### Session 2026-10-28

- Q: How long should tier 3's case 5 wait, after editing the branch, before it asserts that nothing rebuilt the twin? → A: Longer than five minutes, the retired default check interval.
- Q: What should `twin show` call a twin whose record names no snapshot and was not provisioned from a bundle directory? → A: Kind `snapshot`, its line `kind: snapshot none (branch B, read at T)`, the record line `snapshot none`, and a note that it names no snapshot, so `twin step` refuses it and `twin destroy` clears it.
- Q: Does a stage twin whose record is `twin.json` 8, which names no snapshot, still step, as 018 allowed? → A: No. Only a twin whose record names a snapshot steps; 018's allowance for an 8 that names a stage is retired, and `twin destroy` clears it (settled by the operator at plan).
- Q: The constitution's Governance says a change to a cited decision requires an amendment; D-062 supersedes D-007, D-012 and D-014, cited by VIII, VI and IX, in part. Amend? → A: No. No principle names following; as when D-060 superseded D-059 (cited by III) in part, the sentence is read as a change to what a principle relies on, and D-062 says so (settled by the operator at plan).
- Q: Where does the upgrade sentence live before 0.3's release notes exist? → A: In `contracts/cli.md`'s 019 section and an "Upgrading a 0.2 host" list in the roadmap's Release 0.3 section, which 0.3's notes copy at the release's close; `release.yml`'s heredoc is v0.2.0's and is not edited (settled by the operator at plan).
- Q: Is D-062 appended now or at `analyze`? → A: Now, at plan, with the five *Superseded* status lines and the index row, uncommitted beside the roadmap's edits.
- Q: Which decisions did the plan settle without the operator, as following from the spec's own words? → A: `step.target.foreign` is retired, since US3 scenario 3 leaves it no case; the "no target" refusal reads the record before the workflow service is dialed, to meet FR-014's "before any connection"; `stage.twin.moved` is given only when the target is in the proposed change the record's stage belongs to; `twin.json` moves to `10`, since a 10 record can hold what no 9 can; the snapshot rule is the server's alone, since inside the run it would refuse the recorded step histories (research R-03, R-07–R-09).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A twin is frozen at its snapshot (Priority: P1)

The operator runs `fylgja twin create --branch <b>` with no `--at`, as before. The server
takes and files the snapshot, compiles, files the bundle and starts the provision
workflow, which ends when the twin is ready. Nothing is scheduled. The operator then edits
the branch in Infrahub and generates its artifacts, and waits longer than the retired
default check interval of five minutes: no run starts, the twin's record is unchanged
byte for byte, its containers are the same, and `twin show`'s kind line still names the
snapshot the twin was built from. The worker's start-up registers four workflows,
provision, destroy, step and rehearse, and fifteen activities, the lab's; no workflow
reads a branch.

**Why this priority**: this is the feature's one exit criterion, and the ground the next
spec stands on. Until the check goes, the production shape's core still knows a branch.

**Independent Test**: on a throwaway branch seeded with the three-node fixture, create
from `--branch`, record the twin's record hash and container ids, change one port's state
and generate, wait longer than five minutes, and read both again: unchanged, no Schedule
on the workflow service, no run of any type started since the create, and the kind line
as at the create.

**Acceptance Scenarios**:

1. **Given** no twin and a branch, **When** the operator runs `twin create --branch <b>`,
   **Then** the twin boots as before, the create's document holds no following block, and
   no Schedule exists on the workflow service afterwards.
2. **Given** that twin, **When** the branch is edited and its artifacts regenerated, and
   longer than five minutes pass, **Then** no run has started, the record and the
   containers are unchanged, and `twin show` says what it said at the create.
3. **Given** a worker of this build, **When** it starts, **Then** its report names both
   packages as before, and it serves provision, destroy, step and rehearse and the lab's
   fifteen activities; it serves no reconcile workflow and no control activity.
4. **Given** a twin of this build, **When** the operator runs `twin destroy`, **Then** the
   destroy workflow alone runs, stopping nothing first, and its document names no
   following.
5. **Given** a rehearsal of a proposed change, **When** it is planned, **Then** its
   deadline is 30 s shorter than the same plan's before this feature, since its baseline
   no longer stops a following before it builds; nothing else of the rehearsal changes.

---

### User Story 2 - The operator steps a twin to a snapshot (Priority: P1)

The operator holds a running twin built from `--branch`, `--stage` or `--snapshot`, and a
snapshot: an id the server's store holds, or a file written by `intent read --out`. `twin
step --snapshot <id|file>` takes the twin to it without a rebuild, as a stage step does: the
server compiles and files the snapshot's bundle, computes the step between the two
bundles and the push plan, reads containerlab's plan, and starts the step workflow with a
target side that names no stage, the snapshot id, the bundle id, and the branch and `at`
the snapshot's envelope carries. No request reaches Infrahub for the target. Afterwards the
record names the target's snapshot, bundle, branch and `at`, and no stage. An id the store
does not hold is refused, a file whose declared id its body does not hash to is refused,
and either way a file is filed under its id, as on create. A twin `twin provision
<bundle-dir>` built names no snapshot and stays unsteppable, in words that say so.

**Why this priority**: this is how the operator walks a twin now that nothing walks it for
them, and what the orchestrator's event rule would call. It is also where tier 3's case 5
shows the exit criterion live: a change reaches a running twin only through this step.

**Independent Test**: tier 3's case 5, repurposed. Create from a throwaway branch; show the
criterion as Story 1 does; disable one port on the branch and generate; `intent read --out`
the branch to a file and `twin step --snapshot <file>`; the node reads the port disabled and
`twin verify` skips that port and its link's two ends (M12's 5a); add a third link and
generate; read and step again; the link is cabled live and both nodes read back their new
artifacts. In tier 1, a step by id and by file from a twin built by each of the three
references, and the refusal for a bundle twin.

**Acceptance Scenarios**:

1. **Given** a twin built from `--branch` and a snapshot id the store holds, **When** the
   operator runs `twin step --snapshot <id>`, **Then** the server compiles and files its
   bundle, starts the step workflow with the snapshot id and the bundle id, no request
   reaches Infrahub, and the record afterwards names that snapshot and bundle and no stage.
2. **Given** a twin built from `--stage` and a snapshot file, **When** the operator runs
   `twin step --snapshot <file>`, **Then** the client sends the file, the server files it
   under its id, and the step runs as in scenario 1; the record's step block names the
   stage on its from side and no stage on its to side.
3. **Given** a twin built from `--snapshot`, **When** the operator steps it to another
   snapshot, **Then** it steps; the guard that only a twin built from a stage steps is gone.
4. **Given** a twin `twin provision <bundle-dir>` built, **When** the operator runs `twin
   step --snapshot <id>`, **Then** it is refused by `step.twin.unsteppable`, saying the
   twin names no snapshot, before any run.
5. **Given** a snapshot id the store does not hold, **When** the operator steps to it,
   **Then** it is refused by `snapshot.unknown`, naming the id, before any run; a file
   whose declared id does not match its body is refused by `snapshot.id.mismatch`, naming
   both ids.
6. **Given** a snapshot whose bundle equals the twin's, **When** the operator steps to it,
   **Then** the step is `unchanged`, as a step to a stage of the same bundle is today.
7. **Given** a snapshot whose compile is refused (a platform no package matches), **When**
   the operator steps to it, **Then** the refusal is the server's before any run, and the
   twin is untouched.
8. **Given** `--dry-run` with `--snapshot`, **When** the operator runs it, **Then** it
   prints the twin line, the target, the step, containerlab's plan and the push plan, and
   changes no lab, container, twin directory or run, as the stage step's dry run does.

---

### User Story 3 - A step to a stage of any proposed change (Priority: P2)

The operator holds a twin built from `--branch` or `--snapshot`, which names no stage, and
runs `twin step --stage <branch>/<label>`: the stage of any proposed change, resolved,
read and compiled under the twin's scope as a stage step is today, and stepped to. For a
twin that names no stage `--stage` is required, and leaving it out is refused before any
connection. For a twin that names a stage, `--stage` left out keeps its meaning, the next
stage of the twin's own proposed change, and `--stage` given may name a stage of another
proposed change; the warning that the twin's own stage has moved is given only when the
record names a stage of the proposed change the target is found in.

**Why this priority**: a twin built from a branch head could not walk a proposed change
before; now it can, and a twin can cross from one proposed change's story to another's.

**Independent Test**: on two throwaway branches each with a draft proposed change and a
marked stage, create from `--branch` on the first; `twin step` with no `--stage` is
refused; `twin step --stage <first>/<label>` steps and the record names the stage; `twin
step --stage <second>/<label>` steps to the other proposed change's stage and the record
names it; `twin step` with no `--stage` now steps to the next stage of the second.

**Acceptance Scenarios**:

1. **Given** a twin built from `--branch`, **When** the operator runs `twin step` with no
   `--stage` and no `--snapshot`, **Then** it is refused before any connection, saying the
   twin names no stage and a target is required.
2. **Given** that twin and a stage on its branch's proposed change, **When** the operator
   runs `twin step --stage <branch>/<label>`, **Then** the stage is resolved and read under
   the record's scope, the twin steps, and the record names the stage.
3. **Given** a twin built from stage A of proposed change P, **When** the operator runs
   `twin step --stage <q>/<label>` naming a stage of another proposed change Q, **Then** it
   steps, and the record names Q's stage and Q's branch; `step.target.foreign` no longer
   refuses it.
4. **Given** a twin that names a stage, **When** the operator runs `twin step` with no
   `--stage`, **Then** the target is the next stage of the twin's own proposed change, as
   today.
5. **Given** a twin that names no stage, **When** the operator runs `stage list` or
   `twin step --stage`, **Then** no `stage.twin.moved` warning is given, since there is no
   stage of the twin's to have moved.
6. **Given** `--stage` beside `--snapshot` on `twin step`, **When** the operator runs it,
   **Then** it is refused before any connection, naming the conflict, as the two are on
   `twin create`.

---

### User Story 4 - Scope and mapping are the twin's for life; the branch is not (Priority: P2)

A twin's scope (`tag:<name>`) and mapping (the reader, the model and its version) are fixed
when it is created. A step whose target's snapshot names another scope or another mapping
is refused by `step.twin.unsteppable`, naming the record's and the target's, before any
run: for a `--snapshot` target by its envelope, and for a `--stage` target through the
snapshot its resolution takes. To change scope, the operator destroys and creates. The
branch is not fixed: a target may be a snapshot of any branch, and after the step the
record names the target's branch and `at`, so one twin can hold A and then B.

**Why this priority**: the core knows no branch, so the step diffs two bundles whatever
branch each was read from; but a diverged step keeps the record's provenance, and a scope
or mapping the twin did not start with would write a provenance it never had.

**Independent Test**: build a twin from the fixture branch under `tag:fylgja`; a snapshot of
the same branch read under another tag is refused before any run, the refusal naming both
scopes; a snapshot of another branch under `tag:fylgja` steps, and the record names that
branch afterwards.

**Acceptance Scenarios**:

1. **Given** a twin under scope `tag:fylgja` and a snapshot whose envelope names scope
   `tag:other`, **When** the operator steps to it, **Then** it is refused by
   `step.twin.unsteppable` before any run, naming `tag:fylgja` and `tag:other`.
2. **Given** a twin read by one mapping version and a snapshot read by another, **When**
   the operator steps to it, **Then** it is refused before any run, naming both mappings.
3. **Given** a twin built from branch A's snapshot and a snapshot of branch B under the
   same scope and mapping, **When** the operator steps to it, **Then** it steps, and
   afterwards the record's branch, `at`, snapshot and bundle are B's snapshot's.
4. **Given** a `--stage` target whose resolved snapshot names the twin's scope and
   mapping, **When** the operator steps to it, **Then** the check passes without a word,
   as every stage step's does by construction.

---

### User Story 5 - `twin show` names the snapshot (Priority: P2)

The operator runs `twin show`. For a twin built from or stepped to a snapshot, the kind
line names the snapshot, then what it holds: `kind: snapshot <short> (branch B at T)` when
the snapshot's envelope carries an `at`, `kind: snapshot <short> (branch B, read at T)` when
it does not, so the reader still knows whether the snapshot can be taken again. The stage,
the `(stepped from …)` and the rehearsal notes stay where they are; "; not following" goes.
`from a bundle`, `diverged` and `none` stay. The show document's kind loses `pinned`,
`frozen` and `following`, its following block and last check go, and runs in flight stay.
`twin verify`'s twin block names the snapshot beside the bundle. "Pinned" survives as a
word for a reference with an `at`, never as a kind.

**Why this priority**: three kinds collapse into one fact, which is what the operator asks
of a twin that only they move: what is it built from, and can I take that again.

**Independent Test**: build a twin from `--branch`, from `--branch --at`, from `--stage` and
from `--snapshot`, and read the kind line of each; each names its snapshot's short id and,
in brackets, its branch and its `at` or read time; none says pinned, frozen or following;
`twin show --json`'s kind is `snapshot` for each and `from_bundle` for a provisioned twin.

**Acceptance Scenarios**:

1. **Given** a twin built from `--branch <b>` with no `--at`, **When** the operator runs
   `twin show`, **Then** the kind line reads `kind: snapshot <short> (branch <b>, read at
   <observed_at>)`.
2. **Given** a twin built from `--branch <b> --at <T>`, or from a stage, **When** the
   operator runs `twin show`, **Then** the kind line reads `kind: snapshot <short> (branch
   <b> at <T>)` and keeps `, stage <branch>/<label>` where the record names one.
3. **Given** a twin stepped from one snapshot to another, **When** the operator runs `twin
   show`, **Then** the kind line names the new snapshot and keeps `(stepped from … by run
   fylgja-step …)`.
4. **Given** a rehearsal's baseline twin, **When** the operator runs `twin show` while it
   runs, **Then** the kind line names the snapshot and the rehearsal's run as today, with
   no "not following".
5. **Given** the workflow service unreachable, **When** the operator runs `twin show`,
   **Then** it still reports the host and the record, says whether a run is in flight is
   unknown, says nothing of following, and exits 0.
6. **Given** a twin `twin provision <bundle-dir>` built, **When** the operator runs `twin
   show`, **Then** the kind is `from a bundle` and the record line reads `snapshot none`,
   as today.
7. **Given** a twin of this build, **When** the operator runs `twin verify`, **Then** its
   first line and its document's twin block name the snapshot beside the bundle.

---

### User Story 6 - The flags, the records, the decision and the documents (Priority: P3)

`--interval` and `--no-follow` are unknown flags on every command, and the API refuses
`interval` and `no_follow` as unknown arguments under version `1`; the following rules and
the findings step `follow` are gone, and `stage.flags.conflict` stops naming `--interval`.
The twin record's rule that a stage implies an intent source is reworked, so a `--snapshot`
twin stepped to a stage and a stage twin stepped to a snapshot both have valid records. The
show, findings, API and twin schemas move, their earlier formats still load from frozen
copies, and every remaining recorded history replays against the workflows as changed.
One decision entry, D-062, says following leaves the core and not Fylgja, superseding
D-012 in part, D-026 and D-027 whole, and D-007 and D-014 in their Reconcile and Schedule;
the constitution is not amended, since it never mentioned following. The contracts, the
README, the architecture, the glossary, the C4 model, the development notes, the ideas file,
`CLAUDE.md` and the roadmap say what is now true, and the upgrade note (in `contracts/cli.md`
and the roadmap, for 0.3's release notes to copy) says to destroy a following twin before
upgrading.

**Why this priority**: none of it changes what a twin does, and all of it is how the next
spec and the next reader find out what this one built, and how an operator of a 0.2 host
upgrades without a Schedule left behind that starts a workflow no worker serves.

**Independent Test**: `twin create --branch b --interval 30s` and `--no-follow` are each
refused as an unknown flag before any connection; a request to the API carrying
`interval` or `no_follow` is refused as an unknown argument; grep the tracked documents
for following as current behaviour and find it only in the decision log's superseded
entries, the archive and the release notes; load each frozen record and replay each
remaining history.

**Acceptance Scenarios**:

1. **Given** `twin create --branch <b> --interval 30s`, **When** the operator runs it,
   **Then** it is refused before any connection as an unknown flag; the same for
   `--no-follow` on `create`, and for either on any other command.
2. **Given** a request to `twin.create` carrying `interval` or `no_follow`, **When** the
   server reads it, **Then** it is refused as an unknown argument, as any unknown argument
   is, under API version `1`.
3. **Given** a `--snapshot` twin stepped to a stage, and a stage twin stepped to a
   snapshot, **When** each record is written and read back, **Then** each is valid under
   the twin record's rules, and `twin show` reads each.
4. **Given** the recorded histories that remain once the two following histories are gone,
   **When** they are replayed against the workflows as changed, **Then** each replays.
5. **Given** the decision log, **When** D-062 is read, **Then** it names the entries it
   supersedes and in what part, each of which gains its *Superseded* status and nothing
   else, lists the entries that cite following and stand as history, and says the
   orchestrator may bring following back as take, compare, step.
6. **Given** a host upgraded from a build that followed, with a following twin left up,
   **When** the upgrade note is read (`contracts/cli.md`'s 019 section, the roadmap's
   Release 0.3 section, and 0.3's release notes once written), **Then** it says to destroy
   that twin before upgrading, and the new build carries no code for the Schedule it would leave.

---

### Edge Cases

- **A Schedule left behind by an earlier build**: a host upgraded with a following twin up
  keeps a Schedule that starts a workflow no worker of this build serves. The upgrade note
  says to destroy the twin first; nothing in the build clears it; tier 3's leak check keeps
  refusing a stray `fylgja-follow` after its trap's destroy.
- **A record naming no snapshot that is not a bundle twin**: a twin a rebuild of an earlier
  build made, left up across the upgrade. Its kind is `snapshot`, its kind line `kind:
  snapshot none (branch B, read at T)`, its record line `snapshot none`, with a note that it
  names no snapshot, so `twin step` refuses it as unsteppable, in words that say so, and
  `twin destroy` clears it.
- **A record of `8` or earlier**: unsteppable, naming its version and `twin destroy` as
  the remedy. A 7 or earlier is refused as today; an 8 that names a stage could step under
  018, and no longer does, since it names no snapshot (clarified 2026-10-28).
- **A diverged twin**: `step.twin.diverged` as today; a step to a snapshot does not change
  what diverged means or how it is cleared.
- **A step while a run is in flight**: `run.in_flight` as today, for a snapshot target as
  for a stage target.
- **A twin stepped to a snapshot, then `twin step` with no target**: the record names no
  stage after a `--snapshot` step, so `--stage` or `--snapshot` is required, and leaving
  both out is refused.
- **A `--snapshot` target of another branch than the twin's proposed change's**: allowed;
  the record names the new branch; a later `--stage` left out means the next stage of the
  proposed change the record names, which after such a step is none.
- **A snapshot file with no declared id**: the server computes the id and files it, as on
  create.
- **A snapshot that passes the outer check and fails the CTM's own rules**: refused before
  any compile, as a sent snapshot is on create.
- **A step to a snapshot whose scope matches but whose mapping version is newer**: refused
  naming both mappings; the operator destroys and creates.
- **A stage step whose resolution reads under the record's scope**: the target's scope is
  the record's by construction and the check passes silently; a stage target whose
  mapping differs is refused like a snapshot's.
- **`stage.twin.moved` for a twin that names no stage**: never given; the rule applies
  only when the record names a stage.
- **The rehearsal's check timeout**: `fylgja-twin`'s timeout of 4260 s was sized with the
  30 s stop in it; whether it moves is the plan's call, and nothing here needs it to.
- **A step's `--wait`, `--allow-restart` and phases**: unchanged for a snapshot target; a
  restart or recreate still needs `--allow-restart`, and the wait is recorded as today.
- **`twin show` during a step towards a snapshot**: `in_flight` names `stepping towards
  snapshot <short>` where it named `stepping towards stage <s>`; the exact words are the
  plan's.

## Requirements *(mandatory)*

### Functional Requirements

**Following leaves the core**

- **FR-001**: The core MUST run no read of any branch on a timer: no Schedule is made by
  any command, no workflow reads a branch, and the worker MUST serve four workflows
  (provision, destroy, step and rehearse) and the lab's fifteen activities, with no
  reconcile workflow and no control activity.
- **FR-002**: A twin MUST change only by the operator's `twin step` or `twin destroy`:
  after a create from `--branch`, `--stage` or `--snapshot`, an edit of any branch, a
  regeneration of its artifacts and the passing of any time MUST start no run and change
  neither the record nor the lab.
- **FR-003**: `--interval` and `--no-follow` MUST be unknown flags on every command,
  refused before any connection, and the API MUST refuse `interval` and `no_follow` as
  unknown arguments under version `1`, pre-1.0 as at 014, 015, 017 and 018.
- **FR-004**: The rules `follow.interval.invalid`, `follow.flags.conflict`,
  `follow.start.failed`, `follow.stop.failed`, `follow.stopped`, `check.skipped`,
  `rebuild.failed` and `step.target.foreign` MUST go, with the findings step `follow`, the `following` block on
  create and destroy, and the dry run's `follow:` line and `dry_run.follow`;
  `stage.flags.conflict` MUST stop naming `--interval`.
- **FR-005**: `twin destroy` MUST be the destroy workflow alone: it stops nothing first,
  and its document names no following.
- **FR-006**: A rehearsal's baseline MUST stop no following before it builds, so every
  rehearsal's deadline MUST be 30 s shorter than the same plan's before this feature;
  nothing else of the rehearsal, its report or its checks changes.
- **FR-007**: A build MUST NOT write under or read `bundles/.reads/`; the server's take and
  filing under `snapshots/` is the one read path left.

**`twin show`**

- **FR-008**: For a twin whose record names a snapshot, `twin show`'s kind line MUST read
  `kind: snapshot <short> (branch B at T)` when the snapshot's envelope carries an `at`
  and `kind: snapshot <short> (branch B, read at T)` when it does not, keeping the stage,
  the `(stepped from …)` and the rehearsal notes as they are today and dropping "; not
  following". A twin from intent whose record names no snapshot (an earlier build's
  rebuild, or a record of 8) MUST read `kind: snapshot none (branch B at T)` when the
  record carries an `at` and `kind: snapshot none (branch B, read at T)` when it does not,
  with a note that it names no snapshot, so `twin step` refuses it and `twin destroy`
  clears it (analyzed 2026-10-28). `from a bundle`, `diverged` and `none` MUST stay.
- **FR-009**: The show document's kind MUST be one of `none`, `snapshot`, `from_bundle` and
  `diverged`, losing `pinned`, `frozen` and `following`; its following block and last check
  MUST go; runs in flight MUST stay, since the service
  unreachable note and verify's host holder read them.
- **FR-010**: `twin verify`'s first line and its document's twin block MUST name the
  snapshot beside the bundle it names today.
- **FR-011**: "Pinned" MUST survive as a word for a reference with an `at`, never as a
  kind; `--at` on `twin create` and `intent read` MUST keep its meaning and its rules.

**`twin step`**

- **FR-012**: Any twin whose record names a snapshot MUST step, whether built from
  `--branch`, `--stage` or `--snapshot`; a twin whose record names no snapshot (one `twin
  provision <bundle-dir>` built, or one an earlier build's rebuild made) MUST be refused by
  `step.twin.unsteppable` in words that say it names no snapshot.
- **FR-013**: `twin step --snapshot <id|file>` MUST take the same forms as `twin create
  --snapshot`: an id is looked up in the store and refused by `snapshot.unknown` when
  absent; a file is read by the client and sent, refused by `snapshot.id.mismatch` when its
  declared id does not match, and filed under its id. The server MUST compile and file the
  bundle, compute the step and the push plan, read containerlab's plan, and start the step
  workflow with a target side that names no stage, the snapshot id, the bundle id and the
  envelope's branch and `at`; it MUST send no request to the source of truth for such a
  target. `--dry-run` MUST work with `--snapshot` as it does with `--stage`.
- **FR-014**: `twin step --stage <branch>/<label>` MUST name a stage of any proposed
  change, resolved, judged and read under the record's scope as today; `--stage` left out
  MUST mean the next stage of the twin's own proposed change; for a twin that names no
  stage, a target MUST be required and its absence refused before any connection;
  `stage.twin.moved` MUST apply only when the record names a stage of the proposed change
  the target is found in. `--stage` beside
  `--snapshot` MUST be refused before any connection.
- **FR-015**: A twin's scope and mapping MUST be fixed for its life: a target whose
  snapshot names another scope or another mapping than the record's MUST be refused by
  `step.twin.unsteppable`, naming both, before any run, for a `--snapshot` target by its
  envelope and for a `--stage` target through its resolved snapshot.
- **FR-016**: A twin's branch MUST NOT be fixed: a target may be a snapshot of any branch
  or a stage of any proposed change, and after a stepped or unchanged step the record MUST
  name the target's branch, `at`, snapshot, bundle and stage, or no stage for a snapshot
  target; after a diverged step the record's top level MUST stay the previous one's, as
  today.
- **FR-017**: The step-to-nowhere rule MUST stay on bundle equality; `--allow-restart`,
  `--wait`, the phases, `run.in_flight`, `step.twin.diverged` and the record's handling of
  a diverged step MUST be unchanged for a snapshot target.

**The records and the histories**

- **FR-018**: The twin record's rule that a stage implies an intent source MUST be
  reworked so that a `--snapshot` twin stepped to a stage and a stage twin stepped to a
  snapshot both write valid records, under `twin.json` `10`, and the record MUST hold no
  field about following.
- **FR-019**: The show, findings, API and twin schemas MUST move as FR-003, FR-004, FR-008,
  FR-009 and FR-018 say, and every earlier format that a test reads MUST keep a frozen
  copy under its package's `testdata/contracts/`, each still loading.
- **FR-020**: The recorded histories of a cancellation during following and during its
  stop MUST go with their replay cases, and every remaining recorded history MUST replay
  against the workflows as changed.
- **FR-021**: Bundle `5`, CTM `2`, snapshot `1`, the compiler, the three goldens
  (`43d91715…`, `4213b3cf…`, `ecb665f5…`) and the live fixture's compile (`f764e1fa…`,
  from snapshot `576933ec…`) MUST NOT move; nothing on Infrahub's `main`, no fixture, no
  query, template or check changes.

**Tier 3**

- **FR-022**: Tier 3 MUST keep nine cases. Case 5 MUST create from `--branch`, edit the
  branch and show FR-002 live over a wait longer than five minutes, the retired default
  check interval, then `intent read --out` and `twin step --snapshot <file>` twice: once for an
  artifact-only change with the readback and `twin verify` 5a kept, once for a topology
  change. The Schedule assertions in cases 5 and 7 and every `--no-follow` in the script
  MUST go; no case may make a Schedule; the trap's leak check MUST keep refusing a stray
  `fylgja-follow`.

**The decision and the documents**

- **FR-023**: One decision entry, D-062, MUST record that following leaves the core and
  not Fylgja, that the orchestrator may bring it back as take, compare, step, and that
  walking means stepping; it MUST supersede D-012 in the part that says an unpinned twin
  follows its branch, D-026 and D-027 whole, D-007 in its Reconcile and Schedule and D-014
  in its Schedule, each old entry gaining its *Superseded* status and nothing else; it MUST
  list the entries that cite following and stand as history (D-011, D-017, D-023, D-024,
  D-025, D-028, D-032, D-039, D-048, D-049, D-053); D-061 MUST NOT be superseded. The
  constitution MUST NOT be amended, and D-062 MUST say why (clarified 2026-10-28).
- **FR-024**: `contracts/cli.md` and `contracts/api.md` MUST gain their F-026 sections,
  and `api.schema.json`, `findings.schema.json`, `show.schema.json` and `twin.schema.json`
  MUST move with FR-019.
- **FR-025**: `docs/brief.md`, `docs/architecture.md` (§1's claim rewritten for stepping;
  §2, §4.4–§4.7, §6 and §7 where they describe following, the reconcile or the Schedule),
  `docs/glossary.md` (Following, Frozen twin, Interval, `reconcile` (workflow) and
  Schedule (Temporal) removed; Kind, Pinned, Rebuild, Check and Walking twin reworded; the
  two meanings of "follow" separated), `docs/development.md`, `README.md` (the walk-through
  rewritten around a step to a snapshot; "Pinned and frozen twins" removed), the C4 model
  (redrawn, `make diagrams` run), `docs/ideas.md`'s webhook entry, `CLAUDE.md`'s worker
  counts and M4 line, and the roadmap MUST say what is now true.
- **FR-026**: `contracts/cli.md`'s 019 section and the roadmap's Release 0.3 section
  ("Upgrading a 0.2 host", which 0.3's release notes copy at the release's close) MUST say
  to destroy a following twin before upgrading, and the build MUST carry no code for a
  Schedule it would leave behind.

### Key Entities

- **Twin**: the running topology. Built from a snapshot, by `--branch`, `--stage` or
  `--snapshot`, or from a bundle directory. Frozen at its snapshot: changed only by a step
  or a destroy.
- **Snapshot**: unchanged ([D-061](../../docs/decisions.md#d-061)), the core's one input;
  now also the step's target, by id or by file.
- **Step target**: a stage of any proposed change, resolved to a snapshot under the twin's
  scope, or a snapshot given directly. Either compiles to a bundle, which the step diffs
  against the twin's.
- **The twin's provenance**: fixed for life, its scope and its mapping; movable by a step,
  its branch, `at`, snapshot, bundle and stage.
- **Twin record**: names the snapshot, or none; a step's two sides, each with or without a
  stage; nothing about following.
- **Kind (of a twin)**: `snapshot <short> (…)` for every twin from intent, `snapshot none
  (…)` when its record names none; from a bundle; diverged; or none.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A twin built from a branch that is then edited sees no run and no change over
  a wait longer than five minutes, shown live in tier 3's case 5, and by the absence of any
  Schedule and any timer in tier 1; no case of tier 3 leaves or makes a Schedule.
- **SC-002**: The worker registers four workflows and fifteen activities; the tree holds no
  reconcile workflow, no control activity and no code that makes or reads a Schedule,
  found by grep in nothing but the leak check, the decision log, the archive and the
  release notes.
- **SC-003**: `--interval` and `--no-follow` are refused as unknown flags on every command,
  and `interval` and `no_follow` as unknown arguments on the API, in 100% of tier-1 cases.
- **SC-004**: A twin built by each of the three references steps to a snapshot by id and
  by file, and to a stage of its own and of another proposed change; a bundle twin is
  refused; a step to another scope or mapping is refused before any run naming both; each
  in tier 1, and the server's snapshot step from a `fylgja-test-*` branch in tier 2.
- **SC-005**: Every twin whose record names a snapshot shows a kind line of one of FR-008's
  two forms; no kind line says pinned, frozen or following.
- **SC-006**: Every rehearsal deadline is 30 s shorter than before this feature, in 100%
  of tier-1 deadline cases.
- **SC-007**: The three goldens and the live fixture's compile stand unchanged.
- **SC-008**: Tier 2 passes whole without `TestFollowingDetection`; tier 3's nine cases
  pass `E2E-OK`, case 5 on its repurposed flow with verify 5a; the frozen copies load and
  the remaining histories replay.
- **SC-009**: Tier 1 stays under its 45 s budget, uncached.

## Assumptions

- Nothing on Infrahub's `main`, no fixture branch, no query, template or check moves; no
  Infrahub skill applies, since nothing is designed in Infrahub.
- The constitution is not amended: it does not mention following, a reconcile, a Schedule
  or an interval; Principle VIII admits a workflow through a decision entry and one leaves
  through one too, and Principle IX's "Temporal holds run history" becomes exact.
- The plan decides what the brief [leaves to it](brief.md#left-to-the-plan): the step's
  name for a snapshot side; how a stage of another proposed change is found and that
  `stage.twin.moved` applies only when the record names a stage; whether `twin.json` `9`
  becomes `10`; the exact wording of each refusal and of `in_flight`'s line for a snapshot
  target; the frozen
  copies; whether `fylgja-twin`'s timeout moves with the deadline; which branch the
  README's walk-through edits and whether it steps by file or by id; the C4 redraw; and
  the re-estimate. Each is verified before it is relied on.
- Case 5's live proof waits longer than five minutes, the default interval following had,
  so tier 3 grows by about that wait (clarified 2026-10-28).
- The API stays at version `1`: the removals are pre-1.0 and made without a named refusal,
  as the brief decides.
- The orchestrator and any follow it brings back, the API's shape for long operations,
  probes (016) and the NetBox reader (F-025) are out of this feature; 016 is specified
  against a twin that changes only when the operator steps it.
- The brief's [Decided](brief.md#decided) list, settled with the operator on 2026-10-27, is
  not reopened here: walking means stepping; any snapshot twin steps, to a stage or a
  snapshot; case 5 is repurposed; the flags go outright; the kind line names the snapshot;
  upgrade is by release note; another scope or mapping is refused; another branch is
  allowed; `--stage` names a stage of any proposed change and is required for a twin with
  no stage; one decision entry.
