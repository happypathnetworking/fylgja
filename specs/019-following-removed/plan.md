# Implementation Plan: Following removed from the core

**Branch**: `019-following-removed` | **Date**: 2026-10-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/019-following-removed/spec.md`, the brief
([brief.md](brief.md)), the roadmap's [Release 0.3](../../docs/roadmap.md#release-03) and
[F-026](../../docs/roadmap.md#f-026), [D-007](../../docs/decisions.md#d-007),
[D-012](../../docs/decisions.md#d-012), [D-013](../../docs/decisions.md#d-013),
[D-014](../../docs/decisions.md#d-014), [D-026](../../docs/decisions.md#d-026),
[D-027](../../docs/decisions.md#d-027), [D-045](../../docs/decisions.md#d-045)–[D-053](../../docs/decisions.md#d-053),
[D-061](../../docs/decisions.md#d-061) and Constitution 2.2.0. Research is in
[research.md](research.md) (§1 verified at this plan on the host and in the tree, §2 its
decisions R-01…R-27, §3 D-062 drafted for the operator, §4 owed at implement); the
entities and where each changes in [data-model.md](data-model.md); the commands and the
formats in [contracts/](contracts/); the validation in [quickstart.md](quickstart.md). No
OpsMill skill was loaded: the feature designs nothing in Infrahub, writes nothing to
`main`, and changes no query, template, check or fixture data (R-26).

## Summary

Release 0.3's third spec takes following out of the core. The `Reconcile` workflow, the
Schedule `fylgja-follow`, the five control activities and `bundles/.reads/` go, so the
worker serves **four workflows and fifteen activities** and reads no source of truth;
`--interval` and `--no-follow` become unknown flags and unknown API arguments; destroy stops
nothing first; the rehearsal's baseline stops nothing, so every deadline is 30 s shorter
(R-01, R-13–R-15, R-22). A twin is frozen at its snapshot, and **`twin step` widens to any
twin whose record names a snapshot**: to `--stage <branch>/<label>` of any proposed change
or to a new `--snapshot <id|file>` of any branch, resolved by create's own resolver with no
request to Infrahub, then stepped by the unchanged run through a small `stepTarget` in place
of a `PlanStage` (R-04, R-07). Scope and mapping are fixed for a twin's life and checked
before any run; the branch moves with the step (R-06). `twin show`'s kinds collapse to
`snapshot`, `from_bundle`, `diverged` and `none`, the kind line naming the snapshot and its
`at` or read time (R-10); `twin verify` names the snapshot beside the bundle (R-11).
`twin.json` moves to **10**, since a stage no longer implies `source: intent` (R-09). Tier
3's case 5 shows the exit criterion live over 330 s, then steps to a snapshot by file and by
id (R-18). One decision entry, D-062, drafted (§3); the constitution is not amended.

Verified at this plan (research §1): the host holds no Schedule, no twin and no open run; of
the nine recorded histories, the seven that remain schedule no removed activity and carry
no follow field, and their records name stages, so they replay unchanged by construction
with no version marker (R-02); the worker's one path to Infrahub is `ReadIntent`; the
version gates are numeric, so `10` reads as later than 8; `fylgja-twin`'s 4,260 s is sized
against the ceiling, not a deadline, so it stays.

Eight things the plan found that the spec did not say, or said otherwise, all **settled on
2026-10-28** and recorded in the spec's Clarifications (research R-27). By the operator:

- **A stage twin of record `8` no longer steps** (R-03), retiring 018's R-06 allowance; the
  edge case is reworded.
- **The upgrade sentence lives in `contracts/cli.md` and the roadmap's Release 0.3 list**
  until 0.3's release notes are written (R-21); FR-026 is reworded.
- **No constitution amendment** (R-20), on D-060's precedent; D-062 says why.
- **D-062 is appended** to `docs/decisions.md` now, with the five *Superseded* status lines
  and its index row, uncommitted.

By the plan, as following from the spec's own words:

- **The snapshot rule is the server's alone** (R-03): inside the run it would refuse the
  three step histories, whose records predate `snapshot_id`. The run's inspect only loses
  its stage-less refusal.
- **`step.target.foreign` is retired** (R-07); FR-004 names it.
- **"Before any connection" for a stage-less twin with no target** is met by reading the
  record before the workflow service is dialed (R-08).
- **`stage.twin.moved` is given only when the target is in the record's own proposed
  change** (R-07); FR-014 says so.
- **`twin.json` moves to 10** (R-09); FR-018 says so.

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled; JSON Schema
2020-12 for the four schemas that move; bash for tier 3; Markdown for the records. No
dependency added or removed (the Temporal SDK's Schedule client simply goes unused).

**Primary Dependencies**: unchanged. Infrahub 1.11.2 read by the server alone; Temporal
Go SDK v1.49 runs four workflows and fifteen activities; containerlab 0.79.0 untouched.

**Storage**: files only (IX): the bundle store without `.reads/`, the snapshot store, the
twin directory (`twin.json` 10), Temporal history. No Schedule.

**Testing**: tier 1 (`make test`, under 45 s; quickstart §1): the registration counts, the
seven replays, the flags and arguments refused, the step to a snapshot and to a stage of
another proposed change from each kind of twin and every refusal, the kind lines, the
record's rules, the frozen copies, the deadlines. Tier 2 (`make test-contract`; §4):
`TestFollowingDetection` gone, `TestStepTargetFromASnapshot` added. Tier 3 (`make
test-e2e`; §5): nine cases, case 5 repurposed.

**Target Platform**: the development host (Ubuntu 26.04.1) and CI's runner for tiers 1–2.

**Project Type**: a feature of the existing single-binary Go project: mostly removal, one
widened command, four records.

**Performance Goals**: tier 1 under 45 s (it loses about 2,000 lines of following tests);
tier 2 shorter by `TestFollowingDetection` and longer by one test of about a minute; tier 3
about 32–33 minutes, about 3 more than today (R-18). A step to a snapshot is faster than a
stage step by the stage's resolution and read.

**Constraints**: bundle `5`, CTM `2`, snapshot `1`, PSP `0.7`, the three goldens and the live
fixture's `f764e1fa…` unchanged (FR-021); the API and findings at `1`, the removals pre-1.0;
no new workflow, activity, marker or queue (VIII), the seven histories replaying; every
refusal the server's (XI); nothing on Infrahub's `main`, no fixture, query, template or
check; no twin while tier 2 runs; a session never pushes.

**Scale/Scope**: about 3,500 lines removed and 900 added (R-25): `internal/provision` (the
reconcile, the control activities, the follow fields and options, the Schedule half of
`client.go`), `internal/server` (create, dry run, destroy, follow's reports, show, the step's
snapshot path), `internal/cli` (the flags; `--snapshot` on step), `internal/findings`,
`internal/stages` (`Target`, `Moved`), `internal/lab` (`twin.json` 10, side names),
`internal/rehearsal` (the deadline); four schemas and seven frozen copies; `scripts/e2e.sh`;
about fifteen records. Re-estimated at **8–11 hours** of sessions plus the tiers (R-25).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 2.2.0 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. Code leaves the one binary; nothing is added or embedded. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness and the manufacturer and platform pairs from the PSP | **PASS**. No package, compiler or budget moves; the step's rules still read each node's package. The rehearsal's `FollowBudget` was a mechanism constant, not a platform's, and goes. |
| III | The CTM is the contract; the reader names its model version; approximations and omissions in the envelope's fidelity list, copied by the compiler; nothing read the mapping does not name; the read-only test's list; wiring derived from what was mapped; conformance and completeness checked separately | **PASS**. The reader is untouched and now called by the server alone; the read-only test's kind list does not move. A step to a snapshot reads nothing. The mapping a twin was read by is held fixed for its life (R-06). |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. The step pushes the snapshot's artifacts as Infrahub rendered them. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. The compiler and goldens are untouched; a snapshot target compiles on `stage.Compile` through create's `compileAndFile`; `stage_parity_test.go` is held to that path now that the `Compile` activity is gone (R-16). |
| VI | Provenance recorded (branch, `at`, schema hash, scope, mapping and model version in the bundle; `observed_at` in the CTM envelope, the snapshot's outer part and `twin.json`, never in the bundle nor in the bytes a snapshot's id hashes); `at` passed verbatim or not at all; where the source cannot replay time, the snapshot's id addresses intent | **PASS**. A step to a snapshot records the envelope's branch and `at` verbatim and the stored take's `observed_at`; a stage step is unchanged. The kind line says whether an `at` exists, so whether the intent can be read again. D-012 is superseded only in its following; the reference `(branch, at?)` and its rules stand. |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. Unchanged; the one per-host Schedule goes. |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS**. A workflow and five activities leave by D-062, as VIII says one leaves; no workflow, activity, marker or queue is added; the step's input gains no field; the seven histories replay (R-02); the run's inspect only relaxes (R-03). |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. Temporal holds run history alone, which is what IX says; `.reads/` goes; `twin.json` 10 moves one rule. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. Eight identifiers retire and none is reused; four are reworded, each keeping its severity, exit and step; the worker holds no Infrahub token. |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `--snapshot` on `twin step` is an argument and a file of `twin.step`; every guard and refusal, the no-target one included, is the server's; the client's own refusals are cobra's unknown flags and an unreadable file, as on create; `TestClientReachesTheCoreThroughTheAPIAlone` unchanged. |

**Development Workflow gates**: three tiers (tier 2 against the real Infrahub; tier 3 never
in CI) **PASS**; verification just-in-time and recorded (research §1: the host, the
histories, the tree; §4 what implement owes) **PASS**; documents (the glossary's five
removals and rewordings, D-062 drafted, the architecture grepped at the close, the C4 model
redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the mapping, one per source, documented (D-057).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None flagged.** The feature removes a timer and adds none.

**Post-design re-check (after Phase 1)**: unchanged. The design removes one workflow, five
activities, a Schedule and two flags, widens one command by one argument and one target
kind, and moves one record version; it violates no gate. The Governance question of R-20 is
settled (no amendment), and D-062 is appended.

## Project Structure

### Documentation (this feature)

```text
specs/019-following-removed/
├── brief.md            # the specify brief (to be committed by the operator)
├── spec.md             # the specification, clarified 2026-10-28
├── plan.md             # this file
├── research.md         # §1 verified (host, histories, tree), §2 R-01…R-27, §3 D-062 drafted, §4 owed
├── data-model.md       # the twin, the step's target and eligibility, names, twin.json 10, workflows, show, findings, API, deadline, documents
├── quickstart.md       # §0 the operator's, §1 tier 1, §2 the host, §3 by hand, §4 tier 2, §5 tier 3, §6 records
├── contracts/
│   ├── commands.md     # cli.md's and api.md's "019: following removed" sections
│   └── formats.md      # twin.json 10, findings, show, api, step, the frozen copies
├── checklists/requirements.md
└── tasks.md            # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
internal/provision/
├── workflow_reconcile.go, activities.go           # DELETED (after R-01's moves)
├── workflow_reconcile_test.go, activities_test.go # DELETED (wantRules, repoPath moved)
├── testdata/cancel-during-follow.history.json, cancel-during-stop-following.history.json   # DELETED
├── workflow_provision.go     # no read-and-compile branch, no stop or start of following
├── workflow_step.go          # Ineligible without Stage == nil and origin(); withoutPresence moved in; side names
├── workflow_rehearse.go      # alreadyStarted, childStartRefusal moved in; no StopFollowing
├── types.go, options.go      # the follow types, constants and options removed; DeadlineMechanism without Follow
├── client.go                 # the Schedule half removed; Follow, InFlight (operator runs) kept; DestroyDocument(subject, res)
├── worker.go, doc.go         # four workflows, fifteen activities; NewWorker(c, acts)
└── *_test.go                 # compiled inputs; counts 4/15; replay cases 7
internal/lab/
├── twin.go                   # TwinVersion "10"; NewRecord's stage rule
├── wire/types.go             # StepSide.Name, TwinRecord.Position; ActReadIntent, ActCompile removed
└── testdata/contracts/018-snapshots/twin.schema.json   # NEW: frozen 9
internal/stages/target.go, list.go   # Target across proposed changes, step.target.foreign gone; Moved only within one
internal/rehearsal/deadline.go       # Mechanism without Follow
internal/findings/finding.go, render.go, verify.go   # eight rules and a step retired; follow blocks gone; show kinds; verify twin snapshot_id
internal/findings, internal/cli, internal/server: testdata/contracts/018-snapshots/{findings,show}.schema.json   # NEW: frozen
internal/server/
├── step.go                   # stepTarget; --snapshot path; stepUnsourced; targetUnheld; no-target refusal; the twin line
├── snapshot.go               # snapshotFiles by operation; snapshotGuards without the follow guard
├── create.go, dryrun.go, resolve.go   # no interval, no follow, no follow: line
├── destroy.go, follow.go     # no stop; provisionReport without following
├── show.go                   # four kinds; no following reads; kind lines
├── verify.go                 # the snapshot in the twin line and block
├── filing.go                 # StoreMismatchMessage moved in
├── handlers.go               # twin.create without interval, no_follow; twin.step snapshot and files
└── snapshot_contract_test.go # TestStepTargetFromASnapshot (tier 2)
internal/stage/following_contract_test.go   # DELETED (tier 2)
internal/cli/create.go, step.go, show.go, destroy.go   # flags out; --snapshot on step; help texts
cmd/fylgja/worker.go          # no ControlActivities
contracts/twin.schema.json, findings.schema.json, show.schema.json, api.schema.json, step.schema.json (description), cli.md, api.md
scripts/e2e.sh                # case 5 repurposed; --no-follow gone; kinds and twin_version 10 in 7 and 8; the trap's leak check kept
docs/architecture.md, brief.md, glossary.md, development.md, ideas.md, roadmap.md, verified-facts.md,
docs/decisions.md (the operator's D-062), docs/c4/workspace.dsl (+ make diagrams), README.md, CLAUDE.md
```

**Structure Decision**: removal in place, and the step's two target kinds meet in one
struct in the server, `stepTarget`, so the run, its input, the record and every document
stay the stage step's code. The snapshot's resolution is create's own function, so a
`--snapshot` refused on a step is refused in the words a create uses. The eligibility rule
that a twin must name a snapshot lives in the server alone, beside the version gates,
because the run's inspect must keep accepting what its recorded histories accepted. The
component changes are drawn in `docs/c4/workspace.dsl`: the worker loses its `stage`
component and its two relationships to Infrahub, Temporal its Schedule (R-24).

## Order of the work

0. **The operator's**: the roadmap's edits, D-062 (appended 2026-10-28) and this directory
   committed. R-27 is settled.
1. **Moves first** (tier 1 green after each): `withoutPresence`, `alreadyStarted`,
   `childStartRefusal`, `StoreMismatchMessage`, `wantRules`, `repoPath` to their new homes,
   unchanged.
2. **Following leaves the core**: the provision workflow's three paths, the reconcile, the
   control activities, the worker's registration, the follow types and options, the Schedule
   half of the client, destroy's stops, the rehearsal's stop and deadline term; the tests
   moved to compiled inputs; the two histories. Checkpoint: `make test`, counts 4/15, seven
   replays.
3. **The surface**: the flags and arguments, the findings retired, the dry run, `twin show`'s
   kinds, `twin verify`'s snapshot, the schemas and the frozen copies. Checkpoint: `make
   test`, `make lint`.
4. **The step widened**: side names, `twin.json` 10 and the record rule, `stepTarget`,
   `--snapshot` on the client and the API, `stepUnsourced`, `targetUnheld`, the no-target
   refusal, `Target` and `Moved` across proposed changes. Checkpoint: `make test` with the
   cases of quickstart §1.
5. **Tier 3's script and the documents**: `scripts/e2e.sh`; the contracts' prose; the
   architecture, the brief, the glossary, the development notes, the README, the ideas
   file, the C4 model; `make diagrams`, `make linkcheck`.
6. **The host, live** (quickstart §2–§3): rebuild, restart and verify the worker and the
   server; the hand step. The session's.
7. **Tier 2** (§4), then **tier 3** whole and narrowed (§5). The session's.
8. **The records at the close** (research §4): `docs/verified-facts.md`, the roadmap (F-026
   built), `CLAUDE.md`.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None.
