# Tasks: Following removed from the core

**Input**: Design documents from `/specs/019-following-removed/`: [plan.md](plan.md),
[spec.md](spec.md) (clarified 2026-10-28), [research.md](research.md) (§1 verified at plan,
§2 decisions R-01–R-27, §3 D-062 drafted, §4 owed at implement),
[data-model.md](data-model.md), [contracts/](contracts/) (`commands.md`, `formats.md`),
[quickstart.md](quickstart.md); the [brief](brief.md); Constitution 2.2.0 (not amended,
R-20); [D-062](../../docs/decisions.md#d-062), appended and committed at `a5e8b2d` with the
five *Superseded* status lines; [D-007](../../docs/decisions.md#d-007),
[D-012](../../docs/decisions.md#d-012), [D-014](../../docs/decisions.md#d-014),
[D-026](../../docs/decisions.md#d-026), [D-027](../../docs/decisions.md#d-027),
[D-061](../../docs/decisions.md#d-061).

**Tests**: requested. The brief's Exit, the spec's SC-001–SC-009 and quickstart §1, §4 and
§5 name each tier's cases, and each is a task below. Every format test validates against
the contract file under `contracts/`, and every earlier format against its frozen copy.
**No golden moves**: `testdata/golden/` must stay byte-identical to `main`'s after every
run (FR-021, SC-007). A run that changes it has broken the feature, and the loop will
stop.

**Organization**: the plan's order ("Order of the work"). Phase 2 lands what every later
phase stands on: the helpers moved out of the files that will be deleted, the side names
and the frozen copies. Then following leaves the core, in three phases that keep the tree
compiling: the worker (US1, Phase 3), destroy and the rehearsal (US1, Phase 4), and create
with its flags (US6 and US1, Phase 5, which completes the MVP). Then `twin show` and `twin
verify` (US5, Phase 6). Then the step widened: to a snapshot (US2, Phase 7), to a stage of
any proposed change (US3, Phase 8), with scope and mapping held (US4, Phase 9). Then the
tier-2 test (US2, Phase 10), tier 3's script and the contracts' prose (US6, Phase 11), the
documents (US6, Phase 12), the host, live (Phases 13–14), and the records at the close
(Phase 15). The loop runs the pure gates after every implement run, so every run must
leave the tree green: `make build`, static, `make test`, `make lint` (with tags
`contract,fixture,e2e`, so every tagged test must compile after every run). Story labels
mark which story each task builds or proves.

**Already done before this file** (brief, Exit; research §4): the roadmap's F-026 edits
(`759be50`), D-062 appended and the design directory committed (`a5e8b2d`), R-27 settled.
No operator task is owed before Phase 2 but T002, at `analyze`.

**Decisions this file takes, against or beyond the plan's text** (each for `analyze` to
settle at T002):

- **The follow types outlive the workflow code by a phase or two.** Phase 3 deletes the
  reconcile, the control activities and the provision workflow's three following paths,
  but the types and client methods the server still reads stay until the phase that
  removes their last reader: `ProvisionInput.StopFollowing`, `ProvisionResult.FollowingStopped`,
  `DestroyRun.FollowingStopped`, `FollowStop` and `Client.StopFollowing` until Phase 4;
  `ProvisionInput.Follow`, `FollowInput`, `ProvisionResult.Following`, `FollowingResult`,
  `DefaultInterval` and `MinInterval` until Phase 5; `FollowingState`, `CheckRecord`, the
  `Check*` outcomes, `FollowScheduleID`, `WorkflowReconcile`, `Client.Following`,
  `Client.LastCheck` and the checks in `InFlight` until Phase 6. So every run compiles and
  passes its gates. Between Phase 3 and Phase 5 a create on this tree sets a `Follow` that
  no workflow reads; nothing boots a twin before Phase 13.
- **The side names land first** (T006): `wire.StepSide.Name()` and
  `wire.TwinRecord.Position()` with their tests, before the show (Phase 6) and the step
  (Phase 7) switch to them.
- **`TestFollowingDetection` goes in Phase 3** (T013), with the code it guarded, not in the
  tier-2 phase. Phase 10 adds the new tier-2 test alone.
- **`intent.ErrBranchNotFound` stays.** Once `activities.go` goes, nothing outside
  `internal/intent` reads it, but the reader still marks a missing branch with it. Removing
  it would change the reader, which this feature does not touch (Constitution III). Its
  comment is reworded to name no consumer (T039).
- **Each rule constant retires with its last emitter**, in the phase that removes it, and
  leaves `dataModelRules` in the same run. T026 closes the seven following rules and the
  step `follow`; T033 retires `step.target.foreign`. T055 greps that all eight are gone.
- **The frozen copies are made in Phase 2, before any schema moves** (T007): formats.md
  §6's seven, each kept only where a test in that package validates a document of the 018
  shape. The count is recorded, and is 56 if all seven are kept.
- **`internal/server/follow.go` and `internal/provision/client_follow_test.go` keep their
  names.** They hold the run streaming, the meaning of "follow" that stays (following a
  run's events, glossary), not following a branch.
- **`twin.json` `10` lands at the head of the step phase** (T027). From then on every
  record this tree writes is `10`, and the tests that pin a new record's `twin_version`
  move in that run.
- **`infrahub/` is not edited.** A grep hit there (e.g. a comment on the 30 s stop) is
  recorded and left, since any change there needs an import into Infrahub, and FR-021
  changes no check.

**Tags**: `[operator]` marks a task that needs the operator: a decision, a spec amendment
or the review. `[live]` marks a task that needs the development host's server or worker
restarted from this tree, a twin, a hand check, the whole contract tier beside the server
on the bridge, or the end-to-end tier. Unattended, the loop stops at both. A single
tier-2 test a task names is not `[live]`: the loop's sessions hold Infrahub's address and
token and run it. Commits are by hand, conventional, with a body saying why, and end with
the model's `Co-Authored-By` trailer. A session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6, from spec.md

---

## Phase 1: Setup (the baseline and the decisions)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own; then settle this file's decisions at `analyze`.

- [X] T001 Run the pure gates from the repository root and confirm each passes: `make build`; `file bin/fylgja` reports a statically linked executable; `make test` uncached (`GOFLAGS=-count=1`; note the wall time against the 45 s budget, and the load average before and after); `make lint`; `go vet -tags contract,fixture,e2e ./...`; `git diff --stat main -- testdata/golden` is empty. Then read, writing nothing, and report each in this task's note:
  - `git status`: clean on `019-following-removed`.
  - `~/.temporalio/bin/temporal schedule list --address localhost:7233`: its header alone (research §1.1).
  - `ls internal/provision/testdata/*.history.json | wc -l` (expected 9) and `go test ./internal/provision -run Replay -v -count=1 2>&1 | /usr/bin/grep -c '^=== RUN'` (the replay cases today).
  - `find internal/*/testdata/contracts -type f | wc -l` (expected 49, `frozenContractCopies` in `internal/findings/frozen_contracts_test.go`).
  - The registration counts `TestWorkerRegistersEveryScheduledActivity` (`internal/provision/worker_test.go`) and `TestEveryActivityHasAFindingStep` (`internal/provision/client_follow_test.go`) assert today (expected 5 workflows, 20 activities).
  - `pgrep -x fylgja`: the worker and the server, each `/proc/<pid>/exe`, told apart by `/proc/<pid>/cmdline`.
  - *Note (Run 1, 2026-10-28, at `764f543`)*: every gate passes. `make build` is statically linked. `GOFLAGS=-count=1 make test` passes in 40.9 s wall, under the 45 s budget, at a load average of 1.99 before and 3.19 after, `internal/cli` 36.3 s of it (`internal/lab` 11.4 s, `internal/provision` 8.9 s). `make lint` reports 0 issues; `go vet -tags contract,fixture,e2e ./...` is clean; `git diff --stat main -- testdata/golden` is empty. The reads, nothing written:
    - `git status`: clean on `019-following-removed`.
    - `temporal schedule list`: the header (`ScheduleId  Action  Paused  NextRunTime  LastRunTime`) alone.
    - Nine histories: `cancel-during-follow`, `cancel-during-host-check`, `cancel-during-push`, `cancel-during-record`, `cancel-during-stop-following`, `push-after-cancel`, `step-cancelled`, `step-diverged`, `step-wait-cancelled`. Nine replay cases, all passing: `TestReplayCancelDuringRecordCleansUp`, `…HostCheckTouchesNothing`, `…DuringFollowStopsTheFollowing`, `…DuringStopFollowingNamesTheStop`, `…DuringPushCleansUp`, `TestReplayPushAfterCancelStillCancels`, `TestReplayDivergedStepRecordsEachPush`, `TestReplayCancelledStepRecordsDiverged`, `TestReplayStepWaitCancelledEndsStepped`.
    - 49 frozen contract files, and `frozenContractCopies = 49`.
    - `TestWorkerRegistersEveryScheduledActivity` asserts 20 activity names and five workflows: `Provision`, `Destroy`, `Step` and `Rehearse` by name, and `Reconcile` under the follow Schedule's action type name. `TestEveryActivityHasAFindingStep` asserts 20, the five `ControlActivities` and the fifteen `lab.Activities`.
    - `pgrep -x fylgja`: the worker, pid 2012205 (`bin/fylgja worker run`), and the server, pid 2012228 (`bin/fylgja serve --listen 127.0.0.1:7650 --listen 172.17.0.1:7650`), both started 2026-10-28 01:05:27. Each `/proc/<pid>/exe` reads `(deleted)`, because this run's `make build` replaced the binary. Neither was restarted, since this run starts and stops no process. No Go file has changed since `c8d46c7` (`git diff --stat c8d46c7 HEAD -- '*.go'` is empty), so they run this tree's code under an older VCS stamp. T048 restarts both from this tree.

- [X] T002 [operator] Settle at `analyze` this file's nine decisions (the header above), and amend `spec.md`, `plan.md` or `research.md` where an answer changes their text. A different answer changes: the first, Phases 3–6's split (T010, T015, T019, T021); the second, T006 and its callers; the sixth, T007 and `frozenContractCopies`; the eighth, T027. Record the operator's answers in this task's note.
  - *Note (`analyze`, 2026-10-28)*: the analysis found all nine consistent with the spec, the plan and the research, none changing their text; its edits were FR-008's `snapshot none` form for a record of 8 (spec and T022), T034's `--snapshot` twin case made unconditional, T037's query checked by hand at T048, and the wording of T025 and T030. The operator's confirmation is still this task's.
  - *Note (operator, 2026-10-28)*: all nine decisions confirmed as written ("all a"), and with them the notes' Run 4 as one run (T008 separable) and R-25's estimate; no text of `spec.md`, `plan.md` or `research.md` changes.

**Checkpoint**: baseline green; this file's decisions settled.

---

## Phase 2: Foundational — the moves, the side names and the frozen copies

**Purpose**: everything that later phases stand on and that must exist before a file is
deleted or a schema moves: the helpers moved beside their remaining callers, unchanged
(R-01), the side names (R-05), and the 018 shapes frozen (formats.md §6).

- [X] T003 [P] In `internal/provision`, move `withoutPresence` from `workflow_reconcile.go` into `workflow_step.go` beside `WithoutPresence`, and `alreadyStarted` and `childStartRefusal` from `workflow_reconcile.go` into `workflow_rehearse.go`. Cut and paste, bodies and comments unchanged; `workflow_reconcile.go` keeps compiling against them in the same package. `go test ./internal/provision` passes, and `go test ./internal/provision -run Replay` replays all nine histories.
  - *Note (Run 3, 2026-10-28)*: moved, bodies and comments unchanged: `withoutPresence` sits just after `WithoutPresence` in `workflow_step.go`; `alreadyStarted` and `childStartRefusal` just after `started`, their main caller, in `workflow_rehearse.go`, which gains the imports `errors`, `go.temporal.io/api/serviceerror` and `go.temporal.io/sdk/temporal`. `workflow_reconcile.go` drops its `serviceerror` import, which only `alreadyStarted` used. `go test ./internal/provision` passes, and `-run Replay` replays all nine histories, each passing.

- [X] T004 [P] Add `StoreMismatchMessage`'s body to `internal/server/filing.go` as an unexported `storeMismatchMessage(m *bundle.ErrIDMismatch, id string) string`, unchanged, and switch its two server callers (`filing.go`, `provision.go`) to it. `internal/provision/activities.go`'s own copy stays until T010 deletes the file. If a test pins the message, it moves to `internal/server` with it.
  - *Note (Run 3, 2026-10-28)*: `storeMismatchMessage` is at the end of `internal/server/filing.go`, its body unchanged. Its comment names its two callers, `fileCompiled` and `fileBundle` (`provision.go`). `filing.go` no longer imports `internal/provision`; the package still does, through `provision.go`, so the import graph and the C4 model don't move. No test pinned the message. The `cannot be filed` assertions in `internal/server/snapshot_test.go` and `read_test.go` check the snapshot store's own message, which is a different function, so nothing moved. `internal/provision/activities.go`'s exported copy stays until T010.

- [X] T005 [P] Move the two test helpers out of the files T010 deletes, cut and paste, unchanged: `wantRules` into `internal/provision/workflow_rehearse_test.go` and `repoPath` into `internal/provision/worker_test.go` (find each with `/usr/bin/grep -n 'func wantRules\|func repoPath' internal/provision/*_test.go`). `go test ./internal/provision` passes.
  - *Note (Run 3, 2026-10-28)*: `wantRules` is at the end of `workflow_rehearse_test.go` and `repoPath` at the end of `worker_test.go`, each unchanged. Both files already import what each helper needs (`slices` and `findings`; `path/filepath`). `go test ./internal/provision` passes.

- [X] T006 [P] Add the side names (R-05) in `internal/lab/wire/types.go`, with tests in a new `internal/lab/wire/names_test.go`:
  - `func (s StepSide) Name() string`: `stage <branch>/<label>` when the side names a stage; else `snapshot <first 8 of snapshot_id>…` when it names a snapshot; else `bundle <first 8 of bundle_id>…` (a side of an 8 record that stepped).
  - `func (r *TwinRecord) Position() string`: the same over the record's top level (`stage`, `snapshot_id`, `bundle_id`), keeping `SideStage`'s superseded-waypoint wording for a record of 5 or earlier that names a waypoint.
  - The tests cover each branch of each function, the `…` after the eight characters, and a record of 5 naming a waypoint.

  Nothing calls them yet: T022 and T029 switch the callers.
  - *Note (Run 3, 2026-10-28)*: `StepSide.Name()` sits beside `StepSide`, and `TwinRecord.Position()` beside `SideStage`. Both go through one unexported `sideName(stage, snapshotID, bundleID)` and `shortID`, the first eight characters and `…`, or a shorter id whole. An empty `snapshot_id` reads as none, so the name falls through to the bundle. `Position()` returns `SupersededWaypoint()` for a record with no stage and `Superseded`, which is `SideStage`'s wording. `StepSide.Name()` cannot see the record, so a superseded record's step side is still the callers' to word, as `SideStage` words it today (T029). `names_test.go` covers each branch of each function, the empty snapshot id, a record of 8, a record of 5 naming a waypoint (equal to `SideStage`'s wording), and `shortID` at 64, 9, 8 and 4 characters. `TestWireImportsNoIO` still passes.

- [X] T007 Freeze the 018 shapes before any schema moves (formats.md §6). Copy byte for byte, from `contracts/` as it stands:
  - `twin.schema.json` to `internal/lab/testdata/contracts/018-snapshots/twin.schema.json`;
  - `findings.schema.json` and `show.schema.json` to `internal/cli/testdata/contracts/018-snapshots/`, `internal/findings/testdata/contracts/018-snapshots/` and `internal/server/testdata/contracts/018-snapshots/`.

  Keep a copy only where a test in that package validates, or will validate in T020, T024 or T027, a document of the 018 shape (as `contract017` in `internal/cli/create_test.go` and `internal/server/helpers_test.go`, `snapshotFeature` in `internal/findings/snapshot_test.go` and `twinSchemaOf(t, "017-dcim-reader")` in `internal/lab/twin_test.go` read 017's). Add a `contract018 = "018-snapshots"` constant beside each `contract017`. Move `frozenContractCopies` by the number kept (49 → 56 if all seven). `TestFrozenContractCopiesAgree` passes. Record the count and any copy not made, with why, in this task's note.
  - *Note (Run 3, 2026-10-28)*: all seven made, copied byte for byte from `contracts/`, which equals `main`'s. `frozenContractCopies` is 56, and `TestFrozenContractCopiesAgree` passes. What reads each:
    - `internal/cli` and `internal/server`: `contract018` sits beside `contract017`, and `validateM10Document`, which every document test calls, now also validates each document as built against 018's copy (`validateWithShow`'s plain-marshal case in cli). Before the schemas move this holds trivially. T020's removals keep it holding, since neither `following` nor `dry_run.follow` is in any `required` list of the findings or show contract. Once a document carries a shape 019 adds (show kind `snapshot`, T022), the check needs a guard, as `namesSnapshot` guards 017's. That guard is T022's or T024's to add. Cost, A/B on `internal/cli`: 37.4 s without the check, 37.6 s with it.
    - `internal/findings`: `contract018` sits beside `snapshotFeature`. The new `TestAn018DocumentIsUnchanged` validates all 73 documents the package builds (`noSnapshotDocuments()` and `snapshotDocuments()`) against 018's copy. They include M4's following blocks and `dry_run.follow`, which are the 018-shaped documents T020 holds to that copy.
    - `internal/lab`: only `TestFrozenContractCopiesAgree` reads it until T027's 9-record test (`twinSchemaOf(t, "018-snapshots")`). The lab package has no `contract017` constant either, so none was added.
    - Not frozen: `stages`, `step`, `verify` and `rehearsal.schema.json`. The loaders read a block that a frozen directory lacks from `contracts/`, as they read `verify.schema.json` beside 017's copy, and their comments now say so for 018. One thing for T025 to know: the verify block's `twin` is defined in `contracts/verify.schema.json` (`$defs/verify/properties/twin`, `additionalProperties: false`), not in `findings.schema.json` as T025's text says, so `snapshot_id` lands there. Because the 017 and 018 copies both read the current `verify.schema.json`, and this build's documents will carry the new key, no frozen verify copy is needed for the tests to hold.

**Checkpoint**: `make test`, `make lint`; nothing yet removed.

  *Run 3's checkpoint, 2026-10-28 (T003, T004, T005, T006, T007)*:
  - **Commits**: `7bc2318` (T003, T005), `10a418c` (T004), `c4e1133` (T006), `9393bca` (T007), then this note. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 41.2 s wall, under 45 s, at a load average of 2.81 before and 4.07 after, `internal/cli` 36.7 s of it. Before the commits, the first uncached run took 49.2 s (load 3.99, then 5.42) because it recompiled every test binary the run had touched. With the build cache warm it took 41.8 s (load 4.98, then 5.67).
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
    - `go test ./internal/provision -run Replay -v` lists nine cases, all passing.
  - **Tier 2**: none run, since no task here names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. The worker and the server still run the binary T001 found `(deleted)`. This run's code changes nothing either one runs: two moves within packages, one message moved with its text unchanged, two names nothing calls yet, and test files. T048 restarts both.

---

## Phase 3: User Story 1, part 1 — the worker serves four workflows (Priority: P1)

**Goal**: the reconcile workflow, the five control activities and the provision workflow's
three following paths leave the worker; it serves provision, destroy, step and rehearse
and the lab's fifteen activities, and imports neither `internal/stage` nor
`internal/intent` (FR-001, FR-007, FR-020; R-01, R-02, R-16, R-22, R-24).

**Independent Test**: `TestWorkerRegistersEveryScheduledActivity` counts 4 and 15 with no
`Reconcile`; seven histories replay; `go list -deps ./internal/provision` names neither
`internal/stage` nor `internal/intent`.

- [X] T008 [US1] Move every tier-1 test that starts the provision workflow with no `BundleID` onto a compiled input (`BundleID`, `BundlePath`, `SnapshotID`, as the server builds it; R-16). The files: `internal/provision/workflow_provision_test.go`, `workflow_retry_test.go`, `workflow_unstage_test.go`, `workflow_heterogeneous_test.go`, `workflow_heartbeat_test.go`, `workflow_failure_test.go`, `workflow_cancel_test.go`, `workflow_bundle_test.go`, and `internal/cli/marker_test.go` (drop its `.reads/` CTM and its `Compile` detail; the marker proof stays). `workflow_helpers_test.go`'s `mockHappyPath` and its stubs lose `ReadIntent`, `Compile` and the follow activities. Find the rest with `/usr/bin/grep -ln 'ReadIntent\|ActCompile\|StartFollowing\|StopFollowing\|RunsInFlight' internal/*/*_test.go`. Each test keeps what it asserts about its own subject. `TestProvisionAlreadyCompiled` and `workflow_bundle_test.go`'s "ReadIntent did not run" assertions go, with the activities they named. The tests pass against the workflow before T009 changes it.
  - *Note (Run 4, 2026-10-28)*: `workflow_helpers_test.go` gains `compiled(branch)`: a create from intent as the server starts it, with bundle id, bundle path, snapshot id (`testSnapshotID`) and read time (`testObservedAt`). Every test in the eight files that started the workflow with no bundle id starts from it. The harness loses the `ReadIntent` and `Compile` stubs and `mockHappyPath` their mocks. `TestProvisionHappyPath` and the stage case now count ten activities from the host check. `TestProvisionAlreadyCompiled` goes, and so does the bundle test's "ReadIntent did not run" check, with the test renamed `TestProvisionFromBundleRecordsNoRead`. The failure table loses its five read and compile cases, and the cancellation table its two. `marker_test.go` compiles the fixture with `stage.Compile`, files it with `bundle.PutFiles` as the server does, and starts the run with that bundle and `snap.Take`'s id. Its `.reads/` CTM, its `Compile` event detail and its `ControlActivities` go; the marker proof is unchanged and passes. The follow stubs stayed in the harness through T008's commit (`d4c0f99`), whose follow tests still ran against them, and left with T009. The grep's other hits (`internal/cli`'s create, destroy, gone, provision, show, stage-create, step and verify tests, and `internal/server`'s rehearse and step tests) are `StopFollowing`, `Follow` and the show's reads, which belong to Phases 4–6.

- [X] T009 [US1] In `internal/provision/workflow_provision.go`, remove `stopFollowingBeforeStage`, `readAndCompile`, `startFollowing`, `FollowStartFailedMessage` and the `default:` source branch (R-01). A provision input with no bundle id ends `operation.failed` at its first step and schedules no activity; add a test for exactly that in `workflow_provision_test.go`. The fields `Follow` and `StopFollowing` stay on `ProvisionInput`, read by nothing in the workflow, until T016 and T019 remove them with the server's last writes.
  - *Note (Run 4)*: the three paths and the `default:` branch go. With them goes the workflow's `compiled` value: it reads the bundle from its input, and every activity input is unchanged, so the replays hold. An input with no bundle id ends at `untouched(…, StepHostCheck, …)`: error, `operation.failed` at `host_check`, with the message `NoBundleMessage`. `TestProvisionWithNoBundleSchedulesNothing` covers an intent, a snapshot and a bundle input. Each schedules no activity, skips both cleanups, exits 2 and validates against M2. The follow tests go: `TestProvisionReadsAndFollowsUnderItsScope` (renamed `…FollowsUnderItsScope` in T008), `…FollowBeginsAfterRecord`, `…FollowNilSchedulesNothing`, `…FollowStartFailed`, `…FollowCancelled`, `…StopStepBeforeStage`, `…StopStepNotScheduled` and `…StopStepFails`, along with `TestProvisionCreatesCarryTheirSnapshot`'s stop assertion. `internal/cli/create_test.go`'s one call to `FollowStartFailedMessage` now holds the message's literal text until T019 removes `TestCreateFollowStartFailed`. `Follow` and `StopFollowing` stay on `ProvisionInput`, read by nothing in the workflow.

- [X] T010 [US1] Delete `internal/provision/workflow_reconcile.go`, `workflow_reconcile_test.go`, `activities.go` and `activities_test.go` (after T003–T005). With `activities.go` go `ControlActivities`, its `bundles/.reads/` writes and reads (FR-007), and provision's own `StoreMismatchMessage` (T004 made the server's). Then remove every name in R-01's lists that nothing outside the deleted files still reads: from `types.go` (`ActRunsInFlight`, `ActStartFollowing`, `ActStopFollowing`, `ReconcileInput`, `ReconcileResult`, `RunsInFlightResult`, `StartFollowingInput`, `StopFollowingResult`, `ReadIntentInput`/`Result`, `CompileInput`/`Result`); `wire.ActReadIntent` and `wire.ActCompile` from `internal/lab/wire`; from `options.go` (`FollowCatchupWindow`, `FollowJitter`, `RunsInFlightBudget`, `ReadOptions`, `CompileOptions`, `RunsInFlightOptions`, `FollowOptions`), with their rows in `options_test.go`, which then stops importing `internal/stage`; and `findingStep`'s rows for the five control activities in `client.go`. Keep `InspectTwinBudget`, `ShowServiceBudget` and `ChildOptions`. Leave the names this file's first decision keeps for later phases, and list each left name with the task that removes it in this task's note. Rewrite `internal/cli/stage_parity_test.go` to hold `twin compile --snapshot` to the server's create path (`compileAndFile`, both on `stage.Compile`), the D-011 parity that remains (R-16). `go list -deps ./internal/provision | /usr/bin/grep -E 'internal/(stage|intent)$'` prints nothing.
  - *Note (Run 4)*: the four files are deleted, and so are the names T010 lists: `types.go`'s, `wire.ActReadIntent` and `wire.ActCompile`, `options.go`'s, and `findingStep`'s five rows. Four further things go with them, since nothing else read them:
    - `ReadBudget`, `CompileBudget` and `controlOptions`;
    - the rows for the five activities in `client.go`'s `stepName` and `completedDetail`, which name activities nothing schedules;
    - `options_test.go`'s `TestFixedStepBounds` (read and compile alone) and its `internal/stage` import;
    - `stage_create_test.go`'s `ControlActivities` and its `StopFollowing` stub.

    `TestStepNames` loses the five activities' rows. `ChildOptions`' and `InspectTwinOptions`' comments name the rehearsal and the step. `twin compile --snapshot` is now held to `twin create --snapshot` over the thirteen defect CTMs. One finding: `five.json` breaks rules `validate.Intrinsic` reads, so the create refuses it at compile before filing it (018's T082), with 5 of `twin compile`'s 7 rules. The test asserts that subset is Intrinsic's and is contained in `twin compile`'s, and equality otherwise. `go list -deps ./internal/provision` names neither `internal/stage` nor `internal/intent` (nor `internal/ctm`). The names left, each with the task that removes it:
    - T015: `Client.StopFollowing`, `stopFollowing`, `FollowStop`, `FollowStopError`, `FollowStopFailedMessage`, `DestroyRun.FollowingStopped`.
    - T016: `ProvisionInput.StopFollowing`, `ProvisionResult.FollowingStopped`, `StopFollowingResult`.
    - T017: `FollowBudget` and `DeadlineMechanism`'s `Follow`.
    - T019: `ProvisionInput.Follow`, `FollowInput`, `ProvisionResult.Following`, `FollowingResult`, `DefaultInterval`, `MinInterval`.
    - T021: `FollowingState`, `CheckRecord`, the seven `Check*` outcomes, `FollowScheduleID`, `WorkflowReconcile`, provision's `ReconcileInput` and `ReconcileResult` (`CheckRecord.Result`), `reconcileWorkflowType`, `followedBranch` (both moved into `client.go` beside their readers; `followedBranch` is T015's too), `runningChecksQuery`, `allChecksQuery`, `isCheck` and `stepName`'s check rows, `Client.Following`, `Client.LastCheck`, the checks in `InFlight`, and `client_test.go`'s `scheduleService`, `describedSchedule` and `scheduleNotFound`, moved there from `activities_test.go`.

- [X] T011 [US1] Register four workflows and fifteen activities. `provision.NewWorker(c, acts)` loses its `control` parameter (`internal/provision/worker.go`), `cmd/fylgja/worker.go` builds no `ControlActivities`, and `worker.go`'s and `doc.go`'s comments say four workflows, each started with a snapshot id and a bundle id, none reading a source of truth (R-22). `TestWorkerRegistersEveryScheduledActivity` asserts 4 and 15 and that `Reconcile` is not registered; `TestEveryActivityHasAFindingStep` asserts 15. `determinism_test.go` and `worker_options_test.go` drop any reconcile row. The start-up report is unchanged (it names packages).
  - *Note (Run 4)*: `NewWorker(c, acts)` registers four workflows and `lab.Activities.Names()`. `cmd/fylgja/worker.go` builds no `ControlActivities`, and its help says "its four workflows" (it said "both workflows", out of date since M4, which a convergence pass of 018 had noted). `worker.go`'s and `doc.go`'s comments say four workflows, the three that need one started with a snapshot id and a bundle id, none reading a source of truth. Two comments that called the rehearsal "a fifth short workflow" are reworded (`types.go`, `wire/types.go`). `TestWorkerRegistersEveryScheduledActivity` reads one table and asserts 15 names. It asserts the four workflows by the SDK's refusal of a second registration, and that `Reconcile` is not served: a first registration under that name is taken. `TestEveryActivityHasAFindingStep` asserts 15. `determinism_test.go` and `worker_options_test.go` held no reconcile row. The start-up report is unchanged.

- [X] T012 [US1] Delete `internal/provision/testdata/cancel-during-follow.history.json` and `cancel-during-stop-following.history.json`, with `TestReplayCancelDuringFollowStopsTheFollowing`, `TestReplayCancelDuringStopFollowingNamesTheStop` and the header comment's sentence on them in `workflow_replay_test.go` (R-02). The seven others stay byte-identical, re-recorded by nobody, with no `GetVersion` marker added. `go test ./internal/provision -run Replay -v -count=1` lists seven cases, all passing; record the list in this task's note.
  - *Note (Run 4)*: both histories, their two replay cases and the header comment's sentence (the t063-worker recordings) are deleted. The seven others are byte-identical (`git status` shows no change under `testdata/` but the two deletions). `go test ./internal/provision -run Replay -v -count=1` lists seven cases, all passing: `TestReplayCancelDuringRecordCleansUp`, `TestReplayCancelDuringHostCheckTouchesNothing`, `TestReplayCancelDuringPushCleansUp`, `TestReplayPushAfterCancelStillCancels`, `TestReplayDivergedStepRecordsEachPush`, `TestReplayCancelledStepRecordsDiverged`, `TestReplayStepWaitCancelledEndsStepped`.

- [X] T013 [US1] Delete `internal/stage/following_contract_test.go` (`TestFollowingDetection`, tier 2; R-17), and reword `internal/stage/stage.go`'s package comment: its read and compile serve the server alone, no provisioning activity. `go vet -tags contract,fixture,e2e ./...` passes.
  - *Note (Run 4)*: deleted. The package comment says the read and compile serve the server alone, and that no provisioning activity reads or compiles (019). `go vet -tags contract,fixture,e2e ./...` passes, and no Go file, script or workflow names the test. `docs/development.md`'s tier-2 row still names it, and that line is T043's.

- [X] T014 [US1] Redraw the C4 model in the same change (R-24). In `docs/c4/workspace.dsl`: the worker's `workflows` component describes four workflows, each taking a snapshot id and a bundle id, none reading; the `wstage` component and the relationship `workflows -> wstage "ReadIntent, Compile: a following check's"` go; the two `worker -> infrahub` relationships go; `temporal` is "Durable execution: run history"; the worker's deployment node names "both node logins; no API token". Then `make diagrams`, which also regenerates `docs/development.md`'s import graph from `go list` (the edges `internal_provision --> internal_stage` and `--> internal_intent` go). Commit the rendered views with the edit.
  - *Note (Run 4)*: edited as listed. The server's `stage` component also loses "shared with the worker" ("the server's alone"). `make diagrams` validated the model and re-rendered the five views' `.puml` and `.svg`. It regenerated `docs/development.md`'s import graph, which loses `internal_provision --> internal_stage`, `--> internal_intent` and `--> internal_ctm`. All committed with the edit (`b458f1c`). `docs/architecture.md`'s prose beside it is T040's.

**Checkpoint**: `make test`, `make lint`; 4 workflows, 15 activities, seven replays; the
worker reads no source of truth.

  *Run 4's checkpoint, 2026-10-28 (T008–T014)*:
  - **Commits**: `d4c0f99` (T008), `1386dd8` (T009–T012, one change: the workflow, the registration and the replays pass only together), `228d53f` (T013), `b458f1c` (T014), then this note. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 40.1 s wall, under 45 s, at a load average of 4.95 before and 5.08 after, `internal/cli` 35.7 s of it. The first uncached run, which recompiled the test binaries after the build, took 49.0 s (load 2.59, then 5.00), as Run 3's first did.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
    - Seven replays, 4 workflows, 15 activities.
  - **Tier 2**: none run, since no task here names a tier-2 test (T013 deletes one), and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **For T047**: `make linkcheck`, a hand tool and not this run's gate, finds 5 broken links in 2,063. All five are in this feature's own `brief.md` (lines 23, 76, 168, 169 and 170), and each points at a file this run deleted by design: `workflow_reconcile.go` twice, `workflow_reconcile_test.go`, `activities_test.go` and `following_contract_test.go`. No task edits the feature's brief (T042 is `docs/brief.md`), so T047's clean linkcheck needs them turned into code spans, the brief's sense unchanged.
  - **The host**: no process started or stopped. The worker (2012205) and the server (2012228) still run the binary T001 found `(deleted)`. That worker still registers the reconcile and the control activities, which nothing on this tree starts. T048 restarts both from this tree.

---

## Phase 4: User Story 1, part 2 — destroy and the rehearsal stop nothing (Priority: P1)

**Goal**: `twin destroy` is the destroy workflow alone, a create's provision stops nothing
before it stages, and every rehearsal's deadline is 30 s shorter (FR-005, FR-006; R-14,
R-15).

**Independent Test**: a destroy's events and document name no following; the rehearsal's
deadline tests read 1,950, 2,580, 2,400, 690 and 5,520.

- [X] T015 [US1] Destroy stops nothing first (R-14). In `internal/provision/client.go`: `destroy`'s step 2a (the second stop), `StopFollowing`, `stopFollowing`, `FollowStop`, `FollowStopError`, `FollowStopFailedMessage` and `DestroyRun.FollowingStopped` go; `DestroyDocument(subject, res)` loses its third argument; `StopFollowing` leaves the `Service` interface and every fake of it (`/usr/bin/grep -rn 'StopFollowing' internal --include='*_test.go'`). In `internal/server/destroy.go`, step 1a and both `doc.Following` writes go. Tests: `TestDestroyStopsFollowingAgain` and `TestStopFollowingOrder` (`internal/provision/client_test.go`) and `TestDestroyStopsFollowing`, `TestDestroyNoFollowing`, `TestDestroyFollowStopFailed` and `TestDestroyStopsFollowingAgain` (`internal/cli/destroy_test.go`) go. Add or keep one test in `internal/cli/destroy_test.go`: a destroy's events are the destroy run's alone, and its document has no `following` key (US1 scenario 4). `contracts/api.md`'s wording is T038's.
  - *Note (Run 5, 2026-10-28)*: the client's second stop, `StopFollowing`, `stopFollowing`, `FollowStop`, `FollowStopError`, `FollowStopFailedMessage` and `DestroyRun.FollowingStopped` go; `DestroyDocument(subject, res)`; `StopFollowing` leaves `Service` and its three fakes (`internal/cli`'s `fakeService` with its `stopEvents`, `stopResult` and `stopErr`, `gone_test.go`'s `stopHeld`, `internal/server`'s `rehearsingService`). The server's step 1a and both `doc.Following` writes go: a destroy's start frame now comes first, and a failure names `followed.get()`'s step alone. The four tests the task names go, and with them five more that tested a stop: `TestDestroyCancelsCheck`, `TestDestroyStopThenFails` and `TestDestroySecondStopFails` (`internal/cli/destroy_test.go`), `TestAServerStoppedDuringADestroy`'s "while following stops" case (`gone_test.go`), and `client_test.go`'s `stopScript`, `scriptStop` and `scheduleService.deletes`. `scriptDestroy` answers nothing of a Schedule or a listing, so a destroy that looked at one would fail every destroy test; `TestDestroyCancelsInFlightProvision` asserts `ScheduleClient` and `ListWorkflow` are never called, and the reclaim's "none" case expects `start destroy` alone. `TestDestroyAnswersWithAStartAndNoRun` expects the start frame first, then the destroy's events. Added: `TestDestroyStopsNothingFirst`, text and JSON: the calls are `StartDestroy` alone, the lines the destroy run's, and the document has no `following` key (US1 scenario 4). `followedBranch`, `reconcileWorkflowType` and `runningChecksQuery` stay, read by `Following` and `InFlight` until T021. `RuleFollowStopFailed` has no emitter left in product code; the constant is T026's. Commit `6e8b416`.

- [X] T016 [US1] A provision stops nothing before it stages. `internal/server/follow.go`'s `in.StopFollowing = true` (`runProvision`) and the baseline's `StopFollowing` in `internal/provision/workflow_rehearse.go` (about line 175) go, then `ProvisionInput.StopFollowing`, `ProvisionResult.FollowingStopped` and `provisionReport`'s stopped lines in `follow.go`. Tests: `TestCreateReplacesFollowing` and `TestCreateFollowStopFailed` (`internal/cli/create_test.go`) go; read `TestDestroyFollowsARehearsalsDestroyFirst` (`internal/server/step_test.go`) and the rehearse workflow's tests, and remove any assertion of a stop. The rehearse workflow's input to its baseline names no stop.
  - *Note (Run 5)*: `runProvision`'s `in.StopFollowing = true`, the baseline's in `workflow_rehearse.go` (and the workflow's doc comment, "which stops following"), `ProvisionInput.StopFollowing`, `ProvisionResult.FollowingStopped`, `StopFollowingResult`, `provisionReport`'s stopped line and `RehearseStage.Provision`'s "and StopFollowing" go. So does `cancelledFinding`'s message for a run cancelled at the stop step, which no run reaches since T009. `TestCreateReplacesFollowing` and `TestCreateFollowStopFailed` go, and `TestProvisionNotFollowing`'s `follow.stop.failed` case. `stop_following` leaves the expected inputs of `TestCreateFollowsByDefault`, `TestCreateNoFollow`, `TestCreatePinnedNotFollowing`, `TestProvisionNotFollowing` and three cases in `stage_create_test.go`, and those tests stop checking for a `StopFollowing` call. `TestRehearseRecordNamesTheRun` (`workflow_rehearse_test.go`) holds the baseline's child input to the server's with the rehearsal's reference alone added, and the server's rehearse test no longer checks `p.StopFollowing`. `TestDestroyFollowsARehearsalsDestroyFirst` asserted no stop and is unchanged; its fake lost its `StopFollowing` in T015. No recorded history is a rehearsal's, and the seven replays pass. Commit `86f143f`.

- [X] T017 [P] [US1] The rehearsal's deadline (R-15). In `internal/rehearsal/deadline.go`, `Mechanism` loses `Follow` (eleven fields to ten) and the baseline's sum its `m.Follow` term. `provision.DeadlineMechanism` loses its row, and `provision.FollowBudget` goes. In `internal/rehearsal/deadline_test.go` and every test that computes a deadline, the computed values fall by 30 s: 1,980 → 1,950, 2,610 → 2,580, 2,430 → 2,400, 720 → 690, 5,550 → 5,520 (still over the ceiling, still refused). Where 1,980 or 2,610 is a fixture's input or a rendered report and not a computed deadline, it stays: `markdown_test.go`, `report.go`'s comment, `internal/server/server_test.go` (about line 1107), `internal/provision/client_test.go` (about line 1621), `workflow_rehearse_test.go`. `TestTheTwinCheckOutlastsItsRehearsal` (`internal/rehearsal/check_timeout_test.go`) and `infrahub_yaml_test.go` are unchanged and pass. `infrahub/checks/fylgja_twin.py`'s `timeout = 4260` is not touched. Record each number moved and each left, with its file, in this task's note (SC-006).
  - *Note (Run 5)*: `Mechanism` has ten fields, the baseline's sum is `CheckHost + build`, and `DeadlineMechanism`'s row and `FollowBudget` (with its row in `TestFollowingConstants`) go. Numbers moved, each a computed deadline:
    - `internal/rehearsal/deadline_test.go`: 1,980 → 1,950, 2,610 → 2,580, 2,430 → 2,400, (600 + 120) → (570 + 120), 5,550 → 5,520 (still refused). The two-node case's sum loses its 30 s term, and the comments read baseline 570 and the mixed baseline 720.
    - `internal/provision/options_test.go`: the fixture's 1,980 → 1,950 (570 + 630 + 630 + 120), and `NumField` 11 → 10.
    - `internal/server/rehearse_test.go` (`TestRehearsalDeadlineFromTheStore`): 1,980 → 1,950, 33m0s → 32m30s.
    - `internal/cli/twin_rehearse_test.go`: the run's `DeadlineS` 1,980 → 1,950 (three tests), 2,610 → 2,580, 720 → 690; the rendered `of the 1980s deadline` → `1950s` (twice), `deadline 33m0s` → `32m30s`, the unfit `33m0s (1980s)` → `32m30s (1950s)`, the cut's message `1980s` → `1950s`, and that fixture's `UsedS` 1,980.2 → 1,950.2, just past the deadline it names.

    Left, each a fixture's input or a rendered report: `internal/rehearsal/markdown_test.go` (1980s, 2610s), `report.go:342`'s comment, `report_test.go` (`input(1980…)`, `input(2610…)`, `input(720…)`), `internal/findings/rehearsal_test.go` (1980, 2610), `internal/server/server_test.go:1107`, `internal/provision/client_test.go:1351` (the task's "about line 1621", moved by T015's deletions), `workflow_rehearse_test.go` (`rehearsalOf`'s 1,980, the cut's, `TestRehearseDeadlineNeverCutsTheDestroy`'s and `TestRehearseDeadlineOf`'s, each the run's input), and `internal/server/rehearse_test.go`'s `deadlineS: 1980` fixtures. `TestTheTwinCheckOutlastsItsRehearsal` and `infrahub_yaml_test.go` are unchanged and pass. `infrahub/` is untouched, and has no hit. Outside the code the figure stands in documents later tasks own: `docs/glossary.md:316` (T041), `docs/architecture.md:968` and `:1699` (T040), `docs/development.md:923` (`FollowBudget` among the constants, T043), `contracts/cli.md:593` and `:616` (an earlier section's sample, T038), and `README.md:582`, `:628` and `:654` (recorded output, T044). No task lists these lines; each needs its task to move them or say why they stay. Commit `327c082`.

**Checkpoint**: `make test`, `make lint`.

  *Run 5's checkpoint, 2026-10-28 (T015–T017)*:
  - **Commits**: `6e8b416` (T015), `86f143f` (T016), `327c082` (T017), then this note. Each passed its packages' tests and lint when committed. T015 held `FollowStopFailedMessage`'s text as a literal in the two tests T016 then removed. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 40.7 s wall, under 45 s, at a load average of 2.94 before and 2.74 after, `internal/cli` 36.3 s of it (`internal/lab` 11.4 s, `internal/provision` 8.6 s). The first uncached run after the build took 48.1 s (load 2.53, then 3.30), as Runs 3 and 4 found.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
    - Seven replays.
  - **Tier 2**: none run, since no task here names a tier-2 test, and nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. Between this run and T048, the running server (from T001's `(deleted)` binary) still stops following on a destroy, which finds no Schedule.

---

## Phase 5: User Story 6, part 1 — create follows nothing; the flags and the arguments go (Priority: P3, completing US1)

**Goal**: `--interval` and `--no-follow` are unknown flags, the API refuses `interval` and
`no_follow`, a create's document and dry run name no following, and the findings and API
schemas move (FR-003, FR-004, FR-019; R-12, R-13). With Phase 5, US1 is whole: the MVP.

**Independent Test**: each flag refused as an unknown flag, exit 2, with no request logged
by the harness; a raw `twin.create` with either argument answered 400; a create's document
has no `following` key and its dry run no `follow:` line.

- [X] T018 [US6] The client's flags (R-13). In `internal/cli/create.go`, `--interval`, `--no-follow`, their fields, `defaultInterval` and `minInterval` go; `TestFlagDefaultsAreTheCoresOwn` (`internal/cli/defaults_test.go`) loses its interval rows. The help texts of `internal/cli/create.go`, `show.go`, `destroy.go` and `step.go` lose following; a comment citing "M4's `--interval=` precedent" keeps the name and says it was `twin create`'s. Tests, after `TestCompileTakesNoCTM`'s template: `twin create --branch b --interval 30s` and `--no-follow` each fail `unknown flag`, exit 2, and the harness logs no request; the same for either flag on every other command of the root (a loop over the command tree). `TestCreateIntervalRefusals`, `TestCreateIntervalDefaultIsNotGiven` and `TestCreateNoFollow` (`internal/cli/create_test.go`) go or become these cases.
  - *Note (Run 6, 2026-10-28)*: `--interval`, `--no-follow`, their three fields, `defaultInterval` and `minInterval` go; `defaultBudget` stands alone, and `TestFlagDefaultsAreTheCoresOwn` holds it and `--wait` alone. `snapshotConflicts()` reads `--branch`, `--stage`, `--at` and `--scope`. The help texts:
    - `twin create`: "and the twin never follows" leaves the long text and `--snapshot`'s usage, and "never followed" leaves `--stage`'s.
    - `twin show`: the short text is "Say what twin there is and what it was built from". The long text loses "whether it is pinned, frozen or following, the last and next check".
    - `twin destroy`: the long text loses both stops. It now says a provisioning run in flight is cancelled and its cleanup waited for first, then a step run.
    - `twin step`: its help named no following; only its two comments moved.

    Every comment citing M4's `--interval=` precedent or rule now ends "a flag twin create had until 019", in the client (`create`, `step` twice, `read`, `stages`, `verify`, `rehearse`) and the server (`create`, `step` twice, `read`, `stages`, `verify`). `send.go`'s example is `"stage": ""`. Tests:
    - New: `TestNoCommandTakesTheFollowingFlags` (`create_test.go`) walks the client's tree as `AddCommands` builds it. It asserts the runnable commands are `api.Operations`, the thirteen. For each it runs `--interval 30s` and `--no-follow`, with `twin create` given `--branch b`, through the command line with `--json`. Each answer is cobra's `unknown flag: <flag>`, exit 2, and the harness logs no request (26 cases).
    - Gone: `TestCreateIntervalRefusals` and `TestCreateIntervalDefaultIsNotGiven`.
    - Renamed: `TestCreateNoFollow` is now `TestCreateFollowsNothing` (T019).
    - Gone or moved with the flags:
      - `TestCreateFlagsConflict` (`follow.flags.conflict` has no emitter left).
      - `connect_test.go`'s four `--interval` refusals.
      - `stream_test.go`'s `--interval=` case. It becomes `--stage=`, still a refusal before the start frame.
      - `TestSnapshotFlagConflicts`' three `--interval` cases.
      - `TestCreateDryRunFromASnapshot`'s `--no-follow` variant.
      - `TestCreateStageRefusedBeforeAnyConnection`'s four `--interval` cases. Its "first found" case keeps `--at` and `--branch`.
      - `TestCreateFromAStage`'s `--no-follow` case.
    - `noFollow`/`--no-follow`/`no_follow` leave `clients_test.go`, `create_snapshot_test.go`, `marker_test.go` and `gone_test.go`'s two raw requests (now answered 400). `send_test.go` sends `stage: ""` and `dry_run`.
    - `TestStepTakesNoBranchFlags` still lists both flags, unchanged.

    T018 and T019 are one commit (`818c231`): without `--no-follow` the client's tests create from the branch head, which the server followed until its half went, so neither half passes alone.

- [X] T019 [US6] [US1] The server's half. In `internal/server/handlers.go`, `interval` and `no_follow` leave `operationArgs["twin.create"]`, and `internal/server/server_test.go`'s argument table gains two rows answered 400 `the request is not one: twin.create takes no argument "interval"` (and `"no_follow"`). In `internal/server/create.go`, `followFlagsConflict`, `createFollow`, `followInterval`, `in.Follow` and `snapshotConflicts()`'s `intervalGiven` go, with `followFlagsConflict`'s call in `snapshot.go`, `neverFollows` in `resolve.go`, `followLine` and `dry_run.follow` in `dryrun.go`, and `provisionReport`'s following lines in `follow.go`. In `internal/provision`, `ProvisionInput.Follow`, `FollowInput`, `ProvisionResult.Following`, `FollowingResult`, `DefaultInterval` and `MinInterval` go. In `internal/findings/render.go`, `FollowingBlock`, `FollowingStarted`/`NotStarted`, `DryRunFollow` and the `FollowReason*` constants go; the `following` field leaves the document type. `stage.flags.conflict` (`internal/findings/finding.go` and its emitter) names `--branch` or `--at` beside `--stage`, no `--interval`. Tests: `TestDryRunFollowCreate` (`internal/server/dryrun_test.go`), `TestDryRunFollowProvision` (`internal/cli/dryrun_test.go`), `TestProvisionNotFollowing` (`internal/cli/provision_test.go`), `TestCreateFollowsByDefault`, `TestCreatePinnedNotFollowing` and `TestCreateFollowStartFailed` (`internal/cli/create_test.go`) go. Add: a `--branch` create's document has no `following` key, its dry run prints no `follow:` line and its JSON no `dry_run.follow` (US1 scenario 1).
  - *Note (Run 6)*: the server: `twin.create` takes neither argument, and `server_test.go`'s table gains the two 400 rows (`takes no argument "interval"`, `"no_follow"`). `followFlagsConflict`, `createFollow`, `followInterval`, `in.Follow`, the stage guard's `--interval` row and `neverFollows` go, and so do `snapshotGuards`' call, which now ends `nil`, `followLine`, `block.Follow` and the `follow:` line. `dryRunReport` and `runCreateDryRun` lose their `follow` parameter, and `twin provision`'s dry run passes none. `provisionReport` loses its input parameter and its whole following switch. A ready twin's text now ends at `twin directory …`, since the record line before it already names the stage and the at. `carriesRule` stays (other callers). In `internal/provision`: `ProvisionInput.Follow`, `FollowInput`, `ProvisionResult.Following`, `FollowingResult`, `DefaultInterval`, `MinInterval` and `ProvisionDocument`'s following block go. `options.go`'s "Following." heading becomes "Reads that change nothing.", over `InspectTwinBudget` and `ShowServiceBudget`, and `TestFollowingConstants` loses two rows (its others are T021's). In `internal/findings`: `FollowingBlock`, `FollowingStarted`/`NotStarted`, `FollowReason*`, `DryRunFollow`, `DryRunBlock.Follow` and `Document.Following` go, and `Document`'s comment says 019 removed both. `stage.flags.conflict`'s comment names `--branch` or `--at`. Tests:
    - Gone: the six the task names. `TestProvisionNotFollowing` keeps its record-line check as `TestProvisionReadyEndsAtTheTwinDirectory`.
    - Added (US1 scenario 1):
      - `TestCreateFollowsNothing` (`internal/cli`): the run's input is M3's compiled one, byte for byte with no `follow` key. The text ends at the twin directory and names no following. The document has no `following` key.
      - `TestDryRunSaysNothingOfFollowing` (`internal/server`): a create's dry run from `--branch` with no `--at`, and `twin provision`'s. Neither prints a `follow:` line, the verdict follows the `host:` line, and neither document carries `"follow`. Both are valid against the current contract, and the provision's against M6's. That keeps the server's `validateM6Document` read, since `TestDryRunFollowCreate` was its last caller.
    - Assertions of following left: the step dry run's `d.Follow`, the rehearse baseline's `p.Follow`, `wantSnapshotRun`'s `in.Follow`, the stage tests' `doc.Following`, `res.Following` and `DryRun.Follow`, and the stage create's closing `pinned at …; not following` line (now the twin directory's). The provision dry run's expected stdout (`answer_test.go`, `dryrun_test.go`) loses its `follow:` line.
    - `internal/findings`: the seven M4 documents with following leave `m4Documents` for `m4FollowingDocuments()`, of a new `earlierDocument` type. It holds this build's document and a `restore` that puts the removed keys back as raw JSON. They are held to M4's, M5's, M6's, 017's and 018's frozen contracts. `followingDocuments()` adds the stage (014) and snapshot (018) dry runs, held to 018's. Those two dry runs in `stageDocuments` and `snapshotDocuments` lose `Follow`, their key checks name the blocks' other keys, and the "follow reason the contract does not name" refusal goes.

    Left for later tasks:
    - `follow.interval.invalid`, `follow.flags.conflict` and `follow.start.failed` have no emitter and no Go reader but their definitions and `dataModelRules` (T026).
    - The show's "; not following" (T021, T022).
    - `ProvisionInput.Branch`'s and `Scope`'s comments still name "the following's checks" (T021, with `ReconcileInput`).
    - `scripts/e2e.sh` still passes `--no-follow` four times (lines 878, 921, 1022, 1272) and `--interval` once (1075). Tier 3 would refuse each as an unknown flag until T037 rewrites them, and it runs no earlier than Phase 13.

    Commit `818c231`, with T018.

- [X] T020 [US6] The two schemas (formats.md §2, §4). In `contracts/findings.schema.json`, `dry_run.follow` (and from `dry_run`'s properties) and `following` go, and the description gains the 019 sentence: the removals, pre-1.0, without a version move, as the API. In `contracts/api.schema.json`, `$defs/args/$defs/twin.create` loses `interval` and `no_follow` and keeps `additionalProperties: false`. Every document this build writes validates against the moved files; every test that validates a document of the 018 shape (one carrying `following` or `dry_run.follow`) validates it against T007's frozen `018-snapshots/findings.schema.json`.
  - *Note (Run 6)*: `findings.schema.json` loses `dry_run.follow` and `following`. Its description gains the 019 sentence: both removed, `findings_version` 1, accepted pre-1.0 as the API's version 1 accepts the create's two arguments going, and an earlier build's document held to the copy under `018-snapshots/`. The step enum's `follow` stays for T026. `api.schema.json`'s `twin.create` loses `interval` and `no_follow` and keeps `additionalProperties: false`. Its description gains a 019 sentence as each earlier feature's did; formats.md §4 names no description change, and T030 extends it for `twin.step`'s `snapshot`. Tests:
    - Every document this build writes is still validated against `contracts/` by the cli and server suites (`validateM10Document`, `validateWithShow(currentContract, …)`).
    - New: `TestFollowingLeftTheContract` (`internal/findings`). The current contract refuses each of the nine `followingDocuments()` with its keys restored, and accepts each as this build writes it. `TestAn018DocumentIsUnchanged` holds the same nine to 018's copy.
    - The M4 fixture's `follow.start.failed` warning is now restored as raw keys too, so no fixture builds it from `RuleFollowStartFailed` or `StepFollow`.
    - `internal/api`: `TestEveryOperationsRequestSatisfiesTheContract`'s two create requests lose both arguments. Two `invalid` rows refuse `twin.create` with either. Two transport tests that sent `interval` as an arbitrary empty argument send `stage`.

    No frozen copy moved (`frozenContractCopies` stays 56). Commit `680eae4`.

**Checkpoint**: `make test`, `make lint`. **MVP**: a twin is frozen at its snapshot, in tier 1.

  *Run 6's checkpoint, 2026-10-28 (T018–T020)*:
  - **Commits**: `818c231` (T018 and T019, one change), `680eae4` (T020), then this note. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 40.0 s wall, under 45 s, at a load average of 3.51 before and 4.08 after. The first uncached run after the build, on the T018–T019 tree, took 49.9 s (load 2.42, then 4.83), as Runs 3–5 found; `internal/cli` took 36.8 s of it.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
  - **Tier 2**: none run, since no task here names a tier-2 test, and no tagged test sends either flag or argument. Nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. The running server (from T001's `(deleted)` binary) still accepts `interval` and `no_follow`, and still follows a create from the branch head. T048 restarts it from this tree.
  - **MVP**: in tier 1, a create follows nothing, from any reference. Neither flag nor argument is taken, and no document or dry run names following. `twin show`'s following reads are Phase 6's.

---

## Phase 6: User Story 5 — `twin show` and `twin verify` name the snapshot (Priority: P2)

**Goal**: four kinds, the kind line naming the snapshot and its `at` or read time, no
following reads, `twin verify` naming the snapshot beside the bundle, and the following
rules retired (FR-008–FR-011, FR-004; R-10, R-11, R-12).

**Independent Test**: the kind line in each shape of [contracts/commands.md](contracts/commands.md)
"The text"; `twin show --json`'s kind `snapshot` for each twin from intent and `from_bundle`
for a provisioned one; none says pinned, frozen or following.

- [X] T021 [US5] The client's following reads go (R-10, R-14). In `internal/provision/client.go`: `Following`, `LastCheck`, `closedCheck`, `checkScheduledAt`, `isCheck`, `runningChecksQuery` and the checks in `InFlight`, which lists the operator's runs alone; in `types.go`: `FollowingState`, `CheckRecord`, the seven `Check*` outcomes, `FollowScheduleID` and `WorkflowReconcile`. `Following` and `LastCheck` leave the `Service` interface and every fake. `Follow`, `childEvents`, `Event` and `InFlight` stay. Tests: `TestFollowingDescribesTheSchedule`, `TestLastCheckFromTheSchedule` and `TestLastCheckWithoutASchedule` (`client_test.go`) and `TestFollowFollowsACheckChild` (`client_follow_test.go`) go; the `InFlight` tests lose their check rows. Lands in the same run as T022, whose show reads them. After it, `/usr/bin/grep -rn 'Schedule' internal cmd --include='*.go'` names no Temporal Schedule call.
  - *Note (Run 7, 2026-10-28)*: `Following`, `LastCheck`, `closedCheck`, `checkScheduledAt`, `isCheck`, `runningChecksQuery`, `allChecksQuery`, `followedBranch`, `reconcileWorkflowType`, `ScheduledCheck`, `FollowingState`, `CheckRecord` and `stepName`'s check rows go from `client.go`, and `FollowScheduleID`, `WorkflowReconcile`, the seven `Check*` outcomes, `ReconcileInput` and `ReconcileResult` from `types.go`. `Following` and `LastCheck` leave `Service`, its doc comment and the cli's `fakeService`. `InFlight` lists the operator's runs alone, with no listing (`ListWorkflow`) and no Schedule read. `ProvisionInput`'s `Branch`, `Scope` and `ObservedAt` comments no longer name the following's checks (T019's leftover). Two readers of the check form went with it: `rehearse.go`'s `holdingRun` loses its child branch (a rehearsal's child is listed under the rehearsal, which holds the host first), and `verify.go`'s `hostHolder` loses `rebuildInFlight`. **`Towards` now carries the side's name with its word** (`stage <ref>` or `snapshot <short>…`, by `StepSide.Name()`; a rehearsal's baseline `stage <ref>`), so T022's `stepping towards <Name()>` needs no second field, and `runInFlight` and `rehearsalAt` print it as given. Tests: the four named go, with `TestInFlightNamesTheSteps`' check subtest, `TestStepNames`' check rows (now a step run's inspect and a rehearsal's children) and the identities check of `TestReadOnlyConstants` (was `TestFollowingConstants`); `scheduleService`, `describedSchedule`, `scheduleNotFound`, `describedExecution` and `checkResult` go. `TestInFlightNamesAStepAndItsTarget` gains a snapshot target (`snapshot 9c2d01e7…`), and `TestInFlightNamesTheSteps` asserts `ListWorkflow` and `ScheduleClient` are never called. `worker_test.go` names the type `Reconcile` as a literal. `TestHoldingRunNamesTheFour` (was `…AndAChecksChild`) has a rehearsal with a child in place of the check rows. The `Schedule` grep finds no Temporal Schedule call: only `AssertNotCalled(t, "ScheduleClient")` in tests, a comment in `workflow_step.go`, and `internal/stage/stage.go:44`'s comment, which still says a following twin of before 017 reaches `Read`; that one is T039's.

- [X] T022 [US5] `twin show`'s kinds and lines (R-10). In `internal/findings/render.go`: the `ShowKind*` constants become `none`, `snapshot` (new), `from_bundle` and `diverged`; `ShowBlock` loses `Following` and `LastCheck`; `ShowFollowing` and `ShowCheck` go. In `internal/server/show.go`: `serviceReads` keeps in-flight runs alone; the rebuild, following and frozen rows, `scheduleWithoutTwin`, `followingStopped`, `createStartsAgain`, `showCheck`, `checkTime`, `rebuildInFlight` and the check forms of `runInFlight` go; `decideShow` writes R-10's table:
  - `snapshot_id` set and the record's `provenance.at` set (the envelope's, copied; show opens no snapshot file): `kind: snapshot <short> (branch B at T)`;
  - set with no `at`: `kind: snapshot <short> (branch B, read at <observed_at>)`;
  - intent with `snapshot_id` null: `kind: snapshot none (branch B at T)` when the record carries an `at` (a record of 8), else `kind: snapshot none (branch B, read at T)`, then the note `the twin's record names no snapshot, so fylgja twin step refuses it; fylgja twin destroy clears it`;
  - `from a bundle`, `diverged` and `none` as today, the diverged kind naming its sides by `Position()` (T006).

  After the bracket, as today: `, stage <ref>` when the record names one; `(stepped from <side name> by run fylgja-step <run>, ended <t>)` with the from side by `Name()`; the rehearsal's clause. "; not following" goes from every line; the best-effort note stays for a twin with no `at`. `show.service.unreachable`'s message becomes `the workflow service at <addr> did not answer within 5s: whether a run is in flight is unknown`, and the kind line's suffix `in flight: unknown (workflow service unreachable at <addr>)`. `stepTowards` names the run's to side by `Name()`: `stepping towards snapshot <short>` or `stepping towards stage <ref>`.
  - *Note (Run 7)*: `render.go` has `ShowKindNone`, `ShowKindSnapshot`, `ShowKindFromBundle` and `ShowKindDiverged`; `ShowBlock` loses `Following` and `LastCheck`; `ShowFollowing` and `ShowCheck` go. In `show.go`, `serviceReads` holds `inFlight` alone. These go: the rebuild, following and frozen rows, `scheduleWithoutTwin`, `createStartsAgain`, `followingStopped`, `showCheck`, `orSkipped`, `timeString`, `checkTime`, `rebuildInFlight`, the check form of `runInFlight`, and `printShow`'s last-check findings on stderr. `decideShow` gives none (a provisioning run holding the host, an empty host, a record without its lab), diverged, `from a bundle` for any bundle record (before 019 one with an at showed pinned), and `snapshotKind` for every other: R-10's table. Choices taken from the contract where the task's text and `contracts/commands.md` "The text" differ or say nothing, each for review:
    - The stepped bracket names a stage side by its reference alone, `(stepped from change-1/seeded by run …)`, as the contract's example and M11 do, and any other side by `Name()`, `(stepped from snapshot 576933ec… by run …)` (`stepSideRef`). The task says "by `Name()`", which would print `stage change-1/seeded`. The record block's step line names sides the same way. The diverged kind line names its target by `stepSideName` (a stage with its word) and where the twin is by `Position()`. So no show line prints `none` for a stage-less side. A record of 5 or earlier naming a waypoint keeps no stepped bracket on its kind line, as before.
    - Notes: the kind line is no longer a note (pinned's was). A snapshot kind notes the best-effort read for a twin with no at. A record naming none gets `the twin's record names no snapshot, so fylgja twin step refuses it; fylgja twin destroy clears it`, which also prints under the kind line. `from_bundle` notes `provisioned from a bundle; read time unknown`. 018's `built from snapshot <id>` note goes: the kind line names the snapshot, and the record line names it in full.
    - `show.service.unreachable`'s message is the task's, verbatim, with the server's budget: `… did not answer within 5s: …`, whatever the cause. The cause is no longer printed. `twin verify`'s own message for the identifier is unchanged.

- [X] T023 [US5] The show's tests, in `internal/cli/show_test.go`. `TestShowFollowing`, `TestShowFrozen`, `TestShowRebuildInFlight`, `TestShowFollowingStopped`, `TestShowFollowingStoppedSuperseded`, `TestShowFollowingOtherBranch`, `TestShowScheduleWithoutTwin` and `TestShowOrphanWithSchedule` go; `TestShowPinned` and `TestShowPinnedFromAStage` become snapshot cases. Cover each line of [contracts/commands.md](contracts/commands.md) "The text", with JSON kinds:
  - from `--branch` with no `--at` (US5 scenario 1);
  - from `--branch --at`, and from a stage, keeping `, stage <ref>` (scenario 2);
  - stepped from a stage, and stepped from a snapshot (scenario 3);
  - a rehearsal's baseline while it runs (scenario 4);
  - the workflow service unreachable: the host and record reported, `in flight: unknown`, nothing of following, exit 0 (scenario 5);
  - from a bundle, with `snapshot none` in the record line (scenario 6);
  - `snapshot none` with its note; and `none`.

  One case greps every rendered kind line for `pinned`, `frozen` and `following` and finds none (SC-005).
  - *Note (Run 7)*: `twinOf` names `showSnapshotID` (the live fixture's, `576933ec…`) by default, as a create of 018 or later does, and every record line moves with it. `steppedTwin` names both sides' snapshots (the target `9c2d01e7…`), and so does `steppedShowStep`. Gone: the eight named, and with them `TestShowRecordWithoutLab`'s three Schedule and stopped subtests, two of `TestShowProvisionInFlight`'s (its readiness case is kept without a Schedule), `TestShowServiceUnreachable`'s last-check subtest, `answer_test.go`'s stopped-following case, `verify_test.go`'s "an empty host a check is rebuilding" and `twin_rehearse_host_test.go`'s "a step run in flight under a check". Renamed: `TestShowPinned` → `TestShowSnapshotAt`, `TestShowPinnedFromAStage` → `TestShowSnapshotOfAStage`, and `TestShowFollowing` → `TestShowSnapshotReadAt`, which also asserts the service is read for `InFlight` alone. The cases:
    - Scenario 1: `TestShowSnapshotReadAt`.
    - Scenario 2: `TestShowSnapshotAt`, `TestShowSnapshotOfAStage` and `TestShowNamesTheStageAsRecorded`.
    - Scenario 3: `TestShowSteppedRecord`, `TestShowTwiceSteppedRecord` and the new `TestShowSteppedFromASnapshot`.
    - Scenario 4: `TestShowNamesARehearsalAndWhereItIs` (`internal/server`), its twin now a 9 naming `35aea06f…`.
    - Scenario 5: `TestShowServiceUnreachable`, over the read, a failing listing and the dial. Nothing says `follow`, and the exit is 0.
    - Scenario 6: `TestShowFromBundle`.
    - `snapshot none`: the new `TestShowSnapshotNone`, with an at and with a read time. `none`: `TestShowNoTwin`.
    - `TestShowStepInFlight` steps towards a stage and towards a snapshot (`stepping towards snapshot 9c2d01e7…`).

    SC-005: `showDialled` now fails any case whose kind line or note says pinned, frozen or following, and `TestNoKindLineNamesFollowing` runs six shapes and checks their JSON kinds. `TestShowSnapshotTwin` (`create_from_snapshot_test.go`) reads kind snapshot for a `--snapshot` twin, with and without an at.

- [X] T024 [P] [US5] `contracts/show.schema.json` (formats.md §3): `kind`'s enum `["none", "snapshot", "from_bundle", "diverged"]`; `following`, the top-level `last_check` and `$defs/check` go; `notes`' description loses the rebuild and the stopped following. Every show document T023 renders validates against it; a test reading an 018-shaped show document validates it against T007's frozen copy.
  - *Note (Run 7)*: `kind`'s enum is the four. `following`, `last_check` and `$defs` (whose one entry was `check`) go. `notes`' description now lists the best-effort note, the snapshot-none note, the orphan's remedy and a run in flight that holds the host; `in_flight.child`'s says no check is listed. The description gains a 019 paragraph (no version move, as the findings document's). Every show document the cli suite renders is now validated against the current contract and 018's copy: `showDialled` calls `validateM10Document` for every one, and M7's for those naming no stage, state or snapshot. An earlier contract reads kind `snapshot` as the kind that build wrote for the same twin, pinned with an at and frozen without (`restore018Kind`, in `internal/findings` and in `internal/cli`'s `as018Contract`, `as017Contract` and `asEarlierContract`), as `drop018Snapshots` lets 017's contract read 018's documents. `internal/findings`' 018-shaped show documents join `m4FollowingDocuments`: kinds pinned, frozen and following, the following block with its last check and a check in flight, and the last check of a stopped following. They are held to M4's through 018's copies, and the current contract refuses each (`TestFollowingLeftTheContract`). No frozen copy moved (56).

- [X] T025 [US5] `twin verify` names the snapshot (R-11, FR-010). The verify block's `twin` gains `snapshot_id` (`internal/findings/verify.go`; in `contracts/findings.schema.json` `{"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}` for a string, required). T020's 019 sentence in that schema's description gains this one addition beside the removals, still with no version move. It is the staged bundle's: the record's `snapshot_id` when the staged bundle is the record's, the step's `to.snapshot_id` when it is the step's target (a diverged twin), null otherwise. `internal/server/verify.go`'s first line becomes `twin: <ref> (snapshot <short>, bundle <short>), <state>; …`, `snapshot none` when null. Tests in `internal/cli/verify_test.go`: each of the three cases, text and JSON, valid against the contract (US5 scenario 7).
  - *Note (Run 7)*: the twin is defined in `contracts/verify.schema.json` (T007's note), so `snapshot_id` lands there, required, before `bundle_id`, with a 019 sentence in that file's description; `findings.schema.json`'s 019 sentence gains the addition. `verify.TwinOf` picks the staged bundle's snapshot: the record's when the staged bundle is the record's, the step's `to.snapshot_id` when it is the step's target, else nil. `findings.VerifyTwin.SnapshotID` writes it, null when nil. The first line pairs the record's snapshot with the record's bundle, which the line already names: `twin: <ref> (snapshot <short>, bundle <short>), <state>; …`, or `snapshot none` for a record naming none. Tests: `TestTwinOfNamesTheStagedSnapshot` (`internal/verify`, six cases); `TestBlock`'s twin with `snapshot_id` (null, and a diverged twin's target's); and `TestVerifyNamesTheSnapshot` (`internal/cli`), covering the record's, the step's target's and none, each first line and JSON, each document the contract's. Every earlier verify line gains `snapshot none, `. The diverged case keeps stage sides, because a stage-less diverged side still reads `towards none` on verify's line until T029 switches `SideName` to `Name()`. **Found, not fixed** (no task names it): `verify.schema.json`'s `twin.source` enum is `["intent", "bundle"]`, so a verify of a twin `twin create --snapshot` built writes `source: snapshot`, which the contract refuses. The gap is 018's, and no test verifies such a twin. It needs a task.

- [X] T026 [US6] Retire the seven following rules and the step `follow` (R-12). In `internal/findings/finding.go`, `follow.interval.invalid`, `follow.flags.conflict`, `follow.start.failed`, `follow.stop.failed`, `follow.stopped`, `check.skipped` and `rebuild.failed` go, with `dataModelRules`' rows in `finding_test.go`, and the step `follow` leaves the step constants and `contracts/findings.schema.json`'s step enum. Each that a grep still finds in product code is removed with its emitter. `TestEveryDataModelRuleHasAConstant` and its converse pass. `/usr/bin/grep -rn -e 'follow\.\(interval\|flags\|start\|stop\)' -e 'check\.skipped' -e 'rebuild\.failed' internal cmd contracts --include='*.go' --include='*.json'` finds only frozen copies and comments citing history.
  - *Note (Run 7)*: the seven constants and `StepFollow` go from `finding.go`, which keeps a comment naming them as retired. Their rows leave `dataModelRules`, and the new `TestTheFollowingRulesAreRetired` (beside `TestTheGenericsRulesAreRetired`) asserts that none is declared or in the table, and that no step constant is `follow`. `findings.schema.json`'s step enum loses `follow` (`TestStepConstantsMatchTheContractEnum` holds the two lists equal), and its 019 sentence names the seven and the step. No product code had emitted any of them since Runs 5 and 6. `TestEveryActivityHasAFindingStep` loses `StepFollow`. Outside the frozen copies, the grep finds:
    - `finding.go`'s retirement comment;
    - `finding_test.go`'s retired list, its comment on 018's `--interval` (reworded as history), and the M4 fixtures that restore an earlier document's raw rules (`follow.start.failed`, `rebuild.failed`, `follow.stopped`);
    - `findings.schema.json`'s description (M4's history and the 019 sentence).

    `TestEveryDataModelRuleHasAConstant` and `TestNoConstantIsUnknownToTheDataModel` pass.

**Checkpoint**: `make test`, `make lint`.

  *Run 7's checkpoint, 2026-10-28 (T021–T026)*:
  - **Commits**: `48b1f77` (T021–T024, one change: the server's show reads what the client no longer offers, and its tests validate against the moved show contract), `b69ab3d` (T025), `b263874` (T026), then this note. Files that carried two tasks' hunks were staged as each commit's version, and each commit was vetted with all tags and its packages' tests run in a throwaway worktree before the next. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 39.8 s wall with the build cache warm, under 45 s, at a load average of 4.74 before and 3.86 after, `internal/cli` 35.4 s of it. The first uncached run after the build took 46.0 s (load 3.84, then 4.02), as Runs 3–6 found.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
  - **Tier 2**: none run, since no task here names a tier-2 test. No tagged test asserts a line this run moved (the one show kind a contract test reads, `internal/checks`', is `none`). Nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. The running server (from T001's `(deleted)` binary) still shows following, the old kinds and verify's old first line. T048 restarts it from this tree.
  - **For later tasks**: `scripts/e2e.sh` case 5 still reads `.show.kind=="following"`, `.show.following` and the destroy's `.following` (lines 1078–1230), which is T037's rewrite. `internal/stage/stage.go:44`'s comment is T039's. A stage-less diverged side still reads `towards none` on verify's first line until T029. T025's note records a contract gap for a task: `verify.schema.json`'s `twin.source` lacks `snapshot`.

---

## Phase 7: User Story 2 — the operator steps a twin to a snapshot (Priority: P1)

**Goal**: `twin step --snapshot <id|file>` steps any twin whose record names a snapshot,
with no request to Infrahub for the target; the record moves to `10` (FR-012, FR-013,
FR-016–FR-018; R-03–R-05, R-09).

**Independent Test**: in tier 1, a step by id and by file from a twin built by each of
`--branch`, `--stage` and `--snapshot`, the record afterwards, the bundle twin refused, and
the fake Infrahub's counter unmoved by the target.

- [X] T027 [US2] `twin.json` `10` (R-09; formats.md §1). `lab.TwinVersion = "10"` (`internal/lab/twin.go`); in `contracts/twin.schema.json`, the `$id` `…/contracts/twin/v10`, `twin_version`'s const `"10"`, the `allOf` entry "stage ⇒ `source: intent` and `provenance.at`" reduced to "stage ⇒ `provenance.at`", and the descriptions: the top-level 019 paragraph (formats.md §1), and `source: intent` and `snapshot_id` with no following rebuild (an earlier build's rebuild). `NewRecord` drops its refusal of a stage beside `source: snapshot`. `NewStepRecord` is unchanged in code. Tests in `internal/lab/twin_test.go`:
  - a `--snapshot` twin stepped to a stage and a stage twin stepped to a snapshot, each written, read back and valid against the 10 schema (US6 scenario 3);
  - a 9 record read against T007's frozen `018-snapshots/twin.schema.json`;
  - the version gates (`scopeRecorded`, `snapshotRecorded`, the show's `v >= 5`) on `"10"`.

  Every test that pins a newly written record's `twin_version` `"9"` moves to `"10"` (`/usr/bin/grep -rn 'twin_version\|TwinVersion' internal --include='*_test.go'`).
  - *Note (Run 8)*: `lab.TwinVersion = "10"`, its comment naming 10. In `contracts/twin.schema.json`: `$id` `…/twin/v10`, the title `v10 … 018, 019)`, `twin_version`'s const `"10"`, the `allOf` entry reduced to "stage ⇒ `provenance.at`", and formats.md §1's 019 paragraph appended to the description verbatim. `source`'s description: intent's "or a check's rebuild did" is now "an earlier build's rebuild did", and a sentence says a step keeps `source`; `snapshot_id`'s null case names "an earlier build's rebuild"; the opening sentence's "or a check's" is now "or an earlier build's check". `NewRecord` drops its refusal of a stage beside `source: snapshot` and still refuses a stage on a bundle twin and an unpinned stage of any source; `NewStepRecord` is unchanged in code, its comment naming 10. **Found**: formats.md §1's reduction leaves the 10 contract admitting a stage on a `source: bundle` record, which `NewRecord` refuses and no step writes (`stepUnsourced` refuses a bundle twin, T028); `TestNewRecordRefusesAStageItCannotHold`'s comment says so. Tests:
    - `TestRecord10` (`internal/lab/twin_test.go`): a `--snapshot` twin stepped to a stage (`source: snapshot`, stage cabled) and a stage twin stepped to a snapshot (`source: intent`, `stage: null`), each written by `WriteRecord`, read back equal, valid against the 10 contract and refused by 018's frozen copy; and `NewRecord` accepting a snapshot twin naming a pinned stage. `TestRecord9StillReads`: four records as an 018 worker wrote them (a rehearsal's baseline, a snapshot twin, a bundle twin, a step with its wait), each valid against `018-snapshots/twin.schema.json` and read back as written. `TestRecord9` loses its two "snapshot twin naming a stage" refusals and gains the contract's refusal of an unpinned stage and of `twin_version` 9; `TestNewRecordRefusesAStageItCannotHold` runs its unpinned case over intent and snapshot. A helper `stepPrevWith` builds `stepPrev`'s create with its fields changed.
    - The version gates live in `internal/server/show.go`, not `internal/lab`, so their test is there: `TestVersionGatesReadTen` (`waitRecorded`, `scopeRecorded`, `snapshotRecorded` over 10, 9, 8, 5, 4, 1 and ""), `TestStepRefusesARecordThatNamesNoScope` over 8, 9 and 10, and `TestRecordLineNamesTheSnapshot` reading a 10 and a 9.
    - Pins moved to 10: `internal/lab/twin_test.go` (`TestCreateWritesVersion10`, `TestVersion10RecordCarriesEachWait`, `TestVersion10RecordRoundTrips`, and every assertion on a new record), `internal/cli/show_test.go` (`TestShowCreatedVersion10RecordAsM11`, the stepped record, and `TestShowTreatsAnUnreadableScopeAsUnknown`'s `(record 10 names …)`), `stage_create_test.go` (two) and `create_test.go` (the fake run's record). `scripts/e2e.sh`'s four `.twin_version=="9"` and three comments naming twin.json 9 move to 10, since `TestE2EScriptExpectsTheRecordsVersion` holds the script to `lab.TwinVersion`; the rest of the script is T037's. `shellcheck` is clean.

- [X] T028 [US2] The eligibility splits (R-03). In `internal/provision/workflow_step.go`, `Ineligible` loses its `Stage == nil` case and `origin()`, and its two no-twin messages say `a twin built from a snapshot steps (fylgja twin create --branch, --stage or --snapshot)`. In `internal/server/step.go`, add `stepUnsourced(rec)`, run after `Ineligible` and `stepScopeUnknown`, refusing `step.twin.unsteppable` (rejection, resolve, object the record's `bundle_id`) with R-03's three messages verbatim:
  - `source: bundle`: `the twin was provisioned from a bundle, which names no snapshot; only a twin whose record names a snapshot steps; fylgja twin destroy clears it`;
  - `twin_version` 8: `the twin was created from a record version that names no snapshot (twin.json 8); only a twin whose record names a snapshot steps; fylgja twin destroy clears it`;
  - 9 or 10 with `snapshot_id` null, not a bundle twin: `the twin's record names no snapshot (an earlier build's rebuild made it); only a twin whose record names a snapshot steps; fylgja twin destroy clears it`.

  A record of 7 or earlier keeps `stepScopeUnknown`'s refusal. Update `step.twin.unsteppable`'s comment in `finding.go`. Tests: `Ineligible`'s cases (`workflow_step_test.go`); the three refusals and the order against `stepScopeUnknown` (`internal/cli/twin_step_test.go`); the three step histories still replay (T012's list). The stage twin of record 8 that stepped under 018 now refuses (the clarification). `TestStepFromSnapshotTwinIsUnsteppable` (`internal/cli/create_from_snapshot_test.go`) is rewritten in T031, once a snapshot twin can step.
  - *Note (Run 8)*: `Ineligible` loses its `Stage == nil` case and `origin()`. Its no-twin message ends `a twin built from a snapshot steps (fylgja twin create --branch, --stage or --snapshot)`, and the orphan, unreadable, lab-gone and leftover one `<phrase>; a twin built from a snapshot steps; fylgja twin destroy clears it`: the parenthetical stands where the old one had `(fylgja twin create --stage)`. The superseded-waypoint message said "only a twin built from a stage steps" too, no longer true, so it is reworded with them (R-03 names two). `Step`'s comment says "the running twin". `stepUnsourced` (`internal/server/step.go`) runs after `Ineligible` and `stepScopeUnknown` with R-03's three messages verbatim, the bundle twin first whatever its version; `step.twin.unsteppable`'s comment gains its 019 clause. **Interim, for T031 and T034**: a twin naming a snapshot and no stage (`--branch`, `--snapshot`) now passes `Ineligible` and `stepUnsourced`, but the stage path reads the record's stage (`stages.Find` by its branch, the twin line), so `stepStageless` refuses it, `step.twin.unsteppable` at resolve, with the words `Ineligible` gave it before (`origin()`'s, whose bundle case is now unreachable). T031 lets a `--snapshot` target past it and rewrites `TestStepFromSnapshotTwinIsUnsteppable`; T034 replaces it with R-08's refusal and R-07's stage of any proposed change, and its `noStage` cases in `TestStepRefusedBeforeAnyConnection` go with it. Tests:
    - `TestIneligibleWording`: no twin, the four no-twin shapes and the superseded twin reworded; a branch twin, pinned or not, a snapshot twin and a bundle twin pass at resolve and at inspect. `TestStepRejectedAtEachLock`'s no-twin case reworded.
    - `TestStepRefusesARecordThatNamesNoSnapshot` (`internal/server/step_test.go`): `stepUnsourced`'s three refusals, a bundle twin of 8 refused as a bundle twin, and a 9 or 10 naming a snapshot passing whatever its source; `stepStageless` refusing a branch and a snapshot twin and passing a stage twin.
    - `TestStepRefusedBeforeAnyConnection` (`internal/cli`), each before Infrahub is asked: a bundle twin of 10 and of 8, a stage twin of 8, a stage twin of 9 and of 10 naming no snapshot, a branch twin naming none; and the order, a bundle twin of 7 refused naming its version and a 10 naming no snapshot and scope `fylgja` refused naming its scope. A record of 5 naming no waypoint is now refused by `stepScopeUnknown`, naming 5. The orphan shapes reworded.
    - The clarification: `TestStepNamesEachSidesSnapshot`'s "from an 8 record" is now refused, the dry run's included, with no request to Infrahub. `TestStepDryRunReconcileLifecycles`' `fromLess` twin names its snapshot, as `stepHost`'s does, since a 10 naming none is now refused.
    - The seven replays pass (`go test ./internal/provision -run Replay -v`).

- [X] T029 [US2] `stepTo` takes a target (R-04, R-05; data-model §2), a pure refactor. In `internal/server/step.go`, add `stepTarget{name, stage *wire.StageRef, snapshotID, bundle step.Bundle, at, branch, observedAt}`; `stepTo` and `stepInput` take it in place of `stages.PlanStage`, and the stage path fills it from the `PlanStage` and its `Resolved`. Switch the side names to `Name()`/`Position()` (T006): `step.Between`'s callers (the stage part without its word, as today), `m11Closing`, `stepClosing`, and in `internal/provision/workflow_step.go` `divergedTwin` and `notPlannedFrom` (message text only; no command moves, so the replays hold). Every existing step test passes with its text unchanged for stage sides.
  - *Note (Run 8)*: `stepTarget` as data-model §2 draws it, its `name` the side as `step.Between` names it. `stageTarget(built)` fills it from the `PlanStage` and its `Resolved` (named by `built.Ref.String()`, as before); `recordSide(rec)` is the from side, which `stepInput` and `step.Between` share; `betweenName(side)` names a stage by its reference alone and any other side by `Name()`. `stepTo` and `stepInput` take the target. `m11Closing`, so `stepClosing`, names each side by `Name()`; `divergedTwin` by the to side's `Name()`, a superseded record's waypoint kept; `notPlannedFrom` by `rec.Position()` and `from.Name()`. Beyond the list: `divergedFinding` (the run's `step.diverged`) by `Name()` too, the same text on the run's side, and verify's diverged clause by `stepSideRef` (show's), which T025's note left reading `towards none` for this task. No existing test's text moved. Tests: `TestStepClosingNamesASnapshotSide` (`internal/server`, the three closing lines towards a snapshot from a twin at one), `TestStepTextsNameASnapshotSide` (`internal/provision`: `step.diverged` towards a snapshot from a stage and from a snapshot, `step.twin.diverged`, the second lock between two snapshots), and `TestVerifyNamesTheSnapshot`'s diverged case towards a snapshot. T032 tests the lines through the command.

- [X] T030 [US2] `--snapshot` on the client and the API (R-04).
  - `internal/cli/step.go` gains `--snapshot <id|file>`, read and sent as `twin create`'s is: share `isSnapshotID`/`readSnapshot` with `internal/cli/create.go`. An explicit empty `--snapshot=` with no `--stage` beside it names no file and is the client's own refusal, as on create. The file is read only when `--stage` is not also given; with both given the client sends the request with no file, for the server to refuse. The help says "a snapshot of any branch".
  - `internal/server/handlers.go`: `twin.step` takes `snapshot` and joins `takesFiles`.
  - `contracts/api.schema.json`: `$defs/args/$defs/twin.step` gains `"snapshot": {"type": "string"}`, and the request's `files` description names `twin.step` beside a `snapshot` path.
  - `internal/server/snapshot.go`: `snapshotFiles` is generalised to name its operation (one file under the `--snapshot` path when it is not an id, none otherwise).
  - The guard is the server's, at step `start`, exit 2, as create's is (Constitution XI): `--stage` beside `--snapshot` is `snapshot.flags.conflict`, object `--stage`, message `--stage is meaningless with --snapshot: the snapshot is the target` (US3 scenario 6); `snapshot.flags.conflict`'s comment names the step's case.

  Tests in `internal/cli/twin_step_test.go`: each guard refused with no request logged; `TestStepTakesNoBranchFlags` still holds; a raw `twin.step` request with a second file, or a file beside an id, is `operation.failed`, as on create.
  - *Note (Run 9)*: the client's `--snapshot` (`internal/cli/step.go`) is sent by `snapshotSent`, one helper `twin create` now shares (`create.go`): an id as it is, else the file read and sent under its path; `--snapshot=` and an unreadable file are the client's own `operation.failed`. With `--stage` beside it no file is read. The help keeps the sentence two help tests pin ("The API's server resolves the target, reads it, …") and adds the `--snapshot` clause; its Short is now "Take the running twin to another stage or a snapshot, without a rebuild", and the flag says "a snapshot of any branch". `handlers.go`: `twin.step` takes `snapshot` and joins `takesFiles`. `snapshotFiles` takes `(op, subject, given, arg, files)` and names the command from the operation (`twin create`, `twin step`), so create's messages are unchanged. The server's guard runs first in `runTwinStep`, then `snapshotFiles`, then the stage and wait guards. `contracts/api.schema.json`: `twin.step.snapshot`, the files description and the 019 sentence of the description; `contracts/findings.schema.json`'s `subject.snapshot` names `twin.step --snapshot`; `snapshot.flags.conflict`'s comment names the step's case. Tests: `TestStepSnapshotBesideAStageIsRefused` (`--stage=change-1/linked` and `--stage=` beside an id, a file, a file not there and `--snapshot=`: one refused step logged by the server, nothing dialled, inspected, asked or filed), `TestStepSnapshotTheClientCannotSend` (no request logged), `TestAStepsFilesAreOneSnapshotFile` (five raw shapes through `send`, each `operation.failed` naming `twin step`); `TestStageHelpsNameTheServersTake` holds the new help words.

- [X] T031 [US2] The server's snapshot path (R-04; data-model §2). In `runTwinStep`, after the host is read, judged eligible (T028) and its scope known, a `--snapshot` target is resolved by `resolveSnapshot`, create's own: store lookup, or the file through `snapshot.Unmarshal`, `validate.Intrinsic` and filing. No `intent.StageReaderFromEnv`, `stages.Find`, `Target` or `Build` runs. The CTM compiles and its bundle is filed by `compileAndFile`, each refusal at compile as on create, and a `stepTarget` is built from the envelope (`branch`, `at` verbatim, `""` when unpinned) and the stored snapshot's `observed_at`. `stepTo` continues unchanged. Tests in `internal/cli/twin_step_test.go`, against the harness's fake Infrahub with its request counter:
  - **By id and by file, from each reference** (US2 scenarios 1–3): from twins built by `--branch`, `--stage` and `--snapshot`. Afterwards the record names the target's snapshot, bundle, branch and `at` and no stage, and keeps its `source`; the step block's from side names the stage (from a stage twin) and its to side `stage: null`; the fake Infrahub saw no request for the target. Rewrite `TestStepFromSnapshotTwinIsUnsteppable` as the `--snapshot` twin's case.
  - **Refusals and outcomes**: the bundle twin refused, naming no snapshot (scenario 4); `snapshot.unknown` naming the id, and `snapshot.id.mismatch` naming both ids, before any run (scenario 5), with `snapshot.invalid` and `snapshot.version.unsupported` as on create; the bundle equal to the twin's is `unchanged` (scenario 6); a compile refused (a platform no package matches) before any run, twin untouched (scenario 7).
  - **Edges**: a snapshot of another branch under the same scope steps, and the record names that branch (US4 scenario 3); a file with no declared id is filed under its computed id; a snapshot failing the CTM's own rules is refused before any compile; `run.in_flight` and `step.twin.diverged` as today for a snapshot target (FR-017).
  - *Note (Run 9)*: `runTwinStep` judges the twin (`Ineligible`, `stepScopeUnknown`, `stepUnsourced`), runs `stepStageless` on the stage path alone (until T034), prints the twin line and, for `--snapshot`, hands over to `stepToSnapshot`: `resolveSnapshot`, the target line, `compileAndFile` (`compiledRead` now keeps the compiled files for the target's `step.Bundle`), and `stepTo` with a `stepTarget` named by `wire.StepSide{SnapshotID}.Name()`. A package override that fails to load is refused at compile for `--snapshot`, as on create. T035's `targetUnheld` is not here. **Found**: R-05 names a stage-less side `snapshot <short>…` in the step's diff, which `stages.schema.json`'s `$defs/step` refused (`from`/`to` were `$defs/ref`, `<branch>/<label>`); formats.md §5 said `step.schema.json` was unchanged and missed it. `$defs/side_name` (a reference, or `^snapshot [0-9a-f]{8}…$`) now names both, with a 019 sentence in the description: additive, so every earlier document validates, and no frozen copy is needed. T038 may name it in `contracts/cli.md`'s 019 section. Tests: `TestStepToASnapshot` (from `--branch` unpinned, `--stage` and `--snapshot`, each by id and by file: the run's two sides and observed_at, the document, no request to Infrahub, the file filed; then `recordOnHost` runs the worker's own `RecordStep` on the staged target and the record validates against twin.json 10, naming the target's snapshot, bundle, branch and at, no stage, its source kept); `TestStepFromSnapshotTwin` (`create_from_snapshot_test.go`, the rewritten `TestStepFromSnapshotTwinIsUnsteppable`); `TestStepToASnapshotRefused` (a bundle twin, a diverged twin, `snapshot.unknown`, `snapshot.id.mismatch` naming both ids, `snapshot.version.unsupported`, `snapshot.invalid`, the CTM's own rule at compile with nothing filed, and `platform.unsupported` at compile with the file filed and named by its stored line; twin.json unchanged and no run started in each); `TestStepToASnapshotEdges` (the twin's own snapshot unchanged, a snapshot of branch `other` recorded as `other` under `tag:fylgja`, a file declaring no id, `run.in_flight`).

- [X] T032 [US2] The dry run and the text for a snapshot target (R-04, R-05; [contracts/commands.md](contracts/commands.md) "The text"). `--dry-run --snapshot` prints:
  - the twin line, in its stage-less form for a twin that names no stage: `twin: snapshot <short> (bundle <short>), branch B at T; N nodes` or `…, branch B, read at T; N nodes`;
  - `target: snapshot <short> (branch B at T | branch B, read at T)` in place of the stage's resolution line;
  - the step (`step snapshot 576933ec… → snapshot 9c2d01e7… (… → …):`), `reconcile:` and `push:`.

  It files the snapshot (when sent) and the bundle and starts no run (US2 scenario 8). The closing lines for a snapshot target: `stepped to snapshot <short> (bundle <short>) in …`, `unchanged; the record moves to snapshot … (bundle …) in …`, `diverged towards snapshot … (bundle …) at phase …; the twin is up at <Position()> (bundle …); fylgja twin destroy clears it`. Tests in `internal/cli/twin_step_test.go` for each line, and for `twin show`'s `stepping towards snapshot <short>` while such a step runs.
  - *Note (Run 9)*: the twin line (`stepTwinLine`) and the target line are T031's code, since its path prints them; `branchRef` (`show.go`) now words both and twin show's kind line. The closing lines needed no change (T029's `Name()`). Tests: `TestStepToASnapshotDryRun` (the whole stdout from a stage twin, a branch twin pinned and read, and to a snapshot read with no at, whose target line says `read at` its observed_at; the snapshot and bundle filed, no run, the twin directory unchanged, no request to Infrahub) and `TestStepToASnapshotCloses` (stepped, unchanged to the twin's own snapshot, diverged from a stage twin and from a snapshot twin; then twin show, given the run's own input's `To.Name()` as the service reads it, says `stepping towards snapshot <short>` on the kind line and in its notes).

**Checkpoint**: `make test`, `make lint`.

  *Run 8's checkpoint, 2026-10-28 (T027–T029)*:
  - **Commits**: `008e40f` (T027), `0936f8f` (T028), `6701869` (T029), then this note. The four files that carried two tasks' hunks (`internal/server/step.go`, `step_test.go`, `internal/provision/workflow_step.go`, `workflow_step_test.go`) were staged hunk by hunk. The first two commits were vetted with all tags and their packages' tests (`internal/lab`, `lab/wire`, `server`, `provision`, `cli`, `findings`, `verify`) run in throwaway worktrees; the third is the tree the gates below ran on. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 40.3 s wall with the build cache warm, under 45 s, at a load average of 3.41 before and after, `internal/cli` 35.7 s of it. The first uncached run after the build took 48.6 s (load 3.06, then 3.71), as Runs 3–7 found.
    - `make lint` reports 0 issues; `go vet -tags contract,fixture,e2e ./...` is clean; `shellcheck scripts/e2e.sh` is clean.
  - **Tier 2**: none run, since no task here names a tier-2 test, and no tagged test reads a text or a version this run moved. Nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped.
  - **For later tasks**: `stepStageless` and the `noStage` cases are T031's and T034's (T028's note). `contracts/cli.md`'s `step.twin.unsteppable` row (about line 437) still says a record "naming no stage" is refused; T038's prose. `NewStepRecord`'s refusal of a record whose stage is not the from side's still names a nil stage `stage none` (`internal/lab/twin.go`), outside T029's list and met by no planned step. The rest of `scripts/e2e.sh` is T037's, its record version already 10.

  *Run 9's checkpoint, 2026-10-28 (T030–T032)*:
  - **Commits**: `e86ec20` (T030 and T031, one change: a `--snapshot` the server could not yet act on would have stepped a stage twin to its next stage), `adc3983` (T032's tests), then this note. `internal/cli/twin_step_test.go` carried both commits' hunks: the first was committed without T032's two tests, vetted with all tags and the package's step, snapshot and help tests run, and the second added them. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 42.0 s wall with the build cache warm, under 45 s, at a load average of 3.55 before and 5.00 after, `internal/cli` 37.6 s of it (35.7 s at Run 8; this run's tests add about 2 s). The first uncached run after the build took 47.4 s (load 3.01, then 3.94), as Runs 3–8 found.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
  - **Tier 2**: none run, since no task here names a tier-2 test; the tagged tests compile against the new `runTwinStep(…, files)`. Nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. `make build` replaced the binary, so the running worker's and server's `/proc/<pid>/exe` read `(deleted)`; T048 restarts both from this tree.
  - **For later tasks**: `stepStageless` and the `noStage` cases of `TestStepRefusedBeforeAnyConnection` are T034's (a stage-less twin with no target, or with `--stage`, still meets it). T035's `targetUnheld` goes into `stepToSnapshot` after `resolveSnapshot` and before `compileAndFile`. T037's `jq` filters can be checked against a document of `TestStepToASnapshot` or `TestStepToASnapshotDryRun`. T038: `stages.schema.json`'s `side_name` (T031's note) beside formats.md §5's `step.schema.json` sentence.

---

## Phase 8: User Story 3 — a step to a stage of any proposed change (Priority: P2)

**Goal**: `--stage` names a stage of any proposed change, is required for a twin that names
no stage, and `stage.twin.moved` is given only within the record's own proposed change
(FR-014; R-07, R-08).

**Independent Test**: US3's six scenarios in tier 1, the no-target refusal with nothing
dialled.

- [X] T033 [US3] `stages.Target` and `stages.Moved` (R-07). In `internal/stages/target.go`, `Target(ch *Change, view *RecordView, recordBranch, recordAt string, given *Ref)`. Let `same` be "the view names a stage of the found proposed change":
  - with a given reference and not `same`, the target is the given label, refused `step.target.unknown` naming the proposed change's stages when it lacks it, and no `step.stage.skipped` warning;
  - with `same`, today's rules 3–6 hold;
  - rule 5, `step.target.current`, judges every target against the record's `(branch, at)`, stage or not;
  - no reference given with the record's proposed change closed stays `step.target.unknown`.

  `step.target.foreign` retires: its constant, its `dataModelRules` row and every emitter go. In `internal/stages/list.go`, `Moved` applies only when `same`; `recordView` still returns nil for a stage-less record. Tests in `target_test.go` and `list_test.go`:
  - a nil view;
  - a given reference in another proposed change, present and absent;
  - rule 5 for a stage-less record;
  - `Moved` silent for another proposed change.

  Callers in `internal/server` are adapted to the new signature, with behaviour moved in T034.
  - *Note (Run 10, 2026-10-28)*: `Target(ch, view, recordBranch, recordAt, given)`. `same` is `view != nil` and the view's proposed change is the one found. A given reference is the target in the found proposed change, refused `step.target.unknown` naming its stages when it lacks the label (rule 4's words, now for any proposed change). With `same`, rules 3–6 hold as before; rule 5 compares against `recordBranch` and `recordAt`; rule 6 (skipped) applies only when `same`. With none given, a nil view is refused `step.target.unknown` with R-08's message, now `stages.NoTargetMessage`, its object the record's branch. The server refuses that case first, naming the bundle (T034), so this one is defensive. Choices for review:
    - **Rule 2's message is reworded.** It ended "a step stays inside the proposed change the twin was built from", which 019 makes false. It now ends `…is pc-9), so the twin has no next stage; give --stage <branch>/<label> or --snapshot <id|file>`. `contracts/cli.md`'s rows (its `step.target.foreign` row at about line 438, and the rule-2 wording) are T038's prose.
    - **`step.target.foreign` is retired.** Its constant goes, and `finding.go`'s M11 block comment says why. Its `dataModelRules` row goes, and the new `TestTheForeignTargetIsRetired` asserts neither is back. `findings.schema.json`'s 019 sentence names it beside the step `follow`. Its emitter in `target.go` goes. The grep now finds it only in comments citing history and in frozen copies.
    - **`Moved`**: a found proposed change of another id now returns nothing. That is a target outside the record's proposed change. A nil change still gives the listing's "no longer open" warning. The listing never passes one of another id. Its doc comment says so.

    Tests: `TestTargetByPosition` loses its two foreign cases and takes rule 2's new words. The new `TestTargetOfAnyProposedChange` has eleven cases:
    - another branch's proposed change, its label present and absent;
    - another proposed change on the record's branch, across a mark with nothing skipped, a label absent, and a stage at the record's own reference (`current`);
    - a nil view: a given stage, one of another branch, one absent, one at the record's own (branch, at) (`current`), an unpinned record, and none given.

    `TestMovedOfTheFoundChange`'s reopened case is now silent. It gains another branch's proposed change, also with the record's head moved. `foundChange(t, branch, …)` generalises `targetChange`.

- [X] T034 [US3] The server's stage path (R-07, R-08).
  - **Which proposed change**: `stages.Find` reads the given reference's branch when `--stage` is given, else the record's stage's branch.
  - **No target**: with neither `--stage` nor `--snapshot`, the server reads the twin directory's record (`lab.ReadRecord`, no connection) before `rehearsalHolds` dials the workflow service. A readable record naming no stage is refused `step.target.unknown` (rejection, exit 1, resolve, object the record's `bundle_id`): `the twin names no stage, so there is no next stage to step to; give --stage <branch>/<label> or --snapshot <id|file>`. An absent or unreadable record, or one that names a stage, goes on as today.
  - **The warning**: `stage.twin.moved` only when `same`.

  Tests in `internal/cli/twin_step_test.go` (US3 scenarios 1–5):
  - a `--branch` twin with no target is refused, with the fake workflow service and the fake Infrahub both untouched;
  - it steps to `--stage <branch>/<label>`, and the record names the stage;
  - a stage twin of P steps to Q's stage, and the record names Q's stage and branch: rewrite `TestStepToAnotherProposedChangeIsForeign` as this case;
  - a `--snapshot` twin steps to `--stage <branch>/<label>`, and the record names the stage beside `source: snapshot` (SC-004's third reference; the record's shape is T027's);
  - a stage twin with no `--stage` steps to its own next stage (`TestStepWithNoTargetGoesToTheNextStage` holds);
  - no `stage.twin.moved` for a stage-less twin on `stage list` or `twin step --stage` (beside `TestStageListTwinMoved`);
  - a rehearsal's host, with no record or a staged one, still meets `run.in_flight` first;
  - after a `--snapshot` step, `twin step` with no target is refused.
  - *Note (Run 10)*: `stages.Find` reads `given.Branch`, else the record's stage's branch. **No target**: `stepNoTarget` runs after the packages and the state root, before the dry-run branch and `rehearsalHolds`. With neither flag it reads `lab.ReadRecord(paths.TwinJSON)`. A readable record naming no stage gets `noTarget`'s refusal: `step.target.unknown`, at resolve, exit 1, its object the record's bundle, with `stages.NoTargetMessage`. `noTarget` is applied again to the record as inspected, so a record written between the two reads cannot reach `rec.Stage` nil on the stage path. `stepStageless` goes. `Moved` is filed only when the record has a view. Choices for review:
    - **R-08 is applied as written.** Every readable record naming no stage, given no target, is refused `step.target.unknown`. That includes a bundle twin, a record naming no snapshot, a record of 5 or earlier with or without a waypoint, and a diverged stage-less record. Each meets its own refusal once given a target. The operator of such a twin is first told to give a target, then refused for the twin itself. I kept R-08's words, which FR-014 echoes, and changed nothing beyond them. Exempting the twins no target can step is the operator's call.

    Tests (`internal/cli`):
    - `TestStepWithNoTargetNamesNoStage`: a `--branch` and a `--snapshot` twin, and a stage twin after its step to a snapshot (via `recordOnHost`). Each is refused with no target, with `--dry-run` and with `--allow-restart --wait 1m`. Each refusal names the bundle. The service is installed nil, so any dial fails the test. Infrahub's counter and containerlab's calls do not move, and twin.json is unchanged (US3 scenario 1).
    - `TestStepStagelessTwinToAStage`: a `--branch` and a `--snapshot` twin step to `change-1/linked`. The dry run's twin line is the stage-less form, followed by the resolution line and `step snapshot <short>… → change-1/linked (`. No `stage.twin.moved` and no `step.stage.skipped`. The run's input has no from stage. The record names the stage beside its kept source, `intent` or `snapshot`, and is valid against twin.json 10. A stage at the twin's own (branch, at) is `step.target.current` (scenarios 2 and 5; SC-004's third reference).
    - `TestStepToAStageOfAnotherProposedChange` (was `…IsForeign`): a stage twin of pc-1 steps to pc-2's `linked`, on `change-2` (versioned like change-1) and on `change-1` with pc-1 closed. The resolution and step lines are pinned, with no skipped or moved warning. The run's to side and the record name pc-2's stage and branch (scenario 3).
    - `TestStageListStagelessTwinMovesNothing` (`stage_list_test.go`): a branch twin whose at's mark was edited, and a snapshot twin whose proposed change closed. Neither gets `stage.twin.moved`, a marked row or a record (scenario 5).
    - `TestStepWithNoTargetGoesToTheNextStage` and `TestStepBesideARehearsalNamesItBeforeAnyRead` are unchanged and pass. The latter covers a host with no record and one with a staged, diverged record (scenario 4, the rehearsal).
    - `TestStepRefusedBeforeAnyConnection`: the two `noStage` cases are now the no-target refusal. The stage-less cases that test a later refusal pass `--stage change-1/linked` (`aStage`): the bundle twins of 10, 8 and 7, the branch twin naming no snapshot, and the three records of 5. "another branch" is now `stage.unknown` naming the branches with an open proposed change. Rule 2's case takes its new words.

    `internal/server`: `TestStepRefusesARecordThatNamesNoSnapshot` checks `noTarget` in place of `stepStageless`. T033 and T034 are one commit (`dbe0585`): either half alone steps a twin to the wrong proposed change's stage.

**Checkpoint**: `make test`, `make lint`.

---

## Phase 9: User Story 4 — scope and mapping are the twin's for life (Priority: P2)

**Goal**: a target of another scope or mapping is refused before any run, naming both; the
branch moves with the step (FR-015, FR-016; R-06).

**Independent Test**: US4's four scenarios in tier 1.

- [X] T035 [US4] `targetUnheld(rec, scope, mapping, object)` in `internal/server/step.go` (R-06). It returns `step.twin.unsteppable` (rejection, resolve, object the target: the snapshot id or the stage reference) when the target's scope or any field of its mapping differs from the record's provenance. The message, verbatim in shape: `the twin's record names scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 26336e9; snapshot 576933ec… names scope tag:other and mapping infrahub-dcim opsmill/schema-library 26336e9; a twin's scope and mapping are fixed when it is created; fylgja twin destroy and create again to change them`. Where it runs:
  - for a `--snapshot` target, on the envelope after the resolve and before the compile, so a refused target's bundle is never filed;
  - for a `--stage` target, after `stages.Build`, on the compiled bundle's manifest provenance, before the host check.

  Tests in `internal/cli/twin_step_test.go`:
  - another scope refused naming `tag:fylgja` and `tag:other`, before any run, with no bundle filed (US4 scenario 1);
  - another mapping version refused naming both mappings (scenario 2);
  - a stage target under the record's scope passes with no finding (scenario 4);
  - a stage target whose mapping differs is refused like a snapshot's.
  - *Note (Run 10)*: `targetUnheld(rec, scope, mapping, object, name)`: the task's four parameters plus `name`, the target's side name in the message (`snapshot <short>…` by `StepSide.Name()`, or `stage <branch>/<label>`). The object is the full snapshot id or the bare reference. Its message is R-06's, verbatim, each mapping written as reader, model and version. The two call sites:
    - **A `--snapshot` target**: after `resolveSnapshot` and the target line, before `compileAndFile`, on the envelope (`wire.Mapping(env.Mapping)`). A file target is filed by then, so the refusal goes through `compiledRead.refused`, as a refused compile does: the document names the snapshot, and the text prints its stored line. That comment is updated.
    - **A `--stage` target**: after `stages.Build`, on its bundle manifest's provenance, before `stepTo`'s host check. The document carries the resolved stage block, as the other stage refusals do. A manifest that does not parse is `operation.failed` at resolve; nothing builds one.

    Tests:
    - `TestStepTargetKeepsScopeAndMapping` (`internal/cli`), five subtests:
      - a file whose envelope names `tag:other`, and one naming mapping version `0f0f0f0`, each stepped by file, then dry-run, then by the id it was filed under. Each is refused naming both, with the snapshot filed and named on stdout, no bundle filed, no run, no Infrahub request, no containerlab plan, and twin.json unchanged (US4 scenarios 1–2);
      - a stage twin whose record names version `0f0f0f0`, stepped to `change-1/linked` with and without `--dry-run`, refused naming both on `change-1/linked` with the stage block, before containerlab's plan and any run;
      - a stage and a snapshot under the record's scope and mapping, passing with no `step.twin.unsteppable` (scenario 4).
    - `TestTargetUnheldNamesBoth` (`internal/server`): R-06's message verbatim, and each mapping field (reader, model, version) refused alone. Commit `dfbd8e6`.

**Checkpoint**: `make test`, `make lint`; every tier-1 case of quickstart §1 present.

  *Run 10's checkpoint, 2026-10-28 (T033–T035)*:
  - **Commits**: `dbe0585` (T033 and T034, one change), `dfbd8e6` (T035), then this note. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the committed tree:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes in 44.2 s wall with the build cache warm, at a load average of 3.85 before and 3.77 after. **That is 0.8 s under the 45 s budget.** `internal/cli` took 39.5 s, up from 37.6 s at Run 9, and this run's tests add about 2 s. The first uncached run after the build took 53.6 s (load 2.90, then 4.55); Runs 3–9 saw 46–50 s.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
  - **Tier 2**: none run, since no task here names a tier-2 test. The one tagged caller of `Moved` (`internal/stages/stages_contract_test.go`) passes the record's own proposed change, whose result is unchanged. Nothing was written to Infrahub. Read afterwards: `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage` and `CoreChangeThread` each count 0.
  - **The host**: no process started or stopped. The worker (2012205) and the server (2012228) still run a binary that reads `(deleted)`. T048 restarts both.
  - **Quickstart §1**: every tier-1 case it lists is now present (Runs 4–10).
  - **For later tasks**:
    - **T038**: rule 2's new words. `step.target.foreign`'s row and the "stays inside" sentences in `contracts/cli.md`, `docs/architecture.md:837` and `docs/glossary.md:1166` are prose for T038, T040 and T041.
    - **R-08's literal reach** (T034's note) is the operator's to confirm.
    - **The test budget**: with `internal/cli` near 40 s, the next run that adds tier-1 cases may cross 45 s.

---

## Phase 10: User Story 2, part 2 — the server's step to a snapshot, in Infrahub (Priority: P1)

**Goal**: tier 2's proof that the snapshot target files and compiles as a stage step does,
with no second Infrahub request (SC-004, SC-008; R-17).

**Independent Test**: `TestStepTargetFromASnapshot` passes alone against the real
Infrahub.

- [X] T036 [US2] Add `TestStepTargetFromASnapshot` to `internal/server/snapshot_contract_test.go` (build tag `contract`; R-17). It runs on a `fylgja-test-*` branch it seeds through `testsupport`:
  - it takes a snapshot through `intent read --out`'s server path;
  - it builds the step's snapshot target (T031's resolve, T035's check and the compile) from the file and from the id;
  - each files the same snapshot and compiles to the bundle that `stage plan`'s path compiles from the same read;
  - the stamper's and the reader's counters, as the other contract tests count them, show no Infrahub request on the snapshot path.

  No twin boots. The test deletes its branch at the end, as every contract test does. Run it alone: `set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/server -run '^TestStepTargetFromASnapshot$' -v`. Record its time and result in this task's note. No twin while it runs.
  - *Note (Run 11, 2026-10-28)*: **passed alone in 194.98 s** (201.7 s wall with the build), with no twin up and about 20.8 GiB available. The seed took 60 s, and the draft's pipeline concluded after 101 s. The test follows `TestStageTakenTwiceHasOneSnapshot` beside it: `seededBranch` (`fylgja-test-rh-…`), a draft proposed change and one mark, `seeded`. Then:
    - **The bundle stage plan compiles from the same read**: `stage plan` on the branch compiles the mark (snapshot `009ce0b4…`, bundle `696db406…`, at `2026-10-28T16:00:57.507059+00:00`). `intent read --out --stage <branch>/seeded` (`runRead`, its frames recorded) reads the same pinned reference, names the plan's snapshot, and sends a file whose envelope names the branch, that at and `tag:fylgja`. Reading the mark by `--stage` is how this test gets the same read; R-17 names no reference.
    - **The target**: the step's snapshot target is built from the file and then from the id, for a record naming `tag:fylgja` and the reader's mapping (`ctm.ReaderInfrahubDCIM`, `ModelSchemaLibrary`, `ModelVersion`), under a state root of its own. Each names the plan's snapshot and compiles to its bundle, with the branch, the at and the file's `observed_at` verbatim, and no stage. After each, the store holds the file alone, byte for byte, and the bundle store holds the plan's bundle alone.
    - **The counters**: no contract test counted requests before this one. `countedInfrahub` puts a reverse proxy in front of the Infrahub `INFRAHUB_ADDRESS` names and points that variable at it. Every reader and stamper the server builds reads the address when it is built (`intent.FromEnv`, `StageReaderFromEnv`), so the proxy counts their requests together. The plan sent 33 requests and the read 24; each target sent 0. A zero count before the targets fails the test, since it would prove nothing.
    - **The code**: so the test runs the step's own code and not a copy of it, `stepToSnapshot`'s first half became `snapshotTarget(ctx, opts, op, subject, reg, paths, rec, arg, files) (stepTarget, findings.List, error)`. That half is the resolve, the target line, `targetUnheld` and `compileAndFile`. `stepToSnapshot` calls it, then `stepTo`. Behaviour is unchanged: tier 1's step tests pass as they stand.
    - **Afterwards**: the cleanup deleted 1 stage, 1 proposed change and the branch. `Branch` lists `main` and `fylgja-fixture` alone, and `CoreProposedChange`, `FylgjaStage`, `CoreChangeThread` and `CoreUserValidator` each count 0.

**Checkpoint**: the test passes alone.

  *Run 11's checkpoint, 2026-10-28 (T036)*:
  - **Commits**: one commit, T036's test with the `snapshotTarget` split it calls, then this note. No golden moved (`git diff --stat main -- testdata/golden` is empty), so there is no re-baseline commit.
  - **Gates**, on the tree with the change:
    - `make build` is statically linked.
    - `make test` uncached (`GOFLAGS=-count=1`) passes. The first run after the edit took 51.0 s wall (load 2.91, then 3.10), over the 45 s budget. The second took 43.3 s with the build cache warm (load 2.78, then 3.51), `internal/cli` 38.8 s of it. Run 10 saw the same pattern, 53.6 s and then 44.2 s. This run adds no tier-1 test.
    - `make lint` reports 0 issues, and `go vet -tags contract,fixture,e2e ./...` is clean.
  - **Tier 2**: `TestStepTargetFromASnapshot` alone, as above. Infrahub is left as the tier leaves it.
  - **The host**: no process started or stopped. The worker (2012205) and the server (2012228) still run a binary that reads `(deleted)`. T048 restarts both.
  - **For later tasks**: T050's whole tier 2 runs this test, about 3¼ minutes, three times the plan's estimate of about a minute: most of it is the draft's pipeline (101 s) and the seed (60 s).

---

## Phase 11: User Story 6, part 2 — tier 3's script and the contracts' prose (Priority: P3)

**Goal**: `scripts/e2e.sh` proves the criterion live in case 5 and makes no Schedule; the
contracts say what is now true (FR-022, FR-024, FR-026; R-18, R-21).

**Independent Test**: `bash -n` and `shellcheck` clean; each changed `jq` filter checked
offline against recorded outputs; the 019 sections present.

- [ ] T037 [US6] `scripts/e2e.sh` (R-18):
  - **Case 5**, its branch, seed, two changes and verify 5a kept:
    1. `create_twin 5 --scope tag:fylgja` with no `--interval`. Assert no `following` key, `twin show --json`'s `.show.kind=="snapshot"` naming `SID5` and `BID5`, and the text kind line `kind: snapshot ${SID5:0:8}… (branch $FB, read at …)`, kept in `kind-5.txt`.
    2. Hash `twin.json` and the three container ids; note `CREATED5` (UTC, after the create's answer).
    3. `-disable-port n1:ethernet-1/2 -generate`; `await_checksums_moved`; wait until `FROZEN_WAIT_S=330` seconds have passed since the checksums moved. Assert `twin.json` and the containers unchanged, the kind line equal to `kind-5.txt`, and `temporal workflow list --query "StartTime > '$CREATED5'"` empty. The query's exact form and the time's format cannot be checked offline: T048 checks them by hand before T051 and corrects this line if they differ.
    4. `compiled_id 5a`, then `fylgja twin step --snapshot "$OUT/snapshot-5a.json" --json`. Assert `.status=="ok"`, `.step.outcome=="stepped"`, `.step.to.stage==null`, `.step.to.snapshot_id==env.COMPILED_SNAPSHOT` and `.step.to.bundle_id==env.COMPILED_ID`; the record's `.stage==null`, `.snapshot_id` and `.bundle_id` the target's, and `.source=="intent"`. Then `readback 5a "$FB" disable`, and `verify_twin 5a` with today's skipped port and link and `.verify.twin.snapshot_id==env.COMPILED_SNAPSHOT`.
    5. `-add-link`; `await_checksums_moved` on n1 and n3; `compiled_id 5b`; `twin step --snapshot "$COMPILED_SNAPSHOT"`, by id: stepped. Then `readback 5b`, and `twin show` names the new snapshot and `(stepped from snapshot <5a's short>… by run fylgja-step …)`.
    6. `destroy_twin 5`, then the branch deleted.
  - **Cases 7 and 8**: the Schedule assertions go (`has("following") | not` and `schedule_state` absent in case 7); `.show.kind=="pinned"` becomes `"snapshot"`; `twin_version=="9"` becomes `"10"` at each of its four lines.
  - **The rest of the script**: the four `--no-follow` go, with the header's sentences on them; `FOLLOW_INTERVAL_S` goes. `schedule_state` and `FOLLOW_SCHEDULE` stay for the trap's leak check alone, whose comment says it catches a Schedule kept by a host upgraded with a following twin up. The closing timing line names case 5's `frozen wait`, `step 5a` and `step 5b` in place of its rebuilds. The header's duration is about 32–33 minutes.

  Check offline: `bash -n scripts/e2e.sh`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`. Run each new or changed `jq` filter against the recorded outputs under `local/e2e-*.outputs` where one exists, else against a document from a tier-1 test of T031–T032, and record each check in this task's note.

- [ ] T038 [P] [US6] The contracts' prose. Append [contracts/commands.md](contracts/commands.md)'s two sections as `contracts/cli.md`'s "019: following removed" (with the upgrade sentence of R-21 under "Upgrading", verbatim: `Destroy a following twin before upgrading a host of an earlier build: a Schedule fylgja-follow left behind starts a workflow no worker of this build serves, and this build carries no code to clear it`) and `contracts/api.md`'s. Its `twin.destroy` answer loses its following events and "its `start` comes once following has stopped". Each earlier section that states following as current behaviour gains a one-line pointer to the 019 section and no other edit (`/usr/bin/grep -n -i 'follow\|interval\|schedule' contracts/cli.md contracts/api.md`). `contracts/step.schema.json`'s description gains formats.md §5's sentence. `contracts/cli.md`'s Environment table: the worker reads `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` no longer (R-22).

- [ ] T039 [P] [US6] The code comments that say following's change (data-model §11; R-26). Reword, changing no code, no flag and no data: `internal/intent/errors.go` (`ErrBranchNotFound` names no consumer outside the reader; this file's fourth decision), `internal/compiler/manifest.go` (about line 146), `cmd/fylgja-fixture/main.go` (about lines 5 and 356), `internal/testsupport/seed.go` (about lines 470–471), and any other comment `/usr/bin/grep -rn -i 'following\|reconcile check\|follow check\|\.reads' internal cmd --include='*.go'` finds stating following as current (comments citing history stay). Not under `infrahub/`.

**Checkpoint**: `make test`, `make lint`, `shellcheck` clean.

---

## Phase 12: User Story 6, part 3 — the documents (Priority: P3)

**Goal**: every document says what is now true (FR-025, FR-026; R-19, R-21–R-23;
data-model §11).

**Independent Test**: quickstart §6's greps find following only as history; `make
linkcheck` clean.

- [ ] T040 [P] [US6] `docs/architecture.md`, at the lines data-model §11 lists:
  - §1: "A walking twin walks" rewritten for stepping.
  - §2: the operate row.
  - §3.
  - §4.4: the state diagram, the workflows, "Inside the worker", "Following" and the check outcomes removed, the sequence.
  - §4.5: the worker's reads (R-22) and its table.
  - §4.6: create, show, destroy and step, the step's two target kinds, scope and mapping for life.
  - §4.7.
  - §6 and §7.

  Then `/usr/bin/grep -n -i -e follow -e reconcile -e schedule -e interval -e frozen -e pinned docs/architecture.md`. Every hit is made true, or is history (a superseded decision named as such), "reconcile" containerlab's phase, or "pinned" a reference with an `at`.

- [ ] T041 [P] [US6] `docs/glossary.md` (FR-025):
  - **Removed**: Following, Frozen twin, Interval, `reconcile` (workflow), Schedule (Temporal).
  - **Reworded**: Kind (the four kinds); Pinned (a reference with an `at`, never a kind); Rebuild (what following's check did until D-062, and why a record an earlier build's rebuild made names no snapshot); Check (following's check until D-062; "check" now means Infrahub's); Walking twin (walks by stepping).
  - **Touched**: `bundle_id`, Reconcile (its contrast with the workflow), Scope, Snapshot, Step (of a run), Step (of a twin) (its target, a stage or a snapshot), Workflow (four).
  - **The two meanings of "follow"** separated: following a run's events stays; following a branch is gone.

- [ ] T042 [P] [US6] `docs/brief.md`: Scope (about lines 26–30 and 36–38), Pipeline (about line 73) and the CLI (about lines 92–95) say a twin is frozen at its snapshot and walks by stepping; no `--interval` or `--no-follow`.

- [ ] T043 [P] [US6] `docs/development.md` at data-model §11's lines:
  - the environment table (about line 164): the worker reads no `INFRAHUB_*` (R-22);
  - the layout (about lines 362–363 and 387): `internal/stage` serves the server alone, and `internal/provision` holds no following;
  - the tier 1 and tier 2 rows (about lines 583–584): no reconcile check, no `TestFollowingDetection`, seven histories, `TestStepTargetFromASnapshot`;
  - tier 3's cases 1 and 5 (about lines 671 and 687–695), and the leak check (about lines 753–755);
  - conformance (about line 773), "Following is a Schedule" (about lines 916–931) removed, about line 1042, and the naming table (about lines 1061–1062).

  Also `.env.example`: `INFRAHUB_ADDRESS` and `INFRAHUB_API_TOKEN` are read by the server, never the worker. Re-read `SECURITY.md` and change only a sentence that says the worker holds an Infrahub token.

- [ ] T044 [P] [US6] `README.md` (R-23):
  - The intro (about line 10).
  - "A walking twin, start to finish" keeps `fylgja-test-readme`, its seed and its two changes. Create from `--branch`, the kind line naming the snapshot; disable a port and generate; `twin show` unchanged; `intent read --branch fylgja-test-readme --out local/readme-1.json`, then `twin step --snapshot local/readme-1.json`, the node reading the port disabled; the link added and stepped to by id, from the id the read printed.
  - One paragraph under the walk-through says what the kind line's bracket tells: an `at` or a read time, and so whether the snapshot can be taken again.
  - "A stepping twin" (about lines 288, 300 and 356–416) loses "A walking twin keeps up with its branch by rebuilding" and its "never follows" lines.
  - "Pinned and frozen twins" (about lines 684–696) goes.

  Samples keep the shapes of [contracts/commands.md](contracts/commands.md) "The text", with ids this host never printed written `…`.

- [ ] T045 [P] [US6] `docs/ideas.md`'s webhook entry (about lines 182–200): its latency argument is moot; reword it as an orchestrator's trigger for a take and a step (D-062's consequences).

- [ ] T046 [P] [US6] `docs/roadmap.md`, Release 0.3 section: add an "Upgrading a 0.2 host" list with R-21's sentence, which 0.3's release notes copy at the release's close. `.github/workflows/release.yml` is not edited. F-026's "built" mark is T053's.

- [ ] T047 [US6] After T040–T046: `make linkcheck` clean. If any of them touched `docs/c4/workspace.dsl`, run `make diagrams` again and commit the views. Run quickstart §6's grep over `docs/architecture.md` and `docs/glossary.md`, and record each remaining hit and why it stays in this task's note.

**Checkpoint**: `make test`, `make lint`, `make linkcheck`.

---

## Phase 13: User Story 1 and 2, live — the host and the hand step (Priority: P1)

**Goal**: the processes from this tree on the development host, verified, and a step to a
snapshot by hand (quickstart §2–§3).

**Independent Test**: quickstart §2 and §3's expected outcomes, each recorded in its task's
note.

- [ ] T048 [live] [US1] Restart the worker and the server from this tree's `bin/fylgja` (`make build` first), as `CLAUDE.md` prescribes, and verify both:
  - `/proc/<pid>/exe` is not `(deleted)`;
  - the server's environment carries `INFRAHUB_*`, both logins, `FYLGJA_STATE_ROOT`, `FYLGJA_API_TOKEN` and `FYLGJA_DEFAULT_SCOPE`;
  - the worker's carries both logins and `FYLGJA_STATE_ROOT`; it still inherits `INFRAHUB_*` from `local/.env` but reads neither (R-22);
  - the server's report in `local/server.log`, line by line as `CLAUDE.md` gives it;
  - the worker's start-up report names both packages;
  - from inside each Infrahub task worker, `POST /v1/twin/show` answers `200` with the token and `401` without (`specs/015-proposed-change-rehearsal/quickstart.md` §2);
  - `~/.temporalio/bin/temporal schedule list --address localhost:7233` prints its header alone;
  - case 5's query form (T037 step 3): `~/.temporalio/bin/temporal workflow list --address localhost:7233 --query "StartTime > '<UTC time>'" -o json` with a time before a known run lists it and with one after it lists nothing; record the form that answers and the time's format, and correct `scripts/e2e.sh` where it differs, before T051.

  Restart the dev server if it is down. Record pids and lines, never a token.

- [ ] T049 [live] [US2] The hand step, quickstart §3, on a throwaway `fylgja-test-qs-<pid>` branch, never `fylgja-fixture`. No tier 2 runs at the same time; read `free -m` first and restart Infrahub's containers if it reads well below `CLAUDE.md`'s figure. Run each line of §3 and record each output's key line:
  - the kind line before and after the branch edit, which is the same;
  - the dry run's `twin:`, `target:`, step, `reconcile:` and `push:` lines, with no run started;
  - `stepped to snapshot …`, then the kind line naming the new snapshot with `(stepped from snapshot …)`;
  - `twin verify` skipping `n1:ethernet-1/2` and its link;
  - `jq '.stage, .source, .snapshot_id, .twin_version'` reading `null`, `"intent"`, the id and `"10"`;
  - the no-target refusal, then the step to the record's own snapshot reading `unchanged`;
  - the destroy with no following line.

  Afterwards `temporal workflow list` shows no run but the create, the steps and the destroy. Delete the branch and `local/qs-1.json`. Leave no twin up.

**Checkpoint**: the host runs this tree; the step proven by hand.

---

## Phase 14: User Story 1 and 2, live — tier 2 and tier 3 (Priority: P1)

**Goal**: the contract tier whole and the end-to-end tier whole (SC-001,
SC-008).

**Independent Test**: quickstart §4 and §5's expected outcomes.

- [ ] T050 [live] [US2] `make test-contract` whole (quickstart §4), beside the server on the bridge from this tree (T048), with no twin up and none booted while it runs. Expected: `TestFollowingDetection` absent; `TestStepTargetFromASnapshot` passes; `internal/stages` and `internal/checks` pass; afterwards Infrahub is left as `CLAUDE.md`'s Stages paragraph says the tier leaves it, and `Branch` lists `main` and `fylgja-fixture` alone. Record each package's time, the whole, and any re-run with its cause.

- [ ] T051 [live] [US1] Tier 3 (quickstart §5), on a quiet host after T050, from a commit, so the build's VCS stamp matches (memory: the stamp replaces the binary). Steps:
  1. Read `free -m` and restart Infrahub's containers if it reads well below `CLAUDE.md`'s figure.
  2. Start `make test-e2e` detached, its exit status in a file, and wait in foreground calls under ten minutes.
  3. Expected: `E2E-OK`, nine cases. Case 5's log shows the 330 s frozen wait with no run started and the record, the containers and the kind line unchanged, then `stepped to snapshot …` twice (by file, then by id), the readback, and verify 5a's skipped port and link.
  4. Afterwards `temporal schedule list` is empty and the trap's leak check is silent.

  Record its time against the 32–33 minute estimate (R-18), and any attempt lost to the host with its cause.
  - *Note (operator, 2026-10-28)*: the narrowed run (`PLATFORMS=nokia_srlinux make test-e2e`) is dropped for 019: on the same host and binary the whole run covers every case it runs, and 019 changes neither `scripts/e2e.sh`'s case-to-package table nor its skip logic, so it would prove nothing the whole run does not.

**Checkpoint**: tiers 2 and 3 green.

---

## Phase 15: Polish — the records at the close

**Purpose**: every record true, the feature closed (research §4; quickstart §6).

- [ ] T052 [P] `docs/verified-facts.md`, research §4, each with the version and the date:
  - under Temporal, a host of this build makes no Schedule, read by `temporal schedule list` after T051;
  - under the step, a step to a snapshot sends no request to Infrahub, by T036's counters.

- [ ] T053 [P] `docs/roadmap.md`: F-026 marked built (its table row and paragraph, Release 0.3's item 3) with the closing date and its measured effort beside R-25's estimate of 8–11 hours.

- [ ] T054 `CLAUDE.md` (research §4):
  - the worker's counts (four workflows and fifteen activities) and its verification (the environment names carry both logins; `INFRAHUB_*` no longer needed);
  - the M4 line ("Walking": stepping);
  - Formats (`twin.json` `10`);
  - Build and test: tier 2 without `TestFollowingDetection` and with T050's times, tier 3's case 5 and T051's times;
  - State: 019 closed, rewritten as the release's closes are, with **Next** F-014 probes (`016-probes`).

  Check every number against T050's and T051's notes, never estimates.

- [ ] T055 The closing gates and greps. Gates:
  - `make build`, statically linked;
  - `GOFLAGS=-count=1 make test` under 45 s wall (SC-009; note the load average);
  - `make lint`; `go vet -tags contract,fixture,e2e ./...`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`; `make linkcheck`;
  - `git diff --stat main -- testdata/golden` empty, and `go test -count=1 ./internal/compiler` passing with no `-update` (`43d91715…`, `4213b3cf…`, `ecb665f5…`; SC-007);
  - `go test ./internal/provision -run Replay -v` lists seven;
  - `TestFrozenContractCopiesAgree` at T007's count;
  - `TestClientReachesTheCoreThroughTheAPIAlone` passes.

  Greps, each with `-e` patterns, recording every hit and why it stays:
  - SC-002: quickstart §1's grep finds only `scripts/e2e.sh`'s leak check and comments citing history;
  - the eight retired rules (T026, T033) are in no product code;
  - quickstart §6's over `docs/architecture.md` and `docs/glossary.md`;
  - over `infrahub/`, recorded and not edited;
  - the credential greps over the tree, every commit on `main..HEAD` and their messages, counts and file names only, as 018's T063 ran them.

- [ ] T056 [operator] The operator's review of the feature, the commits by hand that the runs left uncommitted, and `make command-log` once the session is closed. Record the review's outcome in this task's note, including the merge and the push, which are the operator's.

**Checkpoint**: every record true; the feature closed.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 first. T002 is the operator's, at `analyze`; its answers may
  change T006, T007, T010, T015, T019, T021 and T027.
- **Foundational (Phase 2)**: after T001. T003, T004, T005, T006 in parallel; T007 before
  any task that edits a schema under `contracts/` (T020, T024, T025, T027, T030).
- **US1 part 1 (Phase 3)**: after T003–T005. T008 → T009 → T010 → T011 → T012; T013 any
  time in the phase; T014 last, after T010–T011 move the imports.
- **US1 part 2 (Phase 4)**: after Phase 3. T015 → T016; T017 beside them.
- **US6 part 1 (Phase 5)**: after Phase 4 (T016 removes `StopFollowing` before T019 removes
  `Follow` from the same input). T018 → T019 → T020.
- **US5 (Phase 6)**: after Phase 5 and T006–T007. T021 and T022 in one run; T023 after
  T022; T024 after T022; T025 after T007; T026 last.
- **US2 (Phase 7)**: after Phase 6 (the show names the snapshot target by T022). T027 →
  T028 → T029 → T030 → T031 → T032.
- **US3 (Phase 8)**: after T029 (`stepTarget`) and T030 (the `--stage`/`--snapshot`
  guard). T033 → T034.
- **US4 (Phase 9)**: after T031 and T034. T035.
- **US2 part 2, tier 2 (Phase 10)**: after Phase 9. T036.
- **US6 part 2 (Phase 11)**: after Phases 7–9. T037 after T031–T032 (its `jq` checks read
  their documents); T038 and T039 beside it.
- **US6 part 3 (Phase 12)**: after Phase 11. T040–T046 together; T047 last.
- **Live (Phases 13–14)**: after Phase 12, from a commit. T048 → T049 → T050 → T051; T050
  never beside a twin, and T051 never beside T050.
- **Polish (Phase 15)**: after Phase 14. T052 needs T036's and T051's results; T053 and
  T054 need T050–T051's times. T052–T053 together; T054; T055 after them; T056 last.

### Within a phase

Pure code is gated in tier 1 before its harness, tier-2 or live proof. A story's test names
the scenario it proves. A defect a test finds is fixed in that phase, in the package that
holds the behaviour, before the checkpoint. A live task's defect gets a tier-1 test that
pins it. A removal leaves no fake, interface method or test helper behind for a later
phase, except the names this file's first decision keeps.

### Parallel opportunities

- Phase 2: T003, T004, T005 and T006 (four packages' files), then T007.
- Phase 4: T017 (`internal/rehearsal`) beside T015–T016.
- Phase 6: T024 and T025 beside T023, once T022 is in.
- Phase 11: T038 and T039 beside T037.
- Phase 12: T040–T046 together.
- Phase 15: T052 and T053 together.

### Parallel example: the foundation

```text
T003  internal/provision/workflow_step.go, workflow_rehearse.go     (the helpers moved)
T004  internal/server/filing.go, provision.go                       (the store's message)
T005  internal/provision/workflow_rehearse_test.go, worker_test.go  (the test helpers)
T006  internal/lab/wire/types.go, names_test.go                     (the side names)
→ then T007, the frozen copies, before any schema moves
```

### Parallel example: the documents

```text
T040  docs/architecture.md
T041  docs/glossary.md
T042  docs/brief.md
T043  docs/development.md, .env.example, SECURITY.md
T044  README.md
T045  docs/ideas.md
T046  docs/roadmap.md
→ T047  make linkcheck, the greps
```

---

## Implementation Strategy

**MVP**: Phases 1–5. After Phase 5, the worker serves four workflows and fifteen
activities, nothing makes a Schedule, destroy is the destroy alone, every rehearsal's
deadline is 30 s shorter, and `--interval` and `--no-follow` are gone: a twin is frozen at
its snapshot, proved in tier 1. Phase 14 proves it live in case 5.

**Incremental delivery**: the moves, the names and the frozen copies → the worker →
destroy and the rehearsal → create and the flags (MVP) → `twin show` and `twin verify` →
the step to a snapshot → to a stage of any proposed change → scope and mapping held → the
tier-2 test → tier 3's script and the contracts → the documents → the host, live → the
records. Every checkpoint leaves the tree green, and no golden moves.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

1. **Run 1** — the baseline: the pure gates and the tree's state read (T001). Only this; stop and report.
2. **Run 2** — [operator] this file's nine decisions settled at analyze (T002). Stop and report.
3. **Run 3** — the helpers moved out of the files to be deleted, StoreMismatchMessage in the server, the side names, and the 018 shapes frozen (T003–T007). Only these; stop and report.
4. **Run 4** — the worker serves four workflows: the tests moved to compiled inputs, the provision workflow's following paths, the reconcile and the control activities deleted, the registration, the two histories, TestFollowingDetection, and the C4 model and import graph redrawn (T008–T014). Only these; stop and report.
5. **Run 5** — destroy stops nothing, a provision and the rehearsal's baseline stop nothing, and every rehearsal deadline 30 s shorter (T015–T017). Only these; stop and report.
6. **Run 6** — --interval and --no-follow gone from the client, the API and the server; the create's and the dry run's following blocks; the findings and API schemas (T018–T020). Only these; stop and report.
7. **Run 7** — twin show's four kinds and kind lines, the client's following reads gone, show.schema.json, twin verify naming the snapshot, and the seven following rules retired (T021–T026). Only these; stop and report.
8. **Run 8** — twin.json 10, the step's eligibility split with stepUnsourced, and stepTo taking a stepTarget with the side names (T027–T029). Only these; stop and report.
9. **Run 9** — twin step --snapshot: the client's flag and the API's argument and file, the server's snapshot path, the dry run and the text (T030–T032). Only these; stop and report.
10. **Run 10** — a stage of any proposed change, the no-target refusal before any connection, and targetUnheld for scope and mapping (T033–T035). Only these; stop and report.
11. **Run 11** — the tier-2 test TestStepTargetFromASnapshot written and run alone (T036). Only this; stop and report.
12. **Run 12** — scripts/e2e.sh's case 5 repurposed and cases 7 and 8 moved, checked offline; the contracts' 019 sections; the code comments (T037–T039). Only these; stop and report.
13. **Run 13** — the documents: architecture, glossary, brief, development.md with .env.example and SECURITY.md, README, ideas, the roadmap's upgrade list, then linkcheck and the greps (T040–T047). Only these; stop and report.
14. **Run 14** — [live] the worker and the server restarted from this tree and verified, and the hand step to a snapshot of quickstart §3 (T048–T049). Stop and report.
15. **Run 15** — [live] the contract tier whole beside the server on the bridge, then tier 3 whole on a quiet host (T050–T051). Stop and report.
16. **Run 16** — the records: verified-facts.md, the roadmap's F-026 built, CLAUDE.md, then the closing gates and greps (T052–T055). Only these; stop and report.
17. **Run 17** — [operator] the operator's review, commits and the command log (T056). Stop and report.

`converge` follows Run 17.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading.

**For `analyze` to settle**, beside T002's list:

- **Run 4's size.** Seven tasks, the largest deletion (about 2,700 lines with their
  tests). It is one run because the tree compiles only once the tests, the workflow, the
  deleted files and the registration agree; T008 alone may be split off if a session finds
  the run too large, since it passes against the workflow before T009.
- **R-25's estimate** (8–11 hours of sessions plus the tiers) stands against seventeen
  runs, two of them live and two the operator's; T053 records the measured effort beside
  it.
- **SC-004's "a stage of its own and of another proposed change" from a `--snapshot`
  twin**: settled at `analyze` (2026-10-28). T034 adds the `--snapshot` twin's case
  unconditionally, since SC-004 names it and the record's shape is T027's.
