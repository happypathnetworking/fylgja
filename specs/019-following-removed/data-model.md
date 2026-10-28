# Data model: Following removed from the core

**Feature**: `019-following-removed` · **Plan**: [plan.md](plan.md) · **Research**:
[research.md](research.md)

What each entity becomes, and where in the tree it changes. Line numbers are the tree's at
`c8d46c7`. No entity is added; one record version moves (`twin.json` `10`), one document
loses blocks (findings `1`, show), one operation gains an argument (`twin.step`), and the
step gains a target kind.

## 1. The twin

A running topology, built from a snapshot (`--branch`, `--stage`, `--snapshot`) or from a
bundle directory (`twin provision`). **Frozen at its snapshot**: no workflow, timer or
Schedule changes it; only `twin step` and `twin destroy` do (FR-002).

| Fact | Fixed for life | Moved by a stepped or unchanged step |
|---|---|---|
| `source` (how it was created: `intent`, `snapshot`, `bundle`) | yes | no |
| `provenance.scope`, `provenance.mapping` | yes (R-06) | no: a target naming others is refused |
| `run` (the create's run) | yes | no |
| `provenance.branch`, `.at`, `.schema_hash`, `snapshot_id`, `bundle_id`, `observed_at` | no | yes: the target's |
| `stage` | no | the target's, or `null` for a snapshot target |
| `rehearsal` | yes | no |

After a diverged step the top level stays the previous record's, as today (FR-016).

## 2. The step's target (`internal/server/step.go`)

```text
stepTarget {
  name       string           // R-05: "<branch>/<label>" or "snapshot <short>"
  stage      *wire.StageRef   // nil for a snapshot target
  snapshotID string           // always set: a stage's take, or the snapshot given
  bundle     step.Bundle      // compiled and filed
  at, branch string           // the stage's resolution, or the envelope's, verbatim
  observedAt string           // the stage's read's, or the stored snapshot's
}
```

Built by one of two paths, then handed to `stepTo` (today's `stepTo(…, built
stages.PlanStage, …)` takes it instead):

| | `--stage <ref>` (or none, for a stage twin) | `--snapshot <id\|file>` |
|---|---|---|
| Proposed change read | `stages.Find` by the given ref's branch, else the record's stage's (R-07) | none |
| Target chosen | `stages.Target(ch, view, recordBranch, recordAt, given)` | the snapshot |
| Built | `stages.Build` (read, take, compile, file) | `resolveSnapshot`, then `compileAndFile` |
| Scope and mapping check (R-06) | after `Build`, on the bundle manifest's provenance | after resolve, on the envelope, before the compile |
| Warnings | `step.stage.skipped` and `stage.twin.moved` when the record names a stage of the same proposed change | none |
| Requests to Infrahub | as today | **none** |

The to side the run receives: `wire.StepSide{Stage, SnapshotID, BundleID, At, Branch}` from
the target; the from side: the record's, as today.

## 3. The step's eligibility (`internal/provision/workflow_step.go`, `internal/server/step.go`)

In order, each refusal ending the command before any run:

1. **Guards at start** (no connection): `--stage` beside `--snapshot` →
   `snapshot.flags.conflict`; `--snapshot=` empty; the files' shape; `--wait`'s.
2. **No target** (no connection; a file read, R-08): neither flag, and a readable record
   naming no stage → `step.target.unknown`. *Amended 2026-10-28 (R-08, T058):* that record
   is first held to the refusals it alone decides, in 4–6's order (`Ineligible`'s diverged
   and waypoint cases, `stepScopeUnknown`, `stepUnsourced`), each given in its own words.
3. `rehearsalHolds` → `run.in_flight` (dials the workflow service, not in a dry run).
4. `provision.Ineligible` (also the run's inspect): no twin, orphan or unreadable record,
   diverged, a record of 5 or earlier naming a waypoint. **Its `Stage == nil` case and
   `origin()` go** (R-03); its no-twin messages say a twin built from a snapshot steps.
5. `stepScopeUnknown`: a record of 7 or earlier, or a scope or mapping 8 cannot hold
   (unchanged).
6. **`stepUnsourced`** (new, server only): `source: bundle`, a record of 8, or a 9/10 naming
   no snapshot → `step.twin.unsteppable` (R-03's three messages).
7. The target's resolution (§2), with `targetUnheld` (R-06).
8. `step.bundle.missing`, the host check without presence, containerlab's plan, the rules
   (unchanged).

The run's second lock at inspect stays `Ineligible` (as relaxed) and `notPlannedFrom`
(bundle and stage equal; its message names each side by `Position()`/`Name()`).

## 4. Names (`internal/lab/wire/types.go`, `internal/step`)

- `func (s StepSide) Name() string`: `stage <branch>/<label>` | `snapshot <8>…` | `bundle
  <8>…`.
- `func (r *TwinRecord) Position() string`: the same for the record's top level;
  `SupersededWaypoint()` for a record of 5 or earlier naming a waypoint (replacing
  `SideStage`'s callers: `divergedTwin`, `show.go`'s diverged kind).
- `step.Between(from, to string, s)` unchanged; callers pass the stage reference without
  its word, or `snapshot <8>…`.
- `m11Closing`, `stepClosing`, `divergedTwin`, `stepTowards`, `notPlannedFrom` and the
  diverged kind use `Name()`/`Position()`.

## 5. The record: `twin.json` 10 (`internal/lab`, `contracts/twin.schema.json`)

- `lab.TwinVersion = "10"`; `$id` `…/contracts/twin/v10`; `twin_version` const `"10"`.
- The schema's `allOf` entry `if stage is object then source const intent and
  provenance.required at` becomes `if stage is object then provenance.required at`.
- `NewRecord` drops its refusal of a stage beside `source: snapshot`.
- `NewStepRecord` unchanged in code: it keeps `prev.Source`, moves `stage` to `f.To.Stage`
  (nil for a snapshot target) and `snapshot_id` to `f.To.SnapshotID`. Its tests gain a
  `--snapshot` twin stepped to a stage and a stage twin stepped to a snapshot, each written,
  read back and validated against the 10 schema.
- Descriptions: `source: intent` loses "or a check's rebuild did"; `snapshot_id`'s null
  case names "a twin `twin provision` built, one an earlier build's rebuild made, or a
  record of 8 or earlier"; the 019 paragraph says what moved.
- **Frozen**: the 9 schema as `internal/lab/testdata/contracts/018-snapshots/twin.schema.json`.
- Readers unchanged: `scopeRecorded` (≥ 8) and `snapshotRecorded` (≥ 9) are numeric.

## 6. The workflows (`internal/provision`)

| | Before | After |
|---|---|---|
| Workflows | Provision, Destroy, Reconcile, Step, Rehearse | Provision, Destroy, Step, Rehearse |
| Activities | 5 control + 15 lab | 15 lab |
| `ProvisionInput` | `BundleID` or a read; `Follow`, `StopFollowing` | `BundleID` required; no follow fields |
| `ProvisionResult` | `Following`, `FollowingStopped` | neither |
| `DestroyRun` | `FollowingStopped` | none |
| Rehearse's baseline | `StopFollowing = true` | nothing to stop |
| `NewWorker(c, acts, control)` | | `NewWorker(c, acts)` |

Moved before the deletion (R-01): `withoutPresence` → `workflow_step.go`; `alreadyStarted`,
`childStartRefusal` → `workflow_rehearse.go`; `StoreMismatchMessage` →
`internal/server/filing.go`. In tests: `wantRules` → `workflow_rehearse_test.go`;
`repoPath` → `worker_test.go`.

Deleted files: `workflow_reconcile.go`, `workflow_reconcile_test.go`, `activities.go`,
`activities_test.go`, `testdata/cancel-during-follow.history.json`,
`testdata/cancel-during-stop-following.history.json`. In `client.go`: the Schedule code research §1.3
names and R-14 lists; `Follow`, `childEvents`, `Event` and `InFlight` (operator runs
alone) stay. `doc.go` and `worker.go`'s comments say four workflows.

## 7. `twin show` (`internal/server/show.go`, `internal/findings/render.go`, `contracts/show.schema.json`)

- `ShowKind*`: `none`, `snapshot` (new), `from_bundle`, `diverged`; `pinned`, `frozen`,
  `following` go.
- `ShowBlock` loses `Following` and `LastCheck`; `ShowFollowing`, `ShowCheck` go;
  `$defs/check` goes from the schema.
- `serviceReads` keeps `inFlight` alone; `svc.Following` and `svc.LastCheck` leave the
  `Service` interface.
- The kind lines of research R-10; `in flight: unknown (workflow service unreachable at
  <addr>)`; `stepping towards <Name()>`.

## 8. The findings document (`findings` `1`, `internal/findings`, `contracts/findings.schema.json`)

| Retired | Kind |
|---|---|
| `follow.interval.invalid`, `follow.flags.conflict`, `follow.start.failed`, `follow.stop.failed`, `follow.stopped`, `check.skipped`, `rebuild.failed`, `step.target.foreign` | rules |
| `follow` | step |
| `following` (`FollowingBlock`, `FollowingStarted`/`NotStarted`) | block on create, provision, destroy |
| `dry_run.follow` (`DryRunFollow`, `FollowReason*`) | block on every dry run |

Reworded: `stage.flags.conflict` (`--branch` or `--at` beside `--stage`),
`step.twin.unsteppable` (R-03, R-06), `step.target.unknown` (R-08's case),
`snapshot.flags.conflict` (`--stage` beside `--snapshot` on `twin step`),
`show.service.unreachable`. The verify block's `twin` gains `snapshot_id` (R-11). Frozen:
the 018 `findings.schema.json` and `show.schema.json` under `018-snapshots/` in `cli`,
`findings` and `server`, where a test validates a document of the 018 shape.

## 9. The client and the API (`internal/cli`, `internal/server/handlers.go`, `contracts/api.schema.json`)

| Operation | Arguments before | After |
|---|---|---|
| `twin.create` | `branch, at, stage, interval, no_follow, dry_run, scope, snapshot` | `branch, at, stage, dry_run, scope, snapshot` |
| `twin.step` | `stage, allow_restart, dry_run, wait`; no files | `stage, snapshot, allow_restart, dry_run, wait`; one file beside a `snapshot` path |

API version `1`. `cli/create.go` loses `--interval`, `--no-follow`, `defaultInterval`,
`minInterval`; `cli/step.go` gains `--snapshot`; help texts of `create`, `show`, `destroy`
and `step` lose following.

## 10. The rehearsal's deadline (`internal/rehearsal/deadline.go`)

`Mechanism` loses `Follow`; `baseline = CheckHost + Stage + deploy + (readiness +
ReadinessMargin) + (push + PushMargin) + Record + (Wait + VerifyMargin)`. Every deadline
−30 s (research R-15).

## 11. The documents

| Document | What moves |
|---|---|
| `docs/decisions.md` | D-062 (the operator's); Status lines of D-007, D-012, D-014, D-026, D-027; the index |
| `docs/brief.md` | Scope (L26–30, L36–38), Pipeline (L73), CLI (L92–95) |
| `docs/architecture.md` | §1 "A walking twin walks" → stepping (L40–45); §2 operate row (L123); §3 (L159, L162–167); §4.4 state diagram (L558–563), workflows (L583–600), "Inside the worker" (L624–632), L713–714, "Following" and the check outcomes (L716–747), L770, the sequence (L793, L810); §4.5 the worker's reads (L1044–1052), table (L1066, L1069, L1084), L1178, L1187–1196; §4.6 create, show, destroy, step (L1241–1270, L1362, L1415–1452); §4.7 (L1596); §6 (L1665–1672, L1733–1739); §7 (L1809–1811) |
| `docs/glossary.md` | removed: Following, Frozen twin, Interval, `reconcile` (workflow), Schedule (Temporal); reworded (FR-025): Kind (the four kinds), Pinned (a reference with an `at`, never a kind), Rebuild (what following's check did until D-062, and why a record an earlier build's rebuild made names no snapshot), Check (following's check until D-062; "check" now means Infrahub's), Walking twin (walks by stepping); touched: `bundle_id`, Reconcile (its contrast with the workflow), Scope, Snapshot, Step (of a run), Step (of a twin) (its target, a stage or a snapshot), Workflow (four); added: none |
| `docs/development.md` | env table (L164), layout (L362–363, L387), tier 1 and 2 (L583–584), case 1 and 5 (L671, L687–695), leak (L753–755), conformance (L773), "Following is a Schedule" (L916–931), L1042, naming table (L1061–1062) |
| `README.md` | intro (L10), the walk-through (L92–283, research R-23), "A stepping twin" (L288, L300, L356–416), "Pinned and frozen twins" (L684–696) removed |
| `docs/ideas.md` | the webhook entry (L182–200): its latency argument is moot; reworded as an orchestrator's trigger for a take and step |
| `contracts/cli.md`, `contracts/api.md` | "019: following removed" sections ([contracts/commands.md](contracts/commands.md)); earlier sections untouched but for a pointer where they state following as current |
| `contracts/*.schema.json` | [contracts/formats.md](contracts/formats.md) |
| `docs/c4/workspace.dsl` | research R-24, then `make diagrams` |
| `docs/verified-facts.md` | research §4 |
| `docs/roadmap.md` | F-026 built at the close; Release 0.3's upgrade list (R-21) |
| `CLAUDE.md` | the worker's counts and environment check, the M4 line, Formats, State |
| code comments | `internal/stage/stage.go`, `internal/intent/errors.go`, `internal/compiler/manifest.go:146`, `cmd/fylgja-fixture/main.go:5, :356`, `internal/testsupport/seed.go:470–471` |
