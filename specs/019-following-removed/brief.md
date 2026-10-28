# Specify brief: 0.3 spec 3 of 5: following removed from the core (F-026)

This is what `/speckit-specify` reads for roadmap F-026, the third spec of
[Release 0.3](../../docs/roadmap.md#release-03). It was written on 2026-10-27, while 018
closed, from an inventory of the tree and eight questions put to the operator the same day.
It was re-read against 018's close, at `c8d46c7` on 2026-10-28. **A core fed snapshots does not read a branch on a timer**: following leaves
the core, and a twin is frozen at its snapshot until the operator steps it. F-026 is placed
before 016 so that probes are specified against a twin that cannot rebuild itself. The
session verified nothing live; the plan verifies each point before relying on it. Specify
what the operator gets, not a new design.

The prompt:

```
SPECIFY_FEATURE_DIRECTORY=specs/019-following-removed GIT_BRANCH_NAME=019-following-removed. 0.3, the third of its five specs: following removed from the core, as docs/roadmap.md's F-026 and Release 0.3 section define it. Read specs/019-following-removed/brief.md first: it holds what changes, the decisions to treat as settled, the questions left for clarify, the exit criteria and every record to read. Specify what the operator gets, not a new design.
```

## Why

- **The reconcile is the core's last reader of a branch.** Since 018, every workflow the
  core runs but the reconcile starts with a snapshot id and a bundle id
  ([D-061](../../docs/decisions.md#d-061)). `ReadIntent`, `Compile` and `RunsInFlight` have
  no caller but [provision/workflow_reconcile.go](../../internal/provision/workflow_reconcile.go);
  `bundles/.reads/` is theirs alone; and provision's own read-and-compile branch is dead,
  since all four of the server's `ProvisionInput`s set a bundle id and none of the nine
  recorded histories schedules either activity (018 research R-10). Until the reconcile
  goes, the production shape's core still knows a branch.
- **A twin that rebuilds itself is the wrong ground for probes.** 016 measures loss across
  a step on a running twin. A twin that a Schedule may tear down and rebuild between two
  measurements, on a branch edit the operator did not make, makes that measurement
  ambiguous. 016 should be specified against a twin that changes only when the operator
  steps it.
- **Following leaves the core, not Fylgja.** The
  [production shape](../../docs/roadmap.md#the-production-shape) gives following to the
  orchestrator, which may bring it back as take, compare, step, and for NetBox
  ([F-025](../../docs/roadmap.md#f-025)) by push on an event rule. What the core keeps is
  the step, which that orchestrator would call.

## Where the shape is fixed

- **The roadmap's [F-026](../../docs/roadmap.md#f-026)** and the
  [Release 0.3 section](../../docs/roadmap.md#release-03), written on 2026-10-27. This
  brief differs from the F-026 paragraph in two places, both settled with the operator on
  2026-10-27 and owed back to it ([Exit](#exit)): tier 3's case 5 is **repurposed** as a
  step to a snapshot rather than deleted, and "walking" is **redefined** as stepping.
- **[D-012](../../docs/decisions.md#d-012)**, the intent reference `(branch, at?)`:
  superseded only in the part that says an unpinned twin follows its branch. The reference,
  `observed_at` outside the bundle, and the six-digit `at` stand.
- **[D-026](../../docs/decisions.md#d-026)**, following by a scheduled read and compare, and
  **[D-027](../../docs/decisions.md#d-027)**, `--no-follow` as the opt-out: superseded whole.
- **[D-007](../../docs/decisions.md#d-007)**, short workflows with fixed ids: superseded in
  its Reconcile, its Schedule `fylgja-follow` and its workflow count. Short workflows with
  fixed ids stand.
- **[D-014](../../docs/decisions.md#d-014)**, state in containerlab, files and Temporal:
  superseded in "Temporal holds … the Schedule `fylgja-follow`". Temporal holds run history
  alone afterwards, which is what Constitution IX already says.
- **[D-061](../../docs/decisions.md#d-061)**, the snapshot as the core's one input, and its
  sentences that wait for this feature: "every workflow the core runs but the reconcile",
  "a twin built from a snapshot is frozen by rule", and "the reconcile workflow is
  untouched until F-026".
- **[D-045](../../docs/decisions.md#d-045)** to **[D-048](../../docs/decisions.md#d-048)**,
  stages and stepping, and **[D-049](../../docs/decisions.md#d-049)** to
  **[D-053](../../docs/decisions.md#d-053)**, the rehearsal: unchanged, except that the
  rehearsal's baseline stops no following.
- **[D-013](../../docs/decisions.md#d-013)**, one twin at a time, and the name it uses:
  kept, with "walking" redefined ([Decided](#decided)).
- **[Constitution 2.2.0](../../.specify/memory/constitution.md)** does not mention following,
  reconcile, a Schedule or an interval (read on 2026-10-27), so it is **not amended**. VIII
  admits a workflow through a decision entry, and one leaves through one too. IX's "Temporal
  holds run history" becomes exact rather than an understatement.

<a id="what-changes"></a>
## What changes, and nothing else

1. **The reconcile goes.**
   - [provision/workflow_reconcile.go](../../internal/provision/workflow_reconcile.go) goes,
     with the Schedule `fylgja-follow`, the workflow type `Reconcile` and the id prefix
     `fylgja-reconcile-`.
   - Three of its helpers are used elsewhere and move first: `withoutPresence` (the step,
     and `WithoutPresence`, which `server/step.go` calls), and `alreadyStarted` and
     `childStartRefusal` (the rehearsal).
   - `ControlActivities` goes whole: `ReadIntent`, `Compile`, `RunsInFlight`,
     `StartFollowing` and `StopFollowing`. `StoreMismatchMessage` stays, since the server's
     filing uses it.
   - `bundles/.reads/` goes, with `intent.ErrBranchNotFound`'s one consumer.
   - Provision's dead read-and-compile branch goes, and so do `ProvisionInput.Follow` and
     `.StopFollowing`, `ProvisionResult.Following`, the follow options and the constants
     `DefaultInterval`, `MinInterval`, `FollowCatchupWindow`, `FollowJitter` and
     `FollowBudget`.
   - **The worker serves four workflows and fifteen activities**: provision, destroy,
     step and rehearse, and the lab's fifteen.
2. **Destroy stops nothing first.** The server's step 1a and the client's second stop
   (`client.go`'s `stopFollowing`, `FollowStopError`) go, and so does destroy's
   `following.stopped` in its document. `twin destroy` is the destroy workflow alone.
3. **The rehearsal's baseline stops no following.** `StopFollowing` leaves its provision
   input, and `rehearsal.Deadline` loses its `Follow` term, so every rehearsal's
   `deadline_s` drops by `FollowBudget`, 30 s.
4. **`--interval` and `--no-follow` are removed outright.**
   - In the CLI they become unknown flags.
   - The API refuses `interval` and `no_follow` as unknown arguments, under version `1`,
     pre-1.0 as at 014, 015, 017 and 018.
   - The rules `follow.interval.invalid`, `follow.flags.conflict`, `follow.start.failed`,
     `follow.stop.failed`, `follow.stopped`, `check.skipped` and `rebuild.failed` go, with
     the findings step `follow`.
   - `stage.flags.conflict` stops naming `--interval`.
   - The dry run loses its `follow:` line and `dry_run.follow`.
5. **`twin show` names the snapshot the twin was built from.**
   - The kind line is `kind: snapshot <short> (branch B at T)` when the snapshot's envelope
     carries an `at`, and `kind: snapshot <short> (branch B, read at T)` when it does not.
     It keeps today's stage, `(stepped from …)` and rehearsal notes, without "; not
     following".
   - `from a bundle`, `diverged` and `none` stay.
   - The show document's `kind` enum loses `pinned`, `frozen` and `following`. Its
     `following` block, its `last_check` and the service reads behind them (`Following`,
     `LastCheck`) go.
   - Runs in flight stay, since `show.service.unreachable` and verify's host holder read
     them.
   - "Pinned" survives as a word for a reference with an `at`, never as a kind.
   - 018's deferred item moves with the line: `verify.twin.bundle_id`, which names the
     bundle alone, names the snapshot beside it (018 research R-21).
6. **`twin step` steps any twin whose record names a snapshot**, to `--stage <ref>` or to
   `--snapshot <id|file>`.
   - **What steps:** a twin built from `--branch`, `--stage` or `--snapshot` steps.
   - **What stays refused:** a twin `twin provision <bundle-dir>` built names no snapshot
     and stays `step.twin.unsteppable`, worded for that reason.
   - **The guard relaxed** is `provision.Ineligible`'s `Stage == nil` case
     ([workflow_step.go](../../internal/provision/workflow_step.go)), together with its
     message and `origin()`, which has no snapshot case today.
   - **`--snapshot` takes the same forms as on create.** An id is looked up in the store and
     refused as `snapshot.unknown` when it is absent. A file is read by the client and sent,
     and refused as `snapshot.id.mismatch` when its declared id does not match. Either way it
     is filed under its id.
   - **The server's snapshot path** skips the stage resolution (`stages.Find`,
     `stages.Target`, `stages.Build`). It compiles and files, then starts the step workflow
     with a to-side of `{stage: null, snapshot_id, bundle_id, at, branch}` from the
     envelope.
   - **Scope and mapping are the twin's for life.** A target whose snapshot names another
     scope or mapping than the record is refused with `step.twin.unsteppable`, naming both,
     before any run. This applies to a `--snapshot` target, and to a `--stage` target
     through its resolved snapshot. Every read a step makes is already under the record's
     scope (`stepScopeUnknown` in [server/step.go](../../internal/server/step.go)), and a
     diverged step keeps the record's provenance. To change scope, destroy and create.
   - **The branch is not the twin's for life.** A target may be a snapshot of any branch,
     or a stage of any proposed change, and after the step the record names the target's
     branch. So `--stage <branch>/<label>` names a stage of any proposed change. Left out,
     it means the next stage of the twin's own proposed change, as today. For a twin with no
     stage it is required, and leaving it out is refused.
   - **The step's sides already allow a null stage** (`step.schema.json`'s `side`).
   - **The record's rules must be reworked:**
     - `twin.schema.json` says "a stage implies `source: intent`", so a `--snapshot` twin
       stepped to a stage breaks it.
     - `NewStepRecord` keeps `Source`.
     - `SameStage` and `notPlannedFrom` already handle a null stage.
   - **The step-to-nowhere rule stays on bundle equality**, as at 018.
7. **Tier 3's case 5 becomes a step to a snapshot.**
   - The case creates from `--branch`, edits the branch, and then asserts the feature's one
     exit criterion: over an interval longer than the retired default check, no run
     starts, and the kind line and record are unchanged.
   - It then runs `intent read --out` and `twin step --snapshot <file>`, once for an
     artifact-only change, with the readback and `twin verify` 5a (M12's skipped-port
     coverage) kept, and once for a topology change.
   - The Schedule's asserts in cases 5 and 7 go. The trap's leak check keeps refusing a
     stray `fylgja-follow`, for a host upgraded with a following twin up.
   - Every other `--no-follow` in the script goes: case 1's create, the refused second
     create, the orphan's dry run and case 6's create, plus the header comment.
   - **Tier 3 keeps nine cases.**
8. **Tests that go whole:**
   - [workflow_reconcile_test.go](../../internal/provision/workflow_reconcile_test.go) and
     [activities_test.go](../../internal/provision/activities_test.go).
   - [internal/stage/following_contract_test.go](../../internal/stage/following_contract_test.go),
     tier 2's `TestFollowingDetection`.
   - The histories `cancel-during-follow` and `cancel-during-stop-following`, with their
     replay cases.
   - The following functions in cli, server and provision, about 1,300 lines by the
     inventory.

   The other recorded histories must still replay against the workflows as changed.
9. **"Follow" keeps its other meaning.** A client following a run (`Service.Follow`,
   `server/follow.go`'s `followRun`) streams its progress, and stays: only `follow.go`'s
   `StopFollowing` lines and its `provisionReport` lines about following go. The glossary
   separates the two words, and keeps "reconcile" for containerlab's step phase alone.
10. **The decision entry**, one, D-062: following leaves the core.
    - It supersedes D-012 in part, D-026 and D-027 whole, D-007 in its Reconcile and
      Schedule, and D-014 in the Schedule. Each old entry gains its *Superseded* status and
      nothing else.
    - It says following leaves the core and not Fylgja: the orchestrator may bring it back
      as take, compare, step.
    - Entries that cite following stand as history and are listed in D-062's context:
      D-011, D-017, D-023, D-024, D-025, D-028, D-032, D-039, D-048, D-049, D-053.
    - D-061's sentences on the reconcile and on a snapshot twin frozen by rule become
      universal; D-061 is not superseded.
11. **The documents:**
    - **[docs/brief.md](../../docs/brief.md):** Scope, Pipeline, CLI.
    - **[docs/architecture.md](../../docs/architecture.md):**
      - §1, the claim "A walking twin walks", rewritten for stepping.
      - §2's operate row.
      - §4.4: the state diagram, the workflow drawing, the control activities, the
        "Following" paragraph and the create sequence.
      - §4.5: Temporal's row and the pre-017 following twin.
      - §4.6: create, destroy and show.
      - §4.7's rebuild for a package change.
      - §6: "Reconcile is rebuild", "cannot step: following still rebuilds", "Following is
        a poll".
      - §7's closed question.
    - **[docs/glossary.md](../../docs/glossary.md):**
      - Removed: Following, Frozen twin, Interval, `reconcile` (workflow), Schedule (Temporal).
      - Reworded: Kind (of a twin), Pinned, Rebuild, Check and Walking twin.
    - **[docs/development.md](../../docs/development.md):** the layout, the test
      architecture, case 5, "Following is a Schedule" and the naming table.
    - **[README.md](../../README.md):** "A walking twin, start to finish", which is built on
      following, is rewritten around a step to a snapshot; "Pinned and frozen twins" goes.
    - **The contracts:** [contracts/cli.md](../../contracts/cli.md) and
      [contracts/api.md](../../contracts/api.md) gain their F-026 sections. The schemas
      move: `api.schema.json`, `findings.schema.json`, `show.schema.json` and
      `twin.schema.json`.
    - **The C4 model:** redrawn, with the worker no longer reading Infrahub, Temporal
      holding no Schedule, and `make diagrams` run.
    - **[docs/ideas.md](../../docs/ideas.md):** the webhook entry, which is about
      following's latency.
    - **`CLAUDE.md`:** the worker's counts and the M4 line.
    - **The roadmap** ([Exit](#exit)).
12. **Upgrade.** The release notes say to destroy a following twin before upgrading. A
    Schedule left behind would start a workflow no worker serves. The new build carries no
    code for it.

<a id="decided"></a>
## Decided

Each was settled with the operator on 2026-10-27, unless marked otherwise.

- **Walking means stepping.** A twin walks when the operator steps it from one snapshot to
  another: through a proposed change's stages, or to any snapshot the operator takes. The
  name is kept. Architecture §1, the glossary and docs/brief.md say so. Following was one
  way of walking, the one the operator did not drive.
- **Any twin whose record names a snapshot steps, to a stage or to a snapshot.** The guard
  that only a stage twin steps goes, and the step record gains its stage-less side. A
  bundle twin stays unsteppable: it names no snapshot and no scope.
  - *Not chosen:* stepping only to `--snapshot`, keeping stage steps for stage twins.
  - *Not chosen:* letting bundle twins step too.
- **Tier 3's case 5 is repurposed, not deleted.** It keeps the live proof that an
  artifact-only change and a topology change reach a running twin, and verify 5a. The proof
  now comes through the operator's step, and the case is where the exit criterion is shown
  live.
- **`--interval` and `--no-follow` are removed outright**, in the CLI and the API, with no
  named refusal and no tolerated no-op. The release notes say so.
- **The kind line names the snapshot, then what it holds.** Pinned, frozen and following
  collapse into one kind. Whether the envelope carries an `at` is still shown, because it
  says whether the snapshot can be taken again.
  - *Not chosen:* keeping `pinned` and `frozen` as kinds.
- **Upgrade by release note.** Destroy a following twin before upgrading. The new build
  keeps no shim.
  - *Not chosen:* a destroy that clears a stray Schedule for one release.
- **A step to a target of another scope or mapping is refused.** A twin's scope and mapping
  are fixed when it is created, as a stage step's already are. *Not chosen:* the record
  taking the snapshot's scope and mapping, which would have a diverged step write a
  provenance the twin did not start with.
- **A step to a snapshot of another branch is allowed.** The core knows no branch: the step
  diffs two bundles, whatever branches their snapshots were read from, and the record names
  the new branch afterwards. This gives A/B within one twin. *Not chosen:* keeping a twin to
  the branch it was built from.
- **`--stage` names a stage of any proposed change, and is required for a twin with no
  stage.** *Settled by the brief's author* on 2026-10-27, as following from the two answers
  above. Leaving `--stage` out keeps its meaning, the next stage of the twin's own proposed
  change, and a twin with no stage has none.
- **The constitution is not amended**, because it never mentioned following. *Settled by the
  brief's author.*
- **One decision entry, D-062**, superseding in part where the old entry holds more than
  following. *Settled by the brief's author*, on D-057's and D-058's pattern.
- **Out of this feature:**
  - the orchestrator, and any follow it brings back;
  - the API's shape for long operations;
  - probes (016);
  - the NetBox reader (F-025);
  - any change to the snapshot, the CTM, the compiler, the bundle, the goldens, the
    template, the checks, the schema on `main` or the fixtures.

<a id="open"></a>
## Open, for clarify

Nothing. The two questions this brief first left open, a step to another scope or mapping
and a step to another branch, were put to the operator on 2026-10-27 and are under
[Decided](#decided). Clarify may still find its own.

<a id="left-to-the-plan"></a>
## Left to the plan

- **The step's name for a snapshot side.** `step.Between` names stages today.
- **A stage step across proposed changes.** `stages.Target` and `stages.Moved` choose and
  warn within one proposed change, found by the record's stage. The plan says how a target
  of another proposed change is found, and that `Moved` applies only when the record names
  a stage.
- **The record versions.**
  - `twin.json` holds no field about following, but its "stage implies `source: intent`"
    rule moves, so whether `9` becomes `10` is the plan's call.
  - The show and findings documents move, and so does the API's argument list.
  - Their frozen copies under each package's `testdata/contracts/` are the plan's to write.
- **The replay of the remaining histories** once provision's read-and-compile branch and
  `StopFollowing` are gone. A history that recorded neither should replay unchanged; the
  plan checks all of them.
- **`deadline_s` dropping by 30 s** against `fylgja-twin`'s `timeout` of 4260, which was
  sized with the term in it.
- **The README's walk-through:** which branch it edits, and whether it shows `intent read
  --out` then `twin step --snapshot <file>`, or a step by id.
- **The C4 redraw:** the worker's read of Infrahub goes, and so do Temporal's Schedule and
  the workflows' `ReadIntent`/`Compile` relation.
- **No Infrahub skill applies.** This feature designs nothing in Infrahub, writes nothing to
  `main`, and changes no query, template or check.
- **The estimate.** The roadmap's 3–5 hours was set before the inventory. About 3,000 lines
  go, most of them tests, and the step gains a path. The plan re-estimates.

<a id="hand-off"></a>
## Hand-off

- **To 016**: the twin a probe measures changes only when the operator steps it, so loss
  across a step is the step's. 018's open question for 016 stands: whether a rehearsal
  carries the first take's probe list into every later snapshot, or each take reads the
  probes afresh.
- **To F-025**: no push-based follow. The roadmap's F-025 paragraph says an orchestrator
  bringing following back would follow by push, and the decisions the order needs already
  strike it from F-025. An event rule calling `twin step --snapshot` is the orchestrator's,
  later.
- **To the production shape**: the core's surface is create from a snapshot, step to one,
  destroy, show and verify, with no timer of its own. The orchestrator's first demand is
  still the API's shape for long operations.

<a id="exit"></a>
## Exit

**The one criterion:** a twin is frozen at its snapshot, and nothing rebuilds it but the
operator.

- **Tier 1:**
  - The worker registers four workflows and fifteen activities, with no `Reconcile`.
  - `--interval` and `--no-follow` are unknown flags, and the API refuses both arguments.
  - The kind line in each shape.
  - A step to a snapshot, by id and by file, from twins built by `--branch`, `--stage` and
    `--snapshot`, and the refusal for a bundle twin.
  - A step to a stage from a `--branch` twin, with `--stage` required.
  - A step to a stage of another proposed change.
  - A step to a snapshot of another branch, after which the record names that branch.
  - A step to a target of another scope or mapping, refused before any run and naming both.
  - The record's rules for a stepped snapshot twin.
  - The remaining histories replay.
  - The frozen copies still load.
  - Every rehearsal deadline is 30 s shorter.
- **Tier 2:** `TestFollowingDetection` is gone. The server's step to a snapshot, taken from
  a `fylgja-test-*` branch, compiles and files as a stage step does. `internal/stages` and
  `internal/checks` pass.
- **Tier 3:**
  - Nine cases.
  - Case 5 shows the criterion live, then steps to a snapshot twice, with verify 5a.
  - No Schedule is made in any case.
  - The leak check still refuses a stray `fylgja-follow`.
- **The goldens and the live fixture's compile do not move** (`43d91715…`, `4213b3cf…`,
  `ecb665f5…`, `f764e1fa…`).
- **Owed before the work starts:**
  - The roadmap's F-026 paragraph, its table row and its decisions bullet reworded for the
    repurposed case 5, walking as stepping, the step's rules, and D-007 and D-014. Release
    0.3's item 3 linked to this brief. Both done on 2026-10-28, uncommitted.
  - The operator's: the estimate revisited, and the roadmap's edits and this brief
    committed, as 018's were at its T005.

<a id="references"></a>
## References

Read in this order, after `CLAUDE.md`'s list.

| Record | What it gives |
|---|---|
| [docs/roadmap.md](../../docs/roadmap.md): [Release 0.3](../../docs/roadmap.md#release-03), [The production shape](../../docs/roadmap.md#the-production-shape), [F-026](../../docs/roadmap.md#f-026), [F-014](../../docs/roadmap.md#f-014), [F-025](../../docs/roadmap.md#f-025), [Decisions the order needs](../../docs/roadmap.md#decisions-the-order-needs) | the scope, who takes following back, and the two specs after this one |
| [018's brief](../018-snapshots/brief.md), [Hand-off](../018-snapshots/brief.md#hand-off), and its research R-10, R-12 and R-21 | what 018 left for this feature |
| [docs/decisions.md](../../docs/decisions.md): D-007, D-012, D-013, D-014, D-026, D-027, D-045, D-048, D-061 | the entries superseded, the one that hands off, and those that stand |
| [.specify/memory/constitution.md](../../.specify/memory/constitution.md) 2.2.0: VIII, IX | the Constitution Check, and why there is no amendment |
| [docs/architecture.md](../../docs/architecture.md) §1, §4.4–§4.7, §6, §7 | the claim and the sections that move |
| [docs/glossary.md](../../docs/glossary.md): Following, Frozen twin, Kind, Pinned, Walking twin, `reconcile` (workflow), Schedule | the entries that go or are reworded |
| [contracts/cli.md](../../contracts/cli.md), [api.md](../../contracts/api.md), [show.schema.json](../../contracts/show.schema.json), [findings.schema.json](../../contracts/findings.schema.json), [twin.schema.json](../../contracts/twin.schema.json), [step.schema.json](../../contracts/step.schema.json) | the formats that move |
| [internal/provision](../../internal/provision) (`workflow_reconcile.go`, `activities.go`, `workflow_provision.go`, `workflow_step.go`, `workflow_rehearse.go`, `client.go`, `types.go`, `options.go`, `worker.go`) | what goes, and the guard relaxed |
| [internal/server](../../internal/server) (`create.go`, `show.go`, `destroy.go`, `dryrun.go`, `follow.go`, `step.go`, `snapshot.go`) | the server's half |
| [internal/rehearsal/deadline.go](../../internal/rehearsal/deadline.go), [internal/lab/twin.go](../../internal/lab/twin.go) (`NewStepRecord`), [internal/findings](../../internal/findings) | the deadline, the record's rule, the rules that go |
| [scripts/e2e.sh](../../scripts/e2e.sh): case 5, case 7, the trap's leak check | the case repurposed |
| [016's brief](../016-probes/brief.md) | the next spec, which this one prepares the ground for |
