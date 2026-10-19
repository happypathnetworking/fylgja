# Feature Specification: A proposed change rehearsed on a twin

**Feature Branch**: `015-proposed-change-rehearsal`

**Created**: 2026-10-17

**Status**: Draft

**Input**: User description: "SPECIFY_FEATURE_DIRECTORY=specs/015-proposed-change-rehearsal. 0.2, the second of its three specs: a proposed change rehearsed on a twin, as docs/roadmap.md's Release 0.2 section and F-007 and F-008 define it. Read specs/015-proposed-change-rehearsal/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design."

Release 0.2 rehearses a proposed change on a twin before it merges. 014 gave a proposed
change its **stages**: the branch point, the operator's marks, the head. This feature, the
release's second of three, rehearses them. `fylgja twin rehearse` names a proposed change
by its source branch, boots a twin at its first stage, steps the twin through each later
stage with the step's wait, verifies after every one, stops at the first stage that fails,
always destroys the twin, and answers with a **rehearsal report**: a document of its own,
rendered as text and as markdown. Two checks in this repository bring that inside
Infrahub's own change workflow, as F-007 and F-008 define them: `fylgja-step` answers in
seconds with the plan over the stages, and `fylgja-twin` answers in minutes with the
rehearsal, posting the report as a markdown comment on the proposed change, so that a
stage that fails blocks the merge. For the checks to reach Fylgja, the API's server
listens where Infrahub's task workers can reach it, beside loopback. Its settled points are
the brief's [Decided](brief.md#decided) list, restated here only where a requirement needs
the sentence; its four decision entries are the plan's to write after the live
verification, as the roadmap's [Decisions the order
needs](../../docs/roadmap.md#decisions-the-order-needs) names them. The contract stays
`0.2`; the API's version and the findings document's stay `1`, each gaining a member.

Four actors appear below. **The operator** runs the lab host and Fylgja, marks stages by
Infrahub's own means, may run `twin rehearse` from a client by hand, and is also the
**engineer** who opens the proposed change, and the **reviewer** who reads its comment and
its checks in Infrahub's proposed-change view. **Infrahub** runs the two checks in its task
workers when the proposed change is created and when its checks are re-run, and holds what
they write. **Fylgja** reads intent, proposed changes and stages, boots, steps, verifies and
destroys the twin, and writes nothing to Infrahub (Constitution III); the check is the one
writer, of its comment (the brief's Decided; [D-026](../../docs/decisions.md#d-026)).
Probes and loss are the next feature's (`016-probes`), so nothing here measures traffic.

## Clarifications

### Session 2026-10-17

- Q: Which proposed changes does `fylgja-twin` rehearse, given that every proposed change this Infrahub sees runs the checks at its creation, the tiers' throwaway drafts included? → A: Only a proposed change that is not a draft. On a draft it asks Fylgja for nothing, logs that it skipped a draft and concludes success; the engineer marks stages on the draft, marks it ready for review and re-runs the checks. `fylgja-step` runs on drafts too, since it boots nothing.
- Q: What do the rehearsal and `fylgja-step` do with a branch point refused `contract.node.missing`, because `main` holds no network, as the development host's does not? → A: The baseline falls to the first stage that resolves; the refused branch point keeps its row in the report as `stage plan` prints it, and neither check fails for it. Any other refusal of any stage still refuses the rehearsal.
- Q: Is the rehearsal's deadline fixed per check or derived from the stages? → A: Derived: each stage's provision, step and wait budgets, summed from the packages, under a ceiling of Fylgja's own that the live check's timeout exceeds by the destroy and a margin. A proposed change whose deadline cannot fit the ceiling is refused up front, naming the time it needs.
- Q: When `twin rehearse` is asked while a twin that is not a dead rehearsal's holds the host, is it refused at once, with `fylgja-twin` retrying until its deadline, or does Fylgja wait for the host inside the rehearsal? → A: Refused at once, naming what holds the host, as `twin create` is. `fylgja-twin` retries the request until its own deadline, then concludes failure naming the twin. The hand command is refused and does not retry. Fylgja waits for nothing and adds no lock.
- Q: When `fylgja-twin` loses its connection to Fylgja while a rehearsal is running, what does the check conclude, given that the rehearsal goes on to its destroy without it? → A: Failure, saying the connection was lost, that the run goes on to its destroy and that no report will be posted; the engineer re-runs the checks once `twin show` reports no twin. Nothing re-attaches to a run and the server keeps no report (D-040, D-014); a fetch of a past report would be a new decision.
- Q: How does the check obtain the report's markdown: as a third rendering the API serves on request, or as a field inside the report's JSON? → A: A third rendering. `render` gains `markdown` beside `text` and `json`; the markdown rides beside the document in its frame as the text does; `twin rehearse --markdown` prints it; the check posts what comes back. The document itself carries no rendering.
- Q: When the checks are re-run on a proposed change that already carries a rehearsal comment, does `fylgja-twin` add a new comment or replace its earlier one? → A: A new comment each run, never edited or deleted. Each is headed by the run's identity and the time its stages were resolved, so the newest is plain and the history of the proposed change's rehearsals stays readable.
- Q: When only one stage of a proposed change resolves, because nothing is marked and the branch point is refused for want of a network on `main`, does the rehearsal still boot and verify that one stage, or refuse because there is no step to rehearse? → A: Boot and verify the one stage, destroy, and report it as the baseline with a warning that no step was rehearsed; `ok` when its verify is clean, and the check concludes success.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - `twin rehearse`: a proposed change rehearsed on a twin, and reported (Priority: P1)

The operator has built a change on a branch, opened a proposed change on it and marked
its stages, as 014 taught them. Now they want the whole story told on a running twin,
unattended: `fylgja twin rehearse --branch <b>`. Fylgja resolves and compiles every stage
first, as `stage plan` does, so a stage that cannot be built refuses the rehearsal before
anything is booted. Then it creates the twin from the first stage that resolves, the
branch point where `main` carries a network and the first mark where it does not, and
verifies it: the **baseline stage**, whose findings, if any, are what the twin looks like
before the change and are reported as such. Then, for each later stage in order, it steps the twin there,
waits for it to settle and verifies it. A stage passes when its step landed and its verify
found nothing the baseline's did not; it fails when the step left the twin diverged, or
when verify found something new. The rehearsal stops at the first stage that fails, and
whatever happened, the twin is destroyed. The report the operator reads has one row per
stage, says why a stage failed, and, when one did, gives the commands that reproduce it by
hand on the same stages, which outlive the rehearsal.

**Why this priority**: the rehearsal is what both checks ask for, and the release's demo.
Everything else here is how it is reached and reported.

**Independent Test**: on a throwaway branch with a draft proposed change and two marks,
the first the seeded fixture and the second with a third link added and its artifacts
regenerated, `twin rehearse --branch <b>` boots the twin from the first stage Fylgja can
build, steps it to the second mark and to the head, verifies three times, destroys the
twin and prints a report whose rows say `baseline`, `passed`, `passed`; after it `twin
show` reports no twin and `stage list` lists the four stages unchanged. With a stage made
to fail, the report stops at that row, the rows after it read `not reached`, the twin is
still gone, and the commands printed reproduce the failure by hand.

**Acceptance Scenarios**:

1. **Given** a proposed change on branch `b` with two marks whose every stage compiles,
   **When** the operator runs `twin rehearse --branch b`, **Then** the twin is created
   from the branch point, verified, stepped to the first mark, the second mark and the
   head in order, each step followed by its wait and a verify, then destroyed, and the
   report has one row per stage, the first `baseline` and the rest `passed`, exit 0.
2. **Given** a stage whose step leaves the twin diverged, **When** the rehearsal reaches
   it, **Then** the row says `failed` naming the phase and the nodes the push reached, no
   later stage is stepped to and each later row reads `not reached`, the twin is destroyed,
   the report gives the commands that reproduce the step by hand, and the command exits
   non-zero.
3. **Given** a stage after which verify reports a finding the baseline's verify did not,
   **When** the rehearsal verifies it, **Then** the row says `failed` naming the finding,
   the rehearsal stops there, the twin is destroyed, and the command exits non-zero.
4. **Given** a baseline whose verify reports a finding, and later stages whose verifies
   report that finding and no other, **When** the rehearsal runs, **Then** every later
   stage passes, the baseline's finding is reported as the baseline's, and the command
   exits 0.
5. **Given** a mark that is stale, or a reference that resolves to no open proposed
   change, **When** the operator runs `twin rehearse`, **Then** it is refused with 014's
   finding before any twin is booted, and the host is untouched.
6. **Given** `main` holds no network, so the branch point is refused
   `contract.node.missing`, **When** the operator runs `twin rehearse`, **Then** the
   baseline is the first mark, the branch point's row reads `refused` as the plan prints
   it, the rehearsal goes on through the later stages, and a stale mark among them still
   refuses the rehearsal.
7. **Given** the operator interrupts the rehearsal while a step runs, **When** the
   interrupt is delivered, **Then** the step is cancelled as `twin step`'s is, the twin is
   destroyed, the report says the rehearsal was cancelled at that stage, and nothing of
   the twin remains.
8. **Given** a rehearsal whose deadline passes mid-way, **When** the deadline is reached,
   **Then** the destroy begins, the report says the deadline cut the rehearsal at that
   stage and how long each finished stage took, and nothing of the twin remains.
9. **Given** a proposed change whose stages' budgets sum past the ceiling, **When** the
   operator runs `twin rehearse`, **Then** it is refused before any boot, naming the time
   the stages need and the ceiling, and the host is untouched.
10. **Given** `twin rehearse --json`, **When** it ends, **Then** stdout carries one
    findings document, operation `twin.rehearse`, with a `rehearsal` block that validates
    against its contract and carries every fact the text printed and no configuration
    content.

---

### User Story 2 - `fylgja-twin`: the rehearsal from inside Infrahub, as a comment and a conclusion (Priority: P1)

The engineer opens a proposed change in Infrahub as a draft, marks its stages on it, marks
it ready for review and re-runs its checks. `fylgja-twin` leaves a draft alone, saying so,
and on a proposed change that is not a draft asks Fylgja to rehearse it, waits the
minutes it takes, posts the rehearsal report as a markdown comment on the proposed change,
puts the report's text in its own message, and concludes: success when every rehearsed
stage passed, failure when a stage failed or the rehearsal could not run. The reviewer
reads the comment in the proposed-change view: a table with one row per stage, a drawing of
what each step changed, the stages themselves, which Infrahub's own view does not show, the
fidelity caveat, and, on a failure, the commands to reproduce it. A failed check blocks
the merge, as Infrahub's own checks do.

**Why this priority**: this is the release's story, and the reason the rehearsal exists.
F-008.

**Independent Test**: on a throwaway branch with a draft proposed change and two marks,
the check skips the draft at its creation and passes; marked ready for review and its
checks re-run, the check concludes success, and a comment with the report's table and
drawing is on the proposed change; with a stage made to fail, the check concludes failure
at that stage and the comment names it; after both, no twin, no `fylgja-test-*` branch,
proposed change, stage or comment remains.

**Acceptance Scenarios**:

1. **Given** a proposed change whose stages all rehearse clean, **When** Infrahub runs the
   check, **Then** the check concludes success, its message is the report's text, and the
   proposed change carries one comment with the report's markdown: the table, the
   drawing, the stages, the caveat.
2. **Given** a proposed change with a stage that fails, **When** Infrahub runs the check,
   **Then** the check concludes failure, its message and its comment name the stage, why it
   failed and the commands that reproduce it, and the proposed change cannot be merged
   while that conclusion stands.
3. **Given** a rehearsal Fylgja refuses before any boot (a stale mark, a twin that holds
   the host), **When** Infrahub runs the check, **Then** the check concludes failure with
   Fylgja's finding in its message, and posts the report it got.
4. **Given** Fylgja cannot be reached from the task worker, or refuses the token, **When**
   Infrahub runs the check, **Then** the check concludes failure saying so, without a value
   of either variable in its message, and nothing is booted.
5. **Given** a comment that cannot be posted, **When** the check has its report, **Then**
   the failure to post is in the check's message and the conclusion is the rehearsal's,
   not the comment's.
6. **Given** the check's `FYLGJA_API_ADDRESS` or `FYLGJA_API_TOKEN` is unset, **When**
   Infrahub runs the check, **Then** it concludes failure naming the variable, before any
   request.
7. **Given** a draft proposed change, **When** Infrahub runs the check at its creation or
   on a re-run, **Then** it asks Fylgja for nothing, its message says it skipped a draft,
   it concludes success, and no twin is booted.

---

### User Story 3 - `fylgja-step`: the plan in seconds, inside Infrahub (Priority: P2)

The same proposed change also gets the cheap answer. `fylgja-step` asks Fylgja for the plan
over the proposed change's stages, the plan `stage plan` prints, and puts it in its
message as plain text: each stage, its bundle identifier and read counts or its refusal,
and the step between each pair, by name and checksum, never a line of content. It fails
only when Fylgja refuses a stage as intent, refuses the stages, or cannot be reached, a
branch point refused for want of a network on `main` excepted: a plan that compiles lets
the merge proceed. It runs on drafts too. It needs no twin, no worker and no workflow
service, so it answers in seconds and runs wherever a server is reachable.

**Why this priority**: the first time Fylgja appears inside Infrahub's workflow, and the
check the live one builds on. F-007. It works without the rehearsal.

**Independent Test**: on a throwaway branch with a draft proposed change and two marks,
the check runs in Infrahub's pipeline, concludes success, and its message is the plan's
text with four stages and three steps; with a mark made stale, it concludes failure and
its message carries the stale finding naming the device.

**Acceptance Scenarios**:

1. **Given** a proposed change whose stages compile, **When** Infrahub runs the check,
   **Then** it concludes success and its message is the plan's text, the stages in order
   with their bundle identifiers and the steps between them.
2. **Given** a mark marked before its regenerate, **When** Infrahub runs the check,
   **Then** it concludes failure and its message carries `stage.artifact.stale` naming the
   device and both remedies, with the other stages still planned.
3. **Given** `main` has moved since the branch point, **When** Infrahub runs the check,
   **Then** the warning is in its message and the check still concludes success.
4. **Given** Fylgja cannot be reached, **When** Infrahub runs the check, **Then** it
   concludes failure saying so, naming no token.
5. **Given** `main` holds no network, so the branch point is refused
   `contract.node.missing`, **When** Infrahub runs the check, **Then** the refusal is in
   its message as the plan prints it, and the check still concludes success when every
   other stage compiled.

---

### User Story 4 - The server where the task workers reach it, and the host kept clean (Priority: P2)

Infrahub's task workers run on the Compose bridge, where neither the host's loopback nor
`host.docker.internal` reaches the lab host. The server therefore listens on the host's
Docker-bridge address beside loopback, in plaintext, with the one bearer token guarding
it; `fylgja serve --listen` is repeatable, and the start-up report names each address and,
for each off loopback, that the token crosses it in the clear. The Compose override gives
the task workers the host-gateway entry and the two variables a check needs, and the
bring-up script starts the server on both addresses. On the host, a rehearsal that finds a
twin left by a rehearsal whose run is no longer running destroys it before it starts; any
other twin is refused, under Constitution VII, as every command is today.

**Why this priority**: without it neither check reaches Fylgja, and without the reclaim a
dead rehearsal would hold the host until the operator noticed.

**Independent Test**: `fylgja serve --listen 127.0.0.1:7650 --listen <bridge>:7650` reports
both addresses and the plaintext line for the second; `curl` from inside a task-worker
container reaches `/v1/twin/show` with the token and is refused without it; a twin left
by a killed rehearsal is destroyed by the next rehearsal, which says so in its report; a
twin built by hand refuses the rehearsal naming the twin.

**Acceptance Scenarios**:

1. **Given** two `--listen` flags, **When** the server starts, **Then** it listens on both,
   its report names each with the port it got, the bridge address's line says the token is
   sent unencrypted on it, and a request on either is answered alike.
2. **Given** an address that cannot be listened on among several, **When** the server
   starts, **Then** it refuses to start naming that address, exit 2, and listens on none.
3. **Given** the Compose override applied and the server on the bridge address, **When** a
   task worker sends a request with the token, **Then** it is answered; without the token
   it is `401`.
4. **Given** a twin whose record names a rehearsal whose run is no longer running,
   **When** a rehearsal starts, **Then** it destroys that twin first, says so in its report,
   and goes on.
5. **Given** a twin built by hand, a rehearsal in flight, or an orphan lab, **When** a
   rehearsal starts, **Then** it is refused before anything is touched, naming what holds
   the host, as `twin create` is refused today.
6. **Given** the bring-up script's `fylgja` part, **When** it runs on a host it set up,
   **Then** the server it leaves running listens on loopback and the bridge address, its
   report says so, and a second run keeps it.

---

### User Story 5 - The records say what runs (Priority: P3)

A stranger reads the README's proposed-change walk-through and gets a comment on their own
proposed change. The contracts carry the operation, the command and the report's schema;
the architecture and its diagrams show the checks as a client inside Infrahub's task
worker, the rehearsal as a run and the bridge listener; `docs/development.md` says how the
three processes are started with two addresses, what the override does and how the checks
are tested; `docs/verified-facts.md` carries what the plan verified of Infrahub's checks,
comments and pipeline; the glossary defines the rehearsal and its baseline; `SECURITY.md`
states the bridge listener's exposure; the roadmap marks F-007 and F-008 built; and
`CLAUDE.md`'s State and the server's start line say what runs.

**Why this priority**: the records are what the audience reads, and what a later session
acts on.

**Independent Test**: a stranger following the README opens a proposed change on a
throwaway branch, marks two stages, gets both checks' results and the comment, reads the
report by hand with `twin rehearse`, and deletes everything in the order the README gives,
with no leftover; `docs/verified-facts.md` carries every item of the brief's "Infrahub as
read" that the build relies on, with its date.

**Acceptance Scenarios**:

1. **Given** the README, **When** a stranger follows the proposed-change walk-through,
   **Then** they get a rehearsal comment on their proposed change and a `fylgja-step`
   message, and after the walk-through nothing of theirs remains in Infrahub or on the
   host.
2. **Given** the records at the close, **When** a reader greps for the loopback-only
   server, **Then** every sentence that said the server listens on loopback alone says
   where it listens now, and `SECURITY.md` says who can reach the bridge address and what
   guards it.

---

### Edge Cases

- **A stage refused on the way in.** The rehearsal resolves and compiles every stage
  before it boots anything. A stale mark, a mark before the branch point, a reserved
  label, an unknown branch or label: each is 014's refusal, the rehearsal is refused with
  the plan's findings, and the host is untouched. The branch point refused for want of a
  network on `main` is the one exception: the baseline falls to the first stage that
  resolves, and the refused row stays in the report (FR-003).
- **One stage alone resolves.** Nothing is marked and the branch point is refused for want
  of a network on `main`, as at the creation of an unmarked proposed change on this
  install: the head is booted, verified and destroyed, reported as the baseline with a
  warning that no step was rehearsed, `ok` when clean; the engineer who wants the story
  marks stages and re-runs the checks (FR-003).
- **The baseline cannot be built.** The provision fails, by a deploy, a readiness timeout
  or a push the node refuses, and cleans up as every provision does. The report says the
  baseline could not be built and why; no stage is rehearsed; the check concludes failure.
- **A stage whose step could not run.** The step's own `operation.failed` (the bundle
  unreadable, the workflow service lost) is not a verdict on the change: the rehearsal
  ends `error` naming the stage, after its destroy, and the check concludes failure.
- **The deadline.** It is the stages' budgets summed, under Fylgja's ceiling, which the
  check's timeout exceeds, so the destroy runs inside the check (FR-006); a proposed
  change that cannot fit is refused before any boot. A deadline reached mid-step cancels
  the step, which leaves the twin diverged
  ([D-036](../../docs/decisions.md#d-036)), and the destroy follows; the report names the
  stage, the time each finished stage took and the deadline.
- **The operator's interrupt.** The first cancels the run: the current step is cancelled,
  the twin destroyed, the report written. The second stops waiting; the rehearsal goes on
  to its destroy without the client, as every run does.
- **The client goes away.** A check cancelled or timed out by Infrahub, a server
  restarted, a shell closed: the rehearsal goes on, to its deadline at most, and destroys
  its twin. `twin show` names it in flight meanwhile. Its report reaches no one but the
  run's history: the check concludes failure saying so, and the engineer re-runs the checks
  once the twin is gone (FR-021).
- **The worker dies mid-rehearsal.** The run is still in flight on the workflow service
  and its twin stands; a later rehearsal sees a run that is running and is refused. The
  reclaim is for a rehearsal whose run has ended; a run that never ends is the operator's
  to cancel or destroy, as today.
- **The destroy leaves something.** The rehearsal ends `unclean`, exit 4, saying what
  remains and that `twin destroy` clears it. A lab left without a record is an orphan and
  refuses the next rehearsal, as it refuses `twin create`; the reclaim covers a recorded
  rehearsal twin alone.
- **Two rehearsals at once.** Two proposed changes' checks, or the hand command beside a
  check: the second is refused by the fixed run identities and the twin that holds the
  host, as two shells are today. No new lock.
- **A mark written, edited or removed while the rehearsal runs.** The stages are fixed
  when the rehearsal resolves them, and the report says when that was. A stage that no
  longer resolves to what was rehearsed is warned of, as `stage list` warns
  `stage.twin.moved`; a head that moved since is such a stage.
- **A `main` that moved since the branch point.** 014's warning, in the report, refusing
  nothing.
- **The checks re-run.** The engineer fixes a stage and re-runs the checks: a new rehearsal,
  a new comment beside the earlier ones, each headed by its run and when its stages were
  resolved; nothing is edited or deleted, and the newest conclusion is the one that gates.
- **A step that is `unchanged`.** The mark written after the last regenerate steps to the
  head with nothing to apply; the twin is still verified and the row says `unchanged`,
  `passed`.
- **A step that restarts a node.** A cEOS node whose link is added or removed restarts in
  place and returns a minute later. The rehearsal's twin is its own, so the step proceeds
  as with `--allow-restart`, waits for the node and pushes it again; the row names the
  node restarted and the minute it cost.
- **A baseline finding whose object a later stage removes.** A link the change deletes
  carries no assertion at the later stage, so there is nothing to compare; nothing fails.
- **A finding that appears and vanishes.** A finding new at stage 2 fails stage 2, and the
  rehearsal stops there; what stage 3 would have shown is not reached, and the report says
  so.
- **The proposed change closes or merges mid-rehearsal.** Its stages become invisible to
  Fylgja, but the rehearsal's references are already pinned and its branch still exists,
  so it finishes on them; the report's warning says the proposed change is no longer open.
  A source branch deleted under it fails the next read, which ends the rehearsal `error`
  after its destroy.
- **A `main` that carries a network.** On a deployment whose `main` holds intent, the
  branch point compiles and is the baseline: the twin boots `main`'s network and the
  change is rehearsed against it, which is the design. The development host's `main` holds
  none (014's research R-04).
- **A test's proposed change.** Every proposed change this Infrahub sees runs this
  repository's checks, the tiers' throwaway drafts included, since the pipeline runs at
  creation. The tiers open drafts, so `fylgja-twin` skips each and boots nothing, and
  `fylgja-step` plans each in seconds (FR-018); tier 3's new case alone marks its
  proposed change ready for review, and tier 2 boots no twin.
- **The bridge address.** Any container on the host can reach it: Infrahub's, the twin's
  nodes, anything else running there. The bearer check is what guards it, and the token
  is in the task workers' environment, so whoever can inspect those containers or read
  `local/.env` holds it. `SECURITY.md` says so.
- **CI's contract job.** Its Infrahub registers this repository, so its proposed changes
  run both checks, and no server is reachable there: `fylgja-twin` skips each draft and
  passes, `fylgja-step` concludes failure saying the address is unreachable, since the
  override sets both variables and no server listens there, and no tier-2
  assertion reads a user check's conclusion unless the plan starts a server there.

## Requirements *(mandatory)*

### Functional Requirements

**The rehearsal**

- **FR-001**: `fylgja twin rehearse --branch <b>` and the API operation `twin.rehearse`
  (`POST /v1/twin/rehearse`, argument `branch`) MUST rehearse the one open proposed change
  whose source branch is `b`, over its stages as 014 defines them (the branch point, the
  marks by `at`, the head): resolve and compile every stage first; create the twin from the
  first stage it builds, the **baseline stage**, and verify it; then, for each later stage
  in order, step the twin to it with the step's wait and verify it; stop at the first stage
  that fails; destroy the twin whatever happened; and answer with the rehearsal report. It
  is a run: a `start`, a `run`, its `event`s and the document, taking an interrupt from
  `start`. The hand command and the check are refused and answered alike, since every
  refusal is the server's (Constitution XI).
- **FR-002**: A rehearsed stage **passes** when its step ended `stepped` or `unchanged`
  and the verify after its wait reports no finding the baseline's verify did not report,
  a finding being the same when its rule and its object are. It **fails** when its step
  left the twin diverged, or when its verify reports a finding the baseline's did not.
  The baseline stage's own findings MUST be reported as the baseline's and fail nothing.
  A stage after a failed one is **not reached**. A stage whose step could not run or was
  rejected by its locks, whose wait did not complete, or that the deadline or an
  interrupt cut is **`error`**: no verdict on the change, the rehearsal stops there and
  ends `error`, exit 2, after its destroy. The baseline is verified in verify's waiting
  form, under the same budget the step's wait has.
- **FR-003**: Every stage MUST be resolved and compiled before any twin is booted, with
  014's refusals and warnings; a stage refused there MUST refuse the rehearsal, exit 1,
  with the plan's findings, and touch nothing on the host, with one exception: a branch
  point refused `contract.node.missing`, because `main` holds no network, as the
  development host's does not (014's research R-04). Then the baseline falls to the first
  stage that resolves, the refused branch point keeps its row in the report, `refused`, as
  `stage plan` prints it, and neither check fails for it. Any other refusal of any stage,
  the branch point's included, refuses the rehearsal. When one stage alone resolves, the
  rehearsal MUST still boot it, verify it and destroy it, reporting it as the baseline with
  a warning that no step was rehearsed; it ends `ok` when that verify is clean.
- **FR-004**: A step whose plan restarts or recreates a node MUST proceed, as `twin step
  --allow-restart` does, since the rehearsal's twin is its own: the node is awaited and
  pushed again, and the report names each node restarted or recreated and the time it
  cost.
- **FR-005**: The twin MUST be destroyed at the end of every rehearsal: every stage passed,
  a stage failed, a stage could not be stepped, the baseline could not be built, the
  deadline passed, the operator interrupted, the check or the client went away. When the
  rehearsal ends `ok`, `nonconforming`, `failed` or `error`, nothing of the twin remains
  on the host; `unclean` says what remains and that `twin destroy` clears it.
- **FR-006**: A rehearsal MUST have a deadline derived from its stages: the baseline's
  provision budgets and, for each later stage, its step's and its wait's, each the largest
  of that budget over the packages of the nodes it touches (Constitution II), plus the
  destroy's; under a
  ceiling of Fylgja's own, which `fylgja-twin`'s timeout exceeds by the destroy and a
  margin, so that the destroy runs inside the check. A proposed change whose derived
  deadline cannot fit the ceiling MUST be refused up front, naming the time it needs and
  the ceiling. When the deadline passes, the stage in progress is cancelled and the destroy
  begins, and the report says the deadline cut the rehearsal at that stage, how long each
  finished stage took and what the deadline was. The hand command has the same deadline
  and ceiling, since every client is answered alike.
- **FR-007**: One twin at a time (Constitution VII). A twin whose record names a rehearsal
  whose run is no longer running MUST be destroyed before the rehearsal starts, and the
  report MUST say so. Any other twin, lab or run in flight MUST refuse the rehearsal before
  anything is touched, under the refusals every command makes today, naming what holds the
  host and how to clear it. No new lock, and no waiting inside Fylgja: `fylgja-twin`
  retries the refused request until its own deadline, then concludes failure naming the
  twin, posting the last refusal's report as its comment as it posts any report it got;
  the hand command is refused once and does not retry.
- **FR-008**: The rehearsal's twin MUST be known as the rehearsal's: its record and `twin
  show` say it belongs to a rehearsal and name the run, and `twin show` while it runs
  names the rehearsal in flight and the stage the twin is at. `twin destroy` during a
  rehearsal MUST cancel it and wait for its destroy, as it cancels a step today.
- **FR-009**: The rehearsal's status and exit MUST be: `ok`, 0, when every rehearsed stage
  passed, warnings and the baseline's findings notwithstanding; `nonconforming`, 5, when a
  stage failed and the twin was destroyed; `rejected`, 1, when refused before any boot;
  `failed`, 3, when the baseline could not be built and the provision cleaned up; `error`,
  2, when the rehearsal could not run or its deadline cut it, after its destroy; `unclean`,
  4, when its destroy left something. No status, exit or step is new. Every finding,
  warning and notice the rehearsal itself makes MUST have a stable `rehearsal.*`
  identifier (Constitution X), the stage verdicts, the deadline and the reclaim among
  them; the baseline's and each stage's verify findings keep verify's identifiers, and a
  step's keep the step's.
- **FR-010**: The rehearsal MUST write nothing to Infrahub and read no Infrahub-owned kind
  014 does not read (Constitution III); the read-only test holds it. Its report MUST stay
  advisory: no Fylgja operation reads it, and the check maps it to a conclusion
  ([D-039](../../docs/decisions.md#d-039)).
- **FR-011**: The stages MUST be fixed when the rehearsal resolves them, and the report
  MUST say when that was; a stage that no longer resolves to what was rehearsed, the head
  included, MUST be warned of in the report as `stage list` warns of a moved stage, and
  `main` having moved since the branch point MUST be warned of as 014 warns it. Neither
  refuses anything.

**The report**

- **FR-012**: The rehearsal report MUST be the findings document, operation `twin.rehearse`,
  with a `rehearsal` block under a JSON schema of its own in `contracts/`
  (`rehearsal.schema.json`), `findings_version` staying `1`. The block MUST carry: the
  proposed change by id, name, source branch and draft flag; when the stages were
  resolved; the deadline and the time used; whether a dead rehearsal's twin was reclaimed;
  one entry per stage in order, with its reference, its `at` and where the `at` came
  from, its bundle identifier or its refusal, its role (`baseline`, `rehearsed`, `not
  reached`, `refused`), the step into it (outcome, the phase when diverged, the nodes
  restarted or recreated, the timings), its wait (outcome, seconds), its verify's counts,
  the findings new against the baseline, and its verdict (one of FR-002's six); the
  baseline's own findings; the warnings; the destroy's outcome; and, when a stage failed,
  the commands that reproduce
  it. It MUST carry no configuration line, device diff, artifact or bootstrap content,
  token or login (Constitution X).
- **FR-013**: `twin rehearse` MUST print the run's progress line by line as every run
  does, each stage as it is reached, then the report as text: one line per stage with its
  verdict, the baseline's findings, the warnings and the findings, as every findings
  document prints. `--json` prints the document and nothing else on stdout.
- **FR-014**: The report MUST also render as markdown, holding: a heading that names
  Fylgja, the run and when the stages were resolved, so that two comments on one proposed
  change are told apart; a table with one row per
  stage (the reference, the `at`, the bundle identifier, the step's outcome and restarted
  nodes, the wait's outcome, the verify's counts, the new findings, the verdict); a
  Mermaid drawing of the stages and what each step changed (nodes and links added or
  removed, artifacts changed, by name and never a line of content); the fidelity caveat
  (fidelity is asserted, not measured; containers forward in software and keep their own
  timing); 014's warnings; the stages the proposed change has, since Infrahub's view does
  not show them; and, on a failure, the commands that reproduce it by hand: the create from
  the baseline stage, each step to the failed stage, the verify, with the stages'
  references. It is a rendering the API serves on request: `render` gains `markdown`
  beside `text` and `json`, the markdown rides beside the document in its frame as the
  text does, `twin rehearse --markdown` prints it and nothing else on stdout, and the
  document itself carries no rendering. An operation that has no markdown rendering, asked
  for `markdown`, answers as it does for `text`; the plan says whether any other operation
  gains one.
- **FR-015**: The commands the report gives MUST reproduce the failure by hand on the same
  stages: run in order they make the same step and the same verify, since the stages are
  the operator's and outlive the rehearsal.

**The checks**

- **FR-016**: Two global check definitions MUST be in this repository's `.infrahub.yml`,
  `fylgja-step` and `fylgja-twin`, each an `InfrahubCheck` class, imported with the
  repository's read-only registration ([D-044](../../docs/decisions.md#d-044)). Each MUST
  find its proposed change by the source branch Infrahub hands it, among the open ones,
  and reach Fylgja through the API alone, with `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`
  from the task worker's environment and nothing else of Fylgja's (Constitution XI). The
  Python is glue: it finds the proposed change, calls the API, posts the comment and sets
  the conclusion; everything that decides is behind the API.
- **FR-017**: `fylgja-step` MUST ask `stage.plan` for the proposed change and log the
  plan's text as its message. It MUST conclude failure only when the plan refused a stage
  as intent, when the stages could not be listed, or when Fylgja cannot be reached or
  refuses the token or the version; a plan whose every stage compiled passes, warnings
  included. A branch point refused `contract.node.missing` for want of a network on
  `main` is not such a refusal (FR-003): the plan's other stages decide. This exception
  is the one rule the check holds beyond a status mapping, since `stage plan` is 014's
  and refuses that branch point; it reads the finding's rule and the stage's `at_source`
  and nothing else. It runs on every open proposed change, draft or not.
- **FR-018**: `fylgja-twin` MUST ask `twin.rehearse` for the proposed change, post the
  report's markdown as one comment on the proposed change, log the report's text as its
  message, and conclude as FR-022 says: success when the rehearsal ended `ok`, failure
  on every other status and when Fylgja was unreachable. It MUST rehearse a proposed
  change that
  is not a draft alone: on a draft it asks Fylgja for nothing, logs that it skipped a draft
  and concludes success, so the engineer marks stages on the draft, marks it ready for
  review and re-runs the checks, and the tiers' throwaway drafts boot nothing.
- **FR-019**: A comment that cannot be posted MUST be logged, without a credential, and
  MUST NOT fail the check; the conclusion is the rehearsal's. Each run posts a new comment
  and never edits or deletes one: a re-run adds its comment beside the earlier ones, each
  headed by its run and the time its stages were resolved. The checks MUST write nothing
  else to Infrahub: no stage, no series, no object, no edit. The comment is the check's
  write, not Fylgja's ([D-026](../../docs/decisions.md#d-026)).
- **FR-020**: A check whose `FYLGJA_API_ADDRESS` or `FYLGJA_API_TOKEN` is unset MUST
  conclude failure naming the variable, before any request, and MUST echo no value of
  either; `fylgja-twin` decides the draft skip first, since it needs nothing of Fylgja's
  for it. CI's contract job runs no server: its `fylgja-step` says so, and its
  `fylgja-twin` skips the tier's drafts.
- **FR-021**: The checks MUST wait for their answer: `fylgja-twin`'s timeout is long
  enough for the rehearsal's ceiling, its destroy and a margin, and `fylgja-step`'s for
  the plan. `fylgja-twin` MUST close its answer by a deadline of its own, short of its
  timeout: it interrupts the run, reads the answer to its document or its cut, and
  concludes failure saying the run was asked to cancel. A check Infrahub times out leaves
  its validator `in_progress` and the merge blocked with no conclusion, so the check's
  deadline, not Infrahub's, is what ends a rehearsal that overruns. A check Infrahub
  cancels MUST ask its run to cancel with a blocking call, since nothing is awaited in
  that handler, and the rehearsal's deadline MUST cover the case where it cannot (FR-005,
  FR-006). The check's own deadline MUST be at least the ceiling, the destroy's whole
  budget and the time the server spends before `start` (the plan, a reclaim, the host
  check), so that a rehearsal which uses every budget is never interrupted by its own
  check.
  A check whose connection to Fylgja is lost mid-rehearsal MUST conclude failure saying the
  connection was lost, that the run goes on to its destroy and that no report will be
  posted; nothing re-attaches to the run and no past report is fetched
  ([D-040](../../docs/decisions.md#d-040)), so the engineer re-runs the checks once `twin
  show` reports no twin.
- **FR-022**: `fylgja-twin`'s conclusion MUST be the mapping of the rehearsal report's
  status alone: `ok` is success, every other status is failure. Nothing else is read into
  it, and Fylgja's verdicts stay advisory. `fylgja-step` maps `stage plan`'s status the
  same way, with FR-017's one exception, which is the only rule either check holds.
- **FR-023**: Neither check's message nor the comment MUST carry a credential, a
  configuration line or a device diff.

**The server and the host**

- **FR-024**: `fylgja serve --listen` MUST be repeatable: the server listens on every
  address given, refuses to start naming the first it cannot listen on, exit 2, listening
  on none, and its report names each address with the port it got and, for each that is
  not loopback, a line straight after it saying the token is sent unencrypted on it. One
  token guards every address.
- **FR-025**: The Compose override (`scripts/infrahub/docker-compose.override.yml`) MUST
  give the task workers a `host-gateway` entry, `FYLGJA_API_ADDRESS` as the name that
  entry resolves (`host.docker.internal:7650`, since `local/.env`'s address is the host's
  loopback and reaches nothing from a container) and `FYLGJA_API_TOKEN` as
  `${FYLGJA_API_TOKEN}`, read by Compose from `local/.env`, the token the one the server
  reads, and nothing else of Fylgja's; it MUST hold no secret value. `.env.example` MUST
  document the address a check uses.
- **FR-026**: The bring-up script's `fylgja` part MUST start the server on loopback and on
  the host's Docker-bridge address, the one the task workers' `host-gateway` resolves to,
  verify its report names both, and say the token crosses the bridge in the clear; a
  second run keeps it. `CLAUDE.md`'s start line for the server MUST do the same, and
  `docs/development.md`'s three-process paragraph MUST say how the bridge address is
  found.
- **FR-027**: `SECURITY.md` MUST state the bridge listener's exposure: any container on the
  host can reach the API, the twin's nodes included; the bearer check is what guards it;
  the token is in the task workers' environment and in `local/.env`, so whoever can
  inspect those containers or read that file holds it; no TLS; one token with no roles, the
  revisit [D-042](../../docs/decisions.md#d-042) names for the check inside Infrahub
  consciously deferred.

**Tests and tiers**

- **FR-028**: Tier 1 MUST cover, with no infrastructure and within its budget: the
  classification against the baseline (a finding the baseline had, one it did not, one
  the baseline alone had, a divergence, a stage not reached); the report, its text and its
  markdown (the table, the drawing, the caveat, the warnings, the commands); the status
  mapping; the deadline derived from the stages' budgets, a proposed change too long for
  the ceiling refused up front, and the deadline cutting each phase with the destroy still
  run; the reclaim rule
  (a dead rehearsal's twin destroyed; a live rehearsal, a hand twin and an orphan lab
  refused); `--listen` repeated and its report; the rehearse workflow under Temporal's
  test suite, every outcome, the destroy on every failure and cancellation path; the
  operation's frames valid against the API's schema; the client's command and its
  renderings; and the boundary test still holding.
- **FR-029**: Tier 2 MUST, against the real Infrahub, on a throwaway `fylgja-test-*`
  branch with a draft proposed change and two stages, prove `fylgja-step` runs inside
  Infrahub to a pass (conclusion success, message the plan's text, the branch point's
  refusal in it) and to a failure on a stage Fylgja refuses (a stale mark), prove
  `fylgja-twin` skips the draft and concludes success, and prove the rehearsal's up-front
  refusals as `stage plan` refuses; no twin is booted, as always in tier 2; the test
  deletes the
  stages, the proposed change and the branch in order. Where the task workers can reach
  no server, the test MUST say so, by skipping or by starting one, as the plan decides.
- **FR-030**: Tier 3 MUST gain a ninth case: a throwaway branch with a draft proposed
  change and two stages, `fylgja-twin` having skipped the draft at its creation, then
  marked ready for review and its checks re-run, so that `fylgja-twin` rehearses it; the
  check concludes success, the comment is on the proposed change with the table and the
  stages, and the message carries the text; then a stage made to fail, by a means the
  plan chooses, fails
  the check at that stage, the comment naming it and the commands, the later stages not
  reached; after the case no twin, no `fylgja-test-*` branch, proposed change, stage or
  comment remains; the run ends `E2E-OK` whole, nine cases, the new one's two twins
  beside the seven; the case runs only once the checks are on `origin`'s `main` and
  imported on the host's registration, which the operator does, and fails naming that
  before; `PLATFORMS=nokia_srlinux` runs the new case too, since it needs
  SR Linux alone; the credential and marker greps extend to the comment and the checks'
  messages.
- **FR-031**: No golden, no fixture identifier, no bundle, CTM, PSP or contract format
  MUST move; the API's version stays `1` with its new operation, the findings document's
  stays `1` with its new block; the twin record moves only if the rehearsal's mark on it
  needs a field, with a frozen copy for the tests of older records, as 014 did.

**The records**

- **FR-032**: [contracts/api.md](../../contracts/api.md) MUST gain `twin.rehearse` (its
  path, arguments, frames and interrupt), the `markdown` rendering and the repeatable
  `--listen`;
  [contracts/cli.md](../../contracts/cli.md) the command, its statuses and identifiers, the
  two checks' conclusions and what each needs; `api.schema.json` and the new
  `rehearsal.schema.json` the shapes.
- **FR-033**: At the close, [docs/architecture.md](../../docs/architecture.md) and its C4
  model (redrawn in the same change: the checks as a client inside Infrahub's task worker,
  the rehearsal, the bridge listener), [docs/development.md](../../docs/development.md)
  (the three processes on two addresses, the override, how a check change reaches
  Infrahub and how the checks are tested), [docs/verified-facts.md](../../docs/verified-facts.md)
  (every item of the brief's "Infrahub as read" the build relies on, verified), the
  [glossary](../../docs/glossary.md) (rehearsal, baseline stage and baseline finding,
  distinguished from M11's baseline, the checks, the bridge listener), `SECURITY.md`, the
  [README](../../README.md) (the proposed-change walk-through), the
  [roadmap](../../docs/roadmap.md) (F-007 and F-008 built, F-007's row reworded to what
  the check does), `.env.example` and `CLAUDE.md`'s State, Formats and server start line
  MUST describe what runs.
- **FR-034**: The decision entries the roadmap names for 015 MUST be written by the plan
  after the live verification, each as a new entry: the check as the writer of a comment
  beside D-026; the server listening on the Docker bridge, superseding D-042's loopback
  default for this deployment; `twin rehearse` as a fifth workflow beside the four
  (Constitution VIII); and how the check maps the report to a conclusion with Fylgja's
  verdict advisory (D-039). The constitution is amended only where an entry requires it.
- **FR-035**: Nothing this feature writes (a report, a comment, a message, a log line, the
  override, the script's output, a test's output) MUST carry a token, a login, a password
  or Infrahub's secret key.

### Key Entities

- **Rehearsal**: one run of `twin rehearse` over one proposed change: its stages resolved
  and compiled, a twin created from the baseline stage and verified, stepped to each later
  stage and verified, stopped at the first failure, destroyed, reported. Run by the
  operator's hand or by `fylgja-twin`.
- **Baseline stage**: the first stage of the proposed change that resolves, from which the
  twin is created: the branch point where `main` carries a network, the first mark where
  it does not. Its verify's findings are the **baseline findings**: what the twin looks
  like before the change, reported and never failing anything. Not M11's *baseline*, a
  node's deploy configuration; the glossary keeps both apart.
- **Stage verdict**: `baseline`, `passed`, `failed` (by divergence or by a finding the
  baseline did not have), `error` (the step could not run or was rejected, the wait did
  not complete, or the deadline or an interrupt cut the stage; nothing was learned about
  the change), `not reached` or `refused`; one per stage of the rehearsal.
- **Rehearsal report**: the findings document of `twin.rehearse` with its `rehearsal`
  block, rendered as text (the check's message, the CLI's output) and as markdown (the
  comment), both from the one document.
- **Check (Infrahub)**: a check definition this repository ships, run by Infrahub's task
  worker on a proposed change at its creation and on a re-run, concluding success or
  failure with a message. A client of the API. Not the *check* of a following twin.
- **`fylgja-step`**: the pure check: the plan over the stages, in seconds, failing only on
  a refusal or on Fylgja unreachable.
- **`fylgja-twin`**: the live check: the rehearsal, in minutes, its report as a comment,
  failing on a failed stage or a rehearsal that could not run.
- **Comment**: the one write the checks make in Infrahub, a markdown comment on the
  proposed change carrying the rehearsal report.
- **Deadline**: the time a rehearsal may run before its destroy begins: its stages'
  provision, step and wait budgets summed from the packages, under Fylgja's ceiling, which
  the live check's timeout exceeds by the destroy and a margin.
- **Reclaim**: the destroy, before a rehearsal starts, of a twin a rehearsal left behind
  whose run is no longer running.
- **Bridge listener**: the server's address on the host's Docker bridge, beside loopback,
  where Infrahub's task workers reach the API in plaintext under the one token.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A proposed change with two marks rehearses as its stages in order, a twin
  created from the first stage Fylgja builds and stepped through every later one, with a
  verify after each, and the report has exactly one row per stage, in the plan's order.
- **SC-002**: No twin remains after any rehearsal, whichever way it ended (every stage
  passed, a stage failed, refused after a reclaim, cut by the deadline, interrupted, its
  client gone): `twin show` reports none once the rehearsal's run has ended, in every
  tier-3 and hand case, and an `unclean` end says what remains.
- **SC-003**: A stage that fails stops the rehearsal at that stage every time: no later
  stage is stepped to, each later row reads `not reached`, the check concludes failure,
  and the commands the report gives reproduce the failure by hand on the same stages.
- **SC-004**: The baseline's findings never fail a stage: a proposed change whose baseline
  verify reports findings and whose later stages add none ends `ok`, and its check
  concludes success.
- **SC-005**: `fylgja-step` concludes within a minute on the fixture's three-node branch
  with two marks, with no twin, worker or workflow service involved.
- **SC-006**: `fylgja-twin` concludes inside its timeout every time, with the destroy
  inside it; on the development host the fixture's three nodes and two marks rehearse in
  under fifteen minutes.
- **SC-007**: After a rehearsal through the check, Infrahub holds one new comment on the
  proposed change and nothing else of Fylgja's or the check's: the stage and proposed
  change counts are what the operator left, and every read Fylgja made is a query.
- **SC-008**: No report, comment, check message, log line, record or run history carries
  the API's token, Infrahub's token, a login, a password or the secret key: tier 3's
  greps, extended to the comment and the messages, find none.
- **SC-009**: A request from inside a task-worker container reaches the API on the bridge
  address with the token and is refused without it, and the server's start-up report says
  the token crosses that address in the clear.
- **SC-010**: Tier 1 passes with no infrastructure within its budget; tier 2 passes
  against the real Infrahub with both checks' cases, its drafts skipped by `fylgja-twin`,
  booting no twin and leaving no
  `fylgja-test-*` branch, proposed change or stage; tier 3 ends `E2E-OK` with nine cases
  and nine twins, and `E2E-PARTIAL` narrowed to SR Linux with the new case run.
- **SC-011**: The three goldens, the live fixture's identifier, the bundle, CTM, PSP and
  contract formats, the API's version and the findings document's version do not move;
  only the operation, the block, the command, `--listen` and the record's rehearsal mark
  are added.
- **SC-012**: A stranger following the README's proposed-change walk-through gets both
  checks' results and the rehearsal comment on a proposed change of their own, and leaves
  nothing behind.

## Assumptions

- **A twin that exists and is not a dead rehearsal refuses the rehearsal at once** (the
  brief's open question 1, settled in clarify): under Constitution VII and with no new
  lock ([D-040](../../docs/decisions.md#d-040)), the rehearsal is refused as every command
  is, naming what holds the host, and `fylgja-twin` retries within its own deadline before
  it concludes failure naming the twin. The rehearsal does not wait for the slot inside
  Fylgja.
- **The markdown is a third rendering** (the brief's open question 3, settled in
  clarify): `render` gains `markdown` beside `text` and `json`, the markdown rides beside
  the document in its frame as the text does, `twin rehearse --markdown` prints it, and
  the check posts what comes back. The alternative, a field of the report's JSON holding
  the markdown, would put a rendering inside the document, which no findings document
  does.
- **Restarts are allowed and the wait is the default.** `twin rehearse` takes no
  `--allow-restart` and no `--wait`: a rehearsal's twin is its own, so a restart loses
  nothing the operator kept, and each wait is the step's default budget. It has no dry run:
  `stage plan` is the rehearsal's dry run.
- **A failed stage ends `nonconforming`**, exit 5, whether it failed by divergence or by a
  new finding, since the twin is destroyed either way and the report says which; a
  diverged twin's verify fails its record claims in any case. `failed` keeps its meaning
  for a baseline that could not be built, `error` for a rehearsal that could not run or
  was cut, `unclean` for a destroy that left something. No new status.
- **"Baseline" is already a term.** M11's *baseline* is the configuration containerlab
  leaves on a node at deploy. This spec says *baseline stage* and *baseline finding*, and
  the glossary entry for the rehearsal distinguishes them in the same change.
- **The brief wins over the roadmap's F-007 row** where they differ: `fylgja-step` logs
  the plan as plain text and posts no comment; `fylgja-twin` posts the one comment. The
  roadmap's row is reworded at the close.
- **The checks' Python is Infrahub's runtime**, as the Jinja template is (Constitution I),
  and stays glue: no stage, verdict, deadline or report is decided in it. The decisions
  are Go behind the API and tested at tier 1.
- **Infrahub as read holds until the plan verifies it**: a global check runs once with
  the source branch as `branch_name` and an authenticated client; its timeout is the
  class's attribute; its result is one `CoreStandardCheck` whose message is plain text;
  every validator but the data one must succeed before a merge, so a failed check blocks
  it; comments render GitHub-flavoured markdown and Mermaid; the pipeline runs at creation
  and on a re-run, never on a branch edit; no secret reaches a check but by the task
  worker's environment; `host.docker.internal` does not resolve on the Compose bridge and
  `host-gateway` is the way. Each is verified on a throwaway proposed change at the plan
  and recorded in `research.md` and `docs/verified-facts.md` before a requirement rests on
  it. A requirement a verification contradicts is re-planned, not forced.
- **The task workers reach the host by `host-gateway`**, and the address the server
  listens on is the one that name resolves to inside the container; the bring-up script
  reads it from Docker rather than hard-coding it. Verified at the plan.
- **The one token grants the check everything.** The check needs `stage.plan` and
  `twin.rehearse` and holds the token that does everything; D-042's revisit for a client
  that needs less is deferred, and `SECURITY.md` says so.
- **The report fits a comment and a message.** Whether Infrahub bounds either is verified
  at the plan; a report that must be cut keeps the table and the verdicts and says what
  was cut.
- **Tier 3's new case reaches the server the task workers reach**, the one the bring-up
  script leaves running on the bridge with `local/.env`'s token, not the loopback server
  the script starts for its own commands; the run therefore needs that server, as it needs
  the worker, and the plan decides whether the script starts one of its own instead.
- **The development host's `main` holds no network**, so its branch point is refused
  `contract.node.missing` (014's research R-04), every rehearsal there starts from the
  first mark and neither check fails for it (FR-003); a deployment whose `main` carries
  the network starts from the branch point.
- **The ceiling is Fylgja's own**, the operator's patience as the wait budget is
  ([D-039](../../docs/decisions.md#d-039)), not a package field; its value and the checks'
  timeouts are the plan's, set after the fixture's rehearsal is measured. The plan sets
  the ceiling at 3,600 s, `fylgja-twin`'s timeout at 4,200 s and its own deadline 180 s
  short of that.
- **Marking a proposed change ready for review starts no pipeline** (verified at 014:
  `is_draft` set to `false` starts nothing), so the engineer re-runs the checks from the
  proposed-change view, or runs `twin rehearse` by hand, once the draft is marked ready;
  tier 3's new case does the same through the fixture tool, with flags the plan names.
- **How the checks are tested before they are on `origin`'s `main`** is the plan's,
  since the registration imports from there alone: a second, test-only registration or
  another means, and whether CI's contract job starts a server the task workers can
  reach or the live check's test skips there and says so.
- **The decision entries** the roadmap names for 015 are written by the plan after the
  live verification, as 014's were; this spec names what each decides and nothing is
  decided here that one would.
