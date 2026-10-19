# Tasks: A proposed change rehearsed on a twin

**Input**: Design documents from `/specs/015-proposed-change-rehearsal/`: [plan.md](plan.md),
[spec.md](spec.md), [research.md](research.md) (§1 verified at plan, §2 decisions
R-01–R-22, §3 the four decision entries drafted, §4 owed at implement),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md);
constitution 1.3.0; [D-040](../../docs/decisions.md#d-040)–[D-048](../../docs/decisions.md#d-048).

**Tests**: requested. FR-028 names tier 1's cases, FR-029 tier 2's and FR-030 tier 3's;
quickstart §1 names the tests that must exist. Each is a task below. Every format test
validates against the contract file under `contracts/`. The goldens and the fixture's
`47b2c449…` do not move, and neither does any format version but `twin.json`'s (FR-031,
SC-011).

**Organization**: the work goes bottom-up, in the plan's order ("Order of the work"),
because every story stands on the same new parts. The formats and the pure package come
first (Phase 2), then the fifth workflow (Phase 3). Both are foundational: the hand
command (US1), the live check (US2) and the reclaim (US4) all run through the same handler
and workflow. US1's handler, client and harness tests follow (Phase 4). Then the listener
and the host (US4, Phase 5), which the checks need before they can reach Fylgja. Then the
test tooling and the rehearsal by hand (Phase 6). Then the checks, US3's first and US2's
after it (Phases 7–8). Last come tier 3 and the walk-through (Phase 9), and the records
(Phase 10). The loop runs the pure gates after every implement run, so every run must
leave the tree green. Story labels mark which story each task builds or proves.

**Orderings this file decides, against the plan's or the spec's text:**

- **US3 before US2, against the spec's priorities.** `fylgja-step` (P2) is built before
  `fylgja-twin` (P1). The shared glue (`fylgja_api.py`), the query and the registration
  land with the first check, and the spec calls US3 "the check the live one builds on".
  The two checks are proved inside Infrahub by one tier-2 test, run once at the end of
  Phase 8 (T050).
- **The reclaim is built in US1's handler, and proved under US4.** The handler's order
  puts the host at step 5 (contracts/rehearse-command.md). T024 builds it and T034 proves
  US4's scenarios 4 and 5 through the harness.
- **The C4 model is redrawn in four runs** (T017, T022, T030, T049), each in the run that
  adds its component, import or container. The rule ("a changed package, import or
  component is redrawn in the same change") holds per commit.
- **The deadline's mechanism constants are passed in, not imported.** `internal/rehearsal`
  imports `findings`, `lab/wire` and `step` alone (R-11), while the constants live in
  `internal/provision/options.go` and `internal/verify/wait.go`. So `rehearsal.Deadline`
  takes a `Mechanism` value, and `provision.DeadlineMechanism()` fills it from the
  constants (T011, T018). A test pins that the two agree.

**Tags**: `[operator]` marks a task that needs the operator: a decision entry, a Compose
change to Infrahub's task workers, a push to `origin`, a write to `main`'s registration, a
look at Infrahub's UI, or the review. `[live]` marks a task that needs the development
host's server, worker or twins: the server on the bridge, the hand scenarios, the checks
inside Infrahub against the operator's server, and tier 3. Unattended, the loop stops at
both. Commits are by hand, conventional, with a body saying why, and end with the model's
`Co-Authored-By` trailer. A session never pushes.

## Format: `[ID] [tag?] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5, from spec.md

---

## Phase 1: Setup (the baseline and the decisions)

**Purpose**: confirm the tree's gates pass on this branch before anything changes, so any
later failure is this feature's own. Then the four decision entries, each the operator's,
each before the code it admits (plan, "Order of the work").

- [X] T001 Run the pure gates from the repository root and confirm each passes: `make build`; `file bin/fylgja` reports a statically linked executable; `make test` (note the wall time against the 45 s budget); `make lint`; `go vet -tags contract,fixture,e2e ./...`; `git diff --stat main -- testdata/golden` is empty. With `local/.env` loaded, and never printing a token, read from Infrahub's `main` (read-only): the schema hash from `GET $INFRAHUB_ADDRESS/api/schema/summary` begins `e43a1cde`; `Branch { name }` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage`, `CoreChangeComment`, `CoreUserValidator` and `CoreCheckDefinition` each count 0; `CoreReadOnlyRepository` holds `fylgja` alone; `CoreGraphQLQuery` holds `device_config` alone. Read `docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'` and confirm `172.17.0.1` (research §1.1). Write nothing; report the results.
  - *2026-10-19 13:40Z, at `a0d5620`:* every check passed. `make build`; `bin/fylgja` statically linked. `make test` 29.3 s wall uncached (`GOFLAGS=-count=1`, load average 3.6; `internal/cli` 25.6 s), 38.3 s on a first run with 8 of 21 packages cached, both under 45 s. `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden differs from `main`. Infrahub's `main`: schema hash `e43a1cde…`; `Branch` lists `main` and `fylgja-fixture` alone; `CoreProposedChange`, `FylgjaStage`, `CoreChangeComment`, `CoreUserValidator` and `CoreCheckDefinition` each count 0; `CoreReadOnlyRepository` holds `fylgja` alone (`https://github.com/happypathnetworking/fylgja.git`, `ref main`); `CoreGraphQLQuery` holds `device_config` alone. The bridge's gateway is `172.17.0.1`. Nothing was written to Infrahub.
- [X] T002 [operator] Put [D-051](research.md#3-the-decision-entries-drafted) (`twin rehearse` as a fifth short workflow, `fylgja-rehearse`, with children under their fixed ids and a derived deadline under a 3,600 s ceiling) to the operator, at `analyze`, as 014 did D-046. If accepted, append it to `docs/decisions.md` as D-051, in D-048's format, after D-048 and before "Parked". Say in this task's note whether Constitution VIII's text must be amended for a fifth workflow (a version bump citing D-051, `.specify/memory/constitution.md`) or whether the entry alone satisfies VIII, as the plan's row VIII argues. If declined, record the answer in `research.md` §5 and build nothing in Phase 3. Blocks T018.
  - *2026-10-19, the operator's answer, after `analyze`:* accepted. Appended as [D-051](../../docs/decisions.md#d-051), after D-050 and before "Parked". Constitution VIII is not amended and stays 1.3.0: its text admits a workflow, a long-running one included, through a decision-log entry, as the step and following workflows were admitted, and `fylgja-rehearse` is short, bounded by its deadline under the 3,600 s ceiling. D-051's status says so.
- [X] T003 [operator] Put [D-050](research.md#3-the-decision-entries-drafted) (the server listens on the host's Docker bridge beside loopback, in plaintext, under the one token, superseding D-042's loopback default for this deployment) to the operator at `analyze`. If accepted, append it as D-050 in the same format, and grep `docs/architecture.md` for D-042's loopback default, noting each hit for T058. Blocks T031.
  - *2026-10-19, the operator's answer, after `analyze`:* accepted. Appended as [D-050](../../docs/decisions.md#d-050); D-042's status is left as it is, since D-050 replaces only its loopback default and its token stands (as D-048 left D-045's). `docs/architecture.md`'s hits for D-042's loopback default, for T058: line 849 (the lab host's processes: `fylgja serve` on `127.0.0.1:7650`), line 1219 (the API row: "HTTP/1.1 on loopback by default") and lines 1308–1312 (§6's limitation: "On an address off loopback the token crosses unencrypted", a remote client through an SSH tunnel or a proxy). Line 983, a client's default `FYLGJA_API_ADDRESS` of `127.0.0.1:7650`, stays true. D-042's own revisit clause ("a server has to listen off loopback as a matter of course: that needs TLS") is what D-050 decides against, on the reasons its options give.
- [X] T004 [operator] Put [D-049](research.md#3-the-decision-entries-drafted) (a check posts the rehearsal's report as a comment, beside D-026; Fylgja writes nothing) to the operator at `analyze`. If accepted, append it as D-049. Blocks T042.
  - *2026-10-19, the operator's answer, after `analyze`:* accepted. Appended as [D-049](../../docs/decisions.md#d-049).
- [X] T005 [operator] Put [D-052](research.md#3-the-decision-entries-drafted) (the check concludes from the report's status alone; Fylgja's verdicts stay advisory, beside D-039) to the operator at `analyze`. If accepted, append it as D-052. Blocks T042.
  - *2026-10-19, the operator's answer, after `analyze`:* accepted. Appended as [D-052](../../docs/decisions.md#d-052).

---

## Phase 2: Foundational — the formats and the pure package

**Purpose**: the record's rehearsal mark (`twin.json` `7`), the verify counts that ride on
the existing results, the `rehearsal` block and its contract, the nine `rehearsal.*`
rules, `internal/rehearsal` (the deadline, the verdict, the block, the reproduce commands,
the markdown), and the API's `markdown` rendering on the wire. Nothing calls the
rehearsal yet.

**⚠️ CRITICAL**: every later phase needs this one.

- [X] T006 [P] In `internal/lab/wire/types.go`, add the types data-model §5 and §6 name, with JSON names as [contracts/rehearsal.schema.json](contracts/rehearsal.schema.json) and the `7` twin schema give them. `RehearsalRef{WorkflowID, RunID string}` (`workflow_id`, `run_id`). `VerifyCounts`: per assertion kind (`host_name`, `port_enabled`, `neighbor`, `record`), the held, failed, skipped and unread counts of the wait's last read; take the exact shape from the schema's `$defs`. `RecordInput.Rehearsal *RehearsalRef`. `TwinRecord.Rehearsal *RehearsalRef` with no `omitempty`, so `7` writes an explicit `null`, as `stage` does. `VerifyResult.Counts *VerifyCounts` with `omitempty`. Each gets a doc comment in the file's style. In the package's tests, assert that a nil `Counts` is omitted and a nil `Rehearsal` on a record is `null`.
  - *2026-10-19, the loop's Run 3:* `wire.VerifyCounts` is an alias of `findings.VerifyCounts`, twin verify's own counts, whose shape is `rehearsal.schema.json`'s `$defs/count` (and `verify.schema.json`'s), so the wait's counts and verify's are one type and cross in one assignment, as `provision.StageInput` aliases `wire.StageRef`. `wire.RehearseWorkflowID` (`fylgja-rehearse`) was added beside `StepWorkflowID`, so the record names the rehearsal without importing `internal/provision`; T018's `WorkflowRehearse` can alias it. The tests are `internal/lab/wire/rehearsal_test.go`'s, which also pin that a record input of no rehearsal writes no key.
- [X] T007 `twin.json` `7` (data-model §5; [contracts/rehearse-command.md](contracts/rehearse-command.md) "twin.json 7").
  - Freeze the current `6` first: copy `contracts/twin.schema.json` unchanged to `internal/lab/testdata/contracts/014-proposed-change-stages/twin.schema.json`.
  - Then give `contracts/twin.schema.json` `$id https://fylgja.dev/contracts/twin/v7` and `twin_version` `"7"`, with `rehearsal` required: `null`, or an object with `workflow_id` (const `fylgja-rehearse`) and `run_id` (a non-empty string), no other key. Everything else of `6` stands.
  - In `internal/lab/twin.go`: `TwinVersion` `"7"`; `RecordFields.Rehearsal`; `NewRecord` copying it from `RecordInput.Rehearsal`; `NewStepRecord` keeping the previous record's. A `6` record decodes with `Rehearsal` nil.
  - Add `TestRecord7` (a rehearsal's record and a hand twin's `null`, both against the contract) and `TestRecord6ReadsWithNoRehearsal` (against the frozen copy) in `internal/lab/twin_test.go`.
  - Set `frozenContractCopies` to 30 in `internal/findings/frozen_contracts_test.go`. Fix every test that pins `"6"` as the current version.
  - *2026-10-19, the loop's Run 3:* `NewRecord` refuses a rehearsal naming another workflow or no run, as the contract does; `RecordTwin` copies `RecordInput.Rehearsal`, and `NewStepRecord` keeps the previous record's through its copy. As 014 renamed its tests to the current version, `TestCreateWritesVersion6`, `TestVersion6RecordCarriesEachWait`, `TestVersion6RecordRoundTrips` and `cli`'s `TestShowCreatedVersion6RecordAsM11` became `…Version7…`, and 014's `TestRecord6` became `TestRecordNamesItsStage` beside the new `TestRecord7`. The tests that rewrite a record as an older worker wrote it (`lab`'s `olderRecord`, `cli`'s `record5` and its version 2 to 5 cases) drop the `rehearsal` key, which the frozen schemas refuse. The documents naming `twin.json` `6` (`CLAUDE.md`, `docs/architecture.md`, `docs/development.md`, `contracts/cli.md`, `contracts/api.md`) are left to T053 and the records phase.
- [X] T008 The counts and the record's mark through the existing runs, with no new activity, budget, heartbeat or version marker.
  - `internal/lab/verify.go`: `VerifyTwin` fills `wire.VerifyResult.Counts` from its last read.
  - `internal/provision/types.go`: `StepResult.WaitCounts *wire.VerifyCounts` (`wait_counts`, `omitempty`), filled by `observeStep` in `workflow_step.go` from the wait's last `VerifyTwin`. `ProvisionInput.Rehearsal *wire.RehearsalRef` (`omitempty`), copied into the record's `RecordInput` in `workflow_provision.go` where `Stage` is.
  - Tests: a count case in `internal/lab/verify_test.go`; `workflow_step_test.go` asserting `WaitCounts` after a settled wait; `workflow_provision_test.go` asserting the record input carries a given `Rehearsal` and nil otherwise.
  - The nine recorded histories in `workflow_replay_test.go` must replay unchanged (research R-07).
  - *2026-10-19, the loop's Run 3:* `verify.Report.Counts()` was factored out of `Block`, so `VerifyTwin` counts its last read exactly as twin verify counts its block. The counts are nil when no read was kept (the cancellation cut the first) and on a retry that returns the wait the record already holds, since the record keeps no counts; `TestVerifyTwinCountsItsLastRead` pins settled, expired, a node unread, the cut first read and the retry. The step tests' `settledWait` answers with counts, and `withoutTheWait` drops them. The nine histories replay unchanged. Uncached `make test` took 36.6 s (load average 2.9; `internal/cli` 26.8 s); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden moved. Tier 2 was not run: no task of this run names a tier-2 test, and no file under a `contract`, `fixture` or `e2e` tag reads the record's version.
- [X] T009 The contracts.
  - Copy [contracts/rehearsal.schema.json](contracts/rehearsal.schema.json) to `contracts/rehearsal.schema.json`.
  - `contracts/findings.schema.json` (still version `1`): the operation `twin.rehearse` in the operation enum, and a `rehearsal` property referencing `rehearsal.schema.json`'s block by `$id`.
  - `contracts/show.schema.json`: `record.rehearsal` (the `RehearsalRef` shape or `null`). `contracts/verify.schema.json`: `twin.rehearsal`, the same. `contracts/step.schema.json`: `wait_counts` where the step's result or wait is described, optional.
  - In `internal/compiler/contract_test.go`, add `rehearsal.schema.json` to the referenced schemas.
  - Leave `api.schema.json` to T016. `make test` must stay green: existing documents still validate.
  - *2026-10-19, the loop's Run 4:* `contracts/rehearsal.schema.json` is the spec's copy, byte for byte. Four schemas moved, each description gaining a 015 sentence: `findings.schema.json` (`twin.rehearse`; `rehearsal` by `$id`), `show.schema.json`, `verify.schema.json` and `step.schema.json`; `twin.schema.json` moved at T007 and `api.schema.json` is T016's. `show.record.rehearsal` is optional, `{workflow_id: fylgja-rehearse, run_id}` or `null`, and the build leaves it out when the record names none, as it does `stage`, so M4–M7's frozen contracts still accept a document of no rehearsal. `verify.twin.rehearsal` is required and nullable, as `twin.stage` is, and written as `null` (no copy of the verify schema is frozen). `step.schema.json`'s `wait_counts` sits beside `wait` in `$defs/step`, its count restated as `$defs/count` (as `rehearsal.schema.json` restates it), so the step schema refers to no other file; **no document writes it yet**: `provision.StepDocument` does not carry `StepResult.WaitCounts` into twin step's block, and no task asks it to (for converge to weigh). `rehearsal.schema.json` is supplied under its `$id` wherever the current findings contract is compiled: `compiler`'s `contract_test.go`, `findings`' `currentResources`, `verify`, `provision`'s `mustValidateM11`, `cli`'s `answer_test.go` and `create_test.go`, `server`'s `server_test.go` and `helpers_test.go`, and `api`'s `wire_test.go`. **One test was given a transitional exception**: `api`'s `TestOperationsAreTheContractsAndTheirPaths` holds `api.Operations` equal to the findings contract's operation enum, which now holds `twin.rehearse` before the API serves it, so the test leaves `twin.rehearse` out of the enum it compares. T016 must drop that exception when it adds the operation; the test fails until it does.
- [X] T010 `internal/findings`.
  - In `finding.go`: the nine rule constants of [contracts/rehearse-command.md](contracts/rehearse-command.md) "Identifiers" (`RuleRehearsalDeadlineUnfit`, `RuleRehearsalTwinReclaimed`, `RuleRehearsalStepsNone`, `RuleRehearsalStageFailed`, `RuleRehearsalStageError`, `RuleRehearsalBaselineFailed`, `RuleRehearsalDeadlineCut`, `RuleRehearsalStageMoved`, `RuleRehearsalChangeClosed`). Each takes the house comment (`// rejection, exit 1, start: <object>; <when>`) with the table's severity, exit and step. Register each wherever the file registers a rule's severity, exit and step. Add `OpTwinRehearse = "twin.rehearse"`.
  - In `render.go`: `RehearsalBlock` and its parts, field for field from `contracts/rehearsal.schema.json` (the proposed change, `resolved_at`, `deadline_s`, `ceiling_s`, `used_s`, `reclaimed`, `run`, `baseline`, `stages` with each stage's `ref`, `label`, `description`, `at_source`, `branch`, `at`, `bundle_id`, `role`, `verdict`, `findings`, `provision`, `step`, `wait`, `verify`, `new_findings`, `took_s`, then `destroy` and `reproduce`); `Document.Rehearsal`; `ShowRecord`'s `Rehearsal`.
  - The verify document's `twin.rehearsal`, in `internal/findings/verify.go` and `internal/verify/report.go` (`TwinInfo.Rehearsal`), whichever carries the field.
  - Extend `finding_test.go`'s tables. Add `rehearsal_test.go`: a full block (every role and verdict, a reclaim, a failed stage with `reproduce`) and a refused document, each validating against `contracts/findings.schema.json` with `rehearsal.schema.json`. Fix `decode_test.go`.
  - *2026-10-19, the loop's Run 4:* the nine constants follow M13's block in `finding.go`, each with the house comment. `finding.go` keeps no registry of severity, exit and step beyond those comments; the table that registers a rule is `finding_test.go`'s `dataModelRules`, which gained the nine. The objects the comments name, which the contract's table leaves open, are the branch for `rehearsal.deadline.unfit` and `rehearsal.change.closed`, the dead run's id for `rehearsal.twin.reclaimed`, and the stage's `<branch>/<label>` for the other six. In `render.go`: `OpTwinRehearse`; `RehearsalBlock` with `RehearsalReclaim`, `RehearsalBaseline`, `RehearsalStage`, `RehearsalProvision`, `RehearsalStep`, `RehearsalPush` and `RehearsalWait`, field for field from the schema. The baseline's findings and a stage's new findings reuse `StepWaitFailing` (rule, object, message), a stage's counts `VerifyCounts`, and every run `ShowRef`. Every nullable key is written and every list as `[]`. `Document.Rehearsal` and `ShowRecord.Rehearsal` (omitted when nil) were added; filling the latter from the record is T026's. `VerifyTwin.Rehearsal` (`null` when none) is filled by `verify.TwinOf` from the record through `TwinInfo.Rehearsal`, so twin verify's document carries it already; `TestBlock` pins `null` for a hand twin and the run for a rehearsal's. `rehearsal_test.go`'s four documents are: nonconforming after a reclaim, with every role, a passed and a failed stage and `reproduce`; an error where the deadline cut a step; a baseline not built; and a refusal before any run. Each validates against the current contract with no content, and together they cover the contract's every role and verdict (read from its enums). The tests pin the nullable keys and show and verify of a rehearsal's twin, and `decode_test.go` round-trips all of them. These are shapes the schema admits; the verdicts and roles T013's `Build` gives a baseline not built or a refused rehearsal's stages are T013's to decide. Gates: `make build`, statically linked; uncached `make test` 36.8 s (load average 2.1; `internal/cli` 26.4 s), and 29.8 s on the committed tree (load average 3.2; `internal/cli` 26.2 s); `make lint` 0 issues; `go vet -tags contract,fixture,e2e ./...` clean; no golden moved. Tier 2 was not run: no task of this run names a tier-2 test, and no file under a `contract`, `fixture` or `e2e` tag compiles a contract or reads the verify twin.
- [ ] T011 Create `internal/rehearsal/doc.go`: the package comment says it holds the rehearsal's pure rules and renderings, imports `findings`, `lab/wire` and `step` alone, and cites D-051. Create `internal/rehearsal/deadline.go` and `deadline_test.go` (R-09; data-model §4).
  - `Ceiling = 3600 * time.Second`.
  - `Mechanism{CheckHost, Stage, Record, PlanTeardown, Unstage, InspectTwin, ReadinessMargin, PushMargin, VerifyMargin, Wait time.Duration}`.
  - `DeadlineStage{Role string; Nodes []wire.NodePlan}`. `Deadline(m Mechanism, stages []DeadlineStage) time.Duration`: for each stage, the largest of each budget over its nodes (`DeployTimeoutS`, readiness `TimeoutS`, the push's timeout, `DestroyTimeoutS`; Constitution II, no constant per platform), summed as data-model §4's three formulas give them, the destroy once.
  - `Fits(deadline, ceiling time.Duration) bool`.
  - `TestDeadline`, with SR Linux's budgets (deploy 180, readiness 60, push 30, destroy 60) and `Mechanism` at research §1.7's values: the fixture's refused branch point, two marks and the head give 1,950 s (570 + 630 + 630 + 120); a compiled branch point 2,580 s; the mixed fixture's three stages 2,400 s; one stage alone is the baseline and the destroy; a stage list over the ceiling is not `Fits`; a stage of SR Linux and EOS nodes takes each budget's largest.
- [ ] T012 Create `internal/rehearsal/verdict.go` and `verdict_test.go` (R-07; data-model §2).
  - `Verdict` with the six values `refused`, `baseline`, `passed`, `failed`, `error`, `not_reached`, as the schema spells them.
  - `NewFindings(baseline, stage []wire.StepFinding) []wire.StepFinding`: by `(rule, object)`, in the stage's order.
  - `Classify(step *StepOutcome, wait *wire.StepWait, baseline []wire.StepFinding, cut bool) (Verdict, []wire.StepFinding)`. `StepOutcome` is a value the caller fills from `provision.StepResult` (its outcome, its phase when diverged, and whether it was cancelled before its stage), so the package imports no `provision`.
  - The rules: `passed` when the step ended `stepped` or `unchanged` and nothing is new; `failed` on any divergence, or when something is new; `error` when the step was rejected, errored or cancelled before its stage, when the wait is `incomplete`, or when `cut`.
  - `Stop(v Verdict) bool`: every verdict but `passed` stops the run.
  - `TestVerdict`, one case each: a finding the baseline had; one it did not; one the baseline alone had (nothing fails); a divergence at each phase; a wait `incomplete`; `cut` mid-step; `unchanged` and settled; `verify.record.holds` never among the wait's failing (assert it is ignored if present).
- [ ] T013 Create `internal/rehearsal/report.go` and `report_test.go` (R-10; data-model §7).
  - `Build(in Input, res Result) findings.RehearsalBlock`. `Input` and `Result` are the package's own mirror of what the server holds before the run and after it: the plan's stages, the baseline, the deadline and ceiling, the reclaim, the run, each stage's child result, wait, counts and time, and the destroy's cleanup. The server fills them from `provision.RehearseInput` and `RehearseResult`, so the package never imports `provision`.
  - `Reproduce(block) []string`: `fylgja twin create --stage <baseline>`, one `fylgja twin step --stage <ref> --allow-restart` per rehearsed stage up to and including the failed one, then `fylgja twin verify` and `fylgja twin destroy`; `[]` when no stage failed.
  - `StageLines(block) []string`: the text's one line per stage after the run, worded as [contracts/rehearse-command.md](contracts/rehearse-command.md) "The text" gives them (`passed`; `diverged at phase push: landed n3; not landed n1 (push.refused)`; `failed: verify.neighbor n1:ethernet-1/3`; `not reached`; `refused (contract.node.missing)`).
  - `Closing(block, status) string`: `rehearsal ok: …`, `rehearsal nonconforming: stage <ref> failed at phase <p>; the twin is destroyed; reproduce it by hand:`, and the others.
  - `StageFindings`: each stage's verify findings as warnings, object prefixed `<ref>: ` (R-08).
  - Tests: `TestReproduce` (no failure; the failure at the first rehearsed stage; at the third); `TestBlockValidates` (blocks built for ok, nonconforming, error by deadline, failed baseline, unclean and one stage alone, each validated against `contracts/rehearsal.schema.json` through `findings.schema.json`); the stage lines and closing lines pinned; no configuration line, device diff, token or login in any field (FR-012).
- [ ] T014 Create `internal/rehearsal/markdown.go` and `markdown_test.go`. `Markdown(block, status) string`, rendered from the block alone, exactly in the order and shape of [contracts/rehearse-command.md](contracts/rehearse-command.md) "The markdown" (FR-014, R-10):
  - the `##` heading naming Fylgja, the proposed change and its branch; the run line with `resolved_at`, the status, and the time used against the deadline and the ceiling;
  - the GFM table, one row per stage;
  - the Mermaid `flowchart LR`: one node per stage labelled `<ref><br/>verdict`; one edge per step labelled with what the step changed (nodes and links added or removed, nodes changed with their reasons, artifacts changed by node; never a line of content); a step not computed as a dotted edge; quoted labels with `"` as `#quot;`, `<` and `>` as `#lt;` and `#gt;`;
  - **Stages**, as `stage list` prints them; **Warnings**; **Baseline findings**; **Reproduce by hand** in a fenced block, on a failure alone;
  - the fidelity caveat in italics, last.
  - `TestMarkdown`: golden strings for an ok run with a refused branch point and an unchanged edge, and for a failed stage; the escaping of a description holding `"`, `<`, `>` and a newline; the caveat present; the reproduce block present only on a failure; and no line of any artifact's content, using the marker convention `internal/findings/finding_test.go`'s `contentMarkers` uses.
- [ ] T015 Add `TestRehearsalIsPure` in `internal/rehearsal/purity_test.go`, in `internal/step/purity_test.go`'s shape: the package imports nothing of the module but `findings`, `lab/wire` and `step`, and no I/O, clock or environment package. Add `filepath.Join("..", "rehearsal")` to `TestCompilerNamesNoPlatform`'s list in `internal/compiler/purity_test.go`.
- [ ] T016 [P] `internal/api/wire.go`: the operation `twin.rehearse` (`/v1/twin/rehearse`, argument `branch`, interrupt from `start`) in `Operations`; `RenderMarkdown = "markdown"` beside text and json; `Frame.Document.Markdown string` (`markdown`, `omitempty`); `fylgja-rehearse` among the `start` frame's workflow ids. In `contracts/api.schema.json`: the `render` enum gains `markdown`; `$defs/frame`'s `document` frame gains `markdown`; `start.workflow_id`'s enum gains `fylgja-rehearse`; `twin.rehearse`'s `args` (`branch`, a string). `api.Version` stays `"1"`. Extend `wire_test.go`: the operation's path and arguments; every new frame valid against the schema; `render: markdown` accepted on every operation; a `twin.rehearse` request carrying anything but `branch` is `400`.
- [ ] T017 Redraw the C4 model for the new package (development.md, "Keeping the documents true"). In `docs/c4/workspace.dsl`, add the component `rehearsal` ("A rehearsal's pure rules and renderings: the deadline, the verdict, the report and its markdown.", `internal/rehearsal`) in the server's and the worker's containers, with its edges to `findings` and `step`. Add `internal/rehearsal` to `docs/development.md`'s package layout. Run `make diagrams`. Check that `git diff --stat docs/c4 docs/diagrams docs/development.md` moves only the new component, its edges and the import graph's `internal_rehearsal`. Then gate the phase: `make build`; `file bin/fylgja` statically linked; `make test` under its budget; `make lint`; `go vet -tags contract,fixture,e2e ./...`; `git diff --stat main -- testdata/golden` empty. Depends on T006–T016.

**Checkpoint**: `twin.json` is `7`, with the `6` frozen; the block, the rules and the
rendering are in the contracts and in `findings`; `internal/rehearsal` is pure and tested;
the tree is green.

---

## Phase 3: Foundational — the fifth workflow, `fylgja-rehearse`

**Purpose**: the run that holds a rehearsal together (R-01, D-051): provision, step and
destroy as children under their fixed ids, the baseline's wait, the deadline as a timer,
the destroy on a disconnected context from every path, and the service's view of it.
Needs D-051 accepted (T002).

**⚠️ CRITICAL**: Phases 4–9 need this one.

- [ ] T018 In `internal/provision/types.go`, add `WorkflowRehearse = "fylgja-rehearse"` beside the four, with its doc comment. Add the wire-crossing types of data-model §6, each with JSON names in the file's style:
  - `RehearseInput{ProposedChange{ID, Name, Branch, Draft}, ResolvedAt, DeadlineS, CeilingS, Stages []RehearseStage, Version}`;
  - `RehearseStage{Ref, Label, Description, AtSource, Branch, At, BundleID, BundlePath, Refused *{Rule, Message}, Role, Diff, Provision *ProvisionInput, Step *StepInput, WaitS}`;
  - `RehearseResult{Outcome, Stages []RehearsedStage, Reached, DeadlineHit, StartedAt, EndedAt, UsedS, Destroy *DestroyResult, Findings}`, where `Outcome` is one of `ok`, `stage_failed`, `stage_error`, `baseline_failed`, `cut`, `cancelled`;
  - `RehearsedStage{Ref, Verdict, Run *RunRef, Provision *ProvisionResult, Step *StepResult, Wait *wire.StepWait, Counts *wire.VerifyCounts, NewFindings []wire.StepFinding, TookS}`.

  In `options.go`, add `DeadlineMechanism() rehearsal.Mechanism`, filled from `CheckHostBudget`, `StageBudget`, `RecordBudget`, `PlanTeardownBudget`, `UnstageBudget`, `InspectTwinBudget`, `ReadinessMargin`, `PushMargin`, `VerifyMargin` and `verify.DefaultBudget`. Add a test in `options_test.go` that each field equals its constant. Depends on T002.
- [ ] T019 Create `internal/provision/workflow_rehearse.go` with `Rehearse(ctx workflow.Context, in RehearseInput) (RehearseResult, error)`, as R-01 and contracts/rehearse-command.md "The run" give it. It never returns an error: every path ends in one result.
  1. A deadline timer (`workflow.NewTimer` on `in.DeadlineS`) whose firing cancels a child context derived from the run's.
  2. The baseline: a child `fylgja-provision` under `ChildOptions(WorkflowProvision)` with the stage's `Provision` input. It is already compiled, carries `Rehearsal` (this run's `WorkflowID` and `RunID` from `workflow.GetInfo`) and has `StopFollowing: true`. Then its wait, `VerifyTwin` on the run's context, with `From` the record's `recorded_at`, `BudgetS` the stage's `WaitS` and `RunID` this run's (so `Recorded: false`). Its `Failing` is the baseline findings.
  3. Each later stage in order: a child `fylgja-step` under `ChildOptions(WorkflowStep)` with the stage's `Step` input. The verdict comes from `rehearsal.Classify` over the child's result, its wait and the baseline findings. The run stops at the first verdict that `rehearsal.Stop`s, and marks every later stage `not_reached`.
  4. Always, last: a child `fylgja-destroy` on `workflow.NewDisconnectedContext`.

  The rest of the rule:
  - The deadline's firing marks the stage in progress `error` (`cut`), with `DeadlineHit` set.
  - The run's own cancellation (the operator's interrupt, `twin destroy`) cancels the children the same way. The outcome is `cancelled`, and the destroy still runs.
  - The baseline's provision not ending ready is `baseline_failed`, with no stage rehearsed; the provision cleaned up after itself, and the destroy child still runs and finds nothing.
  - `UsedS` comes from `workflow.Now`; each stage's `TookS` is its child plus its wait.
  - The run branches only on `Role`, the children's outcomes and the verdict, reads no clock but the workflow's, and starts no activity but `VerifyTwin`.
- [ ] T020 Wire it into the worker and the client.
  - In `worker.go`, register `Rehearse` as the fifth workflow; `doc.go`'s count says five.
  - In `client.go`: `StartRehearse(ctx, in RehearseInput) (string, error)` (the fixed id, `WorkflowExecutionErrorWhenAlreadyStarted`; `run.in_flight` by the fixed id; `run.worker.absent` as the others); `ResultOfRehearse(ctx, runID) (RehearseResult, error)`.
  - `StartDestroy` cancels a running `fylgja-rehearse` first and follows it to its end, its destroy child included, with the notice `cancelling rehearsal run <id>; waiting for its destroy`, before the step and provision checks it already makes (R-12).
  - `StartProvision` and `StartStep` are refused beside a running rehearsal (`run.in_flight` naming `fylgja-rehearse`'s run).
  - `InFlight` lists `fylgja-rehearse` with its running child and the step that child is at, and never lists that child a second time (as it lists a check's children). Add a `RehearsalRunning(ctx) (runID string, err error)` read if the server's reclaim needs one.
  - Add the new methods to the `Service` interface. Extend the fakes that implement it: `internal/cli/create_test.go`'s `fakeService`, with `rehearseRun`, `rehearseEvents` and `rehearseResult` fields, and any fake in `internal/server`.
  - Extend `client_test.go`, `client_follow_test.go` and `client_interrupt_test.go` for each.
- [ ] T021 Create `internal/provision/workflow_rehearse_test.go` on the Temporal Go SDK test suite, the children faked with `env.OnWorkflow` and `VerifyTwin` mocked, in `workflow_reconcile_test.go`'s style. One test per path (quickstart §1; FR-028):
  - `TestRehearseEveryStagePasses`: a refused branch point, a baseline, two rehearsed stages; verdicts `refused`, `baseline`, `passed`, `passed`; the destroy last.
  - `TestRehearseStopsAtAFailedStage`: a divergence at `push`, the later stage `not_reached` and never started.
  - `TestRehearseNewFindingFails`: a finding the baseline lacked.
  - `TestRehearseBaselineFindingsFailNothing`.
  - `TestRehearseBaselineNotBuilt`: no step started; the destroy run.
  - `TestRehearseStepRejectedIsError`.
  - `TestRehearseWaitIncompleteIsError`.
  - `TestRehearseDeadlineCutsAStepAndDestroys`: the timer fires mid-step, the step child is cancelled, `DeadlineHit`, the destroy run.
  - `TestRehearseDeadlineDuringTheBaseline`.
  - `TestRehearseDeadlineDuringAWait`: the timer fires during a stage's wait; the stage is `error`, `DeadlineHit`, the destroy run.
  - `TestRehearseCancelledDestroys`: the run cancelled mid-step.
  - `TestRehearseDestroyUnclean`: the destroy's cleanup left something; the outcome stands and `Destroy` carries it.
  - `TestRehearseOneStage`: the baseline alone, verified and destroyed, `ok`.
  - `TestRehearseRecordNamesTheRun`: the provision child's input carries this run's `RehearsalRef`.

  Add `Rehearse` wherever `determinism_test.go` lists the workflows. The nine recorded histories in `workflow_replay_test.go` must replay unchanged.
- [ ] T022 Redraw the C4 model for the worker's fifth workflow: the worker's description and its `provision -> rehearsal "Classifies each stage"` edge in `docs/c4/workspace.dsl`, then `make diagrams`. The diff moves only those, and the import graph's `internal_provision --> internal_rehearsal`. Gate: `make build`, `make test` under its budget, `make lint`, `go vet -tags contract,fixture,e2e ./...`. Depends on T018–T021.

**Checkpoint**: the worker serves five workflows; a rehearsal under the test suite ends in
its destroy on every path; the replays pass; the tree is green.

---

## Phase 4: User Story 1 — `twin rehearse`: a proposed change rehearsed on a twin, and reported (Priority: P1) 🎯 MVP

**Goal**: `fylgja twin rehearse --branch <b>` resolves and compiles every stage, boots the
baseline, steps and verifies through each later stage, stops at the first that fails,
destroys the twin, and answers with the report as text, JSON or markdown.

**Independent Test**: through the API's harness with a faked Infrahub and a faked
workflow service, `twin rehearse --branch b` over a draft with two marks starts
`fylgja-rehearse` with a refused branch point, a baseline and two rehearsed stages, prints
the stage lines and `rehearsal ok`, exit 0. With a failed stage it ends `nonconforming`,
exit 5, with the reproduce commands. A stale mark is refused, exit 1, with no run started.
Proved live in T041.

- [ ] T023 [US1] Create `internal/server/rehearse.go` with `runTwinRehearse(ctx, opts, f *rehearseFlags) error`, its first half as [contracts/rehearse-command.md](contracts/rehearse-command.md) "What the server does, in order" steps 1–3 and R-02, R-03, R-05 give it. Each refusal ends the request with its document and nothing started.
  - The guards: `branch` required (absent is `--branch is required`, `operation.failed`, exit 2; empty is `stage.ref.invalid` at `start`), before any connection.
  - The packages.
  - `stages.Plan` over the branch's open proposed change, with the dry run's filing pipeline, exactly as `runStagePlan` runs it (share the code rather than copying it).
  - The baseline rule, as a function `rehearsalStages(plan) (baseline int, rows []…, refusal *findings.List)`. A branch point whose one rejection is `contract.node.missing` at `read` is kept as a `refused` row and passed over. Any other refused or failed stage refuses the rehearsal with the plan's findings: `rejected`, exit 1, or `error`, exit 2, for `operation.failed` and `intent.at.precision`. One compiled stage alone files `rehearsal.steps.none`.
  - The deadline: each compiled stage's node plans, read as the dry run reads them, through `rehearsal.Deadline(provision.DeadlineMechanism(), …)`. Over `opts.rehearsalCeiling` (default `rehearsal.Ceiling`, a field a test may lower and no flag sets), it is `rehearsal.deadline.unfit` at `start`, exit 1, naming both.
  - The step chain: one `provision.StepInput` per later stage, as `runTwinStep` builds one but reading no twin. `From` is the previous stage's side and `To` the target's; `ToBundlePath` the store's copy; `Diff`, `Unchanged`, `PushPlan` (`step.PushPlan(s, step.Lifecycle{})`), `Changed` and `Declared` from the plan and the registry; `AllowRestart: true`; `WaitS` from `verify.DefaultBudget`; an empty `Plan`.
  - The baseline's `ProvisionInput`, already compiled, with its stage.

  Put the pure parts (the baseline rule, the step chain, the input) in functions tested in `internal/server/rehearse_test.go` over a canned `stages.PlanResult`.
- [ ] T024 [US1] [US4] In `internal/server/rehearse.go`, the host part (steps 4–5; R-04).
  - The runs in flight: `fylgja-rehearse`, `fylgja-provision`, `fylgja-step` or `fylgja-destroy` running is `run.in_flight`, exit 1, naming the run. This is read through the service, as `runTwinStep`'s start reads it.
  - Then the twin record. If it carries a `rehearsal` naming a `fylgja-rehearse` run that is not running, reclaim it: print the notice `reclaiming the twin of rehearsal run <id>`, start and follow the destroy through `StartDestroy` as `runDestroy` does, file `rehearsal.twin.reclaimed`, and fill the block's `reclaimed`. A destroy that leaves something refuses with `cleanup.incomplete`, exit 4.
  - Then the host check of the baseline bundle in this process, through `dryRunActivities` as the dry run makes it, with every refusal it makes today under its identifier at `host_check`, exit 1.

  A record with no rehearsal, a hand twin and an orphan lab are refused by the host check's presence refusals, never reclaimed.
- [ ] T025 [US1] In `internal/server/rehearse.go`, the run and the report (steps 6–7; R-10, R-12).
  - The start: the `start` frame with `fylgja-rehearse`, `StartRehearse`, then the `run` frame.
  - The follow: every event of the run and its children, as `Follow` reads a check's children. Each child is announced by its `run <workflow> <id>` notice and preceded by the `stage <ref>: creating the twin` / `stepping` line, and the destroy by `destroying the twin`. After each child, a `stage <ref>: …` summary line. The interrupt comes from `start`, as for a create.
  - After the run closes: `ResultOfRehearse`. Then the stages read again (list the proposed change's stages through `stages.List` for the branch) for `rehearsal.stage.moved` (a rehearsed stage no longer at its `(branch, at)`, or gone, the head included) and `rehearsal.change.closed`. Then `stage.main.moved` and the plan's other warnings, carried over.
  - The document: operation `twin.rehearse`, `subject.branch` and `subject.run_id`, the block through `rehearsal.Build`, every verify finding as a warning with its stage prefixed. The status and exit by R-08: `ok` 0; `nonconforming` 5 through `rehearsal.stage.failed`; `error` 2 through `rehearsal.stage.error`, `rehearsal.deadline.cut` or `run.cancelled`; `failed` 3 through `rehearsal.baseline.failed`, with the provision's own findings beside it; `unclean` 4 through `cleanup.incomplete`, whatever the stages did.
  - The text's stage lines and closing line through `rehearsal.StageLines` and `Closing`.
  - In `handlers.go`, the route. In `call.go` and `options.go`, `render: markdown`: the `out` and `err` frames as under `text`, and the `document` frame carrying `markdown` (`rehearsal.Markdown`) beside `text` on `twin.rehearse` alone. Every other operation answers `markdown` as it answers `text`, with no `markdown` field.
- [ ] T026 [US1] The commands beside a rehearsal (FR-008; contracts/rehearse-command.md "twin show, twin verify, twin destroy, stage list").
  - `internal/server/show.go`: a rehearsal's twin's kind line (`pinned at …, stage <ref>, of rehearsal run fylgja-rehearse <id>; not following`), `record.rehearsal`, and the in-flight line naming the rehearsal, its child and the stage it steps towards.
  - `verify.go`: the first line naming the rehearsal's run after the stage, and `twin.rehearsal`.
  - `destroy.go`: printing the cancel notice and following the rehearsal's destroy before its own.
  - `create.go`, `provision.go` and `step.go`: `run.in_flight` naming the rehearsal, through T020's refusals.
  - Extend `internal/server/server_test.go` and `step_test.go` for each.
- [ ] T027 [US1] The client.
  - In `internal/api/client.go`, request `render: markdown` and return the document frame's `markdown`.
  - Create `internal/cli/rehearse.go`: `fylgja twin rehearse --branch <b> [--markdown] [--json]`, one request. `--branch` missing is `--branch is required`, exit 2, with no request. `--markdown` with `--json` is cobra's mutual-exclusion refusal, exit 2, with no request. `--markdown` prints the markdown alone on stdout and exits by the document.
  - Register it under `twin` in `root.go`, and carry `doc.Rehearsal` and the markdown in `send.go`.
  - `TestClientReachesTheCoreThroughTheAPIAlone` in `internal/compiler/purity_test.go` must pass unchanged.
- [ ] T028 [US1] Create `internal/cli/twin_rehearse_test.go`. Through the harness, 014's fake Infrahub (`internal/cli/infrahub_test.go`, serving a draft proposed change with two marks on a `main` with no network), and `fakeService` answering `StartRehearse`, `Follow` and `ResultOfRehearse`, write one test per acceptance scenario of US1:
  1. two marks, every stage passing: the `RehearseInput` started carries the refused branch point, the baseline `seeded` and the two rehearsed stages with `AllowRestart` and the default wait; the text's stage lines; `rehearsal ok`; exit 0.
  2. a step diverged at `push`: `failed` naming the phase and the nodes, the later stage `not reached`, the reproduce commands, exit 5.
  3. a new finding: `failed` naming it, exit 5.
  4. the baseline's finding repeated and nothing new: exit 0, the finding reported as the baseline's.
  5. a stale mark: refused with 014's finding, exit 1, `StartRehearse` never called and no host read; and an unknown branch, `stage.unknown`.
  6. a refused branch point among the rows, the rest rehearsed; a stale mark still refusing the whole.
  7. an interrupt from `start` cancelling the run, `run.cancelled`, exit 2.
  8. a result with `DeadlineHit`: `rehearsal.deadline.cut` naming the stage, each finished stage's time and the deadline, exit 2.
  9. a deadline over a lowered ceiling: `rehearsal.deadline.unfit`, exit 1, no start.
  10. `--json`: one document validating against `contracts/findings.schema.json` with `rehearsal.schema.json`, and no configuration content (`contentMarkers`).

  Add the edge cases: one stage alone (`rehearsal.steps.none`, ok); the baseline not built (`failed`, exit 3); an unclean destroy (exit 4); a stage moved and the proposed change closed after the run (the two warnings). Fix in `internal/server` or `internal/rehearsal` whatever a test finds.
- [ ] T029 [US1] In the same file:
  - the text pinned line by line against [contracts/rehearse-command.md](contracts/rehearse-command.md) "The text" (the heading line, each stage's resolved line, the stage lines around the children, the closing line);
  - `--markdown` printing T014's rendering alone on stdout;
  - `--markdown --json` refused with no request;
  - `--branch` missing, exit 2, and `--branch=` `stage.ref.invalid`, exit 2, each with nothing sent to the fakes;
  - every frame of each answer valid against `contracts/api.schema.json`;
  - the API's token in nothing the server writes (as `token_test.go` asserts for the other operations).
- [ ] T030 [US1] Redraw the C4 model for the server's use of the rehearsal: `handlers -> rehearsal "Decides the deadline; builds the report and its markdown"` and the CLI's `twin rehearse` in `docs/c4/workspace.dsl`, then `make diagrams`; the diff moves only those and the import graph's `internal_server --> internal_rehearsal`. Gate: `make build`, `file bin/fylgja` statically linked, `make test` under its 45 s budget (report the wall time), `make lint`, `go vet -tags contract,fixture,e2e ./...`, `bin/fylgja twin rehearse --help`. Depends on T023–T029.

**Checkpoint**: US1's ten scenarios pass in tier 1; the hand command is complete but not
yet run against a real twin (T041).

---

## Phase 5: User Story 4 — The server where the task workers reach it, and the host kept clean (Priority: P2)

**Goal**: `fylgja serve --listen` repeated, the override giving the task workers the
host-gateway entry and the two variables, the bring-up script starting the server on both
addresses, `SECURITY.md` saying what that exposes, and the reclaim and refusals proved.
Needs D-050 accepted (T003).

**Independent Test**: `fylgja serve --listen 127.0.0.1:0 --listen 127.0.0.2:0` reports
both addresses, and the unencrypted line after any address off loopback. A twin left by a
dead rehearsal is reclaimed through the harness, and a hand twin refuses the rehearsal.
Live: a request from inside a task worker is `200` with the token and `401` without (T037).

- [ ] T031 [US4] In `cmd/fylgja/serve.go`, make `--listen` repeatable, as [contracts/server-and-host.md](contracts/server-and-host.md) "fylgja serve" and R-17 give it. Depends on T003.
  - Cobra `StringArray`; none given is `api.DefaultAddress`.
  - Every value is checked `host:port` before anything listens (`--listen <value> is not host:port`, exit 2).
  - Every listener is opened before any serves, through `netListen`. A failure closes those already opened and refuses, `listening on <address>: <error>`, exit 2, listening on none.
  - The report: one `listening on <addr> (API version 1, build …)` line per address, in the order given, with the port it got, and straight after each address off loopback its line `<addr> is not a loopback address: the API's token is sent unencrypted on it`.
  - One `http.Server` serves every listener. A failure to accept on any is `serving on <address>: <error>`, exit 2. The request log names no address.

  Extend `serve_test.go`: two listeners, each answering a request alike; the report's lines in order; a non-loopback address's line; a second address already taken, refusing with the first closed; a malformed second value refused before anything listens.
- [ ] T032 [P] [US4] The override and the records of what it exposes.
  - In `scripts/infrahub/docker-compose.override.yml`, under `task-worker` beside its image pin: `extra_hosts: ["host.docker.internal:host-gateway"]`, and `environment` with `FYLGJA_API_ADDRESS: host.docker.internal:7650` and `FYLGJA_API_TOKEN: ${FYLGJA_API_TOKEN}`. Add a comment saying the token is read by Compose from `--env-file local/.env` and the file holds no value (R-17).
  - In `.env.example`, under `FYLGJA_API_ADDRESS`, say that the task workers get `host.docker.internal:7650` from the override and the token from this file.
  - In `SECURITY.md`, add the paragraph "The bridge listener" as [contracts/server-and-host.md](contracts/server-and-host.md) "SECURITY.md" gives it, citing D-050. "On a shared host"'s first bullet then says the port is on loopback and the bridge (FR-027).
- [ ] T033 [P] [US4] `scripts/bring-up.sh` ([contracts/server-and-host.md](contracts/server-and-host.md) "The bring-up script"). In `infrahub`: when the override is copied or replaced (`item infrahub override installed`), `compose up -d` runs even when every service is up, so the task workers are recreated. In `fylgja`:
  - the bridge address is read with `docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`; a host with no `bridge` network fails the item, naming it;
  - the server is started with `--listen 127.0.0.1:7650 --listen <bridge>:7650`;
  - `report_ok` requires both listen lines and the bridge's unencrypted line, so a server running from this tree on loopback alone is restarted;
  - the final report's `running: server` line names both addresses and says the token crosses the bridge in the clear.

  Run `shellcheck scripts/bring-up.sh` and `bash -n scripts/bring-up.sh`. Do not run the script: it asks for sudo, so running it is the operator's (T036).
- [ ] T034 [US4] Create `internal/cli/twin_rehearse_host_test.go`. Through the harness and `fakeService`, with a twin directory the test writes, one test per scenario:
  - scenario 4, a `7` record whose `rehearsal` names a run the fake says is not running: the notice, the destroy followed before the `start` frame with no `run` frame of its own, `rehearsal.twin.reclaimed` naming the run and what was removed, the block's `reclaimed`, then the run started;
  - the same, with the reclaim's destroy unclean: `cleanup.incomplete`, exit 4, no start;
  - scenario 5, a running `fylgja-rehearse` (`run.in_flight` naming it), a hand twin's `7` record with `rehearsal: null` (`host.twin.present`, naming `twin destroy`), and an orphan lab from the fake containerlab (refused as `twin create` refuses it), each exit 1 and nothing started or destroyed;
  - a `6` record, which reads with no rehearsal and is refused, not reclaimed.

  Fix in `internal/server/rehearse.go` whatever a test finds.
- [ ] T035 [US4] The start line and the three processes (FR-026). In `CLAUDE.md`, replace the server's start line with [contracts/server-and-host.md](contracts/server-and-host.md)'s, and make its verification sentence name both listen lines and the unencrypted line. In `docs/development.md`, the three-process paragraph says how the bridge address is found (`docker network inspect bridge`), that the task workers reach it as `host.docker.internal:7650` through the override, and that the override is applied by recreating the task workers. Then `make build`, `make test`, `make lint`. Depends on T031–T034.
- [ ] T036 [operator] [US4] Apply the override on the development host (quickstart §2): either the bring-up script's `infrahub` part, or `cp scripts/infrahub/docker-compose.override.yml local/infrahub/` followed by `compose up -d` with the project's flags, so that both task workers are recreated. Then run the script's `fylgja` part twice. The first run leaves the server on both addresses; the second reports it `present`. Infrahub stays up throughout, and its volumes are untouched. Depends on T032, T033 and T035.
- [ ] T037 [live] [US4] Verify the server on the bridge (quickstart §2; SC-009).
  - Rebuild. Restart the worker and the server from this tree, with `CLAUDE.md`'s start lines as T035 left them. Verify both as `CLAUDE.md` says: `/proc/<pid>/exe` not `(deleted)`; their environments; the server's report naming both addresses, the unencrypted line and both packages with their logins set.
  - From inside `fylgja-infrahub-task-worker-1`, run quickstart §2's `python -c` request: `200 1 <build>` with the token, `401` without. From the host, `curl` the bridge address without the token: `401`.
  - Confirm that `docker inspect` of a task worker shows `host.docker.internal` mapped to the bridge address and both `FYLGJA_*` names in its environment, never printing the token's value.
  - Add `research.md` §5 "Verified at implement" and record this there, with the times. Depends on T036.

**Checkpoint**: the server listens on loopback and the bridge, the task workers reach it,
and the reclaim and the host's refusals are proved in tier 1.

---

## Phase 6: Test tooling and the rehearsal by hand (US1, live)

**Goal**: the fixture tool and test support the checks' tests and tier 3 need, the
server's tier-2 proof that a refused rehearsal dials nothing, and every US1 scenario run
by hand on the development host against real twins.

**Independent Test**: on a `fylgja-test-*` branch with a draft and two marks, `twin
rehearse` prints rows `refused`, `baseline`, `passed`, `passed` and ends `ok`. A `bad-port`
stage fails at `push` on n1, exit 5, and its reproduce commands give the same divergence by
hand. `twin show` reports no twin after each.

- [ ] T038 [P] Extend `internal/testsupport` (build tag `contract || fixture`), each helper behind the branch guard of `proposed.go` ([contracts/fixture-tool.md](contracts/fixture-tool.md) "Test support"; R-20). Verify every mutation, argument and field name against `schema/infrahub.graphql` before using it. No error carries the token.
  - In `proposed.go`: `MarkReady(id) error`. `RunUserChecks(id, timeout) ([]UserCheckRow, error)`, which sends `CoreProposedChangeRunCheck(data: {id, check_type: USER})` and polls every 5 s until every `CoreUserValidator` of the proposed change is `completed`; at the bound it names any validator still `in_progress`, which a timed-out check leaves behind (research §1.4). `UserChecksOf(id) ([]UserCheckRow, error)`, with `UserCheckRow{Name, Conclusion, Severity, Message, ValidatorState}`. `CommentsOf(id) ([]CommentRow, error)`, with `CommentRow{ID, Text}`, through the proposed change's `comments`. `AddInterface(branch, device, name) error`: one `NetworkInterface`, `iftype physical`, `enabled true`, `mgmt_only false`, no link.
  - Create `repository.go`: `BridgeAddress() (string, error)`, read as the bring-up script reads it. `ServeRepository(dir) (location string, stop func(), err error)`, which does `git init -b main`, a commit, a bare clone and `git update-server-info` under a scratch directory, served by `net/http` on `<bridge>:0`, the location `http://<bridge>:<port>/<name>.git`. `DeleteRepository(name) error`, through `CoreReadOnlyRepositoryDelete`, whose definitions and query go with it (research §1.6). `CheckDefinitions() ([]CheckDefinitionRow, error)`, the names and timeouts on `main`.
- [ ] T039 [P] In `cmd/fylgja-fixture/main.go`, add `-ready`, `-run-checks <artifact|user>` (`-run-check` stays as the `artifact` form; `user` waits up to 4,500 s) and `-add-interface <device>:<name>`, as [contracts/fixture-tool.md](contracts/fixture-tool.md) "The fixture tool" gives them, with its output lines exactly. Each refuses `fylgja-fixture` and a `-branch` outside `testsupport.TestBranchPrefix` before any request; a malformed `-add-interface` value and an unknown `-run-checks` kind are refused. Failures exit 1 as `fylgja-fixture: <message>`. Extend `docs/development.md`'s `make infrahub-seed` / `infrahub-clean` row with the three flags, and with "Composing a rehearsal for a test" in one sentence. `make lint`; `go vet -tags contract,fixture,e2e ./...`.
- [ ] T040 [US1] Write `internal/server/rehearse_contract_test.go` (build tag `contract`), every write on its own `fylgja-test-*` branch deleted by `DeleteTestBranch` in a `t.Cleanup`. `TestRehearseRefusesBeforeAnyRun`: seed, `OpenProposedChange(draft)`, `MarkStage seeded`, an intent change with no generate, then a mark. `twin.rehearse` through a server in the test's process is refused with the plan's findings: `stage.artifact.stale` naming the devices, `rejected`, exit 1. The server's `dial` seam fails the test if called, so the workflow service is never dialled, and no twin directory is created. Then smoke T039's flags on a throwaway branch: `-propose`, `-ready` (the proposed change reads `is_draft` false), `-add-interface n1:ethernet-1/99` and `-generate` (n1's checksum moves; the CTM read omits it with `omit.interface.unmappable` and warns `artifact.interface.unrepresented`, R-14), `-run-checks user` (no user check is registered on `main` yet, so it returns at once with none), `-delete`. Run `go test -count=1 -tags contract ./internal/server -run TestRehearse -v` and report its time. Boot no twin. Afterwards `Branch` lists `main` and `fylgja-fixture` alone. Depends on T030, T038 and T039.
- [ ] T041 [live] [US1] The rehearsal by hand (quickstart §3; FR-001–FR-015; SC-001–SC-004). Read `free -m` and rebuild; restart the worker and the server from this tree, and verify both; the dev server up. On `B=fylgja-test-qs-$$`, run quickstart §3 in order:
  1. The plan, then `twin rehearse`: rows `refused`, `baseline`, `passed`, `passed`, `ok`, exit 0; `twin show`, no twin; `--json`, the rows, `deadline_s` 1950 and `reproduce` empty; `--markdown`, the heading and the table.
  2. `-add-interface n1:ethernet-1/99`, `-generate` and the stage `bad-port`, then `twin rehearse`: `bad-port` `failed` at `push` on n1 (`push.refused`), `head` `not reached`, exit 5, the four reproduce commands. Run the commands by hand: the same divergence, and the destroy clears it.
  3. An interrupt during a step: `run.cancelled`, the destroy run, exit 2, no twin.
  4. A second `twin rehearse` beside a create of your own: `run.in_flight` at once.
  5. A client killed mid-rehearsal: `twin show` names the rehearsal in flight, its child and its stage, and later reports no twin.
  6. The reclaim: the worker stopped while the baseline is created, the run left to end, the worker restarted, then `twin rehearse` again prints `reclaiming the twin of rehearsal run …` and goes on.
  7. The deadline cut, by a server built into the scratchpad with T023's ceiling field lowered through a test-only build (never a flag). If no such build can cut a real stage, record why and leave the cut to T021 and T028.

  Then `-delete`. After each: no lab, no twin directory, nothing of the branch in Infrahub. Record the outputs, times and ids in `research.md` §5. A defect found here is fixed under US1, with a tier-1 test pinning it.

**Checkpoint**: the hand command rehearses, fails, reproduces, interrupts and reclaims on
real twins, and leaves the host clean.

---

## Phase 7: User Story 3 — `fylgja-step`: the plan in seconds, inside Infrahub (Priority: P2)

**Goal**: the first check, its shared glue, its query and its registration; Python glue
that decides nothing. Needs D-049 and D-052 accepted (T004, T005).

**Independent Test**: inside Infrahub's pipeline, on a draft with two marks, `fylgja-step`
concludes success, its message the plan's text with four stages and three steps. With a
mark made stale, it concludes failure naming `stage.artifact.stale` and the device (T050).

- [ ] T042 [US3] Load the `infrahub:infrahub-managing-checks` skill and read its SKILL.md and the rules it names for a Python check, applying them where `CLAUDE.md` and the plan's "The OpsMill skills" paragraph do not decide otherwise. Then create `infrahub/queries/branch.gql` (`query fylgja_branch { Branch { name } }`, with a header comment saying it is the cheap read the SDK requires and the checks ignore). Create `infrahub/checks/fylgja_api.py`, the shared glue of [contracts/checks.md](contracts/checks.md) and R-13, R-15 and R-16, deciding nothing:
  - `variables()`: the two variables, or the name of the unset one;
  - `proposed_change(client, branch)`: through `client.filters(kind="CoreProposedChange", branch="main", source_branch__value=branch, state__value="open")`, its `id`, `name` and `is_draft`;
  - `call(address, token, operation_path, render, args, stream=None, deadline=None)`: one `POST` with `httpx` (streaming, no read timeout), read frame by frame to the document, returning the `out` and `err` lines, the document, its `text` and its `markdown`;
  - the `Fylgja-Api-Versions` check;
  - `interrupt_blocking(address, token, stream)`: a blocking `httpx.Client` `POST /v1/streams/{stream}/interrupt`, never an `await` (research §1.4);
  - `post_comment(client, change_id, text)`: `CoreChangeComment` on `main`, with `text` and `change`;
  - the failure wordings: unreachable, `401`, a `404` under `Fylgja-Api-Versions`, and an answer cut before its document. Each names the address and never the token.

  No module-level side effect. Stdlib and `httpx` only, as the task-worker image carries them (research §1.1).
- [ ] T043 [US3] Create `infrahub/checks/fylgja_step.py`: `class FylgjaStep(InfrahubCheck)`, `query = "fylgja_branch"`, `timeout = 300`, `async def validate(self, data)` doing [contracts/checks.md](contracts/checks.md) "fylgja-step" steps 1–4 through `from .fylgja_api import …`:
  - the variables (`log_error` naming the unset one, nothing sent);
  - the proposed change (`log_error` when none is open on `self.branch_name`);
  - `POST /v1/stage/plan` with `render: text` and `args.branch`;
  - `log_info` of the plan's text line by line, then the findings' text.

  The conclusion: `log_error` when the document's findings hold a rejection other than a branch point's (`at_source: branch_point`) lone `contract.node.missing`, when the status is `error`, or when Fylgja cannot be reached. It runs on drafts. Use `log_error` and `log_info` alone (no `log_warning`). Add `infrahub/checks/__init__.py` only if the relative import needs one under `commits.<sha>.infrahub.checks` (research §1.2). Check the syntax with `python3 -m py_compile infrahub/checks/*.py`, which adds no test framework.
- [ ] T044 [US3] Register it in `.infrahub.yml` as [contracts/checks.md](contracts/checks.md) "Registration" gives it: the query `fylgja_branch` beside `device_config`, and `check_definitions` with `fylgja-step` (file, class). Extend the header comment for the checks. In `embed_test.go` (or a new root test file), add `TestInfrahubYAMLRegistersTheChecks`, which parses `.infrahub.yml` and checks:
  - each check definition's `file_path` exists and defines `class <class_name>(InfrahubCheck)`;
  - each class sets `query = "fylgja_branch"` and a `timeout` (`fylgja-step` 300);
  - no definition carries `query:`, `targets` or `parameters`;
  - the query's file exists.

  `go test . -count=1`.
- [ ] T045 [US3] Create `internal/checks/doc.go` (the package's purpose: tier 2's proof of the two checks inside Infrahub, R-18; the registration's names as constants) and `internal/checks/checks_contract_test.go` (build tag `contract`). `TestChecksInsideInfrahub`'s first half:
  1. `BridgeAddress` (skip, saying why, when Docker reports none).
  2. A scratch repository from the tree's `infrahub/checks/` and `infrahub/queries/` under a `.infrahub.yml` of its own naming the two checks under test-only names, `fylgja-test-step` and `fylgja-test-twin`, pointing at the tree's files and classes, so that the artifact definition is not registered twice and the names never collide with the registration `fylgja`'s once T054 has imported the checks. The query `fylgja_branch` is pinned by the classes' `query` attribute, so its name cannot be test-only: before the first import, verify on this Infrahub that two read-only repositories may each register a `CoreGraphQLQuery` named `fylgja_branch` (register a second throwaway repository holding only that query beside `fylgja`, read both, delete it), and record the answer in `research.md` §5. If they may not, the scratch copy rewrites the class's `query` to `fylgja_test_branch` and registers the query under that name, and T054's re-run proves the two registrations coexist. The test reads validators by the test-only names (the package's constants).
  3. `ServeRepository`; `EnsureReadOnlyRepository("fylgja-test-checks-<pid>", …)` and `AwaitImport`, then 15 s for both task workers' fetches (research §1.5).
  4. Seed a branch, created after the import; `OpenProposedChange(draft)`; `MarkStage seeded`; `SeedThirdLink` with the checksums awaited; `MarkStage third-link`.
  5. Read `fylgja-test-step`: when its message says the address is unreachable or the variable unset, skip, saying the task workers reach no server (CI). Otherwise it is `success`, its message holding the plan's four stages, three steps and the branch point's `contract.node.missing`.
  6. A mark made stale (an intent change with no generate, then a mark), `RunUserChecks`, then `fylgja-test-step` reads `failure`, naming `stage.artifact.stale` and the device.

  The cleanup, however the test ends: `DeleteTestBranch`, then `DeleteRepository`, then assert no `fylgja-test-*` repository and no `fylgja-test-*` check definition remain. `go vet -tags contract ./internal/checks`; do not run the test here (T050). Depends on T038, T043 and T044.

**Checkpoint**: `fylgja-step` and its glue are in the tree, registered, and syntax-checked,
with their tier-2 test written.

---

## Phase 8: User Story 2 — `fylgja-twin`: the rehearsal from inside Infrahub, as a comment and a conclusion (Priority: P1)

**Goal**: the live check: a draft skipped; otherwise the rehearsal asked for, its markdown
posted as one comment, its text the message, its status the conclusion; retries on a held
host; its own deadline inside Infrahub's.

**Independent Test**: inside Infrahub's pipeline, `fylgja-twin` skips a draft at its
creation and concludes success, booting nothing (T050). The rehearsal and its comment are
proved in tier 3 (T055).

- [ ] T046 [US2] Create `infrahub/checks/fylgja_twin.py`: `class FylgjaTwin(InfrahubCheck)`, `query = "fylgja_branch"`, `timeout = 4200`, doing [contracts/checks.md](contracts/checks.md) "fylgja-twin" steps 1–7 through `fylgja_api`. Nothing beyond the glue decides anything.
  1. The draft skip comes first, before the variables, since it needs nothing of Fylgja's (FR-020): `log_info` `skipped: proposed change <id> is a draft; mark it ready for review and re-run the checks to rehearse it`, and success.
  2. Then the variables.
  3. `POST /v1/twin/rehearse` with `render: markdown`, `args.branch` and `Fylgja-Stream: <16 random bytes in hex>`. Each `out` and `err` frame is logged as it comes.
  4. A held host (`run.in_flight`, `host.lab.present` or `host.twin.present` before any `start`) is retried every 30 s until the check's own deadline (`timeout` less 180 s) nears, then `log_error` naming the last answer's run or twin (R-15). A retried refusal's document is logged and never posted; only the final answer's is.
  5. Once the final answer's document is read, the one comment through `post_comment` with the frame's `markdown`: the report, or the last refusal's document (FR-007). A failure to post is `log_info` (`the comment could not be posted: <error>`), never `log_error` (FR-019). One comment per run, whatever the retries.
  6. The conclusion: the document's `status` alone (`ok` passes; anything else is `log_error` with the document's `text`).
  7. The connection lost after `start`: contracts/checks.md step 6's sentence.
  8. The check's own deadline while the answer is open: `interrupt_blocking`, the answer read on to its document or its cut, then `log_error` that the run was asked to cancel.
  9. A `BaseException` in the handler: `interrupt_blocking`, then re-raise.

  `python3 -m py_compile infrahub/checks/*.py`.
- [ ] T047 [US2] Add `fylgja-twin` to `.infrahub.yml`'s `check_definitions`, and extend `TestInfrahubYAMLRegistersTheChecks` to both checks (`fylgja-twin` 4200, the 3,600 s ceiling plus 600 s, R-09). Add a tier-1 test that pins the two timeouts against `rehearsal.Ceiling`: `fylgja-twin`'s `timeout` less its own 180 s margin is at least the ceiling plus the destroy's whole budget (`PlanTeardownBudget` + the largest `destroy_timeout_s` + `UnstageBudget`, 120 s) plus 300 s for the work before `start`, so a run that uses every budget still ends before the check interrupts it (FR-006, FR-021). `go test . ./internal/rehearsal -count=1`.
- [ ] T048 [US2] Extend `TestChecksInsideInfrahub` (T045): at the draft's creation, `fylgja-test-twin` reads `success` with `skipped` and the proposed change's id in its message. Through the API, `twin show` reports no twin, and no lab exists. Both checks' messages carry no token or login (FR-023, SC-008), checked against the values of the test's environment and never printed. Afterwards `CoreChangeComment` counts 0, since a draft gets no comment. `go vet -tags contract ./internal/checks`. Depends on T045–T047.
- [ ] T049 Redraw the C4 model for the checks: in `docs/c4/workspace.dsl`, Infrahub's task worker as a container running `fylgja-step` and `fylgja-twin` as a client of the API over the bridge (`HTTP, bearer token, plaintext`), the API's server listening on loopback and the bridge, and the deployment view's bridge; `infrahub/checks` beside the template in the repository's description. Then `make diagrams`; the diff moves only those. Gate: `make build`, `make test` under its budget, `make lint`, `go vet -tags contract,fixture,e2e ./...`, `python3 -m py_compile infrahub/checks/*.py`. Depends on T046–T048.
- [ ] T050 [live] [US2] [US3] The checks inside Infrahub, and tier 2 whole (quickstart §4, §5; FR-029; SC-010). With the server on the bridge from this tree (T037; restart it after T049's rebuild and verify it) and no twin, run `go test -count=1 -tags contract ./internal/checks -run TestChecksInsideInfrahub -v`. It must pass rather than skip, and report its time. Then `make test-contract`, which must pass, `TestRehearseRefusesBeforeAnyRun` and `TestChecksInsideInfrahub` among it. Afterwards quickstart §5's query must read: `main` and `fylgja-fixture`; 0 proposed changes, stages and comments; the one registration `fylgja`; and the check definitions that registration holds, none before T054. Record the tier's wall time against 716.7 s, and `fylgja-test-step`'s own time from its validator's `started_at` to `completed_at` against SC-005's minute, in `research.md` §5. Boot no twin while it runs. A failure is fixed under its story and the run repeated. Depends on T037, T040 and T049.

**Checkpoint**: both checks run inside the real Infrahub through a test-only registration;
tier 2 passes whole and leaves nothing behind.

---

## Phase 9: User Story 5 — Tier 3, the walk-through and the contracts (Priority: P3)

**Goal**: tier 3's ninth case runs the live check end to end; the README's walk-through
gets a stranger a comment on their own proposed change; the contracts say what was added.

**Independent Test**: `make test-e2e` ends `E2E-OK` with nine cases; case 9's comments
carry the table and the stages; `PLATFORMS=nokia_srlinux` runs case 9; nothing is left
behind.

- [ ] T051 [US2] `scripts/e2e.sh`: case 9 as [research.md R-19](research.md#r-19) gives it, SR Linux alone.
  - **Before the case**:
    - Require the checks on `main`: `CoreCheckDefinition` holds `fylgja-step` 300 and `fylgja-twin` 4200; otherwise fail, naming quickstart §6.
    - Require the server the task workers reach: `http://<bridge>:7650/v1/twin/show` with `local/.env`'s token, sent through a header file, must answer with `Fylgja-Build` equal to `bin/fylgja --version`'s build; otherwise fail, naming `CLAUDE.md`'s start line. The script's own server stays on loopback.
  - **The case**, on `fylgja-test-e2e-rh-<pid>-<n>`:
    1. Seed, then `-propose`, at which `fylgja-twin` skipped the draft and `fylgja-step` passed: read both through `UserChecksOf`'s query in `jq`.
    2. `-stage seeded`, `-add-link`, the checksums awaited, `-stage third-link`, `-ready`, `-run-checks user`.
    3. `fylgja-twin` reads success, its message holding `rehearsal ok`. There is one comment holding the table, the Mermaid block and **Stages**. `twin show` reports no twin.
    4. `-add-interface n1:ethernet-1/99`, `-generate`, n1's checksum awaited, `-stage bad-port`, `-run-checks user`.
    5. `fylgja-twin` reads failure, naming `bad-port`, `push` and n1. The second comment carries the reproduce commands and `head`'s row `not reached`.
    6. `-delete`, after which Infrahub holds nothing of the branch.
  - **Around it**:
    - Write the two comments' text and the two checks' messages to `$OUT`, and extend the credential and marker greps to them (FR-035, SC-008).
    - The trap's destroy cancels a rehearsal in flight, and its `-delete` covers the new branch.
    - `PLATFORMS=nokia_srlinux` runs case 9.
    - The header's case list says nine cases and nine twins.

  `shellcheck scripts/e2e.sh`; `bash -n scripts/e2e.sh`. Do not run tier 3 here.
- [ ] T052 [P] [US5] `README.md`: add a proposed-change walk-through section after "A stepping twin", as quickstart §6's tail gives it. Seed `fylgja-test-readme`, then `-propose` (the draft skipped, the plan passed), two stages, `-ready`, and the checks re-run from the proposed-change view. Read the comment and `fylgja-step`'s message in Infrahub, run `twin rehearse` by hand, and `-delete`. Say the deletion order, what the comment holds, that the checks reach Infrahub once on `origin`'s `main` and imported, and the bridge listener with a link to `SECURITY.md`. Its outputs are placeholders until T056 corrects them. The tests line says nine cases and nine twins.
- [ ] T053 [P] [US5] `contracts/cli.md` and `contracts/api.md`: a section "015: the rehearsal" in each, saying what [contracts/rehearse-command.md](contracts/rehearse-command.md), [contracts/checks.md](contracts/checks.md) and [contracts/server-and-host.md](contracts/server-and-host.md) say. `cli.md`: the command, its flags, statuses and exits, the nine `rehearsal.*` identifiers, `twin show`, `verify` and `destroy` beside a rehearsal, `twin.json` `7`, the two checks' conclusions and what each needs, and `--listen` repeated. `api.md`: `twin.rehearse` (path, arguments, frames, interrupt), `render: markdown` and the `document` frame's `markdown`, `start.workflow_id`'s `fylgja-rehearse`, the operations table, and that `api.Version` stays `1`.
- [ ] T054 [operator] [US2] Put the checks on the development host's Infrahub (quickstart §6; R-21). Once the operator has pushed the feature's commits to `origin`'s `main`, run `InfrahubReadOnlyRepositoryImportLastCommit` on the registration `fylgja`, wait for both task workers' fetches (about 15 s after the import's flow), then read `CoreCheckDefinition`: `fylgja-step` 300 and `fylgja-twin` 4200. The fixture branch, made before the import, never runs them; that is harmless and needs no rebase. Record the times in `research.md` §5. Then run `go test -count=1 -tags contract ./internal/checks -run TestChecksInsideInfrahub -v` once more against the imported checks, so that tier 2 is proved green with both registrations present. Depends on T050–T053.
- [ ] T055 [live] [US2] [US5] Tier 3 on a quiet host (quickstart §7; FR-030; SC-002, SC-006, SC-008, SC-010).
  - Read `free -m`; rebuild; restart the worker and the server (both addresses) from this tree and verify both; the dev server up.
  - Start `make test-e2e` detached, with its exit status in a file, and wait in foreground calls of under ten minutes. It must end `E2E-OK`: nine cases, nine twins, case 9's lines as T051 asserts them.
  - Rest the host, then `PLATFORMS=nokia_srlinux make test-e2e`. It must end `E2E-PARTIAL`, cases 6 and 8 skipped and case 9 run.
  - After each run: no lab, no twin directory, no Schedule, no `fylgja-test-*` branch, proposed change, stage or comment.
  - Record both wall times and case 9's rehearsal times (under fifteen minutes, SC-006) in `research.md` §5. A failure is fixed under its story and the run repeated. Depends on T051 and T054.
- [ ] T056 [live] [US5] Follow T052's walk-through by hand on the development host, with the worker and the server from this tree (SC-012), up to what needs the UI. Re-run the checks through `-run-checks user` where the README says the view's button, and read the comment and the message through the API. Correct the README to the outputs seen: ids, timings, the comment's first lines. Leave the branch and its proposed change for T057, which deletes them; nothing else is left in Infrahub or on the host. Record it in `research.md` §5. Depends on T052 and T055.
- [ ] T057 [operator] [US5] In Infrahub's UI, on the proposed change T056 left open, read the comment's rendering in the conversation tab: the table, the Mermaid drawing (no error banner), the stages, the caveat. Read `fylgja-twin`'s and `fylgja-step`'s messages under `Message` in the checks tab (research §1.8). Say what renders and what does not; then `-delete` the branch, after which nothing of it is left. The session records the answer in `research.md` §5 and fixes any rendering defect in `internal/rehearsal/markdown.go`, under US2, with a test.

**Checkpoint**: tier 3 passes whole and narrowed with the live check; a stranger's
walk-through leaves a comment and nothing else.

---

## Phase 10: Polish & the close

- [ ] T058 [P] `docs/architecture.md`.
  - §4.4: the fifth workflow and its drawing (the children, the deadline, the destroy on a disconnected context; D-051).
  - §4.6: `twin rehearse`, the `markdown` rendering, the checks as a client inside Infrahub's task worker (D-049, D-052), and the bridge listener (D-050).
  - §6: the rehearsal's limits (the deadline and its ceiling; a fault reproducible by hand; the bridge's exposure; a check's change reaches Infrahub only on import; a timed-out check leaves its validator `in_progress`).
  - Grep for D-042's loopback default (T003's hits and `loopback`) and rewrite each sentence that said the server listens on loopback alone.
- [ ] T059 [P] The developer's records.
  - `docs/glossary.md`: *rehearsal*, *baseline stage* and *baseline finding* (each distinguished from M11's *baseline*, whose entry gains a pointer), *rehearsed stage*, *verdict*, *deadline*, *reclaim*, *check (Infrahub)* (distinguished from a following twin's check), *bridge listener* (R-22).
  - `docs/development.md`: the package layout's `internal/checks` and `infrahub/checks/`; the worker's five workflows; how a check change reaches Infrahub (R-21: the push, the import, the two fetches, a branch made before it); how the checks are tested (T045's registration; the skip where no server is reachable; no Python test framework); the tiers' wall times and case counts from T050 and T055.
  - `docs/verified-facts.md`: research §1's facts and §5's, each with Infrahub 1.11.2 or Docker 29.8.1 and its date.
- [ ] T060 [P] `docs/roadmap.md` (F-007 and F-008 built, F-007's row reworded to what the check does: the plan logged as text, no comment; 016 next) and `docs/brief.md` (the rehearsal where it is named).
- [ ] T061 `CLAUDE.md`:
  - Formats: `twin.json` `7`.
  - The worker's workflow count: five, with the activities unchanged at twenty.
  - Environment's registration paragraph: the two checks imported, with their timeouts.
  - The override's task-worker entries in Infrahub's bullet.
  - Build and test's tier timings and tier 3's nine cases and nine twins.
  - The `.infrahub.yml` checks beside the template.
  - State rewritten whole: 015 built, `016-probes` next, and the open items for the operator.

  The start line is T035's; re-read it against what T037 verified.
- [ ] T062 [P] Re-read `SECURITY.md` and `.env.example` against what runs (T037, T055), and correct any sentence that no longer holds.
- [ ] T063 The closing gates and hygiene (quickstart §8; SC-011; FR-035).
  - `make build`, and `file bin/fylgja` statically linked.
  - `make test` under its budget.
  - `git diff --stat main -- testdata/golden` empty, and the live fixture still compiling to `47b2c449…` (quickstart §8's `intent read` and `twin compile`).
  - Of the format versions, only `TwinVersion` moved (`6` → `7`); bundle `4`, CTM `1`, PSP `0.6`, contract `0.2`, findings `1` and the API `1` unchanged.
  - `make lint`; `shellcheck scripts/bring-up.sh scripts/e2e.sh`; `python3 -m py_compile infrahub/checks/*.py`.
  - Quickstart §8's `loopback` grep: every hit says where the server listens now. `jq` finds one `twin.rehearse` among `findings.schema.json`'s operations.
  - `make diagrams` leaves no diff.
  - From a shell that has loaded `local/.env`, and never printing a value, `/usr/bin/grep -rlF` the tree (excluding `.git`, `.venv`, `local`, `bin`) for the values of `INFRAHUB_API_TOKEN`, `FYLGJA_API_TOKEN`, Infrahub's admin password, agent token and secret key, and both node passwords. The override must hold none, and the published defaults in the two scripts are as before.
  - Infrahub afterwards: `main` and `fylgja-fixture` alone; no proposed change, stage or comment; `main` at `e43a1cde…`; the registration's two check definitions.
- [ ] T064 [operator] The operator reads the feature's diff and its records, commits by hand (conventional messages, bodies saying why), and runs `make command-log` once the session is closed.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 first. T002–T005 are the operator's, at `analyze`. T002 blocks Phase 3, T003 Phase 5, T004 and T005 Phase 7.
- **Formats and the pure package (Phase 2)**: after T001. T006 → T007 → T008. T009 → T010. T011–T014 after T006 and T010, T012 → T013 → T014. T015 after T011–T014. T016 beside T009–T015. T017 last.
- **The workflow (Phase 3)**: after Phase 2 and T002. T018 → T019 → T020 → T021 → T022. **Blocks Phases 4–9.**
- **US1 (Phase 4)**: after Phase 3. T023 → T024 → T025 → T026. T027 after T016 and T025. T028 and T029 after T026 and T027. T030 last.
- **US4 (Phase 5)**: T031 after T003 and Phase 4. T032 and T033 beside T031. T034 after T024. T035 after T031–T034. T036 after T035, the operator's. T037 after T036.
- **Tooling and the hand rehearsal (Phase 6)**: T038 and T039 after Phase 4. T040 after T030, T038 and T039. T041 after T037 and T039.
- **US3 (Phase 7)**: after T004, T005 and Phase 4. T042 → T043 → T044. T045 after T038 and T044.
- **US2 (Phase 8)**: T046 after T042. T047 after T044 and T046. T048 after T045 and T047. T049 after T046–T048. T050 after T037, T040 and T049, never beside a twin.
- **US5 (Phase 9)**: T051–T053 after Phase 8. T054 after T050–T053, once the operator has pushed. T055 after T051 and T054, never beside tier 2. T056 after T052 and T055. T057 after T056.
- **Polish (Phase 10)**: after every story. T059 needs T050's and T055's times, T061 T037's and T055's. T064 last.

### Within a phase

Pure code is gated in tier 1 before its harness, tier-2 or live proof. A story's test
names the scenario it proves. A defect a test finds is fixed in that phase, in the package
that holds the behaviour, before the checkpoint. A live task's defect gets a tier-1 test
that pins it.

### Parallel opportunities

- Phase 2: T006 beside T009; T016 beside T011–T015.
- Phase 5: T032 and T033 beside T031.
- Phase 6: T038 and T039 together.
- Phase 9: T052 and T053 beside T051.
- Phase 10: T058, T059, T060 and T062.
- Phase 7 (the Python) can be written beside Phase 5 once T004 and T005 are accepted. It is not run until T050.

### Parallel example: after the workflow

```text
T023–T030  internal/server/rehearse.go, internal/cli/rehearse.go, twin_rehearse_test.go   (US1)
T031–T033  cmd/fylgja/serve.go, the override, scripts/bring-up.sh                         (US4)
T042–T044  infrahub/checks/, infrahub/queries/branch.gql, .infrahub.yml                   (US3)
→ then T034 (needs T024), T045 (needs T038), T046 onwards
```

---

## Implementation Strategy

**MVP**: Phases 1–4, the hand command. After Phase 4 the operator can rehearse a
proposed change from a client, proved through the harness, and from Phase 6 on real twins.
The checks (US2, US3) need the listener (US4) to reach Fylgja live, and the push and the
import (T054) to run on the host's own registration.

**Incremental delivery**: the formats and the pure package → the workflow → US1 in tier 1
→ US4's listener and override, live → the tooling and the hand rehearsal, live → US3's and
US2's checks, proved inside Infrahub in tier 2 → tier 3 and the walk-through → the records.
Every checkpoint leaves the tree green.

### Recommended route

Each line is one implement run's prompt. Every run: only the tasks it names; stop at its
checkpoint and report; a hand run leaves its work for the operator to commit, a loop run
commits its own.

1. **Run 1** — the baseline: the pure gates and Infrahub's state read (T001). Only this; stop and report.
2. **Run 2** — [operator] the four decision entries, D-049 to D-052, accepted or declined at analyze and appended (T002–T005). Stop and report.
3. **Run 3** — the wire types, twin.json 7 with the 6 frozen, and the verify counts and the record's mark through the existing runs, the histories replaying (T006–T008). Only these; stop and report.
4. **Run 4** — the contracts (rehearsal.schema.json and the five moved schemas) and findings' rules and blocks (T009–T010). Only these; stop and report.
5. **Run 5** — internal/rehearsal: the deadline, the verdict, the block and its text, the markdown, the purity test; the API's markdown rendering on the wire; the C4 model redrawn and the phase gated (T011–T017). Only these; stop and report.
6. **Run 6** — the fifth workflow fylgja-rehearse: its types, the workflow, the worker and the client, its test suite over every path, the C4 model, gated (T018–T022). Only these; stop and report.
7. **Run 7** — the server's twin.rehearse handler: the plan, the baseline, the deadline, the step chain, the host and the reclaim, the run and the report, the markdown frame, and show, verify and destroy beside a rehearsal (T023–T026). Only these; stop and report.
8. **Run 8** — the client's twin rehearse and US1's scenarios through the harness, the C4 model, gated (T027–T030). Only these; stop and report.
9. **Run 9** — --listen repeated, the Compose override, the bring-up script, SECURITY.md and .env.example, the reclaim and host refusals through the harness, the start line and the three-process paragraph (T031–T035). Only these; stop and report.
10. **Run 10** — [operator] the override applied and the task workers recreated, the bring-up script's fylgja part run twice (T036). Stop and report.
11. **Run 11** — [live] the server on the bridge restarted from this tree and verified from inside a task worker (T037). Stop and report.
12. **Run 12** — test support's helpers, the fixture tool's three flags, and the server's tier-2 refusal test with the flags smoked (T038–T040). Only these; stop and report.
13. **Run 13** — [live] the rehearsal by hand on real twins: ok, the failing stage and its reproduce commands, the interrupt, in flight, a client gone, the reclaim, the deadline (T041). Stop and report.
14. **Run 14** — fylgja-step: the checks skill loaded, the shared glue, the query, the check, its registration and root test, and the checks' tier-2 test written (T042–T045). Only these; stop and report.
15. **Run 15** — fylgja-twin: the check, its registration and timeout test, the tier-2 test extended, the C4 model, gated (T046–T049). Only these; stop and report.
16. **Run 16** — [live] the checks inside Infrahub against the server on the bridge, then the contract tier whole (T050). Stop and report.
17. **Run 17** — tier 3's case 9, the README's proposed-change walk-through and the contracts' 015 sections (T051–T053). Only these; stop and report.
18. **Run 18** — [operator] the push to origin's main and the checks imported on the host's registration (T054). Stop and report.
19. **Run 19** — [live] tier 3 whole and narrowed on a quiet host, then the walk-through followed by hand (T055–T056). Stop and report.
20. **Run 20** — [operator] the comment and the messages read in Infrahub's UI (T057). Stop and report.
21. **Run 21** — the records: architecture, glossary, development.md, verified-facts.md, roadmap, brief, CLAUDE.md, SECURITY.md re-read (T058–T062). Only these; stop and report.
22. **Run 22** — the closing gates and greps (T063). Only this; stop and report.
23. **Run 23** — [operator] the operator's review, commits and the command log (T064). Stop and report.

`converge` follows Run 23.

## Notes

The heading above closes the route: `scripts/converge-loop.sh` reads "Recommended route"
only up to the next heading.

**For `analyze` to settle in the spec**, as the plan flags them: the sixth verdict `error`
and its status (R-07, R-08; FR-002, FR-009, the spec's Key Entities, which list five);
FR-025's reading, where the override names the address and Compose carries the token
(R-17); the check's own deadline inside Infrahub's, with the synchronous interrupt (R-16;
FR-021); and tier 3's ninth case passing only once the checks are on `origin`'s `main` and
imported (R-19, R-21; FR-030, T054). Beside them, the four decision entries (T002–T005).
This file builds the plan's reading of each. A different answer at `analyze` changes the
tasks it names.

Owed from research §4, and where each lands: the override and the server on the bridge
(T036, T037); the checks on `origin`'s `main` (T054); the hand scenarios (T041), with the
UI's rendering (T057); the push refused for `ethernet-1/99` (T041, T055); the decision
entries (T002–T005); `make diagrams` (T017, T022, T030, T049).
