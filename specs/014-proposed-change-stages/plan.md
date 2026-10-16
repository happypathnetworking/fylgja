# Implementation Plan: A proposed change's stages

**Branch**: `014-proposed-change-stages` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/014-proposed-change-stages/spec.md`, the brief
([brief.md](brief.md)), [D-045](../../docs/decisions.md#d-045) and Constitution 1.2.1.
Research is in [research.md](research.md) (§1–§4 from the session before `specify`, §5–§7
from this plan), the entities in [data-model.md](data-model.md), the wire forms in
[contracts/](contracts/), the validation in [quickstart.md](quickstart.md).

## Summary

Release 0.2's first spec replaces the waypoint with the **stage**: a moment of a proposed
change. A branch-agnostic `FylgjaStage` relates to its `CoreProposedChange`, carries a
`label` unique within it, an optional `as_of` and an optional `description`, and lands on
`main` as a migration of the candidate already there; `FylgjaWaypoint` is removed from
`main` by a `state: absent` load and from the tree. A proposed change is found by its
source branch among the open ones, and its stages are, in order, the **branch point**
(`main` pinned at `branched_from`), the operator's **marks** by `at`, and the **head** (the
branch pinned one microsecond after its latest stamp). `stage list` and `stage plan`
replace the waypoint commands, `--stage <branch>/<label>` replaces `--waypoint` on `twin
create`, `twin step` and `intent read`, and `twin step` walks a twin through its own
proposed change's stages. Every refusal is made at `resolve`, before any run and before any
branch's intent is read: the kind absent, no open proposed change, no such stage, a
reserved label on a mark, an `at` before the branch point (a rebase named when it did it) or
later than now, and a **stale** stage, whose intent is newer than its last generation. The
twin record moves to `6` and names the stage and its proposed change; the API serves
`stage.list` and `stage.plan`; the findings document carries `stage` blocks under a new
`stages.schema.json`. No golden, fixture identifier, workflow, activity or format beyond
those moves. `internal/waypoint` becomes `internal/stages`; the fixture tool and test
support open draft proposed changes and mark stages on `fylgja-test-*` branches and delete
them in order; tier 3's cases 7 and 8 and the README's walk-through run on stages.

Two things the plan found that the spec did not say, both verified live
([research.md §6](research.md#6-verified-at-plan)) and both decided here:

- **On this install every branch point is refused, not compiled.** `main` holds the
  schema and no `FylgjaContract` object and no device, so a read of `main` at any instant
  is `contract.node.missing` ("branch defines FylgjaContract but holds no instance of
  it"). The plan goes on to the other stages, the step from the branch point is "not
  computed", and the tiers assert exactly that. On an install whose `main` carries the
  network the branch point compiles. The spec's "each compiled" (US1 scenario 1, SC-004)
  holds only there; `analyze` should reword it ([research.md R-04](research.md#r-04)).
- **A regeneration to identical bytes leaves no stamp, so D-045's staleness rule as
  written has a hole**: an intent edit the template does not render (a device's `site`)
  would leave a stage stale with no remedy that clears it, since neither a generate nor a
  run-check moves the checksum's stamp. The proposed change's artifact validator does move
  on a run-check, identical bytes or not. So the generation stamp a device's intent is
  compared with is the later of its artifact's `checksum.updated_at` and the proposed
  change's artifact validator's `completed_at`, both read pinned at the stage's `at`, and
  the comparison is per device. This refines D-045's text; the plan drafted the entry
  ([research.md R-05](research.md#r-05)) and the operator accepted it at `analyze` as
  [D-046](../../docs/decisions.md#d-046), 2026-10-16, before the staleness code is built.

## Technical Context

**Language/Version**: Go 1.26.0 (`go.mod`), one static binary, CGO disabled; YAML for the
schema file and the migration; JSON Schema 2020-12 for `contracts/stages.schema.json` and
the moved `twin.schema.json`; bash for `scripts/e2e.sh`; GraphQL for the five new queries
genqlient generates from (`internal/intent/queries.graphql`); Markdown for the records.

**Primary Dependencies**: Infrahub 1.11.2 (`CoreProposedChange`, its validators, `Branch`,
`FylgjaStage`, pinned reads, `schema/load` migrations with `state: absent`), genqlient
(the typed client, regenerated after `make sdl`), the Temporal Go SDK v1.49 (unchanged
workflows; three recorded step histories whose payloads carry the old record shape),
containerlab 0.79.0 (unchanged), the OpsMill skills `infrahub-managing-schemas` and
`infrahub-managing-objects` (loaded for the kind and the README's object file), cobra for
`stage list`, `stage plan` and `--stage`, `infrahub-sdk[ctl]` 1.23.2's `infrahubctl` for
the migration by hand and the README's guide.

**Storage**: files only, as before (IX): the bundle store, the twin directory (`twin.json`
`6`), Temporal history. Infrahub holds the kind, the proposed changes and the stages, all
the operator's. No database.

**Testing**: tier 1 (`make test`) with faked readers for every resolution rule, the head's
microsecond, the order, the staleness rule, `--stage` parsing, the step's target rule, the
record `6` and the renderings; the contract tests of `findings` against
`contracts/stages.schema.json` and the frozen `twin.schema.json` `5`; the replay tests over
the three step histories, their payloads rewritten to the record's stage block; tier 2
(`make test-contract`) against the real Infrahub: the kind on `main`, a throwaway branch
with a draft proposed change and two marks listed and planned, each refusal (stale, rebase,
reserved, closed, unknown), deletion in order, no `FylgjaWaypoint`; tier 3 cases 7 and 8 on
stages, `E2E-OK`. Tier 1 stays under its budget (no infrastructure); tier 2 gains about
three minutes (two rebases at about 67 s, proposed-change waits of about 40 s); tier 3 gains
about 90 s (two proposed changes).

**Target Platform**: the development host (Ubuntu 26.04.1, the one Infrahub install,
`main` at hash `e7386419…` with the candidate kind) and CI's `ubuntu-26.04` runner, whose
`--part infrahub` loads the final kind on a fresh `main` and never had the waypoint kind.

**Project Type**: a feature of an existing single-binary Go project with a bash test tier
and Markdown records.

**Performance Goals**: `stage list` and `stage plan` answer with Infrahub alone, as the
waypoint commands did; a plan of four stages costs four pinned reads plus one stamps query
and one validator query per stage, and compiles each stage once; `twin create --stage`
and `twin step` add one stamps and one validator read before the run. No new budget.

**Constraints**: Fylgja writes nothing to Infrahub (III; the read-only test widened by
name to the two Infrahub-owned roots it now reads); no `at` composed from a clock of
Fylgja's own (VI 1.2.0: the head is a stamp Infrahub returned plus one microsecond, the
branch point a stamp it returned, a mark's its `as_of` or its own write stamp); every
refusal the server's (XI); no credential in anything written (X; FR-033); the contract,
goldens, fixture identifier, bundle, CTM, PSP and findings versions do not move (FR-024);
one twin at a time (VII); a session never pushes, and the migration of the development
host's `main` is run from this tree and verified before `make sdl`.

**Scale/Scope**: one schema file replaced and one migration document; one package renamed
and reshaped (`internal/waypoint` → `internal/stages`, about 900 lines of product code and
1,700 of tests today); five new GraphQL queries and one removed; the reader in
`internal/intent`; about twenty files in `internal/server`, `internal/cli`,
`internal/findings`, `internal/lab`, `internal/lab/wire`, `internal/provision` and
`internal/verify` that name the waypoint; two contracts replaced (`waypoints.schema.json` →
`stages.schema.json`, `twin.schema.json` `5` → `6`) and five amended (`findings`, `show`,
`step`, `verify`, `api`); the fixture tool (five flags removed, four added) and test support
(the series file replaced by proposed changes and stages); two tier-3 cases; eleven records.
The roadmap sizes it at 4–6 hours of agent time; the live parts (the migration, tier 2, tier
3) are the operator's or a live session's.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution 1.2.1 (`.specify/memory/constitution.md`). Mark each gate PASS, N/A (say
why), or VIOLATION (justify in Complexity Tracking). Cite the principle number.

| # | Gate | Status |
|---|---|---|
| I | Go only; static binary; no second runtime; pure-Go deps; PSPs and schema embedded | **PASS**. Everything new is Go in the one binary; `schema/fylgja-stage.yaml` is embedded where `fylgja-waypoint.yaml` was (`embed.go`, `embed_test.go`); `infrahubctl` is the operator's hand tool for the migration and for writing a stage, as it was for a waypoint, and nothing Fylgja runs shells out to it. |
| II | Platforms are data: no compiler change for a platform; no vendor-homogeneity assumption; budgets/timeouts/readiness from the PSP | **PASS**. No compiler, PSP or platform change. The staleness check names a device's artifact by its package's `config.artifact_name`, from the registry, never a constant; `internal/stages` joins `TestCompilerNamesNoPlatform`'s list where `waypoint` leaves it. |
| III | Queries only the Fylgja generics; never past a generic; least demanded; graduate-don't-gate; `iftype` is kind, `mgmt_only` is the use-flag; unimplemented `iftype` rejects; conformance and completeness checked separately | **PASS** (III as amended to 1.2.1 for D-045, at `analyze`: an Infrahub-owned kind a Fylgja kind relates to may be read, each a named exception in the read-only test). Every operation stays a query (`readonly_test.go`). The stamps read names `FylgjaDevice` and `FylgjaLink` and spreads the artifact fragment `on CoreArtifactTarget`, as the read does. The proposed change, its artifact validator and the branch are read by their Infrahub kinds (`CoreProposedChange`, `CoreArtifactValidator`, `Branch`): they are Infrahub's own units, not the operator's model, and D-045 chose the proposed change as the stage's home; `TestQueryRootsAreFylgjaGenerics` names those two roots and the `Branch` query as the allowed exceptions, and the concrete-kind check (`NetworkDevice` and the rest) stands. The stage kind is Fylgja's, beside the contract (D-028), demanding nothing of anyone's model. Without the kind, only the stage surface refuses, naming the file; the read is untouched. |
| IV | No configuration rendered; bootstrap from the PSP only; production config is an Infrahub artifact | **PASS**. Untouched. The staleness check reads when an artifact was last generated and never generates. |
| V | Compiler pure (test-enforced); bundle deterministic, self-describing, content-addressed, deployable as emitted; `twin compile` shares the test code path | **PASS**. Untouched: `stage plan` and `twin step` compile through `stage.Read`/`stage.Compile` as the waypoint plan did; the stage's name enters neither CTM nor bundle (FR-015); the goldens and the fixture's `47b2c449…` do not move (FR-024, SC-008). |
| VI | Provenance recorded (branch, `at`, schema hash, contract version in the bundle; `observed_at` in the CTM envelope and `twin.json`, never in the bundle); `at` passed verbatim or not at all | **PASS**. Every stage is pinned and every `at` is a stamp Infrahub returned (a mark's `as_of` or its write stamp; `branched_from`) or the first instant after one (the head: the latest stamp plus one microsecond, formatted in the stamp's own layout), passed verbatim on every query of the read and recorded as `provenance.at`; the record and every block say where the `at` came from (`given`, `written`, `branch_point`, `head`); `observed_at` is captured per read as before; a given `as_of` is compared with the server's clock for the future rule alone and that reading is never sent (1.2.0, D-045). |
| VII | One twin at a time: create refused while lab `fylgja` exists; orphan detection at create and worker start; nothing per-twin | **PASS**. Untouched. |
| VIII | Temporal: `provision`/`destroy` with fixed IDs; deterministic workflow code; idempotent activities passing references; heartbeats with PSP budgets; cleanup on a disconnected context; one task queue; host-bound code in `internal/lab` | **PASS**. No workflow, activity or budget changes (FR-024). `wire.WaypointRef` becomes `wire.StageRef` on `RecordInput`, `StepSide` and `TwinRecord`, data the workflows copy and never branch on; the step workflow's refusal that a twin "names no series" becomes "names no stage". The three recorded step histories carry the old block inside their `InspectTwin` results and `RecordStep` inputs, so their payloads are rewritten once to the new shape, as they were scrubbed of the host's name (research R-10); the replays stay tier 1. |
| IX | No database; containerlab + twin directory + bundle store + Temporal history | **PASS**. `twin.json` `6` names the stage and its proposed change (identifier and branch); nothing else holds state. |
| X | Fidelity manifest on every bundle; skips and omissions recorded; stable finding IDs; no credential persisted or logged | **PASS**. Every `waypoint.*` rule becomes a `stage.*` one with a stable identifier, five are added (`stage.artifact.stale`, `stage.label.reserved`, `stage.at.before_branch_point`, `stage.orphaned`, `stage.main.moved`), one is dropped with its cause (`waypoint.time.reversed`, since marks are ordered by `at`; a mark with no stamp at all is `stage.at.unresolved`'s second half), so twelve `stage.*` rules for the waypoint's eight, and one M11 identifier whose noun was the waypoint's is renamed (`step.sequence.skipped` → `step.stage.skipped`); the contract lists every move. A refused stage in a plan says it was not computed, never silently. No token, login or password reaches a finding, record, log line or test output; the proposed change's name is the operator's and is printed. |
| XI | The API is the boundary: a user-facing client reaches the core through the API alone; every refusal is the server's; payloads are the versioned documents; test code excepted, with no second path in a shipped client; held by an import test | **PASS**. `stage.list` and `stage.plan` are operations (`/v1/stage/list`, `/v1/stage/plan`) with handlers in `internal/server`; `twin.create`, `twin.step` and `intent.read` take `stage`; the client's three commands build one request each and link nothing new; every `stage.*` refusal is the server's; the payloads are the findings document with its new blocks. `TestClientReachesTheCoreThroughTheAPIAlone` is unchanged and must still pass. |

**Development Workflow gates**: three tiers (tier 3 never in CI; tier 2 against the real
Infrahub, which the stage reads need) **PASS**; verification just-in-time and recorded
(research §2 before `specify`, §6 at this plan: the empty branch point's finding, the
migration diffs, `state: absent`'s idempotence, the proposed change's pipeline on a bare and
on a seeded branch, the identical-bytes run-check, the validators' pinned read, the stamps
through the generics, the histories' payloads) **PASS**; documents (new glossary terms:
stage reference, mark, branch point, head, orphaned stage, generation stamp; D-045 is
written and the plan drafts D-046 for the operator; `architecture.md` grepped for the old
position at the close; the C4 model redrawn in the same change) **PASS**.

**Blessed layers** (do not flag as complexity): the CTM (D-010), the PSP abstraction
(D-016), the generics contract (D-002).

**Must flag** (rejected designs; return only via a new decision-log entry): a binding
stage (D-011), a database (D-014), a long-running workflow, signal or TTL (D-007),
per-twin resources (D-013), a second task queue before the host move (D-015), a
user-facing client path around the API or a direct mode for tests in a shipped client
(D-040). **None introduced.**

**The OpsMill skills**: `infrahub-managing-schemas` was loaded for the kind (research
R-01: the migration rules, identifiers, cardinality, uniqueness, `order_by`, string caps)
and `infrahub-managing-objects` for the README's object file (a peer with no
human-friendly id is referenced by `id`). Their branch-first rule is not followed on
purpose: Fylgja's schema loads on `main` (D-028), and a stage is a branch-agnostic object
that lands in no branch's diff.

**Post-design re-check (after Phase 1)**: unchanged. The design adds no gate-relevant
structure: one package renamed, one kind migrated, two operations in the API's place for
two removed, one record version. Three places where the design departs from or refines the
spec's text are the plan's to flag and `analyze`'s to settle in the spec: the branch point
on an install whose `main` holds no contract is refused, not compiled (R-04; US1 scenario
1, SC-004); the staleness rule's generation stamp and its per-device reading (R-05; FR-011,
whose "each artifact's checksum stamp" gains the validator's completion); and the one M11
identifier renamed (R-08; FR-014 says the waypoint rules move, and this one is M11's).

## Project Structure

### Documentation (this feature)

```text
specs/014-proposed-change-stages/
├── brief.md                 # the specify brief (committed)
├── spec.md                  # the specification, clarified
├── plan.md                  # this file
├── research.md              # §1–§4 before specify (committed); §5 the plan's decisions R-01…R-14, §6 verified at plan, §7 owed
├── research-probe/fylgja-stage.yaml   # the candidate on main today (committed)
├── migration/fylgja-waypoint-absent.yaml   # NEW: the one-time removal of FylgjaWaypoint, loaded by hand on the development host's main
├── data-model.md            # Phase 1: the kind, the proposed change as read, the stage and its reference, the list, the plan, the record 6, the API, the fixture tool
├── quickstart.md            # Phase 1: the validation scenarios, in the order the work lands
├── contracts/
│   ├── stage-kind.md        # the schema file, its migration on main, the removal, what the README's guide says
│   ├── stage-reference.md   # <branch>/<label>; the resolution's order; every rule with severity, exit, step, object and wording
│   ├── stage-commands.md    # stage list, stage plan, --stage on create/step/read, twin step's target; the text; the API's operations; the findings blocks; twin.json 6
│   ├── stages.schema.json   # the findings blocks' contract, to land as contracts/stages.schema.json
│   └── fixture-tool.md      # the fixture tool's flags and test support's helpers for proposed changes and stages
├── checklists/requirements.md
└── tasks.md                 # Phase 2 (/speckit-tasks), not created here
```

### Source Code (repository root)

```text
schema/
├── fylgja-stage.yaml                 # NEW: the final kind (adds description, the label regex) and the extension; replaces fylgja-waypoint.yaml, deleted
├── infrahub.graphql                  # refetched from main after the migration (make sdl); carries FylgjaStage and fylgja_stages, no FylgjaWaypoint
└── README.md                         # "Stages: marking one" replaces "Waypoints: writing one"; the table's row
embed.go, embed_test.go               # the stage kind embedded and asserted
internal/intent/
├── queries.graphql                   # Waypoints removed; ProposedChanges, OrphanStages, BranchInfo, ArtifactValidations, Stamps added (R-06, R-07)
├── generated.go, genqlient.yaml      # regenerated (make generate)
├── stages.go                         # NEW: StageReader on the default branch's unnamed endpoints (Check, ProposedChanges, Orphans, Branch, Validations); replaces waypoints.go
├── stamps.go                         # NEW: (*Client).Stamps: the branch's intent and artifact stamps at the client's at, per device
└── readonly_test.go                  # the root check names CoreProposedChange, CoreArtifactValidator and Branch as the Infrahub-owned exceptions
internal/stages/                      # RENAMED from internal/waypoint, package stages
├── ref.go                            # Ref{Branch, Label}; ParseRef; CheckBranch; the reserved labels; LabelPattern held equal to the kind's regex
├── resolve.go                        # the proposed change's stages: ends derived, marks by at; Resolve, ResolveFrom; the refusals (R-08)
├── stale.go                          # NEW: the staleness rule and stage.main.moved (R-05)
├── list.go                           # List, ListAll, the twin mark, stage.twin.moved, orphans
├── plan.go                           # Plan, Build, the pairs; unchanged in shape
└── target.go                         # Target over a proposed change's ordered stages; a moved head as a target; step.stage.skipped
internal/findings/
├── finding.go                        # the stage.* rules; step.stage.skipped; waypoint.* removed
├── render.go, verify.go              # StageBlock, StagesBlock, StageRow, StageRecord, StageTowards, PlanBlock, PlanStage, StagesVerified; ShowStage; Subject.Stage; OpStageList, OpStagePlan
└── testdata/contracts/008-waypoints/ # deleted with its readers (R-09)
internal/lab/
├── twin.go                           # TwinVersion "6"; RecordFields.Stage; NewStepRecord's sameStage
├── wire/types.go                     # StageRef{ProposedChange{ID, Branch}, Label, Description, AtSource}; RecordInput.Stage; TwinRecord.Stage; StepSide.Stage
└── testdata/contracts/010-verify/twin.schema.json   # NEW: the frozen 5
internal/provision/
├── types.go, workflow_step.go, workflow_provision.go, client.go   # StageInput; the rewordings; stepTowards names a stage
└── testdata/step-*.history.json      # payloads rewritten: the record's waypoint block becomes its stage block (R-10)
internal/server/
├── stages.go                         # RENAMED from waypoint.go: runStageList, runStagePlan, the text
├── resolve.go                        # stageGuards, resolveStage, withStage
├── create.go, read.go, step.go, show.go, verify.go, schema.go, dryrun.go, handlers.go   # --stage; the stage lines; verified.stages
internal/cli/
├── stages.go                         # RENAMED from waypoint.go: stage list, stage plan
├── create.go, step.go, read.go, root.go   # --stage
internal/verify/report.go             # TwinInfo.Stage, Divergence.Towards
internal/step/render.go, diff.go      # comments and the pair's refs
internal/compiler/purity_test.go, contract_test.go   # the grep's list (stages for waypoint); stages.schema.json among the referenced schemas
internal/testsupport/
├── proposed.go                       # NEW: TestBranchPrefix; OpenProposedChange, AwaitValidators, MarkStage, StagesOf, DeleteStagesOf, DeleteProposedChanges, CloseProposedChange, RunCheck, Rebase, DeleteTestBranch; replaces waypoints.go
└── infrahub.go                       # ArtifactsReadyAt reads the checksum's stamp (research §2.5)
cmd/fylgja-fixture/main.go            # -propose, -stage, -run-check, -close; -delete in order; -waypoint, -at (kept for -stage), -description (kept), -delete-series removed
contracts/
├── stages.schema.json                # NEW; waypoints.schema.json deleted
├── findings.schema.json, show.schema.json, step.schema.json, verify.schema.json, api.schema.json, twin.schema.json   # stage blocks; 6
├── api.md, cli.md                    # the operations; what moved at 014
scripts/e2e.sh                        # cases 7 and 8 on stages; the trap's -delete; the case comments
README.md, docs/architecture.md, docs/c4/workspace.dsl (+ make diagrams), docs/glossary.md, docs/development.md,
docs/verified-facts.md, docs/roadmap.md, docs/ideas.md, docs/brief.md, CLAUDE.md, Makefile (the sdl comment)
```

**Structure Decision**: the package that holds a proposed change's stages is
`internal/stages`, since `internal/stage` is the read-and-compile pipelines and the house
style already has a plural package (`findings`); its component, imports and description
move in `docs/c4/workspace.dsl` and `make diagrams` redraws the server's view. The reader
stays in `internal/intent` beside the branch client, as the waypoint reader did, because it
shares its transport, redaction and refusal wording. No new package otherwise; the
server's handlers, the client's commands and the fixture tool gain and lose files by
rename. The one-time migration document lives under this feature's directory, not under
`schema/`, which the tree's `LoadSchema` loads whole and which, by the spec, holds no
waypoint file.

## Order of the work

1. **The kind on `main`, then the client** (live, first, since genqlient needs the SDL):
   `schema/fylgja-stage.yaml` written from the candidate, `embed.go` and its test;
   `fylgja-fixture -prepare-main` loads the migration (the diff verified: `description`
   added, `label`'s regex), verified on `/api/schema`; `make sdl`, `make generate`;
   `schema/README.md`'s section. `fylgja-waypoint.yaml` stays in the tree and
   `FylgjaWaypoint` on `main` until item 5 has deleted the waypoint code: genqlient
   validates the `Waypoints` query against the SDL, so the kind leaves `main` only after
   the query has left the tree (tasks T030, T042), with the SDL fetched again after it.
   Checkpoint: the SDL and the generated client committed; `go build ./...` green.
2. **The reader and the stamps** (`internal/intent`): the four queries, `StageReader`,
   `(*Client).Stamps`, the read-only test's exceptions, `httptest` tests.
3. **`internal/stages`** with tier 1 over faked readers: the reference, the order with the
   ends derived, the head's microsecond and its formatting, each refusal and warning, the
   staleness rule, the list, the plan, the target rule. The platform grep's list.
4. **The formats**: `findings` rules and blocks, `stages.schema.json` and the moved
   schemas, the frozen `twin.schema.json` `5`, `wire.StageRef`, `twin.json` `6` and its
   tests, the histories' payloads rewritten and the replays green, the step renderer's
   refs. Checkpoint: `make test` and `make lint` green with the server still on the old
   surface where it compiles.
5. **The server, the client and the API**: the handlers and commands, `api.schema.json`,
   the harness tests of every command and refusal, `twin show`, `twin verify` and `schema
   check`'s lines, the dry runs. Checkpoint: `make test`, `make lint`.
6. **The fixture tool and test support**, then tier 2: the proposed-change helpers and
   flags, `TestStageKindLoads`, `TestStagesListAndPlan`, `TestStageRefusals` (stale,
   rebase, reserved, closed, unknown, duplicate), the deletion in order, no
   `FylgjaWaypoint`. Checkpoint: `make test-contract` green, `FylgjaStage { count }` 0.
7. **Tier 3 and the walk-through**: cases 7 and 8 on stages, the trap, the README's
   section; `make test-e2e` whole on the development host, `PLATFORMS=nokia_srlinux` once.
   Live, the operator's or a live session's.
8. **The records at the close**: architecture (grepped for the old position) and the C4
   model, glossary, development.md, verified-facts.md (§6's facts), roadmap, ideas (the
   persistent series closed), `docs/brief.md`, `CLAUDE.md`'s Formats and State, `cli.md`
   and `api.md`; the upstream request drafted for the operator through
   `infrahub-reporting-issues`, never filed.

The decision entry D-046 (research R-05) was the operator's, before item 3's staleness
code: accepted at `analyze` (tasks T011, done).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None. No gate is violated and no rejected design returns.
