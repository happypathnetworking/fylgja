# Research: Following removed from the core

**Feature**: `019-following-removed` · **Plan**: [plan.md](plan.md) · **Date**: 2026-10-28

§1 is what was verified on the running host and in the tree at this plan, §2 the decisions
the brief [left to the plan](brief.md#left-to-the-plan) and those the inventory raised
(R-01…R-27), §3 the decision entry D-062 drafted for the operator, §4 what is owed at
implement. Every claim below about the tree was read on 2026-10-28 at `c8d46c7` plus the
roadmap's uncommitted F-026 edits and this feature's directory. Nothing here booted a twin
or wrote to Infrahub; the live proofs are tier 2's and tier 3's.

## 1. Verified at this plan

### 1.1 The host's state

- **No Schedule exists.** `temporal schedule list --address localhost:7233` printed its
  header alone; no `fylgja-follow` is left on this host, so the upgrade note (R-21)
  concerns other hosts, and tier 3's leak check starts clean.
- **No run is open** (`temporal workflow list --query 'ExecutionStatus="Running"'` empty),
  **no twin** (`containerlab inspect --all`: no containers), and the worker and the server
  run from `bin/fylgja` (pids 2012205 and 2012228, neither `exe` deleted).
- `free -m`: 19,635 MiB available, inside `CLAUDE.md`'s band for a live run.

### 1.2 The recorded histories: seven replay unchanged by construction

`internal/provision/testdata/` holds nine histories. Their scheduled activities and the
follow fields of their start input, read with a throwaway `python3 -I` over the JSON:

| History | Workflow | Activities scheduled | Input: `bundle_id` / `follow` / `stop_following` |
|---|---|---|---|
| `cancel-during-follow` | Provision | CheckHost … RecordTwin, **StartFollowing, StopFollowing**, DestroyLab, UnstageTwin | set / set / — |
| `cancel-during-stop-following` | Provision | CheckHost, **StopFollowing** | set / set / `true` |
| `cancel-during-host-check` | Provision | CheckHost | set / — / — |
| `cancel-during-push` | Provision | CheckHost … PushConfig, DestroyLab, UnstageTwin | set / — / — |
| `cancel-during-record` | Provision | CheckHost … RecordTwin, DestroyLab, UnstageTwin | set / — / — |
| `push-after-cancel` | Provision | CheckHost … PushConfig, DestroyLab, UnstageTwin | set / — / — |
| `step-cancelled` | Step | InspectTwin, CheckHost, PlanReconcile, StageStep, ReconcileLab, AwaitReadiness, RecordStep | — |
| `step-diverged` | Step | InspectTwin … PushConfig ×2, RecordStep | — |
| `step-wait-cancelled` | Step | InspectTwin … RecordStep, VerifyTwin | — |

No history schedules `ReadIntent`, `Compile`, `RunsInFlight` or a `Reconcile` child. The
two to delete are the only ones that carry `follow` or `stop_following`. So the four
surviving provision histories never took the read-and-compile branch (`bundle_id` set),
the stop-before-stage step or the start-after-record step, and removing those three code
paths changes no command they recorded. The three step histories inspected records naming
a stage, so relaxing the run's stage-less refusal (R-03) changes no command either. The
proof is tier 1's replay at implement (`workflow_replay_test.go`'s seven remaining cases).
No `GetVersion` marker guards any removed path: the two markers in the tree, `push` and
`verify`, guard paths that stay.

### 1.3 Where following lives in the tree

Inventoried by three read-only passes. Summary; the line references are in
[data-model.md](data-model.md) where each change is placed.

- **`internal/provision`.** `workflow_reconcile.go` (402 lines) defines `Reconcile` and
  sixteen helpers; three are used elsewhere: `withoutPresence` (the step, and
  `WithoutPresence`, whose one caller is `server/step.go`), and `alreadyStarted` and
  `childStartRefusal` (the rehearsal). `activities.go` (347 lines) is `ControlActivities`,
  five activities, plus `StoreMismatchMessage`, which `server/filing.go` and
  `server/provision.go` call and which stays. `bundles/.reads/` is written and read by
  `activities.go` alone; `intent.ErrBranchNotFound` has that file as its one product
  consumer. `client.go` holds about 600 lines of Schedule code (`StopFollowing`,
  `Following`, `LastCheck`, the destroy's second stop, the checks in `InFlight`) beside
  the run streaming (`Follow`, `childEvents`, `Event`), which stays.
- **The worker registers five workflows and twenty activities** (`worker.go:47–57`):
  Provision, Destroy, Reconcile, Step, Rehearse; the five control activities and the lab's
  fifteen (CheckHost, StageBundle, DeployLab, AwaitReadiness, RecordTwin, PlanTeardown,
  DestroyLab, UnstageTwin, InspectTwin, PushConfig, PlanReconcile, StageStep, ReconcileLab,
  RecordStep, VerifyTwin). `TestWorkerRegistersEveryScheduledActivity` and
  `TestEveryActivityHasAFindingStep` assert 20.
- **The worker reads Infrahub only for following.** Its one path to Infrahub is
  `ReadIntent` (`stage.Read`); `cmd/fylgja/worker.go` checks no `INFRAHUB_*` variable.
  Once `ControlActivities` goes, `internal/provision` imports neither `internal/stage` nor
  `internal/intent`, and the worker reads no source of truth (R-22).
- **The server.** `create.go` (the flags, `followFlagsConflict`, `createFollow`,
  `followInterval`, `in.Follow`), `dryrun.go` (`followLine`, `dry_run.follow`),
  `destroy.go` (step 1a), `follow.go` (`in.StopFollowing = true` and `provisionReport`'s
  following lines, beside the run streaming that stays), `show.go` (the following reads,
  the rebuild row, the following and frozen kinds, `scheduleWithoutTwin`,
  `followingStopped`, `showCheck`), `handlers.go` (`interval`, `no_follow`), `resolve.go`
  (`neverFollows`) and `snapshot.go` (`followFlagsConflict`'s call).
- **The client.** `--interval` and `--no-follow` exist on `twin create` alone
  (`cli/create.go:78–81`); `twin step` already refuses both as unknown
  (`TestStepTakesNoBranchFlags`). The client stops nothing on destroy itself: the second
  stop is in `provision.Client.StartDestroy`.
- **The findings.** Seven rules and the step `follow` (`finding.go:95–104, :290`); the
  `following` and `dry_run.follow` blocks and six show kinds (`render.go`). The findings
  version is the literal `"1"` in three places; the show document has no version of its
  own.
- **The rehearsal.** `workflow_rehearse.go:175` sets `StopFollowing` on the baseline's
  provision; `rehearsal.Mechanism.Follow` adds `FollowBudget` (30 s) to the baseline
  (`deadline.go:82`).
- **The record.** `NewRecord` refuses a stage beside `source: snapshot` (`twin.go:81–83`);
  `NewStepRecord` keeps `prev.Source` and moves `stage` to the target's, so a `--snapshot`
  twin stepped to a stage would break both that rule and the schema's (`twin.schema.json`'s
  `allOf`, "stage ⇒ `source: intent`"). The version gates (`scopeRecorded`,
  `snapshotRecorded`, the show's `v >= 5`) parse `twin_version` with `strconv.Atoi`, so a
  `"10"` compares as a number.
- **Tests that go whole**: `workflow_reconcile_test.go` (1,019 lines), `activities_test.go`
  (896), `internal/stage/following_contract_test.go` (tier 2), the two histories and their
  replay cases. Two helpers in the deleted files are used elsewhere and move:
  `wantRules` (the rehearsal's tests) and `repoPath` (`worker_test.go`). About twenty
  tier-1 tests reach the provision workflow through its read-and-compile branch with no
  `BundleID` (`workflow_provision_test.go`, `_retry_`, `_unstage_`, `_heterogeneous_`,
  `_heartbeat_`, `_failure_`, `_cancel_`, `cli/marker_test.go`); they move to a compiled
  input. `cli/stage_parity_test.go` holds `twin compile` to the `Compile` activity and is
  held instead to the server's compile path (R-16).
- **Tier 3** (`scripts/e2e.sh`): `--no-follow` at lines 878, 921, 1022 and 1272; case 5 at
  1052–1250 (create following at 15 s, an unchanged check, two rebuilds awaited, verify 5a,
  the show after the rebuild, a destroy asserting `following.stopped`); case 7's
  `has("following") | not`, `schedule_state` absent and `.show.kind=="pinned"`; case 8's
  `.show.kind=="pinned"`; the trap's `schedule_state` leak check (692–701);
  `twin_version=="9"` at four lines. `compiled_id` (528–541) already runs `intent read
  --out` and `twin compile --snapshot`, which case 5 reuses.
- **The rehearsal check's timeout.** `fylgja_twin.py`'s `timeout = 4260` is sized against
  the ceiling (3,600 s) plus the destroy (120 s) plus the allowance before the start
  (300 s) plus `DEADLINE_MARGIN_S` (240 s), equality with no slack
  (`TestTheTwinCheckOutlastsItsRehearsal`); no term of it is a rehearsal's deadline, so
  the 30 s that every deadline loses moves nothing there (R-15).

### 1.4 Not verified here, and why

- **The replays**, **the step to a snapshot on a running twin**, and **five quiet minutes
  after a branch edit**: tier 1, tier 2 and tier 3 at implement, against the code as
  changed. No twin was booted at plan.
- **Temporal's Schedule API**: the build stops calling it; nothing about it is relied on.

### 1.5 The roadmap's edits are uncommitted

`git status` shows `docs/roadmap.md` modified (F-026's paragraph, table row, decisions
bullet and Release 0.3's item 3) and `specs/019-following-removed/` untracked: the brief's
[Exit](brief.md#exit) says both are the operator's to commit, as 018's were at its T005.

## 2. Decisions

### R-01 What leaves `internal/provision`, and where the three helpers go

**Decision.** Delete `workflow_reconcile.go` and `activities.go` whole, after moving
`withoutPresence` into `workflow_step.go` beside `WithoutPresence`, `alreadyStarted` and
`childStartRefusal` into `workflow_rehearse.go`, and `StoreMismatchMessage` into
`internal/server/filing.go`, its caller's package (it reads nothing of the provision
package; `server/provision.go` calls it too). From `types.go`: `FollowScheduleID`,
`WorkflowReconcile`, `ActRunsInFlight`, `ActStartFollowing`, `ActStopFollowing`, the seven
`Check*` outcomes, `ProvisionInput.Follow` and `.StopFollowing`, `FollowInput`,
`ProvisionResult.Following` and `.FollowingStopped`, `FollowingResult`, `ReconcileInput`,
`ReconcileResult`, `RunsInFlightResult`, `StartFollowingInput`, `StopFollowingResult`,
`DestroyRun.FollowingStopped`, and `ReadIntentInput`/`Result` and `CompileInput`/`Result`.
`wire.ActReadIntent` and `wire.ActCompile` go from `internal/lab/wire`. From `options.go`:
`DefaultInterval`, `MinInterval`, `FollowCatchupWindow`, `FollowJitter`,
`RunsInFlightBudget`, `FollowBudget`, `ReadOptions`, `CompileOptions`,
`RunsInFlightOptions`, `FollowOptions`. `InspectTwinBudget`, `ShowServiceBudget` and
`ChildOptions` stay (the step, the show and the rehearsal use them). From
`workflow_provision.go`: `stopFollowingBeforeStage`, `readAndCompile`, `startFollowing`,
`FollowStartFailedMessage`, and the `default:` source branch, so a provision input with no
bundle id is a programming error the workflow reports as `operation.failed` at its first
step, never a read. `NewWorker` loses its `control` parameter.

**Rationale.** The brief's [list](brief.md#what-changes). Moving each helper beside its one
remaining caller keeps the move a pure relocation; nothing about them changes.

**Alternatives.** A new `workflow_children.go` for the three helpers: one more file for
three small functions whose callers are already in two files.

### R-02 The replays: no marker, seven cases kept

**Decision.** Delete `cancel-during-follow.history.json`,
`cancel-during-stop-following.history.json`,
`TestReplayCancelDuringFollowStopsTheFollowing` and
`TestReplayCancelDuringStopFollowingNamesTheStop`, and the header comment's sentence on
them. Keep the seven others unchanged, re-recorded by nobody. No `GetVersion` marker.

**Rationale.** §1.2: none of the seven recorded a removed path, so the workflows as
changed issue the same commands for them. A marker guards a path a live history still
takes; none does, and the Constitution VIII gate is satisfied by determinism, not by a
marker. `rewrite-stage.go`, the tool that re-wrote histories at 014, is not run.

### R-03 The step's eligibility splits: the run relaxes, the server judges the snapshot

**Decision.** `provision.Ineligible`, which both the server and the step run's inspect call,
keeps its no-twin, orphan/unreadable, diverged and superseded-waypoint cases and **loses
its `Stage == nil` case**, with `origin()`. Its two no-twin messages stop saying "only a
twin built from a stage steps" and say "a twin built from a snapshot steps (fylgja twin
create --branch, --stage or --snapshot)". The rule that a twin must name a snapshot is
**the server's alone**, in `server/step.go` beside `stepScopeUnknown`, as one function,
`stepUnsourced(rec)`, run after `Ineligible` and `stepScopeUnknown`:

| Record | Refusal (`step.twin.unsteppable`, resolve, object the record's `bundle_id`) |
|---|---|
| `source: bundle` | `the twin was provisioned from a bundle, which names no snapshot; only a twin whose record names a snapshot steps; fylgja twin destroy clears it` |
| `twin_version` 8 | `the twin was created from a record version that names no snapshot (twin.json 8); only a twin whose record names a snapshot steps; fylgja twin destroy clears it` |
| 9 or 10, `snapshot_id` null, not a bundle twin | `the twin's record names no snapshot (an earlier build's rebuild made it); only a twin whose record names a snapshot steps; fylgja twin destroy clears it` |

A record of 7 or earlier keeps `stepScopeUnknown`'s refusal, naming its version, since the
order is `Ineligible`, then `stepScopeUnknown`'s version and scope gates, then the
snapshot. A bundle twin's record carries its manifest's scope and mapping, so it passes
the second and meets the third.

**Rationale.** A snapshot rule inside the run would refuse the three step histories at
inspect, since their records predate `snapshot_id` and read it as nil: the run would
return instead of scheduling `CheckHost`, a non-determinism. Every refusal is the server's
in any case (XI); the run's inspect is a second lock against a host that changed between
the command's look and the run's, and `notPlannedFrom` (bundle and stage equal) remains
that lock unchanged.

**Departure from 018, settled by the operator on 2026-10-28.** 018's R-06 let a stage twin
of record `8` step, its from side naming no snapshot. That allowance is retired: only a
twin whose record names a snapshot steps, and such a twin predates 018's build and is
destroyed and made again. The spec's edge case, which said "as today", is reworded, and
D-062's consequences say so.

### R-04 `twin step --snapshot <id|file>`: the client, the API, the server

**Decision.**

- **Client.** `twin step` gains `--snapshot <id|file>`, read and sent as `twin create`'s
  is (`cli/create.go`'s `isSnapshotID`/`readSnapshot`): an id is sent as it is; any other
  value is a path, read here and sent as the request's one file under that path; an
  explicit empty `--snapshot=` is refused before any connection as on create. The file is
  read only when `--stage` is not also given, so the conflict's refusal comes first,
  whatever the file. Its help names "a snapshot of any branch".
- **API.** `twin.step` takes `snapshot` (string), and `twin.step` joins `takesFiles`
  (`handlers.go`). Version `1`, additive.
- **Guards, before any connection, exit 2 at start.** `--stage` beside `--snapshot` is
  `snapshot.flags.conflict`, object `--stage`: `--stage is meaningless with --snapshot: the
  snapshot is the target`. The request's files are held to one shape by the function
  `snapshotFiles` already is for create, generalised to name its operation (one file under
  the `--snapshot` path when it is not an id, none otherwise).
- **Server.** After the host is read, judged eligible (R-03) and its scope known, a
  `--snapshot` target is resolved by `resolveSnapshot` as create resolves it (store
  lookup, or the file read by `snapshot.Unmarshal`, held to `validate.Intrinsic` and
  filed), so `snapshot.unknown`, `snapshot.id.mismatch`, `snapshot.invalid` and
  `snapshot.version.unsupported` are create's own, at resolve. **No request reaches
  Infrahub**: no `intent.StageReaderFromEnv`, no `stages.Find`, `Target` or `Build`. Then
  the scope and mapping are judged (R-06), the snapshot's CTM is compiled and its bundle
  filed by the path create's `--snapshot` uses (`compileAndFile`, on `stage.Compile`), each
  refusal at compile as there, and the step continues in `stepTo` exactly as a stage
  step's.
- **`stepTo` takes a target, not a `PlanStage`.** A small struct, `stepTarget`, carries
  what `stepTo` and `stepInput` read today from `stages.PlanStage`: the side's name
  (R-05), the stage (`*wire.StageRef`, nil for a snapshot), `SnapshotID`, the compiled
  `step.Bundle`, `At`, `Branch` and `ObservedAt`. A stage target fills it from the
  `PlanStage` and its `Resolved`; a snapshot target from the envelope (`branch`, `at`,
  verbatim, `""` when unpinned) and the stored snapshot's `observed_at`. So the to side is
  `{stage: null, snapshot_id, bundle_id, at, branch}`, and the run, the record and the
  document are the stage step's code.
- **The dry run** (`--dry-run --snapshot`) prints the twin line, a `target:` line
  (`target: snapshot <short> (branch B at T | branch B, read at T)`, in place of the
  stage's resolution line), the step, containerlab's plan and the push plan, files the
  snapshot (when sent) and the bundle, and starts no run, as the stage step's dry run.

**Rationale.** FR-013 and the brief: the same forms as on create, so one resolver, one set
of refusals; and the step's run is indifferent to how its target was chosen, since its
input is two bundle ids, a plan and a push plan (D-061).

**Alternatives.** A new API operation `twin.step_snapshot`: a second command surface for
one flag. Resolving the snapshot in the client: every refusal is the server's (XI).

### R-05 A side's name: `stage <ref>` or `snapshot <short>`

**Decision.** One name for each side of a step and for the record's position, used by the
step's text, its closing line, the diverged refusal, `twin show`'s kind and in-flight
lines, and `notPlannedFrom`:

- `wire.StepSide.Name()`: `stage <branch>/<label>` when the side names a stage; else
  `snapshot <first 8 of snapshot_id>…` when it names a snapshot; else `bundle <first 8>…`
  (a side of an 8 record that stepped, which names neither).
- `wire.TwinRecord.Position()`: the same over the record's top level, keeping `SideStage`'s
  superseded-waypoint wording for a record of 5 or earlier.
- `step.Between(from, to, s)` is unchanged and takes the stage part without its word, as
  today (`change-1/seeded → change-1/third-link`), and `snapshot 576933ec…` for a snapshot
  side: `step change-1/seeded → snapshot 576933ec… (35aea06f… → 9c2d01e7…):`.
- The closing lines: `stepped to snapshot 576933ec… (bundle 9c2d01e7…) in 41s: …`,
  `unchanged; the record moves to snapshot … (bundle …) in …`, `diverged towards snapshot
  … (bundle …) at phase …; the twin is up at stage … (bundle …); fylgja twin destroy
  clears it`.
- The step's twin line, for a twin that names no stage: `twin: snapshot <short> (bundle
  <short>), branch B at T; N nodes` or `…, branch B, read at T; N nodes`; for a stage twin,
  as today without "pinned at" changing.
- `in_flight`'s step form: `stepping towards snapshot <short>` where it says `stepping
  towards stage <s>` today (`stepTowards` reads the run's input's to side).

**Rationale.** The brief leaves the name to the plan. A stage's reference already carries
its branch; a snapshot's short id is how every line since 018 names one, and the word
`snapshot` keeps it from reading as a branch.

### R-06 Scope and mapping are the twin's for life

**Decision.** One function, `targetUnheld(rec, scope, mapping, object)`, returns
`step.twin.unsteppable` (rejection, resolve, object the target: the snapshot id or the
stage reference) when the target's scope or any field of its mapping differs from the
record's provenance, naming both:

```
the twin's record names scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 26336e9; snapshot 576933ec… names scope tag:other and mapping infrahub-dcim opsmill/schema-library 26336e9; a twin's scope and mapping are fixed when it is created; fylgja twin destroy and create again to change them
```

For a `--snapshot` target it runs on the envelope, after the snapshot is resolved and
before the compile. For a `--stage` target it runs after `stages.Build`, on the provenance
of the compiled bundle's manifest (the snapshot's envelope copied, bundle 5), before the
host check. A stage resolved under the record's scope matches by construction, so only a
mapping that moved since the twin's creation (a build whose reader moved) refuses there.

**Rationale.** FR-015 and the brief's Decided list. The check on the envelope before the
compile keeps a refused target's bundle out of the store; the stage's check after the
build uses what the build already holds, with no second read.

### R-07 A stage of any proposed change

**Decision.**

- **Which proposed change is read.** `stages.Find` by the given reference's branch when
  `--stage` is given, else by the record's stage's branch (R-08 covers the case with
  neither).
- **`stages.Target` is rewritten** for a record that may name no stage or a stage of
  another proposed change: `same` is "the record names a stage of the found proposed
  change". With a given reference and not `same`, the target is the given label, refused
  as `step.target.unknown` naming the proposed change's stages when it lacks it; no
  `step.stage.skipped` warning (the marks between two proposed changes' stages are not an
  order). With `same`, today's rules 3 to 6 hold. Rule 5, `step.target.current`, judges
  every target against the record's provenance `(branch, at)`, stage or not.
- **`step.target.foreign` is retired**: its two cases (another branch; another proposed
  change opened on the record's branch) are now targets. With no reference given and the
  record's proposed change closed (another opened on its branch), `step.target.unknown`
  stays, as today's rule 2.
- **`stages.Moved` applies only when `same`.** When the target is in another proposed
  change, the record's own stage is not read and no `stage.twin.moved` is given; a step
  goes from the bundle the record holds in either case. `stage list` already passes no
  view for a stage-less record (`RecordViewOf` returns nil), so it gives none for such a
  twin, unchanged.
- **The record view** gains no fields: `recordView` returns nil for a stage-less record as
  today, and `Target` takes the record's `(branch, at)` as two arguments beside the view.

**Rationale.** The brief leaves both to the plan. Reading the record's proposed change only
to warn that its stage moved, when the step does not go there, would be a second Infrahub
read for a warning about something the step does not use.

**Settled at plan, 2026-10-28.** US3 scenario 3 leaves `step.target.foreign` no case, so
the identifier is retired from the catalogue and FR-004's list names it.

### R-08 No target for a twin that names no stage

**Decision.** When neither `--stage` nor `--snapshot` is given, the server reads the twin
directory's record (`lab.ReadRecord`, a file read; no connection) **before**
`rehearsalHolds` dials the workflow service. A readable record naming no stage is refused
as `step.target.unknown`, rejection, exit 1, at resolve, object the record's `bundle_id`:
`the twin names no stage, so there is no next stage to step to; give --stage
<branch>/<label> or --snapshot <id|file>`. An absent or unreadable record, or one that
names a stage, goes on as today, so a rehearsal's host (no record during its baseline's
provision, a staged record after) still meets `run.in_flight` first.

**Rationale.** FR-014 and US3 scenario 1 say "before any connection". The record is the
only fact needed, and reading it first cannot misname a rehearsal's twin, since a
rehearsal's records always name a stage.

### R-09 The record: `twin.json` 10, and its rule on a stage

**Decision.** `twin.json` moves to **`10`**. No field is added or removed. The rule "a stage
implies `source: intent`" becomes "a stage implies `provenance.at`" alone (in the schema's
`allOf` and in `NewRecord`, which drops its refusal of a stage beside `source: snapshot`
for symmetry, though no create writes one). `source` keeps its meaning, how the twin was
**created**, and `NewStepRecord` keeps it, so a `--snapshot` twin stepped to a stage is
`source: snapshot` with a stage, and a stage twin stepped to a snapshot is `source:
intent` with `stage: null` and a `snapshot_id`. The `--branch` twin's `source: intent`
description loses "or a check's rebuild did". `lab.TwinVersion = "10"`; a step rewrites a
9 record as 10, as every step rewrites to the current version. The 9 schema is frozen as
`internal/lab/testdata/contracts/018-snapshots/twin.schema.json`, and the tests that read
a 9 record keep reading it there.

**Rationale.** A 10 record can hold what no 9 could (a snapshot-sourced twin with a
stage), so it is not a 9: the frozen-copy discipline holds every version's records to its
own schema. The version gates are numeric (§1.3), so 10 reads as later than 8 and 9.

**Alternatives.** Keeping `9` with a loosened rule: one version, two definitions. A new
`source` value for a stepped twin: the record would say how it was last moved, which
`step` already says.

### R-10 `twin show`

**Decision.** The kind is one of `none`, `snapshot`, `from_bundle`, `diverged`:

| Record | Kind | Kind line |
|---|---|---|
| intent or snapshot, `snapshot_id` set, envelope `at` set | `snapshot` | `snapshot <short> (branch B at T)` |
| the same, no `at` | `snapshot` | `snapshot <short> (branch B, read at <observed_at>)` |
| intent, `snapshot_id` null (an earlier build's rebuild, or an 8) | `snapshot` | `snapshot none (branch B, read at T)` (or `at T`), with the note `the twin's record names no snapshot, so fylgja twin step refuses it; fylgja twin destroy clears it` |
| bundle | `from_bundle` | `from a bundle` |
| diverged, none | as today | as today |

After the bracket come, as today, `, stage <ref>` when the record names one, `(stepped from
<side name> by run fylgja-step <run>, ended <t>)` when it has stepped (the from side named
by R-05), and the rehearsal's clause. "; not following" goes from every line. The
best-effort note stays for an unpinned twin. The following reads go (`svc.Following`,
`svc.LastCheck`), so a show dials the workflow service for runs in flight alone; the rebuild
row, the following and frozen rows, `scheduleWithoutTwin`, `followingStopped`,
`createStartsAgain`, `showCheck` and the check forms of `runInFlight` go.
`show.service.unreachable`'s message becomes `the workflow service at <addr> did not answer
within 5s: whether a run is in flight is unknown`, and the kind line's suffix `in flight:
unknown (workflow service unreachable at <addr>)`. The show document loses `following` and
`last_check` and `$defs/check`, and `kind`'s enum becomes the four.

**Rationale.** FR-008, FR-009 and the clarification. `from_bundle` keeps its kind, since the
bundle names no snapshot to put in the line.

### R-11 `twin verify` names the snapshot

**Decision.** The verify block's twin gains `snapshot_id` (string or null) beside
`bundle_id`, which is the **staged** bundle's: the record's `snapshot_id` when the staged
bundle is the record's, the step's `to.snapshot_id` when the staged bundle is the step's
target (a diverged twin), and null otherwise. The first line becomes `twin: <ref>
(snapshot <short>, bundle <short>), <state>; …`, `snapshot none` when null. This is 018's
deferred R-21.

### R-12 What leaves the findings

**Decision.** Retired identifiers: `follow.interval.invalid`, `follow.flags.conflict`,
`follow.start.failed`, `follow.stop.failed`, `follow.stopped`, `check.skipped`,
`rebuild.failed` and `step.target.foreign` (R-07); the step `follow`. Retired blocks:
`following` on create, provision and destroy documents; `dry_run.follow` with
`DryRunFollow` and the five `FollowReason*`. Reworded: `stage.flags.conflict` (`--branch`
or `--at` beside `--stage`), `step.twin.unsteppable` (R-03, R-06),
`show.service.unreachable` (R-10), `snapshot.flags.conflict` (its comment: also `--stage`
beside `--snapshot` on `twin step`), `step.target.unknown` (R-08). The dry run loses its
`follow:` line. The findings document stays version `1`, as the API does (pre-1.0; the
removals carry no named refusal, as the brief decides); `findings.schema.json`'s
description records the 019 removals. The 018 shapes of `findings.schema.json` and
`show.schema.json` are frozen under `018-snapshots/` in the packages that froze 017's
(`cli`, `findings`, `server`) for any test that reads a document an earlier build wrote;
`frozenContractCopies` moves by their count.

### R-13 The flags and the arguments

**Decision.** `--interval` and `--no-follow` leave `twin create` with their fields,
`defaultInterval` and `minInterval` (`cli/create.go`), and
`TestFlagDefaultsAreTheCoresOwn`'s interval rows; cobra refuses each as `unknown flag`,
exit 2, before any request, as it refuses `--ctm` since 018 (`TestCompileTakesNoCTM`'s
template). `interval` and `no_follow` leave `operationArgs[twin.create]`, so `checkArgs`
answers 400 `the request is not one: twin.create takes no argument "interval"`, as for
`waypoint` and `ctm` (`server_test.go`'s table gains two rows). `snapshotConflicts()`
drops `intervalGiven`. The comments that cite "M4's `--interval=` precedent" keep the
precedent's name, since it is history, and say it was `twin create`'s.

### R-14 Destroy stops nothing first

**Decision.** `server/destroy.go`'s step 1a and `provision.Client.destroy`'s step 2a (the
second stop) go, with `StopFollowing`, `FollowStop`, `FollowStopError` and
`FollowStopFailedMessage`. `DestroyDocument(subject, res)` loses its third argument. The
destroy's events lose "following of branch B stopped"; `contracts/api.md`'s `twin.destroy`
answer loses its following events and "its `start` comes once following has stopped".
`provision.Client.InFlight` lists the operator's runs alone (no checks); `isCheck` and
`runningChecksQuery` go.

### R-15 The rehearsal's deadline, and `fylgja-twin`'s timeout

**Decision.** `rehearsal.Mechanism` loses `Follow` (eleven fields to ten) and the baseline's
sum its `m.Follow` term; `DeadlineMechanism` loses its row. Every deadline falls by 30 s:
the tests' 1,980 s → 1,950 s, 2,610 → 2,580, 2,430 → 2,400, 720 → 690, 5,550 → 5,520 (still
over the ceiling, still refused). Where 1,980 or 2,610 is a fixture's input or a rendered
report and not a computed deadline (`markdown_test.go`, `report.go`'s comment,
`server_test.go:1107`, `client_test.go:1621`, `workflow_rehearse_test.go`), it stays.
`fylgja-twin`'s `timeout` stays **4260**, `infrahub_yaml_test.go` unchanged, and no check
moves (FR-021): it is sized against the ceiling, not a deadline (§1.3).

### R-16 Tier 1's fallout

**Decision.** Every test that started the provision workflow with no bundle id is given a
compiled input (`BundleID`, `BundlePath`, `SnapshotID`), as the server builds it; the
helpers `mockHappyPath` and the stubs in `workflow_helpers_test.go` lose `ReadIntent`,
`Compile` and the follow activities; `TestProvisionAlreadyCompiled` and
`workflow_bundle_test.go`'s "ReadIntent did not run" assertions go with the activities
they named. `cli/stage_parity_test.go` holds `twin compile --snapshot` to the server's
create path (`compileAndFile`, both `stage.Compile`), which is the D-011 parity that
remains. `cli/marker_test.go` drops its `.reads/` CTM and its `Compile` detail. The
registration tests assert four workflows and fifteen activities, and that `Reconcile` is
not registered.

### R-17 Tier 2

**Decision.** `internal/stage/following_contract_test.go` (`TestFollowingDetection`) goes.
`internal/server/snapshot_contract_test.go` gains `TestStepTargetFromASnapshot`: on a
`fylgja-test-*` branch it seeds, takes a snapshot through `intent read --out`'s server path,
then builds the step's snapshot target (R-04's resolve, scope check and compile) from the
file and from the id, and asserts that each files the same snapshot and compiles to the
bundle `stage plan`'s path compiles from the same read, with no second Infrahub request on
the snapshot path (the stamper's and the reader's counters, as the other contract tests
count them). No twin boots in tier 2. `internal/stages` and `internal/checks` run as
today; `Target`'s and `Moved`'s new cases are pure and tier 1's.

### R-18 Tier 3's case 5

**Decision.** Case 5 keeps its branch, its seed, its two changes and verify 5a, and loses
following:

1. Seed `fylgja-test-e2e-$$-$RANDOM`; `create_twin 5 --scope tag:fylgja` (no
   `--interval`). Assert the create's document has no `following` key, `twin show --json`
   `.show.kind=="snapshot"` naming `SID5` and `BID5`, and the text kind line
   `kind: snapshot ${SID5:0:8}… (branch $FB, read at …)`; keep it in `kind-5.txt`.
2. Hash `twin.json` and the three container ids; note `CREATED5` (UTC, after the create's
   answer).
3. `-disable-port n1:ethernet-1/2 -generate`; `await_checksums_moved`; then wait until
   **330 s** have passed since the checksums moved (`FROZEN_WAIT_S=330`, five minutes and a
   half, longer than the retired default check). Assert: `twin.json` and the containers
   unchanged, the kind line equal to `kind-5.txt`, and `temporal workflow list --query
   "StartTime > '$CREATED5'"` empty: no run of any type started.
4. `compiled_id 5a` (it writes `$OUT/snapshot-5a.json` and compiles it), then `fylgja twin
   step --snapshot "$OUT/snapshot-5a.json" --json`: assert `.status=="ok"`,
   `.step.outcome=="stepped"`, `.step.to.stage==null`,
   `.step.to.snapshot_id==env.COMPILED_SNAPSHOT`, `.step.to.bundle_id==env.COMPILED_ID`;
   the record's `.stage==null`, `.snapshot_id` and `.bundle_id` the target's, `.source ==
   "intent"`; `readback 5a "$FB" disable`; `verify_twin 5a` with today's assertions on the
   skipped port and link and `.verify.twin.snapshot_id==env.COMPILED_SNAPSHOT`.
5. `-add-link`; `await_checksums_moved` on n1 and n3; `compiled_id 5b`; `twin step
   --snapshot <id>` this time **by id** (`$COMPILED_SNAPSHOT`, which `compiled_id`'s `intent
   read --out` filed): stepped; `readback 5b`; `twin show` names the new snapshot and
   `(stepped from snapshot <5a's short> by run fylgja-step …)`.
6. `destroy_twin 5` (the store's check holds again: no check reads into
   `bundles/.reads/`), then the branch deleted.

The Schedule assertions in cases 5 and 7 and `FOLLOW_INTERVAL_S` go; `schedule_state` and
`FOLLOW_SCHEDULE` stay for the trap's leak check alone, whose comment says it catches a
Schedule a host upgraded with a following twin up kept. Cases 7 and 8 assert
`.show.kind=="snapshot"` where they assert `pinned`, and `twin_version=="10"`. The four
`--no-follow` go, with the header's sentences. The closing timing line names case 5's
`frozen wait`, `step 5a` and `step 5b` in place of its rebuilds. Tier 3 stays nine cases
and grows by about the wait less the two rebuilds it no longer awaits: about three
minutes, to about 32 to 33 minutes.

**Rationale.** FR-022 and the clarification. The 330 s is counted from the moment the
change is visible to a read, which is when a following build's next check could first have
seen it. Stepping 5b by id shows the second form of `--snapshot` live at no cost.

### R-19 The documents

**Decision.** Each listed in the brief and found in §1.3's inventory moves in the same
change as the code it describes, and the architecture is grepped for `follow`, `reconcile`
(the workflow), `Schedule`, `interval`, `frozen` and `pinned` (as a kind) at the close
(Governance). Placed in [data-model.md](data-model.md) §9.

### R-20 D-062, and no amendment

**Decision.** D-062 as drafted in §3, appended to `docs/decisions.md` at plan on
2026-10-28 at the operator's word, with the five *Superseded* status lines and its index
row, uncommitted. The constitution is not amended (spec FR-023, brief).

**Settled by the operator on 2026-10-28: no amendment.** The constitution's Governance
says "a change to any cited decision requires a superseding entry there and an amendment
here". VI cites D-012, VIII D-007 and IX D-014, each superseded here in part. No
principle's text names following, so no principle changes; as when D-060 superseded D-059
(cited by III) in part with no amendment, the sentence is read as "a change to what a
principle relies on". D-062's consequences say so. The alternative, a PATCH 2.2.1 adding
D-062 to the three rationales, was not taken.

### R-21 The upgrade note

**Decision.** The sentence "Destroy a following twin before upgrading: a Schedule
`fylgja-follow` left behind starts a workflow no worker of this build serves, and this
build carries no code to clear it" goes into `contracts/cli.md`'s 019 section and into the
roadmap's Release 0.3 section under an "Upgrading a 0.2 host" list, which 0.3's release
notes copy into `.github/workflows/release.yml` when they are written at the release's
close. `release.yml`'s heredoc is v0.2.0's notes and is not edited by a feature.

**Settled by the operator on 2026-10-28.** FR-026 now names `contracts/cli.md`'s 019
section and the roadmap's "Upgrading a 0.2 host" list, which 0.3's notes copy when written.

### R-22 The worker reads no source of truth

**Decision.** Recorded, not built: no code is added. The worker needs `INFRAHUB_ADDRESS` and
`INFRAHUB_API_TOKEN` no longer, and reads neither; `contracts/cli.md`'s Environment table,
`docs/architecture.md` §4.5, `docs/development.md`'s environment table, the C4 model's
deployment node ("both node logins; no API token"), and `CLAUDE.md`'s worker check ("the
environment names carry `INFRAHUB_*`") say so. `scripts/e2e.sh`'s credential greps over the
worker's log stand. The bring-up script and `make worker` still load `local/.env`, which
holds the logins.

**Rationale.** A consequence the spec does not name: the core's worker no longer knows a
source of truth, which is the production shape's claim for the core.

### R-23 The README

**Decision.** "A walking twin, start to finish" keeps its branch, `fylgja-test-readme`, its
seed and its two changes: create from `--branch` (the kind line naming the snapshot),
disable a port and generate, `twin show` unchanged, then `intent read --branch
fylgja-test-readme --out local/readme-1.json` and `twin step --snapshot
local/readme-1.json`, the node reading the port disabled; the link added and stepped to
**by id**, from the id the read printed. "Pinned and frozen twins" goes; one paragraph under
the walk-through says what the kind line's bracket tells (an `at`, or a read time, and so
whether the snapshot can be taken again). "A stepping twin" loses "A walking twin keeps up
with its branch by rebuilding" and its "never follows" lines.

### R-24 The C4 model

**Decision.** In `docs/c4/workspace.dsl`: the worker's `workflows` component describes four
workflows taking a snapshot id and a bundle id and none reading; `wstage` and the
relationship `workflows -> wstage "ReadIntent, Compile: a following check's"` go; the two
`worker -> infrahub` relationships go; `temporal` is "Durable execution: run history"; the
worker's deployment node names "both node logins; no API token". `make diagrams`
redraws the views.

### R-25 The estimate

**Decision.** About 3,500 lines leave (the reconcile and its test 1,421, `activities.go` and
its test 1,243, `client.go` and its tests about 1,000, the show, create, destroy and
dry-run halves and their tests about 900, the two histories), and about 900 arrive (the
step's snapshot path, `Target`'s rewrite, the side names, `twin.json` 10, and their
tests). Converge-loop time, by 017's and 018's: **8 to 11 hours of sessions**, plus tier 2
(about 29 minutes, less `TestFollowingDetection`) and tier 3 (about 33 minutes) whole and
narrowed. The roadmap's 3–5 was set before the inventory; the operator revisits it (brief,
Exit).

### R-26 No Infrahub skill

**Decision.** None loaded. The feature designs nothing in Infrahub, writes nothing to
`main`, and changes no query, template, check or fixture data; the fixture tool's and
`internal/testsupport/seed.go`'s comments that say "following's change" are reworded, and
no flag of theirs moves.

### R-27 The spec's departures, settled on 2026-10-28

Each is settled, and the spec's Clarifications record it. By the operator:

1. A stage twin of record `8` no longer steps (R-03): retired, the edge case reworded.
6. The upgrade sentence lives in `contracts/cli.md` and the roadmap until 0.3's notes
   exist (R-21): FR-026 reworded.
7. No constitution amendment (R-20): D-062 says why.

By the plan, as following from the spec's own words:

2. `step.target.foreign` retired (R-07): FR-004 names it.
3. The "no target" refusal reads the record before the workflow service is dialed (R-08),
   to meet FR-014's "before any connection".
4. `stage.twin.moved` only when the target is in the record's proposed change (R-07):
   FR-014 and US3 say so.
5. `twin.json` moves to `10` (R-09): FR-018 says so.
8. The worker reads no source of truth (R-22): a consequence, recorded in the documents and
   in D-062's decision.

And D-062 is appended now (R-20).

## 3. Drafted for the operator, appended on 2026-10-28

### 3.1 D-062 — Following leaves the core: a twin is frozen at its snapshot and changes only when the operator steps it

```markdown
<a id="d-062"></a>
## D-062 — Following leaves the core: a twin is frozen at its snapshot and changes only when the operator steps it

**Status:** Accepted 2026-10-28, by the operator, at `019-following-removed`'s plan.
Supersedes [D-012](#d-012) in the part that says an unpinned twin follows its branch,
[D-026](#d-026) and [D-027](#d-027) whole, [D-007](#d-007) in its `Reconcile`, its Schedule
`fylgja-follow` and its count of workflows and activities, and [D-014](#d-014) in "Temporal
holds … the Schedule `fylgja-follow`". Beside [D-061](#d-061), whose sentences on the
reconcile and on a snapshot twin frozen by rule it makes universal. To be built by
`019-following-removed`.

### Context

Since D-061 every workflow the core runs but one starts with a snapshot id and a bundle id
and never reads a branch. The one left is following: a twin built from a branch with no
`at` and no `--no-follow` is checked every interval by the `Reconcile` workflow, which a
Temporal Schedule starts, reads and compiles the branch in the worker, and rebuilds the
twin when its bundle id has moved (D-012, D-026, D-027). It is the core's last reader of a
branch, and the production shape's core knows none. A twin that may tear itself down
between two measurements is also the wrong ground for probes (F-014), which measure loss
across a step. Entries that cite following stand as history: D-011, D-017, D-023, D-024,
D-025, D-028, D-032, D-039, D-048, D-049, D-053.

### Options considered

- **Keep following, fed by snapshots**: the Schedule's check takes a snapshot instead of a
  CTM. The core would still hold a timer and a branch, and probes would still measure a twin
  that rebuilds itself.
- **Keep following as an opt-in flag**: the same, behind a choice nobody defaults to.
- **Remove following from the core**, and keep the step: a twin is frozen at its snapshot
  and changes only by `twin step` or `twin destroy`; any twin whose record names a snapshot
  steps to a stage of any proposed change or to a snapshot of any branch, but never to
  another scope or mapping; the orchestrator of the production shape may bring following
  back outside the core as take, compare, step.

### Decision

Following leaves the core, and not Fylgja. The `Reconcile` workflow, the Schedule
`fylgja-follow`, the five control activities (`ReadIntent`, `Compile`, `RunsInFlight`,
`StartFollowing`, `StopFollowing`), `bundles/.reads/`, `--interval` and `--no-follow` go;
the worker serves four workflows (provision, destroy, step, rehearse) and the lab's fifteen
activities, and reads no source of truth. A twin is frozen at its snapshot, and nothing
rebuilds it but the operator. **Walking means stepping**: a twin walks when the operator
steps it from one snapshot to another, through a proposed change's stages or to any
snapshot the operator takes; following was the way of walking the operator did not drive.
`twin step` steps any twin whose record names a snapshot, to `--stage <branch>/<label>` of
any proposed change or to `--snapshot <id|file>` of any branch; a twin's scope and mapping
are fixed for its life, and its branch is not. `twin show` names the snapshot a twin was
built from in place of pinned, frozen or following; "pinned" remains a word for a
reference with an `at`. Short workflows with fixed ids stand (D-007), and Temporal holds
run history alone (D-014).

### Consequences

- The core's surface is create from a snapshot, step to one, destroy, show and verify, with
  no timer of its own; an orchestrator that follows a branch calls the step.
- A twin of a 0.2 build left following across an upgrade keeps a Schedule that starts a
  workflow no worker serves: the release notes say to destroy it first, and the build
  carries no code to clear it.
- The rehearsal's baseline stops nothing, so every rehearsal's deadline is 30 s shorter.
- A twin built from a bundle directory still does not step: it names no snapshot and no
  scope.
- D-061's sentences that waited for this feature ("every workflow the core runs but the
  reconcile", "the reconcile workflow is untouched until F-026") now hold without the
  exception; D-061 is not superseded.
```

Each superseded entry gains, in its Status line, `; superseded by [D-062](#d-062) on
2026-10-28` with the part for D-012, D-007 and D-014 (`in its following`, `in its
Reconcile and Schedule`, `in its Schedule`), and nothing else. The index gains D-062.

## 4. Owed at implement

- **Before the records move** (the operator's): the roadmap's edits, D-062 in
  `docs/decisions.md` and this directory committed. D-062 is appended and R-27 settled
  (2026-10-28). The text in §3.1 is the draft; `docs/decisions.md` holds the entry as
  appended, with two consequences added (record 8, the constitution).
- **Tier 1**: the seven replays (§1.2) and `frozenContractCopies`'s new count, read, not
  assumed.
- **Live, the session's**: the worker and the server restarted from the rebuilt binary and
  verified as `CLAUDE.md` prescribes (with R-22's change to the worker's check); `temporal
  schedule list` empty again before tier 3; `twin step --snapshot` by hand on a fixture
  twin by file, by id and by dry run (quickstart §3); tier 2 whole; tier 3 whole and
  narrowed.
- **The records at the close**: `docs/verified-facts.md` gains, under Temporal, that a host
  of this build makes no Schedule (read by `temporal schedule list` after tier 3) and, under
  the step, that a step to a snapshot sends no request to Infrahub (tier 2's counters);
  `CLAUDE.md`'s worker counts, M4 line, Formats (`twin.json` `10`) and State.
